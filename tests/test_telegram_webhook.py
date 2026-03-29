import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.controllers.telegram_controller import get_event_store
from main import app


def _load_fixture(name: str) -> dict:
    fixture_path = Path(__file__).parent / "fixtures" / "telegram" / name
    return json.loads(fixture_path.read_text(encoding="utf-8"))


def _read_single_event(event_path: Path) -> dict:
    lines = event_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    return json.loads(lines[0])


@pytest.fixture
def event_store_override(tmp_path: Path):
    event_path = tmp_path / "events.jsonl"

    def override_event_store():
        return get_event_store(event_path)

    app.dependency_overrides[get_event_store] = override_event_store
    yield event_path
    app.dependency_overrides.clear()


def test_webhook_rejects_invalid_json_body(event_store_override: Path) -> None:
    client = TestClient(app)

    response = client.post(
        "/api/telegram/webhook",
        data="{this-is:not-valid-json}",
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid JSON payload"
    assert not event_store_override.exists()


def test_webhook_rejects_non_dict_json(event_store_override: Path) -> None:
    client = TestClient(app)

    response = client.post("/api/telegram/webhook", json=["not", "a", "dict"])

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid JSON payload"
    assert not event_store_override.exists()


def test_webhook_accepts_text_message(event_store_override: Path) -> None:
    client = TestClient(app)

    response = client.post("/api/telegram/webhook", json=_load_fixture("text_message.json"))

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["outcome"] == "stored"
    assert event_store_override.exists()
    event = _read_single_event(event_store_override)
    assert event.get("chat_id") == 2222
    assert event.get("message_id") == 42
    assert isinstance(event.get("text_preview"), str)


def test_webhook_accepts_voice_message(event_store_override: Path) -> None:
    client = TestClient(app)

    response = client.post("/api/telegram/webhook", json=_load_fixture("voice_message.json"))

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["outcome"] == "stored"
    assert event_store_override.exists()
    event = _read_single_event(event_store_override)
    assert event.get("chat_id") == 2222
    assert event.get("message_id") == 43
    assert isinstance(event.get("telegram_file_id"), str)


def test_webhook_accepts_audio_message(event_store_override: Path) -> None:
    client = TestClient(app)

    response = client.post("/api/telegram/webhook", json=_load_fixture("audio_message.json"))

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["outcome"] == "stored"
    assert event_store_override.exists()
    event = _read_single_event(event_store_override)
    assert event.get("chat_id") == 2222
    assert event.get("message_id") == 45
    assert isinstance(event.get("telegram_file_id"), str)


def test_webhook_ignores_unsupported_message(event_store_override: Path) -> None:
    client = TestClient(app)

    response = client.post(
        "/api/telegram/webhook", json=_load_fixture("unsupported_message.json")
    )

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["outcome"] == "ignored"
    assert not event_store_override.exists()


def test_webhook_dedupes_repeated_payload(event_store_override: Path) -> None:
    payload = _load_fixture("text_message.json")
    client = TestClient(app)

    response_one = client.post("/api/telegram/webhook", json=payload)
    response_two = client.post("/api/telegram/webhook", json=payload)

    assert response_one.status_code == 200
    assert response_two.status_code == 200
    assert response_one.json()["outcome"] == "stored"
    assert response_two.json()["outcome"] == "duplicate"
    assert event_store_override.exists()
    event = _read_single_event(event_store_override)
    assert event.get("chat_id") == 2222
    assert event.get("message_id") == 42
