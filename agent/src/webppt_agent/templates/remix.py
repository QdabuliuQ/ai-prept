"""Layout-preserving template remix: clone HTML pack, swap text/images only.

Keeps theme.css, absolute layout geometry, decorative SVG shapes, and slot
structure. Only innermost text runs and image refs change.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import shutil
from pathlib import Path
from typing import Any, Callable

from webppt_agent.config import is_mock, load_env
from webppt_agent.llm import chat_json, make_client_pool

LogFn = Callable[[str], None]

_SLOT_OPEN_RE = re.compile(
    r"""<div\b(?P<attrs>[^>]*?\bdata-slot\s*=\s*["'](?P<slot>[^"']+)["'][^>]*?)>""",
    re.I | re.S,
)
_TYPE_RE = re.compile(r"""\bdata-slot-type\s*=\s*["']([^"']+)["']""", re.I)
_ROLE_RE = re.compile(r"""\bdata-slot-role\s*=\s*["']([^"']+)["']""", re.I)
_SPAN_RE = re.compile(r"(<span\b[^>]*>)(.*?)(</span>)", re.I | re.S)
_IMG_SRC_RE = re.compile(
    r"""\b(?:src|data-src|href)=["'](\.\./images/([^"'?#]+))(?:[?#][^"']*)?["']""",
    re.I,
)
_ALT_ATTR_RE = re.compile(r"""\b(?:alt|data-alt)=["']([^"']*)["']""", re.I)
_SAFE_ID_RE = re.compile(r"[^\w\u4e00-\u9fff.-]+", re.UNICODE)


def _log(log: LogFn | None, msg: str) -> None:
    if log:
        log(msg if msg.endswith("\n") else msg + "\n")


def _find_matching_close(html: str, open_end: int) -> int:
    """Return index after the closing </div> that matches the open tag ending at open_end."""
    i = open_end
    depth = 1
    lower = html.lower()
    n = len(html)
    while i < n and depth > 0:
        next_open = lower.find("<div", i)
        next_close = lower.find("</div>", i)
        if next_close < 0:
            return n
        if next_open >= 0 and next_open < next_close:
            # skip if it's a self-closing-ish or comment; treat as open
            gt = html.find(">", next_open)
            if gt < 0:
                return n
            # ignore </div already handled; only real opens
            if not lower.startswith("</", next_open):
                depth += 1
            i = gt + 1
            continue
        depth -= 1
        i = next_close + len("</div>")
    return i


def _plain_text_from_spans(inner: str) -> str:
    parts: list[str] = []
    for m in _SPAN_RE.finditer(inner):
        t = re.sub(r"\s+", " ", (m.group(2) or "")).strip()
        if t:
            parts.append(t)
    if parts:
        return "\n".join(parts)
    # fallback: strip tags
    text = re.sub(r"<[^>]+>", " ", inner)
    return re.sub(r"\s+", " ", text).strip()


def _replace_span_texts(inner: str, new_text: str) -> str:
    """Replace leaf span texts; distribute multi-line content across existing spans."""
    spans = list(_SPAN_RE.finditer(inner))
    if not spans:
        return inner
    lines = [ln.strip() for ln in str(new_text or "").splitlines() if ln.strip()]
    if not lines:
        lines = [str(new_text or "").strip() or " "]
    if len(spans) == 1:
        m = spans[0]
        joined = " ".join(lines) if len(lines) > 1 and "\n" not in (new_text or "") else "\n".join(lines)
        # single span: prefer space-join for one-liners
        if len(lines) == 1:
            joined = lines[0]
        else:
            # keep first line only in single-span boxes to avoid overflow
            joined = lines[0] if len("".join(lines)) > 80 else " ".join(lines)
        return inner[: m.start()] + m.group(1) + joined + m.group(3) + inner[m.end() :]

    out: list[str] = []
    last = 0
    for i, m in enumerate(spans):
        out.append(inner[last : m.start()])
        content = lines[i] if i < len(lines) else ("" if i > 0 else lines[0])
        if i == len(spans) - 1 and len(lines) > len(spans):
            content = " ".join(lines[i:])
        out.append(m.group(1) + content + m.group(3))
        last = m.end()
    out.append(inner[last:])
    return "".join(out)


