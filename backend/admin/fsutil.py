"""Filesystem helpers for agent-output templates."""

from __future__ import annotations

import json
import re
import shutil
import time
from pathlib import Path
from typing import Any

SAFE_TEMPLATE_DIR = re.compile(r"^[A-Za-z0-9._\u4e00-\u9fff-]+$")
# agent-output 下保留名；首页临时包已迁到仓库根 workspace/
RESERVED_OUTPUT_DIRS = {"admin-jobs", "packs", "templates", "sessions"}
PUBLIC_ID_RE = re.compile(r"^[A-Za-z0-9]{8,}$")
# 首页会话包默认保留 7 天
SESSION_TTL_SECONDS = 7 * 24 * 3600
WORKSPACE_TTL_SECONDS = SESSION_TTL_SECONDS


def repo_root() -> Path:
    # backend/admin/fsutil.py → parents[2] = repo root
    return Path(__file__).resolve().parents[2]


def templates_root() -> Path:
    return repo_root() / "agent-output"


def workspace_root(*, ensure: bool = True) -> Path:
    """首页 remix 临时输出根：workspace/<id>/（不在 agent-output 下）。"""
    d = repo_root() / "workspace"
    if ensure:
        d.mkdir(parents=True, exist_ok=True)
    return d


def sessions_root(*, ensure: bool = True) -> Path:
    """Legacy：agent-output/sessions/<id>/。新包请用 workspace_root()。"""
    d = templates_root() / "sessions"
    if ensure:
        d.mkdir(parents=True, exist_ok=True)
    return d


def jobs_dir() -> Path:
    d = templates_root() / "admin-jobs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def template_dir(template_id: str) -> Path:
    """Resolve package dir: catalog → workspace → legacy sessions → catalog default."""
    catalog = templates_root() / template_id
    if (catalog / "template.json").is_file():
        return catalog
    workspace = workspace_root(ensure=False) / template_id
    if (workspace / "template.json").is_file():
        return workspace
    session = sessions_root(ensure=False) / template_id
    if (session / "template.json").is_file():
        return session
    return catalog


def is_workspace_template(template_id: str) -> bool:
    """True when the package lives under workspace/ (or legacy sessions/)."""
    if not SAFE_TEMPLATE_DIR.match(template_id):
        return False
    catalog = templates_root() / template_id
    if (catalog / "template.json").is_file():
        return False
    workspace = workspace_root(ensure=False) / template_id
    if (workspace / "template.json").is_file():
        return True
    session = sessions_root(ensure=False) / template_id
    return (session / "template.json").is_file()


def is_session_template(template_id: str) -> bool:
    """Alias for is_workspace_template (legacy name)."""
    return is_workspace_template(template_id)


def cleanup_expired_workspaces(
    *,
    ttl_seconds: int = WORKSPACE_TTL_SECONDS,
    now: float | None = None,
) -> int:
    """Delete workspace/ (+ legacy sessions/) packages older than ttl."""
    removed = 0
    cutoff = (now if now is not None else time.time()) - max(60, int(ttl_seconds))
    for root in (workspace_root(ensure=False), sessions_root(ensure=False)):
        if not root.is_dir():
            continue
        for entry in root.iterdir():
            if not entry.is_dir() or entry.name.startswith("."):
                continue
            try:
                mtime = entry.stat().st_mtime
            except OSError:
                continue
            if mtime >= cutoff:
                continue
            try:
                shutil.rmtree(entry)
                removed += 1
            except OSError:
                continue
    return removed


def cleanup_expired_sessions(
    *,
    ttl_seconds: int = SESSION_TTL_SECONDS,
    now: float | None = None,
) -> int:
    """Alias: cleans workspace/ and legacy sessions/."""
    return cleanup_expired_workspaces(ttl_seconds=ttl_seconds, now=now)


def resolve_under(template_id: str, rel: str) -> Path | None:
    if not SAFE_TEMPLATE_DIR.match(template_id):
        return None
    root = template_dir(template_id).resolve()
    target = (root / rel).resolve()
    if target != root and not str(target).startswith(str(root) + "/"):
        return None
    return target


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def read_meta(template_id: str) -> dict[str, Any] | None:
    path = resolve_under(template_id, "template.json")
    if not path or not path.is_file():
        return None
    try:
        data = read_json(path)
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def write_meta(template_id: str, meta: dict[str, Any]) -> None:
    path = resolve_under(template_id, "template.json")
    if not path:
        raise ValueError("非法模板 id")
    write_json(path, meta)


def list_template_ids() -> list[str]:
    root = templates_root()
    if not root.is_dir():
        return []
    out: list[str] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        if entry.name in RESERVED_OUTPUT_DIRS:
            continue
        if not SAFE_TEMPLATE_DIR.match(entry.name):
            continue
        if (entry / "template.json").is_file():
            out.append(entry.name)
    return out


