"""模板类型 = 视觉风格 id。"""

from __future__ import annotations

from templates.categories import (
    DEFAULT_CATEGORY,
    clear_category_cache,
    coerce_category,
    infer_category,
    normalize_category,
    resolve_category,
)


def setup_function() -> None:
    clear_category_cache()


def test_normalize_and_coerce() -> None:
    assert normalize_category("dark-tech") == "dark-tech"
    assert normalize_category("Dark-Tech") == "dark-tech"
    assert normalize_category("business") is None  # 旧业务类失效
    assert normalize_category("nope") is None
    assert coerce_category("swiss-minimal") == "swiss-minimal"
    assert coerce_category(None) == DEFAULT_CATEGORY
    assert coerce_category("finance") == DEFAULT_CATEGORY


def test_infer_no_longer_uses_keywords() -> None:
    assert infer_category("季度财务预算汇报") == DEFAULT_CATEGORY
    assert infer_category("种子轮路演融资") == DEFAULT_CATEGORY


def test_resolve_prefers_visual_style() -> None:
    assert (
        resolve_category(
            override="",
            visual_style="glassmorphism",
            plan_category="other",
            title="财务预算",
        )
        == "glassmorphism"
    )
    assert (
        resolve_category(
            override="blueprint",
            visual_style="dark-tech",
            plan_category="edu",
        )
        == "blueprint"
    )
    assert (
        resolve_category(
            override="",
            visual_style="",
            plan_category="invalid",
            title="教育培训课程",
        )
        == DEFAULT_CATEGORY
    )
