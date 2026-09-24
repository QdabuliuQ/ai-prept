"""Usage accumulator unit tests."""

from __future__ import annotations

from usage import (
    GenerationUsage,
    record_image_usage,
    record_page_usage,
    track_usage,
    use_usage,
)


def test_track_usage_records_page_and_image():
    with track_usage() as usage:
        record_page_usage(
            {
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "total_tokens": 150,
                "prompt_cache_hit_tokens": 20,
            }
        )
        record_image_usage({"prompt_tokens": 10, "total_tokens": 10}, images=1)
        record_image_usage(None, images=1)

    d = usage.to_dict()
    assert d["page_tokens"] == 150
    assert d["page"]["prompt_tokens"] == 100
    assert d["page"]["cache_hit_tokens"] == 20
    assert d["page"]["calls"] == 1
    assert d["image_tokens"] == 10
    assert d["image"]["images"] == 2
    assert d["image"]["calls"] == 2
    assert "cost" in d
    assert d["cost"]["currency"] == "CNY"
    assert d["cost"]["page_cny"] is not None
    assert d["cost"]["page_cny"] > 0


def test_use_usage_binds_worker_context():
    root = GenerationUsage()
    with use_usage(root):
        record_page_usage({"total_tokens": 42, "prompt_tokens": 40, "completion_tokens": 2})
    assert root.page.total_tokens == 42
    assert root.to_dict()["page_tokens"] == 42


def test_merge_into_sums_buckets():
    a = GenerationUsage()
    a.record_page({"total_tokens": 100, "prompt_tokens": 80, "completion_tokens": 20})
    b = GenerationUsage()
    b.record_image({"total_tokens": 5}, images=1)
    merged = b.merge_into(a.to_dict())
    assert merged["page_tokens"] == 100
    assert merged["image_tokens"] == 5
    assert merged["image"]["images"] == 1
    assert merged["cost"]["page_cny"] is not None


def test_flash_cost_rough_scale():
    from pricing import estimate_page_cny

    # 32.8k ≈ 半输入半输出 → 约 0.05 元量级
    c = estimate_page_cny(
        {
            "prompt_tokens": 16400,
            "completion_tokens": 16400,
            "total_tokens": 32800,
            "cache_miss_tokens": 16400,
        },
        model="deepseek-v4-flash",
    )
    assert c is not None
    assert 0.04 < c < 0.06
