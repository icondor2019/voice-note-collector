import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from backend.controllers.telegram_controller import get_message_handler
from backend.repositories.repository_errors import RepositoryError
from backend.services.telegram_audio_downloader import TelegramDownloadError
from backend.services.telegram_message_handler import TelegramMessageHandler
from backend.services.transcription_service import TranscriptionError
from main import app


def _load_fixture(name: str) -> dict:
    fixture_path = Path(__file__).parent / "fixtures" / "telegram" / name
    return json.loads(fixture_path.read_text(encoding="utf-8"))


@pytest.fixture
def mock_message_handler() -> TelegramMessageHandler:
    handler = AsyncMock(spec=TelegramMessageHandler)
    handler.handle = AsyncMock(return_value={"outcome": "stored", "message_type": "voice"})
    return handler


@pytest.fixture
def client(mock_message_handler: TelegramMessageHandler) -> TestClient:
    app.dependency_overrides[get_message_handler] = lambda: mock_message_handler
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_webhook_rejects_invalid_json_body(
    client: TestClient,
    mock_message_handler: TelegramMessageHandler,
) -> None:
    response = client.post(
        "/api/telegram/webhook",
        data="{this-is:not-valid-json}",
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid JSON payload"
    mock_message_handler.handle.assert_not_called()


def test_webhook_rejects_non_dict_json(
    client: TestClient,
    mock_message_handler: TelegramMessageHandler,
) -> None:
    response = client.post("/api/telegram/webhook", json=["not", "a", "dict"])

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid JSON payload"
    mock_message_handler.handle.assert_not_called()


def test_webhook_stores_voice_message(
    client: TestClient,
    mock_message_handler: TelegramMessageHandler,
) -> None:
    payload = _load_fixture("voice_message.json")
    response = client.post("/api/telegram/webhook", json=payload)

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["outcome"] == "stored"
    mock_message_handler.handle.assert_awaited_once_with(payload)


def test_webhook_stores_audio_message(
    client: TestClient,
    mock_message_handler: TelegramMessageHandler,
) -> None:
    payload = _load_fixture("audio_message.json")
    response = client.post("/api/telegram/webhook", json=payload)

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["outcome"] == "stored"
    mock_message_handler.handle.assert_awaited_once_with(payload)


def test_webhook_returns_duplicate_on_repeated_message(
    client: TestClient,
    mock_message_handler: TelegramMessageHandler,
) -> None:
    mock_message_handler.handle.return_value = {
        "outcome": "duplicate",
        "message_type": "voice",
    }

    response = client.post("/api/telegram/webhook", json=_load_fixture("voice_message.json"))

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["outcome"] == "duplicate"
    mock_message_handler.handle.assert_awaited_once()


def test_webhook_ignores_unsupported_message(
    client: TestClient,
    mock_message_handler: TelegramMessageHandler,
) -> None:
    mock_message_handler.handle.return_value = {
        "outcome": "ignored",
        "message_type": "unsupported",
    }
    response = client.post(
        "/api/telegram/webhook", json=_load_fixture("unsupported_message.json")
    )

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["outcome"] == "ignored"
    mock_message_handler.handle.assert_awaited_once()


def test_webhook_returns_500_on_repository_error(
    client: TestClient,
    mock_message_handler: TelegramMessageHandler,
) -> None:
    mock_message_handler.handle.side_effect = RepositoryError("db error")

    response = client.post("/api/telegram/webhook", json=_load_fixture("voice_message.json"))

    assert response.status_code == 500
    mock_message_handler.handle.assert_awaited_once()


def test_webhook_returns_500_on_transcription_error(
    client: TestClient,
    mock_message_handler: TelegramMessageHandler,
) -> None:
    mock_message_handler.handle.side_effect = TranscriptionError("groq failed")

    response = client.post("/api/telegram/webhook", json=_load_fixture("voice_message.json"))

    assert response.status_code == 500
    mock_message_handler.handle.assert_awaited_once()


def test_webhook_returns_500_on_download_error(
    client: TestClient,
    mock_message_handler: TelegramMessageHandler,
) -> None:
    mock_message_handler.handle.side_effect = TelegramDownloadError(
        file_id="x", message="timeout"
    )

    response = client.post("/api/telegram/webhook", json=_load_fixture("voice_message.json"))

    assert response.status_code == 500
    mock_message_handler.handle.assert_awaited_once()
