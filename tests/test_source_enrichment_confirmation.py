"""Tests for intention-based source enrichment confirmation flow.

Replaces the old keyword-matching confirmation tests with LLM-driven
intention-based tests. All tests mock _call_llm to return controlled
JSON responses.
"""

from __future__ import annotations

import json
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


def _make_llm_response(
    reply: str = "",
    fields: dict | None = None,
    intention: str = "capture",
) -> str:
    """Build a JSON string that the LLM would return."""
    if fields is None:
        fields = {}
    return json.dumps({
        "reply": reply,
        "fields": fields,
        "intention": intention,
    })


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


# ── First-interaction capture (T1, T2, T3) ───────────────────────────────────


class TestFirstInteractionCapture:
    """Tests for first-interaction capture — all fields from one message."""

    @pytest.mark.anyio
    async def test_t1_update_captures_all_fields_from_first_message(self) -> None:
        """T1: /update flow — user sends author + comment in one message.
        LLM returns intention='capture' with both fields. Agent shows summary,
        does NOT call update_source().
        """
        agent = _make_agent_with_mock_service()
        agent._call_llm = Mock(return_value=_make_llm_response(
            reply="Here's what I captured:\n👤 Author: Javier Maza\n💬 Comment: entrevista sobre el fin del aprendizaje",
            fields={"source_name": None, "type": None, "author": "Javier Maza", "comment": "entrevista sobre el fin del aprendizaje"},
            intention="capture",
        ))
        source = {
            "id": "src-1",
            "source_name": "yt-test-video",
            "type": "youtube",
            "url": "https://youtube.com/watch?v=abc",
        }
        await agent.start_enrich_flow(1, source)

        reply = await agent.handle_response(
            "cambia el autor a Javier Maza y comentario: entrevista sobre el fin del aprendizaje",
            user_id=1,
        )

        # Should show summary with author and comment
        assert "Javier Maza" in reply
        assert "entrevista" in reply.lower()
        # Should NOT have called update_source
        agent._source_service.update_source.assert_not_awaited()
        # Pending context should still exist
        assert agent.get_pending_context(1) is not None
        # Context should have been updated
        ctx = agent.get_pending_context(1)
        assert ctx.author == "Javier Maza"
        assert ctx.comment == "entrevista sobre el fin del aprendizaje"

    @pytest.mark.anyio
    async def test_t2_create_captures_all_fields_from_first_message(self) -> None:
        """T2: /create guided flow — user sends type, name, author, comment in one message.
        LLM returns intention='capture' with all 4 fields.
        """
        agent = _make_agent_with_mock_service()
        agent._call_llm = Mock(return_value=_make_llm_response(
            reply="Here's what I captured:\n📝 Name: bk-parasitic-minds\n📎 Type: book\n👤 Author: Pablo Malo\n💬 Comment: about parasitic minds",
            fields={"source_name": "bk-parasitic-minds", "type": "book", "author": "Pablo Malo", "comment": "about parasitic minds"},
            intention="capture",
        ))
        await agent.start_create_flow(1, None)

        reply = await agent.handle_response(
            "I want to create a book source called bk-parasitic-minds by Pablo Malo, it's about parasitic minds",
            user_id=1,
        )

        # Should show summary with all 4 fields
        assert "bk-parasitic-minds" in reply
        assert "Pablo Malo" in reply
        # Should NOT have created yet
        agent._source_service.create_source_and_optionally_activate.assert_not_awaited()
        # Context should have been updated
        ctx = agent.get_pending_context(1)
        assert ctx.source_name == "bk-parasitic-minds"
        assert ctx.type == "book"
        assert ctx.author == "Pablo Malo"
        assert ctx.comment == "about parasitic minds"

    @pytest.mark.anyio
    async def test_t3_ambiguous_message_returns_ask_intention(self) -> None:
        """T3: /update flow — user sends only 'hi'. LLM returns intention='ask'.
        Agent returns the LLM reply, does NOT save.
        """
        agent = _make_agent_with_mock_service()
        agent._call_llm = Mock(return_value=_make_llm_response(
            reply="What would you like to update?",
            fields={"source_name": None, "type": None, "author": None, "comment": None},
            intention="ask",
        ))
        source = {
            "id": "src-1",
            "source_name": "yt-test-video",
            "type": "youtube",
            "url": "https://youtube.com/watch?v=abc",
        }
        await agent.start_enrich_flow(1, source)

        reply = await agent.handle_response("hi", user_id=1)

        assert "What would you like to update" in reply
        agent._source_service.update_source.assert_not_awaited()
        assert agent.get_pending_context(1) is not None


