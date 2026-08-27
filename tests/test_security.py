import asyncio

import pytest
from fastapi import HTTPException
from starlette.requests import Request

import app


def request(headers: list[tuple[bytes, bytes]] | None = None) -> Request:
    return Request({"type": "http", "method": "GET", "path": "/", "headers": headers or []})


def test_auth_fails_closed_without_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app.settings, "inbound_api_keys", [])
    monkeypatch.setattr(app.settings, "allow_unauthenticated", False)

    with pytest.raises(HTTPException) as error:
        app.require_auth(request())

    assert error.value.status_code == 503


def test_auth_accepts_only_configured_bearer_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app.settings, "inbound_api_keys", ["expected-secret"])
    monkeypatch.setattr(app.settings, "allow_unauthenticated", False)
    app.require_auth(request([(b"authorization", b"Bearer expected-secret")]))

    with pytest.raises(HTTPException) as error:
        app.require_auth(request([(b"authorization", b"Bearer wrong")]))
    assert error.value.status_code == 401


def test_sensitive_client_headers_are_not_forwarded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app.settings, "upstream_api_key", "upstream-secret")
    req = request(
        [
            (b"authorization", b"Bearer client-secret"),
            (b"cookie", b"session=secret"),
            (b"x-forwarded-for", b"203.0.113.1"),
            (b"x-request-id", b"safe-id"),
        ]
    )

    headers = app.build_upstream_headers(req)

    assert headers["authorization"] == "Bearer upstream-secret"
    assert "cookie" not in headers
    assert "x-forwarded-for" not in headers
    assert headers["x-request-id"] == "safe-id"


@pytest.mark.parametrize("path", ["", "../admin", "models//admin", "models\\admin", "models/./admin"])
def test_ambiguous_upstream_paths_are_rejected(path: str) -> None:
    with pytest.raises(HTTPException) as error:
        app.validate_upstream_path(path)
    assert error.value.status_code == 400


def test_oversized_string_is_rejected_instead_of_bypassing_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app.settings, "max_string_chars", 3)

    with pytest.raises(HTTPException) as error:
        asyncio.run(app.sanitizer.sanitize_payload({"prompt": "secret"}))

    assert error.value.status_code == 413
    assert error.value.detail == "string_too_large_to_sanitize"


def test_model_labels_cannot_inject_placeholders_or_metrics() -> None:
    assert app.normalize_label('PERSON"]}\nforged_metric 1') == "person_forged_metric_1"
    assert len(app.normalize_label("x" * 100)) == 64
