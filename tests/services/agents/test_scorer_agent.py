"""Unit tests for ScorerAgent."""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from backend.models.agent import AgentResult
from backend.services.agents.scorer_agent import ScorerAgent


class MockModel:
    """Minimal mock model that returns a configurable response."""

    def __init__(self, response_content: str = "") -> None:
        self._response_content = response_content

    def invoke(self, prompt: str) -> Mock:
        mock_response = Mock()
        mock_response.content = self._response_content
        return mock_response


class TestScorerAgent:
    """Tests for ScorerAgent.run()."""

    @pytest.mark.anyio
    async def test_run_returns_rating_and_feedback(self) -> None:
        """Valid JSON → AgentResult with outcome='scored' and rating."""
        model = MockModel(response_content='{"rating": 8, "feedback": "Great answer!"}')
        agent = ScorerAgent(model)

        result = await agent.run(
            question_type="quiz",
            question_text="What did you learn?",
            answer_text="I learned about testing.",
            note={"raw_text": "Test note content"},
        )

        assert result.outcome == "scored"
        assert result.updates["rating"] == 8
        assert result.reply == "Great answer!"

    @pytest.mark.anyio
    async def test_run_clamps_rating_to_10(self) -> None:
        """Rating > 10 is clamped to 10."""
        model = MockModel(response_content='{"rating": 99, "feedback": "Too high"}')
        agent = ScorerAgent(model)

        result = await agent.run(
            question_type="reflective",
            question_text="Recall the note.",
            answer_text="My answer here.",
            note={"raw_text": "Some note"},
        )

        assert result.updates["rating"] == 10

    @pytest.mark.anyio
    async def test_run_clamps_rating_to_1(self) -> None:
        """Rating < 1 is clamped to 1."""
        model = MockModel(response_content='{"rating": -5, "feedback": "Too low"}')
        agent = ScorerAgent(model)

        result = await agent.run(
            question_type="reflective",
            question_text="Recall the note.",
            answer_text="My answer here.",
            note={"raw_text": "Some note"},
        )

        assert result.updates["rating"] == 1

    @pytest.mark.anyio
    async def test_run_clamps_rating_boundary_high(self) -> None:
        """Rating of exactly 10 stays 10."""
        model = MockModel(response_content='{"rating": 10, "feedback": "Perfect"}')
        agent = ScorerAgent(model)

        result = await agent.run(
            question_type="quiz",
            question_text="Q",
            answer_text="A",
            note={"raw_text": "N"},
        )

        assert result.updates["rating"] == 10

    @pytest.mark.anyio
    async def test_run_clamps_rating_boundary_low(self) -> None:
        """Rating of exactly 1 stays 1."""
        model = MockModel(response_content='{"rating": 1, "feedback": "No recall"}')
        agent = ScorerAgent(model)

        result = await agent.run(
            question_type="quiz",
            question_text="Q",
            answer_text="A",
            note={"raw_text": "N"},
        )

        assert result.updates["rating"] == 1

    @pytest.mark.anyio
    async def test_run_falls_back_on_parse_failure(self) -> None:
        """Invalid JSON → fallback rating=5 and default feedback."""
        model = MockModel(response_content="broken json")
        agent = ScorerAgent(model)

        result = await agent.run(
            question_type="reflective",
            question_text="What was the note about?",
            answer_text="I don't remember.",
            note={"raw_text": "Some note"},
        )

        assert result.updates["rating"] == 5
        assert "Good effort" in result.reply or "specific" in result.reply.lower()

    @pytest.mark.anyio
    async def test_run_extracts_from_json_codeblock(self) -> None:
        """JSON inside ```json block is correctly extracted."""
        model = MockModel(
            response_content='```json\n{"rating": 7, "feedback": "Good recall"}\n```'
        )
        agent = ScorerAgent(model)

        result = await agent.run(
            question_type="elaboration",
            question_text="Explain the idea.",
            answer_text="The idea was about X.",
            note={"raw_text": "A note about X"},
        )

        assert result.outcome == "scored"
        assert result.updates["rating"] == 7
        assert result.reply == "Good recall"

    @pytest.mark.anyio
    async def test_run_extracts_from_plain_codeblock(self) -> None:
        """JSON inside ``` plain block is correctly extracted."""
        model = MockModel(
            response_content='```\n{"rating": 6, "feedback": "Some recall"}\n```'
        )
        agent = ScorerAgent(model)

        result = await agent.run(
            question_type="follow-up",
            question_text="What's next?",
            answer_text="Continue with Y.",
            note={"clean_text": "Note about Y"},
        )

        assert result.outcome == "scored"
        assert result.updates["rating"] == 6

    @pytest.mark.anyio
    async def test_run_defaults_missing_feedback(self) -> None:
        """JSON has rating but no feedback → uses default feedback."""
        model = MockModel(response_content='{"rating": 5}')
        agent = ScorerAgent(model)

        result = await agent.run(
            question_type="quiz",
            question_text="Q",
            answer_text="A",
            note={"raw_text": "N"},
        )

        assert result.outcome == "scored"
        assert result.updates["rating"] == 5
        assert len(result.reply) > 0  # Default feedback is non-empty