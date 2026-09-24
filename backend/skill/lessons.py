"""质检失败 → 可迁移规则沉淀到 LEARNED_LESSONS.md（去重追加）。"""

from __future__ import annotations

import json
import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from llm import LlmClientPool, chat_json
from usage import current_usage, use_usage

_EXCERPTS_DIR = Path(__file__).resolve().parent / "excerpts"
LESSONS_FILE = "LEARNED_LESSONS.md"
_MARKER = "<!-- 自动追加区：勿删本行 -->"
_ID_RE = re.compile(r"^###\s+`([a-z0-9][a-z0-9-]{1,48})`", re.M)
_TAG_RE = re.compile(r"\[(?P<kind>[a-z]+(?::[a-z0-9_-]+)+)\]", re.I)
_LOCK = threading.Lock()
_MAX_LESSONS = 48
_MAX_PROMPT_ISSUES = 40
_LESSONS_PROMPT_CHARS = 6_000

_FALLBACK_RULES: dict[str, str] = {
    "visual-shell": "分区壳内必须有正文；禁止空内容卡 + 字在卡外/跨卡绝对定位。",
    "visual-contrast": "主标题与正文用 palette.text；勿用 accent/muted 当大面积字色；对比度不足则换色或加深托底。",
    "visual-overlap": "两个 text 可见盒不得大面积相交；用分区壳+flex/gap，勿靠负 margin 叠字。",
    "visual-occlude": "不透明卡/图不得压在可读字上；卡顶边须在标题底边之下，或把标题放进壳内流式区。",
    "visual-edge": "可读文字距画布边 ≥64px；全出血仅装饰字允许。",
    "visual-inset": "卡内文字相对底板内缩 ≥16–24px；勿靠 CSS padding 冒充可读内边距。",
    "export-position": "写了 left/top 必须同时 position:absolute；壳内正文优先不写 left/top。",
    "cover": "封面主视觉全出血；品牌/主标题层级清晰，勿堆次要营销块。",
}

_SYSTEM = """你是 WebPPT 质检教训编辑。把本次硬失败整理成可迁移、可执行的短规则，供下次 Plan/Slide 生成避免重犯。
只输出 JSON object：{"lessons":[{"id":"kebab-case","track":"both"|"html-slide","rule":"一句话规则"}]}。
约束：
- id 小写 kebab-case，稳定（同类问题同 id），长度 ≤40
- rule 一句中文，具体可执行，不要贴具体 slides/ 路径或像素坐标
- track 仅 both 或 html-slide（旧值 html 视为 html-slide）
- 已在「现有 lessons」中覆盖的问题不要再输出
- 无新教训时 lessons 为空数组
- 单次最多 6 条
"""


@dataclass(frozen=True)
class Lesson:
    id: str
    track: str
    rule: str

    def to_md(self) -> str:
        track = self.track if self.track in {"both", "html-slide"} else "both"
        return f"### `{self.id}` · track:{track}\n{self.rule.strip()}\n"


def lessons_path() -> Path:
    return _EXCERPTS_DIR / LESSONS_FILE


