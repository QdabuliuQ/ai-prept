"""Classify editor AI chat intent: rewrite | generate | delete."""

from __future__ import annotations

import re
from typing import Any

from config import is_mock, llm_config, load_env, llm_light_config
from llm import chat_json, make_client_pool

INTENT_REWRITE = "rewrite"
INTENT_GENERATE = "generate"
INTENT_DELETE = "delete"

_DELETE_RE = re.compile(
    r"(删除|删掉|去掉|移除).{0,8}(页|这一页|当前页|第\s*\d+\s*页)|"
    r"\b(delete|remove)\b.{0,12}\bpage\b",
    re.I,
)
_GENERATE_RE = re.compile(
    r"(新增|添加|加一页|加\s*一\s*页|新建一页|插入一页|多一页)|"
    r"\b(add|create|insert|new)\b.{0,12}\bpage\b",
    re.I,
)

SYSTEM_INTENT = """你是 PPT 编辑助手的意图分类器。只输出 JSON 对象：
{"intent":"rewrite"|"generate"|"delete","reason":"一句中文说明"}

含义：
- delete：用户要删除某一页（整页去掉）
- generate：用户要新增一页（插入新 HTML 页）
- rewrite：改当前页或指定页的文案/版式/样式（默认）

不确定时选 rewrite。不要输出其它字段。
"""


def heuristic_intent(issue: str) -> str | None:
    text = (issue or "").strip()
    if not text:
        return None
    if _DELETE_RE.search(text):
        return INTENT_DELETE
    if _GENERATE_RE.search(text):
        return INTENT_GENERATE
    return None


def classify_editor_intent(
    issue: str,
    *,
    page_count: int = 1,
    current_file: str | None = None,
    page_index: int | None = None,
    mock: bool | None = None,
) -> dict[str, Any]:
    """Return {intent, reason, source} where source is heuristic|llm|default."""
    load_env()
    issue = (issue or "").strip()
    use_mock = is_mock() if mock is None else bool(mock)

    hit = heuristic_intent(issue)
    if hit == INTENT_DELETE and page_count <= 1:
        return {
            "intent": INTENT_REWRITE,
            "reason": "仅剩一页，无法删除，改为改写理解",
            "source": "heuristic-fallback",
        }
    if hit:
        return {
            "intent": hit,
            "reason": "关键词匹配",
            "source": "heuristic",
        }

    if use_mock:
        return {
            "intent": INTENT_REWRITE,
            "reason": "mock 默认改写",
            "source": "default",
        }

    try:
        try:
            cfg = llm_light_config()
        except Exception:
            cfg = llm_config()
        if not cfg.api_keys:
            return {
                "intent": INTENT_REWRITE,
                "reason": "未配置 LLM，默认改写",
                "source": "default",
            }
        pool = make_client_pool(cfg)
        user = (
            f"用户消息：{issue}\n"
            f"当前页：index={page_index if page_index is not None else '-'} "
            f"file={current_file or '-'}\n"
            f"总页数：{page_count}\n"
        )
        data = chat_json(
            pool=pool,
            model=cfg.model,
            system=SYSTEM_INTENT,
            user=user,
            temperature=0.1,
        )
        intent = str(data.get("intent") or "").strip().lower()
        if intent not in {INTENT_REWRITE, INTENT_GENERATE, INTENT_DELETE}:
            intent = INTENT_REWRITE
        if intent == INTENT_DELETE and page_count <= 1:
            intent = INTENT_REWRITE
            reason = "仅剩一页，无法删除"
        else:
            reason = str(data.get("reason") or "模型判定").strip() or "模型判定"
        return {"intent": intent, "reason": reason, "source": "llm"}
    except Exception as exc:  # noqa: BLE001
        return {
            "intent": INTENT_REWRITE,
            "reason": f"意图识别失败，默认改写（{exc}）",
            "source": "default",
        }
