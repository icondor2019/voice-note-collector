"""Tests for the /sources inline keyboard feature."""

from unittest.mock import AsyncMock, Mock

import pytest

from backend.services.chat_mode_service import ChatModeService
from backend.services.source_service import SourceService
from backend.services.telegram_bot_client import TelegramBotClient
from backend.services.telegram_command_handler import (
    SOURCES_EMPTY,
    SOURCES_HEADER,
    SOURCES_PAGE_SIZE,
    TelegramCommandHandler,
)
from backend.services.telegram_ingestion_service import TelegramIngestionService
from backend.services.telegram_message_handler import TelegramMessageHandler
from backend.services.transcription_service import TranscriptionService
from backend.services.voice_note_service import VoiceNoteService
from configuration.settings import settings


# ── Helpers ────────────────────────────────────────────────────────────────────


def _make_command_handler(source_service=None, bot_client=None):
    if source_service is None:
        source_service = AsyncMock(spec=SourceService)
    if bot_client is None:
        bot_client = AsyncMock(spec=TelegramBotClient)
    labels_repository = AsyncMock()
    return TelegramCommandHandler(
        source_service=source_service,
        bot_client=bot_client,
        labels_repository=labels_repository,
        chat_mode_service=ChatModeService(),
        reflection_service=AsyncMock(),
    )


def _make_message_handler(
    command_handler=None,
    bot_client=None,
    source_service=None,
):
    if command_handler is None:
        command_handler = AsyncMock()
    if bot_client is None:
        bot_client = AsyncMock()
    if source_service is None:
        source_service = AsyncMock(spec=SourceService)
    ingestion_service = Mock(spec=TelegramIngestionService)
    ingestion_service._build_ingestion_event = Mock(return_value={})
    voice_note_service = AsyncMock(spec=VoiceNoteService)
    transcription_service = AsyncMock(spec=TranscriptionService)
    return TelegramMessageHandler(
        ingestion_service=ingestion_service,
        voice_note_service=voice_note_service,
        transcription_service=transcription_service,
        command_handler=command_handler,
        bot_client=bot_client,
        chat_mode_service=ChatModeService(),
        multi_agent_service=AsyncMock(),
        reflection_service=AsyncMock(),
        source_service=source_service,
    )


def _make_sources(n: int, *, active_index: int = 0) -> list[dict]:
    """Build a deterministic list of n source dicts (created_at DESC order)."""
    sources = []
    for i in range(n):
        sources.append(
            {
                "id": f"id-{i}",
                "source_name": f"source-{i}",
                "status": "active" if i == active_index else "deactivated",
            }
        )
    return sources


def _build_callback_update(callback_data: str, *, user_id=None) -> dict:
    return {
        "callback_query": {
            "id": "cq-1",
            "from": {"id": user_id if user_id is not None else settings.TELEGRAM_ALLOWED_USER_ID},
            "data": callback_data,
            "message": {"chat": {"id": 123}, "message_id": 456},
        }
    }


# ── 5.5 Keyboard building tests ───────────────────────────────────────────────


def test_build_sources_keyboard_active_source_has_checkmark() -> None:
    handler = _make_command_handler()
    sources = _make_sources(1, active_index=0)
    keyboard = handler.build_sources_keyboard(sources, page=0)
    assert keyboard["inline_keyboard"][0][0]["text"] == "✅ source-0"
    assert keyboard["inline_keyboard"][0][0]["callback_data"] == "src:id-0"


def test_build_sources_keyboard_inactive_source_no_prefix() -> None:
    handler = _make_command_handler()
    sources = _make_sources(1, active_index=-1)  # none active
    keyboard = handler.build_sources_keyboard(sources, page=0)
    assert keyboard["inline_keyboard"][0][0]["text"] == "source-0"
    assert keyboard["inline_keyboard"][0][0]["callback_data"] == "src:id-0"


def test_build_sources_keyboard_pagination_six_per_page() -> None:
    handler = _make_command_handler()
    sources = _make_sources(7)
    keyboard = handler.build_sources_keyboard(sources, page=0)
    rows = keyboard["inline_keyboard"]
    # 6 source rows + 1 pagination row
    assert len(rows) == SOURCES_PAGE_SIZE + 1
    # Last row is the pagination row (only ▶️ on page 0)
    assert rows[-1][0]["text"] == "▶️"
    assert rows[-1][0]["callback_data"] == "src_page:1"


def test_build_sources_keyboard_no_pagination_when_six_or_fewer() -> None:
    handler = _make_command_handler()
    sources = _make_sources(6)
    keyboard = handler.build_sources_keyboard(sources, page=0)
    rows = keyboard["inline_keyboard"]
    # 6 source rows, no pagination row
    assert len(rows) == 6
    # No ◀️ or ▶️ anywhere
    for row in rows:
        for btn in row:
            assert "◀" not in btn["text"]
            assert "▶" not in btn["text"]


