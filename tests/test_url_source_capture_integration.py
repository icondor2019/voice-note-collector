"""Tests for URL source capture integration with message handler and command handler."""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest

from backend.models.agent import MultiAgentResult
from backend.services.chat_mode_service import ChatModeService
from backend.services.reflection_service import ReflectionService
from backend.services.source_create_agent import SourceCreateAgent
from backend.services.source_service import SourceService
from backend.services.telegram_command_handler import TelegramCommandHandler
from backend.services.telegram_ingestion_service import TelegramIngestionService
from backend.services.telegram_message_handler import TelegramMessageHandler
from backend.services.transcription_service import TranscriptionService
from backend.services.voice_note_service import VoiceNoteService
from configuration.settings import settings


def _build_event(
    *,
    chat_id: int | None = 123,
    from_user_id: int | None = None,
    message_id: int = 10,
    message_type: str = "text",
) -> dict:
    return {
        "message_type": message_type,
        "chat_id": chat_id,
        "from_user_id": (
            settings.TELEGRAM_ALLOWED_USER_ID if from_user_id is None else from_user_id
        ),
        "message_id": message_id,
        "telegram_file_id": "",
    }


def _make_source_create_agent() -> SourceCreateAgent:
    svc = AsyncMock()
    svc._repository = AsyncMock()
    svc._repository.get_source_by_url = AsyncMock(return_value=None)
    svc._repository.get_source_by_name = AsyncMock(return_value=None)
    svc.create_source_and_optionally_activate = AsyncMock(
        return_value={"id": "1", "source_name": "yt-test-video", "type": "youtube"}
    )
    return SourceCreateAgent(source_service=svc)


def _build_message_handler(
    event: dict,
    *,
    chat_mode_service: ChatModeService | None = None,
    source_create_agent: SourceCreateAgent | None = None,
    use_default_agent: bool = True,
) -> TelegramMessageHandler:
    ingestion_service = Mock(spec=TelegramIngestionService)
    ingestion_service._build_ingestion_event = Mock(return_value=event)

    voice_note_service = AsyncMock(spec=VoiceNoteService)
    transcription_service = Mock(spec=TranscriptionService)
    command_handler = AsyncMock()
    bot_client = AsyncMock()
    multi_agent_service = AsyncMock()
    multi_agent_service.handle = AsyncMock(
        return_value=MultiAgentResult(reply="LLM reply", outcome="agent_response")
    )
    reflection_service = AsyncMock(spec=ReflectionService)
    reflection_service.get_pending_reflection = AsyncMock(return_value=None)
    source_service = AsyncMock(spec=SourceService)

    agent = source_create_agent
    if agent is None and use_default_agent:
        agent = _make_source_create_agent()

    return TelegramMessageHandler(
        ingestion_service=ingestion_service,
        voice_note_service=voice_note_service,
        transcription_service=transcription_service,
        command_handler=command_handler,
        bot_client=bot_client,
        chat_mode_service=chat_mode_service or ChatModeService(),
        multi_agent_service=multi_agent_service,
        reflection_service=reflection_service,
        source_service=source_service,
        source_create_agent=agent,
    )


# ── URL-only detection in message handler ─────────────────────────────────────


@pytest.mark.anyio
async def test_url_only_in_note_mode_triggers_source_creation() -> None:
    """URL-only message in note mode triggers deterministic source creation (no mode switch)."""
    event = _build_event(message_type="text")
    chat_mode_service = ChatModeService()
    chat_mode_service.set_mode("note")
    source_create_agent = _make_source_create_agent()

    handler = _build_message_handler(
        event,
        chat_mode_service=chat_mode_service,
        source_create_agent=source_create_agent,
    )
    update = {"message": {"text": "https://youtube.com/watch?v=abc", "chat": {"id": 123}}}

    result = await handler.handle(update)

    assert result == {"outcome": "source_create", "message_type": "text"}
    # No auto-switch to agent mode anymore
    assert chat_mode_service.get_mode() == "note"
    handler._bot_client.send_message.assert_awaited_once()
    sent_text = handler._bot_client.send_message.call_args[0][1]
    assert "youtube" in sent_text


@pytest.mark.anyio
async def test_url_only_in_agent_mode_triggers_source_creation() -> None:
    """URL-only message in agent mode routes to source creation."""
    event = _build_event(message_type="text")
    chat_mode_service = ChatModeService()
    chat_mode_service.set_mode("agent")
    source_create_agent = _make_source_create_agent()

    handler = _build_message_handler(
        event,
        chat_mode_service=chat_mode_service,
        source_create_agent=source_create_agent,
    )
    update = {"message": {"text": "https://instagram.com/p/xyz", "chat": {"id": 123}}}

    result = await handler.handle(update)

    assert result == {"outcome": "source_create", "message_type": "text"}


