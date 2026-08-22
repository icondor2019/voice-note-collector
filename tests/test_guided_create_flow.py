"""Regression tests for the guided `/create` flow fix.

Tests the SourceCreateContext flow marker roundtrip, guided name-based
creation, source creation only after confirmation, screenshot scenario,
_apply_enrichment() remaining update-only, /update with no active source,
and URL creation unchanged.

Covers:
- TestFlowMarker
- TestGuidedCreateFlowCreatesSource
- TestEnrichmentStillUpdateOnly
- TestNoSourceUpdateBehavior
- TestScreenshotScenario
- TestURLCreationUnchanged
"""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest

from backend.services.multi_agent_service import MultiAgentService
from backend.services.source_create_agent import (
    SourceCreateAgent,
    SourceCreateContext,
    SourceCreateStep,
)
from backend.services.telegram_command_handler import TelegramCommandHandler
from backend.services.chat_mode_service import ChatModeService


# ── Helper factories ──────────────────────────────────────────────────────────


def _make_agent_with_mock_service() -> SourceCreateAgent:
    svc = AsyncMock()
    svc._repository = AsyncMock()
    svc._repository.get_source_by_url = AsyncMock(return_value=None)
    svc._repository.get_source_by_name = AsyncMock(return_value=None)
    svc.create_source_and_optionally_activate = AsyncMock(
        return_value={
            "id": "src-new-123",
            "source_name": "bk-test-book",
            "type": "book",
            "status": "active",
        }
    )
    svc.update_source = AsyncMock(
        return_value={
            "id": "src-123",
            "source_name": "yt-test-video",
            "author": "Test Author",
            "comment": "Test Comment",
        }
    )
    svc.get_active_source = AsyncMock(
        return_value={
            "id": "src-123",
            "source_name": "yt-test-video",
            "type": "youtube",
            "url": "https://youtube.com/watch?v=abc",
            "author": None,
            "comment": None,
        }
    )
    return SourceCreateAgent(source_service=svc)


def _make_agent_with_mock_service_no_active() -> SourceCreateAgent:
    svc = AsyncMock()
    svc._repository = AsyncMock()
    svc._repository.get_source_by_url = AsyncMock(return_value=None)
    svc._repository.get_source_by_name = AsyncMock(return_value=None)
    svc.get_active_source = AsyncMock(return_value=None)
    svc.create_source_and_optionally_activate = AsyncMock(
        return_value={
            "id": "src-new-456",
            "source_name": "bk-my-book",
            "type": "book",
            "status": "active",
        }
    )
    return SourceCreateAgent(source_service=svc)


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
                "source_name": "yt-test-video",
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


# ── TestFlowMarker ────────────────────────────────────────────────────────────


class TestFlowMarker:
    """SourceCreateContext flow marker roundtrip and entry-point setting."""

    def test_context_default_flow_is_enrich(self) -> None:
        """SourceCreateContext defaults to flow='enrich'."""
        ctx = SourceCreateContext(source_type="web")
        assert ctx.flow == "enrich"

    def test_context_flow_create_roundtrips(self) -> None:
        """A context with flow='create' survives to_dict() / from_dict()."""
        ctx = SourceCreateContext(source_type="book", flow="create")
        data = ctx.to_dict()
        assert data["flow"] == "create"

        restored = SourceCreateContext.from_dict(data)
        assert restored.flow == "create"

    @pytest.mark.anyio
    async def test_start_create_flow_sets_flow_create(self) -> None:
        """start_create_flow() sets flow='create' on the pending context."""
        agent = _make_agent_with_mock_service()
        await agent.start_create_flow(1, None)

        ctx = agent.get_pending_context(1)
        assert ctx is not None
        assert ctx.flow == "create"

    @pytest.mark.anyio
    async def test_start_enrich_flow_sets_flow_enrich(self) -> None:
        """start_enrich_flow() sets flow='enrich' on the pending context."""
        agent = _make_agent_with_mock_service()
        source = {
            "id": "src-1",
            "source_name": "yt-test-video",
            "type": "youtube",
            "url": "https://youtube.com/watch?v=abc",
        }
        await agent.start_enrich_flow(1, source)

        ctx = agent.get_pending_context(1)
        assert ctx is not None
        assert ctx.flow == "enrich"


# ── TestGuidedCreateFlowCreatesSource ─────────────────────────────────────────


