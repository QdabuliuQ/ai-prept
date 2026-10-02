"""Visual style catalog helpers for Admin."""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

from admin.fsutil import repo_root

FALLBACK = [
    {
        "id": "dark-tech",
        "family": "corporate-product",
        "group_zh": "企业 / 产品",
        "label_zh": "暗色科技",
        "status": "curated",
        "path": "dark-tech.md",
    },
    {
        "id": "swiss-minimal",
        "family": "corporate-product",
        "group_zh": "企业 / 产品",
        "label_zh": "瑞士极简",
        "status": "curated",
        "path": "swiss-minimal.md",
    },
]


def visual_styles_dir() -> Path:
    import os

    env = os.environ.get("PPT_MASTER_ROOT", "").strip()
    root = Path(env).expanduser().resolve() if env else repo_root() / "ppt-master"
    return root / "skills" / "ppt-master" / "references" / "visual-styles"


def load_catalog() -> dict[str, Any]:
    file = visual_styles_dir() / "_catalog.json"
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("styles"), list) and data["styles"]:
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return {"schema_version": "1.0", "count": len(FALLBACK), "styles": FALLBACK}


def select_options(*, include_variants: bool = True) -> list[dict[str, Any]]:
    catalog = load_catalog()
    groups: dict[str, list[dict[str, str]]] = {}
    for s in catalog["styles"]:
        status = s.get("status") or "curated"
        if not include_variants and status != "curated":
            continue
        group = s.get("group_zh") or "其他"
        label = s.get("label_zh") or s.get("id")
        if status and status != "curated":
            label = f"{label} · {status}"
        groups.setdefault(group, []).append({"value": s["id"], "label": label})
    return [{"label": g, "options": opts} for g, opts in groups.items()]


def pick_random(*, exclude: list[str] | None = None) -> dict[str, Any] | None:
    """Uniform-within-bucket pick; warm-paper styles capped (~25%) so beige doesn't dominate."""
    from ppt_master.styles import is_paper_warm_style

    catalog = load_catalog()
    ban = set(exclude or [])
    curated = [
        s
        for s in catalog["styles"]
        if (s.get("status") or "curated") == "curated" and s.get("id") not in ban
    ]
    if not curated:
        curated = [s for s in catalog["styles"] if s.get("id") not in ban]
    if not curated:
        return None

    warm = [s for s in curated if is_paper_warm_style(str(s.get("id") or ""))]
    warm_ids = {str(s.get("id") or "") for s in warm}
    other = [s for s in curated if str(s.get("id") or "") not in warm_ids]
    if warm and other:
        pool = warm if random.random() < 0.25 else other
    else:
        pool = curated
    s = random.choice(pool)
    return {
        "mode": "catalog",
        "styleId": s["id"],
        "labelZh": s.get("label_zh") or s["id"],
        "groupZh": s.get("group_zh") or "",
        "family": s.get("family") or "",
    }
