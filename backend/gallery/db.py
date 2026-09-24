"""PostgreSQL 中的模板目录（Admin 列表与公开墙同源）。"""

from __future__ import annotations

import os
from typing import Any

from psycopg.types.json import Json

from config import load_env
from gallery.catalog import public_templates, scan_all

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS gallery_templates (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  slide_count INTEGER NOT NULL DEFAULT 0,
  cover TEXT NOT NULL DEFAULT '',
  pages JSONB NOT NULL DEFAULT '[]'::jsonb,
  status TEXT NOT NULL DEFAULT 'draft',
  storage_backend TEXT NOT NULL DEFAULT 'local',
  featured BOOLEAN NOT NULL DEFAULT false,
  category TEXT NOT NULL DEFAULT 'other',
  summary JSONB NOT NULL DEFAULT '{}'::jsonb,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""

MIGRATE_SQL = [
    "ALTER TABLE gallery_templates ADD COLUMN IF NOT EXISTS storage_backend TEXT NOT NULL DEFAULT 'local'",
    "ALTER TABLE gallery_templates ADD COLUMN IF NOT EXISTS summary JSONB NOT NULL DEFAULT '{}'::jsonb",
    "ALTER TABLE gallery_templates ADD COLUMN IF NOT EXISTS featured BOOLEAN NOT NULL DEFAULT false",
    "ALTER TABLE gallery_templates ADD COLUMN IF NOT EXISTS category TEXT NOT NULL DEFAULT 'other'",
    "ALTER TABLE gallery_templates ALTER COLUMN cover SET DEFAULT ''",
    "ALTER TABLE gallery_templates ALTER COLUMN slide_count SET DEFAULT 0",
    "ALTER TABLE gallery_templates ALTER COLUMN pages SET DEFAULT '[]'::jsonb",
    "ALTER TABLE gallery_templates ALTER COLUMN status SET DEFAULT 'draft'",
]


def database_url() -> str:
    load_env()
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError(
            "未配置 DATABASE_URL。请在 .env.local 设置 PostgreSQL 连接串，例如 "
            "postgresql://webppt:webppt@127.0.0.1:5432/webppt"
        )
    return url


def connect():
    import psycopg

    return psycopg.connect(database_url())


def ensure_schema(conn) -> None:
    conn.execute(SCHEMA_SQL)
    for stmt in MIGRATE_SQL:
        conn.execute(stmt)
    conn.commit()


def upsert_rows(conn, rows: list[dict[str, Any]]) -> None:
    for row in rows:
        summary = row.get("summary") if isinstance(row.get("summary"), dict) else {}
        conn.execute(
            """
            INSERT INTO gallery_templates (
              id, title, description, slide_count, cover, pages, status,
              storage_backend, featured, category, summary, updated_at
            ) VALUES (
              %(id)s, %(title)s, %(description)s, %(slide_count)s, %(cover)s,
              %(pages)s, %(status)s, %(storage_backend)s, %(featured)s,
              %(category)s, %(summary)s, to_timestamp(%(updated_ms)s / 1000.0)
            )
            ON CONFLICT (id) DO UPDATE SET
              title = EXCLUDED.title,
              description = EXCLUDED.description,
              slide_count = EXCLUDED.slide_count,
              cover = EXCLUDED.cover,
              pages = EXCLUDED.pages,
              status = EXCLUDED.status,
              storage_backend = EXCLUDED.storage_backend,
              featured = EXCLUDED.featured,
              category = EXCLUDED.category,
              summary = EXCLUDED.summary,
              updated_at = EXCLUDED.updated_at
            """,
            {
                "id": row["id"],
                "title": row["title"],
                "description": row.get("description") or "",
                "slide_count": int(row.get("slide_count") or 0),
                "cover": row.get("cover") or "",
                "pages": Json(row.get("pages") or []),
                "status": row.get("status") or "draft",
                "storage_backend": row.get("storage_backend") or "local",
                "featured": bool(row.get("featured")),
                "category": row.get("category") or "other",
                "summary": Json(summary),
                "updated_ms": int(row.get("updated_ms") or 0),
            },
        )


def upsert_one(conn, row: dict[str, Any]) -> None:
    ensure_schema(conn)
    upsert_rows(conn, [row])
    conn.commit()


def delete_one(conn, template_id: str) -> None:
    ensure_schema(conn)
    conn.execute("DELETE FROM gallery_templates WHERE id = %s", (template_id,))
    conn.commit()


def replace_catalog(conn, rows: list[dict[str, Any]]) -> dict[str, int]:
    ensure_schema(conn)
    upsert_rows(conn, rows)
    ids = [row["id"] for row in rows]
    if ids:
        conn.execute(
            "DELETE FROM gallery_templates WHERE NOT (id = ANY(%s))",
            (ids,),
        )
    else:
        conn.execute("DELETE FROM gallery_templates")
    conn.commit()
    return {"upserted": len(rows)}


def sync_from_disk(conn) -> dict[str, int]:
    return replace_catalog(conn, scan_all())


def list_admin(
    conn,
    statuses: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Admin 模板列表：直接读表（与公开墙同源）。"""
    ensure_schema(conn)
    if statuses:
        cur = conn.execute(
            """
            SELECT id, summary, title, description, slide_count, cover, pages, status,
                   storage_backend, featured, category,
                   (EXTRACT(EPOCH FROM updated_at) * 1000)::bigint AS updated_ms
            FROM gallery_templates
            WHERE status = ANY(%s)
            ORDER BY updated_at DESC
            """,
            (statuses,),
        )
    else:
        cur = conn.execute(
            """
            SELECT id, summary, title, description, slide_count, cover, pages, status,
                   storage_backend, featured, category,
                   (EXTRACT(EPOCH FROM updated_at) * 1000)::bigint AS updated_ms
            FROM gallery_templates
            ORDER BY updated_at DESC
            """
        )
    out: list[dict[str, Any]] = []
    for record in cur.fetchall():
        tid = str(record[0] or "")
        if not tid:
            continue
        summary = record[1] if isinstance(record[1], dict) else {}
        pages = record[6] if isinstance(record[6], list) else []
        status = record[7] or "draft"
        storage = record[8] or "local"
        featured = bool(record[9])
        category = str(record[10] or summary.get("category") or "other")
        updated_ms = int(record[11] or 0)
        slide_count = int(record[4] or 0)
        if summary and summary.get("id"):
            out.append(
                {
                    **summary,
                    "id": tid,
                    "templateId": summary.get("templateId") or tid,
                    "status": status or summary.get("status"),
                    "storageBackend": storage
                    or summary.get("storageBackend")
                    or "local",
                    "featured": featured,
                    "category": category,
                    "mtimeMs": updated_ms or int(summary.get("mtimeMs") or 0),
                    "slideCount": slide_count
                    if slide_count
                    else int(summary.get("slideCount") or 0),
                    "previewPages": pages
                    if pages
                    else (summary.get("previewPages") or []),
                }
            )
            continue
        out.append(
            {
                "id": tid,
                "templateId": tid,
                "label": {
                    "zh_CN": record[2] or tid,
                    "en_US": record[2] or tid,
                },
                "description": {
                    "zh_CN": record[3] or "",
                    "en_US": record[3] or "",
                },
                "slideCount": slide_count,
                "previewFile": None,
                "previewPages": pages,
                "status": status,
                "storageBackend": storage,
                "featured": featured,
                "category": category,
                "mtimeMs": updated_ms,
            }
        )
    return out


def list_public(conn) -> list[dict[str, Any]]:
    ensure_schema(conn)
    cur = conn.execute(
        """
        SELECT id, title, description, slide_count, cover, pages, status,
               storage_backend, featured, category,
               (EXTRACT(EPOCH FROM updated_at) * 1000)::bigint AS updated_ms
        FROM gallery_templates
        WHERE status = 'approved'
          AND storage_backend = 'qiniu'
          AND cover LIKE 'https://%%'
        ORDER BY updated_at DESC
        """
    )
    rows = []
    for record in cur.fetchall():
        pages = record[5] if isinstance(record[5], list) else []
        rows.append(
            {
                "id": record[0],
                "title": record[1],
                "description": record[2] or "",
                "slide_count": record[3],
                "cover": record[4],
                "pages": pages,
                "status": record[6],
                "storage_backend": record[7] or "local",
                "featured": bool(record[8]),
                "category": record[9] or "other",
                "updated_ms": int(record[10] or 0),
            }
        )
    return public_templates(rows)
