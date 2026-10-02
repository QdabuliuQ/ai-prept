"""In-place single-page HTML rewrite for Admin preview feedback.

Allows text + layout/decoration changes while keeping theme.css colors,
1920×1080 canvas, and existing local image filenames (no rematerialize).
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from config import is_mock, llm_config, load_env
from llm import chat_text, make_client_pool
from templates.normalize import wrap_bare_text_runs
from templates.sanitize import sanitize_export_css
from usage import track_usage, use_usage

LogFn = Callable[[str], None]

_IMG_REF_RE = re.compile(
    r"""(?:src|data-src|href)=["'](\.\./images/([^"'?#]+))""",
    re.I,
)
_TITLE_SLOT_RE = re.compile(
    r"""data-slot=["']title["'][^>]*>.*?"""
    r"""<span\b[^>]*>(.*?)</span>""",
    re.I | re.S,
)
_SPAN_PLAIN_RE = re.compile(r"<span\b[^>]*>(.*?)</span>", re.I | re.S)
_TAG_RE = re.compile(r"<[^>]+>")

SYSTEM_PAGE_REWRITE = """你是 WebPPT HTML 幻灯片作者。只输出完整 HTML 文档（可含 <!DOCTYPE>），不要 markdown 围栏，不要解释。

硬规则：
1. 画布：根内容容器必须是 1920×1080（class 含 pptx-slide-root 或 slide-container），position:relative，overflow:hidden
2. 必须引用 `<link rel="stylesheet" href="../theme.css" />`；色板与字体尽量用 theme / 原稿配色，禁止另起一套霓虹默认色
3. 只允许本地配图路径 `../images/<已列出的文件名>`；禁止 http(s)、data:、新文件名；无配图清单时不要写 <img>
4. 可见文案与配图容器尽量带 data-slot / data-slot-type / data-slot-role（text|image）
5. 禁止 <script>、外链 CSS、foreignObject、iframe
6. 可用绝对定位 div + 少量 SVG 装饰；按「用户问题」修正文案与版式，可调整构图，但保持同一主题气质
7. 输出必须是可独立打开的完整 HTML（html/head/body）
8. 可见文案必须包在元素里：优先兄弟 `<span data-element="text">…</span>`；禁止在含有子元素的容器里再挂裸文本（例如 `<div>前缀<span>强调</span></div>` 必须写成两个 span）
"""


def _log(log: LogFn | None, msg: str) -> None:
    if log:
        log(msg if msg.endswith("\n") else msg + "\n")


