"""SCORE_VL helpers — random theme / style intent."""

from __future__ import annotations

import os
import random
import time
from typing import Any

import httpx

from config import load_env


def resolve_score_vl() -> dict[str, str]:
    load_env()
    base = (
        os.environ.get("SCORE_VL_BASE_URL")
        or "https://dashscope.aliyuncs.com/compatible-mode/v1"
    ).rstrip("/")
    model = os.environ.get("SCORE_VL_MODEL") or "qwen-vl-max"
    api_key = (
        os.environ.get("SCORE_VL_API_KEY")
        or os.environ.get("DASHSCOPE_API_KEY")
        or (os.environ.get("SCORE_VL_API_KEYS") or "").split(",")[0].strip()
    )
    if not api_key:
        raise RuntimeError(
            "未配置 SCORE_VL / DashScope Key。请在 .env.local 设置 SCORE_VL_API_KEY 或 DASHSCOPE_API_KEY。"
        )
    return {"baseUrl": base, "model": model, "apiKey": api_key}


def _chat(system: str, user: str, *, temperature: float = 1.2, max_tokens: int = 220) -> dict[str, str]:
    cfg = resolve_score_vl()
    url = f"{cfg['baseUrl']}/chat/completions"
    with httpx.Client(timeout=60.0) as client:
        res = client.post(
            url,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {cfg['apiKey']}",
            },
            json={
                "model": cfg["model"],
                "temperature": temperature,
                "top_p": 0.95,
                "max_tokens": max_tokens,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
        )
        res.raise_for_status()
        data = res.json()
    text = (
        ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    ).strip()
    if text.startswith("```"):
        text = text.replace("```", "").strip()
        if text.lower().startswith("json"):
            text = text[4:].strip()
    text = text.strip().strip('"「『」』')
    return {"text": text, "model": cfg["model"]}


def generate_random_theme_prompt(*, visual_style: str = "") -> dict[str, str]:
    salt = f"{int(time.time() * 1000):x}-{random.randrange(1 << 24):x}"
    system = (
        "你是 PPT 主题文案助手。只输出一段中文「主题描述」（1–3 句），不要标题、不要列表、不要引号、不要 markdown。\n"
        "要求：\n"
        "- 自由发明一个具体内容主题\n"
        "- 禁止把视觉风格名或设计隐喻写成主题\n"
        "- 控制在 40–90 个汉字"
    )
    user = f"发散编号：{salt}\n"
    if visual_style.strip():
        user += f"当前选用视觉风格 id（仅供语气参考，勿写入主题文案）：{visual_style.strip()}\n"
    user += "请发明一个具体的 PPT 主题描述。"
    out = _chat(system, user, temperature=1.35)
    return {"prompt": out["text"], "model": out["model"]}


def generate_inspire_brief() -> dict[str, str]:
    """Homepage「发现灵感」：一段可直接当 PPT 创作要求的中文简述（与模板无关）。"""
    salt = f"{int(time.time() * 1000):x}-{random.randrange(1 << 24):x}"
    system = (
        "你是 PPT 需求文案助手。只输出一段中文「PPT 创作要求」（2–4 句），"
        "不要标题、不要列表、不要引号、不要 markdown、不要编号。\n"
        "要求：\n"
        "- 自由发明一个具体、可做的演示主题（业务 / 分享 / 汇报 / 教学等均可）\n"
        "- 写清场景或受众、要讲清的核心信息，可带页数或结构偏好\n"
        "- 语气像用户写给 AI 做网页 PPT 的需求，可直接粘贴使用\n"
        "- 禁止写视觉风格名、配色口号或空洞形容词堆砌\n"
        "- 控制在 60–140 个汉字"
    )
    user = f"发散编号：{salt}\n请写出一段可直接使用的 PPT 创作要求。"
    out = _chat(system, user, temperature=1.3, max_tokens=280)
    return {"prompt": out["text"], "model": out["model"]}


def generate_random_style_intent() -> dict[str, Any]:
    salt = f"{int(time.time() * 1000):x}-{random.randrange(1 << 24):x}"
    system = (
        "你是视觉风格策划。只输出一段中文风格意图（1–2 句），描述色调、材质、气质与禁忌。"
        "不要输出风格 id，不要 markdown。"
    )
    user = f"发散编号：{salt}\n请发明一个适合网页 PPT 的视觉风格意图。"
    out = _chat(system, user, temperature=1.25, max_tokens=180)
    return {
        "mode": "invent",
        "styleIntent": out["text"],
        "model": out["model"],
        "ensureStyle": True,
    }
