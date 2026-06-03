"""Unit tests for MultiAgentService."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, Mock

import pytest

from backend.models.agent import AgentResult, MultiAgentResult
from backend.services.multi_agent_service import MultiAgentService


# -------------------------------------------------------------------------- #
#  Helpers
# -------------------------------------------------------------------------- #

def _mock_model(response_content: str = "") -> Mock:
    """Build a minimal mock ChatOpenAI that returns configurable content."""
    model = Mock()
    response = Mock()
    response.content = response_content
    model.invoke = Mock(return_value=response)
    return model


async def _mock_note_response(reflection_repository: Mock, note_id: str, note_text: str) -> None:
    """Stub the client's table().select().eq().maybe_single().execute() chain."""
    note_data = {"id": note_id, "raw_text": note_text, "clean_text": note_text}
    note_response = Mock()
    note_response.data = note_data
    note_response.error = None
    eq_query = Mock()
    eq_query.select = Mock(return_value=eq_query)
    eq_query.eq = Mock(return_value=eq_query)
    eq_query.maybe_single = Mock(return_value=eq_query)
    eq_query.execute = AsyncMock(return_value=note_response)
    table = Mock()
    table.select = Mock(return_value=eq_query)
    reflection_repository._client = Mock()
    reflection_repository._client.table = Mock(return_value=table)


# -------------------------------------------------------------------------- #
#  Fixtures
# -------------------------------------------------------------------------- #

@pytest.fixture
def chat_agent_service() -> Mock:
    agent = Mock()
    agent.get_response = AsyncMock(return_value="Hi from chat!")
    return agent


@pytest.fixture
def reflection_service() -> Mock:
    svc = Mock()
    svc.get_pending_reflection = AsyncMock(return_value=None)
    svc.cancel_pending_reflection = AsyncMock()
    svc.reflection_repository = AsyncMock()
    return svc


@pytest.fixture
def question_agent() -> Mock:
    agent = Mock()
    agent.run = AsyncMock(
        return_value=AgentResult(
            reply="What did you learn?",
            outcome="asked",
            updates={"question_type": "reflective", "question_text": "What did you learn?"},
        )
    )
    return agent


@pytest.fixture
def scorer_agent() -> Mock:
    agent = Mock()
    agent.run = AsyncMock(
        return_value=AgentResult(
            reply="Good recall!",
            outcome="scored",
            updates={"rating": 8},
        )
    )
    return agent


@pytest.fixture
def hint_agent() -> Mock:
    agent = Mock()
    agent.run = AsyncMock(
        return_value=AgentResult(reply="a clue", outcome="hinted")
    )
    return agent


@pytest.fixture
def chat_mode_service() -> Mock:
    svc = Mock()
    svc.get_mode = Mock(return_value="agent")
    svc.set_mode = Mock()
    return svc


@pytest.fixture
def sources_repository() -> Mock:
    svc = Mock()
    svc.get_active_source = AsyncMock(
        return_value={"id": "source-1", "source_name": "test source"}
    )
    return svc


@pytest.fixture
def note_selector_service() -> Mock:
    svc = Mock()
    svc.pick_note = AsyncMock(
        return_value={
            "id": "note-00000000-0000-0000-0000-000000000001",
            "raw_text": "This is the note text.",
            "clean_text": "This is the note text.",
        }
    )
    return svc


@pytest.fixture
def memory_repository() -> Mock:
    return Mock()


@pytest.fixture
def agent_model() -> Mock:
    return _mock_model()


@pytest.fixture
def reflection_repository(reflection_service: Mock) -> Mock:
    return reflection_service.reflection_repository


# -------------------------------------------------------------------------- #
#  Tests
# -------------------------------------------------------------------------- #

