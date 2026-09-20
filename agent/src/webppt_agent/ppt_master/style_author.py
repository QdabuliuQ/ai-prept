"""Resolve a visual style against the catalog, or author a new card.

Flow:
1. Exact id / label match → reuse.
2. Token overlap with existing cards → reuse (avoid near-duplicates).
3. Otherwise call the light LLM to write one standalone card (style-skill contract),
   validate, write visual-styles/<id>.md, rebuild _catalog.json.
"""

from __future__ import annotations

import json
import os
import re
import threading
from typing import Any, Callable

from webppt_agent.config import llm_light_config
from webppt_agent.llm import chat_json, make_client_pool
from webppt_agent.ppt_master.styles import (
    FAMILY_GROUP_ZH,
    _ID_RE,
    load_catalog,
    load_style_card,
    rebuild_catalog,
    style_exists,
    visual_styles_dir,
)

LogFn = Callable[[str], None]

_HEX_RE = re.compile(r"#[0-9A-Fa-f]{3,8}\b")
_ALLOWED_FAMILIES = frozenset(FAMILY_GROUP_ZH) - {"variant", "experimental"}
_ALLOWED_ILLUS = frozenset({"core", "supportive", "sparse"})
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")

_write_lock = threading.Lock()

SYSTEM_RESOLVE = """你是 PPT Master 视觉风格库管理员。
任务：判断用户意图是否能复用已有风格卡；不能则给出一张全新的独立风格卡草稿。

硬规则：
1. 能复用就 reuse，禁止为近义风格新建卡。
2. 新建必须是 standalone 根卡：不要 Base、不要 variants、id 不要用 parent-modifier 形式去套已有母版。
3. 禁止任何 HEX 色值（#RGB / #RRGGBB）。只描述用色纪律。
4. Style ≠ 内容大纲：不要规定页数或论证结构。
5. id 为 kebab-case，^[a-z][a-z0-9-]{1,40}$，且不得与 catalog 已有 id 冲突。
6. Family 只能是：corporate-product | editorial | expressive-print | hand-drawn | specialty | extension
7. illustration 只能是：core | supportive | sparse
8. composition_geometry 必须 4–6 条具体版式骨架。
9. 只输出一个 JSON 对象，不要 markdown。
"""

SYSTEM_AUTHOR = """你是 PPT Master 风格卡作者（style-skill）。
按契约写一张独立视觉风格卡。禁止 HEX。禁止 Base/变体。只输出 JSON。
"""


def _log(log: LogFn | None, msg: str) -> None:
    if log:
        log(msg if msg.endswith("\n") else msg + "\n")


def _norm(text: str) -> str:
    return re.sub(r"[\s_\-]+", "", (text or "").strip().lower())


def _tokens(text: str) -> set[str]:
    raw = (text or "").lower()
    parts = re.findall(r"[a-z0-9]{3,}|[\u4e00-\u9fff]{2,}", raw)
    stop = {
        "style", "visual", "deck", "slide", "ppt", "风格", "视觉", "风格卡",
        "一种", "这个", "那个", "以及", "用于",
    }
    return {p for p in parts if p not in stop}


def catalog_entries() -> list[dict[str, Any]]:
    data = load_catalog()
    styles = data.get("styles") if isinstance(data, dict) else None
    if not isinstance(styles, list):
        return []
    return [s for s in styles if isinstance(s, dict) and s.get("id")]


def catalog_digest(limit: int = 80) -> str:
    rows: list[str] = []
    for item in catalog_entries()[:limit]:
        rows.append(
            f"- {item.get('id')} | {item.get('label_zh') or ''} | "
            f"{item.get('family') or ''} | {(item.get('character') or '')[:90]}"
        )
    extra = max(0, len(catalog_entries()) - limit)
    if extra:
        rows.append(f"…(+{extra} more)")
    return "\n".join(rows) or "(empty catalog)"


