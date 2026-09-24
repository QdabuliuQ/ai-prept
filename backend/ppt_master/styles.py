"""Load PPT Master visual-style cards + machine-readable catalog."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from ppt_master.paths import skill_dir

# Human-facing family metadata for curated presets (Admin groups).
FAMILY_META: dict[str, dict[str, str]] = {
    "swiss-minimal": {"family": "corporate-product", "group_zh": "企业 / 产品", "label_zh": "瑞士极简"},
    "soft-rounded": {"family": "corporate-product", "group_zh": "企业 / 产品", "label_zh": "柔和圆角"},
    "glassmorphism": {"family": "corporate-product", "group_zh": "企业 / 产品", "label_zh": "玻璃拟态"},
    "dark-tech": {"family": "corporate-product", "group_zh": "企业 / 产品", "label_zh": "暗色科技"},
    "blueprint": {"family": "corporate-product", "group_zh": "企业 / 产品", "label_zh": "蓝图线稿"},
    "editorial": {"family": "editorial", "group_zh": "编辑 / 出版", "label_zh": "编辑杂志"},
    "photo-editorial": {"family": "editorial", "group_zh": "编辑 / 出版", "label_zh": "摄影编辑"},
    "data-journalism": {"family": "editorial", "group_zh": "编辑 / 出版", "label_zh": "数据新闻"},
    "brutalist": {"family": "editorial", "group_zh": "编辑 / 出版", "label_zh": "粗野主义"},
    "memphis": {"family": "expressive-print", "group_zh": "表现 / 印刷", "label_zh": "孟菲斯"},
    "zine": {"family": "expressive-print", "group_zh": "表现 / 印刷", "label_zh": "小誌印刷"},
    "vintage-poster": {"family": "expressive-print", "group_zh": "表现 / 印刷", "label_zh": "复古海报"},
    "paper-cut": {"family": "expressive-print", "group_zh": "表现 / 印刷", "label_zh": "剪纸层叠"},
    "sketch-notes": {"family": "hand-drawn", "group_zh": "手绘 / 笔触", "label_zh": "手绘笔记"},
    "ink-notes": {"family": "hand-drawn", "group_zh": "手绘 / 笔触", "label_zh": "墨线笔记"},
    "chalkboard": {"family": "hand-drawn", "group_zh": "手绘 / 笔触", "label_zh": "黑板粉笔"},
    "ink-wash": {"family": "hand-drawn", "group_zh": "手绘 / 笔触", "label_zh": "水墨留白"},
    "pixel-art": {"family": "specialty", "group_zh": "特殊", "label_zh": "像素风"},
    "gallery-white": {"family": "extension", "group_zh": "扩展 / 高级", "label_zh": "画廊留白"},
    "midnight-luxe": {"family": "extension", "group_zh": "扩展 / 高级", "label_zh": "午夜奢静"},
    "nordic-calm": {"family": "extension", "group_zh": "扩展 / 高级", "label_zh": "北欧静气"},
    "kinetic-poster": {"family": "extension", "group_zh": "扩展 / 高级", "label_zh": "动能海报"},
    "dossier-archive": {"family": "extension", "group_zh": "扩展 / 高级", "label_zh": "档案简报"},
}

FAMILY_GROUP_ZH = {
    "corporate-product": "企业 / 产品",
    "editorial": "编辑 / 出版",
    "expressive-print": "表现 / 印刷",
    "hand-drawn": "手绘 / 笔触",
    "specialty": "特殊",
    "extension": "扩展 / 高级",
    "variant": "变体",
    "experimental": "实验",
}

# Extra metaphors that models often bake into pack titles (not content topics).
_STYLE_TITLE_EXTRA = (
    "胶印狂潮",
    "胶印",
    "舞台灯光",
    "代码编辑器风",
    "暗色科技风",
    "瑞士极简风",
    "视觉风格",
)


def style_title_ban_tokens(style_id: str | None = None) -> tuple[str, ...]:
    """Chinese fragments that must not become the pack book title.

    Pack naming = content topic; visual_style only governs look. Tokens come from
    curated labels, catalog label_zh, and known metaphors. When style_id is set,
    prefer that style's label first, then shared extras.
    """
    tokens: list[str] = []
    sid = (style_id or "").strip()
    if sid and sid in FAMILY_META:
        tokens.append(FAMILY_META[sid]["label_zh"])
    try:
        for item in load_catalog().get("styles") or []:
            if not isinstance(item, dict):
                continue
            item_id = str(item.get("id") or "").strip()
            label = str(item.get("label_zh") or "").strip()
            if not label or label == item_id:
                continue
            if sid and item_id != sid:
                continue
            if label not in tokens:
                tokens.append(label)
    except Exception:
        pass
    if not sid:
        for meta in FAMILY_META.values():
            lab = meta.get("label_zh") or ""
            if lab and lab not in tokens:
                tokens.append(lab)
    for extra in _STYLE_TITLE_EXTRA:
        if extra not in tokens:
            tokens.append(extra)
    # Longest first so 「代码编辑器风」 beats 「代码编辑器」
    tokens.sort(key=len, reverse=True)
    return tuple(tokens)

_ID_RE = re.compile(r"^[a-z][a-z0-9-]{1,62}$")
_BASE_RE = re.compile(r"(?im)^\s*(?:Base|母版)\s*:\s*`?([a-z][a-z0-9-]*)`?")
_LABEL_ZH_RE = re.compile(r"(?im)^\s*Label-zh\s*:\s*(.+?)\s*$")
_GROUP_ZH_RE = re.compile(r"(?im)^\s*Group-zh\s*:\s*(.+?)\s*$")
_FAMILY_RE = re.compile(r"(?im)^\s*Family\s*:\s*([a-z][a-z0-9-]*)\s*$")
_RENDER_RE = re.compile(
    r"##\s*5\.\s*Paired image-rendering\s*\n+\s*`([^`]+)`",
    re.I,
)
_ILLUS_RE = re.compile(r"\*\*(core|supportive|sparse)\*\*", re.I)


def visual_styles_dir() -> Path:
    return skill_dir() / "references" / "visual-styles"


def catalog_path() -> Path:
    return visual_styles_dir() / "_catalog.json"


def resolve_style_path(style_id: str) -> Path | None:
    """Resolve card path: root first, then variants/."""
    sid = (style_id or "").strip()
    if not sid or sid.startswith("_"):
        return None
    root = visual_styles_dir()
    for candidate in (root / f"{sid}.md", root / "variants" / f"{sid}.md"):
        if candidate.is_file():
            return candidate
    return None


def style_exists(style_id: str) -> bool:
    return resolve_style_path(style_id) is not None


def normalize_style_id(style_id: str | None, *, default: str = "dark-tech") -> str:
    sid = (style_id or "").strip() or default
    if style_exists(sid):
        return sid
    if style_exists(default):
        return default
    return sid


def _truncate_markdown(text: str, max_chars: int = 2800) -> str:
    text = text.strip()
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars]
    idx = cut.rfind("\n## ")
    if idx > max_chars // 2:
        cut = cut[:idx]
    return cut.rstrip() + "\n\n…(style card truncated)"


def _first_pitch(text: str) -> str:
    lines = text.splitlines()
    for line in lines[1:]:
        s = line.strip()
        if not s or s.startswith("#") or s == "---":
            continue
        low = s.lower()
        if low.startswith("hard bans"):
            continue
        if low.startswith("base:"):
            continue
        if low.startswith("label-zh:") or low.startswith("group-zh:"):
            continue
        if low.startswith("family:"):
            continue
        return s[:160]
    return ""


def _parse_card_meta(path: Path, *, relative: str) -> dict[str, Any]:
    sid = path.stem
    text = path.read_text(encoding="utf-8")
    known = FAMILY_META.get(sid, {})
    rel_norm = relative.replace("\\", "/")
    in_variants = "/variants/" in rel_norm or rel_norm.startswith("variants/")
    base_m = _BASE_RE.search(text)
    base_explicit = base_m.group(1).strip() if base_m else None
    base: str | None = base_explicit
    # Only infer parent from id prefix when the file already lives under variants/.
    # Root cards must stay standalone (curated / experimental) — never auto-「变体」.
    if not base and in_variants and "-" in sid:
        for parent in sorted(FAMILY_META.keys(), key=len, reverse=True):
            if sid.startswith(parent + "-"):
                base = parent
                break

    rend_m = _RENDER_RE.search(text)
    rendering = (rend_m.group(1).strip().split()[0] if rend_m else "") or None
    if rendering and "/" in rendering:
        rendering = rendering.split("/")[0].strip()

    illus_m = _ILLUS_RE.search(text)
    illus = (illus_m.group(1).lower() if illus_m else None)

    label_override = (_LABEL_ZH_RE.search(text) or [None, None])[1]
    if isinstance(label_override, str):
        label_override = label_override.strip() or None
    group_override = (_GROUP_ZH_RE.search(text) or [None, None])[1]
    if isinstance(group_override, str):
        group_override = group_override.strip() or None
    family_override = (_FAMILY_RE.search(text) or [None, None])[1]
    if isinstance(family_override, str):
        family_override = family_override.strip() or None

    if known and not in_variants and not base_explicit:
        status = "curated"
        family = family_override or known["family"]
        group_zh = group_override or known["group_zh"]
        label_zh = label_override or known["label_zh"]
    elif in_variants or base_explicit:
        status = "variant"
        parent = FAMILY_META.get(base or "", {})
        family = family_override or parent.get("family") or "variant"
        group_zh = group_override or FAMILY_GROUP_ZH.get(family, "变体")
        label_zh = label_override or sid
    else:
        # Standalone new root card — first-class, not 变体
        status = "curated" if (label_override and family_override) else "experimental"
        family = family_override or "extension"
        group_zh = group_override or FAMILY_GROUP_ZH.get(family, FAMILY_GROUP_ZH["extension"])
        label_zh = label_override or sid

    return {
        "id": sid,
        "family": family,
        "group_zh": group_zh,
        "label_zh": label_zh,
        "status": status,
        "base": base,
        "path": relative.replace("\\", "/"),
        "rendering": rendering,
        "illus": illus,
        "character": _first_pitch(text),
    }


def scan_style_cards() -> list[dict[str, Any]]:
    root = visual_styles_dir()
    if not root.is_dir():
        return []
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    paths: list[Path] = sorted(root.glob("*.md"))
    variants = root / "variants"
    if variants.is_dir():
        paths.extend(sorted(variants.glob("*.md")))
    for path in paths:
        if path.name.startswith("_"):
            continue
        if path.name.lower() in {"readme.md", "license.md"}:
            continue
        rel = str(path.relative_to(root))
        meta = _parse_card_meta(path, relative=rel)
        if not _ID_RE.match(meta["id"]):
            continue
        if meta["id"] in seen:
            continue
        seen.add(meta["id"])
        entries.append(meta)
    # curated first, then family, then id
    status_rank = {"curated": 0, "variant": 1, "experimental": 2}

    def sort_key(e: dict[str, Any]) -> tuple:
        return (status_rank.get(str(e.get("status")), 9), str(e.get("family")), str(e.get("id")))

    return sorted(entries, key=sort_key)


def build_catalog_dict() -> dict[str, Any]:
    styles = scan_style_cards()
    return {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "count": len(styles),
        "styles": styles,
    }


def rebuild_catalog() -> Path:
    root = visual_styles_dir()
    root.mkdir(parents=True, exist_ok=True)
    (root / "variants").mkdir(parents=True, exist_ok=True)
    path = catalog_path()
    data = build_catalog_dict()
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    load_catalog.cache_clear()
    list_style_ids.cache_clear()
    return path


@lru_cache(maxsize=4)
def load_catalog() -> dict[str, Any]:
    path = catalog_path()
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("styles"), list):
                return data
        except (OSError, json.JSONDecodeError):
            pass
    return build_catalog_dict()


@lru_cache(maxsize=4)
def list_style_ids(*, curated_only: bool = False) -> tuple[str, ...]:
    styles = load_catalog().get("styles") or []
    out: list[str] = []
    for item in styles:
        if not isinstance(item, dict):
            continue
        sid = str(item.get("id") or "").strip()
        if not sid:
            continue
        status = str(item.get("status") or "curated")
        if curated_only and status != "curated":
            continue
        out.append(sid)
    return tuple(out)


def admin_select_options(*, include_variants: bool = True) -> list[dict[str, Any]]:
    """Grouped options for Admin Select (Ant Design shape)."""
    styles = load_catalog().get("styles") or []
    groups: dict[str, list[dict[str, str]]] = {}
    for item in styles:
        if not isinstance(item, dict):
            continue
        status = str(item.get("status") or "curated")
        if not include_variants and status != "curated":
            continue
        if status == "experimental" and not include_variants:
            continue
        sid = str(item.get("id") or "").strip()
        if not sid:
            continue
        group = str(item.get("group_zh") or FAMILY_GROUP_ZH.get(str(item.get("family")), "其他"))
        label_zh = str(item.get("label_zh") or sid)
        label = f"{sid} {label_zh}".strip() if label_zh != sid else sid
        if status == "variant":
            base = item.get("base")
            if base:
                label = f"{sid} (←{base})"
        groups.setdefault(group, []).append({"value": sid, "label": label})
    return [{"label": g, "options": opts} for g, opts in groups.items()]


@lru_cache(maxsize=64)
def load_style_card(style_id: str) -> str:
    """Return a compact style bible excerpt for prompts (no fixed HEX palette)."""
    sid = (style_id or "dark-tech").strip() or "dark-tech"
    path = resolve_style_path(sid)
    body = ""
    if path and path.is_file():
        try:
            body = _truncate_markdown(path.read_text(encoding="utf-8"))
        except OSError:
            body = ""
    header = (
        f"visual_style id = {sid}\n"
        "Follow this style's shape language, typography character, whitespace, "
        "decoration density, and color-usage discipline.\n"
        "Invent an original palette for this deck — do NOT copy any fixed HEX recipe.\n"
        "Hard bans for non-tech styles: neon cyan/purple glow grids, particle fields, "
        "orbital HUD rings, holographic panels — unless the selected style is "
        "dark-tech / glassmorphism / blueprint.\n"
    )
    if body:
        return header + "\n## Style reference\n\n" + body
    return header + f"\n(No local reference file for {sid}; follow id semantics strictly.)\n"


def force_plan_style(plan: dict, visual_style: str) -> dict:
    """Lock visual_style id only; never overwrite the LLM's palette."""
    sid = normalize_style_id(visual_style)
    plan["visual_style"] = sid
    return plan


def assert_valid_style_id(style_id: str) -> str:
    """Raise ValueError if id is missing on disk."""
    sid = (style_id or "").strip()
    if not sid:
        raise ValueError("visual_style id is empty")
    if not _ID_RE.match(sid):
        raise ValueError(f"invalid visual_style id: {sid!r}")
    if not style_exists(sid):
        raise ValueError(
            f"unknown visual_style {sid!r}; "
            f"add {sid}.md under visual-styles/ or visual-styles/variants/ "
            "then rebuild _catalog.json"
        )
    return sid
