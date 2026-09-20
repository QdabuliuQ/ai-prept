"""模板包 format 常量与判定。"""

from __future__ import annotations

FORMAT_HTML_SLIDE = "html-slide"


def normalize_package_format(value: str | None) -> str:
    """仅保留 html-slide；任意输入归一为此轨。"""
    _ = value
    return FORMAT_HTML_SLIDE
