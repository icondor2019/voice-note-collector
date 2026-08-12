from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from backend.controllers.session_documents_controller import (
    get_session_builder_service,
    get_session_documents_repository,
)
from backend.services.session_builder_service import NoValidNotesError
from configuration.settings import settings
from main import app


class StubSessionBuilderService:
    def __init__(self) -> None:
        self.build = AsyncMock(
            return_value={
                "id": "doc-123",
                "source_id": "source-1",
                "title": "Test Title",
                "content": "# Test Title\n\n## Summary\nTest Summary\n\n## Key Ideas\n- idea 1",
                "status": "ready",
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:00Z",
            }
        )
        self.preview = AsyncMock(
            return_value={
                "pending_count": 2,
                "un_enriched_count": 1,
                "time_range": "2026-01-01 → 2026-01-02",
                "notes": [],
            }
        )


class StubSessionDocumentsRepository:
    def __init__(self) -> None:
        self.get_document = AsyncMock(
            return_value={
                "id": "doc-123",
                "source_id": "source-1",
                "title": "Test Title",
                "content": "# Test Title\n\n## Summary\nTest Summary",
                "status": "ready",
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:00Z",
            }
        )
        self.get_document_labels = AsyncMock(return_value=[])


@pytest.fixture
def builder_service_override() -> StubSessionBuilderService:
    stub = StubSessionBuilderService()

    def override() -> StubSessionBuilderService:
        return stub

    app.dependency_overrides[get_session_builder_service] = override
    yield stub
    app.dependency_overrides.clear()


@pytest.fixture
def docs_repo_override() -> StubSessionDocumentsRepository:
    stub = StubSessionDocumentsRepository()

    def override() -> StubSessionDocumentsRepository:
        return stub

    app.dependency_overrides[get_session_documents_repository] = override
    yield stub
    app.dependency_overrides.clear()


class TestSessionDocumentsController:
    def test_post_create_session_document_returns_201(
        self,
        monkeypatch: pytest.MonkeyPatch,
        builder_service_override: StubSessionBuilderService,
    ) -> None:
        monkeypatch.setattr(settings, "API_KEY", "test-key")
        client = TestClient(app)

        response = client.post(
            "/api/session-documents",
            json={
                "source_id": "a0dcea10-ca65-4314-af78-ce096824aff1",
                "note_ids": ["b0dcea10-ca65-4314-af78-ce096824aff1"],
            },
            headers={"X-API-Key": "test-key"},
        )

        assert response.status_code == 201
        data = response.json()
        assert data["id"] == "doc-123"
        assert data["title"] == "Test Title"
        assert "content" in data
        builder_service_override.build.assert_awaited_once()

    def test_post_create_with_no_valid_notes_returns_400(
        self,
        monkeypatch: pytest.MonkeyPatch,
        builder_service_override: StubSessionBuilderService,
    ) -> None:
        monkeypatch.setattr(settings, "API_KEY", "test-key")
        builder_service_override.build = AsyncMock(
            side_effect=NoValidNotesError("No valid notes")
        )
        client = TestClient(app)

        response = client.post(
            "/api/session-documents",
            json={
                "source_id": "a0dcea10-ca65-4314-af78-ce096824aff1",
                "note_ids": ["b0dcea10-ca65-4314-af78-ce096824aff1"],
            },
            headers={"X-API-Key": "test-key"},
        )

        assert response.status_code == 400

    def test_get_session_document_returns_document_with_labels(
        self,
        monkeypatch: pytest.MonkeyPatch,
        docs_repo_override: StubSessionDocumentsRepository,
    ) -> None:
        monkeypatch.setattr(settings, "API_KEY", "test-key")
        client = TestClient(app)

        response = client.get(
            "/api/session-documents/doc-123",
            headers={"X-API-Key": "test-key"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "doc-123"
        assert "content" in data
        assert "labels" in data
        assert "components" not in data

    def test_get_session_document_returns_404_for_missing(
        self,
        monkeypatch: pytest.MonkeyPatch,
        docs_repo_override: StubSessionDocumentsRepository,
    ) -> None:
        monkeypatch.setattr(settings, "API_KEY", "test-key")
        docs_repo_override.get_document = AsyncMock(return_value=None)
        client = TestClient(app)

        response = client.get(
            "/api/session-documents/nonexistent",
            headers={"X-API-Key": "test-key"},
        )

        assert response.status_code == 404
