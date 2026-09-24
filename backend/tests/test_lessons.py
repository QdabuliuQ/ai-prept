"""Learned lessons: fingerprint, dedupe append, prompt injection."""

from __future__ import annotations

from pathlib import Path

import skill.lessons as lessons_mod
from skill.lessons import (
    Lesson,
    append_lessons,
    issue_kind_ids,
    learn_from_hard_issues,
    learn_lessons_enabled,
    lessons_prompt_block,
    parse_lesson_ids,
)


def test_issue_kind_ids():
    issues = [
        "[visual:shell] pages/a.json: 空内容卡",
        "[visual:contrast] 对比度 1.9",
        "文字重叠在 pages/b.json",
    ]
    ids = issue_kind_ids(issues)
    assert "visual-shell" in ids
    assert "visual-contrast" in ids
    assert "visual-overlap" in ids


def test_append_lessons_dedupes(tmp_path: Path, monkeypatch):
    path = tmp_path / "LEARNED_LESSONS.md"
    path.write_text(
        "# Learned Lessons\n\n## Lessons\n\n"
        "<!-- 自动追加区：勿删本行 -->\n\n"
        "### `visual-shell` · track:both\n已有规则\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(lessons_mod, "_EXCERPTS_DIR", tmp_path)
    added = append_lessons(
        [
            Lesson(id="visual-shell", track="both", rule="重复不应写入"),
            Lesson(id="visual-contrast", track="both", rule="主字用 text 色"),
        ]
    )
    assert added == ["visual-contrast"]
    text = path.read_text(encoding="utf-8")
    assert text.count("### `visual-shell`") == 1
    assert "### `visual-contrast`" in text
    assert "主字用 text 色" in text


def test_learn_fallback_without_llm(tmp_path: Path, monkeypatch):
    path = tmp_path / "LEARNED_LESSONS.md"
    path.write_text(
        "# Learned Lessons\n\n## Lessons\n\n<!-- 自动追加区：勿删本行 -->\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(lessons_mod, "_EXCERPTS_DIR", tmp_path)
    monkeypatch.setenv("AGENT_LEARN_LESSONS", "1")
    result = learn_from_hard_issues(
        ["[visual:shell] pages/x.json: 空卡"],
        pool=None,
        model=None,
    )
    assert result["enabled"] is True
    assert "visual-shell" in result["added"]
    # 再学一次应去重
    result2 = learn_from_hard_issues(
        ["[visual:shell] pages/y.json: 仍空卡"],
        pool=None,
        model=None,
    )
    assert result2["added"] == []


def test_learn_lessons_env(monkeypatch):
    monkeypatch.setenv("AGENT_LEARN_LESSONS", "0")
    assert learn_lessons_enabled() is False
    monkeypatch.delenv("AGENT_LEARN_LESSONS", raising=False)
    assert learn_lessons_enabled() is True


def test_lessons_prompt_block_includes_entries(tmp_path: Path, monkeypatch):
    path = tmp_path / "LEARNED_LESSONS.md"
    path.write_text(
        "# Learned Lessons\n\n## Lessons\n\n<!-- 自动追加区：勿删本行 -->\n\n"
        "### `visual-shell` · track:both\n空卡内必须有正文。\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(lessons_mod, "_EXCERPTS_DIR", tmp_path)
    block = lessons_prompt_block()
    assert "visual-shell" in block
    assert "空卡内必须有正文" in block
    assert len(block) <= 14_000
