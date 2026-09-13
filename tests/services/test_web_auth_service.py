from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.services.web_auth_service import WebAuthError, WebAuthService
from configuration.settings import settings


def auth_response(email: str, access: str = "access", refresh: str = "refresh") -> SimpleNamespace:
    return SimpleNamespace(
        user=SimpleNamespace(email=email),
        session=SimpleNamespace(access_token=access, refresh_token=refresh),
    )


@pytest.mark.anyio
async def test_sign_in_accepts_only_allowlisted_email(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "WEB_AUTH_DISABLED", False)
    monkeypatch.setattr(settings, "WEB_ALLOWED_EMAIL", "owner@example.com")
    client = SimpleNamespace(
        auth=SimpleNamespace(
            sign_in_with_password=AsyncMock(return_value=auth_response("owner@example.com")),
            sign_out=AsyncMock(),
        )
    )
    service = WebAuthService()
    monkeypatch.setattr(service, "_client", AsyncMock(return_value=client))

    session = await service.sign_in("owner@example.com", "secret")

    assert session.email == "owner@example.com"
    assert session.access_token == "access"


@pytest.mark.anyio
async def test_sign_in_rejects_other_authenticated_user(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "WEB_AUTH_DISABLED", False)
    monkeypatch.setattr(settings, "WEB_ALLOWED_EMAIL", "owner@example.com")
    sign_out = AsyncMock()
    client = SimpleNamespace(
        auth=SimpleNamespace(
            sign_in_with_password=AsyncMock(return_value=auth_response("other@example.com")),
            sign_out=sign_out,
        )
    )
    service = WebAuthService()
    monkeypatch.setattr(service, "_client", AsyncMock(return_value=client))

    with pytest.raises(WebAuthError):
        await service.sign_in("other@example.com", "secret")
    sign_out.assert_awaited_once()


@pytest.mark.anyio
async def test_validate_session_refreshes_expired_access_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "WEB_AUTH_DISABLED", False)
    monkeypatch.setattr(settings, "WEB_ALLOWED_EMAIL", "owner@example.com")
    client = SimpleNamespace(
        auth=SimpleNamespace(
            get_user=AsyncMock(side_effect=RuntimeError("expired")),
            refresh_session=AsyncMock(return_value=auth_response("owner@example.com", "new-access", "new-refresh")),
        )
    )
    service = WebAuthService()
    monkeypatch.setattr(service, "_client", AsyncMock(return_value=client))

    session = await service.validate_session("old-access", "refresh")

    assert session.refreshed is True
    assert session.access_token == "new-access"


@pytest.mark.anyio
async def test_validate_session_rejects_missing_cookies() -> None:
    with pytest.raises(WebAuthError):
        await WebAuthService().validate_session(None, None)


@pytest.mark.anyio
async def test_local_auth_bypass_accepts_any_values_without_supabase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "WEB_AUTH_DISABLED", True)
    monkeypatch.setattr(settings, "ENVIRONMENT", "local")
    service = WebAuthService()
    session = await service.sign_in("anything@example.com", "anything")

    assert session.email == "anything@example.com"
    assert await service.validate_session(
        session.access_token, session.refresh_token
    )


@pytest.mark.anyio
async def test_local_auth_bypass_never_applies_in_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "WEB_AUTH_DISABLED", True)
    monkeypatch.setattr(settings, "ENVIRONMENT", "prod")
    service = WebAuthService()

    with pytest.raises(WebAuthError):
        await service.validate_session(None, None)


@pytest.mark.anyio
async def test_local_auth_bypass_supports_development_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "WEB_AUTH_DISABLED", True)
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    session = await WebAuthService().sign_in("preview@example.com", "anything")
    assert session.access_token == "local-preview-access"