def match_existing(intent: str) -> str | None:
    """Exact id / label, or strong token overlap. Returns style id or None."""
    text = (intent or "").strip()
    if not text:
        return None
    entries = catalog_entries()
    by_id = {str(e["id"]): e for e in entries}

    if text in by_id or style_exists(text):
        return text if text in by_id or style_exists(text) else None
    if _ID_RE.match(text) and style_exists(text):
        return text

    folded = _norm(text)
    for e in entries:
        sid = str(e["id"])
        label = str(e.get("label_zh") or "")
        if folded and folded in {_norm(sid), _norm(label)}:
            return sid
        # "comic-panel 漫画分镜" pasted from Admin select label
        if sid in text and (label in text or _norm(sid) in folded):
            if len(text) <= len(sid) + len(label) + 4:
                return sid

    want = _tokens(text)
    if len(want) < 2:
        return None
    best_id: str | None = None
    best = 0.0
    for e in entries:
        blob = " ".join(
            str(e.get(k) or "")
            for k in ("id", "label_zh", "character", "family", "group_zh")
        )
        have = _tokens(blob)
        if not have:
            continue
        inter = want & have
        if not inter:
            continue
        score = len(inter) / max(1, min(len(want), 6))
        # Require the distinctive tokens, not just "印刷"/"企业"
        if score > best and score >= 0.66 and len(inter) >= 2:
            best = score
            best_id = str(e["id"])
    return best_id


