"""Tolerant JSON object parsing for free-tier / messy LLM replies."""

from __future__ import annotations

import json

import pytest

from llm import _loads_json_object


def test_loads_plain_object() -> None:
    assert _loads_json_object('{"a": 1}') == {"a": 1}


def test_loads_fenced_and_prose() -> None:
    raw = '好的，这是结果：\n```json\n{"ok": true, "n": 2}\n```\n完'
    assert _loads_json_object(raw) == {"ok": True, "n": 2}


def test_loads_trailing_comma() -> None:
    assert _loads_json_object('{"a": 1, "b": [2, 3,],}') == {"a": 1, "b": [2, 3]}


def test_loads_smart_quotes_key_path() -> None:
    # Smart quotes wrapping a simple string value after fence strip.
    raw = '{\n  "title": “七一专题”\n}'
    data = _loads_json_object(raw)
    assert data["title"] == "七一专题"


def test_loads_still_raises_on_garbage() -> None:
    with pytest.raises(json.JSONDecodeError):
        _loads_json_object("not json at all")
