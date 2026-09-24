"""Generate visual-spec.md for an existing template package (post-approval)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from config import llm_light_config
from llm import chat_text, make_client_pool
from templates import prompts
from usage import track_usage, use_usage


def _strip_fence(text: str) -> str:
    s = (text or "").strip()
    if not s.startswith("```"):
        return s
    s = re.sub(r"^```(?:markdown|md)?\s*", "", s, flags=re.I)
    s = re.sub(r"\s*```$", "", s)
    return s.strip()


def _read_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"invalid JSON object: {path}")
    return data


def build_deck_context(package_dir: Path) -> dict[str, Any]:
    """Compact planning context for visual-spec LLM (no full HTML)."""
    meta_path = package_dir / "template.json"
    if not meta_path.is_file():
        raise FileNotFoundError(f"missing template.json: {meta_path}")
    meta = _read_json(meta_path)

    files = meta.get("files") if isinstance(meta.get("files"), dict) else {}
    theme_rel = str(files.get("theme_css") or "theme.css")
    theme_path = package_dir / theme_rel
    theme_excerpt = ""
    if theme_path.is_file():
        theme_excerpt = theme_path.read_text(encoding="utf-8")[:8_000]

    slides_brief: list[dict[str, Any]] = []
    for item in meta.get("slides") or []:
        if not isinstance(item, dict):
            continue
        slides_brief.append(
            {
                "file": item.get("file"),
                "layout": item.get("layout"),
                "title": item.get("title"),
                "description": (str(item.get("description") or ""))[:180],
            }
        )

    return {
        "template_id": meta.get("template_id") or package_dir.name,
        "label": meta.get("label"),
        "description": meta.get("description"),
        "format": meta.get("format") or "html-slide",
        "visual_spec_outline": meta.get("visual_spec_outline") or "",
        "slides": slides_brief,
        "theme_css_excerpt": theme_excerpt,
    }


def write_visual_spec(package_dir: Path, markdown: str) -> Path:
    text = (markdown or "").rstrip() + "\n"
    out = package_dir / "visual-spec.md"
    out.write_text(text, encoding="utf-8")

    meta_path = package_dir / "template.json"
    if meta_path.is_file():
        meta = _read_json(meta_path)
        files = meta.get("files") if isinstance(meta.get("files"), dict) else {}
        files = dict(files)
        files.setdefault("visual_spec", "visual-spec.md")
        meta["files"] = files
        meta_path.write_text(
            json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return out


def generate_visual_spec(
    package_dir: Path,
    *,
    mock: bool = False,
    only_if_missing: bool = False,
) -> Path:
    """Call LLM (or mock stub) and write visual-spec.md into the package."""
    root = package_dir.resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"package not found: {root}")

    existing = root / "visual-spec.md"
    if only_if_missing and existing.is_file():
        try:
            if existing.read_text(encoding="utf-8").strip():
                return existing
        except OSError:
            pass

    deck = build_deck_context(root)
    # This context is only a compact documentation brief.  Keep the readable
    # package files unchanged, but avoid spending tokens on indentation and
    # repeated whitespace in the one-shot prompt.
    deck_json = json.dumps(deck, ensure_ascii=False, separators=(",", ":"))

    if mock:
        label = ""
        if isinstance(deck.get("label"), dict):
            label = str(deck["label"].get("zh_CN") or deck["label"].get("en_US") or "")
        outline = str(deck.get("visual_spec_outline") or "").strip()
        slides = deck.get("slides") or []
        layouts = [
            str(s.get("layout") or s.get("title") or "")
            for s in slides
            if isinstance(s, dict)
        ]
        md = "\n".join(
            [
                f"# Visual Spec · {label or deck.get('template_id')}",
                "",
                "## Design Read",
                outline or "（mock：无 outline）",
                "",
                "## Layout inventory",
                "- " + "\n- ".join(x for x in layouts if x) if layouts else "- （无 slides）",
                "",
                "## Locked vs editable",
                "- Locked: 结构、装饰、主题色、非槽位样式",
                "- Editable: `data-slot*` 文案与配图",
                "",
                "（mock 模式生成，未调用 LLM）",
                "",
            ]
        )
        return write_visual_spec(root, md)

    # visual-spec is a short documentation task; use the light tier when it is
    # configured, falling back to the heavy tier transparently.
    cfg = llm_light_config()
    pool = make_client_pool(cfg)
    with track_usage() as usage:
        with use_usage(usage):
            raw = chat_text(
                pool=pool,
                model=cfg.model,
                system=prompts.SYSTEM_VISUAL_SPEC,
                user=prompts.user_visual_spec(deck_json=deck_json),
                temperature=0.35,
            )
    return write_visual_spec(root, _strip_fence(raw))
