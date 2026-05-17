from unittest.mock import AsyncMock, Mock

import pytest

from backend.services.chat_mode_service import ChatModeService
from backend.services.telegram_ingestion_service import TelegramIngestionService
from backend.services.telegram_message_handler import (
    AGENT_MOCK_RESPONSE,
    TelegramMessageHandler,
)
from backend.services.transcription_service import TranscriptionService
from backend.services.voice_note_service import VoiceNoteService
from configuration.settings import settings


ERROR_MESSAGE = "❌ Failed to process your voice note. Please try again."


def _build_event(
    *,
    chat_id: int | None = 123,
    from_user_id: int | None = None,
    message_id: int = 10,
    telegram_file_id: str = "file-id",
    message_type: str = "voice",
) -> dict:
    return {
        "message_type": message_type,
        "chat_id": chat_id,
        "from_user_id": settings.TELEGRAM_ALLOWED_USER_ID
        if from_user_id is None
        else from_user_id,
        "message_id": message_id,
        "telegram_file_id": telegram_file_id,
    }


def _build_handler(
    event: dict,
    *,
    raw_text: str = "hello",
    ingest_result: dict | None = None,
    existing_voice_note: dict | None = None,
    transcription_error: Exception | None = None,
    ingestion_error: Exception | None = None,
    bot_client_error: Exception | None = None,
    chat_mode_service: ChatModeService | None = None,
) -> tuple[
    TelegramMessageHandler,
    Mock,
    AsyncMock,
    Mock,
    AsyncMock,
]:
    ingestion_service = Mock(spec=TelegramIngestionService)
    ingestion_service._build_ingestion_event = Mock(return_value=event)
    if ingestion_error is None:
        ingestion_service.ingest_update = AsyncMock(
            return_value=ingest_result
            or {
                "outcome": "stored",
                "message_type": event["message_type"],
                "voice_note_id": "note-123",
                "source_name": "my-source",
            }
        )
    else:
        ingestion_service.ingest_update = AsyncMock(side_effect=ingestion_error)

    voice_note_service = AsyncMock(spec=VoiceNoteService)
    voice_note_service._repository = Mock()
    voice_note_service._repository.get_voice_note_by_message_id = AsyncMock(
        return_value=existing_voice_note
    )

    transcription_service = Mock(spec=TranscriptionService)
    if transcription_error is None:
        transcription_service.transcribe_telegram_audio = Mock(return_value=raw_text)
    else:
        transcription_service.transcribe_telegram_audio = Mock(side_effect=transcription_error)

    command_handler = AsyncMock()
    bot_client = AsyncMock()
    if bot_client_error is not None:
        bot_client.send_message = AsyncMock(side_effect=bot_client_error)

    handler = TelegramMessageHandler(
        ingestion_service=ingestion_service,
        voice_note_service=voice_note_service,
        transcription_service=transcription_service,
        command_handler=command_handler,
        bot_client=bot_client,
        chat_mode_service=chat_mode_service or ChatModeService(),
    )
    return handler, ingestion_service, voice_note_service, transcription_service, bot_client


@pytest.mark.anyio
async def test_success_notification_includes_preview() -> None:
    event = _build_event(chat_id=321)
    raw_text = "Short preview"
    handler, _, _, _, bot_client = _build_handler(event, raw_text=raw_text)

    result = await handler.handle({})

    expected_message = f"✅ Note saved!\n📂 Source: my-source\n📝 {raw_text}"
    bot_client.send_message.assert_awaited_once_with(321, expected_message)
    assert result == {"outcome": "stored", "message_type": "voice"}


@pytest.mark.anyio
async def test_success_notification_truncates_preview_to_100_chars() -> None:
    raw_text = "x" * 120
    event = _build_event()
    handler, _, _, _, bot_client = _build_handler(event, raw_text=raw_text)

    await handler.handle({})

    expected_preview = raw_text[:100]
    expected_message = f"✅ Note saved!\n📂 Source: my-source\n📝 {expected_preview}..."
    bot_client.send_message.assert_awaited_once_with(123, expected_message)


@pytest.mark.anyio
async def test_success_notification_without_source_name() -> None:
    event = _build_event(chat_id=456)
    raw_text = "No source"
    ingest_result = {
        "outcome": "stored",
        "message_type": event["message_type"],
        "voice_note_id": "note-999",
        "source_name": None,
    }
    handler, _, _, _, bot_client = _build_handler(
        event, raw_text=raw_text, ingest_result=ingest_result
    )

    await handler.handle({})

    expected_message = f"✅ Note saved!\n📝 {raw_text}"
    bot_client.send_message.assert_awaited_once_with(456, expected_message)


@pytest.mark.anyio
async def test_transcription_error_sends_notification_and_raises() -> None:
    event = _build_event()
    handler, _, _, _, bot_client = _build_handler(
        event, transcription_error=RuntimeError("boom")
    )

    with pytest.raises(RuntimeError):
        await handler.handle({})

    bot_client.send_message.assert_awaited_once_with(123, ERROR_MESSAGE)