def _strip_html_fence(raw: str) -> str:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:html|HTML)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _plain(html_fragment: str) -> str:
    text = _TAG_RE.sub(" ", html_fragment or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def list_image_files(html: str) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for m in _IMG_REF_RE.finditer(html or ""):
        name = (m.group(2) or "").strip()
        if name and name not in seen:
            seen.add(name)
            names.append(name)
    return names


def extract_title_hint(html: str) -> str | None:
    m = _TITLE_SLOT_RE.search(html or "")
    if m:
        t = _plain(m.group(1))
        if t:
            return t[:80]
    for m in _SPAN_PLAIN_RE.finditer(html or ""):
        t = _plain(m.group(1))
        if 4 <= len(t) <= 40:
            return t
    return None


def _slot_text_inventory(html: str, *, limit: int = 12) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for m in re.finditer(
        r"""<div\b([^>]*\bdata-slot=["']([^"']+)["'][^>]*)>(.*?)</div>""",
        html or "",
        re.I | re.S,
    ):
        attrs, slot, inner = m.group(1), m.group(2), m.group(3)
        if "data-slot-type" in attrs.lower() and 'image"' in attrs.lower().replace(
            " ", ""
        ):
            continue
        if re.search(r'data-slot-type\s*=\s*["\']image["\']', attrs, re.I):
            continue
        text = _plain(inner)
        if not text:
            continue
        rows.append({"slot": slot, "text": text[:200]})
        if len(rows) >= limit:
            break
    return rows


def _truncate_html(html: str, *, max_chars: int = 14000) -> str:
    text = html or ""
    if len(text) <= max_chars:
        return text
    head = max_chars * 3 // 4
    tail = max_chars - head - 80
    return (
        text[:head]
        + "\n\n<!-- … middle truncated for prompt … -->\n\n"
        + text[-tail:]
    )


def validate_rewritten_html(
    html: str,
    *,
    allowed_images: list[str],
) -> None:
    low = (html or "").lower()
    if "<html" not in low or "<body" not in low:
        raise RuntimeError("重写结果缺少 html/body")
    if "theme.css" not in low:
        raise RuntimeError("重写结果未引用 ../theme.css")
    if "1920" not in html or "1080" not in html:
        raise RuntimeError("重写结果缺少 1920×1080 画布")
    if "<script" in low:
        raise RuntimeError("重写结果禁止包含 script")
    allowed = set(allowed_images)
    for m in _IMG_REF_RE.finditer(html):
        name = (m.group(2) or "").strip()
        if name not in allowed:
            raise RuntimeError(f"重写结果引用了未允许的图片：{name}")
        href = m.group(1) or ""
        if href.startswith("http") or href.startswith("data:"):
            raise RuntimeError("重写结果禁止外链/data 图片")


def _mock_rewrite(html: str, issue: str) -> str:
    note = (
        f'\n<!-- page-rewrite mock: {issue[:200].replace("--", "—")} -->\n'
    )
    if "</body>" in html.lower():
        idx = html.lower().rfind("</body>")
        return html[:idx] + note + html[idx:]
    return html + note


def _load_meta(package_dir: Path) -> dict[str, Any]:
    path = package_dir / "template.json"
    if not path.is_file():
        raise RuntimeError(f"缺少 template.json：{package_dir}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError("template.json 不是 object")
    return data


def _resolve_slide_file(
    meta: dict[str, Any],
    package_dir: Path,
    *,
    slide_file: str | None,
    page_index: int | None,
) -> tuple[str, Path]:
    slides = meta.get("slides") if isinstance(meta.get("slides"), list) else []
    rel = (slide_file or "").strip().lstrip("/")
    if not rel and page_index is not None:
        idx = int(page_index)
        if idx < 0 or idx >= len(slides):
            raise RuntimeError(f"pageIndex 越界：{idx}")
        item = slides[idx] if isinstance(slides[idx], dict) else {}
        rel = str(item.get("file") or "").strip().lstrip("/")
    if not rel:
        raise RuntimeError("缺少 slide file / pageIndex")
    if not rel.startswith("slides/"):
        rel = f"slides/{rel}" if "/" not in rel else rel
    path = (package_dir / rel).resolve()
    root = package_dir.resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise RuntimeError("非法 slide 路径") from exc
    if not path.is_file():
        raise RuntimeError(f"页面不存在：{rel}")
    return rel, path


def _sibling_titles(meta: dict[str, Any], current_file: str) -> list[str]:
    out: list[str] = []
    for item in meta.get("slides") or []:
        if not isinstance(item, dict):
            continue
        f = str(item.get("file") or "")
        if f == current_file:
            continue
        title = str(item.get("title") or "").strip()
        if title:
            out.append(f"{f}: {title}")
    return out[:12]


def build_user_prompt(
    *,
    issue: str,
    slide_file: str,
    html: str,
    theme_excerpt: str,
    label: str,
    visual_style: str,
    siblings: list[str],
    images: list[str],
    slot_texts: list[dict[str, str]],
    visual_spec_excerpt: str,
    target_element: dict[str, Any] | None = None,
) -> str:
    from templates.element_target import format_target_for_prompt

    img_line = (
        "允许的图片文件（必须原样使用 ../images/<name>）：\n"
        + "\n".join(f"- {n}" for n in images)
        if images
        else "本页无配图：不要输出 <img>。"
    )
    slots_json = json.dumps(slot_texts, ensure_ascii=False, indent=2)
    sib = "\n".join(f"- {s}" for s in siblings) or "（无）"
    target_block = format_target_for_prompt(target_element)
    target_section = f"\n{target_block}\n" if target_block else ""
    return f"""## 模板
id/label: {label}
visual_style: {visual_style or "（未知）"}
当前页文件: {slide_file}

## 用户问题（必须解决）
{issue.strip()}
{target_section}
## 邻页标题（节奏参考）
{sib}

## 主题 CSS 摘录（只读，服从其色板）
```css
{theme_excerpt}
```

## 可选设计规范摘录
{visual_spec_excerpt or "（无）"}

## 本页现有文案槽（参考，可改写）
{slots_json}

## {img_line}

## 当前页 HTML（可能截断）
```html
{_truncate_html(html)}
```

## 任务
输出修正后的完整 HTML。解决用户问题；可调整版式与装饰；保留 theme 气质与允许的本地图片。
若提供了「选中元素」，优先只改该元素及其必要周边，避免无关整页重排。
"""


def run_page_rewrite(
    package: str | Path,
    *,
    slide_file: str | None = None,
    page_index: int | None = None,
    issue: str,
    mock: bool | None = None,
    target_element: dict[str, Any] | None = None,
    log: LogFn | None = None,
) -> dict[str, Any]:
    load_env()
    package_dir = Path(package).expanduser().resolve()
    if not package_dir.is_dir():
        raise RuntimeError(f"模板目录不存在：{package_dir}")
    issue = (issue or "").strip()
    if len(issue) < 4:
        raise RuntimeError("问题描述太短")
    if len(issue) > 2000:
        raise RuntimeError("问题描述过长（最多 2000 字）")

    use_mock = is_mock() if mock is None else bool(mock)
    meta = _load_meta(package_dir)
    rel, slide_path = _resolve_slide_file(
        meta, package_dir, slide_file=slide_file, page_index=page_index
    )
    original = slide_path.read_text(encoding="utf-8")
    if not original.strip():
        raise RuntimeError(f"页面为空：{rel}")

    theme_path = package_dir / "theme.css"
    theme = theme_path.read_text(encoding="utf-8") if theme_path.is_file() else ""
    theme_excerpt = theme[:4000]
    spec_path = package_dir / "visual-spec.md"
    visual_spec = ""
    if spec_path.is_file():
        visual_spec = spec_path.read_text(encoding="utf-8")[:2500]

    label = ""
    lab = meta.get("label")
    if isinstance(lab, dict):
        label = str(lab.get("zh_CN") or lab.get("en_US") or "").strip()
    label = label or str(meta.get("template_id") or package_dir.name)
    visual_style = str(
        meta.get("visual_style")
        or meta.get("category")
        or meta.get("style")
        or ""
    ).strip()

    images = list_image_files(original)
    # Only keep files that still exist
    images = [n for n in images if (package_dir / "images" / n).is_file()]
    slot_texts = _slot_text_inventory(original)
    siblings = _sibling_titles(meta, rel)

    _log(log, f"[rewrite-page] file={rel} mock={use_mock} images={len(images)}")

    with track_usage() as usage:
        if use_mock:
            rewritten = _mock_rewrite(original, issue)
        else:
            cfg = llm_config()
            if not cfg.api_keys:
                raise RuntimeError("未配置 LLM_API_KEY，无法重写页面（或加 --mock）")
            usage.set_models(page_model=cfg.model)
            pool = make_client_pool(cfg)
            user = build_user_prompt(
                issue=issue,
                slide_file=rel,
                html=original,
                theme_excerpt=theme_excerpt,
                label=label,
                visual_style=visual_style,
                siblings=siblings,
                images=images,
                slot_texts=slot_texts,
                visual_spec_excerpt=visual_spec,
                target_element=target_element,
            )
            with use_usage(usage):
                raw = chat_text(
                    pool=pool,
                    model=cfg.model,
                    system=SYSTEM_PAGE_REWRITE,
                    user=user,
                    temperature=0.4,
                )
            rewritten = _strip_html_fence(raw)

        validate_rewritten_html(rewritten, allowed_images=images)
        san = sanitize_export_css(rewritten, is_theme=False)
        rewritten = san.text
        if san.fixes:
            _log(log, f"[rewrite-page] sanitize: {'；'.join(san.fixes[:4])}")
        wrapped = wrap_bare_text_runs(rewritten)
        rewritten = wrapped.html
        if wrapped.bare_text_fixes:
            _log(
                log,
                f"[rewrite-page] wrap bare text×{wrapped.bare_text_fixes}",
            )
        validate_rewritten_html(rewritten, allowed_images=images)

        slide_path.write_text(rewritten.rstrip() + "\n", encoding="utf-8")
        _log(log, f"[rewrite-page] wrote {rel}")

        # Update template.json
        title_hint = extract_title_hint(rewritten) or extract_title_hint(original)
        slides = meta.get("slides") if isinstance(meta.get("slides"), list) else []
        for item in slides:
            if isinstance(item, dict) and str(item.get("file") or "") == rel:
                if title_hint:
                    item["title"] = title_hint
                break
        meta["last_page_rewrite"] = {
            "file": rel,
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "issue": issue[:500],
        }
        meta["usage"] = usage.to_dict()
        (package_dir / "template.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    return {
        "ok": True,
        "template_id": str(meta.get("public_id") or meta.get("template_id") or package_dir.name),
        "file": rel,
        "title": title_hint,
        "usage": usage.to_dict() if not use_mock else None,
    }
