"""Plan editor AI assist actions (modify / regenerate_image / add / delete)."""

from __future__ import annotations

import re
from typing import Any

from config import is_mock, llm_config, load_env, llm_light_config
from llm import chat_json, make_client_pool
from templates.editor_intent import (
    INTENT_DELETE,
    INTENT_GENERATE,
    heuristic_intent,
)

OP_MODIFY = "modify"
OP_REGENERATE_IMAGE = "regenerate_image"
OP_ADD = "add"
OP_DELETE = "delete"

_ALLOWED_OPS = {OP_MODIFY, OP_REGENERATE_IMAGE, OP_ADD, OP_DELETE}
_MAX_ACTIONS = 5

_IMAGE_RE = re.compile(
    r"("
    r"换\s*一?\s*下?\s*(图|配图|图片|主视觉|封面图)|"
    r"(图|配图|图片|主视觉|封面图).{0,8}(换|改|重|新)|"
    r"(换|改|重|新).{0,8}(图|配图|图片|主视觉|封面图)|"
    r"换成.{0,40}(风格|写实|插画|摄影)|"
    r"\b(replace|change|regenerate|swap|redraw)\b.{0,20}\b(image|photo|picture|illustration|visual)\b|"
    r"\b(image|photo|picture)\b.{0,20}\b(replace|change|regenerate|swap|redraw)\b"
    r")",
    re.I,
)

SYSTEM_PLAN = """你是 WebPPT 编辑助手的动作规划器。只输出 JSON：
{
  "summary": "一句中文说明本次要做什么",
  "actions": [
    {"op":"modify"|"regenerate_image"|"add"|"delete", "pageIndex":0, "file":"slides/x.html", "instruction":"...", "prompt":"...", "imageFile":"cover-asset-1.png", "afterPageIndex":0, "reason":"..."}
  ]
}

规则：
- 先识别用户意图：只改文案/版式 → modify；要换配图 → regenerate_image；新增页 → add；删页 → delete。可组合。
- op=modify：改写某页 HTML 文案/版式（不生成新图文件名）；instruction 保留用户原话或改写要求
- op=regenerate_image：重生该页已有本地图（覆盖同名文件）；默认当前页第一张图
  - prompt 必须是「纯画面描述」（人物、场景、构图、风格），例如「几个老年人围坐在小桌旁，写实摄影」
  - 禁止把操作话术写进 prompt（不要写「换图」「第一页」「请帮我」等）
- op=add：在 afterPageIndex / 当前页后新增一页
- op=delete：删除一页（删后至少保留 1 页）
- 换图且需要同步图注/说明文字时：先 modify，再 regenerate_image
- 单次最多 5 个动作；pageIndex 为 0-based；不确定时用当前页
- 不要输出其它字段
"""


def wants_image_regen(issue: str) -> bool:
    return bool(_IMAGE_RE.search(issue or ""))


def extract_visual_prompt(
    issue: str,
    *,
    mock: bool | None = None,
) -> str:
    """从用户指令抽出 regenerate_image 用的纯画面描述（意图槽位，不在生图层清洗）。"""
    load_env()
    text = (issue or "").strip()
    if not text:
        return ""
    use_mock = is_mock() if mock is None else bool(mock)
    if use_mock:
        return text

    try:
        try:
            cfg = llm_light_config()
        except Exception:
            cfg = llm_config()
        if not cfg.api_keys:
            return text
        pool = make_client_pool(cfg)
        data = chat_json(
            pool=pool,
            model=cfg.model,
            system=(
                "你是视觉提示词提取器。用户在编辑 PPT，可能要求换图或改文案。"
                "只输出 JSON：{\"image_prompt\":\"纯画面描述\"}。"
                "image_prompt 只写要画的内容（人物/场景/风格），不要操作指令（换图、第几页、请帮我等）。"
                "若看不出画面，把用户原话里与画面相关的部分精炼写出。"
            ),
            user=f"用户指令：{text}",
            temperature=0.1,
        )
        prompt = str((data or {}).get("image_prompt") or "").strip()
        return prompt or text
    except Exception:
        return text