def learn_lessons_enabled() -> bool:
    """AGENT_LEARN_LESSONS：默认开；0/false/off 关闭。"""
    raw = (os.environ.get("AGENT_LEARN_LESSONS") or "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def read_lessons_raw(*, max_chars: int | None = None) -> str:
    path = lessons_path()
    if not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8")
    if max_chars is not None and len(text) > max_chars:
        text = text[:max_chars] + "\n\n…(truncated)"
    return text


def lessons_prompt_block(*, max_chars: int = 3_500) -> str:
    raw = read_lessons_raw(max_chars=max_chars)
    if not raw.strip() or not parse_lesson_ids(raw):
        return ""
    return f"# excerpts/{LESSONS_FILE}\n\n{raw}"


def parse_lesson_ids(text: str) -> set[str]:
    return {m.group(1).lower() for m in _ID_RE.finditer(text or "")}


def issue_kind_ids(issues: list[str]) -> list[str]:
    """从质检串提取稳定 id，如 [visual:shell] → visual-shell。"""
    seen: set[str] = set()
    out: list[str] = []
    for issue in issues:
        for m in _TAG_RE.finditer(issue):
            kid = re.sub(r"[^a-z0-9]+", "-", m.group("kind").lower()).strip("-")
            if kid and kid not in seen:
                seen.add(kid)
                out.append(kid)
        # 无 tag 时用粗粒度类别
        low = issue.lower()
        for needle, kid in (
            ("对比度", "visual-contrast"),
            ("重叠", "visual-overlap"),
            ("遮挡", "visual-occlude"),
            ("空卡", "visual-shell"),
            ("跨卡", "visual-shell"),
            ("贴边", "visual-edge"),
            ("安全区", "visual-edge"),
            ("position", "export-position"),
        ):
            if needle in low and kid not in seen:
                seen.add(kid)
                out.append(kid)
    return out


def _seed_header() -> str:
    seed = lessons_path()
    if seed.is_file():
        return seed.read_text(encoding="utf-8")
    return (
        "# Learned Lessons（质检沉淀 · 自动追加）\n\n"
        "## Lessons\n\n"
        f"{_MARKER}\n"
    )


def _normalize_lesson(item: Any) -> Lesson | None:
    if not isinstance(item, dict):
        return None
    lid = str(item.get("id") or "").strip().lower()
    lid = re.sub(r"[^a-z0-9-]+", "-", lid).strip("-")
    rule = str(item.get("rule") or "").strip()
    if not lid or len(lid) < 2 or not rule:
        return None
    if len(lid) > 48:
        lid = lid[:48].rstrip("-")
    track = str(item.get("track") or "both").strip().lower()
    if track == "pptxgen":
        track = "both"
    if track == "html":
        track = "html-slide"
    if track not in {"both", "html-slide"}:
        track = "both"
    rule = re.sub(r"\s+", " ", rule)
    if len(rule) > 220:
        rule = rule[:217].rstrip() + "…"
    return Lesson(id=lid, track=track, rule=rule)


def _fallback_lessons(kind_ids: list[str], existing: set[str]) -> list[Lesson]:
    out: list[Lesson] = []
    for kid in kind_ids:
        if kid in existing:
            continue
        rule = _FALLBACK_RULES.get(kid)
        if not rule:
            # 未知 tag：仍落一条泛化提醒
            rule = f"避免质检硬失败 `{kid}`：生成时自检对照 VISUAL_QA 同类规则。"
        out.append(Lesson(id=kid, track="both", rule=rule))
        if len(out) >= 6:
            break
    return out


def _trim_lessons_md(text: str, *, max_lessons: int = _MAX_LESSONS) -> str:
    ids = list(_ID_RE.finditer(text))
    if len(ids) <= max_lessons:
        return text
    # 保留文件头 + 最新 max_lessons 条（按出现顺序，丢掉最旧）
    drop_n = len(ids) - max_lessons
    cut_at = ids[drop_n].start()
    # 找到 Lessons 段起点
    lessons_idx = text.find("## Lessons")
    if lessons_idx < 0:
        lessons_idx = 0
    head = text[: lessons_idx]
    mid = text[lessons_idx:cut_at]
    # mid 可能只剩标题；保证 marker 在
    if _MARKER not in mid:
        mid = "## Lessons\n\n" + _MARKER + "\n\n"
    else:
        # 丢掉旧块后，从 cut_at 起是保留的 lessons
        pass
    body = text[cut_at:]
    return head + mid.rstrip() + "\n\n" + body.lstrip()


def append_lessons(lessons: list[Lesson]) -> list[str]:
    """去重追加；返回新写入的 id 列表。"""
    if not lessons:
        return []
    with _LOCK:
        path = lessons_path()
        text = path.read_text(encoding="utf-8") if path.is_file() else _seed_header()
        existing = parse_lesson_ids(text)
        fresh = [x for x in lessons if x.id not in existing]
        if not fresh:
            return []
        block = "\n".join(x.to_md() for x in fresh)
        if _MARKER in text:
            text = text.replace(_MARKER, _MARKER + "\n\n" + block, 1)
        else:
            if not text.endswith("\n"):
                text += "\n"
            text += "\n" + block
        text = _trim_lessons_md(text)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return [x.id for x in fresh]


def distill_lessons_with_llm(
    hard_issues: list[str],
    *,
    pool: LlmClientPool,
    model: str,
    package_format: str = "html-slide",
) -> list[Lesson]:
    """让 LLM 把硬问题总结成新 lessons；失败则 fallback 到 tag 规则。"""
    issues = [x for x in hard_issues if x][:_MAX_PROMPT_ISSUES]
    if not issues:
        return []

    existing_text = read_lessons_raw(max_chars=_LESSONS_PROMPT_CHARS)
    existing_ids = parse_lesson_ids(existing_text)
    kinds = issue_kind_ids(issues)
    pending_kinds = [k for k in kinds if k not in existing_ids]
    # 若所有可识别 kind 已有，且没有未识别噪声，可跳过 LLM
    if kinds and not pending_kinds and all(_TAG_RE.search(x) for x in issues):
        return []

    track_hint = "html-slide"
    _ = package_format
    user = (
        f"导出轨提示: {track_hint}（不确定则 track=both）\n\n"
        f"## 现有 lessons\n\n{existing_text or '(空)'}\n\n"
        f"## 本次硬问题\n\n"
        + "\n".join(f"- {x}" for x in issues)
    )
    usage = current_usage()
    try:
        with use_usage(usage):
            data = chat_json(
                pool=pool,
                model=model,
                system=_SYSTEM,
                user=user,
                temperature=0.15,
            )
        raw_list = data.get("lessons") if isinstance(data, dict) else None
        out: list[Lesson] = []
        seen: set[str] = set(existing_ids)
        if isinstance(raw_list, list):
            for item in raw_list[:6]:
                lesson = _normalize_lesson(item)
                if lesson is None or lesson.id in seen:
                    continue
                seen.add(lesson.id)
                out.append(lesson)
        if out:
            return out
    except Exception:
        pass
    return _fallback_lessons(pending_kinds or kinds, existing_ids)


def learn_from_hard_issues(
    hard_issues: list[str],
    *,
    pool: LlmClientPool | None,
    model: str | None,
    package_format: str = "html-slide",
) -> dict[str, Any]:
    """
    质检硬失败后沉淀教训。
    返回 {enabled, added: [...], skipped_reason?}。
    """
    if not learn_lessons_enabled():
        return {"enabled": False, "added": [], "skipped_reason": "disabled"}
    cleaned = [x.strip() for x in hard_issues if x and x.strip()]
    if not cleaned:
        return {"enabled": True, "added": [], "skipped_reason": "no_issues"}
    if pool is None or not model:
        # 无 LLM：仍可按 tag fallback 写入
        existing = parse_lesson_ids(read_lessons_raw())
        lessons = _fallback_lessons(issue_kind_ids(cleaned), existing)
        added = append_lessons(lessons)
        return {"enabled": True, "added": added, "mode": "fallback"}
    lessons = distill_lessons_with_llm(
        cleaned,
        pool=pool,
        model=model,
        package_format=package_format,
    )
    added = append_lessons(lessons)
    return {"enabled": True, "added": added, "mode": "llm"}
