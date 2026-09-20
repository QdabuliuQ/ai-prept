from __future__ import annotations

import os
from pathlib import Path

_EXCERPTS_DIR = Path(__file__).resolve().parent / "excerpts"


def resolve_skill_root(explicit: str | Path | None = None) -> Path:
    """Skill 内容根目录（lessons / LEARNED_LESSONS 等）。

    ``DOM_TO_PPTX_SKILL_ROOT`` / 显式路径仅在指定时覆盖。
    """
    raw = str(explicit) if explicit is not None else None
    raw = raw or os.environ.get("DOM_TO_PPTX_SKILL_ROOT")
    if raw:
        path = Path(raw).expanduser().resolve()
        if path.is_dir():
            return path
        raise FileNotFoundError(f"skill 目录不存在: {path}")

    if _EXCERPTS_DIR.is_dir():
        return _EXCERPTS_DIR.resolve()

    raise FileNotFoundError(
        f"skill excerpts 不存在: {_EXCERPTS_DIR}\n"
        "请确认 agent 包完整，或设置 DOM_TO_PPTX_SKILL_ROOT。"
    )
