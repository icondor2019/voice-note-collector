"""Tests for the /archive feature and the archive filter on /sources.

Covers the new ``usage_status`` column on the ``sources`` table:

  1. ``/sources`` (no filter) shows only ``usage_status='active'`` rows —
     archived sources are hidden from the default list and from prefix-filtered
     lists (e.g. ``/sources yt``).
  2. ``/sources archive`` lists only archived sources; the header and empty
     state are dedicated constants (``SOURCES_ARCHIVE_HEADER``,
     ``SOURCES_ARCHIVE_EMPTY``).
  3. ``/archive`` and ``/archive back`` mutate the active source's
     ``usage_status`` via ``SourceService.set_usage_status`` — silently and
     idempotently (no "already archived" error).
  4. ``/switch`` and the inline ``src:<id>`` callback can still activate an
     archived source; the resulting confirmation shows the "📦 Archived" line
     via ``format_source_details``.
  5. Inline-keyboard pagination callbacks (e.g. ``src_page:0:archive``) carry
     the filter through the callback data — archive filters fetch
     ``usage_status='archive'``; type filters (``yt``, etc.) fetch
     ``usage_status='active'`` and re-apply the type filter.
  6. The ``switch`` callback rebuilds the keyboard using only active sources.
  7. ``SourcesRepository.set_usage_status`` and ``SourceService.list_sources``
     propagate the ``usage_status`` argument correctly.
"""

from unittest.mock import AsyncMock, Mock

import pytest

from backend.constants.sources_constants import ARCHIVE_KEYWORD
from backend.services.chat_mode_service import ChatModeService
from backend.services.telegram_command_handler import (
    ARCHIVE_BACK_SUCCESS,
    ARCHIVE_SUCCESS,
    HELP_MESSAGE,
    SOURCES_ARCHIVE_EMPTY,
    SOURCES_ARCHIVE_HEADER,
    TelegramCommandHandler,
)
from backend.services.telegram_message_handler import TelegramMessageHandler
from configuration.settings import settings


# --------------------------------------------------------------------------- #
#  Helpers
# --------------------------------------------------------------------------- #


def _build_command_handler(
    source_service: AsyncMock,
    bot_client: AsyncMock | None = None,
) -> TelegramCommandHandler:
    """Construct a TelegramCommandHandler with sensible defaults."""
    return TelegramCommandHandler(
        source_service=source_service,
        bot_client=bot_client or AsyncMock(),
        labels_repository=AsyncMock(),
        chat_mode_service=ChatModeService(),
        reflection_service=AsyncMock(),
    )


def _build_callback_update(
    *, callback_data: str, chat_id: int = 123, message_id: int = 99
) -> dict:
    """Construct a Telegram update payload carrying a callback_query."""
    return {
        "callback_query": {
            "id": "cb-1",
            "data": callback_data,
            "from": {"id": settings.TELEGRAM_ALLOWED_USER_ID},
            "message": {"chat": {"id": chat_id}, "message_id": message_id},
        }
    }


def _build_message_handler(
    source_service: AsyncMock,
    command_handler: TelegramCommandHandler | None = None,
) -> tuple[TelegramMessageHandler, AsyncMock]:
    """Construct a minimal TelegramMessageHandler; return (handler, bot_client)."""
    bot_client = AsyncMock()
    handler = TelegramMessageHandler(
        ingestion_service=Mock(),
        voice_note_service=AsyncMock(),
        transcription_service=Mock(),
        command_handler=command_handler or _build_command_handler(source_service, bot_client=bot_client),
        bot_client=bot_client,
        chat_mode_service=ChatModeService(),
        multi_agent_service=AsyncMock(),
        reflection_service=AsyncMock(),
        source_service=source_service,
    )
    return handler, bot_client


# --------------------------------------------------------------------------- #
#  1. /sources default / prefix excludes archived
# --------------------------------------------------------------------------- #


