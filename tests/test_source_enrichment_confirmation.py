"""Tests for source enrichment decoupling — confirmation flow, ephemeral context,
new source types, type propagation, and source switch invalidation.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest

from backend.services.source_create_agent import (
    SourceCreateAgent,
    SourceCreateContext,
    SourceCreateStep,
    SOURCE_CREATE_SYSTEM_PROMPT,
    _TYPE_PREFIX_MAP,
)
from backend.services.chat_mode_service import ChatModeService
from backend.services.source_service import SourceService
from backend.services.telegram_command_handler import TelegramCommandHandler


# ── Helper factories ──────────────────────────────────────────────────────────


def _make_agent_with_mock_service() -> SourceCreateAgent:
    svc = AsyncMock()
    svc._repository = AsyncMock()
    svc._repository.get_source_by_url = AsyncMock(return_value=None)
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


# ── Confirmation flow ─────────────────────────────────────────────────────────


class TestConfirmationFlow:
    """Tests for the confirmation summary flow before persistence."""

    @pytest.mark.anyio
    async def test_no_auto_apply_after_collecting_all_fields(self) -> None:
        """Enrichment flow does NOT auto-apply when all fields have been collected."""
        agent = _make_agent_with_mock_service()
        source = {
            "id": "src-1",
            "source_name": "yt-test-video",
            "type": "youtube",
            "url": "https://youtube.com/watch?v=abc",
        }
        await agent.start_enrich_flow(1, source)
        await agent.handle_response("yes", user_id=1)  # accept name
        await agent.handle_response("John Doe", user_id=1)  # author
        reply = await agent.handle_response("Great tutorial", user_id=1)  # comment

        # Should show confirmation summary, NOT apply
        assert "Here's what I'll update" in reply
        assert "Anything else to add" in reply
        # update_source should NOT have been called
        agent._source_service.update_source.assert_not_awaited()
        # Pending context should still exist
        assert agent.get_pending_context(1) is not None

    @pytest.mark.anyio
    async def test_confirmation_summary_shows_all_fields_including_empty(self) -> None:
        """Confirmation summary shows all fields, including empty ones."""
        agent = _make_agent_with_mock_service()
        source = {
            "id": "src-1",
            "source_name": "yt-test-video",
            "type": "youtube",
            "url": "https://youtube.com/watch?v=abc",
        }
        await agent.start_enrich_flow(1, source)
        await agent.handle_response("yes", user_id=1)  # accept name
        await agent.handle_response("skip", user_id=1)  # skip author
        reply = await agent.handle_response("skip", user_id=1)  # skip comment

        assert "Name: yt-test-video" in reply
        assert "Type: youtube" in reply
        assert "URL: https://youtube.com/watch?v=abc" in reply
        assert "Author: (empty)" in reply
        assert "Comment: (empty)" in reply

    @pytest.mark.anyio
    async def test_affirmative_confirm_applies_changes(self) -> None:
        """Clear affirmative response applies changes and clears pending context."""
        agent = _make_agent_with_mock_service()
        source = {
            "id": "src-1",
            "source_name": "yt-test-video",
            "type": "youtube",
            "url": "https://youtube.com/watch?v=abc",
        }
        await agent.start_enrich_flow(1, source)
        await agent.handle_response("yes", user_id=1)
        await agent.handle_response("John Doe", user_id=1)
        await agent.handle_response("Great tutorial", user_id=1)

        # Confirm
        reply = await agent.handle_response("confirm", user_id=1)

        assert "Source updated" in reply
        assert agent.get_pending_context(1) is None
        agent._source_service.update_source.assert_awaited_once()

    @pytest.mark.anyio
    async def test_thats_all_applies_changes(self) -> None:
        """'that's all' response applies changes."""
        agent = _make_agent_with_mock_service()
        source = {
            "id": "src-1",
            "source_name": "yt-test-video",
            "type": "youtube",
            "url": "https://youtube.com/watch?v=abc",
        }
        await agent.start_enrich_flow(1, source)
        await agent.handle_response("yes", user_id=1)
        await agent.handle_response("skip", user_id=1)
        await agent.handle_response("skip", user_id=1)

        reply = await agent.handle_response("that's all", user_id=1)
        assert "Source updated" in reply
        agent._source_service.update_source.assert_awaited_once()

    @pytest.mark.anyio
    async def test_no_thats_all_applies_changes(self) -> None:
        """'no, that's all' response to 'anything else?' prompt applies changes."""
        agent = _make_agent_with_mock_service()
        source = {
            "id": "src-1",
            "source_name": "yt-test-video",
            "type": "youtube",
            "url": "https://youtube.com/watch?v=abc",
        }
        await agent.start_enrich_flow(1, source)
        await agent.handle_response("yes", user_id=1)
        await agent.handle_response("skip", user_id=1)
        await agent.handle_response("skip", user_id=1)

        reply = await agent.handle_response("no, that's all", user_id=1)
        assert "Source updated" in reply
        agent._source_service.update_source.assert_awaited_once()

    @pytest.mark.anyio
    async def test_correction_updates_field_and_reshows_summary(self) -> None:
        """Correction response updates field and re-shows summary."""
        agent = _make_agent_with_mock_service()
        source = {
            "id": "src-1",
            "source_name": "yt-test-video",
            "type": "youtube",
            "url": "https://youtube.com/watch?v=abc",
        }
        await agent.start_enrich_flow(1, source)
        await agent.handle_response("yes", user_id=1)
        await agent.handle_response("John Doe", user_id=1)
        await agent.handle_response("Great tutorial", user_id=1)

        # Correction
        reply = await agent.handle_response("author: Jane Smith", user_id=1)

        # Should show revised summary
        assert "Here's what I'll update" in reply
        assert "Jane Smith" in reply
        # Should NOT have applied
        agent._source_service.update_source.assert_not_awaited()
        # Context should still be pending
        assert agent.get_pending_context(1) is not None

    @pytest.mark.anyio
    async def test_ambiguous_no_triggers_clarification(self) -> None:
        """Ambiguous bare 'no' triggers clarification question."""
        agent = _make_agent_with_mock_service()
        source = {
            "id": "src-1",
            "source_name": "yt-test-video",
            "type": "youtube",
            "url": "https://youtube.com/watch?v=abc",
        }
        await agent.start_enrich_flow(1, source)
        await agent.handle_response("yes", user_id=1)
        await agent.handle_response("skip", user_id=1)
        await agent.handle_response("skip", user_id=1)

        reply = await agent.handle_response("no", user_id=1)

        # Should ask for clarification, NOT apply
        assert "Just to confirm" in reply
        agent._source_service.update_source.assert_not_awaited()
        assert agent.get_pending_context(1) is not None

    @pytest.mark.anyio
    async def test_apply_returns_note_mode_message(self) -> None:
        """On apply, message includes 'We are now in note mode.'"""
        agent = _make_agent_with_mock_service()
        source = {
            "id": "src-1",
            "source_name": "yt-test-video",
            "type": "youtube",
            "url": "https://youtube.com/watch?v=abc",
        }
        await agent.start_enrich_flow(1, source)
        await agent.handle_response("yes", user_id=1)
        await agent.handle_response("skip", user_id=1)
        await agent.handle_response("skip", user_id=1)

        reply = await agent.handle_response("apply", user_id=1)

        assert "We are now in note mode." in reply

    @pytest.mark.anyio
    async def test_apply_does_not_mention_next_audio(self) -> None:
        """On apply, message does NOT mention what the next audio will do."""
        agent = _make_agent_with_mock_service()
        source = {
            "id": "src-1",
            "source_name": "yt-test-video",
            "type": "youtube",
            "url": "https://youtube.com/watch?v=abc",
        }
        await agent.start_enrich_flow(1, source)
        await agent.handle_response("yes", user_id=1)
        await agent.handle_response("skip", user_id=1)
        await agent.handle_response("skip", user_id=1)

        reply = await agent.handle_response("apply", user_id=1)

        assert "next audio" not in reply.lower()
        assert "next voice" not in reply.lower()

    @pytest.mark.anyio
    async def test_bare_no_does_not_apply(self) -> None:
        """Bare 'no' without context does NOT apply changes."""
        agent = _make_agent_with_mock_service()
        source = {
            "id": "src-1",
            "source_name": "yt-test-video",
            "type": "youtube",
            "url": "https://youtube.com/watch?v=abc",
        }
        await agent.start_enrich_flow(1, source)
        await agent.handle_response("yes", user_id=1)
        await agent.handle_response("skip", user_id=1)
        await agent.handle_response("skip", user_id=1)

        await agent.handle_response("no", user_id=1)

        # Should NOT have applied
        agent._source_service.update_source.assert_not_awaited()