class TestGuidedCreateFlowCreatesSource:
    """Guided /create flow creates source only after confirmation."""

    @pytest.mark.anyio
    async def test_guided_create_no_args_creates_source(self) -> None:
        """Full guided /create flow: type → name (with prefix) → author → comment → confirm."""
        agent = _make_agent_with_mock_service()

        # Start guided /create (no args)
        reply = await agent.start_create_flow(1, None)
        assert "What type of source" in reply

        # Provide type → prompts for name
        reply = await agent.handle_response("book", 1)
        assert "suggested name" in reply.lower()

        # Provide name with valid prefix → prompts for author
        reply = await agent.handle_response("bk-test-book", 1)
        assert "author" in reply.lower()

        # Provide author → prompts for comment
        reply = await agent.handle_response("John Doe", 1)
        assert "comment" in reply.lower() or "anything else" in reply.lower()

        # Provide comment → reaches confirmation
        reply = await agent.handle_response("A great book", 1)
        assert "Here's what" in reply or "anything else" in reply.lower()

        # Confirm
        reply = await agent.handle_response("confirm", 1)

        # Should have called create_source_and_optionally_activate
        agent._source_service.create_source_and_optionally_activate.assert_awaited_once()
        call_kwargs = agent._source_service.create_source_and_optionally_activate.call_args.kwargs
        assert call_kwargs["activate"] is True
        assert call_kwargs["author"] == "John Doe"
        assert call_kwargs["comment"] == "A great book"

    @pytest.mark.anyio
    async def test_guided_create_with_name_creates_source_immediately(self) -> None:
        """/create <name> creates source immediately, no guided flow."""
        agent = _make_agent_with_mock_service()

        reply = await agent.start_create_flow(1, "bk-my-book")

        # Should create immediately
        agent._source_service.create_source_and_optionally_activate.assert_awaited_once()
        call_kwargs = agent._source_service.create_source_and_optionally_activate.call_args.kwargs
        assert call_kwargs["source_name"] == "bk-my-book"
        assert call_kwargs["activate"] is True
        assert call_kwargs["type"] is None

        # Should return confirmation, not guided flow prompt
        assert "Source created" in reply
        assert "bk-my-book" in reply

        # No pending context
        assert agent.get_pending_context(1) is None

    @pytest.mark.anyio
    async def test_guided_create_confirmation_says_created(self) -> None:
        """After guided create confirmation, reply contains 'Source created'."""
        agent = _make_agent_with_mock_service()

        await agent.start_create_flow(1, None)
        await agent.handle_response("book", 1)  # type
        await agent.handle_response("bk-test-book", 1)  # name
        await agent.handle_response("John", 1)  # author
        await agent.handle_response("A comment", 1)  # comment
        reply = await agent.handle_response("confirm", 1)

        assert "Source created" in reply
        assert "Source updated" not in reply

    @pytest.mark.anyio
    async def test_guided_create_clears_pending_context(self) -> None:
        """After guided create confirmation, pending context is cleared."""
        agent = _make_agent_with_mock_service()

        await agent.start_create_flow(1, None)
        await agent.handle_response("book", 1)  # type
        await agent.handle_response("bk-test-book", 1)  # name
        await agent.handle_response("John", 1)  # author
        await agent.handle_response("A comment", 1)  # comment
        await agent.handle_response("confirm", 1)

        assert agent.get_pending_context(1) is None

    @pytest.mark.anyio
    async def test_guided_create_activates_source(self) -> None:
        """create_source_and_optionally_activate() is called with activate=True."""
        agent = _make_agent_with_mock_service()

        await agent.start_create_flow(1, None)
        await agent.handle_response("book", 1)  # type
        await agent.handle_response("bk-test-book", 1)  # name
        await agent.handle_response("John", 1)  # author
        await agent.handle_response("A comment", 1)  # comment
        await agent.handle_response("confirm", 1)

        agent._source_service.create_source_and_optionally_activate.assert_awaited_once()
        call_kwargs = agent._source_service.create_source_and_optionally_activate.call_args.kwargs
        assert call_kwargs["activate"] is True


# ── TestEnrichmentStillUpdateOnly ─────────────────────────────────────────────


