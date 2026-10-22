"""Agnes image transport and provider configuration."""

from __future__ import annotations

import json

from admin.providers import (
    image_env_for_selection,
    list_image_providers_public,
    resolve_image_selection,
)
from image import generate as image_generate


class _JsonResponse:
    def __init__(self, payload: dict):
        self._payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self) -> bytes:
        return self._payload


def test_agnes_image_config_uses_dedicated_defaults(monkeypatch) -> None:
    monkeypatch.setenv("IMAGE_API_PROVIDER", "agnes")
    monkeypatch.setenv("AGNES_API_KEY", "sk-agnes-test")
    monkeypatch.delenv("AGNES_API_KEYS", raising=False)
    monkeypatch.delenv("IMAGE_API_KEY", raising=False)
    monkeypatch.delenv("IMAGE_API_KEYS", raising=False)
    monkeypatch.delenv("IMAGE_MODEL", raising=False)
    monkeypatch.delenv("IMAGE_API_BASE_URL", raising=False)
    monkeypatch.delenv("AGNES_BASE_URL", raising=False)

    cfg = image_generate.image_api_config()

    assert cfg.provider == "agnes"
    assert cfg.transport == "agnes-images"
    assert cfg.base_url == "https://apihub.agnes-ai.com/v1"
    assert cfg.model == "agnes-image-2.5-flash"
    assert cfg.api_keys == ("sk-agnes-test",)
    assert cfg.skip is False


def test_agnes_payload_uses_resolution_tier_and_ratio(monkeypatch) -> None:
    captured: dict = {}

    def fake_urlopen(req, timeout):
        captured["url"] = req.full_url
        captured["headers"] = dict(req.header_items())
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return _JsonResponse(
            {
                "data": [
                    {
                        "url": "https://cdn.example/agnes.png",
                        "b64_json": None,
                    }
                ]
            }
        )

    monkeypatch.setenv("IMAGE_RESOLUTION", "2k")
    monkeypatch.setattr(image_generate.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(
        image_generate,
        "_download",
        lambda url, timeout: b"\x89PNG\r\n\x1a\n" + b"x" * 32,
    )

    data = image_generate.generate_image_bytes_agnes(
        base_url="https://apihub.agnes-ai.com/v1",
        api_key="sk-agnes-test",
        model="agnes-image-2.5-flash",
        prompt="A clean editorial landscape",
        size="16:9",
    )

    assert data.startswith(b"\x89PNG")
    assert captured["url"] == "https://apihub.agnes-ai.com/v1/images/generations"
    assert captured["headers"]["Authorization"] == "Bearer sk-agnes-test"
    assert captured["body"] == {
        "model": "agnes-image-2.5-flash",
        "prompt": "A clean editorial landscape",
        "size": "2K",
        "ratio": "16:9",
        "extra_body": {"response_format": "url"},
    }


def test_agnes_base64_response(monkeypatch) -> None:
    png = b"\x89PNG\r\n\x1a\n" + b"x" * 16
    response = _JsonResponse(
        {"data": [{"b64_json": image_generate.base64.b64encode(png).decode()}]}
    )
    monkeypatch.setattr(
        image_generate.urllib.request,
        "urlopen",
        lambda req, timeout: response,
    )

    data = image_generate.generate_image_bytes_agnes(
        base_url="https://apihub.agnes-ai.com",
        api_key="sk-agnes-test",
        model="agnes-image-2.5-flash",
        prompt="A blue circle",
        size="1:1",
    )

    assert data == png


def test_agnes_resolution_normalization() -> None:
    assert image_generate.normalize_agnes_resolution("2k") == "2K"
    assert image_generate.normalize_agnes_resolution("4096") == "4K"
    assert image_generate.normalize_agnes_resolution("giant") == "1K"


def test_agnes_provider_catalog_and_selection(monkeypatch) -> None:
    monkeypatch.setenv("AGNES_API_KEY", "sk-agnes-test")
    monkeypatch.delenv("AGNES_API_KEYS", raising=False)
    monkeypatch.delenv("AGNES_BASE_URL", raising=False)

    providers = list_image_providers_public()
    agnes = next(p for p in providers if p["id"] == "agnes")
    assert agnes["configured"] is True
    assert agnes["transport"] == "agnes-images"
    assert agnes["models"][0]["id"] == "agnes-image-2.5-flash"

    selection = resolve_image_selection("agnes", "agnes-image-2.5-flash")
    env = image_env_for_selection(selection)
    assert env["IMAGE_API_PROVIDER"] == "agnes"
    assert env["IMAGE_TRANSPORT"] == "agnes-images"
    assert env["AGNES_API_KEY"] == "sk-agnes-test"
    assert env["IMAGE_API_KEY"] == "sk-agnes-test"