def test_build_sources_keyboard_page_zero_no_left_arrow() -> None:
    handler = _make_command_handler()
    sources = _make_sources(7)
    keyboard = handler.build_sources_keyboard(sources, page=0)
    pagination_row = keyboard["inline_keyboard"][-1]
    assert len(pagination_row) == 1
    assert "◀" not in pagination_row[0]["text"]


def test_build_sources_keyboard_last_page_no_right_arrow() -> None:
    handler = _make_command_handler()
    sources = _make_sources(7)
    keyboard = handler.build_sources_keyboard(sources, page=1)
    pagination_row = keyboard["inline_keyboard"][-1]
    assert len(pagination_row) == 1
    assert "▶" not in pagination_row[0]["text"]
    assert pagination_row[0]["text"] == "◀️"
    assert pagination_row[0]["callback_data"] == "src_page:0"


def test_build_sources_keyboard_callback_data_format() -> None:
    handler = _make_command_handler()
    sources = _make_sources(7)
    keyboard = handler.build_sources_keyboard(sources, page=0)
    # Source buttons use src:{id}
    for row in keyboard["inline_keyboard"][:SOURCES_PAGE_SIZE]:
        assert row[0]["callback_data"].startswith("src:")
        assert not row[0]["callback_data"].startswith("src_page:")
    # Nav buttons use src_page:{n}
    nav_row = keyboard["inline_keyboard"][-1]
    assert nav_row[0]["callback_data"].startswith("src_page:")


def test_build_sources_keyboard_empty_sources() -> None:
    handler = _make_command_handler()
    keyboard = handler.build_sources_keyboard([], page=0)
    # total_pages=1, no source rows, no nav row
    assert keyboard["inline_keyboard"] == []


# ── 5.5 Callback query handling tests ──────────────────────────────────────────


@pytest.mark.anyio
async def test_callback_query_unauthorized_user_answered_with_alert() -> None:
    handler = _make_message_handler()
    update = _build_callback_update("src:id-0", user_id=999999)

    result = await handler.handle(update)

    handler._bot_client.answer_callback_query.assert_awaited_once()
    call = handler._bot_client.answer_callback_query.call_args
    assert call.kwargs.get("show_alert") is True
    assert result == {"outcome": "ignored", "reason": "unauthorized_callback"}


@pytest.mark.anyio
async def test_callback_query_src_activates_source() -> None:
    source_service = AsyncMock(spec=SourceService)
    source_service.activate_source_by_id = AsyncMock(
        return_value={"id": "id-0", "source_name": "source-0", "status": "active"}
    )
    source_service.list_sources = AsyncMock(return_value=_make_sources(2, active_index=0))
    cmd_handler = _make_command_handler(source_service=source_service)
    handler = _make_message_handler(command_handler=cmd_handler, source_service=source_service)
    update = _build_callback_update("src:id-0")

    result = await handler.handle(update)

    source_service.activate_source_by_id.assert_awaited_once_with("id-0")
    handler._bot_client.edit_message_text.assert_awaited_once()
    handler._bot_client.answer_callback_query.assert_awaited_once()
    assert result == {"outcome": "source_switched", "source_id": "id-0"}


@pytest.mark.anyio
async def test_callback_query_src_edits_message_with_updated_keyboard() -> None:
    source_service = AsyncMock(spec=SourceService)
    source_service.activate_source_by_id = AsyncMock(
        return_value={"id": "id-0", "source_name": "source-0", "status": "active"}
    )
    source_service.list_sources = AsyncMock(return_value=_make_sources(2, active_index=0))
    cmd_handler = _make_command_handler(source_service=source_service)
    handler = _make_message_handler(command_handler=cmd_handler, source_service=source_service)
    update = _build_callback_update("src:id-0")

    await handler.handle(update)

    # edit_message_text was called with the header text and a fresh keyboard
    handler._bot_client.edit_message_text.assert_awaited_once()
    call_args = handler._bot_client.edit_message_text.call_args
    # Positional: (chat_id, message_id, text, reply_markup)
    assert call_args[0][0] == 123
    assert call_args[0][1] == 456
    assert SOURCES_HEADER in call_args[0][2]
    assert "inline_keyboard" in call_args[0][3]


@pytest.mark.anyio
async def test_callback_query_src_stale_source_shows_alert() -> None:
    source_service = AsyncMock(spec=SourceService)
    source_service.activate_source_by_id = AsyncMock(return_value=None)  # stale
    handler = _make_message_handler(source_service=source_service)
    update = _build_callback_update("src:does-not-exist")

    result = await handler.handle(update)

    handler._bot_client.answer_callback_query.assert_awaited_once()
    call = handler._bot_client.answer_callback_query.call_args
    assert call.kwargs.get("show_alert") is True
    assert "use /sources to refresh" in (call.kwargs.get("text") or "")
    handler._bot_client.edit_message_text.assert_not_awaited()
    assert result == {"outcome": "error", "reason": "stale_source"}


