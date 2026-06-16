from unittest.mock import AsyncMock, Mock

import pytest

from backend.models.reflection import ReflectionSummary
from backend.services.chat_mode_service import (
    AGENT_MODE_ACTIVATED,
    NOTE_MODE_ACTIVATED,
    ChatModeService,
)
from backend.services.telegram_command_handler import HELP_MESSAGE, TelegramCommandHandler
from backend.services.telegram_message_handler import TelegramMessageHandler
from backend.services.telegram_ingestion_service import TelegramIngestionService
from backend.services.transcription_service import TranscriptionService
from backend.services.voice_note_service import VoiceNoteService
from backend.utils.slug import slugify, validate_slug_input
from configuration.settings import settings


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
    labels_repository = AsyncMock()
    handler = TelegramCommandHandler(
        source_service, bot_client, labels_repository, ChatModeService(), AsyncMock()
    )

    reply = await handler.handle_text("/create my new source", chat_id=123)

    assert "✅" in reply
    assert "my-new-source" in reply
    source_service.create_source_and_optionally_activate.assert_awaited_once()


@pytest.mark.anyio
async def test_create_already_exists() -> None:
    source_service = AsyncMock()
    source_service._repository.get_source_by_name = AsyncMock(return_value={"id": "1"})
    bot_client = AsyncMock()
    labels_repository = AsyncMock()
    handler = TelegramCommandHandler(
        source_service, bot_client, labels_repository, ChatModeService(), AsyncMock()
    )

    reply = await handler.handle_text("/create my new source", chat_id=123)

    assert "❌" in reply
    assert "already exists" in reply
    source_service.create_source_and_optionally_activate.assert_not_awaited()


@pytest.mark.anyio
async def test_create_invalid_name() -> None:
    source_service = AsyncMock()
    bot_client = AsyncMock()
    labels_repository = AsyncMock()
    handler = TelegramCommandHandler(
        source_service, bot_client, labels_repository, ChatModeService(), AsyncMock()
    )

    reply = await handler.handle_text("/create source", chat_id=123)

    assert "❌" in reply
    assert "2–4 words" in reply


@pytest.mark.anyio
async def test_switch_success() -> None:
    source_service = AsyncMock()
    source_service._repository.get_source_by_name = AsyncMock(return_value={"id": "1"})
    bot_client = AsyncMock()
    labels_repository = AsyncMock()
    handler = TelegramCommandHandler(
        source_service, bot_client, labels_repository, ChatModeService(), AsyncMock()
    )

    reply = await handler.handle_text("/switch my new source", chat_id=123)

    assert "✅" in reply
    source_service.activate_source_by_id.assert_awaited_once_with("1")


@pytest.mark.anyio
async def test_switch_not_found() -> None:
    source_service = AsyncMock()
    source_service._repository.get_source_by_name = AsyncMock(return_value=None)
    bot_client = AsyncMock()
    labels_repository = AsyncMock()
    handler = TelegramCommandHandler(
        source_service, bot_client, labels_repository, ChatModeService(), AsyncMock()
    )

    reply = await handler.handle_text("/switch my new source", chat_id=123)

    assert "❌" in reply
    assert "not found" in reply


@pytest.mark.anyio
async def test_switch_invalid_name() -> None:
    source_service = AsyncMock()
    bot_client = AsyncMock()
    labels_repository = AsyncMock()
    handler = TelegramCommandHandler(
        source_service, bot_client, labels_repository, ChatModeService(), AsyncMock()
    )

    reply = await handler.handle_text("/switch", chat_id=123)

    assert "❌" in reply


@pytest.mark.anyio
async def test_default_activates_default_source() -> None:
    source_service = AsyncMock()
    source_service._repository.get_source_by_name = AsyncMock(return_value={"id": "default"})
    bot_client = AsyncMock()
    labels_repository = AsyncMock()
    handler = TelegramCommandHandler(
        source_service, bot_client, labels_repository, ChatModeService(), AsyncMock()
    )

    reply = await handler.handle_text("/default", chat_id=123)

    assert "✅" in reply
    assert "default" in reply
    source_service.activate_source_by_id.assert_awaited_once_with("default")


