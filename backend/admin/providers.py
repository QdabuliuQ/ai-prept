"""LLM / image provider catalogs for Admin UI (env-masked)."""

from __future__ import annotations

import os
from typing import Any

from config import load_env, parse_api_keys

LLM_PROVIDERS: list[dict[str, Any]] = [
    {
        "id": "deepseek",
        "label": "DeepSeek",
        "tier": "heavy",
        "baseUrl": "https://api.deepseek.com",
        "models": [
            {"id": "deepseek-v4-flash", "label": "deepseek-v4-flash"},
            {"id": "deepseek-v4-pro", "label": "deepseek-v4-pro"},
        ],
        "keyEnvNames": [
            "DEEPSEEK_API_KEYS",
            "DEEPSEEK_API_KEY",
            "LLM_API_KEYS",
            "LLM_API_KEY",
        ],
    },
    {
        "id": "sensenova",
        "label": "商汤 SenseNova",
        "tier": "heavy",
        "baseUrl": "https://token.sensenova.cn/v1",
        "models": [
            # deepseek-v4-flash 在商汤网关上明显快于本校 flash-lite（测 ~1–2s vs ~12–20s）
            {"id": "deepseek-v4-flash", "label": "DeepSeek V4 Flash"},
            {"id": "deepseek-flash", "label": "DeepSeek V4.1 Flash"},
            {
                "id": "sensenova-6.8-flash-lite",
                "label": "SenseNova 6.8 Flash Lite",
            },
            {"id": "sensenova-u1.5-lite", "label": "SenseNova U1.5 Lite"},
            {"id": "glm-5.2", "label": "GLM-5.2"},
            {"id": "kimi-k3", "label": "Kimi K3"},
            # u1.5-fast 当前 chat/completions 返回 model is not found，暂不列出
        ],
        "keyEnvNames": ["SENSENOVA_API_KEYS", "SENSENOVA_API_KEY"],
    },
    {
        "id": "cloudflare",
        "label": "Cloudflare Workers AI",
        "tier": "heavy",
        "baseUrl": "https://api.cloudflare.com/client/v4/accounts",
        "models": [
            {
                "id": "@cf/qwen/qwen3.8-27b",
                "label": "Qwen3.8-27B",
            },
            {
                "id": "@cf/zai-org/glm-4.7-flash",
                "label": "GLM-4.7-Flash（免费档可用）",
            },
            {
                "id": "@cf/qwen/qwen2.5-coder-32b-instruct",
                "label": "qwen2.5-coder-32b（免费档可用）",
            },
            {
                "id": "@cf/google/gemma-4-26b-a4b-it",
                "label": "Gemma 4 26B（免费档可用）",
            },
            {
                "id": "@cf/moonshotai/kimi-k2.7-code",
                "label": "Kimi K2.7 Code（需 Workers Paid）",
            },
        ],
        "keyEnvNames": [
            "CLOUDFLARE_API_TOKENS",
            "CLOUDFLARE_API_TOKEN",
            "CLOUDFLARE_API_KEYS",
            "CLOUDFLARE_API_KEY",
        ],
    },
    {
        "id": "pollinations",
        "label": "Pollinations.ai",
        "tier": "heavy",
        "baseUrl": "https://gen.pollinations.ai/v1",
        "models": [
            {"id": "openai", "label": "openai（默认）"},
            {"id": "openai-fast", "label": "openai-fast"},
        ],
        "keyEnvNames": [
            "POLLINATIONS_API_KEYS",
            "POLLINATIONS_API_KEY",
            "LLM_API_KEYS",
            "LLM_API_KEY",
        ],
    },
    {
        "id": "siliconflow",
        "label": "硅基流动",
        "tier": "light",
        "baseUrl": "https://api.siliconflow.cn/v1",
        "models": [
            {"id": "Qwen/Qwen3-8B", "label": "Qwen3-8B"},
            {"id": "Qwen/Qwen2.5-7B-Instruct", "label": "Qwen2.5-7B-Instruct"},
        ],
        "keyEnvNames": ["SILICONFLOW_API_KEYS", "SILICONFLOW_API_KEY"],
    },
    {
        "id": "modelscope",
        "label": "魔塔社区",
        "tier": "heavy",
        "baseUrl": "https://api-inference.modelscope.cn/v1",
        "models": [
            {
                "id": "deepseek-ai/DeepSeek-V4.1-Flash",
                "label": "DeepSeek-V4.1-Flash",
            },
        ],
        "keyEnvNames": [
            "MODELSCOPE_API_KEYS",
            "MODELSCOPE_API_KEY",
            "MODELSCOPE_API_TOKENS",
            "MODELSCOPE_API_TOKEN",
            "MODELSCOPE_TOKENS",
            "MODELSCOPE_TOKEN",
        ],
    },
    {
        "id": "gemini",
        "label": "Google Gemini",
        "tier": "heavy",
        # OpenAI 兼容：https://ai.google.dev/gemini-api/docs/openai
        "baseUrl": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "models": [
            {
                "id": "gemini-3.8-flash",
                "label": "gemini-3.8-flash",
            },
            {
                "id": "gemini-3.5-flash-lite",
                "label": "gemini-3.5-flash-lite",
            },
            {
                "id": "gemini-3.1-flash",
                "label": "gemini-3.1-flash",
            },
            {
                "id": "gemini-3.1-flash-lite",
                "label": "gemini-3.1-flash-lite",
            },
        ],
        "keyEnvNames": [
            "GEMINI_API_KEYS",
            "GEMINI_API_KEY",
            "GOOGLE_API_KEYS",
            "GOOGLE_API_KEY",
            "GOOGLE_AI_API_KEYS",
            "GOOGLE_AI_API_KEY",
        ],
    },
    {
        "id": "groq",
        "label": "Groq",
        "tier": "heavy",
        # OpenAI 兼容：https://console.groq.com/docs/openai
        "baseUrl": "https://api.groq.com/openai/v1",
        "models": [
            {
                "id": "qwen/qwen3.8-27b",
                "label": "Qwen3.8-27B",
            },
            {
                "id": "llama-3.3-70b-versatile",
                "label": "Llama 3.3 70B",
            },
        ],
        "keyEnvNames": [
            "GROQ_API_KEYS",
            "GROQ_API_KEY",
        ],
    },
    {
        "id": "freeshare",
        "label": "FreeShare",
        "tier": "heavy",
        # OpenAI 兼容：https://freeshare.cc.cd/v1/chat/completions
        "baseUrl": "https://freeshare.cc.cd/v1",
        "models": [
            {
                "id": "agnes-3.0-flash",
                "label": "agnes-3.0-flash",
            },
        ],
        "keyEnvNames": [
            "FREESHARE_API_KEYS",
            "FREESHARE_API_KEY",
        ],
    },
    {
        "id": "workbuddy",
        "label": "WorkBuddy (本机)",
        "tier": "heavy",
        # OpenAI 兼容：workbuddy-bridge → CodeBuddy CLI
        "baseUrl": "http://127.0.0.1:3000/v1",
        "models": [
            {"id": "workbuddy", "label": "workbuddy（默认）"},
            {"id": "hy4-preview-f", "label": "hy4-preview-f"},
            {"id": "hy3", "label": "hy3"},
            {"id": "hy3-x", "label": "hy3-x"},
            {"id": "space-bunny", "label": "space-bunny"},
            {"id": "deepseek-v4.1-flash", "label": "deepseek-v4.1-flash"},
            {"id": "deepseek-v4-pro", "label": "deepseek-v4-pro"},
            {"id": "glm-5.3", "label": "glm-5.3"},
            {"id": "glm-5.3-flash", "label": "glm-5.3-flash"},
            {"id": "glm-5.2", "label": "glm-5.2"},
            {"id": "glm-5.1", "label": "glm-5.1"},
            {"id": "glm-5v-turbo", "label": "glm-5v-turbo"},
            {"id": "minimax-m3", "label": "minimax-m3"},
            {"id": "minimax-m2.7", "label": "minimax-m2.7"},
            {"id": "kimi-k3-1", "label": "kimi-k3-1"},
            {"id": "kimi-k2.8-preview", "label": "kimi-k2.8-preview"},
            {"id": "kimi-k2.7", "label": "kimi-k2.7"},
            {"id": "kimi-k2.6", "label": "kimi-k2.6"},
        ],
        "keyEnvNames": [
            "WORKBUDDY_API_KEYS",
            "WORKBUDDY_API_KEY",
            "LLM_API_KEYS",
            "LLM_API_KEY",
        ],
    },
]