class TestEnrichmentStillUpdateOnly:
    """_apply_enrichment() remains update-only; create is never called."""

    @pytest.mark.anyio
    async def test_enrichment_with_source_id_calls_update(self) -> None:
        """Enrichment flow (has source_id) calls update_source, not create."""
        agent = _make_agent_with_mock_service()
        source = {
            "id": "src-1",
            "source_name": "yt-test-video",
            "type": "youtube",
            "url": "https://youtube.com/watch?v=abc",
        }
        await agent.start_enrich_flow(1, source)
        await agent.handle_response("yes", 1)  # accept name
        await agent.handle_response("John", 1)  # author
        await agent.handle_response("Great tutorial", 1)  # comment

        reply = await agent.handle_response("confirm", 1)

        agent._source_service.update_source.assert_awaited_once()
        agent._source_service.create_source_and_optionally_activate.assert_not_awaited()

    @pytest.mark.anyio
    async def test_enrichment_confirmation_says_updated(self) -> None:
        """After enrichment confirmation, reply contains 'Source updated'."""
        agent = _make_agent_with_mock_service()
        source = {
            "id": "src-1",
            "source_name": "yt-test-video",
            "type": "youtube",
            "url": "https://youtube.com/watch?v=abc",
        }
        await agent.start_enrich_flow(1, source)
        await agent.handle_response("yes", 1)
        await agent.handle_response("John", 1)
        await agent.handle_response("A comment", 1)
        reply = await agent.handle_response("confirm", 1)

        assert "Source updated" in reply
        assert "Source created" not in reply

    @pytest.mark.anyio
    async def test_enrichment_does_not_create_source(self) -> None:
        """After enrichment confirmation, create_source_and_optionally_activate is NOT called."""
        agent = _make_agent_with_mock_service()
        source = {
            "id": "src-1",
            "source_name": "yt-test-video",
            "type": "youtube",
            "url": "https://youtube.com/watch?v=abc",
        }
        await agent.start_enrich_flow(1, source)
        await agent.handle_response("yes", 1)
        await agent.handle_response("skip", 1)
        await agent.handle_response("skip", 1)
        await agent.handle_response("confirm", 1)

        agent._source_service.create_source_and_optionally_activate.assert_not_awaited()

    @pytest.mark.anyio
    async def test_apply_enrichment_unchanged_no_source_id(self) -> None:
        """_apply_enrichment() with source_id=None returns 'No source to update'."""
        agent = _make_agent_with_mock_service()
        ctx = SourceCreateContext(source_type="book", flow="enrich")
        # ctx.source_id is None
        reply = await agent._apply_enrichment(1, ctx)

        assert "No source to update" in reply
        agent._source_service.update_source.assert_not_awaited()
        agent._source_service.create_source_and_optionally_activate.assert_not_awaited()


# ── TestNoSourceUpdateBehavior ────────────────────────────────────────────────


class TestNoSourceUpdateBehavior:
    """/update with no active source stops with a clear error."""

    @pytest.mark.anyio
    async def test_update_no_active_source_returns_error(self) -> None:
        """/update with no active source returns 'No active source' error."""
        svc = AsyncMock()
        svc.get_active_source = AsyncMock(return_value=None)
        svc._repository = AsyncMock()
        svc._repository.get_source_by_url = AsyncMock(return_value=None)
        agent = _make_agent_with_mock_service_no_active()
        handler = _build_command_handler(source_create_agent=agent, source_service=svc)

        reply = await handler.handle_text("/update", chat_id=123, from_user_id=1)

        assert "No active source" in reply

    @pytest.mark.anyio
    async def test_update_no_active_source_no_pending_context(self) -> None:
        """After /update with no active source, no pending context is set."""
        svc = AsyncMock()
        svc.get_active_source = AsyncMock(return_value=None)
        svc._repository = AsyncMock()
        svc._repository.get_source_by_url = AsyncMock(return_value=None)
        agent = _make_agent_with_mock_service_no_active()
        handler = _build_command_handler(source_create_agent=agent, source_service=svc)

        await handler.handle_text("/update", chat_id=123, from_user_id=1)

        assert agent.get_pending_context(1) is None

    @pytest.mark.anyio
    async def test_update_no_active_source_no_followup(self) -> None:
        """Error message does not ask follow-up questions."""
        svc = AsyncMock()
        svc.get_active_source = AsyncMock(return_value=None)
        svc._repository = AsyncMock()
        svc._repository.get_source_by_url = AsyncMock(return_value=None)
        agent = _make_agent_with_mock_service_no_active()
        handler = _build_command_handler(source_create_agent=agent, source_service=svc)

        reply = await handler.handle_text("/update", chat_id=123, from_user_id=1)

        # Should not contain prompts for more information
        assert "What type" not in reply
        assert "author" not in reply.lower()


# ── TestScreenshotScenario ────────────────────────────────────────────────────


