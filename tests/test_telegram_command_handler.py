from unittest.mock import AsyncMock, Mock

import pytest

from backend.services.telegram_command_handler import TelegramCommandHandler
from backend.services.telegram_message_handler import TelegramMessageHandler
from backend.services.telegram_ingestion_service import TelegramIngestionService
from backend.services.transcription_service import TranscriptionService
from backend.services.voice_note_service import VoiceNoteService
from backend.utils.slug import slugify, validate_slug_input


@pytest.mark.parametrize(
    ("input_text", "expected"),
    [
        ("my New Source", "my-new-source"),
    ],
)
def test_slugify_basic(input_text: str, expected: str) -> None:
    assert slugify(input_text) == expected


def test_slugify_strips_special_chars() -> None:
    assert slugify("my-source!") == "my-source"


def test_validate_slug_input_hyphenated_counts_as_two_words() -> None:
    assert validate_slug_input("my-source") is True


def test_validate_slug_input_valid_two_words() -> None:
    assert validate_slug_input("my source") is True


def test_validate_slug_input_valid_four_words() -> None:
    assert validate_slug_input("a b c d") is True


def test_validate_slug_input_one_word_fails() -> None:
    assert validate_slug_input("source") is False


def test_validate_slug_input_five_words_fails() -> None:
    assert validate_slug_input("a b c d e") is False


@pytest.mark.anyio
async def test_create_success() -> None:
    source_service = AsyncMock()
    source_service._repository.get_source_by_name = AsyncMock(return_value=None)
    bot_client = AsyncMock()
    handler = TelegramCommandHandler(source_service, bot_client)

    reply = await handler.handle_text("/create my new source", chat_id=123)

    assert "✅" in reply
    assert "my-new-source" in reply
    source_service.create_source_and_optionally_activate.assert_awaited_once()


@pytest.mark.anyio
async def test_create_already_exists() -> None:
    source_service = AsyncMock()
    source_service._repository.get_source_by_name = AsyncMock(return_value={"id": "1"})
    bot_client = AsyncMock()
    handler = TelegramCommandHandler(source_service, bot_client)

    reply = await handler.handle_text("/create my new source", chat_id=123)

    assert "❌" in reply
    assert "already exists" in reply
    source_service.create_source_and_optionally_activate.assert_not_awaited()


@pytest.mark.anyio
async def test_create_invalid_name() -> None:
    source_service = AsyncMock()
    bot_client = AsyncMock()
    handler = TelegramCommandHandler(source_service, bot_client)

    reply = await handler.handle_text("/create source", chat_id=123)

    assert "❌" in reply
    assert "2–4 words" in reply


@pytest.mark.anyio
async def test_switch_success() -> None:
    source_service = AsyncMock()
    source_service._repository.get_source_by_name = AsyncMock(return_value={"id": "1"})
    bot_client = AsyncMock()
    handler = TelegramCommandHandler(source_service, bot_client)

    reply = await handler.handle_text("/switch my new source", chat_id=123)

    assert "✅" in reply
    source_service.activate_source_by_id.assert_awaited_once_with("1")


@pytest.mark.anyio
async def test_switch_not_found() -> None:
    source_service = AsyncMock()
    source_service._repository.get_source_by_name = AsyncMock(return_value=None)
    bot_client = AsyncMock()
    handler = TelegramCommandHandler(source_service, bot_client)

    reply = await handler.handle_text("/switch my new source", chat_id=123)

    assert "❌" in reply
    assert "not found" in reply


@pytest.mark.anyio
async def test_switch_invalid_name() -> None:
    source_service = AsyncMock()
    bot_client = AsyncMock()
    handler = TelegramCommandHandler(source_service, bot_client)

    reply = await handler.handle_text("/switch", chat_id=123)

    assert "❌" in reply


@pytest.mark.anyio
async def test_default_activates_default_source() -> None:
    source_service = AsyncMock()
    source_service._repository.get_source_by_name = AsyncMock(return_value={"id": "default"})
    bot_client = AsyncMock()
    handler = TelegramCommandHandler(source_service, bot_client)

    reply = await handler.handle_text("/default", chat_id=123)

    assert "✅" in reply
    assert "default" in reply
    source_service.activate_source_by_id.assert_awaited_once_with("default")