# ── Ephemeral context ─────────────────────────────────────────────────────────


class TestEphemeralContext:
    """Tests for ephemeral pending context management."""

    @pytest.mark.anyio
    async def test_pending_context_is_in_memory_only(self) -> None:
        """Pending context is stored in a plain dict (no DB persistence)."""
        agent = _make_agent_with_mock_service()
        assert isinstance(agent._pending, dict)

    @pytest.mark.anyio
    async def test_switch_clears_pending_context(self) -> None:
        """Switching source via /switch clears pending update context."""
        agent = _make_agent_with_mock_service()
        source = {
            "id": "src-1",
            "source_name": "yt-test-video",
            "type": "youtube",
            "url": "https://youtube.com/watch?v=abc",
        }
        await agent.start_enrich_flow(456, source)
        assert agent.get_pending_context(456) is not None

        # Simulate /switch clearing pending
        agent.clear_pending(456)
        assert agent.get_pending_context(456) is None

    @pytest.mark.anyio
    async def test_fresh_update_reads_current_state(self) -> None:
        """Fresh /update after switch reads current source state (not stale)."""
        agent = _make_agent_with_mock_service()

        # First enrichment
        source1 = {
            "id": "src-1",
            "source_name": "yt-first-source",
            "type": "youtube",
            "url": "https://youtube.com/watch?v=abc",
        }
        await agent.start_enrich_flow(1, source1)
        ctx1 = agent.get_pending_context(1)
        assert ctx1.source_id == "src-1"

        # Switch to different source and start new enrichment
        source2 = {
            "id": "src-2",
            "source_name": "bk-second-source",
            "type": "book",
            "url": None,
        }
        await agent.start_enrich_flow(1, source2)
        ctx2 = agent.get_pending_context(1)
        assert ctx2.source_id == "src-2"
        assert ctx2.source_name == "bk-second-source"

    @pytest.mark.anyio
    async def test_inline_keyboard_switch_clears_pending(self) -> None:
        """Switching source via inline keyboard clears pending update context."""
        agent = _make_agent_with_mock_service()
        source = {
            "id": "src-1",
            "source_name": "yt-test-video",
            "type": "youtube",
        }
        await agent.start_enrich_flow(1, source)
        assert agent.get_pending_context(1) is not None

        # Simulate inline keyboard switch clearing pending
        agent.clear_pending(1)
        assert agent.get_pending_context(1) is None


