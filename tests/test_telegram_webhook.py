import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from backend.controllers.telegram_controller import get_voice_note_service
from backend.repositories.repository_errors import DuplicateRecordError, RepositoryError
from backend.services.voice_note_service import VoiceNoteService
from main import app


def _load_fixture(name: str) -> dict:
    fixture_path = Path(__file__).parent / "fixtures" / "telegram" / name
    return json.loads(fixture_path.read_text(encoding="utf-8"))


@pytest.fixture
def mock_voice_note_service() -> VoiceNoteService:
    service = AsyncMock(spec=VoiceNoteService)
    service.create_voice_note_idempotent = AsyncMock(return_value={"id": "note-1"})
    return service


@pytest.fixture
def client(mock_voice_note_service: VoiceNoteService) -> TestClient:
    app.dependency_overrides[get_voice_note_service] = lambda: mock_voice_note_service
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_webhook_rejects_invalid_json_body(
    client: TestClient,
    mock_voice_note_service: VoiceNoteService,
) -> None:
    response = client.post(
        "/api/telegram/webhook",
        data="{this-is:not-valid-json}",
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid JSON payload"
    mock_voice_note_service.create_voice_note_idempotent.assert_not_called()


def test_webhook_rejects_non_dict_json(
    client: TestClient,
    mock_voice_note_service: VoiceNoteService,
) -> None:
    response = client.post("/api/telegram/webhook", json=["not", "a", "dict"])

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid JSON payload"
    mock_voice_note_service.create_voice_note_idempotent.assert_not_called()


def test_webhook_stores_voice_message(
    client: TestClient,
    mock_voice_note_service: VoiceNoteService,
) -> None:
    response = client.post("/api/telegram/webhook", json=_load_fixture("voice_message.json"))

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["outcome"] == "stored"
    mock_voice_note_service.create_voice_note_idempotent.assert_awaited_once_with(
        message_id=11,
        audio_file_id="AwACAgEAAxkBAAMLadb0gz7ExnTG0QfyXx4r30tC_XoAAssGAAJ-1rhGXFdggTuGGfc7BA",
        duration_seconds=8,
        raw_text="",
        clean_text=None,
    )


def test_webhook_stores_audio_message(
    client: TestClient,
    mock_voice_note_service: VoiceNoteService,
) -> None:
    response = client.post("/api/telegram/webhook", json=_load_fixture("audio_message.json"))

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["outcome"] == "stored"
    mock_voice_note_service.create_voice_note_idempotent.assert_awaited_once()


def test_webhook_returns_duplicate_on_repeated_message(
    client: TestClient,
    mock_voice_note_service: VoiceNoteService,
) -> None:
    mock_voice_note_service.create_voice_note_idempotent.side_effect = DuplicateRecordError(
        "duplicate"
    )

    response = client.post("/api/telegram/webhook", json=_load_fixture("voice_message.json"))

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["outcome"] == "duplicate"
    mock_voice_note_service.create_voice_note_idempotent.assert_awaited_once_with(
        message_id=11,
        audio_file_id="AwACAgEAAxkBAAMLadb0gz7ExnTG0QfyXx4r30tC_XoAAssGAAJ-1rhGXFdggTuGGfc7BA",
        duration_seconds=8,
        raw_text="",
        clean_text=None,
    )


def test_webhook_ignores_unsupported_message(
    client: TestClient,
    mock_voice_note_service: VoiceNoteService,
) -> None:
    response = client.post(
        "/api/telegram/webhook", json=_load_fixture("unsupported_message.json")
    )

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["outcome"] == "ignored"
    mock_voice_note_service.create_voice_note_idempotent.assert_not_called()


def test_webhook_returns_500_on_repository_error(
    client: TestClient,
    mock_voice_note_service: VoiceNoteService,
) -> None:
    mock_voice_note_service.create_voice_note_idempotent.side_effect = RepositoryError(
        "db error"
    )

    response = client.post("/api/telegram/webhook", json=_load_fixture("voice_message.json"))

    assert response.status_code == 500