@pytest.mark.anyio
async def test_ingestion_error_sends_notification_and_raises() -> None:
    event = _build_event()
    handler, _, _, _, bot_client = _build_handler(
        event, ingestion_error=RuntimeError("db down")
    )

    with pytest.raises(RuntimeError):
        await handler.handle({})

    bot_client.send_message.assert_awaited_once_with(123, ERROR_MESSAGE)


@pytest.mark.anyio
async def test_notifications_disabled_skip_success_send(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "TELEGRAM_NOTIFY_ON_TRANSCRIPTION", False)
    event = _build_event()
    handler, _, _, _, bot_client = _build_handler(event)

    await handler.handle({})

    bot_client.send_message.assert_not_awaited()


@pytest.mark.anyio
async def test_notifications_disabled_skip_error_send(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "TELEGRAM_NOTIFY_ON_TRANSCRIPTION", False)
    event = _build_event()
    handler, _, _, _, bot_client = _build_handler(
        event, transcription_error=RuntimeError("boom")
    )

    with pytest.raises(RuntimeError):
        await handler.handle({})

    bot_client.send_message.assert_not_awaited()


@pytest.mark.anyio
async def test_no_chat_id_skips_notification() -> None:
    event = _build_event(chat_id=None)
    handler, _, _, _, bot_client = _build_handler(event)

    result = await handler.handle({})

    bot_client.send_message.assert_not_awaited()
    assert result == {"outcome": "stored", "message_type": "voice"}


@pytest.mark.anyio
async def test_notification_failure_is_swallowed() -> None:
    event = _build_event()
    handler, _, _, _, bot_client = _build_handler(
        event, bot_client_error=RuntimeError("telegram down")
    )

    result = await handler.handle({})

    bot_client.send_message.assert_awaited_once()
    assert result == {"outcome": "stored", "message_type": "voice"}


@pytest.mark.anyio
async def test_duplicate_update_skips_notification() -> None:
    event = _build_event()
    handler, _, _, transcription_service, bot_client = _build_handler(
        event, existing_voice_note={"id": "existing"}
    )

    result = await handler.handle({})

    bot_client.send_message.assert_not_awaited()
    transcription_service.transcribe_telegram_audio.assert_not_called()
    assert result == {"outcome": "duplicate", "message_type": "voice"}


@pytest.mark.anyio
async def test_text_non_command_note_mode_ignored() -> None:
    event = _build_event(message_type="text")
    handler, _, _, _, bot_client = _build_handler(event)
    update = {"message": {"text": "hello", "chat": {"id": 123}}}

    result = await handler.handle(update)

    bot_client.send_message.assert_not_awaited()
    assert result == {"outcome": "ignored", "message_type": "text"}


@pytest.mark.anyio
async def test_text_non_command_agent_mode_replies() -> None:
    event = _build_event(message_type="text")
    chat_mode_service = ChatModeService()
    chat_mode_service.set_mode("agent")
    handler, _, _, _, bot_client = _build_handler(event, chat_mode_service=chat_mode_service)
    update = {"message": {"text": "hello", "chat": {"id": 123}}}

    result = await handler.handle(update)

    bot_client.send_message.assert_awaited_once_with(123, AGENT_MOCK_RESPONSE)
    assert result == {"outcome": "agent_response", "message_type": "text"}


@pytest.mark.anyio
async def test_text_command_in_agent_mode_routes_command_handler() -> None:
    event = _build_event(message_type="text")
    chat_mode_service = ChatModeService()
    chat_mode_service.set_mode("agent")
    handler, _, _, _, _ = _build_handler(event, chat_mode_service=chat_mode_service)
    update = {"message": {"text": "/sources", "chat": {"id": 123}}}

    result = await handler.handle(update)

    handler._command_handler.handle_text.assert_awaited_once_with("/sources", 123)
    assert result == {"outcome": "command", "message_type": "text"}


@pytest.mark.anyio
async def test_audio_agent_mode_transcribes_and_skips_storage() -> None:
    event = _build_event(message_type="voice")
    chat_mode_service = ChatModeService()
    chat_mode_service.set_mode("agent")
    handler, ingestion_service, voice_note_service, transcription_service, bot_client = (
        _build_handler(event, chat_mode_service=chat_mode_service)
    )

    result = await handler.handle({"message": {"chat": {"id": 123}}})

    transcription_service.transcribe_telegram_audio.assert_called_once_with("file-id")
    ingestion_service.ingest_update.assert_not_awaited()
    voice_note_service._repository.get_voice_note_by_message_id.assert_not_awaited()
    bot_client.send_message.assert_awaited_once_with(123, AGENT_MOCK_RESPONSE)
    assert result == {"outcome": "agent_response", "message_type": "voice"}
