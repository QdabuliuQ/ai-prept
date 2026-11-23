"""Agent 引擎的工作区：状态外置、快照、回滚、trace。

设计要点（见设计文档 §10）：

- **模型不持有状态**。每一步都是"读磁盘 → 决策 → 改磁盘"，
  所以中断可恢复、试错可回滚、失败可归因。
- **快照只复制 SVG 文本**，7 页约 140KB，成本可忽略，这是 agent 敢试错的前提。
"""

from __future__ import annotations

import json
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class WorkspaceError(RuntimeError):
    """工作区状态非法（文件缺失、越界路径等）。"""


def _safe_rel(raw: str) -> str:
    """拒绝路径穿越：只允许 ``slides/xx.svg`` 这类包内相对路径。"""
    text = str(raw or "").strip().replace("\\", "/")
    if not text:
        raise WorkspaceError("文件路径不能为空")
    if text.startswith("/") or ".." in text.split("/"):
        raise WorkspaceError(f"非法文件路径：{raw!r}")
    return text


@dataclass
class StepRecord:
    """一步的 trace 记录。"""

    n: int
    tool: str
    args_digest: str
    ok: bool
    result_digest: str
    elapsed_ms: int
    signature: str = ""


@dataclass
class Workspace:
    """agent 运行期间的全部可变状态。

    ``root`` 是工作目录（放 plan.json / svg / trace / 快照）；
    ``project`` 在 full 模式下由 PPT Master 的 ``project_manager.py init`` 创建，
    是 ``svg_to_pptx.py`` 真正需要的工程目录。
    """

    root: Path
    style: str
    pages: int
    mode: str = "plan"
    project: Path | None = None
    plan: dict[str, Any] | None = None
    trace: list[StepRecord] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    # 预算计数
    llm_calls: int = 0
    tokens: int = 0
    # 快照序号
    _snap_seq: int = 0

    # ---- 构造 ----

    @classmethod
    def create(
        cls,
        root: Path,
        *,
        style: str,
        pages: int,
        mode: str,
    ) -> "Workspace":
        root = Path(root)
        (root / ".agent" / "snapshots").mkdir(parents=True, exist_ok=True)
        (root / "slides").mkdir(parents=True, exist_ok=True)
        (root / "svg_output").mkdir(parents=True, exist_ok=True)
        (root / "images").mkdir(parents=True, exist_ok=True)
        return cls(root=root, style=style, pages=pages, mode=mode)

    # ---- plan ----

    @property
    def plan_path(self) -> Path:
        return self.root / "plan.json"

    def save_plan(self, plan: dict[str, Any]) -> None:
        self.plan = plan
        self.plan_path.write_text(
            json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    def load_plan(self) -> dict[str, Any]:
        if self.plan is not None:
            return self.plan
        if not self.plan_path.is_file():
            raise WorkspaceError("还没有 plan；请先调用 write_plan")
        data = json.loads(self.plan_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise WorkspaceError("plan.json 不是 JSON 对象")
        self.plan = data
        return data

    def slide_files(self) -> list[str]:
        """plan 中声明的页文件（保持顺序）。"""
        plan = self.load_plan()
        out: list[str] = []
        for slide in plan.get("slides") or []:
            if isinstance(slide, dict) and str(slide.get("file") or "").strip():
                out.append(_safe_rel(str(slide["file"])))
        return out

    # ---- 页面读写 ----

    def page_path(self, rel: str) -> Path:
        """plan 里的 ``file`` 是裸文件名（与 ``_validate_plan`` 的规则一致），
        实际落在 ``svg_output/`` 下——这也是 ``svg_quality_checker.py`` 扫描的目录。"""
        name = _safe_rel(rel)
        if "/" in name:
            raise WorkspaceError(
                f"页面文件名只能是裸文件名（如 01_cover.svg），不能带目录：{rel!r}"
            )
        return self.root / "svg_output" / name

    def read_page(self, rel: str) -> str:
        path = self.page_path(rel)
        if not path.is_file():
            raise WorkspaceError(f"页面不存在：{rel}")
        return path.read_text(encoding="utf-8")

    def write_page(self, rel: str, text: str) -> Path:
        path = self.page_path(rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
        return path

    def delete_page(self, rel: str) -> bool:
        path = self.page_path(rel)
        if path.is_file():
            path.unlink()
            return True
        return False

    # ---- 快照 / 回滚 ----

    def snapshot(self, label: str = "") -> str:
        """把当前 slides 复制一份；返回快照名。"""
        self._snap_seq += 1
        name = f"{self._snap_seq:03d}"
        dest = self.root / ".agent" / "snapshots" / name
        if dest.exists():
            shutil.rmtree(dest)
        dest.mkdir(parents=True)
        for path in sorted(self.root.glob("svg_output/*.svg")):
            shutil.copy2(path, dest / path.name)
        if self.plan_path.is_file():
            shutil.copy2(self.plan_path, dest / "plan.json")
        meta = {"label": label, "at": time.time()}
        (dest / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        return name

    def snapshots(self) -> list[str]:
        base = self.root / ".agent" / "snapshots"
        if not base.is_dir():
            return []
        return sorted(p.name for p in base.iterdir() if p.is_dir())

    def rollback(self, name: str) -> None:
        """回滚到指定快照（默认最近一个）。"""
        base = self.root / ".agent" / "snapshots"
        target = base / (name or "")
        if not name:
            names = self.snapshots()
            if not names:
                raise WorkspaceError("没有可用快照")
            target = base / names[-1]
        if not target.is_dir():
            raise WorkspaceError(f"快照不存在：{name}")
        for path in sorted((self.root / "svg_output").glob("*.svg")):
            path.unlink()
        for path in sorted(target.glob("*.svg")):
            shutil.copy2(path, self.root / "svg_output" / path.name)
        plan_copy = target / "plan.json"
        if plan_copy.is_file():
            shutil.copy2(plan_copy, self.plan_path)
            self.plan = None

    # ---- trace ----

    def record_step(
        self,
        *,
        tool: str,
        args: dict[str, Any],
        result: dict[str, Any],
        elapsed_ms: int,
        signature: str = "",
    ) -> StepRecord:
        self.trace.append(
            StepRecord(
                n=len(self.trace) + 1,
                tool=tool,
                args_digest=digest(args),
                ok=bool(result.get("ok")),
                result_digest=digest(result),
                elapsed_ms=elapsed_ms,
                signature=signature,
            )
        )
        line = {
            "n": self.trace[-1].n,
            "tool": tool,
            "args": self.trace[-1].args_digest,
            "ok": self.trace[-1].ok,
            "result": self.trace[-1].result_digest,
            "ms": elapsed_ms,
            "signature": signature,
        }
        trace_path = self.root / ".agent" / "trace.jsonl"
        with trace_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(line, ensure_ascii=False) + "\n")
        return self.trace[-1]

    def recent_signatures(self, n: int = 2) -> list[str]:
        return [s.signature for s in self.trace[-n:] if s.signature]

    def stalled(self, threshold: int = 2) -> bool:
        """连续 ``threshold`` 步签名相同 → 视为卡死。"""
        sigs = [s.signature for s in self.trace[-threshold:]]
        return len(sigs) >= threshold and len(set(sigs)) == 1 and bool(sigs[0])


def digest(payload: Any, limit: int = 240) -> str:
    """稳定、可读的摘要：用于 trace 与停滞检测，不参与业务逻辑。"""
    try:
        text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        text = str(payload)
    return text[:limit]
