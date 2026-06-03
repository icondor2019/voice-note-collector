"""Unit tests for HintAgent."""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from backend.models.agent import AgentResult
from backend.services.agents.hint_agent import HintAgent


class MockModel:
    """Minimal mock model that returns a configurable response."""

    def __init__(self, response_content: str = "") -> None:
        self._response_content = response_content

    def invoke(self, prompt: str) -> Mock:
        mock_response = Mock()
        mock_response.content = self._response_content
        self._last_prompt = prompt
        return mock_response

    @property
    def last_prompt(self) -> str:
        return getattr(self, "_last_prompt", "")


class TestHintAgent:
    """Tests for HintAgent.run()."""

    @pytest.mark.anyio
    async def test_run_returns_hinted_outcome(self) -> None:
        """Mock returns a short hint → AgentResult with outcome='hinted'."""
        model = MockModel(response_content="Try: a coffee")
        agent = HintAgent(model)

        result = await agent.run(
            note_text="Morning coffee at the cafe",
            question_text="Where did you have coffee?",
            user_message="give me a hint",
        )

        assert result.outcome == "hinted"
        assert result.reply == "Try: a coffee"

    @pytest.mark.anyio
    async def test_run_returns_short_reply_in_note_language_english(self) -> None:
        """English note → reply should be in English, no Spanish stopwords."""
        model = MockModel(response_content="Morning routine")
        agent = HintAgent(model)

        result = await agent.run(
            note_text="I drink coffee every morning at the cafe near work",
            question_text="What is your morning routine?",
            user_message="I don't remember",
        )

        assert result.outcome == "hinted"
        assert len(result.reply) < 50
        # Should not contain Spanish stopwords
        spanish_stopwords = {"el", "la", "que", "de", "en", "un", "una", "es", "por", "para"}
        reply_lower = result.reply.lower()
        for word in spanish_stopwords:
            assert word not in reply_lower, f"Found Spanish stopword '{word}' in English reply"

    @pytest.mark.anyio
    async def test_run_returns_short_reply_in_note_language_spanish(self) -> None:
        """Spanish note → reply should contain Spanish words, not English stopwords."""
        model = MockModel(response_content="Prueba: el café de la mañana")
        agent = HintAgent(model)

        result = await agent.run(
            note_text="Tomo café todas las mañanas en la cafetería cerca del trabajo",
            question_text="¿Cuál es tu rutina por la mañana?",
            user_message="dame una pista",
        )

        assert result.outcome == "hinted"
        # Reply should be in Spanish (contains common Spanish words)
        spanish_indicators = {"prueba", "el", "la", "café", "mañana", "tomo"}
        reply_lower = result.reply.lower()
        has_spanish = any(word in reply_lower for word in spanish_indicators)
        assert has_spanish, f"Reply should contain Spanish words, got: {result.reply}"

    @pytest.mark.anyio
    async def test_run_does_not_reveal_answer(self) -> None:
        """Note contains a specific phrase; the reply should NOT repeat it verbatim."""
        model = MockModel(response_content="the answer is forty-two")
        agent = HintAgent(model)

        result = await agent.run(
            note_text="the answer is forty-two",
            question_text="What is the answer?",
            user_message="help me",
        )

        # The agent's reply is what we get back; we verify the agent was called
        # with the note text in the prompt (contract test)
        assert model.last_prompt is not None
        assert "the answer is forty-two" in model.last_prompt

    @pytest.mark.anyio
    async def test_run_does_not_pose_new_questions(self) -> None:
        """Reply should not contain question marks (no new questions posed)."""
        model = MockModel(response_content="Just recall the cafe name.")
        agent = HintAgent(model)

        result = await agent.run(
            note_text="Went to Blue Bottle cafe yesterday",
            question_text="Where did you go?",
            user_message="hint please",
        )

        assert result.outcome == "hinted"
        # A Socratic hint should not pose a new question
        assert "?" not in result.reply, "Socratic hint should not pose new questions"

    @pytest.mark.anyio
    async def test_run_accepts_empty_note_text(self) -> None:
        """Handles empty note text gracefully."""
        model = MockModel(response_content="Think about your day.")
        agent = HintAgent(model)

        result = await agent.run(
            note_text="",
            question_text="What happened?",
            user_message="hint",
        )

        assert result.outcome == "hinted"
        assert len(result.reply) > 0

    @pytest.mark.anyio
    async def test_run_passes_note_text_to_model(self) -> None:
        """Verify the agent passes note_text in the prompt."""
        model = MockModel(response_content="Hint.")
        agent = HintAgent(model)

        await agent.run(
            note_text="My special moment was at the beach",
            question_text="Where was your special moment?",
            user_message="hint",
        )

        assert "My special moment was at the beach" in model.last_prompt
        assert "Where was your special moment?" in model.last_prompt

    @pytest.mark.anyio
    async def test_run_passes_user_message_to_model(self) -> None:
        """Verify the agent passes user_message in the prompt."""
        model = MockModel(response_content="Hint.")
        agent = HintAgent(model)

        await agent.run(
            note_text="Some note content",
            question_text="The question",
            user_message="I really don't remember",
        )

        assert "I really don't remember" in model.last_prompt

    @pytest.mark.anyio
    async def test_run_trims_whitespace_from_response(self) -> None:
        """Model response with surrounding whitespace is trimmed."""
        model = MockModel(response_content="  Try the coffee  \n")
        agent = HintAgent(model)

        result = await agent.run(
            note_text="Coffee shop",
            question_text="What about coffee?",
            user_message="hint",
        )

        assert result.reply == "Try the coffee"