# ── New source types ──────────────────────────────────────────────────────────


class TestNewSourceTypes:
    """Tests for test and other source types."""

    def test_test_type_in_valid_source_types(self) -> None:
        from backend.models.source import VALID_SOURCE_TYPES
        assert "test" in VALID_SOURCE_TYPES

    def test_other_type_in_valid_source_types(self) -> None:
        from backend.models.source import VALID_SOURCE_TYPES
        assert "other" in VALID_SOURCE_TYPES

    def test_ts_prefix_in_valid_prefixes(self) -> None:
        from backend.models.source import VALID_PREFIXES
        assert "ts-" in VALID_PREFIXES

    def test_ot_prefix_in_valid_prefixes(self) -> None:
        from backend.models.source import VALID_PREFIXES
        assert "ot-" in VALID_PREFIXES

    def test_test_type_in_type_prefix_map(self) -> None:
        assert _TYPE_PREFIX_MAP["test"] == "ts"

    def test_other_type_in_type_prefix_map(self) -> None:
        assert _TYPE_PREFIX_MAP["other"] == "ot"

    def test_test_type_accepted_in_create_request(self) -> None:
        from backend.models.source import SourceCreateByAgentRequest
        req = SourceCreateByAgentRequest(
            source_name="ts-experiment-one",
            type="test",
        )
        assert req.type == "test"

    def test_other_type_accepted_in_create_request(self) -> None:
        from backend.models.source import SourceCreateByAgentRequest
        req = SourceCreateByAgentRequest(
            source_name="ot-misc-thing",
            type="other",
        )
        assert req.type == "other"

    def test_invalid_type_lesson_rejected(self) -> None:
        from backend.models.source import SourceCreateByAgentRequest
        import pydantic
        with pytest.raises(pydantic.ValidationError):
            SourceCreateByAgentRequest(
                source_name="ts-experiment-one",
                type="lesson",
            )

    def test_ts_prefix_accepted_in_name_validation(self) -> None:
        from backend.models.source import SourceCreateByAgentRequest
        req = SourceCreateByAgentRequest(
            source_name="ts-my-test",
            type="test",
        )
        assert req.source_name == "ts-my-test"

    def test_ot_prefix_accepted_in_name_validation(self) -> None:
        from backend.models.source import SourceCreateByAgentRequest
        req = SourceCreateByAgentRequest(
            source_name="ot-misc-thing",
            type="other",
        )
        assert req.source_name == "ot-misc-thing"

    def test_system_prompt_includes_test_and_other(self) -> None:
        assert "test" in SOURCE_CREATE_SYSTEM_PROMPT
        assert "other" in SOURCE_CREATE_SYSTEM_PROMPT
        assert "ts-" in SOURCE_CREATE_SYSTEM_PROMPT
        assert "ot-" in SOURCE_CREATE_SYSTEM_PROMPT


# ── Type propagation ──────────────────────────────────────────────────────────


