"""OpenCode local proxy provider catalog and task environment."""

from __future__ import annotations

from admin.providers import (
    list_gallery_model_catalog,
    list_llm_providers_public,
    llm_env_for_dual,
    resolve_llm_selection,
)


def _row(rows: list[dict]) -> dict:
    return next(p for p in rows if p["id"] == "opencode")


def test_opencode_listed_with_requested_model(monkeypatch) -> None:
    monkeypatch.setenv("OPENCODE_API_KEY", "dummy")
    monkeypatch.delenv("OPENCODE_API_KEYS", raising=False)
    monkeypatch.delenv("OPENCODE_BASE_URL", raising=False)

    opencode = _row(list_llm_providers_public())

    assert opencode["label"] == "OpenCode 反代"
    assert opencode["baseUrl"] == "http://127.0.0.1:8787/v1"
    assert opencode["models"] == [
        {
            "id": "opencode/deepseek-v4.1-flash-free",
            "label": "DeepSeek V4.1 Flash Free",
        }
    ]
    assert opencode["configured"] is True


def test_opencode_base_url_can_be_overridden(monkeypatch) -> None:
    monkeypatch.setenv("OPENCODE_API_KEY", "dummy")
    monkeypatch.setenv("OPENCODE_BASE_URL", "http://localhost:9999/v1")

    public = _row(list_llm_providers_public())
    selection = resolve_llm_selection(
        "opencode", "opencode/deepseek-v4.1-flash-free"
    )

    assert public["baseUrl"] == "http://localhost:9999/v1"
    assert selection["baseUrl"] == "http://localhost:9999/v1"


def test_opencode_task_env_uses_generic_and_dedicated_keys(monkeypatch) -> None:
    monkeypatch.setenv("OPENCODE_API_KEYS", "dummy")
    monkeypatch.delenv("OPENCODE_API_KEY", raising=False)
    monkeypatch.setenv("OPENCODE_BASE_URL", "http://127.0.0.1:8787/v1")

    selection = resolve_llm_selection(
        "opencode", "opencode/deepseek-v4.1-flash-free"
    )
    env = llm_env_for_dual(selection)

    assert selection["keys"] == ("dummy",)
    assert env == {
        "LLM_API_KEY": "dummy",
        "LLM_API_KEYS": "dummy",
        "LLM_BASE_URL": "http://127.0.0.1:8787/v1",
        "LLM_MODEL": "opencode/deepseek-v4.1-flash-free",
        "OPENCODE_API_KEY": "dummy",
        "OPENCODE_API_KEYS": "dummy",
    }


def test_gallery_catalog_exposes_opencode_for_dropdowns(monkeypatch) -> None:
    monkeypatch.setenv("OPENCODE_API_KEY", "dummy")
    monkeypatch.delenv("OPENCODE_API_KEYS", raising=False)

    opencode = _row(list_gallery_model_catalog()["llmProviders"])

    assert opencode["configured"] is True
    assert opencode["models"][0]["id"] == "opencode/deepseek-v4.1-flash-free"