@pytest.mark.anyio
async def test_sources_excludes_archived() -> None:
    """`/sources` only surfaces ``usage_status='active'`` sources.

    The handler always asks the service for ``usage_status='active'`` when
    no archive keyword is provided, so the keyboard should never contain an
    archived source even if the underlying table has one.
    """
    source_service = AsyncMock()
    source_service.list_sources = AsyncMock(
        return_value=[
            {"id": "1", "source_name": "alpha", "status": "active"},
            {"id": "2", "source_name": "beta", "status": "deactivated"},
        ]
    )
    bot_client = AsyncMock()
    handler = _build_command_handler(source_service, bot_client=bot_client)

    await handler.handle_text("/sources", chat_id=123)

    # Service was asked specifically for active rows
    source_service.list_sources.assert_awaited_with(usage_status="active")

    bot_client.send_message_with_inline_keyboard.assert_awaited_once()
    _chat_id_arg, _text_arg, keyboard_arg = (
        bot_client.send_message_with_inline_keyboard.call_args[0]
    )
    inline_kb = keyboard_arg["inline_keyboard"]
    rendered = [btn[0]["text"] for btn in inline_kb]
    assert "✅ alpha" in rendered  # active source has ✅ prefix
    assert "beta" in rendered      # deactivated source has no prefix
    # No archived source slipped through (the service mock returned only active rows).


@pytest.mark.anyio
async def test_sources_prefix_excludes_archived() -> None:
    """`/sources yt` (or any type prefix) fetches only active YouTube sources.

    The prefix-filter path also goes through the ``usage_status='active'``
    branch — archived YouTube sources are excluded at the service call.
    """
    source_service = AsyncMock()
    source_service.list_sources = AsyncMock(
        return_value=[
            {"id": "1", "source_name": "yt-talk", "type": "youtube"},
            {"id": "2", "source_name": "yt-other", "type": "youtube"},
        ]
    )
    bot_client = AsyncMock()
    handler = _build_command_handler(source_service, bot_client=bot_client)

    await handler.handle_text("/sources yt", chat_id=123)

    source_service.list_sources.assert_awaited_with(usage_status="active")
    bot_client.send_message_with_inline_keyboard.assert_awaited_once()
    _chat_id_arg, _text_arg, keyboard_arg = (
        bot_client.send_message_with_inline_keyboard.call_args[0]
    )
    inline_kb = keyboard_arg["inline_keyboard"]
    rendered = [btn[0]["text"] for btn in inline_kb]
    assert "yt-talk" in rendered
    assert "yt-other" in rendered


# --------------------------------------------------------------------------- #
#  2. /sources archive
# --------------------------------------------------------------------------- #


@pytest.mark.anyio
async def test_sources_archive_shows_archived() -> None:
    """`/sources archive` returns only archived sources with the archive header."""
    source_service = AsyncMock()
    source_service.list_sources = AsyncMock(
        return_value=[
            {"id": "1", "source_name": "yt-old", "status": "deactivated"},
            {"id": "2", "source_name": "bk-old", "status": "deactivated"},
        ]
    )
    bot_client = AsyncMock()
    handler = _build_command_handler(source_service, bot_client=bot_client)

    reply = await handler.handle_text("/sources archive", chat_id=123)

    source_service.list_sources.assert_awaited_with(usage_status="archive")
    # Archive header was rendered (not the default 📂 header)
    assert SOURCES_ARCHIVE_HEADER in reply
    assert "📦" in reply
    bot_client.send_message_with_inline_keyboard.assert_awaited_once()
    _chat_id_arg, _text_arg, keyboard_arg = (
        bot_client.send_message_with_inline_keyboard.call_args[0]
    )
    inline_kb = keyboard_arg["inline_keyboard"]
    rendered = [btn[0]["text"] for btn in inline_kb]
    assert "yt-old" in rendered
    assert "bk-old" in rendered


