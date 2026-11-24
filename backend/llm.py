from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

import httpx
from openai import OpenAI

from config import LlmConfig

logger = logging.getLogger(__name__)


def _http_timeout(total_s: float) -> httpx.Timeout:
    """硬超时：避免半开连接一直挂着（float 总超时在部分网关下不生效）。"""
    total = max(5.0, float(total_s))
    connect = min(20.0, total)
    return httpx.Timeout(total, connect=connect, write=min(60.0, total), pool=connect)


def make_client(cfg: LlmConfig) -> OpenAI:
    """单 client（取第一个 key），供 doctor / 简单探测。"""
    return OpenAI(
        api_key=cfg.api_key,
        base_url=cfg.base_url,
        timeout=_http_timeout(cfg.timeout_s),
        max_retries=cfg.max_retries,
    )


class LlmClientPool:
    """多 API Key 轮询；线程安全。"""

    def __init__(self, cfg: LlmConfig):
        if not cfg.api_keys:
            raise ValueError("LlmConfig.api_keys 为空")
        self.cfg = cfg
        timeout = _http_timeout(cfg.timeout_s)
        self._clients = [
            OpenAI(
                api_key=key,
                base_url=cfg.base_url,
                timeout=timeout,
                max_retries=cfg.max_retries,
            )
            for key in cfg.api_keys
        ]
        self._keys = list(cfg.api_keys)
        self._i = 0
        self._lock = threading.Lock()

    @property
    def model(self) -> str:
        return self.cfg.model

    @property
    def attempts(self) -> int:
        return self.cfg.attempts

    def __len__(self) -> int:
        return len(self._clients)

    def next(self) -> OpenAI:
        with self._lock:
            client = self._clients[self._i % len(self._clients)]
            self._i += 1
            return client

    def next_key(self) -> str:
        with self._lock:
            key = self._keys[self._i % len(self._keys)]
            self._i += 1
            return key


def make_client_pool(cfg: LlmConfig) -> LlmClientPool:
    return LlmClientPool(cfg)


def _is_workers_ai_run(cfg: LlmConfig) -> bool:
    """直连 Workers AI /ai/run/@cf/...，绕过 AI Gateway 统一计费。"""
    mode = (os.environ.get("CLOUDFLARE_AI_MODE") or "").strip().lower()
    if mode in {"v1", "openai", "gateway"}:
        return False
    base = (cfg.base_url or "").lower()
    model = (cfg.model or "").strip()
    if "/ai/run" in base:
        return True
    if model.startswith("@cf/") and "api.cloudflare.com" in base:
        return True
    if mode == "run" and "api.cloudflare.com" in base:
        return True
    return False


def _workers_ai_run_url(cfg: LlmConfig, model: str) -> str:
    base = (cfg.base_url or "").rstrip("/")
    model_path = model.strip().lstrip("/")
    if "/ai/run" in base:
        return f"{base}/{model_path}"
    account = (os.environ.get("CLOUDFLARE_ACCOUNT_ID") or "").strip()
    if not account:
        m = re.search(r"/accounts/([^/]+)/", base)
        if m:
            account = m.group(1)
    if not account:
        raise RuntimeError(
            "Cloudflare Workers AI 需要 CLOUDFLARE_ACCOUNT_ID，"
            "或 LLM_BASE_URL=.../accounts/{id}/ai/run"
        )
    return (
        f"https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/{model_path}"
    )


def _extract_workers_ai_text(data: dict[str, Any]) -> str:
    if not data.get("success", True) and data.get("errors"):
        errs = data["errors"]
        raise RuntimeError(f"Workers AI 错误: {errs}")

    def _from_choices(obj: Any) -> str | None:
        if not isinstance(obj, dict):
            return None
        choices = obj.get("choices")
        if not isinstance(choices, list) or not choices:
            return None
        msg = (choices[0] or {}).get("message") or {}
        content = msg.get("content") if isinstance(msg, dict) else None
        if isinstance(content, str) and content.strip():
            return content
        # 部分模型把文本放在 delta / text
        text = (choices[0] or {}).get("text")
        if isinstance(text, str) and text.strip():
            return text
        return None

    # OpenAI 兼容：顶层 choices
    top = _from_choices(data)
    if top is not None:
        return top

    result = data.get("result")
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        # 新格式：result 内嵌 chat.completion（glm / kimi 等）
        nested = _from_choices(result)
        if nested is not None:
            return nested
        if isinstance(result.get("response"), str):
            return result["response"]
        msg = result.get("message")
        if isinstance(msg, dict) and isinstance(msg.get("content"), str):
            return msg["content"]
        if isinstance(result.get("content"), str):
            return result["content"]
    raise RuntimeError(f"Workers AI 无法解析响应: {str(data)[:400]}")


