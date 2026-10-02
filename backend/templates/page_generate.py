"""Generate a new HTML slide into an existing template pack (editor AI chat)."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from config import is_mock, llm_config, load_env
from llm import chat_text, make_client_pool
from templates.page_rewrite import (
    _load_meta,
    _plain,
    _sibling_titles,
    _truncate_html,
    extract_title_hint,
    validate_rewritten_html,
)
from templates.normalize import wrap_bare_text_runs
from templates.sanitize import sanitize_export_css
from usage import track_usage, use_usage

LogFn = Callable[[str], None]

_SLUG_RE = re.compile(r"[^a-zA-Z0-9_\u4e00-\u9fff-]+")

SYSTEM_PAGE_GENERATE = """你是 WebPPT HTML 幻灯片作者。只输出完整 HTML 文档（可含 <!DOCTYPE>），不要 markdown 围栏，不要解释。

硬规则：
1. 画布：根内容容器必须是 1920×1080（class 含 pptx-slide-root 或 slide-container），position:relative，overflow:hidden
2. 必须引用 `<link rel="stylesheet" href="../theme.css" />`；色板与字体尽量用 theme / 邻页气质，禁止另起一套霓虹默认色
3. 只允许本地配图路径 `../images/<已列出的文件名>`；禁止 http(s)、data:、新文件名；无配图清单时不要写 <img>
4. 可见文案与配图容器尽量带 data-slot / data-slot-type / data-slot-role（text|image）
5. 禁止 <script>、外链 CSS、foreignObject、iframe
6. 可用绝对定位 div + 少量 SVG 装饰；按用户要求创作新页面，保持与邻页同一主题气质
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


def _list_pack_images(package_dir: Path) -> list[str]:
    images_dir = package_dir / "images"
    if not images_dir.is_dir():
        return []
    names: list[str] = []
    for p in sorted(images_dir.iterdir()):
        if p.is_file() and p.suffix.lower() in {
            ".png",
            ".jpg",
            ".jpeg",
            ".webp",
            ".gif",
            ".svg",
        }:
            names.append(p.name)
    return names[:40]


def _reference_html(package_dir: Path, meta: dict[str, Any]) -> str:
    slides = meta.get("slides") if isinstance(meta.get("slides"), list) else []
    for item in slides:
        if not isinstance(item, dict):
            continue
        rel = str(item.get("file") or "").strip().lstrip("/")
        if not rel:
            continue
        path = package_dir / rel
        if path.is_file():
            return path.read_text(encoding="utf-8")
    return ""


def _slug_from_issue(issue: str, title_hint: str | None) -> str:
    base = (title_hint or issue or "page").strip()
    base = _SLUG_RE.sub("-", base).strip("-_")[:40] or "page"
    if not re.search(r"[a-zA-Z0-9\u4e00-\u9fff]", base):
        base = "page"
    return base


def _unique_slide_rel(package_dir: Path, meta: dict[str, Any], slug: str) -> str:
    slides = meta.get("slides") if isinstance(meta.get("slides"), list) else []
    existing = {
        str(item.get("file") or "").strip().lstrip("/")
        for item in slides
        if isinstance(item, dict)
    }
    # also avoid colliding with files on disk
    for p in (package_dir / "slides").glob("*.html") if (package_dir / "slides").is_dir() else []:
        existing.add(f"slides/{p.name}")

    candidate = f"slides/{slug}.html"
    if candidate not in existing and not (package_dir / candidate).exists():
        return candidate
    for i in range(2, 200):
        candidate = f"slides/{slug}-{i}.html"
        if candidate not in existing and not (package_dir / candidate).exists():
            return candidate
    raise RuntimeError("无法分配新页面文件名")


def _insert_index(
    meta: dict[str, Any],
    *,
    after_file: str | None,
    after_page_index: int | None,
) -> int:
    slides = meta.get("slides") if isinstance(meta.get("slides"), list) else []
    n = len(slides)
    if after_file:
        rel = after_file.strip().lstrip("/")
        if not rel.startswith("slides/"):
            rel = f"slides/{rel}" if "/" not in rel else rel
        for i, item in enumerate(slides):
            if isinstance(item, dict) and str(item.get("file") or "") == rel:
                return i + 1
    if after_page_index is not None:
        try:
            idx = int(after_page_index)
        except (TypeError, ValueError) as exc:
            raise RuntimeError("afterPageIndex 必须是整数") from exc
        return max(0, min(n, idx + 1))
    return n


def _mock_generate(*, issue: str, theme_ok: bool) -> str:
    note = issue[:120].replace("--", "—")
    bg = "#111" if theme_ok else "#1a1a1a"
    return f"""<!DOCTYPE html>
<html lang="zh">
<head>
  <meta charset="utf-8" />
  <title>new-page</title>
  <link rel="stylesheet" href="../theme.css" />
</head>
<body>
<div class="pptx-slide-root slide" style="position:relative;width:1920px;height:1080px;overflow:hidden;background:{bg};">
  <div data-slot="title" data-slot-type="text" data-slot-role="page-title"
       style="position:absolute;left:80px;top:200px;width:1600px;height:120px;">
    <span style="font-size:48pt;color:#fff;">新页面（mock）</span>
  </div>
  <div data-slot="body" data-slot-type="text" data-slot-role="body"
       style="position:absolute;left:80px;top:360px;width:1600px;height:400px;">
    <span style="font-size:24pt;color:#ddd;">{note}</span>
  </div>
</div>
<!-- page-generate mock: {note} -->
</body>
</html>
"""


