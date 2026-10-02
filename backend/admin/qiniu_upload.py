"""Qiniu upload for prepared template packages."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from admin.fsutil import read_meta, write_meta
from admin.pack import assert_publish_assets, ensure_public_id
from config import load_env


def get_qiniu_config() -> dict[str, str] | None:
    load_env()
    access_key = os.environ.get("QINIU_ACCESS_KEY", "").strip()
    secret_key = os.environ.get("QINIU_SECRET_KEY", "").strip()
    bucket = os.environ.get("QINIU_BUCKET", "").strip()
    domain = os.environ.get("QINIU_DOMAIN", "").strip().rstrip("/")
    if not access_key or not secret_key or not bucket or not domain:
        return None
    prefix = (os.environ.get("QINIU_KEY_PREFIX") or "webppt/").strip()
    if not prefix.endswith("/"):
        prefix += "/"
    return {
        "accessKey": access_key,
        "secretKey": secret_key,
        "bucket": bucket,
        "domain": domain,
        "keyPrefix": prefix,
        "region": os.environ.get("QINIU_REGION", "").strip(),
    }


def qiniu_public_url(cfg: dict[str, str], key: str) -> str:
    return f"{cfg['domain']}/{key.lstrip('/')}"


def _normalize_qiniu_key(key: str) -> str:
    """Strip leading slash, query string, and fragment from an object key."""
    raw = str(key or "").strip().lstrip("/")
    if not raw:
        return ""
    # Preview URLs often append ?v=<cache_bust>; that must not be part of the key.
    for sep in ("?", "#"):
        if sep in raw:
            raw = raw.split(sep, 1)[0]
    return raw.lstrip("/")


def _key_from_url(cfg: dict[str, str], url: str) -> str | None:
    if not isinstance(url, str) or not url.startswith("http"):
        return None
    domain = cfg["domain"].rstrip("/")
    if url.startswith(domain + "/"):
        return _normalize_qiniu_key(url[len(domain) + 1 :])
    # 兼容自定义 CDN 域名与配置不完全一致时，用 path 末两段：{prefix}{id}/xx.webp 或 {prefix}{id}.zip
    try:
        from urllib.parse import urlparse, unquote

        parsed = urlparse(url)
        path = unquote(parsed.path).lstrip("/")
        prefix = cfg["keyPrefix"].lstrip("/")
        if path.startswith(prefix):
            return _normalize_qiniu_key(path)
    except Exception:
        pass
    return None


def _parse_batch_items(ret: Any, info: Any) -> list[Any]:
    """qiniu SDK may leave ret=None on HTTP 298; fall back to text_body JSON."""
    if isinstance(ret, list):
        return ret
    body = getattr(info, "text_body", None) or ""
    if not body:
        return []
    try:
        import json

        parsed = json.loads(body)
        return parsed if isinstance(parsed, list) else []
    except Exception:
        return []


def _batch_item_error(item: Any) -> str:
    if item is None:
        return "empty batch item"
    if isinstance(item, dict):
        code = item.get("code")
        data = item.get("data") if isinstance(item.get("data"), dict) else {}
        err = data.get("error") or item.get("error") or item.get("message")
        if err:
            return f"code={code}: {err}"
        return f"code={code}: {item}"
    return str(item)


def _is_missing_ok(code: Any, payload: Any = None) -> bool:
    """612 / no such file → treat delete as success."""
    if code in (200, 612):
        return True
    if isinstance(payload, dict) and payload.get("error") == "no such file or directory":
        return True
    return False


def delete_keys_from_qiniu(
    keys: list[str],
    cfg: dict[str, str] | None = None,
) -> dict[str, Any]:
    """批量删除七牛对象；已不存在的 key 视为成功。"""
    cfg = cfg or get_qiniu_config()
    if not cfg:
        raise RuntimeError(
            "未配置七牛云。请在 .env.local 设置 QINIU_ACCESS_KEY / QINIU_SECRET_KEY / QINIU_BUCKET / QINIU_DOMAIN"
        )
    cleaned = sorted(
        {
            k
            for k in (_normalize_qiniu_key(x) for x in keys if isinstance(x, str))
            if k
        }
    )
    if not cleaned:
        return {"deleted": [], "failed": []}

    from qiniu import Auth, BucketManager, build_batch_delete

    auth = Auth(cfg["accessKey"], cfg["secretKey"])
    bucket = BucketManager(auth)
    deleted: list[str] = []
    failed: list[dict[str, str]] = []

    # 七牛 batch 单次建议不超过 1000
    chunk_size = 100
    for i in range(0, len(cleaned), chunk_size):
        chunk = cleaned[i : i + chunk_size]
        ops = build_batch_delete(cfg["bucket"], chunk)
        ret, info = bucket.batch(ops)
        if info.status_code not in (200, 298):
            # 整批失败：逐个重试，便于定位
            for key in chunk:
                r, inf = bucket.delete(cfg["bucket"], key)
                if _is_missing_ok(inf.status_code, r):
                    deleted.append(key)
                else:
                    failed.append(
                        {
                            "key": key,
                            "error": f"HTTP {inf.status_code}: {r}",
                        }
                    )
            continue
        items = _parse_batch_items(ret, info)
        for idx, key in enumerate(chunk):
            item = items[idx] if idx < len(items) else None
            code = item.get("code") if isinstance(item, dict) else None
            data = item.get("data") if isinstance(item, dict) else None
            if _is_missing_ok(code, data if isinstance(data, dict) else item):
                deleted.append(key)
            else:
                failed.append(
                    {
                        "key": key,
                        "error": _batch_item_error(item),
                    }
                )
    return {"deleted": deleted, "failed": failed}


def collect_qiniu_keys_for_template(meta: dict[str, Any]) -> list[str]:
    """从 template.json 的 storage / preview 收集远端 key。"""
    storage = meta.get("storage") if isinstance(meta.get("storage"), dict) else {}
    if storage.get("backend") != "qiniu":
        return []
    keys: list[str] = []
    path = storage.get("path")
    if isinstance(path, str) and path.strip():
        keys.append(path.strip().lstrip("/"))

    preview = meta.get("preview") if isinstance(meta.get("preview"), dict) else {}
    pages = (
        [u for u in preview["pages"] if isinstance(u, str)]
        if isinstance(preview.get("pages"), list)
        else []
    )
    cfg = get_qiniu_config()
    if cfg:
        for url in pages:
            key = _key_from_url(cfg, url)
            if key:
                keys.append(key)

    preview_prefix = storage.get("preview_prefix")
    if isinstance(preview_prefix, str) and preview_prefix.strip():
        prefix = preview_prefix.strip().lstrip("/")
        if not prefix.endswith("/"):
            prefix += "/"
        slide_count = 0
        slides = meta.get("slides")
        if isinstance(slides, list):
            slide_count = len(slides)
        n = max(len(pages), slide_count, 1)
        for i in range(1, n + 1):
            keys.append(f"{prefix}{i:02d}.webp")
        # 再按前缀列举，避免遗漏
        if cfg:
            try:
                from qiniu import Auth, BucketManager

                auth = Auth(cfg["accessKey"], cfg["secretKey"])
                bucket = BucketManager(auth)
                marker = None
                while True:
                    ret, eof, info = bucket.list(
                        cfg["bucket"], prefix=prefix, marker=marker, limit=200
                    )
                    if info.status_code != 200 or not isinstance(ret, dict):
                        break
                    for item in ret.get("items") or []:
                        key = item.get("key") if isinstance(item, dict) else None
                        if isinstance(key, str) and key:
                            keys.append(key)
                    marker = ret.get("marker")
                    if eof or not marker:
                        break
            except Exception:
                pass

    seen: set[str] = set()
    out: list[str] = []
    for key in keys:
        norm = _normalize_qiniu_key(key)
        if norm and norm not in seen:
            seen.add(norm)
            out.append(norm)
    return out


def delete_template_from_qiniu(meta: dict[str, Any]) -> dict[str, Any]:
    """删除已上传到七牛的 zip + 预览图。非七牛模板直接跳过。"""
    storage = meta.get("storage") if isinstance(meta.get("storage"), dict) else {}
    if storage.get("backend") != "qiniu":
        return {"skipped": True, "reason": "not_qiniu", "deleted": [], "failed": []}
    keys = collect_qiniu_keys_for_template(meta)
    if not keys:
        return {"skipped": True, "reason": "no_keys", "deleted": [], "failed": []}
    result = delete_keys_from_qiniu(keys)
    if result["failed"]:
        detail = "; ".join(f'{f["key"]}: {f["error"]}' for f in result["failed"][:5])
        raise RuntimeError(f"七牛删除未完全成功（{len(result['failed'])} 个失败）: {detail}")
    return {"skipped": False, **result}


def upload_file_to_qiniu(local_path: Path, key: str, cfg: dict[str, str] | None = None) -> dict[str, Any]:
    cfg = cfg or get_qiniu_config()
    if not cfg:
        raise RuntimeError(
            "未配置七牛云。请在 .env.local 设置 QINIU_ACCESS_KEY / QINIU_SECRET_KEY / QINIU_BUCKET / QINIU_DOMAIN"
        )
    from qiniu import Auth, put_file

    auth = Auth(cfg["accessKey"], cfg["secretKey"])
    key = key.lstrip("/")
    token = auth.upload_token(cfg["bucket"], key, 3600)
    ret, info = put_file(token, key, str(local_path))
    if info.status_code != 200:
        raise RuntimeError(f"七牛上传失败 HTTP {info.status_code}: {ret}")
    body = ret or {}
    final_key = body.get("key") or key
    return {
        "key": final_key,
        "url": qiniu_public_url(cfg, final_key),
        "hash": body.get("hash"),
        "fsize": body.get("fsize"),
    }


def pack_and_upload_template(template_id: str) -> dict[str, Any]:
    cfg = get_qiniu_config()
    if not cfg:
        raise RuntimeError(
            "未配置七牛云。请在 .env.local 设置 QINIU_ACCESS_KEY / QINIU_SECRET_KEY / QINIU_BUCKET / QINIU_DOMAIN"
        )
    from admin.fsutil import template_dir

    root = template_dir(template_id)
    if not root.is_dir():
        raise RuntimeError(f"模板不存在: {template_id}")
    meta = read_meta(template_id)
    if not meta:
        raise RuntimeError(f"缺少 template.json: {template_id}")
    gate = assert_publish_assets(template_id, meta)

    names = sorted(
        n.name
        for n in gate["previewDir"].iterdir()
        if n.is_file() and n.name.lower().endswith(".webp") and n.stem.isdigit()
    ) if gate["previewDir"].is_dir() else []
    if len(names) < gate["slideCount"]:
        raise RuntimeError(
            f"缺少预览图（需要 {gate['slideCount']} 张，现有 {len(names)}）。请先准备上传。"
        )
    zip_path: Path = gate["zipPath"]
    if not zip_path.is_file() or zip_path.stat().st_size <= 0:
        raise RuntimeError("缺少压缩包 package.zip。请先准备上传。")

    public_id = ensure_public_id(template_id, meta)
    key = f"{cfg['keyPrefix']}{public_id}.zip"
    uploaded = upload_file_to_qiniu(zip_path, key, cfg)

    preview_prefix = f"{cfg['keyPrefix']}{public_id}/"
    preview_urls: list[str] = []
    # 预览同名覆盖时 Cloudflare/七牛常长缓存旧图；URL 带版本避开 HIT 旧对象
    cache_bust = str(int(datetime.now(timezone.utc).timestamp()))
    for i in range(1, gate["slideCount"] + 1):
        file_name = f"{i:02d}.webp"
        local = gate["previewDir"] / file_name
        if not local.is_file():
            raise RuntimeError(f"缺少预览图 {file_name}")
        up = upload_file_to_qiniu(local, f"{preview_prefix}{file_name}", cfg)
        base = str(up["url"]).split("?", 1)[0]
        preview_urls.append(f"{base}?v={cache_bust}")

    # 尽力刷新裸 URL 的 CDN 缓存（失败不阻断上传）
    try:
        from qiniu import Auth, CdnManager

        auth = Auth(cfg["accessKey"], cfg["secretKey"])
        bare = [str(u).split("?", 1)[0] for u in preview_urls]
        CdnManager(auth).refresh_urls(bare)
    except Exception:
        pass

    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    meta = read_meta(template_id) or meta
    meta["storage"] = {
        **(meta.get("storage") or {}),
        "backend": "qiniu",
        "path": uploaded["key"],
        "url": uploaded["url"],
        "uploaded_at": now,
        "zip_bytes": uploaded.get("fsize") or zip_path.stat().st_size,
        "preview_prefix": preview_prefix,
    }
    meta["preview"] = {
        "pages": preview_urls,
        "generated_at": now,
        "cache_bust": cache_bust,
    }
    write_meta(template_id, meta)

    try:
        from admin.store import upsert_template_row

        upsert_template_row(template_id)
    except Exception:
        pass

    return {
        "id": template_id,
        "key": uploaded["key"],
        "url": uploaded["url"],
        "zipBytes": uploaded.get("fsize") or zip_path.stat().st_size,
        "imagesCompressed": 0,
        "imagesSkipped": 0,
        "imagesBytesBefore": 0,
        "imagesBytesAfter": 0,
        "htmlCompressed": 0,
        "htmlSkipped": 0,
        "htmlBytesBefore": 0,
        "htmlBytesAfter": 0,
        "cssCompressed": 0,
        "cssBytesBefore": 0,
        "cssBytesAfter": 0,
        "jsonCompressed": 0,
        "jsonBytesBefore": 0,
        "jsonBytesAfter": 0,
        "previewPages": len(preview_urls),
        "previewUrls": preview_urls,
        "visualSpecPath": f"agent-output/{template_id}/visual-spec.md",
        "hash": uploaded.get("hash"),
    }