class TestTypePropagation:
    """Tests for type field propagation through update flow."""

    def test_source_update_request_accepts_type(self) -> None:
        from backend.models.source import SourceUpdateRequest
        req = SourceUpdateRequest(type="youtube")
        assert req.type == "youtube"

    def test_source_update_request_accepts_test_type(self) -> None:
        from backend.models.source import SourceUpdateRequest
        req = SourceUpdateRequest(type="test")
        assert req.type == "test"

    def test_source_update_request_rejects_invalid_type(self) -> None:
        from backend.models.source import SourceUpdateRequest
        import pydantic
        with pytest.raises(pydantic.ValidationError):
            SourceUpdateRequest(type="lesson")

    def test_source_update_request_type_optional(self) -> None:
        from backend.models.source import SourceUpdateRequest
        req = SourceUpdateRequest()
        assert req.type is None

    @pytest.mark.anyio
    async def test_handle_update_action_parses_type(self) -> None:
        """_handle_update_action() parses type from action JSON."""
        agent = _make_agent_with_mock_service()
        source = {
            "id": "src-1",
            "source_name": "yt-test-video",
            "type": "youtube",
            "url": "https://youtube.com/watch?v=abc",
        }
        await agent.start_enrich_flow(1, source)

        # Simulate LLM returning JSON with type
        action = {
            "action": "update_source",
            "source_name": "cr-new-course",
            "type": "course",
            "author": "John",
            "comment": "Test",
        }
        reply = await agent._handle_update_action(action, 1, agent.get_pending_context(1))

        # Should show confirmation (not apply)
        assert "Here's what I'll update" in reply
        ctx = agent.get_pending_context(1)
        assert ctx.type == "course"

    @pytest.mark.anyio
    async def test_update_source_persists_type(self) -> None:
        """update_source() passes type through to repository."""
        repo = AsyncMock()
        repo.update_source = AsyncMock(return_value={"id": "src-1"})
        svc = SourceService(repository=repo)

        await svc.update_source("src-1", type="test")

        repo.update_source.assert_awaited_once_with(
            source_id="src-1",
            source_name=None,
            author=None,
            comment=None,
            type="test",
        )

    @pytest.mark.anyio
    async def test_type_change_triggers_name_prefix_update(self) -> None:
        """When type changes, name prefix is re-derived from new type."""
        agent = _make_agent_with_mock_service()
        source = {
            "id": "src-1",
            "source_name": "yt-test-video",
            "type": "youtube",
            "url": "https://youtube.com/watch?v=abc",
        }
        await agent.start_enrich_flow(1, source)

        # Set up context with type change
        ctx = agent.get_pending_context(1)
        ctx.source_name = "yt-test-video"
        ctx.type = "course"

        reply = await agent._apply_enrichment(1, ctx)

        # update_source should be called with new name prefix
        call_kwargs = agent._source_service.update_source.call_args.kwargs
        assert call_kwargs.get("type") == "course"
        # Name should have been re-prefixed from yt- to cr-
        assert call_kwargs.get("source_name") == "cr-test-video"


# ── Source switch invalidation ────────────────────────────────────────────────


class TestSourceSwitchInvalidation:
    """Tests for clearing pending context on source switch."""

    @pytest.mark.anyio
    async def test_switch_command_clears_pending(self) -> None:
        """/switch command clears pending update context."""
        agent = _make_agent_with_mock_service()
        source = {
            "id": "src-1",
            "source_name": "yt-test-video",
            "type": "youtube",
        }
        await agent.start_enrich_flow(456, source)
        assert agent.get_pending_context(456) is not None

        # Build command handler with the agent
        svc = AsyncMock()
        svc.get_active_source = AsyncMock(return_value=None)
        svc._repository = AsyncMock()
        svc._repository.get_source_by_name = AsyncMock(
            return_value={"id": "src-2", "source_name": "bk-other"}
        )
        svc.activate_source_by_id = AsyncMock(return_value={"id": "src-2"})
        handler = _build_command_handler(source_create_agent=agent, source_service=svc)

        await handler.handle_text("/switch bk-other", chat_id=123, from_user_id=456)

        assert agent.get_pending_context(456) is None

    @pytest.mark.anyio
    async def test_default_command_clears_pending(self) -> None:
        """/default command clears pending update context."""
        agent = _make_agent_with_mock_service()
        source = {
            "id": "src-1",
            "source_name": "yt-test-video",
            "type": "youtube",
        }
        await agent.start_enrich_flow(456, source)
        assert agent.get_pending_context(456) is not None

        svc = AsyncMock()
        svc._repository = AsyncMock()
        svc._repository.get_source_by_name = AsyncMock(
            return_value={"id": "default-id", "source_name": "default"}
        )
        svc.activate_source_by_id = AsyncMock(return_value={"id": "default-id"})
        handler = _build_command_handler(source_create_agent=agent, source_service=svc)

        await handler.handle_text("/default", chat_id=123, from_user_id=456)

        assert agent.get_pending_context(456) is None