def _workers_ai_chat(
    *,
    cfg: LlmConfig,
    api_key: str,
    model: str,
    messages: list[dict[str, Any]],
    temperature: float,
) -> str:
    url = _workers_ai_run_url(cfg, model)
    max_tokens = 8192
    raw_max = os.environ.get("LLM_MAX_TOKENS", "").strip()
    if raw_max:
        try:
            max_tokens = max(256, min(int(raw_max), 32768))
        except ValueError:
            pass
    payload: dict[str, Any] = {
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    with httpx.Client(timeout=_http_timeout(cfg.timeout_s)) as http:
        resp = http.post(
            url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        try:
            data = resp.json()
        except Exception:
            data = {"raw": resp.text[:500]}
        if resp.status_code >= 400:
            raise RuntimeError(f"Workers AI HTTP {resp.status_code}: {data}")
        if not isinstance(data, dict):
            raise RuntimeError(f"Workers AI 响应非 JSON object: {data!r}")
        return _extract_workers_ai_text(data).strip()


def _is_rate_limit_error(exc: BaseException) -> bool:
    name = type(exc).__name__.lower()
    text = str(exc).lower()
    if "ratelimit" in name or "rate_limit" in name:
        return True
    return any(
        token in text
        for token in (
            "429",
            "rate limit",
            "rate_limit",
            "too many requests",
            "quota",
            "overloaded",
            "tpm",
            "rpm",
        )
    )


def _is_timeout_error(exc: BaseException) -> bool:
    name = type(exc).__name__.lower()
    text = str(exc).lower()
    if "timeout" in name or "timedout" in name:
        return True
    return any(
        token in text
        for token in (
            "timed out",
            "timeout",
            "deadline exceeded",
            "read timeout",
            "connect timeout",
            "write timeout",
        )
    )


def _is_connection_error(exc: BaseException) -> bool:
    name = type(exc).__name__.lower()
    text = str(exc).lower()
    if "connection" in name or "connecterror" in name:
        return True
    return any(
        token in text
        for token in (
            "connection reset",
            "connection aborted",
            "connection refused",
            "network is unreachable",
            "temporarily unavailable",
            "remoteprotocolerror",
            "server disconnected",
            "broken pipe",
        )
    )


def _is_server_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    return any(
        token in text
        for token in (
            " 500",
            " 502",
            " 503",
            " 504",
            "internal server error",
            "bad gateway",
            "service unavailable",
            "gateway timeout",
        )
    )


def _is_transient_error(exc: BaseException) -> bool:
    return (
        _is_rate_limit_error(exc)
        or _is_timeout_error(exc)
        or _is_connection_error(exc)
        or _is_server_error(exc)
    )


def _backoff_seconds(attempt: int) -> float:
    return min(8.0, float(2 ** max(0, attempt)))


def _llm_thinking_on() -> bool:
    """Admin「LLM 思考模式」/ 环境变量 LLM_THINKING；默认关。"""
    raw = (os.environ.get("LLM_THINKING") or "0").strip().lower()
    return raw in {"1", "true", "yes", "on", "enabled"}


def _on_custom_gateway(base: str) -> bool:
    """当前 base_url 是否就是 Admin「Custom」那个 OpenAI 兼容网关。

    自定义网关普遍不认 `thinking` / `reasoning_effort` 一类扩展参数，
    发了就整条请求 400（Unsupported parameter: thinking）。既然地址由
    CUSTOM_LLM_BASE_URL 决定，命中时直接不发，省掉一次必然失败的往返。
    """
    custom = (os.environ.get("CUSTOM_LLM_BASE_URL") or "").strip().lower()
    if not custom:
        return False
    return base.rstrip("/") == custom.rstrip("/")


def _thinking_type_extra(model: str) -> dict[str, Any] | None:
    """OpenAI 兼容 `thinking.type`（DeepSeek / 商汤网关模型）。

    LLM_THINKING：1 → enabled；否则 disabled（默认关）。
    商汤 flash-lite / glm 等默认会开思考，短回答也会拖到数十秒且吃光
    max_tokens（只剩 reasoning、content 为空）。
    """
    m = (model or "").lower()
    base = (os.environ.get("LLM_BASE_URL") or "").lower()
    if _on_custom_gateway(base):
        return None
    on_sensenova = "sensenova.cn" in base
    if not (
        "deepseek" in m
        or m.startswith("sensenova")
        or (on_sensenova and m.startswith("glm"))
        or (on_sensenova and m.startswith("kimi"))
    ):
        return None
    mode = "enabled" if _llm_thinking_on() else "disabled"
    return {"thinking": {"type": mode}}


def _gemini_thinking_extra(model: str) -> dict[str, Any] | None:
    """Gemini 3.x：OpenAI 兼容层用 reasoning_effort → thinking_level。

    LLM_THINKING=1 → high；关 → minimal（3.7/3.8 Flash 等不支持则 low）。
    Gemini 3 无法完全关闭思考；不传 include_thoughts，避免摘要污染 SVG/JSON。
    """
    m = (model or "").lower()
    if "gemini" not in m:
        return None
    if _llm_thinking_on():
        effort = "high"
    elif any(
        tok in m
        for tok in ("3.8-flash", "3.7-flash", "3.1-pro", "gemini-3-pro")
    ):
        effort = "low"
    else:
        effort = "minimal"
    return {"reasoning_effort": effort}


def _qwen_thinking_extra(model: str) -> dict[str, Any] | None:
    """Qwen3 思考开关。

    - 硅基等：enable_thinking（默认关，非流式 JSON 易卡死）
    - Groq：用 reasoning_effort；默认不传，避免不兼容参数
    """
    m = (model or "").lower()
    if "qwen3" not in m and "qwq" not in m:
        return None
    raw = (
        os.environ.get("LLM_QWEN_THINKING")
        or os.environ.get("LLM_LIGHT_THINKING")
        or "0"
    ).strip().lower()
    enable = raw in {"1", "true", "yes", "on", "enabled"} or _llm_thinking_on()
    base = (os.environ.get("LLM_BASE_URL") or "").lower()
    if "groq.com" in base:
        if enable:
            return {"reasoning_effort": "default"}
        return None
    return {"enable_thinking": enable}


def _agnes_thinking_extra(model: str) -> dict[str, Any] | None:
    """Agnes 2.5 / 3.0：用 OpenAI 兼容的 chat_template_kwargs 开关思考。

    agnes-2.5-flash 默认开思考，短请求也会先吐 reasoning_content 并占
    max_tokens；默认关，LLM_THINKING=1 / Admin 思考开关再打开。
    """
    m = (model or "").lower()
    if not m.startswith("agnes-"):
        return None
    return {"chat_template_kwargs": {"enable_thinking": _llm_thinking_on()}}


def _chat_extra_body(model: str) -> dict[str, Any] | None:
    extra: dict[str, Any] = {}
    for part in (
        _thinking_type_extra(model),
        _gemini_thinking_extra(model),
        _qwen_thinking_extra(model),
        _agnes_thinking_extra(model),
    ):
        if part:
            extra.update(part)
    return extra or None


def _request_max_tokens() -> int | None:
    """单次请求的输出上限。

    默认不传（各厂商默认够用，避免撞上限）。两种情况显式传：

    - 设了 ``LLM_MAX_TOKENS``：全局覆盖；
    - 走 Admin「Custom」网关：未知网关默认上限偏小，模型还会先花
      reasoning tokens，写 plan / SVG 的大块 JSON 会被硬截断成半截
      arguments（表现为工具参数缺字段、校验报"bounds 非法"）。

    24576 是实测出来的安全值：deepseek-v4.1-flash 画一页 SVG 会先花
    约 1.2 万 reasoning tokens，再写 7k 输出；8192 时 finish_reason
    直接是 length、content 为空字符串（表现为每页都 "missing <svg> root"）。
    """
    raw = (os.environ.get("LLM_MAX_TOKENS") or "").strip()
    if raw:
        try:
            return max(256, min(int(raw), 65536))
        except ValueError:
            return None
    base = (os.environ.get("LLM_BASE_URL") or "").lower()
    if _on_custom_gateway(base):
        return 24576
    return None


def _create_chat(
    client: OpenAI,
    *,
    model: str,
    messages: list[dict[str, Any]],
    temperature: float,
    json_object: bool,
):
    kwargs: dict[str, Any] = {
        "model": model,
        "temperature": temperature,
        "messages": messages,
    }
    max_tokens = _request_max_tokens()
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    extra = _chat_extra_body(model)
    if extra:
        kwargs["extra_body"] = extra

    def _create(**more: Any):
        return client.chat.completions.create(**kwargs, **more)

    def _rejects_extra_body(exc: BaseException) -> bool:
        """网关不认 extra_body 里的参数（如自定义网关直接拒绝 thinking）。"""
        if "extra_body" not in kwargs:
            return False
        text = str(exc).lower()
        return any(
            token in text
            for token in (
                "unsupported parameter",
                "unsupported_parameter",
                "unknown parameter",
                "unrecognized request argument",
                "unexpected keyword",
            )
        )

    def _rejects_max_tokens(exc: BaseException) -> bool:
        """网关不认 max_tokens（少见，但不能让它整条 400 掉）。"""
        if "max_tokens" not in kwargs:
            return False
        text = str(exc).lower()
        return "max_tokens" in text or "max_completion_tokens" in text

    def _call(**more: Any):
        # 未知网关可能整体不支持 thinking/reasoning_effort/max_tokens 这类参数，
        # 去掉后重试一次，避免整条生成线在该供应商上直接瘫痪。
        attempt = 0
        while True:
            try:
                return _create(**more)
            except Exception as e:
                attempt += 1
                if attempt > 2:
                    raise
                if _rejects_max_tokens(e):
                    kwargs.pop("max_tokens", None)
                    continue
                if _rejects_extra_body(e):
                    kwargs.pop("extra_body", None)
                    continue
                raise

    if json_object:
        try:
            return _call(response_format={"type": "json_object"})
        except Exception as e:
            text = str(e).lower()
            if any(
                token in text
                for token in (
                    "response_format",
                    "json_object",
                    "unknown parameter",
                    "unsupported",
                    "invalid_request",
                )
            ):
                return _call()
            raise
    return _call()


def _run_with_pool(
    *,
    pool: LlmClientPool | None,
    client: OpenAI | None,
    fn: Callable[[OpenAI], Any],
    attempts: int | None = None,
):
    if pool is None:
        if client is None:
            raise ValueError("需要传入 client 或 pool")
        max_attempts = max(1, attempts or 3)
        last_err: BaseException | None = None
        for i in range(max_attempts):
            try:
                return fn(client)
            except Exception as e:
                last_err = e
                if i + 1 < max_attempts and _is_transient_error(e):
                    time.sleep(_backoff_seconds(i))
                    continue
                raise
        assert last_err is not None
        raise last_err

    max_attempts = max(1, attempts or pool.attempts)
    last_err = None
    for i in range(max_attempts):
        c = pool.next()
        try:
            return fn(c)
        except Exception as e:
            last_err = e
            if i + 1 < max_attempts and _is_transient_error(e):
                time.sleep(_backoff_seconds(i))
                continue
            raise
    assert last_err is not None
    raise last_err


def _run_workers_ai(
    *,
    pool: LlmClientPool | None,
    client: OpenAI | None,
    cfg: LlmConfig,
    model: str,
    messages: list[dict[str, Any]],
    temperature: float,
) -> str:
    max_attempts = max(1, (pool.attempts if pool else None) or cfg.attempts or 3)
    last_err: BaseException | None = None
    for i in range(max_attempts):
        if pool is not None:
            api_key = pool.next_key()
        elif client is not None:
            api_key = client.api_key or cfg.api_key
        else:
            api_key = cfg.api_key
        try:
            return _workers_ai_chat(
                cfg=cfg,
                api_key=api_key,
                model=model,
                messages=messages,
                temperature=temperature,
            )
        except Exception as e:
            last_err = e
            if i + 1 < max_attempts and _is_transient_error(e):
                time.sleep(_backoff_seconds(i))
                continue
            raise
    assert last_err is not None
    raise last_err


def _normalize_chat_messages(
    *,
    system: str = "",
    user: str = "",
    messages: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Build a chat message list, preserving multimodal content blocks."""
    if messages is not None:
        if not messages:
            raise ValueError("messages 不能为空")
        out: list[dict[str, Any]] = []
        for item in messages:
            role = str(item.get("role") or "").strip()
            content = item.get("content")
            if role not in {"system", "user", "assistant"}:
                raise ValueError(f"不支持的 message role: {role!r}")
            if not isinstance(content, (str, list)):
                raise ValueError(
                    f"message content 必须是字符串或内容块数组: {type(content).__name__}"
                )
            out.append({"role": role, "content": content})
        return out
    if not system and not user:
        raise ValueError("需要传入 system+user 或 messages")
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def _strip_code_fence(content: str) -> str:
    text = (content or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _extract_json_object_text(content: str) -> str:
    """Best-effort: fence strip + outermost `{...}` for messy free-tier output."""
    text = _strip_code_fence(content)
    if not text:
        return "{}"
    if text[0] == "{":
        return text
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return text[start : end + 1]
    return text


def _loads_json_object(content: str) -> dict[str, Any]:
    """Parse a JSON object; tolerate fences, prose wrapping, trailing commas."""
    raw = _extract_json_object_text(content)
    candidates = [raw]
    # Trailing commas before } or ] — common with flash models.
    fixed = re.sub(r",\s*([}\]])", r"\1", raw)
    if fixed != raw:
        candidates.append(fixed)
    # Smart / CJK quotes → ASCII (only outside already-valid parse path).
    quoted = (
        raw.replace("\u201c", '"')
        .replace("\u201d", '"')
        .replace("\u2018", "'")
        .replace("\u2019", "'")
        .replace("「", '"')
        .replace("」", '"')
    )
    if quoted != raw:
        candidates.append(quoted)
        candidates.append(re.sub(r",\s*([}\]])", r"\1", quoted))

    last_err: BaseException | None = None
    for cand in candidates:
        try:
            data = json.loads(cand or "{}")
        except json.JSONDecodeError as exc:
            last_err = exc
            continue
        if isinstance(data, dict):
            return data
        last_err = ValueError("LLM 返回的 JSON 不是 object")
    if last_err is not None:
        raise last_err
    raise ValueError("LLM 返回的 JSON 不是 object")


_JSON_RETRY_HINT = (
    "上一次输出不是合法 JSON。请只输出一个 JSON 对象，"
    "不要 Markdown 代码块，不要解释文字；字符串内引号必须转义。"
)


def chat_json(
    client: OpenAI | None = None,
    *,
    model: str,
    system: str = "",
    user: str = "",
    messages: list[dict[str, Any]] | None = None,
    temperature: float = 0.4,
    pool: LlmClientPool | None = None,
) -> dict[str, Any]:
    """Ask model for a single JSON object (compatible with DeepSeek / OpenAI).

    Free / weak models often return fences or lightly broken JSON; we extract,
    lightly repair, and retry once with a strict nudge before failing.
    """
    messages = _normalize_chat_messages(system=system, user=user, messages=messages)
    cfg = pool.cfg if pool is not None else None

    def _parse_or_raise(content: str) -> dict[str, Any]:
        return _loads_json_object(content)

    if cfg is not None and _is_workers_ai_run(cfg):
        content = _run_workers_ai(
            pool=pool,
            client=client,
            cfg=cfg,
            model=model or cfg.model,
            messages=messages,
            temperature=temperature,
        )
        try:
            return _parse_or_raise(content)
        except (json.JSONDecodeError, ValueError):
            repair_msgs: list[dict[str, Any]] = list(messages) + [
                {"role": "assistant", "content": content[:4000]},
                {"role": "user", "content": _JSON_RETRY_HINT},
            ]
            content2 = _run_workers_ai(
                pool=pool,
                client=client,
                cfg=cfg,
                model=model or cfg.model,
                messages=repair_msgs,
                temperature=min(temperature, 0.2),
            )
            return _parse_or_raise(content2)

    def _once(c: OpenAI, msgs: list[dict[str, Any]], temp: float) -> dict[str, Any]:
        resp = _create_chat(
            c,
            model=model,
            messages=msgs,
            temperature=temp,
            json_object=True,
        )
        from usage import record_page_usage

        record_page_usage(getattr(resp, "usage", None))
        content = (resp.choices[0].message.content or "{}").strip()
        try:
            return _parse_or_raise(content)
        except (json.JSONDecodeError, ValueError):
            repair_msgs = list(msgs) + [
                {"role": "assistant", "content": content[:4000]},
                {"role": "user", "content": _JSON_RETRY_HINT},
            ]
            resp2 = _create_chat(
                c,
                model=model,
                messages=repair_msgs,
                temperature=min(temp, 0.2),
                json_object=True,
            )
            record_page_usage(getattr(resp2, "usage", None))
            content2 = (resp2.choices[0].message.content or "{}").strip()
            return _parse_or_raise(content2)

    return _run_with_pool(
        pool=pool,
        client=client,
        fn=lambda c: _once(c, messages, temperature),
    )


def chat_text(
    client: OpenAI | None = None,
    *,
    model: str,
    system: str = "",
    user: str = "",
    messages: list[dict[str, Any]] | None = None,
    temperature: float = 0.4,
    pool: LlmClientPool | None = None,
) -> str:
    """Plain-text chat. Pass ``messages`` for multi-turn (fusion/repair follow-ups)."""
    messages = _normalize_chat_messages(system=system, user=user, messages=messages)
    cfg = pool.cfg if pool is not None else None
    if cfg is not None and _is_workers_ai_run(cfg):
        return _run_workers_ai(
            pool=pool,
            client=client,
            cfg=cfg,
            model=model or cfg.model,
            messages=messages,
            temperature=temperature,
        )

    def _once(c: OpenAI) -> str:
        resp = _create_chat(
            c,
            model=model,
            messages=messages,
            temperature=temperature,
            json_object=False,
        )
        from usage import record_page_usage

        record_page_usage(getattr(resp, "usage", None))
        return (resp.choices[0].message.content or "").strip()

    return _run_with_pool(pool=pool, client=client, fn=_once)


# ---------------------------------------------------------------------------
# Tool calling（Agent 引擎用）：原生 tools + 伪协议双模
# ---------------------------------------------------------------------------
#
# 为什么要双模：本项目跑在多厂商网关上，`tools` 参数兼容性参差；
# 但 Agent Loop 一旦依赖 tool calling，网关不支持就直接瘫痪。
# 因此原生优先，失败即降级为由 JSON 描述的伪协议——后者网关无关，必然可用。
#
# 伪协议的额外好处：A/B 对比时两个引擎可以跑在完全相同的模型与请求参数上。


@dataclass
class ToolCall:
    """一次工具调用请求。"""

    name: str
    args: dict[str, Any] = field(default_factory=dict)
    call_id: str | None = None
    thought: str | None = None


@dataclass
class ToolReply:
    """模型一轮的回复。

    ``mode`` 决定下一轮把工具结果塞回 messages 的形式：
    ``native`` 用 ``role="tool"``，``pseudo`` 用普通 user 消息。
    """

    mode: str
    calls: list[ToolCall] = field(default_factory=list)
    text: str = ""
    finish_reason: str | None = None
    assistant_message: dict[str, Any] = field(default_factory=dict)


_PSEUDO_PROTOCOL = """## 工具调用协议

你没有原生函数调用能力，请用 JSON 描述下一步动作。**每次只输出一个 JSON 对象**，
不要 Markdown 代码块，不要解释文字。

期望 JSON：
{"thought": "一句话说明为什么这么做", "action": {"name": "工具名", "args": {...}}}

可用工具：
{tool_list}

规则：
- args 必须严格符合该工具的参数 schema。
- 想收工时调用 `finish`；它会触发独立复检，不通过会把具体缺陷返回给你。
- 若你认为某缺陷无法修复，仍调用 `finish` 并在 args.reason 中说明。
"""

_TOOL_UNSUPPORTED_TOKENS = (
    "tools",
    "tool_choice",
    "function",
    "unsupported",
    "unknown parameter",
    "invalid_request",
    "not support",
    "does not support",
)


def _tool_specs(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """把内部工具定义翻译为 OpenAI tools 数组（已是该形状则原样返回）。"""
    specs: list[dict[str, Any]] = []
    for tool in tools:
        if "type" in tool and "function" in tool:
            specs.append(tool)
            continue
        specs.append(
            {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "parameters": tool.get("parameters")
                    or {"type": "object", "properties": {}},
                },
            }
        )
    return specs


def _tool_list_for_prompt(tools: list[dict[str, Any]]) -> str:
    """伪协议用的人类可读工具清单（压缩 JSON，避免占太多 token）。"""
    rows: list[str] = []
    for item in _tool_specs(tools):
        fn = item["function"]
        params = json.dumps(fn.get("parameters") or {}, ensure_ascii=False, separators=(",", ":"))
        rows.append(f"- {fn['name']}: {fn.get('description', '')}\n  args: {params}")
    return "\n".join(rows)


def _looks_like_tool_unsupported(exc: BaseException) -> bool:
    text = str(exc).lower()
    # 这些不是"网关不支持 tools"，而是我们把消息历史拼错了
    # （例如 tool_calls 与 role=tool 数量不匹配）。降级只会掩盖真实原因，
    # 所以直接抛出去让上层记录。
    if "tool output" in text or "tool_call_id" in text:
        return False
    return any(token in text for token in _TOOL_UNSUPPORTED_TOKENS)


def _parse_pseudo_reply(content: str) -> ToolReply:
    """把伪协议 JSON 解析为 ToolReply；解析失败视为"无工具调用的文本回复"。"""
    text = (content or "").strip()
    try:
        data = _loads_json_object(text)
    except (json.JSONDecodeError, ValueError):
        return ToolReply(mode="pseudo", text=text)

    action = data.get("action")
    thought = data.get("thought")
    if not isinstance(action, dict):
        return ToolReply(mode="pseudo", text=text)

    name = str(action.get("name") or "").strip()
    if not name:
        return ToolReply(mode="pseudo", text=text)
    raw_args = action.get("args")
    args = raw_args if isinstance(raw_args, dict) else {}
    return ToolReply(
        mode="pseudo",
        calls=[ToolCall(name=name, args=args, thought=thought if isinstance(thought, str) else None)],
        text=text,
        assistant_message={"role": "assistant", "content": text},
    )


def chat_tools(
    client: OpenAI | None = None,
    *,
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    temperature: float = 0.3,
    pool: LlmClientPool | None = None,
    prefer: str = "auto",
) -> ToolReply:
    """一轮带工具的模型调用。

    ``prefer``：

    - ``auto``   先试原生 tool calling，失败（网关不支持）自动降级伪协议
    - ``native`` 只用原生，失败即抛错
    - ``pseudo`` 只用伪协议（A/B 时用来消除协议差异）

    原生模式下 ``messages`` 需由调用方按 OpenAI 格式维护（assistant.tool_calls
    与 role=tool 消息）；伪协议模式下工具结果以普通 user 消息回路。
    两种模式的具体消息拼装见 ``tool_result_messages``。
    """
    mode = (prefer or "auto").strip().lower()
    if mode not in {"auto", "native", "pseudo"}:
        raise ValueError(f"chat_tools prefer 非法：{prefer!r}")

    if mode in {"auto", "native"}:
        try:
            return _chat_tools_native(
                client=client,
                model=model,
                messages=messages,
                tools=tools,
                temperature=temperature,
                pool=pool,
            )
        except Exception as exc:  # noqa: BLE001 - 只在明确不支持时降级
            if mode == "native" or not _looks_like_tool_unsupported(exc):
                raise
            logger.warning("tool calling 不被支持，降级伪协议：%s", exc)

    return _chat_tools_pseudo(
        client=client,
        model=model,
        messages=messages,
        tools=tools,
        temperature=temperature,
        pool=pool,
    )


def _chat_tools_native(
    *,
    client: OpenAI | None,
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    temperature: float,
    pool: LlmClientPool | None,
) -> ToolReply:
    specs = _tool_specs(tools)
    max_tokens = _request_max_tokens()

    def _once(c: OpenAI) -> ToolReply:
        kwargs: dict[str, Any] = {
            "model": model,
            "temperature": temperature,
            "messages": messages,
            "tools": specs,
        }
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        try:
            resp = c.chat.completions.create(**kwargs)
        except Exception as e:
            # 不认 max_tokens 的网关：去掉再试，别让整条 Agent 线 400。
            if max_tokens is None or "max_tokens" not in str(e).lower():
                raise
            kwargs.pop("max_tokens", None)
            resp = c.chat.completions.create(**kwargs)
        from usage import record_page_usage

        record_page_usage(getattr(resp, "usage", None))
        choice = resp.choices[0]
        msg = choice.message
        raw_calls = getattr(msg, "tool_calls", None) or []
        calls: list[ToolCall] = []
        assistant_message: dict[str, Any] = {
            "role": "assistant",
            "content": msg.content or "",
        }
        if raw_calls:
            wire_calls: list[dict[str, Any]] = []
            for item in raw_calls:
                fn = getattr(item, "function", None)
                name = str(getattr(fn, "name", "") or "")
                raw_args = getattr(fn, "arguments", None) or "{}"
                try:
                    parsed = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
                except (json.JSONDecodeError, TypeError, ValueError):
                    parsed = {}
                call_id = getattr(item, "id", None) or f"call_{len(calls)}"
                calls.append(
                    ToolCall(
                        name=name,
                        args=parsed if isinstance(parsed, dict) else {},
                        call_id=call_id,
                    )
                )
                wire_calls.append(
                    {
                        "id": call_id,
                        "type": "function",
                        "function": {"name": name, "arguments": raw_args},
                    }
                )
            # Agent Loop 每轮只执行一个工具，因此历史里只保留第一个 tool_call。
            # 若把模型并行发出的多个 tool_calls 原样留在 assistant 消息里、却只回一条
            # role=tool，下一轮请求会被网关直接拒绝：
            #   400 No tool output found for tool call call_xx
            # 裁剪后数量 1:1 自洽；被裁掉的调用下一轮模型会重新发起。
            if len(wire_calls) > 1:
                logger.info(
                    "模型一次返回 %d 个 tool_calls，仅执行第一个（%s），其余丢弃",
                    len(wire_calls),
                    wire_calls[0]["function"]["name"],
                )
                calls = calls[:1]
                wire_calls = wire_calls[:1]
            assistant_message["tool_calls"] = wire_calls
        return ToolReply(
            mode="native",
            calls=calls,
            text=msg.content or "",
            finish_reason=getattr(choice, "finish_reason", None),
            assistant_message=assistant_message,
        )

    return _run_with_pool(pool=pool, client=client, fn=_once)


def _chat_tools_pseudo(
    *,
    client: OpenAI | None,
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    temperature: float,
    pool: LlmClientPool | None,
) -> ToolReply:
    protocol = _PSEUDO_PROTOCOL.format(tool_list=_tool_list_for_prompt(tools))
    augmented = list(messages)
    if augmented and augmented[0].get("role") == "system":
        augmented[0] = {
            "role": "system",
            "content": f"{augmented[0].get('content') or ''}\n\n{protocol}",
        }
    else:
        augmented.insert(0, {"role": "system", "content": protocol})

    def _once(c: OpenAI) -> ToolReply:
        resp = _create_chat(
            c,
            model=model,
            messages=augmented,
            temperature=temperature,
            json_object=True,
        )
        from usage import record_page_usage

        record_page_usage(getattr(resp, "usage", None))
        content = (resp.choices[0].message.content or "").strip()
        reply = _parse_pseudo_reply(content)
        reply.finish_reason = resp.choices[0].finish_reason
        return reply

    return _run_with_pool(pool=pool, client=client, fn=_once)


def tool_result_messages(
    reply: ToolReply,
    call: ToolCall,
    result: dict[str, Any],
) -> list[dict[str, Any]]:
    """把一次工具执行结果编码为下一轮 messages。

    原生模式用 ``role="tool"``（需要先追加带 tool_calls 的 assistant 消息）；
    伪协议模式用普通 user 消息，因为网关不认识 tool 角色。
    """
    payload = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
    if reply.mode == "native":
        return [
            {
                "role": "tool",
                "tool_call_id": call.call_id or "",
                "content": payload,
            }
        ]
    return [
        {
            "role": "user",
            "content": f"工具 `{call.name}` 的执行结果：\n{payload}\n\n请根据结果继续。",
        }
    ]
