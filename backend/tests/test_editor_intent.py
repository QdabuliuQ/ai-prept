"""Tests for editor AI intent classification heuristics."""

from templates.editor_intent import (
    INTENT_DELETE,
    INTENT_GENERATE,
    INTENT_REWRITE,
    classify_editor_intent,
    heuristic_intent,
)


def test_heuristic_delete():
    assert heuristic_intent("删掉这一页") == INTENT_DELETE
    assert heuristic_intent("请删除当前页") == INTENT_DELETE
    assert heuristic_intent("remove this page") == INTENT_DELETE


def test_heuristic_generate():
    assert heuristic_intent("新增一页社区花园案例") == INTENT_GENERATE
    assert heuristic_intent("加一页总结") == INTENT_GENERATE
    assert heuristic_intent("add a new page about gardens") == INTENT_GENERATE


def test_heuristic_none_for_rewrite():
    assert heuristic_intent("标题太大挡住图片，缩小字号") is None


def test_classify_mock_defaults_rewrite():
    out = classify_editor_intent("标题挡住图片请改一下", mock=True)
    assert out["intent"] == INTENT_REWRITE


def test_classify_delete_blocked_when_one_page():
    out = classify_editor_intent("删掉这一页", page_count=1, mock=True)
    assert out["intent"] == INTENT_REWRITE
