"""Tests for source display formatting, prefix filtering, and command renaming.

Covers three features:
  1. Full source info display (type/author/comment/URL) across /current, /switch,
     /default, and inline-keyboard activation.
  2. Prefix filter on /sources (e.g. ``/sources yt``) and pagination preservation.
  3. Command rename ``/build`` (and ``/build st``) — the old ``/build_doc`` and
     ``/build_doc stats`` are now unknown.
"""

from unittest.mock import AsyncMock, Mock

import pytest

from backend.constants.sources_constants import (
    SOURCE_PREFIX_TO_TYPE,
    resolve_prefix_to_type,
)
from backend.services.chat_mode_service import ChatModeService
from backend.services.session_builder_service import SessionBuilderService
from backend.services.telegram_command_handler import (
    HELP_MESSAGE,
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
    session_builder: AsyncMock | None = None,
    reflection_service: AsyncMock | None = None,
) -> TelegramCommandHandler:
    """Construct a TelegramCommandHandler with sensible defaults."""
    return TelegramCommandHandler(
        source_service=source_service,
        bot_client=bot_client or AsyncMock(),
        labels_repository=AsyncMock(),
        chat_mode_service=ChatModeService(),
        reflection_service=reflection_service or AsyncMock(),
        session_builder_service=session_builder,
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


# --------------------------------------------------------------------------- #
#  Feature 1 — Full source info display
# --------------------------------------------------------------------------- #


def test_format_source_details_all_fields() -> None:
    """All four fields present → 4 lines in correct order (type, author, comment, URL)."""
    handler = _build_command_handler(AsyncMock())

    details = handler.format_source_details(
        {
            "type": "youtube",
            "author": "Jane Doe",
            "comment": "Great talk",
            "url": "https://youtube.com/watch?v=abc",
        }
    )

    lines = details.split("\n")
    assert len(lines) == 4
    assert lines[0] == "📁 Type: youtube"
    assert lines[1] == "✍️ Author: Jane Doe"
    assert lines[2] == "💬 Comment: Great talk"
    assert lines[3] == "🔗 URL: https://youtube.com/watch?v=abc"


def test_format_source_details_omits_empty_fields() -> None:
    """Only type and URL present → 2 lines, no author/comment lines."""
    handler = _build_command_handler(AsyncMock())

    details = handler.format_source_details(
        {
            "type": "youtube",
            "author": None,
            "comment": None,
            "url": "https://youtube.com/watch?v=abc",
        }
    )

    lines = details.split("\n")
    assert len(lines) == 2
    assert lines[0] == "📁 Type: youtube"
    assert lines[1] == "🔗 URL: https://youtube.com/watch?v=abc"
    assert "Author" not in details
    assert "Comment" not in details


def test_format_source_details_all_empty() -> None:
    """No type/author/comment/url → empty string."""
    handler = _build_command_handler(AsyncMock())

    details = handler.format_source_details(
        {"type": None, "author": None, "comment": None, "url": None}
    )

    assert details == ""


@pytest.mark.anyio
async def test_current_shows_full_info() -> None:
    """`/current` with fully-populated active source → reply includes type, author, comment, URL, mode."""
    source_service = AsyncMock()
    source_service.get_active_source = AsyncMock(
        return_value={
            "id": "1",
            "source_name": "yt-talk",
            "type": "youtube",
            "author": "Jane Doe",
            "comment": "Inspiring",
            "url": "https://youtube.com/watch?v=abc",
        }
    )
    handler = _build_command_handler(source_service)

    reply = await handler.handle_text("/current", chat_id=123)

    assert "📍 Active source" in reply
    assert "yt-talk" in reply
    assert "📁 Type: youtube" in reply
    assert "✍️ Author: Jane Doe" in reply
    assert "💬 Comment: Inspiring" in reply
    assert "🔗 URL: https://youtube.com/watch?v=abc" in reply
    assert "🤖 Mode:" in reply


@pytest.mark.anyio
async def test_current_minimal_source() -> None:
    """`/current` with source that has only a name → just name line and mode line."""
    source_service = AsyncMock()
    source_service.get_active_source = AsyncMock(
        return_value={
            "id": "1",
            "source_name": "my-source",
            # No type/author/comment/url
        }
    )
    handler = _build_command_handler(source_service)

    reply = await handler.handle_text("/current", chat_id=123)

    # Just the two lines: name + mode
    lines = reply.split("\n")
    assert len(lines) == 2
    assert "📍 Active source" in lines[0]
    assert "my-source" in lines[0]
    assert lines[1].startswith("🤖 Mode:")
    assert "Type" not in reply
    assert "Author" not in reply
    assert "URL" not in reply


@pytest.mark.anyio
async def test_switch_shows_full_info() -> None:
    """`/switch <name>` confirmation includes type, author, comment, URL lines."""
    source_service = AsyncMock()
    source_service._repository.get_source_by_name = AsyncMock(
        return_value={
            "id": "1",
            "source_name": "my-source",
            "type": "youtube",
            "author": "Jane Doe",
            "comment": "Great talk",
            "url": "https://youtube.com/watch?v=abc",
        }
    )
    handler = _build_command_handler(source_service)

    reply = await handler.handle_text("/switch my-source", chat_id=123)

    assert "✅" in reply
    assert "my-source" in reply
    assert "📁 Type: youtube" in reply
    assert "✍️ Author: Jane Doe" in reply
    assert "💬 Comment: Great talk" in reply
    assert "🔗 URL: https://youtube.com/watch?v=abc" in reply


@pytest.mark.anyio
async def test_default_shows_full_info() -> None:
    """`/default` confirmation includes source details (only name if no other fields)."""
    source_service = AsyncMock()
    source_service._repository.get_source_by_name = AsyncMock(
        return_value={"id": "default", "source_name": "default"}
    )
    handler = _build_command_handler(source_service)

    reply = await handler.handle_text("/default", chat_id=123)

    assert "✅" in reply
    assert "default" in reply
    # No extra detail lines for the minimal default source
    assert "📁 Type" not in reply
    assert "✍️ Author" not in reply
    assert "🔗 URL" not in reply


@pytest.mark.anyio
async def test_inline_keyboard_activation_shows_full_info() -> None:
    """Callback query for source switch sends confirmation containing full source details."""
    # Build the command handler (for format_source_details and build_sources_keyboard)
    command_handler = _build_command_handler(AsyncMock())

    # Mock SourceService used by TelegramMessageHandler
    source_service = AsyncMock()
    source_service.activate_source_by_id = AsyncMock(
        return_value={
            "id": "1",
            "source_name": "yt-talk",
            "type": "youtube",
            "author": "Jane Doe",
            "comment": "Inspiring",
            "url": "https://youtube.com/watch?v=abc",
        }
    )
    source_service.list_sources = AsyncMock(
        return_value=[
            {
                "id": "1",
                "source_name": "yt-talk",
                "status": "active",
                "type": "youtube",
            }
        ]
    )

    # Minimal message handler — only the callback path is exercised
    handler = TelegramMessageHandler(
        ingestion_service=Mock(),
        voice_note_service=AsyncMock(),
        transcription_service=Mock(),
        command_handler=command_handler,
        bot_client=AsyncMock(),
        chat_mode_service=ChatModeService(),
        multi_agent_service=AsyncMock(),
        reflection_service=AsyncMock(),
        source_service=source_service,
    )

    await handler.handle(_build_callback_update(callback_data="src:1"))

    # Confirmation message sent with full source details
    bot_client = handler._bot_client
    sent_messages = [
        call.args[1]
        for call in bot_client.send_message.await_args_list
        if len(call.args) >= 2
    ]
    assert any(
        "✅ Active source" in msg and "yt-talk" in msg for msg in sent_messages
    )
    assert any("📁 Type: youtube" in msg for msg in sent_messages)
    assert any("✍️ Author: Jane Doe" in msg for msg in sent_messages)
    assert any("💬 Comment: Inspiring" in msg for msg in sent_messages)
    assert any("🔗 URL: https://youtube.com/watch?v=abc" in msg for msg in sent_messages)


# --------------------------------------------------------------------------- #
#  Feature 2 — Prefix filter
# --------------------------------------------------------------------------- #


@pytest.mark.anyio
async def test_sources_no_filter_shows_all() -> None:
    """`/sources` with no argument shows all sources (unchanged)."""
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

    bot_client.send_message_with_inline_keyboard.assert_awaited_once()
    call_args = bot_client.send_message_with_inline_keyboard.call_args
    chat_id_arg, _text_arg, keyboard_arg = call_args[0]
    assert chat_id_arg == 123
    inline_kb = keyboard_arg["inline_keyboard"]
    assert len(inline_kb) == 2  # both sources


@pytest.mark.anyio
async def test_sources_filter_yt() -> None:
    """`/sources yt` shows only sources with `type = "youtube"`."""
    source_service = AsyncMock()
    source_service.list_sources = AsyncMock(
        return_value=[
            {"id": "1", "source_name": "yt-talk", "type": "youtube"},
            {"id": "2", "source_name": "bk-clean-arch", "type": "book"},
            {"id": "3", "source_name": "yt-other", "type": "youtube"},
        ]
    )
    bot_client = AsyncMock()
    handler = _build_command_handler(source_service, bot_client=bot_client)

    await handler.handle_text("/sources yt", chat_id=123)

    bot_client.send_message_with_inline_keyboard.assert_awaited_once()
    call_args = bot_client.send_message_with_inline_keyboard.call_args
    _chat_id_arg, _text_arg, keyboard_arg = call_args[0]
    inline_kb = keyboard_arg["inline_keyboard"]
    rendered = [btn[0]["text"] for btn in inline_kb]
    assert "yt-talk" in rendered
    assert "yt-other" in rendered
    assert "bk-clean-arch" not in rendered


@pytest.mark.anyio
async def test_sources_filter_case_insensitive() -> None:
    """`/sources TS` (uppercase) shows only sources with `type = "test"`."""
    source_service = AsyncMock()
    source_service.list_sources = AsyncMock(
        return_value=[
            {"id": "1", "source_name": "ts-fixture", "type": "test"},
            {"id": "2", "source_name": "yt-talk", "type": "youtube"},
            {"id": "3", "source_name": "ts-other", "type": "test"},
        ]
    )
    bot_client = AsyncMock()
    handler = _build_command_handler(source_service, bot_client=bot_client)

    await handler.handle_text("/sources TS", chat_id=123)

    bot_client.send_message_with_inline_keyboard.assert_awaited_once()
    call_args = bot_client.send_message_with_inline_keyboard.call_args
    _chat_id_arg, _text_arg, keyboard_arg = call_args[0]
    inline_kb = keyboard_arg["inline_keyboard"]
    rendered = [btn[0]["text"] for btn in inline_kb]
    assert "ts-fixture" in rendered
    assert "ts-other" in rendered
    assert "yt-talk" not in rendered


@pytest.mark.anyio
async def test_sources_filter_ot_matches_empty_type() -> None:
    """`/sources ot` shows sources with `type = "other"` AND empty/None type."""
    source_service = AsyncMock()
    source_service.list_sources = AsyncMock(
        return_value=[
            {"id": "1", "source_name": "ot-thing", "type": "other"},
            {"id": "2", "source_name": "no-type", "type": None},
            {"id": "3", "source_name": "empty-type", "type": ""},
            {"id": "4", "source_name": "yt-talk", "type": "youtube"},
        ]
    )
    bot_client = AsyncMock()
    handler = _build_command_handler(source_service, bot_client=bot_client)

    await handler.handle_text("/sources ot", chat_id=123)

    bot_client.send_message_with_inline_keyboard.assert_awaited_once()
    call_args = bot_client.send_message_with_inline_keyboard.call_args
    _chat_id_arg, _text_arg, keyboard_arg = call_args[0]
    inline_kb = keyboard_arg["inline_keyboard"]
    rendered = [btn[0]["text"] for btn in inline_kb]
    assert "ot-thing" in rendered
    assert "no-type" in rendered
    assert "empty-type" in rendered
    assert "yt-talk" not in rendered


@pytest.mark.anyio
async def test_sources_filter_invalid_prefix() -> None:
    """`/sources xyz` returns error message listing valid prefixes."""
    source_service = AsyncMock()
    source_service.list_sources = AsyncMock(
        return_value=[
            {"id": "1", "source_name": "alpha", "type": "youtube"},
        ]
    )
    bot_client = AsyncMock()
    handler = _build_command_handler(source_service, bot_client=bot_client)

    reply = await handler.handle_text("/sources xyz", chat_id=123)

    assert "❌" in reply
    assert "xyz" in reply
    assert "Valid prefixes" in reply
    # All valid prefixes should be listed
    for prefix in SOURCE_PREFIX_TO_TYPE:
        assert prefix in reply
    bot_client.send_message_with_inline_keyboard.assert_not_awaited()


@pytest.mark.anyio
async def test_sources_filter_no_matches() -> None:
    """`/sources bk` when no book sources exist returns 'no sources found' message."""
    source_service = AsyncMock()
    source_service.list_sources = AsyncMock(
        return_value=[
            {"id": "1", "source_name": "yt-talk", "type": "youtube"},
        ]
    )
    bot_client = AsyncMock()
    handler = _build_command_handler(source_service, bot_client=bot_client)

    reply = await handler.handle_text("/sources bk", chat_id=123)

    assert "📂" in reply
    assert "No sources found" in reply
    assert "book" in reply
    bot_client.send_message_with_inline_keyboard.assert_not_awaited()


@pytest.mark.anyio
async def test_sources_filter_pagination_preserves_filter() -> None:
    """Page callback with filter prefix in callback_data re-applies the filter."""
    # Need enough book sources to force >1 page (page size = 6)
    book_sources = [
        {"id": str(i), "source_name": f"bk-{i}", "type": "book"}
        for i in range(7)
    ]
    yt_sources = [
        {"id": "100", "source_name": "yt-talk", "type": "youtube"},
    ]

    # First list_sources call: filtered ("bk") + total -> used for /sources
    # Page callback: filter_prefix re-applies
    source_service = AsyncMock()
    source_service.list_sources = AsyncMock(side_effect=[book_sources + yt_sources, book_sources + yt_sources])
    source_service.activate_source_by_id = AsyncMock()

    command_handler = _build_command_handler(source_service)
    handler = TelegramMessageHandler(
        ingestion_service=Mock(),
        voice_note_service=AsyncMock(),
        transcription_service=Mock(),
        command_handler=command_handler,
        bot_client=AsyncMock(),
        chat_mode_service=ChatModeService(),
        multi_agent_service=AsyncMock(),
        reflection_service=AsyncMock(),
        source_service=source_service,
    )

    # Page callback for the book-filtered list, page 0
    result = await handler.handle(
        _build_callback_update(callback_data="src_page:0:bk")
    )

    assert result["outcome"] == "page_changed"
    # The keyboard sent to edit_message_text should only contain book sources
    edit_call = handler._bot_client.edit_message_text.await_args
    _chat_id_arg, _msg_id_arg, _text_arg, keyboard_arg = edit_call[0]
    inline_kb = keyboard_arg["inline_keyboard"]
    rendered = [btn[0]["text"] for btn in inline_kb]
    assert "yt-talk" not in rendered
    # The pagination nav row (last row) must preserve the filter prefix in callback_data.
    # Source buttons keep their plain "src:<id>" callback_data — only nav buttons carry the filter.
    nav_row = inline_kb[-1]
    assert len(nav_row) >= 1
    for nav_btn in nav_row:
        assert "bk" in nav_btn["callback_data"]
        assert nav_btn["callback_data"].startswith("src_page:")


@pytest.mark.parametrize(
    ("prefix", "expected"),
    [
        ("yt", "youtube"),
        ("TS", "test"),
        ("bk", "book"),
        ("OT", "other"),
    ],
)
def test_resolve_prefix_to_type_valid(prefix: str, expected: str) -> None:
    """`resolve_prefix_to_type` maps prefix codes (case-insensitive) to canonical types."""
    assert resolve_prefix_to_type(prefix) == expected


@pytest.mark.parametrize("prefix", ["xyz", "", "foo", "yt-"])
def test_resolve_prefix_to_type_invalid(prefix: str) -> None:
    """`resolve_prefix_to_type` returns None for unknown prefixes — including trailing-dash."""
    assert resolve_prefix_to_type(prefix) is None


def test_resolve_prefix_to_type_ot() -> None:
    """`resolve_prefix_to_type("ot")` returns `"other"`."""
    assert resolve_prefix_to_type("ot") == "other"


# --------------------------------------------------------------------------- #
#  Feature 3 — Command rename (/build, /build st)
# --------------------------------------------------------------------------- #


@pytest.mark.anyio
async def test_build_command_works() -> None:
    """`/build` triggers session document synthesis (same as the old `/build_doc`)."""
    source_service = AsyncMock()
    source_service.get_active_source = AsyncMock(
        return_value={"id": "source-1", "source_name": "my-source"}
    )
    session_builder = AsyncMock(spec=SessionBuilderService)
    session_builder._session_docs_repo = AsyncMock()
    session_builder._session_docs_repo.get_pending_note_ids = AsyncMock(
        return_value=["note-1", "note-2"]
    )
    session_builder.build = AsyncMock(
        return_value={
            "id": "doc-1",
            "title": "Test Document",
            "content": "# Test Document\n\n## Summary\nA test summary that is long enough to be meaningful.",
        }
    )

    handler = _build_command_handler(
        source_service, session_builder=session_builder
    )

    reply = await handler.handle_text("/build", chat_id=123)

    session_builder.build.assert_awaited_once_with("source-1", ["note-1", "note-2"])
    assert "Test Document" in reply
    assert "2 notes synthesized" in reply


@pytest.mark.anyio
async def test_build_st_command_works() -> None:
    """`/build st` triggers session document preview (same as the old `/build_doc stats`)."""
    source_service = AsyncMock()
    source_service.get_active_source = AsyncMock(
        return_value={"id": "source-1", "source_name": "my-source"}
    )
    session_builder = AsyncMock(spec=SessionBuilderService)
    session_builder._session_docs_repo = AsyncMock()
    session_builder._session_docs_repo.get_pending_note_ids = AsyncMock(
        return_value=["note-1"]
    )
    session_builder.preview = AsyncMock(
        return_value={
            "pending_count": 1,
            "un_enriched_count": 1,
            "time_range": "2026-01-01 → 2026-01-02",
            "notes": [
                {
                    "voice_note_uuid": "note-1",
                    "title": "Note Title",
                    "status": "created",
                    "created_at": "2026-01-01T00:00:00Z",
                }
            ],
        }
    )

    handler = _build_command_handler(
        source_service, session_builder=session_builder
    )

    reply = await handler.handle_text("/build st", chat_id=123)

    session_builder.preview.assert_awaited_once()
    session_builder.build.assert_not_awaited()
    assert "my-source" in reply
    assert "Pending notes: 1" in reply


@pytest.mark.anyio
async def test_build_doc_returns_unknown() -> None:
    """`/build_doc` returns the unknown-command fallback message."""
    source_service = AsyncMock()
    handler = _build_command_handler(source_service)

    reply = await handler.handle_text("/build_doc", chat_id=123)

    assert reply == "🤖 Send voice notes to capture ideas. Use /sources to manage sources."
    # build handler must not have been touched
    handler._bot_client.send_message.assert_awaited_once_with(123, reply)


def test_help_lists_new_commands() -> None:
    """`HELP_MESSAGE` contains `/build` and `/build st`, and does NOT contain `/build_doc`."""
    assert "/build" in HELP_MESSAGE
    assert "/build st" in HELP_MESSAGE
    assert "/build_doc" not in HELP_MESSAGE