def _normalize_action(raw: Any, *, default_page_index: int | None) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    op = str(raw.get("op") or "").strip().lower()
    if op not in _ALLOWED_OPS:
        return None
    out: dict[str, Any] = {"op": op}
    for key in ("file", "instruction", "prompt", "imageFile", "reason"):
        val = raw.get(key)
        if val is not None and str(val).strip():
            out[key] = str(val).strip()
    for key in ("pageIndex", "afterPageIndex"):
        val = raw.get(key)
        if val is None or val == "":
            continue
        try:
            out[key] = int(val)
        except (TypeError, ValueError):
            pass
    if "pageIndex" not in out and default_page_index is not None and op != OP_ADD:
        out["pageIndex"] = default_page_index
    if op == OP_MODIFY and not out.get("instruction"):
        return None
    if op == OP_REGENERATE_IMAGE and not out.get("prompt"):
        return None
    if op == OP_ADD and not out.get("instruction"):
        return None
    return out


def heuristic_plan(
    issue: str,
    *,
    page_count: int = 1,
    page_index: int | None = None,
    current_file: str | None = None,
) -> dict[str, Any] | None:
    """Fast path for single-intent messages. Returns None when LLM planning is better."""
    text = (issue or "").strip()
    if not text:
        return None

    intent = heuristic_intent(text)
    image = wants_image_regen(text)

    # Compound across delete/add/image → let LLM plan
    compound_bits = [
        intent == INTENT_DELETE,
        intent == INTENT_GENERATE,
        image and intent in {INTENT_DELETE, INTENT_GENERATE},
    ]
    if sum(1 for b in compound_bits if b) >= 2:
        return None

    if intent == INTENT_DELETE and not image:
        if page_count <= 1:
            return {
                "summary": "仅剩一页，改为改写当前页",
                "actions": [
                    {
                        "op": OP_MODIFY,
                        "pageIndex": page_index,
                        "file": current_file,
                        "instruction": text,
                        "reason": "无法删除最后一页",
                    }
                ],
                "source": "heuristic",
            }
        return {
            "summary": "删除指定页面",
            "actions": [
                {
                    "op": OP_DELETE,
                    "pageIndex": page_index,
                    "file": current_file,
                    "reason": "关键词匹配删除",
                }
            ],
            "source": "heuristic",
        }

    if intent == INTENT_GENERATE and not image:
        return {
            "summary": "新增一页",
            "actions": [
                {
                    "op": OP_ADD,
                    "afterPageIndex": page_index,
                    "file": current_file,
                    "instruction": text,
                    "reason": "关键词匹配新增",
                }
            ],
            "source": "heuristic",
        }

    if image:
        # 换图交给 LLM 规划，由其填写纯画面 prompt；启发式不写死「换成…」清洗规则
        return None

    return {
        "summary": "改写当前页",
        "actions": [
            {
                "op": OP_MODIFY,
                "pageIndex": page_index,
                "file": current_file,
                "instruction": text,
                "reason": "默认改写",
            }
        ],
        "source": "heuristic",
    }


