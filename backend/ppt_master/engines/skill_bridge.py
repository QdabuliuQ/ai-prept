"""PPT Master Skill 的真实访问实现。

仓库对 Skill 的依赖只有 4 个脚本 + 1 个风格卡目录（见设计文档附录 B）。
这里把路径解析集中一处，引擎通过 ``SkillBridge`` 抽象使用，
测试可注入替身而不必解压 Skill。
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Callable

from ppt_master.engines.base import EngineError, SkillBridge
from ppt_master.paths import (
    assert_ppt_master_ready,
    ppt_master_python,
    ppt_master_root,
    repo_root,
    skill_dir,
)

LogFn = Callable[[str], None]


class LocalSkillBridge(SkillBridge):
    """直接调用本地 ``ppt-master/skills/ppt-master/`` 下的脚本。"""

    def __init__(self, log: LogFn | None = None) -> None:
        self._log_fn = log

    def _log(self, msg: str) -> None:
        if self._log_fn:
            self._log_fn(msg)

    # ---- 前置 ----

    def ready(self) -> None:
        try:
            assert_ppt_master_ready()
        except FileNotFoundError as exc:
            raise EngineError(str(exc)) from exc

    # ---- 脚手架 ----

    def init_project(self, name: str) -> Path:
        from ppt_master.pipeline import _init_project

        return _init_project(name, self._log)

    # ---- 风格卡（只读） ----

    def catalog(self) -> list[dict[str, Any]]:
        from ppt_master.styles import load_catalog

        data = load_catalog()
        styles = data.get("styles") if isinstance(data, dict) else None
        if not isinstance(styles, list):
            return []
        return [s for s in styles if isinstance(s, dict) and s.get("id")]

    def style_card(self, style_id: str) -> str:
        from ppt_master.styles import load_style_card

        return load_style_card(style_id)

    def quality_report(
        self,
        project: Path,
        *,
        file_name: str | None = None,
    ) -> tuple[bool, dict[str, Any]]:
        skill = skill_dir()
        script = skill / "scripts" / "svg_quality_checker.py"
        argv = [
            str(ppt_master_python()),
            str(script),
            str(project),
            "--quick-generate",
            "--stage",
            "page" if file_name else "final",
        ]
        if file_name:
            argv += ["--page", file_name]
        argv.append("--json")
        self._log(f"$ {' '.join(argv)}")

        proc = subprocess.run(
            argv,
            cwd=str(ppt_master_root()),
            capture_output=True,
            text=True,
        )
        if proc.stdout:
            self._log(proc.stdout.rstrip())
        if proc.stderr:
            self._log(proc.stderr.rstrip())

        report_name = "svg_quality_page_report.json" if file_name else "svg_quality_report.json"
        report_path = Path(project) / "validation" / report_name
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"质量检查未生成有效报告：{exc}") from exc
        if not isinstance(report, dict):
            raise RuntimeError("质量检查报告不是 JSON 对象")
        return proc.returncode == 0, report

    # ---- 导出 ----

    def export_argv(
        self,
        project: Path,
        pptx_out: Path,
        *,
        flags: list[str],
    ) -> list[str]:
        skill = skill_dir()
        return [
            str(ppt_master_python()),
            str(skill / "scripts" / "svg_to_pptx.py"),
            str(project),
            *flags,
            "--no-notes",
            "-o",
            str(pptx_out),
        ]

    def export_pptx(
        self,
        project: Path,
        pptx_out: Path,
        *,
        flags: list[str],
    ) -> None:
        pptx_out.parent.mkdir(parents=True, exist_ok=True)
        argv = self.export_argv(project, pptx_out, flags=flags)
        self._log(f"$ {' '.join(argv)}")
        proc = subprocess.run(
            argv,
            cwd=str(ppt_master_root()),
            capture_output=True,
            text=True,
        )
        if proc.stdout:
            self._log(proc.stdout.rstrip())
        if proc.stderr:
            self._log(proc.stderr.rstrip())
        if proc.returncode != 0:
            raise RuntimeError(
                f"svg_to_pptx 失败（{proc.returncode}）：{' '.join(argv)}"
            )
