from __future__ import annotations

import json
from pathlib import Path

from image.generate import (
    collect_local_images,
    extract_theme_colors,
    materialize_images,
)
from templates.normalize import normalize_slide_html
from templates.sanitize import sanitize_export_css
from templates.types import TemplatePackage
from usage import current_usage, track_usage


def _persist_meta(package: TemplatePackage, out_dir: Path) -> None:
    u = current_usage()
    if u is not None:
        package.usage = u.to_dict()
    (out_dir / "template.json").write_text(
        json.dumps(package.to_template_json(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def write_package(
    package: TemplatePackage,
    out_dir: Path,
    *,
    skip_images: bool = False,
) -> Path:
    return _write_html_package(package, out_dir, skip_images=skip_images)


def _write_html_package(
    package: TemplatePackage,
    out_dir: Path,
    *,
    skip_images: bool = False,
) -> Path:
    out_dir = out_dir.resolve()
    slides_dir = out_dir / "slides"
    images_dir = out_dir / "images"
    slides_dir.mkdir(parents=True, exist_ok=True)
    images_dir.mkdir(parents=True, exist_ok=True)

    _persist_meta(package, out_dir)
    if package.visual_spec.strip():
        (out_dir / "visual-spec.md").write_text(
            package.visual_spec.rstrip() + "\n", encoding="utf-8"
        )

    theme_san = sanitize_export_css(package.theme_css, is_theme=True)
    if theme_san.fixes:
        package.theme_css = theme_san.text
        package.warnings.append(
            "已净化 theme.css: " + "；".join(theme_san.fixes)
        )
    (out_dir / "theme.css").write_text(
        package.theme_css.rstrip() + "\n", encoding="utf-8"
    )

    auto_fixed: list[str] = []
    bounds_fixed: list[str] = []
    for slide in package.slides:
        normalized = normalize_slide_html(slide.html)
        if normalized.rotated_text_fixes or normalized.bounds_fixes:
            slide.html = normalized.html
        if normalized.rotated_text_fixes:
            auto_fixed.append(
                f"{slide.file} ×{normalized.rotated_text_fixes}"
            )
        if normalized.bounds_fixes:
            bounds_fixed.append(
                f"{slide.file} ×{normalized.bounds_fixes}"
            )
        html_san = sanitize_export_css(slide.html, is_theme=False)
        if html_san.fixes:
            slide.html = html_san.text
            package.warnings.append(
                f"已净化 {slide.file}: " + "；".join(html_san.fixes)
            )
        path = out_dir / slide.file
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(slide.html.rstrip() + "\n", encoding="utf-8")

    if auto_fixed:
        package.warnings.append(
            "已自动扁平化旋转文字容器: " + ", ".join(auto_fixed)
        )
    if bounds_fixed:
        package.warnings.append(
            "已将易越界的 bottom+rotate 竖排改为 writing-mode: "
            + ", ".join(bounds_fixed)
        )

    if not skip_images:
        refs = collect_local_images([s.html for s in package.slides])
        style_hint = " ".join(
            [
                package.label_zh,
                package.description_zh[:80],
                (package.visual_spec_outline or package.visual_spec)[:200],
            ]
        ).strip()
        theme_colors = extract_theme_colors(package.theme_css)
        warnings = materialize_images(
            images_dir,
            refs,
            style_hint=style_hint,
            bg_hex=theme_colors.get("bg"),
            theme_colors=theme_colors,
        )
        package.warnings.extend(warnings)

    _persist_meta(package, out_dir)
    return out_dir


def rematerialize_package_images(out_dir: Path) -> list[str]:
    """仅补齐/重试配图，不重跑 LLM。用于 batch 隔离图片失败。"""
    out_dir = out_dir.resolve()
    meta_path = out_dir / "template.json"
    if not meta_path.is_file():
        raise FileNotFoundError(f"缺少 template.json: {out_dir}")

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    slides_meta = meta.get("slides") or []
    htmls: list[str] = []
    for slide in slides_meta:
        rel = str((slide or {}).get("file") or "").strip()
        if rel:
            path = out_dir / rel
            if path.is_file():
                htmls.append(path.read_text(encoding="utf-8"))

    refs = collect_local_images(htmls)
    theme_css = ""
    theme_path = out_dir / "theme.css"
    if theme_path.is_file():
        theme_css = theme_path.read_text(encoding="utf-8")
    visual_spec = ""
    spec_path = out_dir / "visual-spec.md"
    if spec_path.is_file():
        visual_spec = spec_path.read_text(encoding="utf-8")

    label = (meta.get("label") or {}).get("zh_CN") or meta.get("template_id") or ""
    desc = (meta.get("description") or {}).get("zh_CN") or ""
    outline = str(meta.get("visual_spec_outline") or "")
    style_hint = " ".join(
        [str(label), str(desc)[:80], (visual_spec or outline)[:200]]
    ).strip()
    theme_colors = extract_theme_colors(theme_css)
    with track_usage() as usage:
        warnings = materialize_images(
            out_dir / "images",
            refs,
            style_hint=style_hint,
            bg_hex=theme_colors.get("bg"),
            theme_colors=theme_colors,
        )
        meta["usage"] = usage.merge_into(
            meta.get("usage") if isinstance(meta.get("usage"), dict) else None
        )
    if warnings:
        existing = list(meta.get("warnings") or [])
        meta["warnings"] = existing + warnings
    meta_path.write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return warnings