@pytest.mark.anyio
async def test_current_returns_active_source_name() -> None:
    source_service = AsyncMock()
    source_service.get_active_source = AsyncMock(return_value={"source_name": "my-source"})
    bot_client = AsyncMock()
    handler = TelegramCommandHandler(source_service, bot_client)

    reply = await handler.handle_text("/current", chat_id=123)

    assert "📍" in reply
    assert "my-source" in reply


@pytest.mark.anyio
async def test_current_no_active_source() -> None:
    source_service = AsyncMock()
    source_service.get_active_source = AsyncMock(return_value=None)
    bot_client = AsyncMock()
    handler = TelegramCommandHandler(source_service, bot_client)

    reply = await handler.handle_text("/current", chat_id=123)

    assert "⚠️" in reply


@pytest.mark.anyio
async def test_sources_lists_all() -> None:
    source_service = AsyncMock()
    source_service.list_sources = AsyncMock(
        return_value=[
            {"source_name": "alpha", "status": "active"},
            {"source_name": "beta", "status": "deactivated"},
        ]
    )
    bot_client = AsyncMock()
    handler = TelegramCommandHandler(source_service, bot_client)

    reply = await handler.handle_text("/sources", chat_id=123)

    assert "📂" in reply
    assert "alpha" in reply
    assert "beta" in reply
    assert "● alpha" in reply
    assert "○ beta" in reply


@pytest.mark.anyio
async def test_sources_empty() -> None:
    source_service = AsyncMock()
    source_service.list_sources = AsyncMock(return_value=[])
    bot_client = AsyncMock()
    handler = TelegramCommandHandler(source_service, bot_client)

    reply = await handler.handle_text("/sources", chat_id=123)

    assert "📂 No sources found" in reply


@pytest.mark.anyio
async def test_non_command_text() -> None:
    source_service = AsyncMock()
    bot_client = AsyncMock()
    handler = TelegramCommandHandler(source_service, bot_client)

    reply = await handler.handle_text("hello there", chat_id=123)

    assert "🤖" in reply


@pytest.mark.anyio
async def test_bot_client_called_with_correct_chat_id() -> None:
    source_service = AsyncMock()
    source_service.get_active_source = AsyncMock(return_value=None)
    bot_client = AsyncMock()
    handler = TelegramCommandHandler(source_service, bot_client)

    reply = await handler.handle_text("/current", chat_id=456)

    bot_client.send_message.assert_awaited_once_with(456, reply)


@pytest.mark.anyio
async def test_message_handler_routes_text_to_command_handler() -> None:
    ingestion_service = Mock(spec=TelegramIngestionService)
    ingestion_service._build_ingestion_event = Mock(return_value={"message_type": "text"})
    voice_note_service = AsyncMock(spec=VoiceNoteService)
    transcription_service = AsyncMock(spec=TranscriptionService)
    command_handler = AsyncMock()
    handler = TelegramMessageHandler(
        ingestion_service=ingestion_service,
        voice_note_service=voice_note_service,
        transcription_service=transcription_service,
        command_handler=command_handler,
    )
    update = {
        "message": {
            "chat": {"id": 123},
            "text": "/current",
        }
    }

    result = await handler.handle(update)

    command_handler.handle_text.assert_awaited_once_with("/current", 123)
    assert result == {"outcome": "command", "message_type": "text"}


@pytest.mark.anyio
async def test_message_handler_audio_path_unaffected() -> None:
    ingestion_service = Mock(spec=TelegramIngestionService)
    ingestion_service._build_ingestion_event = Mock(
        return_value={
            "message_type": "voice",
            "message_id": 1,
            "telegram_file_id": "file-id",
        }
    )
    voice_note_service = AsyncMock(spec=VoiceNoteService)
    voice_note_service._repository = Mock()
    voice_note_service._repository.get_voice_note_by_message_id = AsyncMock(return_value=None)
    transcription_service = Mock(spec=TranscriptionService)
    transcription_service.transcribe_telegram_audio = Mock(return_value="text")
    command_handler = AsyncMock()
    handler = TelegramMessageHandler(
        ingestion_service=ingestion_service,
        voice_note_service=voice_note_service,
        transcription_service=transcription_service,
        command_handler=command_handler,
    )

    result = await handler.handle({"message": {}})

    command_handler.handle_text.assert_not_called()
    assert result["message_type"] == "voice"