@pytest.mark.anyio
async def test_url_plus_text_does_not_trigger_source_creation() -> None:
    """URL + additional text does NOT trigger source creation — follows normal routing."""
    event = _build_event(message_type="text")
    chat_mode_service = ChatModeService()
    chat_mode_service.set_mode("agent")
    source_create_agent = _make_source_create_agent()

    handler = _build_message_handler(
        event,
        chat_mode_service=chat_mode_service,
        source_create_agent=source_create_agent,
    )
    update = {
        "message": {
            "text": "check this https://youtube.com/watch?v=abc",
            "chat": {"id": 123},
        }
    }

    result = await handler.handle(update)

    # Should route to multi-agent, NOT source creation
    assert result == {"outcome": "agent_response", "message_type": "text"}
    handler._multi_agent_service.handle.assert_awaited_once()


@pytest.mark.anyio
async def test_url_only_in_note_mode_without_agent_routes_to_multi_agent() -> None:
    """URL-only in note mode without source_create_agent falls back to multi-agent."""
    event = _build_event(message_type="text")
    chat_mode_service = ChatModeService()
    chat_mode_service.set_mode("note")

    handler = _build_message_handler(
        event,
        chat_mode_service=chat_mode_service,
        use_default_agent=False,
    )
    update = {"message": {"text": "https://youtube.com/watch?v=abc", "chat": {"id": 123}}}

    result = await handler.handle(update)

    # No auto-switch to agent mode; routed to multi-agent
    assert chat_mode_service.get_mode() == "note"
    assert result == {"outcome": "agent_response", "message_type": "text"}


# ── Command handler /create routing ───────────────────────────────────────────


@pytest.mark.anyio
async def test_create_no_args_routes_to_agent() -> None:
    """/create with no args routes to source creation agent."""
    source_service = AsyncMock()
    bot_client = AsyncMock()
    labels_repository = AsyncMock()
    source_create_agent = _make_source_create_agent()

    handler = TelegramCommandHandler(
        source_service,
        bot_client,
        labels_repository,
        ChatModeService(),
        AsyncMock(),
        source_create_agent=source_create_agent,
    )

    reply = await handler.handle_text("/create", chat_id=123, from_user_id=456)

    assert "type" in reply.lower() or "create" in reply.lower()
    assert source_create_agent.get_pending_context(456) is not None


@pytest.mark.anyio
async def test_create_with_url_routes_to_deterministic_creation() -> None:
    """/create <url> creates source deterministically (no LLM, no enrichment)."""
    source_service = AsyncMock()
    bot_client = AsyncMock()
    labels_repository = AsyncMock()
    source_create_agent = _make_source_create_agent()

    handler = TelegramCommandHandler(
        source_service,
        bot_client,
        labels_repository,
        ChatModeService(),
        AsyncMock(),
        source_create_agent=source_create_agent,
    )

    reply = await handler.handle_text(
        "/create https://youtube.com/watch?v=abc", chat_id=123, from_user_id=456
    )

    assert "youtube" in reply
    assert "✅ Source created" in reply
    # No pending context after deterministic creation
    assert source_create_agent.get_pending_context(456) is None


@pytest.mark.anyio
async def test_create_with_name_routes_to_agent() -> None:
    """/create <name> creates source immediately, no pending context."""
    source_service = AsyncMock()
    bot_client = AsyncMock()
    labels_repository = AsyncMock()
    source_create_agent = _make_source_create_agent()

    handler = TelegramCommandHandler(
        source_service,
        bot_client,
        labels_repository,
        ChatModeService(),
        AsyncMock(),
        source_create_agent=source_create_agent,
    )

    reply = await handler.handle_text("/create yt-my-video", chat_id=123, from_user_id=456)

    assert "yt-my-video" in reply
    assert "Source created" in reply
    ctx = source_create_agent.get_pending_context(456)
    assert ctx is None


@pytest.mark.anyio
async def test_help_message_includes_create_variants() -> None:
    """Help message documents new /create behavior."""
    from backend.services.telegram_command_handler import HELP_MESSAGE

    assert "/create" in HELP_MESSAGE
    assert "/create <url>" in HELP_MESSAGE or "URL" in HELP_MESSAGE