# ── Multilingual approval detection (T4, T5, T6, T7) ─────────────────────────


class TestMultilingualApproval:
    """Tests for multilingual approval detection via LLM intention='apply'."""

    @pytest.mark.anyio
    async def test_t4_spanish_si_saves_immediately(self) -> None:
        """T4: After summary shown, user sends 'si'. LLM returns intention='apply'.
        Agent calls update_source(), returns 'We are now in note mode.', clears pending.
        """
        agent = _make_agent_with_mock_service()
        source = {
            "id": "src-1",
            "source_name": "yt-test-video",
            "type": "youtube",
            "url": "https://youtube.com/watch?v=abc",
        }
        await agent.start_enrich_flow(1, source)

        # First message: capture fields
        agent._call_llm = Mock(return_value=_make_llm_response(
            reply="Here's what I captured:\n👤 Author: John",
            fields={"author": "John"},
            intention="capture",
        ))
        await agent.handle_response("author is John", user_id=1)

        # Second message: approval in Spanish
        agent._call_llm = Mock(return_value=_make_llm_response(
            reply="✅ Saved! We are now in note mode.",
            fields={"author": "John"},
            intention="apply",
        ))
        reply = await agent.handle_response("si", user_id=1)

        assert "We are now in note mode" in reply
        agent._source_service.update_source.assert_awaited_once()
        assert agent.get_pending_context(1) is None

    @pytest.mark.anyio
    async def test_t5_mixed_spanish_english_saves_immediately(self) -> None:
        """T5: After summary shown, user sends 'claro, go ahead' (mixed).
        LLM returns intention='apply'. Agent saves immediately.
        """
        agent = _make_agent_with_mock_service()
        source = {
            "id": "src-1",
            "source_name": "yt-test-video",
            "type": "youtube",
            "url": "https://youtube.com/watch?v=abc",
        }
        await agent.start_enrich_flow(1, source)

        agent._call_llm = Mock(return_value=_make_llm_response(
            reply="✅ Saved! We are now in note mode.",
            fields={},
            intention="apply",
        ))
        reply = await agent.handle_response("claro, go ahead", user_id=1)

        assert "We are now in note mode" in reply
        agent._source_service.update_source.assert_awaited_once()

    @pytest.mark.anyio
    async def test_t6_indirect_approval_saves_immediately(self) -> None:
        """T6: After summary shown, user sends 'no, I don't care, just save it'.
        LLM returns intention='apply'. Agent saves immediately.
        """
        agent = _make_agent_with_mock_service()
        source = {
            "id": "src-1",
            "source_name": "yt-test-video",
            "type": "youtube",
            "url": "https://youtube.com/watch?v=abc",
        }
        await agent.start_enrich_flow(1, source)

        agent._call_llm = Mock(return_value=_make_llm_response(
            reply="✅ Saved! We are now in note mode.",
            fields={},
            intention="apply",
        ))
        reply = await agent.handle_response("no, I don't care, just save it", user_id=1)

        assert "We are now in note mode" in reply
        agent._source_service.update_source.assert_awaited_once()

    @pytest.mark.anyio
    async def test_t7_spanish_dale_guardalo_saves_immediately(self) -> None:
        """T7: After summary shown, user sends 'dale, guardalo' (Spanish).
        LLM returns intention='apply'. Agent saves immediately.
        """
        agent = _make_agent_with_mock_service()
        source = {
            "id": "src-1",
            "source_name": "yt-test-video",
            "type": "youtube",
            "url": "https://youtube.com/watch?v=abc",
        }
        await agent.start_enrich_flow(1, source)

        agent._call_llm = Mock(return_value=_make_llm_response(
            reply="✅ Saved! We are now in note mode.",
            fields={},
            intention="apply",
        ))
        reply = await agent.handle_response("dale, guardalo", user_id=1)

        assert "We are now in note mode" in reply
        agent._source_service.update_source.assert_awaited_once()


# ── Correction via LLM fields (T8) ───────────────────────────────────────────