def template_mtime_ms(template_id: str) -> int:
    root = template_dir(template_id)
    best = 0.0
    try:
        best = root.stat().st_mtime
    except OSError:
        return 0
    try:
        best = max(best, (root / "template.json").stat().st_mtime)
    except OSError:
        pass
    return int(best * 1000)


def effective_status(meta: dict[str, Any] | None) -> str:
    if not meta:
        return "approved"
    status = meta.get("status")
    if isinstance(status, str) and status.strip():
        return status.strip()
    return "approved"


def effective_format(meta: dict[str, Any] | None) -> str:
    raw = str((meta or {}).get("format") or "").strip()
    if raw == "ppt-master":
        return "ppt-master"
    return "html-slide"


def effective_render(meta: dict[str, Any] | None) -> str:
    """页面渲染形态：html-slide | svg | svg-fallback。

    svg-fallback = svg_to_pptx / 转 HTML 失败后的整页 SVG 预览包，不可当标准 html-slide。
    """
    if not meta:
        return "unknown"
    raw = str(meta.get("render") or "").strip().lower()
    if raw in {"svg-fallback", "html-slide", "svg"}:
        return raw
    if raw in {"html", "dom"}:
        return "html-slide"

    source = meta.get("source") if isinstance(meta.get("source"), dict) else {}
    kind = str(source.get("kind") or "").lower()
    if "svg-fallback" in kind:
        return "svg-fallback"

    warnings = meta.get("warnings") if isinstance(meta.get("warnings"), list) else []
    for w in warnings:
        text = str(w)
        if "export_fallback=svg" in text or "svg-fallback" in text.lower():
            return "svg-fallback"

    review = meta.get("review") if isinstance(meta.get("review"), dict) else {}
    note = str(review.get("note") or "")
    if "SVG 预览" in note or "svg-fallback" in note.lower():
        return "svg-fallback"

    fmt = effective_format(meta)
    if fmt == "html-slide":
        return "html-slide"
    if fmt == "ppt-master":
        return "svg"
    return raw or "unknown"


def html_slide_count(meta: dict[str, Any]) -> int:
    slides = meta.get("slides") or []
    if not isinstance(slides, list):
        return 0
    return sum(
        1
        for s in slides
        if isinstance(s, dict)
        and str(s.get("file") or "").lower().endswith(".html")
    )


_TREE_SKIP_NAMES = {
    ".DS_Store",
    "__pycache__",
    ".git",
    "node_modules",
    ".turbo",
    # 编辑器文件树不展示：预览图、源包、压缩包目录
    "previews",
    "source",
}
_TREE_SKIP_FILE_NAMES = {
    "source.pptx",
}
_TREE_SKIP_FILE_SUFFIXES = (".zip", ".pptx")
_TREE_MAX_ENTRIES = 800
_TREE_MAX_DEPTH = 5


def build_template_tree(
    root: Path,
    *,
    rel: str = "",
    depth: int = 0,
    counter: list[int] | None = None,
) -> list[dict[str, Any]]:
    """Walk template package into nested {name,type,path,children?} nodes."""
    if counter is None:
        counter = [0]
    if depth > _TREE_MAX_DEPTH or counter[0] >= _TREE_MAX_ENTRIES:
        return []
    try:
        entries = sorted(
            root.iterdir(),
            key=lambda p: (not p.is_dir(), p.name.lower()),
        )
    except OSError:
        return []

    nodes: list[dict[str, Any]] = []
    for entry in entries:
        if counter[0] >= _TREE_MAX_ENTRIES:
            break
        name = entry.name
        if name.startswith(".") or name in _TREE_SKIP_NAMES:
            continue
        if entry.is_file():
            lower = name.lower()
            if lower in _TREE_SKIP_FILE_NAMES or lower.endswith(
                _TREE_SKIP_FILE_SUFFIXES
            ):
                continue
        child_rel = f"{rel}/{name}" if rel else name
        counter[0] += 1
        if entry.is_dir():
            children = build_template_tree(
                entry,
                rel=child_rel,
                depth=depth + 1,
                counter=counter,
            )
            nodes.append(
                {
                    "name": name,
                    "type": "dir",
                    "path": child_rel,
                    "children": children,
                }
            )
        elif entry.is_file():
            try:
                size = entry.stat().st_size
            except OSError:
                size = 0
            nodes.append(
                {
                    "name": name,
                    "type": "file",
                    "path": child_rel,
                    "size": size,
                }
            )
    return nodes


def list_template_tree(template_id: str) -> list[dict[str, Any]] | None:
    """Return package file tree, or None if package is missing."""
    if not SAFE_TEMPLATE_DIR.match(template_id):
        return None
    root = template_dir(template_id)
    if not root.is_dir() or not (root / "template.json").is_file():
        return None
    return build_template_tree(root)
