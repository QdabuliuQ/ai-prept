"""Agnes text (LLM) provider catalog, selection and request extras."""

from __future__ import annotations

from admin.providers import (
    list_llm_providers_public,
    llm_env_for_dual,
    resolve_llm_selection,
)
from llm import _chat_extra_body


def _agnes_row(rows: list[dict]) -> dict:
    return next(p for p in rows if p["id"] == "agnes")


def test_agnes_listed_with_text_models(monkeypatch) -> None:
    monkeypatch.setenv("AGNES_API_KEY", "sk-agnes-test")
    monkeypatch.delenv("AGNES_API_KEYS", raising=False)
    monkeypatch.delenv("AGNES_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("AGNES_BASE_URL", raising=False)

    rows = list_llm_providers_public()
    agnes = _agnes_row(rows)

    ids = [m["id"] for m in agnes["models"]]
    assert ids[0] == "agnes-3.0-flash"
    assert "agnes-2.5-flash" in ids
    assert agnes["tier"] == "heavy"
    assert agnes["baseUrl"] == "https://apihub.agnes-ai.com/v1"
    assert agnes["configured"] is True
    assert agnes["keyHint"]


def test_agnes_unconfigured_without_key(monkeypatch) -> None:
    # `_env` 会 load_env()（backend/.env 可能真有 key），显式置空才算禁用
    monkeypatch.setenv("AGNES_API_KEY", "")
    monkeypatch.setenv("AGNES_API_KEYS", "")

    agnes = _agnes_row(list_llm_providers_public())

    assert agnes["configured"] is False
    assert agnes["keyHint"] is None


def test_resolve_agnes_selection_uses_agnes_env(monkeypatch) -> None:
    monkeypatch.setenv("AGNES_API_KEY", "sk-a,sk-b")
    monkeypatch.delenv("AGNES_API_KEYS", raising=False)
    monkeypatch.setenv("AGNES_BASE_URL", "https://agnes-proxy.example/v1")
    monkeypatch.delenv("AGNES_LLM_BASE_URL", raising=False)

    sel = resolve_llm_selection("agnes", "agnes-2.5-flash")

    assert sel["provider"] == "agnes"
    assert sel["model"] == "agnes-2.5-flash"
    assert sel["baseUrl"] == "https://agnes-proxy.example/v1"
    assert sel["keys"] == ("sk-a", "sk-b")
    assert sel["label"] == "Agnes AI · agnes-2.5-flash"


def test_resolve_agnes_falls_back_to_first_model(monkeypatch) -> None:
    monkeypatch.setenv("AGNES_API_KEY", "sk-agnes-test")
    monkeypatch.delenv("AGNES_API_KEYS", raising=False)

    sel = resolve_llm_selection("agnes", "not-a-model")

    assert sel["model"] == "agnes-3.0-flash"


def test_llm_env_for_agnes_sets_dual_keys(monkeypatch) -> None:
    monkeypatch.setenv("AGNES_API_KEY", "sk-agnes-test")
    monkeypatch.delenv("AGNES_API_KEYS", raising=False)

    env = llm_env_for_dual(resolve_llm_selection("agnes", "agnes-3.0-flash"))

    assert env["LLM_MODEL"] == "agnes-3.0-flash"
    assert env["LLM_BASE_URL"] == "https://apihub.agnes-ai.com/v1"
    assert env["LLM_API_KEY"] == "sk-agnes-test"
    assert env["AGNES_API_KEY"] == "sk-agnes-test"
    assert env["AGNES_API_KEYS"] == "sk-agnes-test"


def test_agnes_thinking_defaults_off(monkeypatch) -> None:
    monkeypatch.delenv("LLM_THINKING", raising=False)

    extra = _chat_extra_body("agnes-2.5-flash")

    assert extra == {"chat_template_kwargs": {"enable_thinking": False}}


def test_agnes_thinking_can_be_enabled(monkeypatch) -> None:
    monkeypatch.setenv("LLM_THINKING", "1")

    extra = _chat_extra_body("agnes-3.0-flash")

    assert extra == {"chat_template_kwargs": {"enable_thinking": True}}


def test_non_agnes_model_gets_no_chat_template_kwargs(monkeypatch) -> None:
    monkeypatch.delenv("LLM_THINKING", raising=False)

    extra = _chat_extra_body("gemini-3.8-flash")

    assert "chat_template_kwargs" not in (extra or {})