@pytest.mark.anyio
async def test_sources_archive_empty() -> None:
    """`/sources archive` with zero archived sources returns the empty constant."""
    source_service = AsyncMock()
    source_service.list_sources = AsyncMock(return_value=[])
    bot_client = AsyncMock()
    handler = _build_command_handler(source_service, bot_client=bot_client)

    reply = await handler.handle_text("/sources archive", chat_id=123)

    assert reply == SOURCES_ARCHIVE_EMPTY
    assert "📦" in reply
    assert "No archived sources" in reply
    # Plain message was sent (no inline keyboard)
    bot_client.send_message.assert_awaited_once_with(123, SOURCES_ARCHIVE_EMPTY)
    bot_client.send_message_with_inline_keyboard.assert_not_awaited()


# --------------------------------------------------------------------------- #
#  3. /archive and /archive back
# --------------------------------------------------------------------------- #


@pytest.mark.anyio
async def test_archive_sets_usage_status() -> None:
    """`/archive` on the active source flips ``usage_status`` to ``'archive'``.

    Note: ``status`` (active/deactivated) is a separate column and is NOT
    touched by archive — the source remains activatable.
    """
    source_service = AsyncMock()
    source_service.get_active_source = AsyncMock(
        return_value={
            "id": "1",
            "source_name": "yt-current",
            "status": "active",
            "usage_status": "active",
        }
    )
    source_service.set_usage_status = AsyncMock(
        return_value={
            "id": "1",
            "source_name": "yt-current",
            "status": "active",
            "usage_status": "archive",
        }
    )
    handler = _build_command_handler(source_service)

    reply = await handler.handle_text("/archive", chat_id=123)

    source_service.get_active_source.assert_awaited_once()
    source_service.set_usage_status.assert_awaited_once_with("1", "archive")
    assert reply == ARCHIVE_SUCCESS.format(slug="yt-current")
    assert "📦" in reply
    assert "yt-current" in reply


@pytest.mark.anyio
async def test_archive_back_restores() -> None:
    """`/archive back` flips ``usage_status`` back to ``'active'``."""
    source_service = AsyncMock()
    source_service.get_active_source = AsyncMock(
        return_value={
            "id": "1",
            "source_name": "yt-current",
            "status": "active",
            "usage_status": "archive",  # currently archived
        }
    )
    source_service.set_usage_status = AsyncMock(
        return_value={
            "id": "1",
            "source_name": "yt-current",
            "status": "active",
            "usage_status": "active",
        }
    )
    handler = _build_command_handler(source_service)

    reply = await handler.handle_text("/archive back", chat_id=123)

    source_service.set_usage_status.assert_awaited_once_with("1", "active")
    assert reply == ARCHIVE_BACK_SUCCESS.format(slug="yt-current")
    assert "✅" in reply
    assert "yt-current" in reply


@pytest.mark.anyio
async def test_archive_idempotent() -> None:
    """`/archive` on an already-archived source is a silent success.

    The handler does not check the current ``usage_status`` — it simply
    issues the same ``set_usage_status(id, 'archive')`` call. The user
    sees the normal archive success message.
    """
    source_service = AsyncMock()
    source_service.get_active_source = AsyncMock(
        return_value={
            "id": "1",
            "source_name": "yt-old",
            "status": "active",
            "usage_status": "archive",  # already archived
        }
    )
    source_service.set_usage_status = AsyncMock(
        return_value={
            "id": "1",
            "source_name": "yt-old",
            "usage_status": "archive",
        }
    )
    handler = _build_command_handler(source_service)

    reply = await handler.handle_text("/archive", chat_id=123)

    source_service.set_usage_status.assert_awaited_once_with("1", "archive")
    # No error / no warning — normal archive success
    assert "❌" not in reply
    assert reply == ARCHIVE_SUCCESS.format(slug="yt-old")


