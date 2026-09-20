from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


def _repo_root() -> Path:
    # agent/src/webppt_agent/config.py → parents[3] = repo root
    return Path(__file__).resolve().parents[3]


def _agent_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_env() -> None:
    """Load env: repo .env → repo .env.local → agent/.env（后者覆盖前者）。

    进程启动时已存在的变量（shell export / Admin 子进程注入）优先于 dotenv 文件，
    否则 agent/.env 会盖掉按任务切换的 LLM_BASE_URL / LLM_MODEL / API Key。
    """
    pinned = dict(os.environ)
    root = _repo_root()
    agent = _agent_root()
    for path, override in (
        (root / ".env", False),
        (root / ".env.local", True),
        (agent / ".env", True),
    ):
        if path.is_file():
            load_dotenv(path, override=override)
    os.environ.update(pinned)


def parse_api_keys(*raw_values: str | None) -> tuple[str, ...]:
    """解析多 key：支持逗号 / 分号 / 换行；去重保序。"""
    seen: set[str] = set()
    out: list[str] = []
    for raw in raw_values:
        if not raw:
            continue
        for part in raw.replace(";", ",").replace("\n", ",").split(","):
            key = part.strip()
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(key)
    return tuple(out)


@dataclass(frozen=True)
class LlmConfig:
    api_keys: tuple[str, ...]
    base_url: str
    model: str
    # 单次 HTTP 超时（秒）；幻灯片 HTML 较长，默认 180
    timeout_s: float = 180.0
    # OpenAI SDK 内置重试（不含换 key）
    max_retries: int = 1
    # 应用层尝试次数（超时/限流/连接失败会换 key 并退避）
    attempts: int = 3

    @property
    def api_key(self) -> str:
        """兼容旧代码：返回第一个 key。"""
        return self.api_keys[0]


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _env_int(name: str, default: int, *, lo: int = 0, hi: int = 20) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(lo, min(hi, value))


def llm_config() -> LlmConfig:
    """主力模型：Theme / Slide HTML（默认 DeepSeek）。支持 LLM_API_KEYS 多 key 轮询。"""
    # 已配置 LLM_* 时不再合并 OPENAI_API_KEY，避免 IDE/shell 里过期兜底 key 污染轮询池。
    dedicated = parse_api_keys(
        os.environ.get("LLM_API_KEYS"),
        os.environ.get("LLM_API_KEY"),
    )
    keys = dedicated or parse_api_keys(os.environ.get("OPENAI_API_KEY"))
    base = (
        os.environ.get("LLM_BASE_URL")
        or os.environ.get("OPENAI_BASE_URL")
        or "https://api.deepseek.com"
    ).strip()
    model = (
        os.environ.get("LLM_MODEL")
        or os.environ.get("OPENAI_MODEL")
        or "deepseek-chat"
    ).strip()
    if not keys:
        raise RuntimeError(
            "缺少 LLM_API_KEY / LLM_API_KEYS（或 OPENAI_API_KEY）。"
            "请在仓库根 .env.local 或 agent/.env 配置，或用 --mock。"
        )
    return LlmConfig(
        api_keys=keys,
        base_url=base.rstrip("/"),
        model=model,
        timeout_s=_env_float("LLM_TIMEOUT", 180.0),
        max_retries=_env_int("LLM_SDK_RETRIES", 1, lo=0, hi=5),
        attempts=_env_int("LLM_ATTEMPTS", 3, lo=1, hi=12),
    )