class TestCorrectionViaLLM:
    """Tests for correction via LLM structured fields."""

    @pytest.mark.anyio
    async def test_t8_correction_updates_field_does_not_save(self) -> None:
        """T8: After summary shown, user sends 'actually the author is Jane Doe'.
        LLM returns intention='capture' with author='Jane Doe'. Agent updates ctx.author,
        returns LLM reply, does NOT save.
        """
        agent = _make_agent_with_mock_service()
        source = {
            "id": "src-1",
            "source_name": "yt-test-video",
            "type": "youtube",
            "url": "https://youtube.com/watch?v=abc",
        }
        await agent.start_enrich_flow(1, source)

        # First: capture initial fields
        agent._call_llm = Mock(return_value=_make_llm_response(
            reply="Here's what I captured:\n👤 Author: John",
            fields={"author": "John"},
            intention="capture",
        ))
        await agent.handle_response("author is John", user_id=1)

        # Correction
        agent._call_llm = Mock(return_value=_make_llm_response(
            reply="Updated summary:\n👤 Author: Jane Doe",
            fields={"author": "Jane Doe"},
            intention="capture",
        ))
        reply = await agent.handle_response("actually the author is Jane Doe", user_id=1)

        assert "Jane Doe" in reply
        agent._source_service.update_source.assert_not_awaited()
        ctx = agent.get_pending_context(1)
        assert ctx.author == "Jane Doe"


# ── LLM failure (T9, T10, T11) ───────────────────────────────────────────────


class TestLLMFailure:
    """Tests for LLM failure graceful error handling."""

    @pytest.mark.anyio
    async def test_t9_empty_llm_response_returns_graceful_error(self) -> None:
        """T9: LLM returns empty string. Agent returns graceful error,
        pending context stays alive.
        """
        agent = _make_agent_with_mock_service()
        agent._call_llm = Mock(return_value="")
        source = {
            "id": "src-1",
            "source_name": "yt-test-video",
            "type": "youtube",
            "url": "https://youtube.com/watch?v=abc",
        }
        await agent.start_enrich_flow(1, source)

        reply = await agent.handle_response("some message", user_id=1)

        assert "trouble processing" in reply.lower() or "try again" in reply.lower()
        assert agent.get_pending_context(1) is not None

    @pytest.mark.anyio
    async def test_t10_unparseable_text_returns_graceful_error(self) -> None:
        """T10: LLM returns unparseable text (no JSON block). Agent returns
        graceful error, pending context stays alive.
        """
        agent = _make_agent_with_mock_service()
        agent._call_llm = Mock(return_value="Just some text without JSON")
        source = {
            "id": "src-1",
            "source_name": "yt-test-video",
            "type": "youtube",
            "url": "https://youtube.com/watch?v=abc",
        }
        await agent.start_enrich_flow(1, source)

        reply = await agent.handle_response("some message", user_id=1)

        assert "trouble processing" in reply.lower() or "try again" in reply.lower()
        assert agent.get_pending_context(1) is not None

    @pytest.mark.anyio
    async def test_t11_json_without_intention_returns_graceful_error(self) -> None:
        """T11: LLM returns JSON without 'intention' key. Agent returns
        graceful error, pending context stays alive.
        """
        agent = _make_agent_with_mock_service()
        agent._call_llm = Mock(return_value='{"reply": "hello", "fields": {}}')
        source = {
            "id": "src-1",
            "source_name": "yt-test-video",
            "type": "youtube",
            "url": "https://youtube.com/watch?v=abc",
        }
        await agent.start_enrich_flow(1, source)

        reply = await agent.handle_response("some message", user_id=1)

        assert "trouble processing" in reply.lower() or "try again" in reply.lower()
        assert agent.get_pending_context(1) is not None


# ── Validation (T13, T14) ────────────────────────────────────────────────────


class TestValidation:
    """Tests for field validation in _handle_llm_response."""

    @pytest.mark.anyio
    async def test_t13_invalid_name_prefix_returns_error(self) -> None:
        """T13: LLM returns source_name without valid prefix. Agent returns
        error message about valid prefixes, does NOT save.
        """
        agent = _make_agent_with_mock_service()
        agent._call_llm = Mock(return_value=_make_llm_response(
            reply="Here's the name",
            fields={"source_name": "invalid-name-no-prefix"},
            intention="capture",
        ))
        source = {
            "id": "src-1",
            "source_name": "yt-test-video",
            "type": "youtube",
            "url": "https://youtube.com/watch?v=abc",
        }
        await agent.start_enrich_flow(1, source)

        reply = await agent.handle_response("change name to invalid-name-no-prefix", user_id=1)

        assert "prefix" in reply.lower()
        agent._source_service.update_source.assert_not_awaited()

    @pytest.mark.anyio
    async def test_t14_invalid_type_returns_error(self) -> None:
        """T14: LLM returns invalid type. Agent returns error message about
        valid types, does NOT save.
        """
        agent = _make_agent_with_mock_service()
        agent._call_llm = Mock(return_value=_make_llm_response(
            reply="Here's the type",
            fields={"type": "lesson"},
            intention="capture",
        ))
        source = {
            "id": "src-1",
            "source_name": "yt-test-video",
            "type": "youtube",
            "url": "https://youtube.com/watch?v=abc",
        }
        await agent.start_enrich_flow(1, source)

        reply = await agent.handle_response("change type to lesson", user_id=1)

        assert "invalid" in reply.lower() or "lesson" in reply.lower()
        agent._source_service.update_source.assert_not_awaited()


