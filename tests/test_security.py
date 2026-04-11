from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from backend.controllers.sources_controller import get_source_service
from backend.controllers.telegram_controller import get_message_handler
from backend.services.telegram_message_handler import TelegramMessageHandler
from configuration.settings import settings
from main import app, create_app


class StubSourceService:
    def __init__(self, *, list_result: list[dict[str, Any]] | None = None) -> None:
        self.list_result = list_result or []
        self.list_status: str | None = None

    async def list_sources(self, *, status: str | None = None) -> list[dict[str, Any]]:
        self.list_status = status
        return self.list_result


@pytest.fixture
def stub_source_service() -> StubSourceService:
    return StubSourceService()


@pytest.fixture
def mock_message_handler() -> TelegramMessageHandler:
    handler = AsyncMock(spec=TelegramMessageHandler)
    handler.handle = AsyncMock(return_value={"processed": True})
    return handler


class TestTelegramWebhookSecretValidation:
    def test_webhook_no_secret_configured_passes(
        self,
        monkeypatch: pytest.MonkeyPatch,
        mock_message_handler: TelegramMessageHandler,
    ) -> None:
        monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", None)
        app.dependency_overrides[get_message_handler] = lambda: mock_message_handler
        client = TestClient(app)

        response = client.post("/api/telegram/webhook", json={"update_id": 1})

        app.dependency_overrides.clear()
        assert response.status_code == 200
        assert response.json()["status"] == "ok"
        mock_message_handler.handle.assert_awaited_once()

    def test_webhook_correct_secret_passes(
        self,
        monkeypatch: pytest.MonkeyPatch,
        mock_message_handler: TelegramMessageHandler,
    ) -> None:
        monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", "test-secret")
        app.dependency_overrides[get_message_handler] = lambda: mock_message_handler
        client = TestClient(app)

        response = client.post(
            "/api/telegram/webhook",
            json={"update_id": 1},
            headers={"X-Telegram-Bot-Api-Secret-Token": "test-secret"},
        )

        app.dependency_overrides.clear()
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_webhook_wrong_secret_returns_403(
        self,
        monkeypatch: pytest.MonkeyPatch,
        mock_message_handler: TelegramMessageHandler,
    ) -> None:
        monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", "test-secret")
        app.dependency_overrides[get_message_handler] = lambda: mock_message_handler
        client = TestClient(app)

        response = client.post(
            "/api/telegram/webhook",
            json={"update_id": 1},
            headers={"X-Telegram-Bot-Api-Secret-Token": "wrong-secret"},
        )

        app.dependency_overrides.clear()
        assert response.status_code == 403
        mock_message_handler.handle.assert_not_called()

    def test_webhook_missing_secret_header_returns_403(
        self,
        monkeypatch: pytest.MonkeyPatch,
        mock_message_handler: TelegramMessageHandler,
    ) -> None:
        monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", "test-secret")
        app.dependency_overrides[get_message_handler] = lambda: mock_message_handler
        client = TestClient(app)

        response = client.post("/api/telegram/webhook", json={"update_id": 1})

        app.dependency_overrides.clear()
        assert response.status_code == 403
        mock_message_handler.handle.assert_not_called()


class TestApiKeyValidation:
    def test_sources_no_api_key_configured_passes(
        self,
        monkeypatch: pytest.MonkeyPatch,
        stub_source_service: StubSourceService,
    ) -> None:
        monkeypatch.setattr(settings, "API_KEY", None)
        app.dependency_overrides[get_source_service] = lambda: stub_source_service
        client = TestClient(app)

        response = client.get("/api/sources")

        app.dependency_overrides.clear()
        assert response.status_code == 200
        assert response.json() == []

    def test_sources_correct_api_key_passes(
        self,
        monkeypatch: pytest.MonkeyPatch,
        stub_source_service: StubSourceService,
    ) -> None:
        monkeypatch.setattr(settings, "API_KEY", "my-key")
        app.dependency_overrides[get_source_service] = lambda: stub_source_service
        client = TestClient(app)

        response = client.get("/api/sources", headers={"X-API-Key": "my-key"})

        app.dependency_overrides.clear()
        assert response.status_code == 200

    def test_sources_wrong_api_key_returns_401(
        self,
        monkeypatch: pytest.MonkeyPatch,
        stub_source_service: StubSourceService,
    ) -> None:
        monkeypatch.setattr(settings, "API_KEY", "my-key")
        app.dependency_overrides[get_source_service] = lambda: stub_source_service
        client = TestClient(app)

        response = client.get("/api/sources", headers={"X-API-Key": "wrong-key"})

        app.dependency_overrides.clear()
        assert response.status_code == 401

    def test_sources_missing_api_key_returns_401(
        self,
        monkeypatch: pytest.MonkeyPatch,
        stub_source_service: StubSourceService,
    ) -> None:
        monkeypatch.setattr(settings, "API_KEY", "my-key")
        app.dependency_overrides[get_source_service] = lambda: stub_source_service
        client = TestClient(app)

        response = client.get("/api/sources")

        app.dependency_overrides.clear()
        assert response.status_code == 401

    def test_health_unprotected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "API_KEY", "my-key")
        client = TestClient(app)

        response = client.get("/api/health")

        assert response.status_code == 200


class TestDocsDisabledInProduction:
    def test_docs_disabled_in_prod(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "ENVIRONMENT", "prod")
        client = TestClient(create_app())

        response = client.get("/docs")

        assert response.status_code == 404

    def test_redoc_disabled_in_prod(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "ENVIRONMENT", "prod")
        client = TestClient(create_app())

        response = client.get("/redoc")

        assert response.status_code == 404

    def test_openapi_disabled_in_prod(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "ENVIRONMENT", "prod")
        client = TestClient(create_app())

        response = client.get("/openapi.json")

        assert response.status_code == 404

    def test_docs_enabled_in_local(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "ENVIRONMENT", "local")
        client = TestClient(create_app())

        response = client.get("/docs")

        assert response.status_code == 200
