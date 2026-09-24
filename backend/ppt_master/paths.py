"""PPT Master 路径解析（仓库根下 ppt-master/）。"""

from __future__ import annotations

import os
from pathlib import Path


def repo_root() -> Path:
    # backend/ppt_master/paths.py → parents[2] = repo root
    return Path(__file__).resolve().parents[2]


def ppt_master_root() -> Path:
    env = os.environ.get("PPT_MASTER_ROOT", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    return (repo_root() / "ppt-master").resolve()


def skill_dir() -> Path:
    env = os.environ.get("PPT_MASTER_SKILL_DIR", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    return ppt_master_root() / "skills" / "ppt-master"


def ppt_master_python() -> Path:
    env = os.environ.get("PPT_MASTER_PYTHON", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    root = ppt_master_root()
    for cand in (
        root / ".venv" / "bin" / "python",
        root / ".venv" / "Scripts" / "python.exe",
    ):
        if cand.is_file():
            return cand
    return Path(os.environ.get("PYTHON", "python3"))


def assert_ppt_master_ready() -> None:
    skill = skill_dir()
    if not (skill / "SKILL.md").is_file():
        raise FileNotFoundError(
            f"未找到 PPT Master Skill：{skill / 'SKILL.md'}\n"
            "请将 ZIP 解压到仓库根目录 ppt-master/，或设置 PPT_MASTER_ROOT。"
        )
    for name in (
        "scripts/project_manager.py",
        "scripts/svg_to_pptx.py",
        "scripts/svg_quality_checker.py",
    ):
        if not (skill / name).is_file():
            raise FileNotFoundError(f"PPT Master 脚本缺失：{skill / name}")