def _truthy(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def llm_light_config() -> LlmConfig:
    """轻量模型：Plan JSON 等短任务。

    解析顺序：
    1. LLM_LIGHT_SAME=1 → 与主力相同
    2. LLM_LIGHT_* 显式配置
    3. 有 DeepSeek Key（DEEPSEEK_* / 官方）→ deepseek-v4-flash
    4. 有 SENSENOVA_* → 商汤
    5. 有 SILICONFLOW_* → 硅基 Qwen3-8B
    6. 否则回退主力
    """
    if _truthy("LLM_LIGHT_SAME"):
        return llm_config()

    light_keys = parse_api_keys(
        os.environ.get("LLM_LIGHT_API_KEYS"),
        os.environ.get("LLM_LIGHT_API_KEY"),
    )
    ds_keys = parse_api_keys(
        os.environ.get("DEEPSEEK_API_KEYS"),
        os.environ.get("DEEPSEEK_API_KEY"),
    )
    # 仅当 LLM_* 仍指向官方 DeepSeek 时，才把 LLM_API_KEY 当作 Plan Key
    # （Admin 切到商汤后会注入 LLM_* = SenseNova，不能误用）。
    llm_base = (
        os.environ.get("LLM_BASE_URL") or os.environ.get("OPENAI_BASE_URL") or ""
    ).strip().lower()
    llm_is_deepseek = "deepseek.com" in llm_base or (
        not llm_base and not (os.environ.get("SENSENOVA_API_KEY") or "").strip()
    )
    if llm_is_deepseek and not ds_keys:
        ds_keys = parse_api_keys(
            os.environ.get("LLM_API_KEYS"),
            os.environ.get("LLM_API_KEY"),
        )
    sn_keys = parse_api_keys(
        os.environ.get("SENSENOVA_API_KEYS"),
        os.environ.get("SENSENOVA_API_KEY"),
    )
    sf_keys = parse_api_keys(
        os.environ.get("SILICONFLOW_API_KEYS"),
        os.environ.get("SILICONFLOW_API_KEY"),
    )
    base = (os.environ.get("LLM_LIGHT_BASE_URL") or "").strip()
    model = (os.environ.get("LLM_LIGHT_MODEL") or "").strip()

    if light_keys and (base or model):
        return LlmConfig(
            api_keys=light_keys,
            base_url=(base or "https://api.deepseek.com").rstrip("/"),
            model=model or "deepseek-v4-flash",
            timeout_s=_env_float("LLM_LIGHT_TIMEOUT", 180.0),
            max_retries=_env_int("LLM_SDK_RETRIES", 1, lo=0, hi=5),
            attempts=_env_int("LLM_ATTEMPTS", 3, lo=1, hi=12),
        )

    # Plan 默认 DeepSeek 官方
    if ds_keys and _truthy("LLM_LIGHT_ENABLED", default=True):
        return LlmConfig(
            api_keys=ds_keys,
            base_url=(base or "https://api.deepseek.com").rstrip("/"),
            model=model or "deepseek-v4-flash",
            timeout_s=_env_float("LLM_LIGHT_TIMEOUT", 180.0),
            max_retries=_env_int("LLM_SDK_RETRIES", 1, lo=0, hi=5),
            attempts=_env_int("LLM_ATTEMPTS", 3, lo=1, hi=12),
        )

    if sn_keys and _truthy("LLM_LIGHT_ENABLED", default=True):
        sn_base = (
            base
            or (os.environ.get("SENSENOVA_BASE_URL") or "").strip()
            or "https://token.sensenova.cn/v1"
        )
        return LlmConfig(
            api_keys=sn_keys,
            base_url=sn_base.rstrip("/"),
            model=model or "deepseek-v4-flash",
            timeout_s=_env_float("LLM_LIGHT_TIMEOUT", 180.0),
            max_retries=_env_int("LLM_SDK_RETRIES", 1, lo=0, hi=5),
            attempts=_env_int("LLM_ATTEMPTS", 3, lo=1, hi=12),
        )

    if sf_keys and _truthy("LLM_LIGHT_ENABLED", default=True):
        return LlmConfig(
            api_keys=sf_keys,
            base_url=(base or "https://api.siliconflow.cn/v1").rstrip("/"),
            model=model or "Qwen/Qwen3-8B",
            timeout_s=_env_float("LLM_LIGHT_TIMEOUT", 90.0),
            max_retries=_env_int("LLM_SDK_RETRIES", 1, lo=0, hi=5),
            attempts=_env_int("LLM_ATTEMPTS", 3, lo=1, hi=12),
        )

    if light_keys:
        return LlmConfig(
            api_keys=light_keys,
            base_url=(base or "https://api.deepseek.com").rstrip("/"),
            model=model or "deepseek-v4-flash",
            timeout_s=_env_float("LLM_LIGHT_TIMEOUT", 180.0),
            max_retries=_env_int("LLM_SDK_RETRIES", 1, lo=0, hi=5),
            attempts=_env_int("LLM_ATTEMPTS", 3, lo=1, hi=12),
        )

    return llm_config()


def default_output_root() -> Path:
    """模板直接写到仓库根下 agent-output/<id>/。"""
    return _repo_root() / "agent-output"


def is_mock() -> bool:
    return os.environ.get("AGENT_MOCK", "").strip() in {"1", "true", "TRUE", "yes"}