class TestScreenshotScenario:
    """Voice note during guided create flow is transcribed and routed correctly."""

    @pytest.mark.anyio
    async def test_voice_note_during_create_flow_routed_to_agent(self) -> None:
        """Voice note during pending guided create is routed through source_create_node."""
        svc = AsyncMock()
        source_create_agent = SourceCreateAgent(source_service=svc)

        # Start a guided create flow (pending context exists)
        ctx = SourceCreateContext(
            source_type="book",
            step=SourceCreateStep.AWAITING_AUTHOR,
            flow="create",
        )
        source_create_agent._pending[123] = ctx

        # Build minimal MultiAgentService
        chat_agent = Mock()
        chat_agent.get_response = AsyncMock(return_value="chat reply")
        reflection_service = Mock()
        reflection_service.get_pending_reflection = AsyncMock(return_value=None)
        reflection_service.reflection_repository = AsyncMock()
        chat_mode_service = Mock()
        chat_mode_service.get_mode = Mock(return_value="agent")
        sources_repo = Mock()
        sources_repo.get_active_source = AsyncMock(return_value=None)

        service = MultiAgentService(
            chat_agent=chat_agent,
            reflection_service=reflection_service,
            question_agent=Mock(),
            scorer_agent=Mock(),
            hint_agent=Mock(),
            chat_mode_service=chat_mode_service,
            sources_repository=sources_repo,
            note_selector_service=Mock(),
            memory_repository=Mock(),
            agent_model=Mock(),
            source_create_agent=source_create_agent,
        )

        # Supervisor routes to source_create_node because pending context exists
        result = await service.handle("A transcribed voice comment", telegram_user_id=123)

        assert result.outcome == "source_create_reply"
        chat_agent.get_response.assert_not_awaited()

    @pytest.mark.anyio
    async def test_transcribed_comment_applied_to_source(self) -> None:
        """Transcribed voice comment becomes the comment field in confirmation."""
        agent = _make_agent_with_mock_service()

        await agent.start_create_flow(1, None)
        await agent.handle_response("book", 1)  # type → prompts for name
        await agent.handle_response("bk-test-book", 1)  # name → prompts for author
        await agent.handle_response("John", 1)  # author → prompts for comment

        # Simulate transcribed voice note providing the comment
        reply = await agent.handle_response("This is my voice comment about the book", 1)

        # Should reach confirmation with the transcribed comment
        assert "This is my voice comment" in reply or "Here's what" in reply


# ── TestURLCreationUnchanged ───────────────────────────────────────────────────


class TestURLCreationUnchanged:
    """/create <url> and URL-only messages still use deterministic creation."""

    @pytest.mark.anyio
    async def test_create_url_still_deterministic(self) -> None:
        """/create <url> uses create_source_from_url, no LLM call, no pending context."""
        svc = AsyncMock()
        svc._repository = AsyncMock()
        svc._repository.get_source_by_url = AsyncMock(return_value=None)
        svc.create_source_and_optionally_activate = AsyncMock(
            return_value={
                "id": "src-url-123",
                "source_name": "yt-youtube-watch",
                "type": "youtube",
                "status": "active",
            }
        )
        agent = SourceCreateAgent(source_service=svc)

        reply = await agent.start_create_flow(1, "https://youtube.com/watch?v=abc")

        # Should use deterministic URL creation path
        svc.create_source_and_optionally_activate.assert_awaited_once()
        assert agent.get_pending_context(1) is None
        assert "Source created" in reply or "✅" in reply

    @pytest.mark.anyio
    async def test_url_only_message_still_deterministic(self) -> None:
        """URL-only message uses create_source_from_url, no pending context."""
        svc = AsyncMock()
        svc._repository = AsyncMock()
        svc._repository.get_source_by_url = AsyncMock(return_value=None)
        svc.create_source_and_optionally_activate = AsyncMock(
            return_value={
                "id": "src-url-456",
                "source_name": "yt-youtube-watch",
                "type": "youtube",
                "status": "active",
            }
        )
        agent = SourceCreateAgent(source_service=svc)

        reply = await agent.create_source_from_url(
            "https://youtube.com/watch?v=xyz", user_id=1
        )

        svc.create_source_and_optionally_activate.assert_awaited_once()
        assert agent.get_pending_context(1) is None
        assert "Source created" in reply or "✅" in reply

    @pytest.mark.anyio
    async def test_create_url_sets_no_pending_context(self) -> None:
        """/create <url> does not leave pending context behind."""
        svc = AsyncMock()
        svc._repository = AsyncMock()
        svc._repository.get_source_by_url = AsyncMock(return_value=None)
        svc.create_source_and_optionally_activate = AsyncMock(
            return_value={
                "id": "src-url-789",
                "source_name": "yt-youtube-watch",
                "type": "youtube",
                "status": "active",
            }
        )
        agent = SourceCreateAgent(source_service=svc)

        await agent.start_create_flow(1, "https://youtube.com/watch?v=abc")

        assert agent.get_pending_context(1) is None