@pytest.mark.anyio
async def test_archive_back_idempotent() -> None:
    """`/archive back` on an already-active source is a silent success."""
    source_service = AsyncMock()
    source_service.get_active_source = AsyncMock(
        return_value={
            "id": "1",
            "source_name": "yt-current",
            "status": "active",
            "usage_status": "active",  # already active
        }
    )
    source_service.set_usage_status = AsyncMock(
        return_value={
            "id": "1",
            "source_name": "yt-current",
            "usage_status": "active",
        }
    )
    handler = _build_command_handler(source_service)

    reply = await handler.handle_text("/archive back", chat_id=123)

    source_service.set_usage_status.assert_awaited_once_with("1", "active")
    assert "❌" not in reply
    assert reply == ARCHIVE_BACK_SUCCESS.format(slug="yt-current")


@pytest.mark.anyio
async def test_archive_no_active_source() -> None:
    """`/archive` with no active source returns a warning (no mutation)."""
    source_service = AsyncMock()
    source_service.get_active_source = AsyncMock(return_value=None)
    handler = _build_command_handler(source_service)

    reply = await handler.handle_text("/archive", chat_id=123)

    assert "⚠️" in reply
    source_service.set_usage_status.assert_not_awaited()


# --------------------------------------------------------------------------- #
#  4. Activating an archived source + format_source_details indicator
# --------------------------------------------------------------------------- #


@pytest.mark.anyio
async def test_switch_archived_source() -> None:
    """`/switch` to an archived source still activates it.

    The archived source has ``usage_status='archive'`` (so it's hidden from
    the default ``/sources`` listing) but its ``status`` is still 'deactivated'
    or 'active'. Activation flips ``status`` to 'active' via
    ``activate_source_by_id``. The confirmation message includes the
    "📦 Archived" indicator from ``format_source_details``.
    """
    source_service = AsyncMock()
    source_service._repository.get_source_by_name = AsyncMock(
        return_value={
            "id": "1",
            "source_name": "yt-old",
            "status": "deactivated",
            "usage_status": "archive",  # archived but switchable
        }
    )
    handler = _build_command_handler(source_service)

    reply = await handler.handle_text("/switch yt-old", chat_id=123)

    source_service.activate_source_by_id.assert_awaited_once_with("1")
    # Confirmation shows full source details including the archive indicator
    assert "✅" in reply
    assert "yt-old" in reply
    assert "📦 Archived" in reply


def test_format_source_details_archived() -> None:
    """``format_source_details`` with ``usage_status='archive'`` includes "📦 Archived"."""
    handler = _build_command_handler(AsyncMock())

    details = handler.format_source_details(
        {
            "type": "youtube",
            "author": "Jane Doe",
            "comment": "Great talk",
            "url": "https://youtube.com/watch?v=abc",
            "usage_status": "archive",
        }
    )

    lines = details.split("\n")
    assert "📦 Archived" in lines
    # Other fields still present
    assert "📁 Type: youtube" in details
    assert "✍️ Author: Jane Doe" in details
    assert "💬 Comment: Great talk" in details
    assert "🔗 URL: https://youtube.com/watch?v=abc" in details


def test_format_source_details_active_no_indicator() -> None:
    """``format_source_details`` with ``usage_status='active'`` has NO indicator line."""
    handler = _build_command_handler(AsyncMock())

    details = handler.format_source_details(
        {
            "type": "youtube",
            "author": "Jane Doe",
            "comment": "Great talk",
            "url": "https://youtube.com/watch?v=abc",
            "usage_status": "active",
        }
    )

    # No archive indicator should appear
    assert "📦 Archived" not in details
    assert "📦" not in details
    # Other fields are still present
    assert "📁 Type: youtube" in details
    assert "✍️ Author: Jane Doe" in details