def build_generate_user_prompt(
    *,
    issue: str,
    theme_excerpt: str,
    label: str,
    visual_style: str,
    siblings: list[str],
    images: list[str],
    visual_spec_excerpt: str,
    reference_html: str,
    title_hint: str | None,
) -> str:
    img_line = (
        "允许的图片文件（必须原样使用 ../images/<name>）：\n"
        + "\n".join(f"- {n}" for n in images)
        if images
        else "包内暂无配图：不要输出 <img>。"
    )
    sib = "\n".join(f"- {s}" for s in siblings) or "（无，这是首屏或邻页无标题）"
    hint = f"\n建议标题：{title_hint.strip()}" if (title_hint or "").strip() else ""
    return f"""## 模板
id/label: {label}
visual_style: {visual_style or "（未知）"}
{hint}

## 用户要求（必须满足的新页内容）
{issue.strip()}

## 邻页标题（节奏与叙事参考）
{sib}

## 主题 CSS 摘录（只读，服从其色板）
```css
{theme_excerpt}
```

## 可选设计规范摘录
{visual_spec_excerpt or "（无）"}

## {img_line}

## 参考页 HTML（气质参考，勿原样复制整页）
```html
{_truncate_html(reference_html, max_chars=10000) if reference_html else "（无）"}
```

## 任务
创作一页全新完整 HTML（1920×1080），插入到上述模板叙事中；保持 theme 气质；只使用允许的本地图片。
"""


def run_page_generate(
    package: str | Path,
    *,
    issue: str,
    after_file: str | None = None,
    after_page_index: int | None = None,
    title_hint: str | None = None,
    mock: bool | None = None,
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
    slides_dir = package_dir / "slides"
    slides_dir.mkdir(parents=True, exist_ok=True)

    theme_path = package_dir / "theme.css"
    theme = theme_path.read_text(encoding="utf-8") if theme_path.is_file() else ""
    theme_excerpt = theme[:4000]
    images = _list_pack_images(package_dir)
    label_obj = meta.get("label") if isinstance(meta.get("label"), dict) else {}
    label = str(
        label_obj.get("zh_CN")
        or label_obj.get("en_US")
        or meta.get("public_id")
        or meta.get("template_id")
        or package_dir.name
    )
    visual_style = str(meta.get("visual_style") or "")
    siblings = _sibling_titles(meta, "")
    visual_spec = ""
    for name in ("visual_spec.md", "VISUAL_SPEC.md", "design.md"):
        p = package_dir / name
        if p.is_file():
            visual_spec = p.read_text(encoding="utf-8")[:3000]
            break
    reference = _reference_html(package_dir, meta)

    _log(log, f"[generate-page] mock={use_mock} images={len(images)}")

    with track_usage() as usage:
        if use_mock:
            html = _mock_generate(issue=issue, theme_ok=bool(theme))
        else:
            cfg = llm_config()
            if not cfg.api_keys:
                raise RuntimeError("未配置 LLM_API_KEY，无法生成页面（或加 --mock）")
            usage.set_models(page_model=cfg.model)
            pool = make_client_pool(cfg)
            user = build_generate_user_prompt(
                issue=issue,
                theme_excerpt=theme_excerpt,
                label=label,
                visual_style=visual_style,
                siblings=siblings,
                images=images,
                visual_spec_excerpt=visual_spec,
                reference_html=reference,
                title_hint=title_hint,
            )
            with use_usage(usage):
                raw = chat_text(
                    pool=pool,
                    model=cfg.model,
                    system=SYSTEM_PAGE_GENERATE,
                    user=user,
                    temperature=0.55,
                )
            html = _strip_html_fence(raw)

        validate_rewritten_html(html, allowed_images=images)
        san = sanitize_export_css(html, is_theme=False)
        html = san.text
        if san.fixes:
            _log(log, f"[generate-page] sanitize: {'；'.join(san.fixes[:4])}")
        wrapped = wrap_bare_text_runs(html)
        html = wrapped.html
        if wrapped.bare_text_fixes:
            _log(log, f"[generate-page] wrap bare text×{wrapped.bare_text_fixes}")
        validate_rewritten_html(html, allowed_images=images)

        title = (
            (title_hint or "").strip()
            or extract_title_hint(html)
            or _plain(issue)[:40]
            or "新页面"
        )
        slug = _slug_from_issue(issue, title)
        rel = _unique_slide_rel(package_dir, meta, slug)
        slide_path = package_dir / rel
        slide_path.parent.mkdir(parents=True, exist_ok=True)
        slide_path.write_text(html.rstrip() + "\n", encoding="utf-8")

        insert_at = _insert_index(
            meta, after_file=after_file, after_page_index=after_page_index
        )
        slides = meta.get("slides") if isinstance(meta.get("slides"), list) else []
        if not isinstance(slides, list):
            slides = []
        entry = {"file": rel, "title": title, "layout": "content"}
        slides.insert(insert_at, entry)
        meta["slides"] = slides
        meta["last_page_generate"] = {
            "file": rel,
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "issue": issue[:500],
            "insertAt": insert_at,
        }
        meta["usage"] = usage.to_dict()
        (package_dir / "template.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        _log(log, f"[generate-page] wrote {rel} insertAt={insert_at}")

    return {
        "ok": True,
        "template_id": str(
            meta.get("public_id") or meta.get("template_id") or package_dir.name
        ),
        "file": rel,
        "title": title,
        "insertAt": insert_at,
        "usage": usage.to_dict() if not use_mock else None,
    }
