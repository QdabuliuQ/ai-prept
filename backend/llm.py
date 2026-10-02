from __future__ import annotations

import json
import os
import re
import threading
import time
from typing import Any, Callable

import httpx
from openai import OpenAI

from config import LlmConfig


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
    messages: list[dict[str, str]],
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


def _thinking_type_extra(model: str) -> dict[str, Any] | None:
    """OpenAI 兼容 `thinking.type`（DeepSeek / 商汤网关模型）。

    LLM_THINKING：1 → enabled；否则 disabled（默认关）。
    商汤 flash-lite / glm 等默认会开思考，短回答也会拖到数十秒且吃光
    max_tokens（只剩 reasoning、content 为空）。
    """
    m = (model or "").lower()
    base = (os.environ.get("LLM_BASE_URL") or "").lower()
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


def _chat_extra_body(model: str) -> dict[str, Any] | None:
    extra: dict[str, Any] = {}
    for part in (
        _thinking_type_extra(model),
        _gemini_thinking_extra(model),
        _qwen_thinking_extra(model),
    ):
        if part:
            extra.update(part)
    return extra or None


def _create_chat(
    client: OpenAI,
    *,
    model: str,
    messages: list[dict[str, str]],
    temperature: float,
    json_object: bool,
):
    kwargs: dict[str, Any] = {
        "model": model,
        "temperature": temperature,
        "messages": messages,
    }
    extra = _chat_extra_body(model)
    if extra:
        kwargs["extra_body"] = extra

    def _create(**more: Any):
        return client.chat.completions.create(**kwargs, **more)

    if json_object:
        try:
            return _create(response_format={"type": "json_object"})
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
                return _create()
            raise
    return _create()


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
    messages: list[dict[str, str]],
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
    messages: list[dict[str, str]] | None = None,
) -> list[dict[str, str]]:
    """Build a chat message list; prefer an explicit multi-turn ``messages``."""
    if messages is not None:
        if not messages:
            raise ValueError("messages 不能为空")
        out: list[dict[str, str]] = []
        for item in messages:
            role = str(item.get("role") or "").strip()
            content = str(item.get("content") or "")
            if role not in {"system", "user", "assistant"}:
                raise ValueError(f"不支持的 message role: {role!r}")
            out.append({"role": role, "content": content})
        return out
    if not system and not user:
        raise ValueError("需要传入 system+user 或 messages")
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def chat_json(
    client: OpenAI | None = None,
    *,
    model: str,
    system: str = "",
    user: str = "",
    messages: list[dict[str, str]] | None = None,
    temperature: float = 0.4,
    pool: LlmClientPool | None = None,
) -> dict[str, Any]:
    """Ask model for a single JSON object (compatible with DeepSeek / OpenAI)."""
    messages = _normalize_chat_messages(system=system, user=user, messages=messages)
    cfg = pool.cfg if pool is not None else None

    if cfg is not None and _is_workers_ai_run(cfg):
        content = _run_workers_ai(
            pool=pool,
            client=client,
            cfg=cfg,
            model=model or cfg.model,
            messages=messages,
            temperature=temperature,
        )
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?\s*", "", content, flags=re.I)
            content = re.sub(r"\s*```$", "", content)
        data = json.loads(content.strip() or "{}")
        if not isinstance(data, dict):
            raise ValueError("LLM 返回的 JSON 不是 object")
        return data

    def _once(c: OpenAI) -> dict[str, Any]:
        resp = _create_chat(
            c,
            model=model,
            messages=messages,
            temperature=temperature,
            json_object=True,
        )
        from usage import record_page_usage

        record_page_usage(getattr(resp, "usage", None))
        content = (resp.choices[0].message.content or "{}").strip()
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?\s*", "", content, flags=re.I)
            content = re.sub(r"\s*```$", "", content)
        data = json.loads(content)
        if not isinstance(data, dict):
            raise ValueError("LLM 返回的 JSON 不是 object")
        return data

    return _run_with_pool(pool=pool, client=client, fn=_once)


def chat_text(
    client: OpenAI | None = None,
    *,
    model: str,
    system: str = "",
    user: str = "",
    messages: list[dict[str, str]] | None = None,
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
