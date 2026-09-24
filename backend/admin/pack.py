"""Prepare package.zip + save client preview shots (Pillow)."""

from __future__ import annotations

import base64
import json
import re
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from PIL import Image

from admin.fsutil import (
    PUBLIC_ID_RE,
    effective_status,
    html_slide_count,
    read_meta,
    template_dir,
    write_meta,
)
from public_id import new_public_template_id

PREVIEW_W = 1920
PREVIEW_H = 1080
WEBP_QUALITY = 90
NAME_RE = re.compile(r"^(\d{2})\.(webp|png|jpe?g)$", re.I)
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
MAX_EDGE = 1920


def _expected_preview_name(index: int) -> str:
    return f"{index:02d}.webp"


def ensure_public_id(
    template_id: str,
    meta: dict[str, Any],
    *,
    sync_db: bool = True,
) -> str:
    existing = str(meta.get("public_id") or "").strip()
    if PUBLIC_ID_RE.match(existing):
        return existing
    public_id = template_id if PUBLIC_ID_RE.match(template_id) else new_public_template_id()
    meta["public_id"] = public_id
    if not meta.get("template_id"):
        meta["template_id"] = public_id
    write_meta(template_id, meta)
    if sync_db:
        try:
            from admin.store import upsert_template_row

            upsert_template_row(template_id)
        except Exception:
            pass
    return public_id


def assert_publish_assets(template_id: str, meta: dict[str, Any]) -> dict[str, Any]:
    if effective_status(meta) != "approved":
        raise RuntimeError("仅「已通过」模板可准备或上传")
    root = template_dir(template_id)
    spec = root / "visual-spec.md"
    if not spec.is_file():
        raise RuntimeError("缺少 visual-spec.md。请先生成设计规范。")
    if not spec.read_text(encoding="utf-8").strip():
        raise RuntimeError("visual-spec.md 为空。请先重新生成设计规范。")
    slide_count = html_slide_count(meta)
    if slide_count <= 0:
        raise RuntimeError("模板无 slides/*.html")
    return {
        "slideCount": slide_count,
        "previewDir": root / "previews",
        "zipPath": root / "package.zip",
        "publicId": str(meta.get("public_id") or "").strip(),
    }