@pytest.mark.anyio
async def test_current_returns_active_source_name() -> None:
    source_service = AsyncMock()
    source_service.get_active_source = AsyncMock(return_value={"source_name": "my-source"})
    bot_client = AsyncMock()
    labels_repository = AsyncMock()
    handler = TelegramCommandHandler(
        source_service, bot_client, labels_repository, ChatModeService(), AsyncMock()
    )

    reply = await handler.handle_text("/current", chat_id=123)

    assert "📍" in reply
    assert "my-source" in reply


@pytest.mark.anyio
async def test_current_no_active_source() -> None:
    source_service = AsyncMock()
    source_service.get_active_source = AsyncMock(return_value=None)
    bot_client = AsyncMock()
    labels_repository = AsyncMock()
    handler = TelegramCommandHandler(
        source_service, bot_client, labels_repository, ChatModeService(), AsyncMock()
    )

    reply = await handler.handle_text("/current", chat_id=123)

    assert "⚠️" in reply


@pytest.mark.anyio
async def test_sources_lists_all() -> None:
    source_service = AsyncMock()
    source_service.list_sources = AsyncMock(
        return_value=[
            {"id": "1", "source_name": "alpha", "status": "active"},
            {"id": "2", "source_name": "beta", "status": "deactivated"},
        ]
    )
    bot_client = AsyncMock()
    labels_repository = AsyncMock()
    handler = TelegramCommandHandler(
        source_service, bot_client, labels_repository, ChatModeService(), AsyncMock()
    )

    await handler.handle_text("/sources", chat_id=123)

    # Inline keyboard was sent (not plain text)
    bot_client.send_message_with_inline_keyboard.assert_awaited_once()
    call_args = bot_client.send_message_with_inline_keyboard.call_args
    chat_id_arg, text_arg, keyboard_arg = call_args[0]
    assert chat_id_arg == 123
    assert "📂" in text_arg
    inline_kb = keyboard_arg["inline_keyboard"]
    # Two source buttons (no pagination for 2 sources)
    assert len(inline_kb) == 2
    # Active source has ✅ prefix
    assert inline_kb[0][0]["text"] == "✅ alpha"
    assert inline_kb[0][0]["callback_data"] == "src:1"
    # Inactive source has no prefix
    assert inline_kb[1][0]["text"] == "beta"
    assert inline_kb[1][0]["callback_data"] == "src:2"
    # Plain text send_message was NOT called
    bot_client.send_message.assert_not_awaited()


@pytest.mark.anyio
async def test_sources_empty() -> None:
    source_service = AsyncMock()
    source_service.list_sources = AsyncMock(return_value=[])
    bot_client = AsyncMock()
    labels_repository = AsyncMock()
    handler = TelegramCommandHandler(
        source_service, bot_client, labels_repository, ChatModeService(), AsyncMock()
    )

    reply = await handler.handle_text("/sources", chat_id=123)

    assert "📂 No sources found" in reply


@pytest.mark.anyio
async def test_non_command_text() -> None:
    source_service = AsyncMock()
    bot_client = AsyncMock()
    labels_repository = AsyncMock()
    handler = TelegramCommandHandler(
        source_service, bot_client, labels_repository, ChatModeService(), AsyncMock()
    )

    reply = await handler.handle_text("hello there", chat_id=123)

    assert "🤖" in reply


@pytest.mark.anyio
async def test_agent_command_sets_mode_and_replies() -> None:
    source_service = AsyncMock()
    bot_client = AsyncMock()
    labels_repository = AsyncMock()
    chat_mode_service = Mock()
    handler = TelegramCommandHandler(
        source_service, bot_client, labels_repository, chat_mode_service, AsyncMock()
    )

    reply = await handler.handle_text("/agent", chat_id=123)

    chat_mode_service.set_mode.assert_called_once_with("agent")
    assert reply == AGENT_MODE_ACTIVATED
    bot_client.send_message.assert_awaited_once_with(123, reply)