IMAGE_PROVIDERS: list[dict[str, Any]] = [
    {
        "id": "openai",
        "label": "OpenAI Images 兼容",
        "baseUrl": os.environ.get("IMAGE_API_BASE_URL") or "",
        "models": [
            {"id": "nano-banana-fast", "label": "nano-banana-fast"},
            {"id": "nano-banana", "label": "nano-banana"},
        ],
        "keyEnvNames": ["IMAGE_API_KEYS", "IMAGE_API_KEY"],
        "transport": "openai-images",
    },
    {
        "id": "siliconflow",
        "label": "硅基流动 文生图",
        "baseUrl": "https://api.siliconflow.cn/v1",
        "models": [
            {
                "id": "Tongyi-MAI/Z-Image-Turbo",
                "label": "Z-Image-Turbo（通义）",
            },
            {
                "id": "Tongyi-MAI/Z-Image",
                "label": "Z-Image（通义）",
            },
            {
                "id": "Kwai-Kolors/Kolors",
                "label": "Kolors",
            },
            {
                "id": "Qwen/Qwen-Image",
                "label": "Qwen-Image",
            },
            {
                "id": "baidu/ERNIE-Image-Turbo",
                "label": "ERNIE-Image-Turbo",
            },
        ],
        "keyEnvNames": [
            "SILICONFLOW_API_KEYS",
            "SILICONFLOW_API_KEY",
        ],
        "transport": "siliconflow-images",
    },
    {
        "id": "pollinations",
        "label": "Pollinations 文生图",
        "baseUrl": "https://gen.pollinations.ai",
        "models": [
            {"id": "flux", "label": "flux"},
            {"id": "turbo", "label": "turbo"},
        ],
        "keyEnvNames": [
            "POLLINATIONS_API_KEYS",
            "POLLINATIONS_API_KEY",
            "IMAGE_API_KEYS",
            "IMAGE_API_KEY",
        ],
        "transport": "pollinations-get",
    },
]


