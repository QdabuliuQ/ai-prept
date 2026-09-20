from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_LAYOUTS: tuple[str, ...] = (
    "cover",
    "agenda-rail",
    "section-band",
    "media-bleed",
    "kpi-band",
    "bento-3",
    "steps-h",
    "vs-split",
    "manifesto",
    "proof-rail",
    "matrix-2x2",
    "closing",
)


@dataclass
class SlideSpec:
    layout: str
    title: str
    description: str
    html: str

    @property
    def file(self) -> str:
        return f"slides/{self.layout}.html"


@dataclass
class TemplatePackage:
    template_id: str
    label_zh: str
    label_en: str
    description_zh: str
    description_en: str
    theme_css: str
    slides: list[SlideSpec] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    source_kind: str = "original"
    source_file: str = ""
    """生成期不写 visual-spec.md；保留 outline 供后续上传时生成。"""
    visual_spec_outline: str = ""
    """若已有正文（上传生成后），write 时可落盘；空则跳过文件。"""
    visual_spec: str = ""
    """页面 LLM / 图片用量，写入 template.json.usage。"""
    usage: dict[str, Any] | None = None
    """html-slide"""
    format: str = "html-slide"

    def to_template_json(self) -> dict[str, Any]:
        files: dict[str, str] = {
            "theme_css": "theme.css",
            "images_dir": "images",
            "slides_dir": "slides",
            # 约定路径：上传/补生成时写入，当前可不存在
            "visual_spec": "visual-spec.md",
        }
        slides_meta: list[dict[str, Any]] = [
            {
                "file": s.file,
                "title": s.title,
                "layout": s.layout,
                "description": s.description,
            }
            for s in self.slides
        ]
        meta: dict[str, Any] = {
            "schema_version": "1.0",
            "template_id": self.template_id,
            "format": self.format,
            "label": {
                "zh_CN": self.label_zh,
                "en_US": self.label_en,
            },
            "description": {
                "zh_CN": self.description_zh,
                "en_US": self.description_en,
            },
            "files": files,
            "slides": slides_meta,
            "source": {
                "kind": self.source_kind,
                "file": self.source_file,
                "canvas": {"width": 1920, "height": 1080},
            },
            "warnings": list(self.warnings),
        }
        if self.visual_spec_outline.strip():
            meta["visual_spec_outline"] = self.visual_spec_outline.strip()
        if self.usage:
            meta["usage"] = self.usage
        return meta


@dataclass
class RunResult:
    out_dir: Path
    package: TemplatePackage
    issues: list[str] = field(default_factory=list)