@pytest.mark.anyio
async def test_note_command_sets_mode_and_replies() -> None:
    source_service = AsyncMock()
    bot_client = AsyncMock()
    labels_repository = AsyncMock()
    chat_mode_service = Mock()
    handler = TelegramCommandHandler(
        source_service, bot_client, labels_repository, chat_mode_service, AsyncMock()
    )

    reply = await handler.handle_text("/note", chat_id=123)

    chat_mode_service.set_mode.assert_called_once_with("note")
    assert reply == NOTE_MODE_ACTIVATED
    bot_client.send_message.assert_awaited_once_with(123, reply)


@pytest.mark.anyio
async def test_help_command_returns_message() -> None:
    source_service = AsyncMock()
    bot_client = AsyncMock()
    labels_repository = AsyncMock()
    reflection_service = AsyncMock()
    handler = TelegramCommandHandler(
        source_service, bot_client, labels_repository, ChatModeService(), reflection_service
    )

    reply = await handler.handle_text("/help", chat_id=123)

    assert reply == HELP_MESSAGE
    bot_client.send_message.assert_awaited_once_with(123, HELP_MESSAGE)


@pytest.mark.anyio
async def test_bot_client_called_with_correct_chat_id() -> None:
    source_service = AsyncMock()
    source_service.get_active_source = AsyncMock(return_value=None)
    bot_client = AsyncMock()
    labels_repository = AsyncMock()
    handler = TelegramCommandHandler(
        source_service, bot_client, labels_repository, ChatModeService(), AsyncMock()
    )

    reply = await handler.handle_text("/current", chat_id=456)

    bot_client.send_message.assert_awaited_once_with(456, reply)


@pytest.mark.anyio
async def test_message_handler_routes_text_to_command_handler() -> None:
    ingestion_service = Mock(spec=TelegramIngestionService)
    ingestion_service._build_ingestion_event = Mock(
        return_value={
            "message_type": "text",
            "chat_id": 123,
            "from_user_id": settings.TELEGRAM_ALLOWED_USER_ID,
        }
    )
    voice_note_service = AsyncMock(spec=VoiceNoteService)
    transcription_service = AsyncMock(spec=TranscriptionService)
    command_handler = AsyncMock()
    bot_client = AsyncMock()
    reflection_service = AsyncMock()
    handler = TelegramMessageHandler(
        ingestion_service=ingestion_service,
        voice_note_service=voice_note_service,
        transcription_service=transcription_service,
        command_handler=command_handler,
        bot_client=bot_client,
        chat_mode_service=ChatModeService(),
        multi_agent_service=AsyncMock(),
        reflection_service=reflection_service,
        source_service=AsyncMock(),
    )
    update = {
        "message": {
            "chat": {"id": 123},
            "text": "/current",
        }
    }

    result = await handler.handle(update)

    command_handler.handle_text.assert_awaited_once_with("/current", 123, 123)
    assert result == {"outcome": "command", "message_type": "text"}


@pytest.mark.anyio
async def test_message_handler_audio_path_unaffected() -> None:
    ingestion_service = Mock(spec=TelegramIngestionService)
    ingestion_service._build_ingestion_event = Mock(
        return_value={
            "message_type": "voice",
            "message_id": 1,
            "telegram_file_id": "file-id",
            "from_user_id": settings.TELEGRAM_ALLOWED_USER_ID,
        }
    )
    ingestion_service.ingest_update = AsyncMock(
        return_value={"outcome": "stored", "voice_note_id": "note-1", "source_name": None}
    )
    voice_note_service = AsyncMock(spec=VoiceNoteService)
    voice_note_service._repository = Mock()
    voice_note_service._repository.get_voice_note_by_message_id = AsyncMock(return_value=None)
    transcription_service = Mock(spec=TranscriptionService)
    transcription_service.transcribe_telegram_audio = Mock(return_value="text")
    command_handler = AsyncMock()
    bot_client = AsyncMock()
    reflection_service = AsyncMock()
    handler = TelegramMessageHandler(
        ingestion_service=ingestion_service,
        voice_note_service=voice_note_service,
        transcription_service=transcription_service,
        command_handler=command_handler,
        bot_client=bot_client,
        chat_mode_service=ChatModeService(),
        multi_agent_service=AsyncMock(),
        reflection_service=reflection_service,
        source_service=AsyncMock(),
    )

    result = await handler.handle({"message": {}})

    command_handler.handle_text.assert_not_called()
    assert result["message_type"] == "voice"


