from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from unittest.mock import AsyncMock, Mock
from uuid import UUID

import pytest

from backend.models.reflection import ReflectionEntry, ReflectionQuestionResult, ReflectionRatingResult
from backend.services.reflection_service import (
    NoActiveSourceError,
    NoNotesError,
    ReflectionService,
)


class MockChatOpenAI:
    """Mock ChatOpenAI model for testing."""

    def __init__(self, response_content: str = "") -> None:
        self._response_content = response_content

    def invoke(self, prompt: str) -> Mock:
        mock_response = Mock()
        mock_response.content = self._response_content
        return mock_response


class TestReflectionService:
    @pytest.mark.anyio
    async def test_start_reflection_creates_pending_reflection(self) -> None:
        # Setup mocks
        reflection_repository = AsyncMock()
        voice_notes_repository = AsyncMock()
        sources_repository = AsyncMock()
        model = MockChatOpenAI(
            response_content='{"question_type": "reflective", "question_text": "What did you learn?"}'
        )

        sources_repository.get_active_source = AsyncMock(
            return_value={"id": "source-1", "source_name": "test"}
        )
        voice_notes_repository.list_voice_notes = AsyncMock(
            return_value=[
                {"id": "note-1", "raw_text": "Note 1"},
                {"id": "note-2", "raw_text": "Note 2"},
            ]
        )
        reflection_repository.create_reflection = AsyncMock(
            return_value={
                "id": "12345678-1234-5678-1234-567812345678",
                "telegram_user_id": 123,
                "question_type": "reflective",
                "question_text": "What did you learn?",
                "status": "pending",
            }
        )

        service = ReflectionService(
            reflection_repository=reflection_repository,
            voice_notes_repository=voice_notes_repository,
            sources_repository=sources_repository,
            model=model,
        )

        result = await service.start_reflection(123)

        assert isinstance(result, ReflectionQuestionResult)
        assert result.question_type == "reflective"
        assert result.question_text == "What did you learn?"
        reflection_repository.create_reflection.assert_awaited_once()

    @pytest.mark.anyio
    async def test_start_reflection_raises_no_active_source(self) -> None:
        reflection_repository = AsyncMock()
        voice_notes_repository = AsyncMock()
        sources_repository = AsyncMock()
        model = MockChatOpenAI()

        sources_repository.get_active_source = AsyncMock(return_value=None)

        service = ReflectionService(
            reflection_repository=reflection_repository,
            voice_notes_repository=voice_notes_repository,
            sources_repository=sources_repository,
            model=model,
        )

        with pytest.raises(NoActiveSourceError):
            await service.start_reflection(123)

    @pytest.mark.anyio
    async def test_start_reflection_raises_no_notes(self) -> None:
        reflection_repository = AsyncMock()
        voice_notes_repository = AsyncMock()
        sources_repository = AsyncMock()
        model = MockChatOpenAI()

        sources_repository.get_active_source = AsyncMock(
            return_value={"id": "source-1", "source_name": "test"}
        )
        voice_notes_repository.list_voice_notes = AsyncMock(return_value=[])

        service = ReflectionService(
            reflection_repository=reflection_repository,
            voice_notes_repository=voice_notes_repository,
            sources_repository=sources_repository,
            model=model,
        )

        with pytest.raises(NoNotesError):
            await service.start_reflection(123)

    @pytest.mark.anyio
    async def test_start_reflection_cancels_existing_pending(self) -> None:
        reflection_repository = AsyncMock()
        voice_notes_repository = AsyncMock()
        sources_repository = AsyncMock()
        model = MockChatOpenAI(
            response_content='{"question_type": "quiz", "question_text": "Test question"}'
        )

        sources_repository.get_active_source = AsyncMock(
            return_value={"id": "source-1", "source_name": "test"}
        )
        voice_notes_repository.list_voice_notes = AsyncMock(
            return_value=[{"id": "note-1", "raw_text": "Note 1"}]
        )
        reflection_repository.create_reflection = AsyncMock(
            return_value={
                "id": "22345678-1234-5678-1234-567812345678",
                "telegram_user_id": 123,
                "question_type": "quiz",
                "question_text": "Test question",
                "status": "pending",
            }
        )

        service = ReflectionService(
            reflection_repository=reflection_repository,
            voice_notes_repository=voice_notes_repository,
            sources_repository=sources_repository,
            model=model,
        )

        await service.start_reflection(123)

        reflection_repository.cancel_pending_reflection.assert_awaited_once_with(123)

    @pytest.mark.anyio
    async def test_start_reflection_uses_fewer_than_5_notes(self) -> None:
        reflection_repository = AsyncMock()
        voice_notes_repository = AsyncMock()
        sources_repository = AsyncMock()
        model = MockChatOpenAI(
            response_content='{"question_type": "elaboration", "question_text": "Expand on this"}'
        )

        sources_repository.get_active_source = AsyncMock(
            return_value={"id": "source-1", "source_name": "test"}
        )
        # Only 3 notes
        voice_notes_repository.list_voice_notes = AsyncMock(
            return_value=[
                {"id": "note-1", "raw_text": "Note 1"},
                {"id": "note-2", "raw_text": "Note 2"},
                {"id": "note-3", "raw_text": "Note 3"},
            ]
        )
        reflection_repository.create_reflection = AsyncMock(
            return_value={
                "id": "32345678-1234-5678-1234-567812345678",
                "telegram_user_id": 123,
                "question_type": "elaboration",
                "question_text": "Expand on this",
                "status": "pending",
            }
        )

        service = ReflectionService(
            reflection_repository=reflection_repository,
            voice_notes_repository=voice_notes_repository,
            sources_repository=sources_repository,
            model=model,
        )

        result = await service.start_reflection(123)

        # Should not raise even with fewer than 5 notes
        assert result.question_type == "elaboration"
        voice_notes_repository.list_voice_notes.assert_awaited_once()

    @pytest.mark.anyio
    async def test_complete_reflection_rates_and_stores(self) -> None:
        reflection_repository = AsyncMock()
        voice_notes_repository = AsyncMock()
        sources_repository = AsyncMock()
        model = MockChatOpenAI(
            response_content='{"rating": 8, "feedback": "Great answer!"}'
        )

        pending_reflection = {
            "id": "42345678-1234-5678-1234-567812345678",
            "telegram_user_id": 123,
            "voice_note_id": None,
            "question_type": "reflective",
            "question_text": "What did you learn?",
            "answer_text": None,
            "rating": None,
            "feedback": None,
            "status": "pending",
            "created_at": datetime.now(timezone.utc),
            "completed_at": None,
        }
        reflection_repository.get_pending_reflection = AsyncMock(return_value=pending_reflection)
        sources_repository.get_active_source = AsyncMock(
            return_value={"id": "source-1", "source_name": "test"}
        )
        voice_notes_repository.list_voice_notes = AsyncMock(
            return_value=[{"id": "note-1", "raw_text": "Note 1"}]
        )
        reflection_repository.complete_reflection = AsyncMock()

        service = ReflectionService(
            reflection_repository=reflection_repository,
            voice_notes_repository=voice_notes_repository,
            sources_repository=sources_repository,
            model=model,
        )

        result = await service.complete_reflection(123, "I learned a lot about testing")

        assert isinstance(result, ReflectionRatingResult)
        assert result.rating == 8
        assert result.feedback == "Great answer!"
        reflection_repository.complete_reflection.assert_awaited_once()

    @pytest.mark.anyio
    async def test_complete_reflection_no_pending_raises(self) -> None:
        reflection_repository = AsyncMock()
        voice_notes_repository = AsyncMock()
        sources_repository = AsyncMock()
        model = MockChatOpenAI()

        reflection_repository.get_pending_reflection = AsyncMock(return_value=None)

        service = ReflectionService(
            reflection_repository=reflection_repository,
            voice_notes_repository=voice_notes_repository,
            sources_repository=sources_repository,
            model=model,
        )

        with pytest.raises(NoNotesError):
            await service.complete_reflection(123, "My answer")

    @pytest.mark.anyio
    async def test_cancel_pending_reflection_delegates_to_repository(self) -> None:
        reflection_repository = AsyncMock()
        voice_notes_repository = AsyncMock()
        sources_repository = AsyncMock()
        model = MockChatOpenAI()

        service = ReflectionService(
            reflection_repository=reflection_repository,
            voice_notes_repository=voice_notes_repository,
            sources_repository=sources_repository,
            model=model,
        )

        await service.cancel_pending_reflection(123)

        reflection_repository.cancel_pending_reflection.assert_awaited_once_with(123)

    @pytest.mark.anyio
    async def test_get_pending_reflection_returns_entry(self) -> None:
        reflection_repository = AsyncMock()
        voice_notes_repository = AsyncMock()
        sources_repository = AsyncMock()
        model = MockChatOpenAI()

        pending_reflection = {
            "id": UUID("12345678-1234-5678-1234-567812345678"),
            "telegram_user_id": 123,
            "voice_note_id": None,
            "question_type": "reflective",
            "question_text": "What did you learn?",
            "answer_text": None,
            "rating": None,
            "feedback": None,
            "status": "pending",
            "created_at": datetime.now(timezone.utc),
            "completed_at": None,
        }
        reflection_repository.get_pending_reflection = AsyncMock(return_value=pending_reflection)

        service = ReflectionService(
            reflection_repository=reflection_repository,
            voice_notes_repository=voice_notes_repository,
            sources_repository=sources_repository,
            model=model,
        )

        result = await service.get_pending_reflection(123)

        assert result is not None
        assert isinstance(result, ReflectionEntry)
        assert result.question_type == "reflective"

    @pytest.mark.anyio
    async def test_get_pending_reflection_returns_none_when_empty(self) -> None:
        reflection_repository = AsyncMock()
        voice_notes_repository = AsyncMock()
        sources_repository = AsyncMock()
        model = MockChatOpenAI()

        reflection_repository.get_pending_reflection = AsyncMock(return_value=None)

        service = ReflectionService(
            reflection_repository=reflection_repository,
            voice_notes_repository=voice_notes_repository,
            sources_repository=sources_repository,
            model=model,
        )

        result = await service.get_pending_reflection(123)

        assert result is None
