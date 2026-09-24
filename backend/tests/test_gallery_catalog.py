"""已上传模板的入库规则。"""

from __future__ import annotations

import json
from pathlib import Path

from gallery.catalog import row_from_meta, scan_uploaded


def test_row_from_meta_maps_category_and_https_pages() -> None:
    row = row_from_meta(
        "deck",
        {
            "label": {"zh_CN": "夜班调度"},
            "description": {"en_US": "night shift"},
            "status": "approved",
            "category": "business",
            "storage": {"backend": "qiniu"},
            "preview": {
                "pages": [
                    "https://cdn.example/01.webp",
                    "http://cdn.example/02.webp",
                    "https://cdn.example/03.webp",
                ]
            },
        },
        1_700_000_000_000,
    )
    assert row is not None
    assert row["title"] == "夜班调度"
    assert row["description"] == "night shift"
    assert row["category"] == "business"
    assert row["pages"] == [
        "https://cdn.example/01.webp",
        "https://cdn.example/03.webp",
    ]
    assert row["slide_count"] == 2

    local = row_from_meta(
        "local-only",
        {"storage": {"backend": "local"}, "preview": {"pages": []}},
        1,
    )
    assert local is not None
    assert local["storage_backend"] == "local"
    assert local["category"] == "other"


def test_missing_status_counts_as_approved() -> None:
    row = row_from_meta(
        "legacy",
        {
            "storage": {"backend": "qiniu"},
            "preview": {"pages": ["https://cdn.example/01.webp"]},
        },
        10,
    )
    assert row is not None
    assert row["status"] == "approved"
    assert row["title"] == "legacy"
    assert row["category"] == "other"


def test_scan_skips_reserved_and_keeps_uploaded(tmp_path: Path) -> None:
    keep = tmp_path / "已上传"
    keep.mkdir()
    (keep / "template.json").write_text(
        json.dumps(
            {
                "label": {"zh_CN": "封面"},
                "storage": {"backend": "qiniu"},
                "preview": {"pages": ["https://cdn.example/01.webp"]},
            }
        ),
        encoding="utf-8",
    )
    skipped = tmp_path / "packs"
    skipped.mkdir()
    (skipped / "template.json").write_text("{}", encoding="utf-8")
    local = tmp_path / "draft"
    local.mkdir()
    (local / "template.json").write_text(
        json.dumps({"storage": {"backend": "local"}, "preview": {"pages": []}}),
        encoding="utf-8",
    )

    rows = scan_uploaded(tmp_path)
    assert [row["id"] for row in rows] == ["已上传"]
