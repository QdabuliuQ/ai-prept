"""Homepage remix workspaces: temporary packs under workspace/<id>/."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import admin.fsutil as fsutil
from templates.remix import remix_template_package


SAMPLE_HTML = """<!DOCTYPE html>
<html><body>
<div class="pptx-slide-root" style="width:1920px;height:1080px;background:#111">
  <div data-slot="title" data-slot-type="text" data-slot-role="page-title"
       style="position:absolute;left:100px;top:200px;width:800px;height:80px">
    <div><span style="font-size:40pt;color:#fff">原标题ABC</span></div>
  </div>
</div>
</body></html>
"""


def _make_source(root: Path, name: str = "源模板A") -> Path:
    src = root / name
    (src / "slides").mkdir(parents=True)
    (src / "images").mkdir()
    (src / "slides" / "cover.html").write_text(SAMPLE_HTML, encoding="utf-8")
    (src / "theme.css").write_text(":root{--color-bg:#111;}\n", encoding="utf-8")
    (src / "visual-spec.md").write_text("# 视觉规范\n主色深灰。\n", encoding="utf-8")
    meta = {
        "schema_version": "1.0",
        "template_id": name,
        "format": "ppt-master",
        "label": {"zh_CN": name, "en_US": "A"},
        "description": {"zh_CN": "desc", "en_US": "desc"},
        "status": "approved",
        "files": {
            "theme_css": "theme.css",
            "slides_dir": "slides",
            "images_dir": "images",
        },
        "slides": [
            {
                "file": "slides/cover.html",
                "title": "原标题ABC",
                "layout": "cover",
                "description": "cover",
            }
        ],
    }
    (src / "template.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return src


def test_list_template_ids_skips_sessions(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(fsutil, "templates_root", lambda: tmp_path)
    catalog = tmp_path / "catalogTpl"
    catalog.mkdir()
    (catalog / "template.json").write_text('{"template_id":"catalogTpl"}\n', encoding="utf-8")
    sess = tmp_path / "sessions" / "sessTpl"
    sess.mkdir(parents=True)
    (sess / "template.json").write_text('{"template_id":"sessTpl"}\n', encoding="utf-8")

    ids = fsutil.list_template_ids()
    assert ids == ["catalogTpl"]
    assert "sessTpl" not in ids


def test_template_dir_resolves_workspace(tmp_path: Path, monkeypatch) -> None:
    catalog_root = tmp_path / "agent-output"
    ws_root = tmp_path / "workspace"
    catalog_root.mkdir()
    monkeypatch.setattr(fsutil, "templates_root", lambda: catalog_root)
    monkeypatch.setattr(
        fsutil, "workspace_root", lambda ensure=True: (ws_root.mkdir(parents=True, exist_ok=True) or ws_root)
    )
    pack = ws_root / "abc12345"
    pack.mkdir(parents=True)
    (pack / "template.json").write_text('{"template_id":"abc12345"}\n', encoding="utf-8")

    assert fsutil.template_dir("abc12345") == pack
    assert fsutil.is_workspace_template("abc12345") is True
    assert fsutil.is_session_template("abc12345") is True


def test_template_dir_resolves_legacy_sessions(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(fsutil, "templates_root", lambda: tmp_path)
    monkeypatch.setattr(
        fsutil,
        "workspace_root",
        lambda ensure=True: tmp_path / "workspace-empty",
    )
    sess = tmp_path / "sessions" / "abc12345"
    sess.mkdir(parents=True)
    (sess / "template.json").write_text('{"template_id":"abc12345"}\n', encoding="utf-8")

    assert fsutil.template_dir("abc12345") == sess
    assert fsutil.is_session_template("abc12345") is True


def test_cleanup_expired_workspaces(tmp_path: Path, monkeypatch) -> None:
    ws = tmp_path / "workspace"
    monkeypatch.setattr(fsutil, "templates_root", lambda: tmp_path / "agent-output")
    monkeypatch.setattr(
        fsutil, "workspace_root", lambda ensure=True: (ws.mkdir(parents=True, exist_ok=True) or ws)
    )
    (tmp_path / "agent-output" / "sessions").mkdir(parents=True)

    old = ws / "oldpack"
    new = ws / "newpack"
    old.mkdir(parents=True)
    new.mkdir(parents=True)
    (old / "template.json").write_text("{}\n", encoding="utf-8")
    (new / "template.json").write_text("{}\n", encoding="utf-8")
    old_mtime = time.time() - 10 * 24 * 3600
    os.utime(old, (old_mtime, old_mtime))

    removed = fsutil.cleanup_expired_workspaces(ttl_seconds=7 * 24 * 3600)
    assert removed == 1
    assert not old.exists()
    assert new.exists()


def test_ephemeral_remix_marks_session_meta(tmp_path: Path) -> None:
    src = _make_source(tmp_path)
    out_root = tmp_path / "workspace"
    row = remix_template_package(
        src,
        prompt="智能穿戴新品发布会",
        out_root=out_root,
        mock=True,
        skip_images=True,
        status="approved",
        ephemeral=True,
    )
    assert row["ok"] is True
    dest = Path(row["output_dir"])
    assert dest.parent == out_root
    meta = json.loads((dest / "template.json").read_text(encoding="utf-8"))
    assert meta["ephemeral"] is True
    assert meta["status"] == "approved"
    assert meta["storage"]["backend"] == "session"