def _env(name: str) -> str:
    load_env()
    return os.environ.get(name, "").strip()


def _keys_for(names: list[str]) -> tuple[str, ...]:
    return parse_api_keys(*(_env(n) or None for n in names))


def _mask(key: str) -> str:
    if len(key) <= 8:
        return "***"
    return f"{key[:4]}…{key[-4:]}"


def list_llm_providers_public() -> list[dict[str, Any]]:
    out = []
    for p in LLM_PROVIDERS:
        keys = _keys_for(p["keyEnvNames"])
        row = dict(p)
        if p["id"] == "cloudflare":
            account = _env("CLOUDFLARE_ACCOUNT_ID")
            if account:
                row["baseUrl"] = f"https://api.cloudflare.com/client/v4/accounts/{account}/ai/run"
        if p["id"] == "gemini":
            row["baseUrl"] = (
                _env("GEMINI_BASE_URL")
                or _env("GOOGLE_AI_BASE_URL")
                or row["baseUrl"]
            )
        if p["id"] == "groq":
            row["baseUrl"] = _env("GROQ_BASE_URL") or row["baseUrl"]
        if p["id"] == "freeshare":
            row["baseUrl"] = _env("FREESHARE_BASE_URL") or row["baseUrl"]
        if p["id"] == "workbuddy":
            row["baseUrl"] = _env("WORKBUDDY_BASE_URL") or row["baseUrl"]
        row["configured"] = bool(keys)
        row["keyCount"] = len(keys)
        row["keyHint"] = _mask(keys[0]) if keys else None
        out.append(row)
    return out


def list_image_providers_public() -> list[dict[str, Any]]:
    out = []
    for p in IMAGE_PROVIDERS:
        keys = _keys_for(p["keyEnvNames"])
        row = dict(p)
        if p["id"] == "openai":
            row["baseUrl"] = _env("IMAGE_API_BASE_URL") or row.get("baseUrl") or ""
        row["configured"] = bool(keys) if p["id"] != "openai" else bool(keys and row["baseUrl"])
        if p["id"] == "openai" and not row["baseUrl"]:
            # still show configured if keys exist (server may inject)
            row["configured"] = bool(keys)
        if p["id"] == "siliconflow":
            row["configured"] = bool(keys)
        row["keyCount"] = len(keys)
        row["keyHint"] = _mask(keys[0]) if keys else None
        out.append(row)
    return out