def _slugify(raw: str) -> str:
    text = (raw or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    text = re.sub(r"-{2,}", "-", text)
    if not text or not text[0].isalpha():
        text = "style-" + text
    return text[:40].strip("-") or "custom-style"


def _unique_id(preferred: str) -> str:
    base = _slugify(preferred)
    if not style_exists(base) and _ID_RE.match(base):
        return base
    for i in range(2, 30):
        cand = f"{base[:36]}-{i}"
        if _ID_RE.match(cand) and not style_exists(cand):
            return cand
    raise RuntimeError(f"无法为 {preferred!r} 分配未占用的风格 id")


def _as_lines(value: Any, *, min_n: int = 4, max_n: int = 6) -> list[str]:
    if isinstance(value, str):
        parts = [p.strip() for p in re.split(r"[;；\n]", value) if p.strip()]
    elif isinstance(value, list):
        parts = [str(p).strip() for p in value if str(p).strip()]
    else:
        parts = []
    if len(parts) < min_n:
        parts.extend(
            [
                "asymmetric split with a quiet margin",
                "full-bleed field with one inset claim",
                "stacked bands with a single accent rule",
                "centered statement over sparse ornament",
            ][: min_n - len(parts)]
        )
    return parts[:max_n]


def validate_card_markdown(text: str, style_id: str) -> list[str]:
    errors: list[str] = []
    if not text.strip().startswith(f"# Visual style: {style_id}"):
        errors.append("missing title")
    if _HEX_RE.search(text):
        errors.append("contains HEX color")
    if re.search(r"(?im)^\s*Base\s*:", text):
        errors.append("contains Base: (variants forbidden)")
    for key in ("Label-zh:", "Group-zh:", "Family:", "## 1.", "## 5.", "## 6."):
        if key not in text:
            errors.append(f"missing {key}")
    if not re.search(r"\*\*(core|supportive|sparse)\*\*", text):
        errors.append("missing illustration propensity")
    return errors


def render_card(style_id: str, draft: dict[str, Any]) -> str:
    label = str(draft.get("label_zh") or style_id).strip()[:24]
    family = str(draft.get("family") or "extension").strip()
    if family not in _ALLOWED_FAMILIES:
        family = "extension"
    group = str(draft.get("group_zh") or FAMILY_GROUP_ZH.get(family) or "扩展 / 高级").strip()
    pitch = str(draft.get("pitch") or "").strip()
    if len(pitch) < 40:
        pitch = (
            f"{label} — a standalone visual system for decks that need this look. "
            "Character should stay coherent across a full presentation without borrowing another style's ornaments."
        )
    bans = str(draft.get("hard_bans") or "generic AI purple gradients, dashboard card grids").strip()
    shapes = str(draft.get("shape_language") or "clear contours; restrained corners; purposeful stroke").strip()
    geos = _as_lines(draft.get("composition_geometry"))
    deco = str(draft.get("decoration") or "sparse marks tied to the motif; no confetti").strip()
    space = str(draft.get("whitespace") or "generous margins; one density rhythm per page").strip()
    typo = str(
        draft.get("typography")
        or "expressive display for the claim; quiet grotesque for body; short lines"
    ).strip()
    typo_ask = str(draft.get("typography_ask") or "display + grotesque").strip()
    field = str(draft.get("color_field") or "one dominant field; type sits in quiet zones").strip()
    accent = str(draft.get("color_accent") or "localized accent, never a second palette").strip()
    discipline = str(draft.get("color_discipline") or "field-and-spot discipline").strip()
    texture = str(draft.get("texture") or "mostly flat; optional fine grain; no glow stacks").strip()
    rendering = re.sub(r"[^a-z0-9-]", "", str(draft.get("rendering") or "flat").lower()) or "flat"
    render_why = str(draft.get("rendering_why") or "imagery should share the same material language").strip()
    illus = str(draft.get("illustration") or "supportive").strip().lower()
    if illus not in _ALLOWED_ILLUS:
        illus = "supportive"
    illus_why = str(draft.get("illustration_why") or "illustration supports the claim, does not replace type").strip()

    geo_line = "; ".join(geos)
    return f"""# Visual style: {style_id}

Label-zh: {label}
Group-zh: {group}
Family: {family}

{pitch}

Hard bans: {bans}

---

## 1. Shape & decoration

- Shape language: {shapes}
- Composition geometry: {geo_line}
- Decoration: {deco}
- Whitespace: {space}

## 2. Typography character

- {typo}

> Families are chosen at confirmation `g`; this style asks for a {typo_ask} pairing/character, not a specific font file. This governs editable native text; decorative-lettering eligibility remains a separate carrier decision.

## 3. Using the deck's colors

- {field}
- {accent}

> HEX values come from confirmation `e`; this style only governs the {discipline} — it names no colors.

## 4. Texture / elevation

- {texture}

## 5. Paired image-rendering

`{rendering}` — {render_why}.

## 6. Illustration propensity

**{illus}** — {illus_why}. Role, scale, reuse, and placement stay Strategist judgment; an explicit user request wins either way, and `image_usage: none` writes no illustration rows.
"""


def _parse_decision(raw: dict[str, Any]) -> dict[str, Any]:
    action = str(raw.get("action") or "").strip().lower()
    if action not in {"reuse", "create"}:
        action = "create" if raw.get("card") or raw.get("id") else "reuse"
    reuse_id = str(raw.get("reuse_id") or raw.get("id") or "").strip()
    card = raw.get("card") if isinstance(raw.get("card"), dict) else raw
    return {"action": action, "reuse_id": reuse_id, "card": card if isinstance(card, dict) else {}}


def _llm_json(system: str, user: str) -> dict[str, Any]:
    cfg = llm_light_config()
    pool = make_client_pool(cfg)
    data = chat_json(
        pool=pool,
        model=cfg.model,
        system=system,
        user=user,
        temperature=0.4,
    )
    if not isinstance(data, dict):
        raise RuntimeError("风格解析未返回 JSON object")
    return data


def write_style_card(style_id: str, markdown: str) -> str:
    """Write root card and rebuild catalog. Returns absolute path."""
    sid = (style_id or "").strip()
    if not _ID_RE.match(sid):
        raise ValueError(f"invalid style id: {sid!r}")
    errors = validate_card_markdown(markdown, sid)
    if errors:
        raise ValueError(f"风格卡未通过校验 ({sid}): {', '.join(errors)}")
    root = visual_styles_dir()
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{sid}.md"
    with _write_lock:
        if path.is_file():
            return str(path)
        path.write_text(markdown.rstrip() + "\n", encoding="utf-8")
        rebuild_catalog()
        load_style_card.cache_clear()
    return str(path)


def ensure_style(
    intent: str,
    *,
    allow_create: bool = True,
    mock: bool = False,
    log: LogFn | None = None,
) -> dict[str, Any]:
    """Return {id, created, reused, path, reason}.

    If the intent matches an existing card, reuse it.
    If allow_create and nothing matches, author a new card (unless mock).
    """
    text = (intent or "").strip()
    if not text:
        raise ValueError("风格意图为空")

    # Auto-create can be disabled globally.
    if os.environ.get("AGENT_STYLE_AUTOCREATE", "").strip().lower() in {
        "0", "false", "no", "off",
    }:
        allow_create = False

    hit = match_existing(text)
    if hit:
        _log(log, f"[style] reuse {hit} (catalog match)")
        path = visual_styles_dir() / f"{hit}.md"
        return {
            "id": hit,
            "created": False,
            "reused": True,
            "path": str(path) if path.is_file() else None,
            "reason": "catalog-match",
        }

    if not allow_create:
        raise ValueError(
            f"未知风格 {text!r}，且未允许自动建卡。"
            "请选择已有风格，或打开「风格不存在时自动生成」。"
        )

    if mock or os.environ.get("AGENT_MOCK", "").strip() in {"1", "true", "yes"}:
        sid = _unique_id(_slugify(text) if re.search(r"[a-zA-Z]", text) else "mock-style")
        draft = {
            "label_zh": text[:12] if _CJK_RE.search(text) else sid,
            "family": "extension",
            "group_zh": "扩展 / 高级",
            "pitch": f"Mock card for intent: {text}. Standalone experimental look for pipeline tests.",
            "shape_language": "simple blocks and one rule",
            "composition_geometry": [
                "left claim, right quiet field",
                "full-bleed title band",
                "three stacked statements",
                "centered close",
            ],
            "illustration": "sparse",
            "rendering": "flat",
        }
        md = render_card(sid, draft)
        path = write_style_card(sid, md)
        _log(log, f"[style] created mock card {sid}")
        return {
            "id": sid,
            "created": True,
            "reused": False,
            "path": path,
            "reason": "mock-create",
        }

    user = f"""## 用户风格意图
{text}

## 已有风格（优先复用）
{catalog_digest()}

## 输出 JSON
{{
  "action": "reuse" | "create",
  "reuse_id": "<已有 id，action=reuse 时必填>",
  "reason": "<一句话>",
  "card": {{
    "id": "<新 kebab id，action=create>",
    "label_zh": "<2-8字中文>",
    "family": "extension",
    "group_zh": "扩展 / 高级",
    "pitch": "<2-4 English or Chinese sentences, no HEX>",
    "hard_bans": "<anti-patterns>",
    "shape_language": "...",
    "composition_geometry": ["skeleton1", "skeleton2", "skeleton3", "skeleton4"],
    "decoration": "...",
    "whitespace": "...",
    "typography": "...",
    "typography_ask": "display + grotesque",
    "color_field": "...",
    "color_accent": "...",
    "color_discipline": "spot accent",
    "texture": "...",
    "rendering": "flat",
    "rendering_why": "...",
    "illustration": "supportive",
    "illustration_why": "..."
  }}
}}
若意图与某一已有风格实质相同，必须 action=reuse。"""

    decision = _parse_decision(_llm_json(SYSTEM_RESOLVE, user))
    if decision["action"] == "reuse":
        rid = decision["reuse_id"]
        if rid and style_exists(rid):
            _log(log, f"[style] reuse {rid} (model)")
            return {
                "id": rid,
                "created": False,
                "reused": True,
                "path": str(visual_styles_dir() / f"{rid}.md"),
                "reason": "model-reuse",
            }
        # Model named a missing id — fall through to create using that slug if present.
        _log(log, f"[style] model reuse id {rid!r} missing; will create")

    card = decision["card"] if isinstance(decision["card"], dict) else {}
    preferred = str(card.get("id") or decision["reuse_id"] or "").strip()
    if not preferred or not re.search(r"[a-zA-Z]", preferred):
        # Ask once more for an id-bearing card.
        card = _llm_json(
            SYSTEM_AUTHOR,
            "Write the card JSON for this intent. Include id.\n\n" + text
            + "\n\nExisting ids to avoid:\n" + catalog_digest(40),
        )
        if "card" in card and isinstance(card["card"], dict):
            card = card["card"]
        preferred = str(card.get("id") or "custom-style")

    sid = _unique_id(preferred)
    # Re-check after lock window: another worker may have created a lexical match.
    again = match_existing(text)
    if again:
        _log(log, f"[style] reuse {again} (race)")
        return {
            "id": again,
            "created": False,
            "reused": True,
            "path": str(visual_styles_dir() / f"{again}.md"),
            "reason": "race-reuse",
        }

    md = render_card(sid, card)
    # Strip any HEX the model slipped into fields.
    md = _HEX_RE.sub("the deck palette", md)
    errors = validate_card_markdown(md, sid)
    if errors:
        raise RuntimeError(f"生成的风格卡无效: {', '.join(errors)}\n{md[:400]}")
    path = write_style_card(sid, md)
    _log(log, f"[style] created {sid} → {path}")
    return {
        "id": sid,
        "created": True,
        "reused": False,
        "path": path,
        "reason": "created",
        "label_zh": str(card.get("label_zh") or ""),
    }


def decision_preview(raw_json: str) -> dict[str, Any]:
    """Test helper."""
    data = json.loads(raw_json)
    return _parse_decision(data)
