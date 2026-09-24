"""生成过程用量统计：页面 LLM token / 图片 token（线程安全）。"""

from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import asdict, dataclass
from typing import Any, Iterator

from pricing import build_cost_dict


@dataclass
class TokenBucket:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    calls: int = 0
    # 图片成功张数（仅 image 桶使用）
    images: int = 0
    reasoning_tokens: int = 0
    cache_hit_tokens: int = 0
    cache_miss_tokens: int = 0

    def add_from_usage(self, usage: Any, *, images: int = 0) -> None:
        self.calls += 1
        if images:
            self.images += images
        if usage is None:
            return
        if isinstance(usage, dict):
            data = usage
        else:
            data = (
                usage.model_dump()
                if hasattr(usage, "model_dump")
                else getattr(usage, "__dict__", {}) or {}
            )
        prompt = int(data.get("prompt_tokens") or data.get("input_tokens") or 0)
        completion = int(
            data.get("completion_tokens") or data.get("output_tokens") or 0
        )
        total = int(data.get("total_tokens") or 0)
        if total <= 0:
            total = prompt + completion
        self.prompt_tokens += max(0, prompt)
        self.completion_tokens += max(0, completion)
        self.total_tokens += max(0, total)
        details = data.get("completion_tokens_details") or {}
        if isinstance(details, dict):
            self.reasoning_tokens += int(details.get("reasoning_tokens") or 0)
        elif hasattr(details, "reasoning_tokens"):
            self.reasoning_tokens += int(getattr(details, "reasoning_tokens") or 0)
        self.cache_hit_tokens += int(
            data.get("prompt_cache_hit_tokens") or data.get("cache_hit_tokens") or 0
        )
        self.cache_miss_tokens += int(
            data.get("prompt_cache_miss_tokens")
            or data.get("cache_miss_tokens")
            or 0
        )

    def to_dict(self) -> dict[str, int]:
        return {k: int(v) for k, v in asdict(self).items()}


class GenerationUsage:
    def __init__(self) -> None:
        self.page = TokenBucket()
        self.image = TokenBucket()
        self.page_model: str | None = None
        self.image_model: str | None = None
        self._lock = threading.Lock()

    def set_models(
        self,
        *,
        page_model: str | None = None,
        image_model: str | None = None,
    ) -> None:
        with self._lock:
            if page_model:
                self.page_model = page_model.strip() or self.page_model
            if image_model:
                self.image_model = image_model.strip() or self.image_model

    def record_page(self, usage: Any) -> None:
        with self._lock:
            self.page.add_from_usage(usage)

    def record_image(self, usage: Any = None, *, images: int = 1) -> None:
        with self._lock:
            self.image.add_from_usage(usage, images=images)

    def to_dict(self) -> dict[str, Any]:
        page = self.page.to_dict()
        image = self.image.to_dict()
        page_model = self.page_model or (os.environ.get("LLM_MODEL") or "").strip() or None
        image_model = (
            self.image_model
            or (os.environ.get("IMAGE_MODEL") or "").strip()
            or None
        )
        cost = build_cost_dict(
            page=page,
            image=image,
            page_model=page_model,
            image_model=image_model,
        )
        return {
            "page_tokens": page["total_tokens"],
            "image_tokens": image["total_tokens"],
            "page": page,
            "image": image,
            "cost": cost,
        }

    def merge_into(self, existing: dict[str, Any] | None) -> dict[str, Any]:
        """合并进已有 template.json usage（补图重试场景）。"""
        base = dict(existing or {})
        cur = self.to_dict()
        for key in ("page", "image"):
            prev = base.get(key) if isinstance(base.get(key), dict) else {}
            nxt = cur[key]
            merged = dict(prev) if isinstance(prev, dict) else {}
            for field in (
                "prompt_tokens",
                "completion_tokens",
                "total_tokens",
                "calls",
                "images",
                "reasoning_tokens",
                "cache_hit_tokens",
                "cache_miss_tokens",
            ):
                merged[field] = int(merged.get(field) or 0) + int(nxt.get(field) or 0)
            base[key] = merged
        base["page_tokens"] = int((base.get("page") or {}).get("total_tokens") or 0)
        base["image_tokens"] = int((base.get("image") or {}).get("total_tokens") or 0)
        prev_cost = base.get("cost") if isinstance(base.get("cost"), dict) else {}
        page_model = (
            self.page_model
            or prev_cost.get("page_model")
            or (os.environ.get("LLM_MODEL") or "").strip()
            or None
        )
        image_model = (
            self.image_model
            or prev_cost.get("image_model")
            or (os.environ.get("IMAGE_MODEL") or "").strip()
            or None
        )
        base["cost"] = build_cost_dict(
            page=base.get("page") if isinstance(base.get("page"), dict) else None,
            image=base.get("image") if isinstance(base.get("image"), dict) else None,
            page_model=str(page_model) if page_model else None,
            image_model=str(image_model) if image_model else None,
        )
        return base


_CURRENT: ContextVar[GenerationUsage | None] = ContextVar(
    "webppt_generation_usage", default=None
)


def current_usage() -> GenerationUsage | None:
    return _CURRENT.get()


def bind_usage(usage: GenerationUsage | None) -> Token:
    """在 ThreadPool 子线程中绑定同一 GenerationUsage。"""
    return _CURRENT.set(usage)


def reset_usage(token: Token) -> None:
    _CURRENT.reset(token)


@contextmanager
def track_usage() -> Iterator[GenerationUsage]:
    usage = GenerationUsage()
    token = _CURRENT.set(usage)
    try:
        yield usage
    finally:
        _CURRENT.reset(token)


@contextmanager
def use_usage(usage: GenerationUsage | None) -> Iterator[None]:
    token = _CURRENT.set(usage)
    try:
        yield
    finally:
        _CURRENT.reset(token)


def record_page_usage(usage: Any) -> None:
    cur = current_usage()
    if cur is not None:
        cur.record_page(usage)


def record_image_usage(usage: Any = None, *, images: int = 1) -> None:
    cur = current_usage()
    if cur is not None:
        cur.record_image(usage, images=images)