def inventory_slide_slots(html: str, *, file: str) -> list[dict[str, Any]]:
    """Return text/image slots for one slide HTML."""
    slots: list[dict[str, Any]] = []
    seen: set[str] = set()
    for m in _SLOT_OPEN_RE.finditer(html):
        attrs = m.group("attrs") or ""
        slot = (m.group("slot") or "").strip()
        if not slot:
            continue
        type_m = _TYPE_RE.search(attrs)
        slot_type = (type_m.group(1) if type_m else "text").strip().lower()
        role_m = _ROLE_RE.search(attrs)
        role = (role_m.group(1) if role_m else "").strip()
        open_end = m.end()
        close_end = _find_matching_close(html, open_end)
        inner = html[open_end:close_end]
        # trim trailing closing tag from inner for content ops
        close_tag = inner.rfind("</div>")
        content = inner[:close_tag] if close_tag >= 0 else inner
        key = f"{file}::{slot}"
        if key in seen:
            # uniquify duplicates
            n = 2
            while f"{file}::{slot}-{n}" in seen:
                n += 1
            slot = f"{slot}-{n}"
            key = f"{file}::{slot}"
        seen.add(key)
        if slot_type == "image":
            src_m = _IMG_SRC_RE.search(content)
            alt_m = _ALT_ATTR_RE.search(content)
            slots.append(
                {
                    "file": file,
                    "slot": slot,
                    "type": "image",
                    "role": role or "image",
                    "src": src_m.group(1) if src_m else "",
                    "filename": src_m.group(2) if src_m else "",
                    "current": (alt_m.group(1) if alt_m else "").strip(),
                    "max_chars": 120,
                }
            )
        else:
            text = _plain_text_from_spans(content)
            if not text and slot_type != "text":
                continue
            slots.append(
                {
                    "file": file,
                    "slot": slot,
                    "type": "text",
                    "role": role or "body",
                    "current": text,
                    "max_chars": max(12, min(200, int(len(text) * 1.4) or 40)),
                }
            )
    return slots


def inventory_package_slots(pack_dir: Path) -> list[dict[str, Any]]:
    meta = json.loads((pack_dir / "template.json").read_text(encoding="utf-8"))
    slides = meta.get("slides") if isinstance(meta.get("slides"), list) else []
    out: list[dict[str, Any]] = []
    for slide in slides:
        if not isinstance(slide, dict):
            continue
        rel = str(slide.get("file") or "").strip()
        if not rel:
            continue
        path = pack_dir / rel
        if not path.is_file():
            continue
        html = path.read_text(encoding="utf-8")
        out.extend(inventory_slide_slots(html, file=rel))
    return out


def apply_text_to_html(html: str, updates: dict[str, str]) -> str:
    """Apply slot→text map; preserve non-slot markup."""
    if not updates:
        return html
    # Process from end to start so indices stay valid
    matches: list[tuple[int, int, int, str, str]] = []
    for m in _SLOT_OPEN_RE.finditer(html):
        attrs = m.group("attrs") or ""
        slot = (m.group("slot") or "").strip()
        type_m = _TYPE_RE.search(attrs)
        slot_type = (type_m.group(1) if type_m else "text").strip().lower()
        if slot_type == "image":
            continue
        if slot not in updates:
            continue
        open_start = m.start()
        open_end = m.end()
        close_end = _find_matching_close(html, open_end)
        matches.append((open_start, open_end, close_end, slot, updates[slot]))

    # de-dupe by slot keeping first occurrence order but apply last-to-first by position
    matches.sort(key=lambda x: x[0], reverse=True)
    used: set[str] = set()
    out = html
    for open_start, open_end, close_end, slot, new_text in matches:
        if slot in used:
            continue
        used.add(slot)
        inner_with_close = out[open_end:close_end]
        close_tag = inner_with_close.rfind("</div>")
        if close_tag < 0:
            continue
        content = inner_with_close[:close_tag]
        tail = inner_with_close[close_tag:]
        new_content = _replace_span_texts(content, new_text)
        out = out[:open_end] + new_content + tail + out[close_end:]
    return out