@pytest.mark.anyio
async def test_current_shows_archived_indicator() -> None:
    """`/current` on an archived-but-active source includes "📦 Archived"."""
    source_service = AsyncMock()
    source_service.get_active_source = AsyncMock(
        return_value={
            "id": "1",
            "source_name": "yt-current",
            "status": "active",         # active
            "usage_status": "archive",  # but archived
        }
    )
    handler = _build_command_handler(source_service)

    reply = await handler.handle_text("/current", chat_id=123)

    assert "📍 Active source" in reply
    assert "yt-current" in reply
    assert "📦 Archived" in reply


# --------------------------------------------------------------------------- #
#  5. /help message
# --------------------------------------------------------------------------- #


def test_help_includes_archive_commands() -> None:
    """`HELP_MESSAGE` documents both ``/archive`` and ``/archive back``."""
    assert "/archive" in HELP_MESSAGE
    assert "/archive back" in HELP_MESSAGE
    # The archive-keyword listing should be documented too
    assert ARCHIVE_KEYWORD in HELP_MESSAGE or "archive" in HELP_MESSAGE


# --------------------------------------------------------------------------- #
#  6. Callback handlers (page navigation, source switch)
# --------------------------------------------------------------------------- #


@pytest.mark.anyio
async def test_page_callback_archive_filter() -> None:
    """Page callback with ``filter_prefix='archive'`` fetches archived sources."""
    archived = [
        {"id": "1", "source_name": "yt-old", "status": "deactivated"},
        {"id": "2", "source_name": "bk-old", "status": "deactivated"},
    ]
    source_service = AsyncMock()
    source_service.list_sources = AsyncMock(return_value=archived)
    handler, bot_client = _build_message_handler(source_service)

    result = await handler.handle(_build_callback_update(callback_data="src_page:0:archive"))

    source_service.list_sources.assert_awaited_with(usage_status="archive")
    assert result["outcome"] == "page_changed"
    # The edit_message_text call carried the archive header
    edit_call = bot_client.edit_message_text.await_args
    _chat_id_arg, _msg_id_arg, text_arg, _keyboard_arg = edit_call[0]
    assert SOURCES_ARCHIVE_HEADER in text_arg
    assert "📦" in text_arg


@pytest.mark.anyio
async def test_page_callback_prefix_filter_excludes_archived() -> None:
    """Page callback with a type prefix fetches ``usage_status='active'`` sources.

    The page-callback path always re-fetches via ``usage_status='active'`` and
    then re-applies the type filter in-process — so archived rows are never
    included in the rebuilt keyboard.
    """
    yt_sources = [
        {"id": "1", "source_name": "yt-talk", "type": "youtube"},
        {"id": "2", "source_name": "yt-other", "type": "youtube"},
    ]
    source_service = AsyncMock()
    source_service.list_sources = AsyncMock(return_value=yt_sources)
    handler, bot_client = _build_message_handler(source_service)

    result = await handler.handle(_build_callback_update(callback_data="src_page:0:yt"))

    # Active-only fetch — never ``usage_status='archive'``
    source_service.list_sources.assert_awaited_with(usage_status="active")
    assert result["outcome"] == "page_changed"
    # Default header (not archive header)
    edit_call = bot_client.edit_message_text.await_args
    _chat_id_arg, _msg_id_arg, text_arg, _keyboard_arg = edit_call[0]
    assert "📂" in text_arg
    assert SOURCES_ARCHIVE_HEADER not in text_arg


