"""SiliconFlow image fallback config."""

from __future__ import annotations

from image.generate import ImageApiConfig, siliconflow_fallback_config


def test_siliconflow_fallback_when_primary_is_openai(monkeypatch) -> None:
    monkeypatch.setenv("SILICONFLOW_API_KEY", "sk-sf-test")
    monkeypatch.delenv("SILICONFLOW_API_KEYS", raising=False)
    monkeypatch.delenv("IMAGE_FALLBACK_SILICONFLOW", raising=False)
    primary = ImageApiConfig(
        api_keys=("sk-maizi",),
        base_url="https://gateway.example/v1",
        model="nano-banana-fast",
        size="16:9",
        skip=False,
        provider="openai",
        transport="openai-images",
    )
    fb = siliconflow_fallback_config(primary=primary)
    assert fb is not None
    assert fb.transport == "siliconflow-images"
    assert fb.base_url == "https://api.siliconflow.cn/v1"
    assert fb.model == "Tongyi-MAI/Z-Image-Turbo"
    assert fb.api_keys == ("sk-sf-test",)


def test_siliconflow_fallback_when_primary_sf_other_model(monkeypatch) -> None:
    monkeypatch.setenv("SILICONFLOW_API_KEY", "sk-sf-test")
    monkeypatch.delenv("IMAGE_FALLBACK_SILICONFLOW", raising=False)
    primary = ImageApiConfig(
        api_keys=("sk-sf-test",),
        base_url="https://api.siliconflow.cn/v1",
        model="free-image-model.online.image-cnt",
        size="3:4",
        skip=False,
        provider="siliconflow",
        transport="siliconflow-images",
    )
    fb = siliconflow_fallback_config(primary=primary)
    assert fb is not None
    assert fb.model == "Tongyi-MAI/Z-Image-Turbo"


def test_siliconflow_fallback_disabled_when_primary_is_same_model(monkeypatch) -> None:
    monkeypatch.setenv("SILICONFLOW_API_KEY", "sk-sf-test")
    primary = ImageApiConfig(
        api_keys=("sk-sf-test",),
        base_url="https://api.siliconflow.cn/v1",
        model="Tongyi-MAI/Z-Image-Turbo",
        size="3:4",
        skip=False,
        provider="siliconflow",
        transport="siliconflow-images",
    )
    assert siliconflow_fallback_config(primary=primary) is None


def test_siliconflow_fallback_can_be_turned_off(monkeypatch) -> None:
    monkeypatch.setenv("SILICONFLOW_API_KEY", "sk-sf-test")
    monkeypatch.setenv("IMAGE_FALLBACK_SILICONFLOW", "0")
    primary = ImageApiConfig(
        api_keys=("sk-maizi",),
        base_url="https://gateway.example/v1",
        model="nano-banana-fast",
        size="16:9",
        skip=False,
        provider="openai",
        transport="openai-images",
    )
    assert siliconflow_fallback_config(primary=primary) is None