def apply_image_hints_to_html(
    html: str, updates: dict[str, str]
) -> tuple[str, list[str]]:
    """Update image slot alt/prompts; return (html, filenames to regenerate)."""
    regen: list[str] = []
    if not updates:
        return html, regen
    matches: list[tuple[int, int, int, str, str]] = []
    for m in _SLOT_OPEN_RE.finditer(html):
        attrs = m.group("attrs") or ""
        slot = (m.group("slot") or "").strip()
        type_m = _TYPE_RE.search(attrs)
        slot_type = (type_m.group(1) if type_m else "text").strip().lower()
        if slot_type != "image" or slot not in updates:
            continue
        open_end = m.end()
        close_end = _find_matching_close(html, open_end)
        matches.append((m.start(), open_end, close_end, slot, updates[slot]))
    matches.sort(key=lambda x: x[0], reverse=True)
    used: set[str] = set()
    out = html
    for _os, open_end, close_end, slot, hint in matches:
        if slot in used:
            continue
        used.add(slot)
        region = out[open_end:close_end]
        src_m = _IMG_SRC_RE.search(region)
        if src_m:
            regen.append(src_m.group(2))
        hint_clean = re.sub(r"\s+", " ", hint).strip()[:300]

        if _ALT_ATTR_RE.search(region):
            region2 = _ALT_ATTR_RE.sub(lambda _am: f'alt="{hint_clean}"', region, count=1)
        else:
            # inject alt onto first img-like tag
            region2 = re.sub(
                r"(<(?:img|image|div)\b)",
                rf'\1 alt="{hint_clean}"',
                region,
                count=1,
                flags=re.I,
            )
        out = out[:open_end] + region2 + out[close_end:]
    return out, regen


def _safe_template_id(label: str, *, fallback: str) -> str:
    raw = (label or "").strip() or fallback
    raw = _SAFE_ID_RE.sub("", raw).strip(".-_")[:48]
    return raw or fallback[:48] or f"remix-{secrets.token_hex(3)}"


def _unique_out_dir(out_root: Path, base: str) -> tuple[str, Path]:
    candidate = (base or "remix").strip() or "remix"
    for i in range(0, 80):
        name = candidate if i == 0 else f"{candidate}-{i + 1}"
        dest = out_root / name
        if not dest.exists():
            return name, dest
    name = f"{candidate}-{secrets.token_hex(3)}"
    return name, out_root / name


def _copy_package(source_dir: Path, dest: Path) -> None:
    """Copy pack; never merge into an existing directory."""
    if dest.exists():
        raise FileExistsError(str(dest))
    shutil.copytree(source_dir, dest)


def _mock_fill(slots: list[dict[str, Any]], prompt: str) -> dict[str, Any]:
    short = re.sub(r"\s+", " ", prompt).strip()[:24] or "新主题"
    texts: dict[str, dict[str, str]] = {}
    images: dict[str, dict[str, str]] = {}
    for s in slots:
        file = str(s["file"])
        if s["type"] == "image":
            images.setdefault(file, {})[s["slot"]] = f"{short} · {s.get('role') or 'image'}"
        else:
            role = str(s.get("role") or "body")
            cur = str(s.get("current") or "")
            max_c = int(s.get("max_chars") or 40)
            if role in {"page-title", "heading", "title"}:
                val = short[:max_c]
            elif role in {"lede", "subtitle"}:
                val = f"{short}相关内容与要点"[:max_c]
            else:
                val = (f"{short}：{cur}" if cur else short)[:max_c]
            texts.setdefault(file, {})[s["slot"]] = val
    return {
        "label_zh": short,
        "description_zh": f"基于模板改写：{short}",
        "texts": texts,
        "images": images,
    }


