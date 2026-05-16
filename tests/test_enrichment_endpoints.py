from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from backend.controllers.enrichment_controller import get_enrichment_service
from configuration.settings import settings
from main import app


class StubEnrichmentService:
    def __init__(self) -> None:
        self.run_process = AsyncMock()


@pytest.fixture
def enrichment_service_override() -> StubEnrichmentService:
    stub = StubEnrichmentService()

    def override_service() -> StubEnrichmentService:
        return stub

    app.dependency_overrides[get_enrichment_service] = override_service
    yield stub
    app.dependency_overrides.clear()


class TestEnrichmentEndpoints:
    def test_run_enrichment_valid_api_key_returns_202(
        self,
        monkeypatch: pytest.MonkeyPatch,
        enrichment_service_override: StubEnrichmentService,
    ) -> None:
        monkeypatch.setattr(settings, "API_KEY", "test-key")
        client = TestClient(app)

        response = client.post(
            "/api/enrichment/run",
            headers={"X-API-Key": "test-key"},
        )

        assert response.status_code == 202
        assert response.json() == {"message": "batch enrichment process initiated"}

    def test_run_enrichment_invalid_api_key_returns_401(
        self,
        monkeypatch: pytest.MonkeyPatch,
        enrichment_service_override: StubEnrichmentService,
    ) -> None:
        monkeypatch.setattr(settings, "API_KEY", "test-key")
        client = TestClient(app)

        response = client.post(
            "/api/enrichment/run",
            headers={"X-API-Key": "wrong-key"},
        )

        assert response.status_code == 401

    def test_run_enrichment_missing_api_key_returns_401(
        self,
        monkeypatch: pytest.MonkeyPatch,
        enrichment_service_override: StubEnrichmentService,
    ) -> None:
        monkeypatch.setattr(settings, "API_KEY", "test-key")
        client = TestClient(app)

        response = client.post("/api/enrichment/run")

        assert response.status_code == 401

    def test_run_enrichment_schedules_background_task(
        self,
        monkeypatch: pytest.MonkeyPatch,
        enrichment_service_override: StubEnrichmentService,
    ) -> None:
        monkeypatch.setattr(settings, "API_KEY", "test-key")
        client = TestClient(app)

        response = client.post(
            "/api/enrichment/run",
            headers={"X-API-Key": "test-key"},
        )

        assert response.status_code == 202
        enrichment_service_override.run_process.assert_awaited_once()
