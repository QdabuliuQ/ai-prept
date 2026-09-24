"""模板类型 = 视觉风格 id（与首页 Gallery chips / Admin 类型选择对齐）。

业务主题不再单独成类；类型展示名来自 ppt-master visual-styles 目录。
未知或旧业务枚举（business/finance/…）一律落到 other。
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

DEFAULT_CATEGORY = "other"

# 旧「业务类型」id：不再作为合法类型，coerce 时视为无效
LEGACY_BUSINESS_IDS = frozenset(
    {
        "business",
        "finance",
        "startup",
        "consult",
        "edu",
        "brand",
    }
)

_FALLBACK_STYLES: tuple[dict[str, str], ...] = (
    {"id": "dark-tech", "labelZh": "暗色科技"},
    {"id": "swiss-minimal", "labelZh": "瑞士极简"},
    {"id": "soft-rounded", "labelZh": "柔和圆角"},
    {"id": "glassmorphism", "labelZh": "玻璃拟态"},
    {"id": "blueprint", "labelZh": "蓝图线稿"},
)


@lru_cache(maxsize=1)
def _style_catalog_rows() -> tuple[dict[str, str], ...]:
    try:
        from admin.styles_catalog import load_catalog

        data = load_catalog()
        rows: list[dict[str, str]] = []
        seen: set[str] = set()
        for item in data.get("styles") or []:
            if not isinstance(item, dict):
                continue
            sid = str(item.get("id") or "").strip()
            if not sid or sid in seen or sid == DEFAULT_CATEGORY:
                continue
            label = str(item.get("label_zh") or sid).strip() or sid
            rows.append({"id": sid, "labelZh": label})
            seen.add(sid)
        if rows:
            return tuple(rows)
    except Exception:
        pass
    return _FALLBACK_STYLES


def clear_category_cache() -> None:
    _style_catalog_rows.cache_clear()


def category_ids() -> tuple[str, ...]:
    ids = [row["id"] for row in _style_catalog_rows()]
    if DEFAULT_CATEGORY not in ids:
        ids.append(DEFAULT_CATEGORY)
    return tuple(ids)


def __getattr__(name: str) -> Any:
    """兼容 `from templates.categories import CATEGORY_IDS`。"""
    if name == "CATEGORY_IDS":
        return category_ids()
    if name == "CATEGORY_LABELS_ZH":
        return {
            **{row["id"]: row["labelZh"] for row in _style_catalog_rows()},
            DEFAULT_CATEGORY: "其他",
        }
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def normalize_category(value: Any) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    lowered = raw.lower()
    if lowered in LEGACY_BUSINESS_IDS:
        return None
    allowed = set(category_ids())
    if raw in allowed:
        return raw
    if lowered in allowed:
        return lowered
    return None


def coerce_category(value: Any, *, default: str = DEFAULT_CATEGORY) -> str:
    return normalize_category(value) or default


def category_label_zh(category_id: str) -> str:
    labels = {
        **{row["id"]: row["labelZh"] for row in _style_catalog_rows()},
        DEFAULT_CATEGORY: "其他",
    }
    return labels.get(category_id, labels[DEFAULT_CATEGORY])


def infer_category(*_texts: str) -> str:
    """已不再按主题关键词推断；保留函数名兼容旧调用，恒为 other。"""
    return DEFAULT_CATEGORY


def resolve_category(
    *,
    override: str = "",
    plan_category: Any = None,
    visual_style: Any = None,
    title: str = "",
    description: str = "",
) -> str:
    """优先：人工覆盖 → visual_style → Plan.category → other。

    title/description 保留参数以兼容旧调用，不再用于推断。
    """
    del title, description
    for candidate in (override, visual_style, plan_category):
        normalized = normalize_category(candidate)
        if normalized is not None:
            return normalized
    return DEFAULT_CATEGORY


def catalog() -> list[dict[str, str]]:
    rows = [{"id": row["id"], "labelZh": row["labelZh"]} for row in _style_catalog_rows()]
    rows.append({"id": DEFAULT_CATEGORY, "labelZh": "其他"})
    return rows