@pytest.mark.anyio
async def test_callback_query_src_already_active_handles_gracefully() -> None:
    source_service = AsyncMock(spec=SourceService)
    # Source is already active — activate_source_by_id still returns the source
    source_service.activate_source_by_id = AsyncMock(
        return_value={"id": "id-0", "source_name": "source-0", "status": "active"}
    )
    source_service.list_sources = AsyncMock(return_value=_make_sources(2, active_index=0))
    cmd_handler = _make_command_handler(source_service=source_service)
    handler = _make_message_handler(command_handler=cmd_handler, source_service=source_service)
    update = _build_callback_update("src:id-0")

    result = await handler.handle(update)

    # Edit may be called (might be no-op on Telegram side, but we still call it)
    handler._bot_client.edit_message_text.assert_awaited_once()
    handler._bot_client.answer_callback_query.assert_awaited_once()
    assert result == {"outcome": "source_switched", "source_id": "id-0"}


@pytest.mark.anyio
async def test_callback_query_src_page_navigates_to_page() -> None:
    source_service = AsyncMock(spec=SourceService)
    source_service.list_sources = AsyncMock(return_value=_make_sources(7))
    cmd_handler = _make_command_handler(source_service=source_service)
    handler = _make_message_handler(command_handler=cmd_handler, source_service=source_service)
    update = _build_callback_update("src_page:1")

    result = await handler.handle(update)

    handler._bot_client.edit_message_text.assert_awaited_once()
    handler._bot_client.answer_callback_query.assert_awaited_once()
    assert result == {"outcome": "page_changed", "page": 1}


@pytest.mark.anyio
async def test_callback_query_unknown_data_ignored() -> None:
    handler = _make_message_handler()
    update = _build_callback_update("unknown:format")

    result = await handler.handle(update)

    handler._bot_client.answer_callback_query.assert_awaited_once()
    call = handler._bot_client.answer_callback_query.call_args
    # No text and no alert for unknown data
    assert call.kwargs.get("text") is None
    assert call.kwargs.get("show_alert", False) is False
    assert result == {"outcome": "ignored", "reason": "unknown_callback_data"}


@pytest.mark.anyio
async def test_callback_query_invalid_page_number_handled() -> None:
    handler = _make_message_handler()
    update = _build_callback_update("src_page:abc")

    result = await handler.handle(update)

    handler._bot_client.answer_callback_query.assert_awaited_once()
    assert result == {"outcome": "error", "reason": "invalid_page"}


# ── 5.5 Integration-style tests ────────────────────────────────────────────────


@pytest.mark.anyio
async def test_sources_command_sends_inline_keyboard() -> None:
    source_service = AsyncMock(spec=SourceService)
    source_service.list_sources = AsyncMock(return_value=_make_sources(2, active_index=0))
    bot_client = AsyncMock()
    handler = _make_command_handler(source_service=source_service, bot_client=bot_client)

    await handler.handle_text("/sources", chat_id=123)

    bot_client.send_message_with_inline_keyboard.assert_awaited_once()
    bot_client.send_message.assert_not_awaited()


@pytest.mark.anyio
async def test_sources_command_empty_sends_plain_text() -> None:
    source_service = AsyncMock(spec=SourceService)
    source_service.list_sources = AsyncMock(return_value=[])
    bot_client = AsyncMock()
    handler = _make_command_handler(source_service=source_service, bot_client=bot_client)

    await handler.handle_text("/sources", chat_id=123)

    bot_client.send_message.assert_awaited_once_with(123, SOURCES_EMPTY)
    bot_client.send_message_with_inline_keyboard.assert_not_awaited()


@pytest.mark.anyio
async def test_message_handler_routes_callback_query_to_handler() -> None:
    handler = _make_message_handler()
    update = _build_callback_update("src:id-0")

    # The callback path is taken (not ingestion event)
    await handler.handle(update)

    # Ingestion event was NOT consulted (the callback branch is parallel)
    handler._ingestion_service._build_ingestion_event.assert_not_called()


@pytest.mark.anyio
async def test_existing_message_handling_unaffected_by_callback_branch() -> None:
    """A regular text message update still goes through the message path."""
    source_service = AsyncMock(spec=SourceService)
    cmd_handler = AsyncMock()
    handler = _make_message_handler(command_handler=cmd_handler, source_service=source_service)
    # Override the ingestion mock to return a valid event with proper user_id
    handler._ingestion_service._build_ingestion_event = Mock(return_value={
        "from_user_id": settings.TELEGRAM_ALLOWED_USER_ID,
        "message_type": "text",
        "chat_id": 123,
    })
    update = {
        "message": {
            "chat": {"id": 123},
            "text": "/current",
            "from": {"id": settings.TELEGRAM_ALLOWED_USER_ID},
        }
    }

    result = await handler.handle(update)

    cmd_handler.handle_text.assert_awaited_once_with("/current", 123, settings.TELEGRAM_ALLOWED_USER_ID)
    assert result == {"outcome": "command", "message_type": "text"}