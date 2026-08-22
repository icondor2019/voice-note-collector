"""Tests for source enrichment decoupling feature.

Covers:
- Deterministic URL creation (no LLM, no pending context)
- /update command (enrichment on demand for any active source)
- Preservation of existing /create flows
- start_url_flow() removal verification
"""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest

from backend.services.source_create_agent import (
    SourceCreateAgent,
    SourceCreateContext,
    SourceCreateStep,
)
from backend.services.chat_mode_service import ChatModeService
from backend.services.source_service import SourceService
from backend.services.telegram_command_handler import (
    HELP_MESSAGE,
    TelegramCommandHandler,
)
from backend.services.telegram_message_handler import TelegramMessageHandler
from backend.services.telegram_ingestion_service import TelegramIngestionService
from backend.services.transcription_service import TranscriptionService
from backend.services.voice_note_service import VoiceNoteService
from backend.services.reflection_service import ReflectionService
from backend.models.agent import MultiAgentResult
from configuration.settings import settings


# ── Helper factories ──────────────────────────────────────────────────────────


def _make_agent_with_mock_service() -> SourceCreateAgent:
    svc = AsyncMock()
    svc._repository = AsyncMock()
    svc._repository.get_source_by_url = AsyncMock(return_value=None)
    svc._repository.get_source_by_name = AsyncMock(return_value=None)
    svc.create_source_and_optionally_activate = AsyncMock(
        return_value={
            "id": "src-123",
            "source_name": "yt-youtube-watch",
            "type": "youtube",
            "status": "active",
        }
    )
    svc.update_source = AsyncMock(
        return_value={
            "id": "src-123",
            "source_name": "yt-youtube-watch",
            "author": "Test Author",
            "comment": "Test Comment",
        }
    )
    svc.get_active_source = AsyncMock(
        return_value={
            "id": "src-123",
            "source_name": "yt-youtube-watch",
            "type": "youtube",
            "url": "https://youtube.com/watch?v=abc",
            "author": None,
            "comment": None,
        }
    )
    return SourceCreateAgent(source_service=svc)


def _build_event(
    *,
    chat_id: int | None = 123,
    from_user_id: int | None = None,
    message_type: str = "text",
) -> dict:
    return {
        "message_type": message_type,
        "chat_id": chat_id,
        "from_user_id": (
            settings.TELEGRAM_ALLOWED_USER_ID if from_user_id is None else from_user_id
        ),
        "message_id": 10,
        "telegram_file_id": "",
    }