# ── Deletion verification (T15, T16, T17, T18, T19) ──────────────────────────


class TestDeletionVerification:
    """Tests verifying that old keyword-matching code has been removed."""

    def test_t15_fallback_handle_does_not_exist(self) -> None:
        """T15: _fallback_handle method does not exist."""
        agent = _make_agent_with_mock_service()
        assert not hasattr(agent, "_fallback_handle")

    def test_t15_todo_comment_exists(self) -> None:
        """T15: TODO comment exists where _fallback_handle was."""
        import inspect
        from backend.services import source_create_agent as module
        source = inspect.getsource(module)
        assert "TODO" in source
        assert "LLM provider" in source

    def test_t16_deleted_methods_do_not_exist(self) -> None:
        """T16: Old keyword-matching methods do not exist."""
        agent = _make_agent_with_mock_service()
        assert not hasattr(agent, "_handle_confirmation_step")
        assert not hasattr(agent, "_build_confirmation_summary")
        assert not hasattr(agent, "_extract_correction")
        assert not hasattr(agent, "_update_context_from_user_input")
        assert not hasattr(agent, "_handle_type_step")

    def test_t17_step_enum_has_only_two_values(self) -> None:
        """T17: SourceCreateStep enum has only AWAITING_INPUT and COMPLETE."""
        values = {s.value for s in SourceCreateStep}
        assert values == {"awaiting_input", "complete"}

    def test_t18_no_affirmative_word_sets(self) -> None:
        """T18: No Python set/dict of affirmative words exists in the file."""
        import inspect
        from backend.services import source_create_agent as module
        source = inspect.getsource(module)
        # These were the old affirmative words
        assert '"confirm", "correct", "go ahead"' not in source
        assert '"no, that\'s all"' not in source

    def test_t19_no_skip_or_apply_prompts(self) -> None:
        """T19: No string containing '(or say 'skip')' or 'Say 'apply' to save' exists."""
        import inspect
        from backend.services import source_create_agent as module
        source = inspect.getsource(module)
        assert "(or say 'skip')" not in source
        assert "Say 'apply' to save" not in source


# ── Apply behavior (T20, T21) ────────────────────────────────────────────────


class TestApplyBehavior:
    """Tests for apply intention routing."""

    @pytest.mark.anyio
    async def test_t20_apply_enrich_flow_calls_update(self) -> None:
        """T20: intention='apply' with flow='enrich' calls _apply_enrichment(),
        returns 'We are now in note mode.', clears pending context.
        """
        agent = _make_agent_with_mock_service()
        source = {
            "id": "src-1",
            "source_name": "yt-test-video",
            "type": "youtube",
            "url": "https://youtube.com/watch?v=abc",
        }
        await agent.start_enrich_flow(1, source)

        agent._call_llm = Mock(return_value=_make_llm_response(
            reply="✅ Saved! We are now in note mode.",
            fields={"author": "John"},
            intention="apply",
        ))
        reply = await agent.handle_response("yes", user_id=1)

        assert "We are now in note mode" in reply
        agent._source_service.update_source.assert_awaited_once()
        assert agent.get_pending_context(1) is None

    @pytest.mark.anyio
    async def test_t21_apply_create_flow_calls_create(self) -> None:
        """T21: intention='apply' with flow='create' calls _create_source_from_context(),
        returns creation confirmation, clears pending context.
        """
        agent = _make_agent_with_mock_service()
        await agent.start_create_flow(1, None)

        # First: capture fields
        agent._call_llm = Mock(return_value=_make_llm_response(
            reply="Here's what I captured:\n📝 Name: bk-test-book\n📎 Type: book",
            fields={"source_name": "bk-test-book", "type": "book", "author": "John"},
            intention="capture",
        ))
        await agent.handle_response("book called bk-test-book by John", user_id=1)

        # Then: apply
        agent._call_llm = Mock(return_value=_make_llm_response(
            reply="✅ Source created! We are now in note mode.",
            fields={"source_name": "bk-test-book", "type": "book", "author": "John"},
            intention="apply",
        ))
        reply = await agent.handle_response("si", user_id=1)

        assert "We are now in note mode" in reply
        agent._source_service.create_source_and_optionally_activate.assert_awaited_once()
        assert agent.get_pending_context(1) is None


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