def _plan_content(
    *,
    prompt: str,
    slots: list[dict[str, Any]],
    source_label: str,
    pages: list[dict[str, Any]],
    visual_brief: str,
    mock: bool,
    log: LogFn | None,
) -> dict[str, Any]:
    if mock or is_mock():
        return _mock_fill(slots, prompt)

    compact_slots = [
        {
            "file": s["file"],
            "slot": s["slot"],
            "type": s["type"],
            "role": s.get("role"),
            "current": (s.get("current") or "")[:160],
            "max_chars": s.get("max_chars"),
        }
        for s in slots
    ]
    page_outline = [
        {
            "file": p.get("file"),
            "title": p.get("title"),
            "layout": p.get("layout"),
        }
        for p in pages
        if isinstance(p, dict)
    ]
    system = (
        "你是模板内容改写器。只输出 JSON。"
        "必须保留参考模板的页数、版式与槽位；只改文案与配图主题。"
        "禁止新增/删除 slot；禁止改颜色、布局或装饰。"
    )
    user = f"""参考模板：{source_label}
用户新主题/要求：
{prompt}

视觉规范摘要（只作语气参考，不要改版式）：
{(visual_brief or '')[:3500]}

页面列表：
{json.dumps(page_outline, ensure_ascii=False)}

可写槽位（必须全部覆盖 text；image 给生图提示词）：
{json.dumps(compact_slots, ensure_ascii=False)}

输出 JSON：
{{
  "label_zh": "新模板中文名（内容主题，不要写风格词）",
  "description_zh": "一句话描述",
  "texts": {{ "slides/cover.html": {{ "title": "新文案", "subtitle": "..." }} }},
  "images": {{ "slides/cover.html": {{ "hero-image": "英文或中文生图提示，描述画面内容" }} }}
}}
约束：
1. texts 的每个 file/slot 必须出现；文案长度尽量不超过 max_chars。
2. 不要输出 HTML；不要解释。
3. 数字/指标可按新主题合理改写。
"""
    from webppt_agent.config import llm_config

    cfg = llm_config()
    pool = make_client_pool(cfg)
    _log(log, f"[remix] planning slots={len(slots)} model={cfg.model}")
    raw = chat_json(
        pool=pool,
        model=cfg.model,
        system=system,
        user=user,
        temperature=0.4,
    )
    if not isinstance(raw, dict):
        raise RuntimeError("remix plan 不是 JSON 对象")
    return raw


