"""Local template store — parity with src/server/templates/store.ts."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from admin.fsutil import (
    effective_format,
    effective_render,
    effective_status,
    html_slide_count,
    jobs_dir,
    list_template_ids,
    read_meta,
    resolve_under,
    template_dir,
    template_mtime_ms,
    write_meta,
)
from pricing import build_cost_dict


def _usage_summary(meta: dict[str, Any]) -> dict[str, Any]:
    empty = {
        "pageTokens": None,
        "imageTokens": None,
        "imageCalls": None,
        "imageCount": None,
        "pageCostCny": None,
        "imageCostCny": None,
        "totalCostCny": None,
    }
    u = meta.get("usage")
    if not isinstance(u, dict):
        return empty
    page_total = u.get("page_tokens")
    if not isinstance(page_total, (int, float)):
        page_total = (u.get("page") or {}).get("total_tokens") if isinstance(u.get("page"), dict) else None
    image_total = u.get("image_tokens")
    if not isinstance(image_total, (int, float)):
        image_total = (u.get("image") or {}).get("total_tokens") if isinstance(u.get("image"), dict) else None
    page_bucket = u.get("page") if isinstance(u.get("page"), dict) else None
    image_bucket = u.get("image") if isinstance(u.get("image"), dict) else {}
    cost = u.get("cost") if isinstance(u.get("cost"), dict) else None
    if not cost:
        page_model = None
        image_model = None
        if isinstance(u.get("cost"), dict):
            page_model = u["cost"].get("page_model")
            image_model = u["cost"].get("image_model")
        cost = build_cost_dict(
            page=page_bucket,
            image=image_bucket if image_bucket else None,
            page_model=page_model,
            image_model=image_model,
        )
    return {
        "pageTokens": int(page_total) if isinstance(page_total, (int, float)) else None,
        "imageTokens": int(image_total) if isinstance(image_total, (int, float)) else None,
        "imageCalls": image_bucket.get("calls") if isinstance(image_bucket.get("calls"), int) else None,
        "imageCount": image_bucket.get("images") if isinstance(image_bucket.get("images"), int) else None,
        "pageCostCny": cost.get("page_cny") if cost else None,
        "imageCostCny": cost.get("image_cny") if cost else None,
        "totalCostCny": cost.get("total_cny") if cost else None,
    }


def _publish_flags(template_id: str, meta: dict[str, Any]) -> dict[str, bool]:
    root = template_dir(template_id)
    spec = root / "visual-spec.md"
    has_visual_spec = False
    if spec.is_file():
        try:
            has_visual_spec = bool(spec.read_text(encoding="utf-8").strip())
        except OSError:
            has_visual_spec = False
    slide_count = html_slide_count(meta)
    preview_dir = root / "previews"
    preview_names = []
    if preview_dir.is_dir():
        preview_names = [
            n.name for n in preview_dir.iterdir() if re.match(r"^\d{2}\.webp$", n.name, re.I)
        ]
    has_preview_pack = slide_count > 0 and len(preview_names) >= slide_count
    zip_path = root / "package.zip"
    has_package_zip = zip_path.is_file() and zip_path.stat().st_size > 0
    return {
        "hasVisualSpec": has_visual_spec,
        "hasPreviewPack": has_preview_pack,
        "hasPackageZip": has_package_zip,
        "publishReady": has_visual_spec and has_preview_pack and has_package_zip,
    }


def to_summary(template_id: str, meta: dict[str, Any]) -> dict[str, Any]:
    from templates.categories import coerce_category

    slides = meta.get("slides") if isinstance(meta.get("slides"), list) else []
    first = slides[0] if slides and isinstance(slides[0], dict) else None
    preview_file = None
    if first and first.get("file"):
        preview_file = str(first["file"]).lstrip("/")
    pages = meta.get("preview", {}).get("pages") if isinstance(meta.get("preview"), dict) else []
    preview_pages = [u for u in pages if isinstance(u, str) and u] if isinstance(pages, list) else []
    remix = meta.get("remix") if isinstance(meta.get("remix"), dict) else {}
    source = meta.get("source_template_id") or remix.get("source_template_id")
    usage = _usage_summary(meta)
    flags = _publish_flags(template_id, meta)
    storage = meta.get("storage") if isinstance(meta.get("storage"), dict) else {}
    render = effective_render(meta)
    review = meta.get("review") if isinstance(meta.get("review"), dict) else {}
    return {
        "id": template_id,
        "templateId": template_id,
        "publicId": str(meta.get("public_id") or template_id).strip() or template_id,
        "label": meta.get("label") or {"zh_CN": template_id, "en_US": template_id},
        "description": meta.get("description") or {"zh_CN": "", "en_US": ""},
        "slideCount": len(slides),
        "previewFile": preview_file,
        "previewPages": preview_pages,
        "format": effective_format(meta),
        "render": render,
        "htmlConvertFailed": render == "svg-fallback",
        "reviewNote": str(review.get("note") or "").strip() or None,
        "status": effective_status(meta),
        "storageBackend": storage.get("backend") or "local",
        "featured": bool(meta.get("featured")),
        "category": coerce_category(meta.get("category")),
        "mtimeMs": template_mtime_ms(template_id),
        "sourceTemplateId": source,
        **flags,
        **usage,
    }


def list_templates(statuses: list[str] | None = None) -> list[dict[str, Any]]:
    """优先从 Postgres 读（与首页同源）；DB 不可用时回退扫盘。"""
    try:
        from gallery.db import connect, list_admin, sync_from_disk

        with connect() as conn:
            rows = list_admin(conn, statuses)
            # 表空时自动从磁盘灌一次，避免首次升级后列表空白
            if not rows and not statuses:
                sync_from_disk(conn)
                rows = list_admin(conn, statuses)
            return rows
    except Exception:
        out: list[dict[str, Any]] = []
        for tid in list_template_ids():
            meta = read_meta(tid)
            if not meta:
                continue
            status = effective_status(meta)
            if statuses and status not in statuses:
                continue
            out.append(to_summary(tid, meta))
        out.sort(key=lambda row: int(row.get("mtimeMs") or 0), reverse=True)
        return out


def upsert_template_row(template_id: str) -> None:
    """把单个模板的当前 summary 写入 DB。"""
    meta = read_meta(template_id)
    if not meta:
        return
    try:
        from admin.pack import ensure_public_id

        ensure_public_id(template_id, meta, sync_db=False)
        meta = read_meta(template_id) or meta
    except Exception:
        pass
    try:
        from gallery.catalog import row_from_summary
        from gallery.db import connect, upsert_one

        with connect() as conn:
            upsert_one(conn, row_from_summary(to_summary(template_id, meta)))
    except Exception:
        pass


def delete_template_row(template_id: str) -> None:
    try:
        from gallery.db import connect, delete_one

        with connect() as conn:
            delete_one(conn, template_id)
    except Exception:
        pass


def set_status(
    template_id: str,
    status: str,
    *,
    note: str | None = None,
    reviewed_by: str = "admin",
) -> dict[str, Any]:
    meta = read_meta(template_id)
    if not meta:
        raise FileNotFoundError(f"模板不存在: {template_id}")
    review = dict(meta.get("review") or {})
    review["updated_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    if note is not None:
        review["note"] = note
    review["reviewed_by"] = reviewed_by
    storage = dict(meta.get("storage") or {})
    storage.setdefault("backend", "local")
    storage.setdefault("path", f"agent-output/{template_id}")
    meta["status"] = status
    meta["review"] = review
    meta["storage"] = storage
    write_meta(template_id, meta)
    upsert_template_row(template_id)
    return meta


def set_featured(template_id: str, featured: bool) -> dict[str, Any]:
    """标记/取消精选。仅已上传七牛的模板可操作。"""
    meta = read_meta(template_id)
    if not meta:
        raise FileNotFoundError(f"模板不存在: {template_id}")
    storage = meta.get("storage") if isinstance(meta.get("storage"), dict) else {}
    if storage.get("backend") != "qiniu":
        raise ValueError("仅已上传的模板可标记精选")
    meta["featured"] = bool(featured)
    write_meta(template_id, meta)
    upsert_template_row(template_id)
    return meta


def set_category(template_id: str, category: str) -> dict[str, Any]:
    """设置类型（= 视觉风格 id；磁盘 meta + DB 双写）。"""
    from templates.categories import category_ids, normalize_category

    meta = read_meta(template_id)
    if not meta:
        raise FileNotFoundError(f"模板不存在: {template_id}")
    normalized = normalize_category(category)
    if normalized is None:
        raise ValueError(f"无效类型: {category}；允许: {', '.join(category_ids())}")
    meta["category"] = normalized
    write_meta(template_id, meta)
    upsert_template_row(template_id)
    return meta


def _style_hints_from_jobs() -> dict[str, str]:
    """从 admin-jobs 历史里收集 templateId → visualStyle。"""
    import re

    mapping: dict[str, str] = {}
    root = jobs_dir()
    if not root.is_dir():
        return mapping

    id_token = re.compile(r"[A-Za-z0-9._\u4e00-\u9fff-]{2,80}")

    for path in sorted(root.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue

        log = str(data.get("log") or "")
        style = ""
        # 优先最终 resolve / plan 行里的风格
        for pattern in (
            r"\[style\]\s+resolved\s+(\S+)",
            r"\[plan\][^\n]*\bstyle=(\S+)",
            r"\[ppt-master\][^\n]*\bstyle=(\S+)",
            r"\[style\]\s+(\S+)",
        ):
            matches = re.findall(pattern, log)
            if matches:
                style = str(matches[-1]).strip().rstrip(">,")
                if style and style not in {"created", "True", "False"}:
                    break
        if not style:
            raw = data.get("visualStyle") or data.get("visual_style")
            style = str(raw or "").strip()
        if not style:
            continue

        tids: list[str] = []
        if data.get("templateId"):
            tids.append(str(data["templateId"]).strip())
        for item in data.get("templateIds") or []:
            t = str(item or "").strip()
            if t:
                tids.append(t)
        if data.get("convertTemplateId"):
            tids.append(str(data["convertTemplateId"]).strip())
        # 日志里的真实落地 id：webppt-<id>-… / --template-id <id>
        for m in re.finditer(
            r"(?:webppt-|--template-id\s+|id=)([A-Za-z0-9._\u4e00-\u9fff-]{4,})",
            log,
        ):
            token = m.group(1).strip().strip("\"'")
            # 去掉 webppt-xxx 后的 hash 后缀：EMviRDhnkCIG-193654ff17 → EMviRDhnkCIG
            if "-" in token and re.search(r"-[0-9a-f]{6,}$", token):
                token = token.rsplit("-", 1)[0]
            if token and id_token.fullmatch(token):
                tids.append(token)

        src = str(data.get("sourceTemplateId") or "").strip()
        for tid in tids:
            # 过滤 SVG 节点误伤（text-16 等）
            if not tid or tid.startswith('"') or ">" in tid:
                continue
            if re.fullmatch(r"(text|bloom|detail|title|corner|dec|light)-\S+", tid):
                continue
            mapping[tid] = style
            if src:
                mapping.setdefault(f"__source__:{tid}", src)
    return mapping


def backfill_categories(*, force: bool = False) -> dict[str, int]:
    """为缺少/旧业务类型/「其他」的模板回填视觉风格类型。

    来源优先级：plan(_lock).visual_style → admin-jobs.visualStyle → remix 源模板 category。
    """
    from templates.categories import (
        DEFAULT_CATEGORY,
        LEGACY_BUSINESS_IDS,
        coerce_category,
        normalize_category,
    )

    job_styles = _style_hints_from_jobs()
    updated = skipped = 0
    for tid in list_template_ids():
        meta = read_meta(tid)
        if not meta:
            continue
        raw = str(meta.get("category") or "").strip()
        current = normalize_category(raw)
        # 已是合法风格且不是 other，默认跳过
        if (
            not force
            and current is not None
            and current != DEFAULT_CATEGORY
            and raw.lower() not in LEGACY_BUSINESS_IDS
        ):
            skipped += 1
            continue

        style = ""
        root = template_dir(tid)
        for name in ("plan_lock.json", "plan.json"):
            path = root / name
            if not path.is_file():
                continue
            try:
                plan = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(plan, dict):
                style = str(plan.get("visual_style") or "").strip()
                if style:
                    break

        if not style:
            style = str(job_styles.get(tid) or "").strip()

        if not style:
            src = str(
                meta.get("source_template_id")
                or (meta.get("remix") or {}).get("source_template_id")
                or job_styles.get(f"__source__:{tid}")
                or ""
            ).strip()
            if src:
                src_meta = read_meta(src) or {}
                style = str(
                    job_styles.get(src)
                    or src_meta.get("category")
                    or ""
                ).strip()

        next_cat = coerce_category(style)
        if next_cat == current and not force:
            # 仍是 other / 无效，且没有更好推断
            if current == DEFAULT_CATEGORY and not style:
                skipped += 1
                continue
            if current is not None and current != DEFAULT_CATEGORY:
                skipped += 1
                continue

        meta["category"] = next_cat
        write_meta(tid, meta)
        upsert_template_row(tid)
        updated += 1
    return {"updated": updated, "skipped": skipped}


def delete_template(template_id: str) -> None:
    root = template_dir(template_id)
    if not root.is_dir():
        raise FileNotFoundError(f"模板不存在: {template_id}")
    import shutil

    meta = read_meta(template_id) or {}
    storage = meta.get("storage") if isinstance(meta.get("storage"), dict) else {}
    if storage.get("backend") == "qiniu":
        from admin.qiniu_upload import delete_template_from_qiniu

        delete_template_from_qiniu(meta)

    shutil.rmtree(root)
    delete_template_row(template_id)


def delete_many(ids: list[str]) -> dict[str, Any]:
    deleted: list[str] = []
    failed: list[dict[str, str]] = []
    for tid in dict.fromkeys(i.strip() for i in ids if i and i.strip()):
        try:
            delete_template(tid)
            deleted.append(tid)
        except Exception as e:  # noqa: BLE001
            failed.append({"id": tid, "error": str(e)})
    return {"deleted": deleted, "failed": failed}


def load_pages_meta(template_id: str) -> dict[str, Any] | None:
    meta = read_meta(template_id)
    if not meta:
        return None
    pages = []
    for i, slide in enumerate(meta.get("slides") or []):
        if not isinstance(slide, dict):
            continue
        file_name = str(slide.get("file") or "").lstrip("/")
        layout = slide.get("layout") or Path(file_name).stem or f"slide-{i + 1}"
        pages.append(
            {
                "id": f"tpl_{layout}_{i + 1}",
                "title": slide.get("title") or layout,
                "layout": layout,
                "file": file_name,
            }
        )
    return {
        "id": template_id,
        "meta": meta,
        "format": effective_format(meta),
        "render": effective_render(meta),
        "htmlConvertFailed": effective_render(meta) == "svg-fallback",
        "reviewNote": (
            str((meta.get("review") or {}).get("note") or "").strip()
            if isinstance(meta.get("review"), dict)
            else None
        )
        or None,
        "pages": pages,
    }


def _strip_slow_cdns(html: str) -> str:
    out = html
    out = re.sub(
        r'<script\b[^>]*\bsrc=["\']https?://cdn\.tailwindcss\.com[^"\']*["\'][^>]*>\s*</script>',
        "",
        out,
        flags=re.I,
    )
    out = re.sub(
        r'<link\b[^>]*href=["\']https?://fonts\.googleapis\.com[^"\']*["\'][^>]*>',
        "",
        out,
        flags=re.I,
    )
    out = re.sub(
        r'<link\b[^>]*href=["\']https?://fonts\.gstatic\.com[^"\']*["\'][^>]*>',
        "",
        out,
        flags=re.I,
    )
    return out


def _rewrite_asset_urls(html: str, template_id: str) -> str:
    from urllib.parse import quote

    from admin.fsutil import template_dir

    base = f"/api/html-templates/{quote(template_id)}/assets"
    try:
        pack_root = template_dir(template_id)
    except Exception:
        pack_root = None

    def _bust(rel: str) -> str:
        """Append mtime so iframe reloads after rematerialize overwrite."""
        path_rel = rel.lstrip("/")
        # strip existing query from relative path in HTML if any
        path_only = path_rel.split("?", 1)[0]
        if pack_root is not None:
            fp = pack_root / path_only
            try:
                if fp.is_file():
                    v = int(fp.stat().st_mtime)
                    return f"{path_only}?v={v}"
            except OSError:
                pass
        return path_only

    def repl_attr(m: re.Match[str]) -> str:
        return f"{m.group(1)}={m.group(2)}{base}/{_bust(m.group(3))}{m.group(2)}"

    out = re.sub(
        r'\b(href|src)=(["\'])\.\./([^"\']+)\2',
        repl_attr,
        html,
        flags=re.I,
    )

    def repl_url(m: re.Match[str]) -> str:
        q = m.group(1) or ""
        return f"url({q}{base}/{_bust(m.group(2))}{q})"

    out = re.sub(
        r"url\(\s*(['\"]?)\.\./([^)'\"]+)\1\s*\)",
        repl_url,
        out,
        flags=re.I,
    )
    return _strip_slow_cdns(out)


def load_editor_doc(template_id: str) -> dict[str, Any] | None:
    meta = read_meta(template_id)
    if not meta or not meta.get("slides"):
        return None
    pages = []
    for i, slide in enumerate(meta["slides"]):
        if not isinstance(slide, dict):
            continue
        file_name = str(slide.get("file") or "").lstrip("/")
        path = resolve_under(template_id, file_name)
        if not path or not path.is_file():
            continue
        raw = path.read_text(encoding="utf-8")
        layout = slide.get("layout") or Path(file_name).stem
        pages.append(
            {
                "id": f"tpl_{layout}_{i + 1}",
                "html": _rewrite_asset_urls(raw, template_id),
                "sourceFile": file_name,
                "elements": [],
                "visible": True,
                "toggleInAnimation": "none",
                "toggleInDuration": "0.5s",
                "toggleInDelay": "0s",
                "autoToggle": False,
                "autoToggleTime": 0,
                "backgroundType": "color",
                "background": "#ffffff",
                "bgColor": "#ffffff",
                "fgColor": "#111111",
                "bgOpacity": 1,
                "remark": slide.get("title") or layout,
            }
        )
    if not pages:
        return None
    name = (meta.get("label") or {}).get("zh_CN") or template_id
    return {
        "id": template_id,
        "name": name,
        "format": effective_format(meta),
        "templateDir": template_id,
        "templateId": template_id,
        "label": meta.get("label"),
        "description": meta.get("description"),
        "meta": meta,
        "pages": pages,
    }


def _sync_gallery() -> None:
    try:
        from gallery.db import connect, sync_from_disk

        with connect() as conn:
            sync_from_disk(conn)
    except Exception:
        # Gallery DB optional during admin CRUD
        pass