@pytest.mark.anyio
async def test_handle_reflect_stats_command_formatted_reply() -> None:
    """Verify /reflect stats returns formatted summary with source name and percentages."""
    source_service = AsyncMock()
    reflection_service = AsyncMock()
    bot_client = AsyncMock()
    labels_repository = AsyncMock()

    reflection_service.get_reflection_summary = AsyncMock(
        return_value=ReflectionSummary(
            source_name="my-source",
            total_notes=10,
            internalized=3,
            in_progress=4,
            pending=3,
        )
    )

    handler = TelegramCommandHandler(
        source_service, bot_client, labels_repository, ChatModeService(), reflection_service
    )

    reply = await handler.handle_text("/reflect stats", chat_id=123)

    assert "📊" in reply
    assert "my-source" in reply
    assert "Total notes: 10" in reply
    assert "Internalized: 3" in reply
    assert "In progress: 4" in reply
    assert "Pending: 3" in reply
    assert "30%" in reply  # 3/10 = 30%
    assert "40%" in reply  # 4/10 = 40%
    assert "30%" in reply  # 3/10 = 30%


@pytest.mark.anyio
async def test_handle_reflect_no_argument_starts_reflection() -> None:
    """Verify /reflect with no argument starts a reflection (no regression)."""
    from unittest.mock import Mock

    source_service = AsyncMock()
    reflection_service = AsyncMock()
    bot_client = AsyncMock()
    labels_repository = AsyncMock()

    # Mock start_reflection to return a question result
    question_result_mock = Mock()
    question_result_mock.question_text = "What did you learn?"
    reflection_service.start_reflection = AsyncMock(return_value=question_result_mock)

    handler = TelegramCommandHandler(
        source_service, bot_client, labels_repository, ChatModeService(), reflection_service
    )

    reply = await handler.handle_text("/reflect", chat_id=123)

    reflection_service.start_reflection.assert_awaited_once()
    assert "What did you learn?" in reply


@pytest.mark.anyio
async def test_handle_reflect_stats_no_active_source_message() -> None:
    """Assert error message returned when no active source."""
    from backend.services.reflection_service import NoActiveSourceError

    source_service = AsyncMock()
    reflection_service = AsyncMock()
    bot_client = AsyncMock()
    labels_repository = AsyncMock()

    reflection_service.get_reflection_summary = AsyncMock(
        side_effect=NoActiveSourceError("No active source")
    )

    handler = TelegramCommandHandler(
        source_service, bot_client, labels_repository, ChatModeService(), reflection_service
    )

    reply = await handler.handle_text("/reflect stats", chat_id=123)

    assert "⚠️" in reply
    assert "No active source" in reply


@pytest.mark.anyio
async def test_handle_reflect_stats_zero_notes_message() -> None:
    """Assert friendly message when no notes yet in active source."""
    source_service = AsyncMock()
    reflection_service = AsyncMock()
    bot_client = AsyncMock()
    labels_repository = AsyncMock()

    reflection_service.get_reflection_summary = AsyncMock(
        return_value=ReflectionSummary(
            source_name="my-source",
            total_notes=0,
            internalized=0,
            in_progress=0,
            pending=0,
        )
    )

    handler = TelegramCommandHandler(
        source_service, bot_client, labels_repository, ChatModeService(), reflection_service
    )

    reply = await handler.handle_text("/reflect stats", chat_id=123)

    assert "📊" in reply
    assert "No notes yet" in reply


@pytest.mark.anyio
async def test_help_message_includes_reflect_stats() -> None:
    """Assert HELP_MESSAGE includes /reflect stats entry."""
    assert "/reflect stats" in HELP_MESSAGE
    assert "show internalization progress" in HELP_MESSAGE