class TestMultiAgentService:
    """Tests for MultiAgentService.handle()."""

    @pytest.mark.anyio
    async def test_handle_in_agent_mode_routes_to_chat(
        self,
        chat_agent_service: Mock,
        reflection_service: Mock,
        question_agent: Mock,
        scorer_agent: Mock,
        hint_agent: Mock,
        chat_mode_service: Mock,
        sources_repository: Mock,
        note_selector_service: Mock,
        memory_repository: Mock,
        agent_model: Mock,
    ) -> None:
        """mode='agent' → chat_agent.get_response is called."""
        chat_mode_service.get_mode = Mock(return_value="agent")
        service = MultiAgentService(
            chat_agent=chat_agent_service,
            reflection_service=reflection_service,
            question_agent=question_agent,
            scorer_agent=scorer_agent,
            hint_agent=hint_agent,
            chat_mode_service=chat_mode_service,
            sources_repository=sources_repository,
            note_selector_service=note_selector_service,
            memory_repository=memory_repository,
            agent_model=agent_model,
        )

        result = await service.handle("hello", telegram_user_id=123)

        assert result.reply == "Hi from chat!"
        assert result.outcome == "chat_reply"
        chat_agent_service.get_response.assert_awaited_once_with(
            "hello", telegram_user_id=123
        )

    @pytest.mark.anyio
    async def test_handle_in_reflect_mode_with_no_pending_starts_reflection(
        self,
        chat_agent_service: Mock,
        reflection_service: Mock,
        question_agent: Mock,
        scorer_agent: Mock,
        hint_agent: Mock,
        chat_mode_service: Mock,
        sources_repository: Mock,
        note_selector_service: Mock,
        memory_repository: Mock,
        agent_model: Mock,
        reflection_repository: Mock,
    ) -> None:
        """mode='reflect', no pending → creates a reflection row and returns question."""
        chat_mode_service.get_mode = Mock(return_value="reflect")
        reflection_service.get_pending_reflection = AsyncMock(return_value=None)
        reflection_repository.create_reflection = AsyncMock(
            return_value={"id": "abc-123", "telegram_user_id": 123}
        )

        service = MultiAgentService(
            chat_agent=chat_agent_service,
            reflection_service=reflection_service,
            question_agent=question_agent,
            scorer_agent=scorer_agent,
            hint_agent=hint_agent,
            chat_mode_service=chat_mode_service,
            sources_repository=sources_repository,
            note_selector_service=note_selector_service,
            memory_repository=memory_repository,
            agent_model=agent_model,
        )

        result = await service.handle("start reflection", telegram_user_id=123)

        assert result.outcome == "asked"
        assert "What did you learn?" in result.reply
        reflection_repository.create_reflection.assert_awaited_once()

    @pytest.mark.anyio
    async def test_handle_in_reflect_mode_with_pending_hint_keeps_reflection_open(
        self,
        chat_agent_service: Mock,
        reflection_service: Mock,
        question_agent: Mock,
        scorer_agent: Mock,
        hint_agent: Mock,
        chat_mode_service: Mock,
        sources_repository: Mock,
        note_selector_service: Mock,
        memory_repository: Mock,
        agent_model: Mock,
        reflection_repository: Mock,
    ) -> None:
        """Pre-seeded pending + HINT intent → hint_agent.run is called."""
        chat_mode_service.get_mode = Mock(return_value="reflect")
        # Simulate pending reflection by having get_pending_reflection return an entry
        mock_entry = Mock()
        mock_entry.id = "pending-123"
        mock_entry.voice_note_id = "note-00000000-0000-0000-0000-000000000001"
        mock_entry.question_type = "reflective"
        mock_entry.question_text = "What did you learn?"
        reflection_service.get_pending_reflection = AsyncMock(return_value=mock_entry)
        # Stub the note fetch
        await _mock_note_response(
            reflection_repository,
            note_id="note-00000000-0000-0000-0000-000000000001",
            note_text="This is the note text.",
        )

        # Intent classifier returns HINT
        model = _mock_model('{"intent": "HINT", "answer_text": "give me a hint"}')
        hint_agent.run = AsyncMock(
            return_value=AgentResult(reply="Think about the beach", outcome="hinted")
        )

        service = MultiAgentService(
            chat_agent=chat_agent_service,
            reflection_service=reflection_service,
            question_agent=question_agent,
            scorer_agent=scorer_agent,
            hint_agent=hint_agent,
            chat_mode_service=chat_mode_service,
            sources_repository=sources_repository,
            note_selector_service=note_selector_service,
            memory_repository=memory_repository,
            agent_model=model,
        )

        result = await service.handle("give me a hint", telegram_user_id=123)

        assert result.outcome == "hinted"
        assert result.reply == "Think about the beach"
        hint_agent.run.assert_awaited_once()

    @pytest.mark.anyio
    async def test_handle_in_reflect_mode_with_pending_context_returns_note(
        self,
        chat_agent_service: Mock,
        reflection_service: Mock,
        question_agent: Mock,
        scorer_agent: Mock,
        hint_agent: Mock,
        chat_mode_service: Mock,
        sources_repository: Mock,
        note_selector_service: Mock,
        memory_repository: Mock,
        agent_model: Mock,
        reflection_repository: Mock,
    ) -> None:
        """Pre-seeded pending + CONTEXT intent → returns note text with banner."""
        chat_mode_service.get_mode = Mock(return_value="reflect")
        mock_entry = Mock()
        mock_entry.id = "pending-123"
        mock_entry.voice_note_id = "note-00000000-0000-0000-0000-000000000001"
        mock_entry.question_type = "reflective"
        mock_entry.question_text = "What did you learn?"
        reflection_service.get_pending_reflection = AsyncMock(return_value=mock_entry)
        await _mock_note_response(
            reflection_repository,
            note_id="note-00000000-0000-0000-0000-000000000001",
            note_text="This is the note text.",
        )

        model = _mock_model('{"intent": "CONTEXT", "answer_text": "what was that note about?"}')

        service = MultiAgentService(
            chat_agent=chat_agent_service,
            reflection_service=reflection_service,
            question_agent=question_agent,
            scorer_agent=scorer_agent,
            hint_agent=hint_agent,
            chat_mode_service=chat_mode_service,
            sources_repository=sources_repository,
            note_selector_service=note_selector_service,
            memory_repository=memory_repository,
            agent_model=model,
        )

        result = await service.handle("what was that note about?", telegram_user_id=123)

        assert result.outcome == "context_shown"
        assert "📋 Here's what the note said:" in result.reply
        assert "This is the note text." in result.reply

    @pytest.mark.anyio
    async def test_handle_in_reflect_mode_with_pending_answer_scores_and_auto_loops(
        self,
        chat_agent_service: Mock,
        reflection_service: Mock,
        question_agent: Mock,
        scorer_agent: Mock,
        hint_agent: Mock,
        chat_mode_service: Mock,
        sources_repository: Mock,
        note_selector_service: Mock,
        memory_repository: Mock,
        agent_model: Mock,
        reflection_repository: Mock,
    ) -> None:
        """Pre-seeded pending + ANSWER intent → scores, completes, and auto-queues next."""
        chat_mode_service.get_mode = Mock(return_value="reflect")
        mock_entry = Mock()
        mock_entry.id = "pending-123"
        mock_entry.voice_note_id = "note-00000000-0000-0000-0000-000000000001"
        mock_entry.question_type = "reflective"
        mock_entry.question_text = "What did you learn?"
        reflection_service.get_pending_reflection = AsyncMock(return_value=mock_entry)
        await _mock_note_response(
            reflection_repository,
            note_id="note-00000000-0000-0000-0000-000000000001",
            note_text="Note for first question.",
        )
        reflection_repository.complete_reflection = AsyncMock()

        model = _mock_model('{"intent": "ANSWER", "answer_text": "I remembered it!"}')
        scorer_agent.run = AsyncMock(
            return_value=AgentResult(reply="✅ Great recall!", outcome="scored", updates={"rating": 8})
        )
        # Second note for auto-loop
        note_selector_service.pick_note = AsyncMock(
            return_value={
                "id": "note-00000000-0000-0000-0000-000000000002",
                "raw_text": "Second note content.",
                "clean_text": "Second note content.",
            }
        )
        reflection_repository.create_reflection = AsyncMock(
            return_value={"id": "next-456", "telegram_user_id": 123}
        )

        service = MultiAgentService(
            chat_agent=chat_agent_service,
            reflection_service=reflection_service,
            question_agent=question_agent,
            scorer_agent=scorer_agent,
            hint_agent=hint_agent,
            chat_mode_service=chat_mode_service,
            sources_repository=sources_repository,
            note_selector_service=note_selector_service,
            memory_repository=memory_repository,
            agent_model=model,
        )

        result = await service.handle("I remembered it!", telegram_user_id=123)

        assert result.outcome in ("scored", "asked")
        assert "🧠 Next one:" in result.reply
        reflection_repository.complete_reflection.assert_awaited_once()

    @pytest.mark.anyio
    async def test_handle_in_reflect_mode_with_pending_answer_no_more_notes_exits_mode(
        self,
        chat_agent_service: Mock,
        reflection_service: Mock,
        question_agent: Mock,
        scorer_agent: Mock,
        hint_agent: Mock,
        chat_mode_service: Mock,
        sources_repository: Mock,
        note_selector_service: Mock,
        memory_repository: Mock,
        agent_model: Mock,
        reflection_repository: Mock,
    ) -> None:
        """ANSWER intent + pick_note returns None → exits reflect mode with no-more-notes msg."""
        chat_mode_service.get_mode = Mock(return_value="reflect")
        mock_entry = Mock()
        mock_entry.id = "pending-123"
        mock_entry.voice_note_id = "note-00000000-0000-0000-0000-000000000001"
        mock_entry.question_type = "reflective"
        mock_entry.question_text = "What did you learn?"
        reflection_service.get_pending_reflection = AsyncMock(return_value=mock_entry)
        await _mock_note_response(
            reflection_repository,
            note_id="note-00000000-0000-0000-0000-000000000001",
            note_text="Final note.",
        )
        reflection_repository.complete_reflection = AsyncMock()

        model = _mock_model('{"intent": "ANSWER", "answer_text": "my answer"}')
        scorer_agent.run = AsyncMock(
            return_value=AgentResult(reply="Good!", outcome="scored", updates={"rating": 7})
        )
        note_selector_service.pick_note = AsyncMock(return_value=None)  # No more notes

        service = MultiAgentService(
            chat_agent=chat_agent_service,
            reflection_service=reflection_service,
            question_agent=question_agent,
            scorer_agent=scorer_agent,
            hint_agent=hint_agent,
            chat_mode_service=chat_mode_service,
            sources_repository=sources_repository,
            note_selector_service=note_selector_service,
            memory_repository=memory_repository,
            agent_model=model,
        )

        result = await service.handle("my answer", telegram_user_id=123)

        assert result.outcome == "exhausted"
        assert "🎉" in result.reply or "reviewed all notes" in result.reply.lower()
        chat_mode_service.set_mode.assert_called_with("agent")

    @pytest.mark.anyio
    async def test_intent_classifier_parse_failure_defaults_to_answer(
        self,
        chat_agent_service: Mock,
        reflection_service: Mock,
        question_agent: Mock,
        scorer_agent: Mock,
        hint_agent: Mock,
        chat_mode_service: Mock,
        sources_repository: Mock,
        note_selector_service: Mock,
        memory_repository: Mock,
        agent_model: Mock,
        reflection_repository: Mock,
    ) -> None:
        """Invalid JSON from intent classifier → routes to _answer (scorer_agent)."""
        chat_mode_service.get_mode = Mock(return_value="reflect")
        mock_entry = Mock()
        mock_entry.id = "pending-123"
        mock_entry.voice_note_id = "note-00000000-0000-0000-0000-000000000001"
        mock_entry.question_type = "reflective"
        mock_entry.question_text = "What did you learn?"
        reflection_service.get_pending_reflection = AsyncMock(return_value=mock_entry)
        await _mock_note_response(
            reflection_repository,
            note_id="note-00000000-0000-0000-0000-000000000001",
            note_text="A note.",
        )
        reflection_repository.complete_reflection = AsyncMock()

        # Intent classifier returns invalid JSON
        model = _mock_model("oops this is not json")
        scorer_agent.run = AsyncMock(
            return_value=AgentResult(reply="Scored!", outcome="scored", updates={"rating": 6})
        )
        note_selector_service.pick_note = AsyncMock(return_value=None)

        service = MultiAgentService(
            chat_agent=chat_agent_service,
            reflection_service=reflection_service,
            question_agent=question_agent,
            scorer_agent=scorer_agent,
            hint_agent=hint_agent,
            chat_mode_service=chat_mode_service,
            sources_repository=sources_repository,
            note_selector_service=note_selector_service,
            memory_repository=memory_repository,
            agent_model=model,
        )

        result = await service.handle("some text", telegram_user_id=123)

        # Should route to _answer, not _hint or _context
        scorer_agent.run.assert_awaited_once()
        hint_agent.run.assert_not_awaited()

    @pytest.mark.anyio
    async def test_handle_cancels_on_slash_in_reflect_mode(
        self,
        chat_agent_service: Mock,
        reflection_service: Mock,
        question_agent: Mock,
        scorer_agent: Mock,
        hint_agent: Mock,
        chat_mode_service: Mock,
        sources_repository: Mock,
        note_selector_service: Mock,
        memory_repository: Mock,
        agent_model: Mock,
    ) -> None:
        """Slash command in reflect mode → cancel and exit to agent."""
        chat_mode_service.get_mode = Mock(return_value="reflect")
        reflection_service.get_pending_reflection = AsyncMock(return_value=None)

        service = MultiAgentService(
            chat_agent=chat_agent_service,
            reflection_service=reflection_service,
            question_agent=question_agent,
            scorer_agent=scorer_agent,
            hint_agent=hint_agent,
            chat_mode_service=chat_mode_service,
            sources_repository=sources_repository,
            note_selector_service=note_selector_service,
            memory_repository=memory_repository,
            agent_model=agent_model,
        )

        result = await service.handle("/sources", telegram_user_id=123)

        assert result.outcome == "cancelled"
        assert "Reflection cancelled" in result.reply
        reflection_service.cancel_pending_reflection.assert_awaited_once_with(123)
        chat_mode_service.set_mode.assert_called_with("agent")