def resolve_llm_selection(
    provider: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    load_env()
    pid = (provider or "deepseek").strip() or "deepseek"
    found = next((p for p in LLM_PROVIDERS if p["id"] == pid), LLM_PROVIDERS[0])
    models = found["models"]
    mid = (model or "").strip() or models[0]["id"]
    if not any(m["id"] == mid for m in models):
        mid = models[0]["id"]
    keys = _keys_for(found["keyEnvNames"])
    if not keys and pid == "deepseek":
        keys = parse_api_keys(_env("LLM_API_KEY") or None, _env("LLM_API_KEYS") or None)
    base = found["baseUrl"]
    if pid == "cloudflare":
        account = _env("CLOUDFLARE_ACCOUNT_ID")
        if account:
            base = f"https://api.cloudflare.com/client/v4/accounts/{account}/ai/run"
    if pid == "gemini":
        base = _env("GEMINI_BASE_URL") or _env("GOOGLE_AI_BASE_URL") or base
    if pid == "groq":
        base = _env("GROQ_BASE_URL") or base
    if pid == "freeshare":
        base = _env("FREESHARE_BASE_URL") or base
    if pid == "workbuddy":
        base = _env("WORKBUDDY_BASE_URL") or base
    return {
        "provider": found["id"],
        "model": mid,
        "label": f"{found['label']} · {mid}",
        "baseUrl": base,
        "keys": keys,
    }


def resolve_image_selection(
    provider: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    load_env()
    pid = (provider or "openai").strip() or "openai"
    found = next((p for p in IMAGE_PROVIDERS if p["id"] == pid), IMAGE_PROVIDERS[0])
    models = found["models"]
    mid = (model or "").strip() or (_env("IMAGE_MODEL") if pid == "openai" else models[0]["id"])
    mid = mid or models[0]["id"]
    if not any(m["id"] == mid for m in models):
        mid = models[0]["id"]
    keys = _keys_for(found["keyEnvNames"])
    base = found["baseUrl"]
    if pid == "openai":
        base = _env("IMAGE_API_BASE_URL") or base
    return {
        "provider": found["id"],
        "model": mid,
        "label": f"{found['label']} · {mid}",
        "baseUrl": base,
        "keys": keys,
        "transport": found["transport"],
    }


def llm_env_for_dual(selection: dict[str, Any]) -> dict[str, str]:
    keys = selection.get("keys") or ()
    if not keys:
        raise RuntimeError("未配置 LLM API Key")
    env = {
        "LLM_API_KEY": keys[0],
        "LLM_API_KEYS": ",".join(keys),
        "LLM_BASE_URL": selection["baseUrl"],
        "LLM_MODEL": selection["model"],
    }
    if selection["provider"] == "deepseek":
        env["DEEPSEEK_API_KEY"] = keys[0]
        env["DEEPSEEK_API_KEYS"] = ",".join(keys)
    if selection["provider"] == "modelscope":
        env["MODELSCOPE_API_KEY"] = keys[0]
        env["MODELSCOPE_API_KEYS"] = ",".join(keys)
        env["MODELSCOPE_API_TOKEN"] = keys[0]
        env["MODELSCOPE_TOKEN"] = keys[0]
    if selection["provider"] == "gemini":
        env["GEMINI_API_KEY"] = keys[0]
        env["GEMINI_API_KEYS"] = ",".join(keys)
        env["GOOGLE_API_KEY"] = keys[0]
        env["GOOGLE_AI_API_KEY"] = keys[0]
    if selection["provider"] == "groq":
        env["GROQ_API_KEY"] = keys[0]
        env["GROQ_API_KEYS"] = ",".join(keys)
    if selection["provider"] == "freeshare":
        env["FREESHARE_API_KEY"] = keys[0]
        env["FREESHARE_API_KEYS"] = ",".join(keys)
    if selection["provider"] == "workbuddy":
        env["WORKBUDDY_API_KEY"] = keys[0]
        env["WORKBUDDY_API_KEYS"] = ",".join(keys)
        # CodeBuddy / 本机桥偏慢，尤其改页+生图
        env.setdefault("LLM_TIMEOUT", "360")
        env.setdefault("LLM_ATTEMPTS", "2")
    return env


def list_gallery_model_catalog() -> dict[str, Any]:
    """首页公开模型目录（不含 key 指纹）。"""
    llm_out: list[dict[str, Any]] = []
    for p in list_llm_providers_public():
        llm_out.append(
            {
                "id": p["id"],
                "label": p["label"],
                "tier": p.get("tier"),
                "models": list(p.get("models") or []),
                "configured": bool(p.get("configured")),
            }
        )
    image_out: list[dict[str, Any]] = []
    for p in list_image_providers_public():
        image_out.append(
            {
                "id": p["id"],
                "label": p["label"],
                "models": list(p.get("models") or []),
                "configured": bool(p.get("configured")),
            }
        )

    def _pick_llm() -> tuple[str, str]:
        # 优先 Groq（新接入），再 Gemini，再任意已配置
        for prefer in ("groq", "gemini", "deepseek"):
            hit = next((x for x in llm_out if x["id"] == prefer and x["configured"]), None)
            if hit and hit["models"]:
                return hit["id"], str(hit["models"][0]["id"])
        hit = next((x for x in llm_out if x["configured"] and x["models"]), None)
        if hit:
            return hit["id"], str(hit["models"][0]["id"])
        first = llm_out[0] if llm_out else None
        if first and first["models"]:
            return first["id"], str(first["models"][0]["id"])
        return "gemini", "gemini-3.8-flash"

    def _pick_image() -> tuple[str, str]:
        for prefer in ("siliconflow", "openai", "pollinations"):
            hit = next(
                (x for x in image_out if x["id"] == prefer and x["configured"]), None
            )
            if hit and hit["models"]:
                # 硅基默认 Kolors（与首页历史行为一致）
                if hit["id"] == "siliconflow":
                    for m in hit["models"]:
                        if m.get("id") == "Kwai-Kolors/Kolors":
                            return hit["id"], "Kwai-Kolors/Kolors"
                return hit["id"], str(hit["models"][0]["id"])
        hit = next((x for x in image_out if x["configured"] and x["models"]), None)
        if hit:
            return hit["id"], str(hit["models"][0]["id"])
        return "siliconflow", "Kwai-Kolors/Kolors"

    llm_p, llm_m = _pick_llm()
    img_p, img_m = _pick_image()
    return {
        "llmProviders": llm_out,
        "imageProviders": image_out,
        "defaults": {
            "llmProvider": llm_p,
            "llmModel": llm_m,
            "imageProvider": img_p,
            "imageModel": img_m,
        },
    }


def image_env_for_selection(selection: dict[str, Any]) -> dict[str, str]:
    keys = selection.get("keys") or ()
    provider = selection.get("provider") or "openai"
    if provider == "openai" and not keys:
        raise RuntimeError("未配置 IMAGE_API_KEY")
    if provider == "openai" and not selection.get("baseUrl"):
        raise RuntimeError("未配置 IMAGE_API_BASE_URL")
    if provider == "siliconflow" and not keys:
        raise RuntimeError("未配置 SILICONFLOW_API_KEY")
    env = {
        "IMAGE_API_PROVIDER": provider,
        "IMAGE_MODEL": selection["model"],
        "IMAGE_TRANSPORT": str(selection.get("transport") or ""),
    }
    if keys:
        env["IMAGE_API_KEY"] = keys[0]
        env["IMAGE_API_KEYS"] = ",".join(keys)
    if selection.get("baseUrl"):
        env["IMAGE_API_BASE_URL"] = selection["baseUrl"]
    if provider == "siliconflow" and keys:
        env["SILICONFLOW_API_KEY"] = keys[0]
        env["SILICONFLOW_API_KEYS"] = ",".join(keys)
    if provider == "pollinations" and keys:
        env["POLLINATIONS_API_KEY"] = keys[0]
        env["POLLINATIONS_API_KEYS"] = ",".join(keys)
    return env
