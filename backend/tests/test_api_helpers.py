"""Backend API helper and security regression tests."""

from __future__ import annotations

import json

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from admin.fsutil import resolve_under
from api.auth import assert_admin, extract_token
from api.http import err, http_error_from_message, ok, require_safe_id
from api.routes.files import _inject_align, _rewrite_asset_urls
from api.routes.templates import _safe
from gallery.catalog import public_templates


def _request(
    *, headers: dict[str, str] | None = None, cookies: dict[str, str] | None = None
) -> Request:
    header_items = [
        (key.lower().encode(), value.encode())
        for key, value in (headers or {}).items()
    ]
    if cookies:
        cookie_header = "; ".join(f"{key}={value}" for key, value in cookies.items())
        header_items.append((b"cookie", cookie_header.encode()))
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": header_items,
        "query_string": b"",
        "client": ("testclient", 1234),
        "server": ("testserver", 80),
        "scheme": "http",
    }
    return Request(scope)


def test_extract_token_priority_and_supported_credentials() -> None:
    request = _request(
        headers={"authorization": "Bearer from-auth"},
        cookies={"webppt_admin_token": "from-cookie"},
    )
    assert extract_token(request, "from-x-header", "Bearer ignored") == "from-x-header"
    assert extract_token(request, "", "Bearer from-auth") == "from-auth"
    assert extract_token(_request(cookies={"webppt_admin_token": "from-cookie"})) == "from-cookie"


def test_assert_admin_reports_missing_and_invalid_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request()
    monkeypatch.delenv("ADMIN_TOKEN", raising=False)
    with pytest.raises(HTTPException) as missing:
        assert_admin(request, "", "")
    assert missing.value.status_code == 503

    monkeypatch.setenv("ADMIN_TOKEN", "expected")
    with pytest.raises(HTTPException) as invalid:
        assert_admin(request, "wrong", "")
    assert invalid.value.status_code == 401
    assert assert_admin(request, "expected", "") is None


def test_http_helpers_return_expected_json_and_status() -> None:
    assert err(400, error="BAD").status_code == 400
    assert json.loads(err(400, error="BAD").body) == {"error": "BAD"}
    assert json.loads(ok(ok=True).body) == {"ok": True}
    assert json.loads(http_error_from_message("模板不存在").body)["error"] == "模板不存在"
    assert http_error_from_message("模板不存在").status_code == 404
    assert http_error_from_message("请先上传文件").status_code == 400


def test_safe_ids_reject_path_traversal_and_accept_unicode() -> None:
    assert require_safe_id("demo-01") == "demo-01"
    assert require_safe_id("../secret").status_code == 400
    assert _safe("中文模板-1") == "中文模板-1"
    assert _safe("bad/id").status_code == 400
    assert resolve_under("demo", "../outside.txt") is None
    assert resolve_under("../demo", "file.txt") is None


def test_asset_rewrite_handles_attributes_and_css_urls() -> None:
    html = (
        '<link href="../theme.css"><img src="../images/hero.png">'
        '<style>.x{background:url(../images/bg.png)}</style>'
    )
    out = _rewrite_asset_urls(html, "demo-01")
    assert 'href="/api/html-templates/demo-01/assets/theme.css"' in out
    assert 'src="/api/html-templates/demo-01/assets/images/hero.png"' in out
    assert "url(/api/html-templates/demo-01/assets/images/bg.png)" in out


def test_align_injection_only_targets_element_slides() -> None:
    plain = "<html><head></head><body>plain</body></html>"
    assert _inject_align(plain) == plain

    html = '<html><head></head><body><div data-element="text"></div></body></html>'
    out = _inject_align(html)
    assert out.count("webppt-data-element-preview-align") == 1
    assert "justify-content:center" in out


def test_public_templates_keeps_only_uploaded_approved_https_rows() -> None:
    rows = [
        {
            "id": "visible",
            "title": "Visible",
            "description": "ok",
            "slide_count": 1,
            "cover": "https://cdn.example/cover.html",
            "pages": ["https://cdn.example/cover.html"],
            "status": "approved",
            "storage_backend": "qiniu",
            "featured": True,
            "updated_ms": 20,
        },
        {
            "id": "draft",
            "title": "Draft",
            "description": "draft",
            "slide_count": 1,
            "cover": "https://cdn.example/draft.html",
            "pages": ["https://cdn.example/draft.html"],
            "status": "draft",
            "storage_backend": "qiniu",
            "updated_ms": 30,
        },
        {
            "id": "local",
            "title": "Local",
            "description": "local",
            "slide_count": 1,
            "cover": "https://cdn.example/local.html",
            "pages": ["https://cdn.example/local.html"],
            "status": "approved",
            "storage_backend": "local",
            "updated_ms": 40,
        },
    ]
    result = public_templates(rows)
    assert [row["id"] for row in result] == ["visible"]
    assert result[0]["featured"] is True
    assert result[0]["slideCount"] == 1
