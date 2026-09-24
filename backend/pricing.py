"""LLM / 生图费用估算（CNY，非官方账单，仅展示用）。

默认按 DeepSeek 官网价目（百万 tokens）：
  deepseek-v4-flash: 缓存命中 0.2 / 未命中 1 / 输出 2
  deepseek-v4-pro:   缓存命中 1 / 未命中 12 / 输出 24
"""

from __future__ import annotations

from typing import Any


# (cache_hit, cache_miss, output) 元 / 百万 tokens
RateTriple = tuple[float, float, float]

_RATES: dict[str, RateTriple] = {
    "deepseek-v4-flash": (0.2, 1.0, 2.0),
    "deepseek-chat": (0.2, 1.0, 2.0),
    "deepseek-reasoner": (0.2, 1.0, 2.0),  # 现映射 Flash 思考模式
    "deepseek-v4-pro": (1.0, 12.0, 24.0),
}

_DEFAULT_PAGE: RateTriple = (0.2, 1.0, 2.0)

# 常见生图：按张估算（无可靠 token 账单时）
_IMAGE_PER_IMAGE_CNY: dict[str, float] = {
    "nano-banana-fast": 0.02,
    "nano-banana": 0.04,
    "tongyi-mai/z-image-turbo": 0.02,
    "tongyi-mai/z-image": 0.03,
    "kwai-kolors/kolors": 0.03,
    "qwen/qwen-image": 0.04,
    "baidu/ernie-image-turbo": 0.02,
}


def normalize_model(model: str | None) -> str:
    return (model or "").strip().lower()


def resolve_page_rates(model: str | None) -> RateTriple:
    key = normalize_model(model)
    if not key:
        return _DEFAULT_PAGE
    if key in _RATES:
        return _RATES[key]
    for name, rates in _RATES.items():
        if name in key or key in name:
            return rates
    if "deepseek" in key and "pro" in key:
        return _RATES["deepseek-v4-pro"]
    if "deepseek" in key:
        return _RATES["deepseek-v4-flash"]
    # 未知网关：按 Flash 粗估，并在结果里标 estimated
    return _DEFAULT_PAGE


def _bucket_prompt_parts(bucket: dict[str, Any]) -> tuple[int, int, int]:
    prompt = int(bucket.get("prompt_tokens") or 0)
    hit = int(bucket.get("cache_hit_tokens") or 0)
    miss = int(bucket.get("cache_miss_tokens") or 0)
    if hit or miss:
        if miss <= 0 and prompt > hit:
            miss = prompt - hit
        return hit, max(0, miss), prompt
    # 无缓存字段：整段 prompt 按未命中计（偏保守）
    return 0, max(0, prompt), prompt


def estimate_page_cny(
    bucket: dict[str, Any] | None,
    *,
    model: str | None = None,
) -> float | None:
    if not bucket or not isinstance(bucket, dict):
        return None
    total = int(bucket.get("total_tokens") or 0)
    prompt = int(bucket.get("prompt_tokens") or 0)
    completion = int(bucket.get("completion_tokens") or 0)
    if total <= 0 and prompt <= 0 and completion <= 0:
        return None
    hit, miss, _ = _bucket_prompt_parts(bucket)
    if completion <= 0 and total > prompt:
        completion = total - prompt
    rh, rm, ro = resolve_page_rates(model)
    cost = (hit / 1e6) * rh + (miss / 1e6) * rm + (max(0, completion) / 1e6) * ro
    return round(cost, 6)


def estimate_image_cny(
    bucket: dict[str, Any] | None,
    *,
    model: str | None = None,
) -> float | None:
    if not bucket or not isinstance(bucket, dict):
        return None
    images = int(bucket.get("images") or 0)
    key = normalize_model(model)
    per = None
    for name, price in _IMAGE_PER_IMAGE_CNY.items():
        if name in key:
            per = price
            break
    if per is not None and images > 0:
        return round(per * images, 6)
    # 无按张价时不拿页面 LLM 价硬套图片 token
    return None


def build_cost_dict(
    *,
    page: dict[str, Any] | None,
    image: dict[str, Any] | None,
    page_model: str | None = None,
    image_model: str | None = None,
) -> dict[str, Any]:
    page_cny = estimate_page_cny(page, model=page_model)
    image_cny = estimate_image_cny(image, model=image_model)
    parts = [c for c in (page_cny, image_cny) if c is not None]
    total = round(sum(parts), 6) if parts else None
    rh, rm, ro = resolve_page_rates(page_model)
    return {
        "currency": "CNY",
        "estimated": True,
        "page_cny": page_cny,
        "image_cny": image_cny,
        "total_cny": total,
        "page_model": page_model or None,
        "image_model": image_model or None,
        "rates": {
            "page_cache_hit_per_m": rh,
            "page_cache_miss_per_m": rm,
            "page_output_per_m": ro,
        },
        "note": "按公开价目估算，非充值账单",
    }