def remix_template_package(
    source_dir: Path,
    *,
    prompt: str,
    out_root: Path | None = None,
    mock: bool | None = None,
    skip_images: bool = False,
    log: LogFn | None = None,
) -> dict[str, Any]:
    """Clone source pack and rewrite text/image slots for prompt."""
    load_env()
    source_dir = source_dir.resolve()
    if not (source_dir / "template.json").is_file():
        raise FileNotFoundError(f"不是有效模板包：{source_dir}")
    use_mock = is_mock() if mock is None else bool(mock)
    out_root = (out_root or source_dir.parent).resolve()
    out_root.mkdir(parents=True, exist_ok=True)

    meta = json.loads((source_dir / "template.json").read_text(encoding="utf-8"))
    source_id = str(meta.get("template_id") or source_dir.name)
    source_label = str((meta.get("label") or {}).get("zh_CN") or source_id)
    pages = meta.get("slides") if isinstance(meta.get("slides"), list) else []

    visual_brief = ""
    for name in ("visual-spec.md", "theme.css"):
        p = source_dir / name
        if p.is_file():
            visual_brief += f"\n## {name}\n" + p.read_text(encoding="utf-8")[:4000]

    slots = inventory_package_slots(source_dir)
    text_slots = [s for s in slots if s["type"] == "text"]
    image_slots = [s for s in slots if s["type"] == "image"]
    _log(
        log,
        f"[remix] source={source_id} text_slots={len(text_slots)} "
        f"image_slots={len(image_slots)} skip_images={skip_images}",
    )
    if not text_slots and not image_slots:
        raise RuntimeError(
            "源模板没有 data-slot 文本/图片槽，无法做保版式改写。"
            "请换用带 data-slot 的 ppt-master 包，或先重新转换。"
        )

    plan = _plan_content(
        prompt=prompt,
        slots=slots,
        source_label=source_label,
        pages=pages if isinstance(pages, list) else [],
        visual_brief=visual_brief,
        mock=use_mock,
        log=log,
    )
    label_zh = str(plan.get("label_zh") or "").strip() or f"{source_label}-改写"
    desc_zh = str(plan.get("description_zh") or "").strip() or f"基于「{source_label}」改写"
    texts_by_file = plan.get("texts") if isinstance(plan.get("texts"), dict) else {}
    images_by_file = plan.get("images") if isinstance(plan.get("images"), dict) else {}

    new_id, dest = _unique_out_dir(
        out_root, _safe_template_id(label_zh, fallback=source_id)
    )
    # Extra guard: never overwrite an existing catalog pack (same label collision).
    for _ in range(20):
        if not dest.exists():
            break
        new_id, dest = _unique_out_dir(out_root, f"{new_id}-套用")
    _log(log, f"[remix] cloning → {dest.name}")
    try:
        _copy_package(source_dir, dest)
    except FileExistsError:
        new_id, dest = _unique_out_dir(
            out_root, f"{_safe_template_id(label_zh, fallback=source_id)}-套用"
        )
        _log(log, f"[remix] dest busy, retry → {dest.name}")
        _copy_package(source_dir, dest)

    # drop qiniu/upload provenance from clone
    try:
        new_meta = json.loads((dest / "template.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise RuntimeError(f"克隆后 template.json 损坏: {e}") from e

    regen_files: list[str] = []
    for slide in pages if isinstance(pages, list) else []:
        if not isinstance(slide, dict):
            continue
        rel = str(slide.get("file") or "").strip()
        if not rel:
            continue
        path = dest / rel
        if not path.is_file():
            continue
        html = path.read_text(encoding="utf-8")
        file_texts = texts_by_file.get(rel) if isinstance(texts_by_file.get(rel), dict) else {}
        # also accept flat keys without path prefix
        if not file_texts:
            file_texts = {
                s["slot"]: texts_by_file.get(s["slot"])
                for s in text_slots
                if s["file"] == rel and isinstance(texts_by_file.get(s["slot"]), str)
            }
        file_texts = {str(k): str(v) for k, v in (file_texts or {}).items() if v is not None}
        html = apply_text_to_html(html, file_texts)

        file_imgs = images_by_file.get(rel) if isinstance(images_by_file.get(rel), dict) else {}
        file_imgs = {str(k): str(v) for k, v in (file_imgs or {}).items() if v}
        if file_imgs and not skip_images:
            html, regen = apply_image_hints_to_html(html, file_imgs)
            regen_files.extend(regen)
        path.write_text(html if html.endswith("\n") else html + "\n", encoding="utf-8")

        # update slide title from page-title / title slot when present
        title_val = (
            file_texts.get("title")
            or file_texts.get("page-title")
            or next((file_texts[k] for k in file_texts if "title" in k), None)
        )
        if title_val:
            slide["title"] = str(title_val)[:80]

    new_meta["template_id"] = new_id
    new_meta["label"] = {"zh_CN": label_zh, "en_US": label_zh}
    new_meta["description"] = {
        "zh_CN": desc_zh,
        "en_US": desc_zh,
    }
    new_meta["status"] = "pending"
    new_meta["source_template_id"] = source_id
    new_meta["remix"] = {
        "mode": "content-slots",
        "source_template_id": source_id,
        "prompt": prompt[:2000],
    }
    new_meta.pop("storage", None)
    new_meta.pop("preview", None)
    if isinstance(pages, list):
        new_meta["slides"] = pages

    # force image regen: delete listed files so materialize rewrites them
    if regen_files and not skip_images and not use_mock:
        images_dir = dest / "images"
        for name in set(regen_files):
            fp = images_dir / name
            if fp.is_file():
                try:
                    fp.unlink()
                except OSError:
                    pass
        _log(log, f"[remix] rematerialize images ×{len(set(regen_files))}")
        try:
            from webppt_agent.templates.write import rematerialize_package_images

            warnings = rematerialize_package_images(dest)
            for w in warnings:
                _log(log, f"[remix] image warn: {w}")
        except Exception as e:
            _log(log, f"[remix] image rematerialize skipped: {e}")
    elif skip_images:
        _log(log, "[remix] images kept (skip)")

    (dest / "template.json").write_text(
        json.dumps(new_meta, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    # Bump directory mtime so Admin list (sorted by folder time) surfaces this pack.
    try:
        os.utime(dest, None)
    except OSError:
        pass
    _log(log, f"[remix] wrote {dest}")
    _log(log, f"[progress] done=1 total=1 ok=1 fail=0 skip=0 id={new_id} status=ok")
    return {
        "ok": True,
        "template_id": new_id,
        "output_dir": str(dest),
        "source_template_id": source_id,
        "text_slots": len(text_slots),
        "image_slots": len(image_slots),
        "label_zh": label_zh,
    }


def run_remix(
    source_id: str,
    prompt: str,
    *,
    out_root: Path | None = None,
    mock: bool | None = None,
    skip_images: bool = False,
    log: LogFn | None = None,
) -> dict[str, Any]:
    from webppt_agent.ppt_master.paths import repo_root

    default_root = (repo_root() / "agent-output").resolve()
    root = (out_root or default_root).resolve()
    source_dir = Path(source_id)
    if not source_dir.is_absolute():
        # Prefer canonical catalog under agent-output/, even when writing elsewhere.
        candidate = default_root / source_id
        if (candidate / "template.json").is_file():
            source_dir = candidate
        else:
            source_dir = root / source_id
    return remix_template_package(
        source_dir,
        prompt=prompt,
        out_root=root,
        mock=mock,
        skip_images=skip_images,
        log=log,
    )