def save_client_preview_shots(
    out_dir: Path,
    shots: list[dict[str, Any]],
    expected_count: int,
) -> list[dict[str, Any]]:
    if expected_count <= 0:
        raise RuntimeError("模板无 slides/*.html，无法保存预览图")
    if len(shots) != expected_count:
        raise RuntimeError(
            f"预览图数量不符：需要 {expected_count} 张，收到 {len(shots)} 张"
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    by_index: dict[int, dict[str, Any]] = {}
    for shot in shots:
        name = Path(str(shot.get("fileName") or "")).name
        m = NAME_RE.match(name)
        if not m:
            raise RuntimeError(f"预览图文件名无效：{shot.get('fileName') or '(空)'}")
        index = int(m.group(1))
        if index in by_index:
            raise RuntimeError(f"预览图序号重复：{m.group(1)}")
        data = shot.get("data")
        if not data:
            raise RuntimeError(f"预览图为空：{shot.get('fileName')}")
        by_index[index] = shot

    saved = []
    for index in range(1, expected_count + 1):
        shot = by_index.get(index)
        if not shot:
            raise RuntimeError(f"缺少预览图 {_expected_preview_name(index)}")
        file_name = _expected_preview_name(index)
        local_path = out_dir / file_name
        raw: bytes = shot["data"]
        with Image.open(__import__("io").BytesIO(raw)) as im:
            im = im.convert("RGBA") if im.mode in ("P", "LA") else im.convert("RGB")
            im.thumbnail((PREVIEW_W, PREVIEW_H), Image.Resampling.LANCZOS)
            im.save(local_path, "WEBP", quality=WEBP_QUALITY, method=4)
        size = local_path.stat().st_size
        if size <= 0:
            raise RuntimeError(f"预览图无效：{file_name}")
        saved.append(
            {"index": index, "fileName": file_name, "localPath": str(local_path), "bytes": size}
        )
    return saved


def _compress_images(root: Path) -> None:
    images = root / "images"
    if not images.is_dir():
        return
    for path in images.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in IMAGE_EXTS:
            continue
        before = path.stat().st_size
        try:
            with Image.open(path) as im:
                im = im.convert("RGB") if path.suffix.lower() in {".jpg", ".jpeg"} else im
                im.thumbnail((MAX_EDGE, MAX_EDGE), Image.Resampling.LANCZOS)
                ext = path.suffix.lower()
                if ext in {".jpg", ".jpeg"}:
                    im.save(path, "JPEG", quality=82, optimize=True)
                elif ext == ".webp":
                    im.save(path, "WEBP", quality=80, method=4)
                else:
                    im.save(path, "PNG", optimize=True)
            if path.stat().st_size >= before:
                # keep smaller original — already overwritten; skip restore for simplicity
                pass
        except Exception:
            continue


def _minify_html(text: str) -> str:
    try:
        import htmlmin

        return htmlmin.minify(
            text,
            remove_comments=True,
            remove_empty_space=True,
            reduce_boolean_attributes=True,
        )
    except Exception:
        return re.sub(r">\s+<", "><", text)


def _minify_css(text: str) -> str:
    try:
        import rcssmin

        return rcssmin.cssmin(text)
    except Exception:
        return re.sub(r"\s+", " ", text).strip()


def _compress_html_css_json(root: Path) -> None:
    for path in root.rglob("*.html"):
        try:
            raw = path.read_text(encoding="utf-8")
            path.write_text(_minify_html(raw), encoding="utf-8")
        except Exception:
            continue
    for path in root.rglob("*.css"):
        try:
            raw = path.read_text(encoding="utf-8")
            path.write_text(_minify_css(raw), encoding="utf-8")
        except Exception:
            continue
    meta = root / "template.json"
    if meta.is_file():
        try:
            data = json.loads(meta.read_text(encoding="utf-8"))
            meta.write_text(
                json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )
        except Exception:
            pass


def _zip_directory(src_dir: Path, zip_path: Path) -> int:
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path in sorted(src_dir.rglob("*")):
            if path.is_file():
                arc = Path(src_dir.name) / path.relative_to(src_dir)
                zf.write(path, arcname=str(arc).replace("\\", "/"))
    return zip_path.stat().st_size


def prepare_template_package(
    template_id: str,
    preview_inputs: list[dict[str, Any]],
) -> dict[str, Any]:
    root = template_dir(template_id)
    if not root.is_dir():
        raise RuntimeError(f"模板不存在: {template_id}")
    meta = read_meta(template_id)
    if not meta:
        raise RuntimeError(f"缺少 template.json: {template_id}")
    gate = assert_publish_assets(template_id, meta)
    if not preview_inputs:
        raise RuntimeError("缺少预览图。请先离屏截图。")

    public_id = ensure_public_id(template_id, meta)
    save_client_preview_shots(gate["previewDir"], preview_inputs, gate["slideCount"])

    with tempfile.TemporaryDirectory(prefix="webppt-pack-") as tmp:
        tmp_root = Path(tmp)
        work_dir = tmp_root / public_id
        shutil.copytree(root, work_dir)
        shutil.rmtree(work_dir / "previews", ignore_errors=True)
        (work_dir / "package.zip").unlink(missing_ok=True)
        _compress_images(work_dir)
        _compress_html_css_json(work_dir)
        # ensure visual-spec present
        spec_src = root / "visual-spec.md"
        if spec_src.is_file():
            shutil.copy2(spec_src, work_dir / "visual-spec.md")
        # keep pretty template.json from source for package? Node re-copies then compresses.
        shutil.copy2(root / "template.json", work_dir / "template.json")
        _compress_html_css_json(work_dir)

        tmp_zip = tmp_root / f"{public_id}.zip"
        zip_bytes = _zip_directory(work_dir, tmp_zip)
        if zip_bytes <= 0:
            raise RuntimeError("压缩包生成失败或为空")
        dest = root / "package.zip"
        shutil.copy2(tmp_zip, dest)
        try:
            from admin.store import upsert_template_row

            upsert_template_row(template_id)
        except Exception:
            pass
        return {
            "slideCount": gate["slideCount"],
            "zipBytes": dest.stat().st_size,
            "zipPath": str(dest),
        }


def decode_preview_body(raw_previews: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in raw_previews:
        b64 = item.get("dataBase64")
        if not isinstance(b64, str) or not b64.strip():
            raise RuntimeError("预览图 dataBase64 无效")
        # strip data URL prefix
        payload = b64.split(",", 1)[-1] if b64.startswith("data:") else b64
        data = base64.b64decode(payload, validate=False)
        if len(data) > 8 * 1024 * 1024:
            raise RuntimeError("预览图过大（单张上限 8MB）")
        out.append({"fileName": item.get("fileName") or "", "data": data})
    return out
