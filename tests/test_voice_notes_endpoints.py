from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

import pytest
from fastapi.testclient import TestClient

from backend.controllers.voice_notes_controller import get_voice_note_service
from backend.repositories.repository_errors import RepositoryError
from main import app


class StubVoiceNoteService:
    def __init__(
        self,
        *,
        list_result: Optional[list[dict[str, Any]]] = None,
        get_result: Optional[dict[str, Any]] = None,
        create_result: Optional[dict[str, Any]] = None,
        raise_on_create: Optional[Exception] = None,
        raise_on_list: Optional[Exception] = None,
        raise_on_get: Optional[Exception] = None,
    ) -> None:
        self.list_result = list_result or []
        self.get_result = get_result
        self.create_result = create_result or {}
        self.raise_on_create = raise_on_create
        self.raise_on_list = raise_on_list
        self.raise_on_get = raise_on_get
        self.list_params: Optional[dict[str, Any]] = None
        self.get_note_id: Optional[str] = None
        self.created_payload: Optional[dict[str, Any]] = None

    async def list_voice_notes(
        self,
        *,
        source_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
        created_after: Optional[datetime] = None,
        created_before: Optional[datetime] = None,
    ) -> list[dict[str, Any]]:
        if self.raise_on_list:
            raise self.raise_on_list
        self.list_params = {
            "source_id": source_id,
            "limit": limit,
            "offset": offset,
            "created_after": created_after,
            "created_before": created_before,
        }
        return self.list_result

    async def get_voice_note(self, note_id: str) -> Optional[dict[str, Any]]:
        if self.raise_on_get:
            raise self.raise_on_get
        self.get_note_id = note_id
        return self.get_result

    async def create_voice_note_idempotent(
        self,
        *,
        raw_text: str,
        clean_text: Optional[str],
        message_id: int,
        audio_file_id: str,
        duration_seconds: Optional[float] = None,
    ) -> dict[str, Any]:
        if self.raise_on_create:
            raise self.raise_on_create
        self.created_payload = {
            "raw_text": raw_text,
            "clean_text": clean_text,
            "message_id": message_id,
            "audio_file_id": audio_file_id,
            "duration_seconds": duration_seconds,
        }
        return self.create_result


@pytest.fixture
def voice_note_service_override():
    stub = StubVoiceNoteService()

    def override_service() -> StubVoiceNoteService:
        return stub

    app.dependency_overrides[get_voice_note_service] = override_service
    yield stub
    app.dependency_overrides.clear()


class TestVoiceNoteEndpoints:
    def test_list_voice_notes_forwards_filters(self, voice_note_service_override: StubVoiceNoteService) -> None:
        voice_note_service_override.list_result = [
            {"id": "note-1", "source_id": "source-1"},
        ]
        client = TestClient(app)

        response = client.get(
            "/api/voice-notes",
            params={
                "source_id": "source-1",
                "limit": 10,
                "offset": 5,
                "created_after": "2026-03-01T00:00:00",
            },
        )

        assert response.status_code == 200
        assert response.json() == voice_note_service_override.list_result
        assert voice_note_service_override.list_params == {
            "source_id": "source-1",
            "limit": 10,
            "offset": 5,
            "created_after": datetime.fromisoformat("2026-03-01T00:00:00"),
            "created_before": None,
        }

    def test_get_voice_note_returns_404_when_missing(self, voice_note_service_override: StubVoiceNoteService) -> None:
        voice_note_service_override.get_result = None
        client = TestClient(app)

        response = client.get("/api/voice-notes/note-404")

        assert response.status_code == 404
        assert response.json()["detail"] == "Voice note not found"
        assert voice_note_service_override.get_note_id == "note-404"

    def test_get_voice_note_returns_payload(self, voice_note_service_override: StubVoiceNoteService) -> None:
        voice_note_service_override.get_result = {
            "id": "note-1",
            "raw_text": "Hello",
        }
        client = TestClient(app)

        response = client.get("/api/voice-notes/note-1")

        assert response.status_code == 200
        assert response.json() == voice_note_service_override.get_result

    def test_create_voice_note_returns_payload(self, voice_note_service_override: StubVoiceNoteService) -> None:
        voice_note_service_override.create_result = {
            "id": "note-1",
            "raw_text": "Hello",
            "message_id": 101,
        }
        client = TestClient(app)

        response = client.post(
            "/api/voice-notes/add/voice-notes",
            json={
                "raw_text": "Hello",
                "clean_text": "Hello",
                "message_id": 101,
                "audio_file_id": "file-1",
                "duration_seconds": 2.5,
            },
        )

        assert response.status_code == 200
        assert response.json() == voice_note_service_override.create_result
        assert voice_note_service_override.created_payload == {
            "raw_text": "Hello",
            "clean_text": "Hello",
            "message_id": 101,
            "audio_file_id": "file-1",
            "duration_seconds": 2.5,
        }

    def test_create_voice_note_returns_503_on_repository_error(
        self,
        voice_note_service_override: StubVoiceNoteService,
    ) -> None:
        voice_note_service_override.raise_on_create = RepositoryError("down")
        client = TestClient(app)

        response = client.post(
            "/api/voice-notes/add/voice-notes",
            json={
                "raw_text": "Hello",
                "message_id": 101,
                "audio_file_id": "file-1",
            },
        )

        assert response.status_code == 503
        assert response.json()["detail"] == "Supabase unavailable"