def plan_editor_actions(
    issue: str,
    *,
    page_count: int = 1,
    current_file: str | None = None,
    page_index: int | None = None,
    slide_outline: list[dict[str, Any]] | None = None,
    mock: bool | None = None,
) -> dict[str, Any]:
    """Return {summary, actions, source}."""
    load_env()
    issue = (issue or "").strip()
    use_mock = is_mock() if mock is None else bool(mock)

    hit = heuristic_plan(
        issue,
        page_count=page_count,
        page_index=page_index,
        current_file=current_file,
    )
    if hit and hit.get("actions"):
        # normalize missing instructions
        actions = []
        for a in hit["actions"]:
            na = _normalize_action(a, default_page_index=page_index)
            if not na:
                continue
            if na["op"] == OP_MODIFY and not na.get("instruction"):
                na["instruction"] = issue
            if na["op"] == OP_REGENERATE_IMAGE and not na.get("prompt"):
                na["prompt"] = extract_visual_prompt(issue, mock=use_mock)
            if na["op"] == OP_ADD and not na.get("instruction"):
                na["instruction"] = issue
            actions.append(na)
        if actions:
            hit["actions"] = actions[:_MAX_ACTIONS]
            return hit

    if use_mock:
        if wants_image_regen(issue):
            visual = extract_visual_prompt(issue, mock=True)
            actions = [
                {
                    "op": OP_MODIFY,
                    "pageIndex": page_index,
                    "file": current_file,
                    "instruction": issue,
                },
                {
                    "op": OP_REGENERATE_IMAGE,
                    "pageIndex": page_index,
                    "file": current_file,
                    "prompt": visual,
                },
            ]
            return {
                "summary": "mock：更新配图并改写相关文案",
                "actions": actions,
                "source": "default",
            }
        return {
            "summary": "mock：改写当前页",
            "actions": [
                {
                    "op": OP_MODIFY,
                    "pageIndex": page_index,
                    "file": current_file,
                    "instruction": issue,
                }
            ],
            "source": "default",
        }

    try:
        try:
            cfg = llm_light_config()
        except Exception:
            cfg = llm_config()
        if not cfg.api_keys:
            fallback = heuristic_plan(
                issue,
                page_count=page_count,
                page_index=page_index,
                current_file=current_file,
            ) or {
                "summary": "默认改写当前页",
                "actions": [
                    {
                        "op": OP_MODIFY,
                        "pageIndex": page_index,
                        "file": current_file,
                        "instruction": issue,
                    }
                ],
            }
            fallback["source"] = "default"
            return fallback

        outline_lines = []
        for i, row in enumerate(slide_outline or []):
            if not isinstance(row, dict):
                continue
            outline_lines.append(
                f"{i}. {row.get('file') or '-'} · {row.get('title') or ''}"
            )
        user = (
            f"用户消息：{issue}\n"
            f"当前页：index={page_index if page_index is not None else '-'} "
            f"file={current_file or '-'}\n"
            f"总页数：{page_count}\n"
            f"大纲：\n" + ("\n".join(outline_lines) if outline_lines else "(无)")
        )
        pool = make_client_pool(cfg)
        data = chat_json(
            pool=pool,
            model=cfg.model,
            system=SYSTEM_PLAN,
            user=user,
            temperature=0.1,
        )
        actions_raw = data.get("actions") if isinstance(data, dict) else None
        actions: list[dict[str, Any]] = []
        if isinstance(actions_raw, list):
            for item in actions_raw:
                na = _normalize_action(item, default_page_index=page_index)
                if not na:
                    continue
                if na["op"] == OP_MODIFY and not na.get("instruction"):
                    na["instruction"] = issue
                if na["op"] == OP_REGENERATE_IMAGE and not na.get("prompt"):
                    na["prompt"] = extract_visual_prompt(issue, mock=False)
                if na["op"] == OP_ADD and not na.get("instruction"):
                    na["instruction"] = issue
                if na["op"] == OP_DELETE and page_count <= 1:
                    continue
                actions.append(na)
                if len(actions) >= _MAX_ACTIONS:
                    break
        if not actions:
            if wants_image_regen(issue):
                actions = [
                    {
                        "op": OP_MODIFY,
                        "pageIndex": page_index,
                        "file": current_file,
                        "instruction": issue,
                    },
                    {
                        "op": OP_REGENERATE_IMAGE,
                        "pageIndex": page_index,
                        "file": current_file,
                        "prompt": extract_visual_prompt(issue, mock=False),
                    },
                ]
            else:
                actions = [
                    {
                        "op": OP_MODIFY,
                        "pageIndex": page_index,
                        "file": current_file,
                        "instruction": issue,
                    }
                ]
        summary = str((data or {}).get("summary") or "").strip() or "按计划执行编辑"
        return {"summary": summary, "actions": actions, "source": "llm"}
    except Exception as exc:  # noqa: BLE001
        return {
            "summary": f"规划失败，回退为改写（{exc}）",
            "actions": [
                {
                    "op": OP_MODIFY,
                    "pageIndex": page_index,
                    "file": current_file,
                    "instruction": issue,
                }
            ],
            "source": "default",
        }