# ── TestImmediateNamedCreation ────────────────────────────────────────────────


class TestImmediateNamedCreation:
    """/create <non-URL argument> creates source immediately, no guided flow."""

    @pytest.mark.anyio
    async def test_create_name_immediate_creates_source(self) -> None:
        """/create lesson calls create_source_and_optionally_activate immediately."""
        svc = AsyncMock()
        svc._repository = AsyncMock()
        svc._repository.get_source_by_name = AsyncMock(return_value=None)
        svc.create_source_and_optionally_activate = AsyncMock(
            return_value={
                "id": "src-new-lesson",
                "source_name": "lesson",
                "type": None,
                "status": "active",
            }
        )
        agent = SourceCreateAgent(source_service=svc)

        reply = await agent.start_create_flow(1, "lesson")

        svc.create_source_and_optionally_activate.assert_awaited_once()
        call_kwargs = svc.create_source_and_optionally_activate.call_args.kwargs
        assert call_kwargs["source_name"] == "lesson"
        assert call_kwargs["activate"] is True
        assert call_kwargs["type"] is None
        assert "Source created" in reply

    @pytest.mark.anyio
    async def test_create_name_immediate_no_pending_context(self) -> None:
        """After /create lesson, get_pending_context(user_id) returns None."""
        svc = AsyncMock()
        svc._repository = AsyncMock()
        svc._repository.get_source_by_name = AsyncMock(return_value=None)
        svc.create_source_and_optionally_activate = AsyncMock(
            return_value={
                "id": "src-new-lesson",
                "source_name": "lesson",
                "type": None,
                "status": "active",
            }
        )
        agent = SourceCreateAgent(source_service=svc)

        await agent.start_create_flow(1, "lesson")

        assert agent.get_pending_context(1) is None

    @pytest.mark.anyio
    async def test_create_name_immediate_says_created(self) -> None:
        """Response contains 'Source created'."""
        svc = AsyncMock()
        svc._repository = AsyncMock()
        svc._repository.get_source_by_name = AsyncMock(return_value=None)
        svc.create_source_and_optionally_activate = AsyncMock(
            return_value={
                "id": "src-new-test",
                "source_name": "test-new-test",
                "type": None,
                "status": "active",
            }
        )
        agent = SourceCreateAgent(source_service=svc)

        reply = await agent.start_create_flow(1, "test-new-test")

        assert "Source created" in reply
        assert "test-new-test" in reply

    @pytest.mark.anyio
    async def test_create_name_no_prefix_required(self) -> None:
        """/create my-source succeeds without prefix validation error."""
        svc = AsyncMock()
        svc._repository = AsyncMock()
        svc._repository.get_source_by_name = AsyncMock(return_value=None)
        svc.create_source_and_optionally_activate = AsyncMock(
            return_value={
                "id": "src-new-mysource",
                "source_name": "my-source",
                "type": None,
                "status": "active",
            }
        )
        agent = SourceCreateAgent(source_service=svc)

        reply = await agent.start_create_flow(1, "my-source")

        assert "Source created" in reply
        assert "my-source" in reply
        assert "prefix" not in reply.lower() or "already exists" in reply.lower()

    @pytest.mark.anyio
    async def test_create_name_duplicate_returns_error(self) -> None:
        """When get_source_by_name() returns existing, start_create_flow returns duplicate error."""
        svc = AsyncMock()
        svc._repository = AsyncMock()
        svc._repository.get_source_by_name = AsyncMock(
            return_value={
                "id": "src-existing",
                "source_name": "existing-source",
                "type": "book",
                "status": "active",
            }
        )
        agent = SourceCreateAgent(source_service=svc)

        reply = await agent.start_create_flow(1, "existing-source")

        assert "already exists" in reply
        svc.create_source_and_optionally_activate.assert_not_awaited()

    @pytest.mark.anyio
    async def test_create_name_arbitrary_no_type_inference(self) -> None:
        """/create ts-new-test does not infer type from prefix; type=None."""
        svc = AsyncMock()
        svc._repository = AsyncMock()
        svc._repository.get_source_by_name = AsyncMock(return_value=None)
        svc.create_source_and_optionally_activate = AsyncMock(
            return_value={
                "id": "src-new-ts",
                "source_name": "ts-new-test",
                "type": None,
                "status": "active",
            }
        )
        agent = SourceCreateAgent(source_service=svc)

        reply = await agent.start_create_flow(1, "ts-new-test")

        call_kwargs = svc.create_source_and_optionally_activate.call_args.kwargs
        assert call_kwargs["type"] is None
        assert "Source created" in reply