def _build_message_handler(
    event: dict,
    *,
    chat_mode_service: ChatModeService | None = None,
    source_create_agent: SourceCreateAgent | None = None,
    source_service: AsyncMock | None = None,
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
    agent = source_create_agent or _make_agent_with_mock_service()
    svc = source_service or AsyncMock(spec=SourceService)
    return TelegramMessageHandler(
        ingestion_service=ingestion_service,
        voice_note_service=voice_note_service,
        transcription_service=transcription_service,
        command_handler=command_handler,
        bot_client=bot_client,
        chat_mode_service=chat_mode_service or ChatModeService(),
        multi_agent_service=multi_agent_service,
        reflection_service=reflection_service,
        source_service=svc,
        source_create_agent=agent,
    )


def _build_command_handler(
    *,
    source_create_agent: SourceCreateAgent | None = None,
    source_service: AsyncMock | None = None,
) -> TelegramCommandHandler:
    if source_service is None:
        svc = AsyncMock()
        svc.get_active_source = AsyncMock(
            return_value={
                "id": "src-123",
                "source_name": "yt-youtube-watch",
                "type": "youtube",
                "url": "https://youtube.com/watch?v=abc",
                "author": None,
                "comment": None,
            }
        )
    else:
        svc = source_service
    agent = source_create_agent or _make_agent_with_mock_service()
    return TelegramCommandHandler(
        svc, AsyncMock(), AsyncMock(), ChatModeService(), AsyncMock(),
        source_create_agent=agent,
    )


# ── start_url_flow() is removed ──────────────────────────────────────────────


class TestStartUrlFlowRemoved:
    def test_start_url_flow_does_not_exist(self) -> None:
        agent = SourceCreateAgent(source_service=AsyncMock())
        assert not hasattr(agent, "start_url_flow")


# ── Deterministic URL creation ────────────────────────────────────────────────


class TestDeterministicURLCreation:
    @pytest.mark.anyio
    async def test_no_llm_call(self) -> None:
        mock_client = Mock()
        mock_client.chat.completions.create = Mock()
        agent = SourceCreateAgent(source_service=AsyncMock(), openai_client=mock_client)
        agent._source_service._repository = AsyncMock()
        agent._source_service._repository.get_source_by_url = AsyncMock(return_value=None)
        agent._source_service.create_source_and_optionally_activate = AsyncMock(
            return_value={"id": "1", "source_name": "yt-test", "type": "youtube"}
        )
        await agent.create_source_from_url("https://youtube.com/watch?v=abc", user_id=1)
        mock_client.chat.completions.create.assert_not_called()

    @pytest.mark.anyio
    async def test_no_pending_context(self) -> None:
        agent = _make_agent_with_mock_service()
        await agent.create_source_from_url("https://youtube.com/watch?v=abc", user_id=1)
        assert agent.get_pending_context(1) is None

    @pytest.mark.anyio
    async def test_confirmation_includes_name_type_url(self) -> None:
        agent = _make_agent_with_mock_service()
        reply = await agent.create_source_from_url(
            "https://youtube.com/watch?v=abc", user_id=1
        )
        assert "✅ Source created" in reply
        assert "yt-youtube-watch" in reply
        assert "youtube" in reply
        assert "https://youtube.com/watch?v=abc" in reply

    @pytest.mark.anyio
    async def test_duplicate_url_returns_error(self) -> None:
        svc = AsyncMock()
        svc._repository = AsyncMock()
        svc._repository.get_source_by_url = AsyncMock(
            return_value={"source_name": "existing-source", "id": "existing-id"}
        )
        svc.create_source_and_optionally_activate = AsyncMock()
        agent = SourceCreateAgent(source_service=svc)
        reply = await agent.create_source_from_url(
            "https://youtube.com/watch?v=abc", user_id=1
        )
        assert "already exists" in reply
        svc.create_source_and_optionally_activate.assert_not_awaited()

    @pytest.mark.anyio
    async def test_works_without_openai_client(self) -> None:
        agent = SourceCreateAgent(source_service=AsyncMock(), openai_client=None)
        agent._source_service._repository = AsyncMock()
        agent._source_service._repository.get_source_by_url = AsyncMock(return_value=None)
        agent._source_service.create_source_and_optionally_activate = AsyncMock(
            return_value={"id": "1", "source_name": "yt-test", "type": "youtube"}
        )
        reply = await agent.create_source_from_url(
            "https://youtube.com/watch?v=abc", user_id=1
        )
        assert "✅ Source created" in reply


# ── /update command ───────────────────────────────────────────────────────────


class TestUpdateCommand:
    @pytest.mark.anyio
    async def test_update_with_active_source_starts_enrichment(self) -> None:
        handler = _build_command_handler()
        reply = await handler.handle_text("/update", chat_id=123, from_user_id=456)
        assert "yt-youtube-watch" in reply
        # New open-ended prompt
        assert "update" in reply.lower() or "tell me" in reply.lower()

    @pytest.mark.anyio
    async def test_update_no_active_source_returns_error(self) -> None:
        svc = AsyncMock()
        svc.get_active_source = AsyncMock(return_value=None)
        agent = _make_agent_with_mock_service()
        handler = _build_command_handler(source_create_agent=agent, source_service=svc)
        reply = await handler.handle_text("/update", chat_id=123, from_user_id=456)
        assert "No active source" in reply

    @pytest.mark.anyio
    async def test_update_ignores_arguments(self) -> None:
        handler = _build_command_handler()
        reply = await handler.handle_text(
            "/update something", chat_id=123, from_user_id=456
        )
        # Should still start enrichment (argument is ignored)
        assert "yt-youtube-watch" in reply

    @pytest.mark.anyio
    async def test_update_sets_pending_context(self) -> None:
        agent = _make_agent_with_mock_service()
        handler = _build_command_handler(source_create_agent=agent)
        await handler.handle_text("/update", chat_id=123, from_user_id=456)
        ctx = agent.get_pending_context(456)
        assert ctx is not None
        assert ctx.step == SourceCreateStep.AWAITING_INPUT
        assert ctx.source_id == "src-123"

    @pytest.mark.anyio
    async def test_update_clears_stale_context(self) -> None:
        """Verify /update clears any pre-existing pending context."""
        agent = _make_agent_with_mock_service()
        # Set stale context from abandoned /create flow
        stale_ctx = SourceCreateContext(
            source_type="thought",
            step=SourceCreateStep.AWAITING_INPUT,
        )
        agent._pending[456] = stale_ctx
        handler = _build_command_handler(source_create_agent=agent)
        await handler.handle_text("/update", chat_id=123, from_user_id=456)
        ctx = agent.get_pending_context(456)
        assert ctx is not None
        assert ctx.source_id == "src-123"  # New context, not stale


# ── Enrichment flow (source-agnostic) ────────────────────────────────────────


class TestEnrichFlowSourceAgnostic:
    @pytest.mark.anyio
    async def test_enrich_url_created_source(self) -> None:
        agent = _make_agent_with_mock_service()
        source = {
            "id": "src-1",
            "source_name": "yt-youtube-watch",
            "type": "youtube",
            "url": "https://youtube.com/watch?v=abc",
            "author": None,
            "comment": None,
        }
        reply = await agent.start_enrich_flow(1, source)
        assert "yt-youtube-watch" in reply
        ctx = agent.get_pending_context(1)
        assert ctx is not None
        assert ctx.source_id == "src-1"

    @pytest.mark.anyio
    async def test_enrich_manually_created_source(self) -> None:
        agent = _make_agent_with_mock_service()
        source = {
            "id": "src-2",
            "source_name": "bk-my-book",
            "type": "book",
            "url": None,
            "author": None,
            "comment": None,
        }
        reply = await agent.start_enrich_flow(1, source)
        assert "bk-my-book" in reply
        ctx = agent.get_pending_context(1)
        assert ctx is not None
        assert ctx.source_id == "src-2"
        assert ctx.url is None

    @pytest.mark.anyio
    async def test_enrich_switched_source(self) -> None:
        agent = _make_agent_with_mock_service()
        source = {
            "id": "src-3",
            "source_name": "ig-instagram-post",
            "type": "instagram",
            "url": "https://instagram.com/p/xyz",
            "author": "Some Author",
            "comment": "Some Comment",
        }
        reply = await agent.start_enrich_flow(1, source)
        assert "ig-instagram-post" in reply
        ctx = agent.get_pending_context(1)
        assert ctx is not None
        assert ctx.author == "Some Author"
        assert ctx.comment == "Some Comment"

    @pytest.mark.anyio
    async def test_enrich_with_existing_metadata(self) -> None:
        """Verify works when source already has author/comment set."""
        agent = _make_agent_with_mock_service()
        source = {
            "id": "src-4",
            "source_name": "yt-existing",
            "type": "youtube",
            "url": "https://youtube.com/watch?v=abc",
            "author": "Existing Author",
            "comment": "Existing Comment",
        }
        reply = await agent.start_enrich_flow(1, source)
        ctx = agent.get_pending_context(1)
        assert ctx is not None
        assert ctx.step == SourceCreateStep.AWAITING_INPUT
        # New open-ended prompt
        assert "update" in reply.lower() or "tell me" in reply.lower()

    @pytest.mark.anyio
    async def test_enrich_clears_existing_pending(self) -> None:
        agent = _make_agent_with_mock_service()
        # Pre-existing pending context
        old_ctx = SourceCreateContext(
            source_type="thought",
            step=SourceCreateStep.AWAITING_INPUT,
        )
        agent._pending[1] = old_ctx
        source = {
            "id": "src-5",
            "source_name": "wb-new-source",
            "type": "web",
        }
        await agent.start_enrich_flow(1, source)
        ctx = agent.get_pending_context(1)
        assert ctx is not None
        assert ctx.source_id == "src-5"  # New context replaced old

    @pytest.mark.anyio
    async def test_enrich_no_url_source(self) -> None:
        """Verify works on a source with url=None (manually created)."""
        agent = _make_agent_with_mock_service()
        source = {
            "id": "src-6",
            "source_name": "th-daily-thoughts",
            "type": "thought",
            "url": None,
        }
        reply = await agent.start_enrich_flow(1, source)
        assert "th-daily-thoughts" in reply
        ctx = agent.get_pending_context(1)
        assert ctx is not None
        assert ctx.url is None


# ── URL-only message integration ─────────────────────────────────────────────


class TestURLOnlyMessageIntegration:
    @pytest.mark.anyio
    async def test_url_only_no_llm_no_pending(self) -> None:
        """URL-only message: no LLM call, no pending context."""
        event = _build_event(message_type="text")
        agent = _make_agent_with_mock_service()
        handler = _build_message_handler(event, source_create_agent=agent)
        update = {"message": {"text": "https://youtube.com/watch?v=abc", "chat": {"id": 123}}}

        result = await handler.handle(update)

        assert result == {"outcome": "source_create", "message_type": "text"}
        assert agent.get_pending_context(settings.TELEGRAM_ALLOWED_USER_ID) is None

    @pytest.mark.anyio
    async def test_url_only_no_mode_switch(self) -> None:
        """URL-only message does NOT auto-switch to agent mode."""
        event = _build_event(message_type="text")
        chat_mode_service = ChatModeService()
        chat_mode_service.set_mode("note")
        handler = _build_message_handler(
            event, chat_mode_service=chat_mode_service
        )
        update = {"message": {"text": "https://youtube.com/watch?v=abc", "chat": {"id": 123}}}

        await handler.handle(update)

        # Mode should remain note (no auto-switch)
        assert chat_mode_service.get_mode() == "note"


# ── /create <url> integration ────────────────────────────────────────────────


class TestCreateURLCommand:
    @pytest.mark.anyio
    async def test_create_url_deterministic(self) -> None:
        """/create <url> creates source deterministically (no LLM, no enrichment)."""
        agent = _make_agent_with_mock_service()
        handler = _build_command_handler(source_create_agent=agent)
        reply = await handler.handle_text(
            "/create https://youtube.com/watch?v=abc", chat_id=123, from_user_id=456
        )
        assert "✅ Source created" in reply
        assert agent.get_pending_context(456) is None


# ── Existing flows preserved ─────────────────────────────────────────────────


class TestExistingFlowsPreserved:
    @pytest.mark.anyio
    async def test_create_no_args_still_guided(self) -> None:
        """/create (no args) still starts guided creation flow."""
        agent = _make_agent_with_mock_service()
        handler = _build_command_handler(source_create_agent=agent)
        reply = await handler.handle_text("/create", chat_id=123, from_user_id=456)
        assert "create" in reply.lower()
        ctx = agent.get_pending_context(456)
        assert ctx is not None
        assert ctx.step == SourceCreateStep.AWAITING_INPUT

    @pytest.mark.anyio
    async def test_create_name_still_name_based(self) -> None:
        """/create <name> creates source immediately, no pending context."""
        agent = _make_agent_with_mock_service()
        handler = _build_command_handler(source_create_agent=agent)
        reply = await handler.handle_text(
            "/create yt-my-video", chat_id=123, from_user_id=456
        )
        assert "yt-my-video" in reply
        assert "Source created" in reply
        ctx = agent.get_pending_context(456)
        assert ctx is None


# ── HELP_MESSAGE ──────────────────────────────────────────────────────────────


class TestHelpMessage:
    def test_help_includes_update(self) -> None:
        assert "/update" in HELP_MESSAGE
        assert "enrich" in HELP_MESSAGE.lower()