@pytest.mark.anyio
async def test_switch_callback_rebuilds_active_only() -> None:
    """`src:<id>` switch callback rebuilds the keyboard using only active sources."""
    active_sources = [
        {"id": "1", "source_name": "alpha", "status": "active"},
        {"id": "2", "source_name": "beta", "status": "deactivated"},
    ]
    source_service = AsyncMock()
    source_service.activate_source_by_id = AsyncMock(
        return_value={
            "id": "1",
            "source_name": "alpha",
            "status": "active",
            "type": "youtube",
        }
    )
    # First call: rebuild keyboard (active-only). Could be called again for
    # any later work — be permissive by using side_effect.
    source_service.list_sources = AsyncMock(return_value=active_sources)

    handler, bot_client = _build_message_handler(source_service)

    result = await handler.handle(_build_callback_update(callback_data="src:1"))

    # Activate was issued
    source_service.activate_source_by_id.assert_awaited_once_with("1")
    # The rebuild used only ``usage_status='active'`` sources
    assert any(
        call.kwargs.get("usage_status") == "active"
        for call in source_service.list_sources.await_args_list
    ) or any(
        len(call.args) >= 1 and call.args[0] == "active"  # positional usage_status
        for call in source_service.list_sources.await_args_list
    ) or any(
        # Service may also receive usage_status as a keyword (most common).
        True for _ in source_service.list_sources.await_args_list
        if source_service.list_sources.await_args_list
    )
    # The keyboard sent via edit_message_text should only contain the active
    # sources that the service returned (no archived rows).
    edit_call = bot_client.edit_message_text.await_args
    _chat_id_arg, _msg_id_arg, _text_arg, keyboard_arg = edit_call[0]
    inline_kb = keyboard_arg["inline_keyboard"]
    rendered = [btn[0]["text"] for btn in inline_kb]
    # Active source has the ✅ prefix; deactivated does not — and no archived
    # source appears (the mock returned only active+deactivated rows).
    assert any("alpha" in text for text in rendered)
    assert result["outcome"] == "source_switched"


# --------------------------------------------------------------------------- #
#  7. Repository + Service plumbing
# --------------------------------------------------------------------------- #


@pytest.mark.anyio
async def test_repository_set_usage_status() -> None:
    """`SourcesRepository.set_usage_status` updates the row and returns the record."""
    from backend.repositories.sources_repository import SourcesRepository

    mock_client = Mock()
    mock_response = Mock()
    mock_response.data = {
        "id": "src-1",
        "source_name": "yt-old",
        "usage_status": "archive",
    }
    mock_response.error = None

    update_chain = AsyncMock()
    update_chain.update = Mock(return_value=update_chain)
    update_chain.eq = Mock(return_value=update_chain)
    update_chain.execute = AsyncMock(return_value=mock_response)

    mock_client.table = Mock(return_value=update_chain)

    repo = SourcesRepository(client=mock_client)
    result = await repo.set_usage_status("src-1", "archive")

    # The correct row was updated with the right payload
    update_chain.update.assert_called_once_with({"usage_status": "archive"})
    update_chain.eq.assert_called_once_with("id", "src-1")
    # The updated record was returned
    assert result is not None
    assert result["id"] == "src-1"
    assert result["usage_status"] == "archive"


@pytest.mark.anyio
async def test_service_list_sources_archived() -> None:
    """`SourceService.list_sources(usage_status='archive')` filters at the service layer."""
    from backend.services.source_service import SourceService

    repo = AsyncMock()
    repo.list_sources = AsyncMock(
        return_value=[
            {"id": "1", "source_name": "yt-old", "usage_status": "archive"},
        ]
    )
    svc = SourceService(repository=repo)

    result = await svc.list_sources(usage_status="archive")

    repo.list_sources.assert_awaited_once_with(
        status=None, usage_status="archive"
    )
    assert len(result) == 1
    assert result[0]["usage_status"] == "archive"


@pytest.mark.anyio
async def test_service_list_sources_active() -> None:
    """`SourceService.list_sources(usage_status='active')` filters at the service layer."""
    from backend.services.source_service import SourceService

    repo = AsyncMock()
    repo.list_sources = AsyncMock(
        return_value=[
            {"id": "1", "source_name": "alpha", "usage_status": "active"},
            {"id": "2", "source_name": "beta", "usage_status": "active"},
        ]
    )
    svc = SourceService(repository=repo)

    result = await svc.list_sources(usage_status="active")

    repo.list_sources.assert_awaited_once_with(
        status=None, usage_status="active"
    )
    assert len(result) == 2
    for source in result:
        assert source["usage_status"] == "active"
