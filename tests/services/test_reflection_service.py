"""Unit tests for ReflectionService after NoteSelectorService integration."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from unittest.mock import AsyncMock, Mock
from uuid import UUID

import pytest

from backend.models.reflection import ReflectionEntry, ReflectionQuestionResult, ReflectionRatingResult
from backend.services.reflection_service import (
    AllNotesInternalizedError,
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


class TestReflectionServiceWithNoteSelector:
    """Tests for ReflectionService using NoteSelectorService for note selection."""

    @pytest.mark.anyio
    async def test_start_reflection_uses_note_selector_to_pick_note(self) -> None:
        """Verify NoteSelectorService.pick_note is called with source_id."""
        reflection_repository = AsyncMock()
        sources_repository = AsyncMock()
        note_selector_service = AsyncMock()
        model = MockChatOpenAI(
            response_content='{"question_type": "reflective", "question_text": "What did you learn?"}'
        )

        sources_repository.get_active_source = AsyncMock(
            return_value={"id": "source-1", "source_name": "test"}
        )
        note_selector_service.pick_note = AsyncMock(
            return_value={"id": "00000000-0000-0000-0000-000000000001", "raw_text": "Note 1"}
        )
        reflection_repository.create_reflection = AsyncMock(
            return_value={
                "id": "12345678-1234-5678-1234-567812345678",
                "telegram_user_id": 123,
                "voice_note_id": "00000000-0000-0000-0000-000000000001",
                "question_type": "reflective",
                "question_text": "What did you learn?",
                "status": "pending",
            }
        )

        service = ReflectionService(
            reflection_repository=reflection_repository,
            sources_repository=sources_repository,
            model=model,
            note_selector_service=note_selector_service,
        )

        result = await service.start_reflection(123)

        assert isinstance(result, ReflectionQuestionResult)
        note_selector_service.pick_note.assert_awaited_once_with("source-1")

    @pytest.mark.anyio
    async def test_start_reflection_raises_all_notes_internalized(self) -> None:
        """pick_note returns None → AllNotesInternalizedError raised."""
        reflection_repository = AsyncMock()
        sources_repository = AsyncMock()
        note_selector_service = AsyncMock()
        model = MockChatOpenAI()

        sources_repository.get_active_source = AsyncMock(
            return_value={"id": "source-1", "source_name": "test"}
        )
        note_selector_service.pick_note = AsyncMock(return_value=None)

        service = ReflectionService(
            reflection_repository=reflection_repository,
            sources_repository=sources_repository,
            model=model,
            note_selector_service=note_selector_service,
        )

        with pytest.raises(AllNotesInternalizedError):
            await service.start_reflection(123)

    @pytest.mark.anyio
    async def test_start_reflection_stores_voice_note_id(self) -> None:
        """Verify create_reflection called with the selected note's ID."""
        reflection_repository = AsyncMock()
        sources_repository = AsyncMock()
        note_selector_service = AsyncMock()
        model = MockChatOpenAI(
            response_content='{"question_type": "quiz", "question_text": "Test question"}'
        )

        sources_repository.get_active_source = AsyncMock(
            return_value={"id": "source-1", "source_name": "test"}
        )
        note_selector_service.pick_note = AsyncMock(
            return_value={"id": "00000000-0000-0000-0000-000000000001", "raw_text": "Note 1"}
        )
        reflection_repository.create_reflection = AsyncMock(
            return_value={
                "id": "22345678-1234-5678-1234-567812345678",
                "telegram_user_id": 123,
                "voice_note_id": "00000000-0000-0000-0000-000000000001",
                "question_type": "quiz",
                "question_text": "Test question",
                "status": "pending",
            }
        )

        service = ReflectionService(
            reflection_repository=reflection_repository,
            sources_repository=sources_repository,
            model=model,
            note_selector_service=note_selector_service,
        )

        await service.start_reflection(123)

        reflection_repository.create_reflection.assert_awaited_once()
        call_kwargs = reflection_repository.create_reflection.call_args
        assert call_kwargs[1]["voice_note_id"] == "00000000-0000-0000-0000-000000000001"

    @pytest.mark.anyio
    async def test_start_reflection_raises_no_active_source(self) -> None:
        """No active source → NoActiveSourceError raised."""
        reflection_repository = AsyncMock()
        sources_repository = AsyncMock()
        note_selector_service = AsyncMock()
        model = MockChatOpenAI()

        sources_repository.get_active_source = AsyncMock(return_value=None)

        service = ReflectionService(
            reflection_repository=reflection_repository,
            sources_repository=sources_repository,
            model=model,
            note_selector_service=note_selector_service,
        )

        with pytest.raises(NoActiveSourceError):
            await service.start_reflection(123)

    @pytest.mark.anyio
    async def test_start_reflection_cancels_existing_pending(self) -> None:
        """start_reflection cancels any existing pending reflection first."""
        reflection_repository = AsyncMock()
        sources_repository = AsyncMock()
        note_selector_service = AsyncMock()
        model = MockChatOpenAI(
            response_content='{"question_type": "quiz", "question_text": "Test question"}'
        )

        sources_repository.get_active_source = AsyncMock(
            return_value={"id": "source-1", "source_name": "test"}
        )
        note_selector_service.pick_note = AsyncMock(
            return_value={"id": "00000000-0000-0000-0000-000000000002", "raw_text": "Note 1"}
        )
        reflection_repository.create_reflection = AsyncMock(
            return_value={
                "id": "32345678-1234-5678-1234-567812345678",
                "telegram_user_id": 123,
                "voice_note_id": "00000000-0000-0000-0000-000000000002",
                "question_type": "quiz",
                "question_text": "Test question",
                "status": "pending",
            }
        )

        service = ReflectionService(
            reflection_repository=reflection_repository,
            sources_repository=sources_repository,
            model=model,
            note_selector_service=note_selector_service,
        )

        await service.start_reflection(123)

        reflection_repository.cancel_pending_reflection.assert_awaited_once_with(123)

    @pytest.mark.anyio
    async def test_complete_reflection_fetches_single_note(self) -> None:
        """Verify note fetched by voice_note_id from pending reflection."""
        reflection_repository = AsyncMock()
        sources_repository = AsyncMock()
        note_selector_service = AsyncMock()
        model = MockChatOpenAI(
            response_content='{"rating": 8, "feedback": "Great answer!"}'
        )

        pending_reflection = {
            "id": "42345678-1234-5678-1234-567812345678",
            "telegram_user_id": 123,
            "voice_note_id": "00000000-0000-0000-0000-000000000003",
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
        reflection_repository.complete_reflection = AsyncMock()

        # Mock the client.table(...).select(...).eq(...).maybe_single().execute() chain
        mock_note_response = Mock()
        mock_note_response.data = {"id": "00000000-0000-0000-0000-000000000003", "raw_text": "Note 1 content"}
        mock_note_response.error = None
        mock_eq_query = Mock()
        mock_eq_query.select = Mock(return_value=mock_eq_query)
        mock_eq_query.eq = Mock(return_value=mock_eq_query)
        mock_eq_query.maybe_single = Mock(return_value=mock_eq_query)
        mock_eq_query.execute = AsyncMock(return_value=mock_note_response)
        mock_table = Mock()
        mock_table.select = Mock(return_value=mock_eq_query)
        reflection_repository._client = Mock()
        reflection_repository._client.table = Mock(return_value=mock_table)

        service = ReflectionService(
            reflection_repository=reflection_repository,
            sources_repository=sources_repository,
            model=model,
            note_selector_service=note_selector_service,
        )

        result = await service.complete_reflection(123, "I learned a lot about testing")

        assert isinstance(result, ReflectionRatingResult)
        assert result.rating == 8
        assert result.feedback == "Great answer!"
        reflection_repository.complete_reflection.assert_awaited_once()

    @pytest.mark.anyio
    async def test_complete_reflection_no_pending_raises(self) -> None:
        """No pending reflection → NoNotesError raised."""
        reflection_repository = AsyncMock()
        sources_repository = AsyncMock()
        note_selector_service = AsyncMock()
        model = MockChatOpenAI()

        reflection_repository.get_pending_reflection = AsyncMock(return_value=None)

        service = ReflectionService(
            reflection_repository=reflection_repository,
            sources_repository=sources_repository,
            model=model,
            note_selector_service=note_selector_service,
        )

        with pytest.raises(NoNotesError):
            await service.complete_reflection(123, "My answer")

    @pytest.mark.anyio
    async def test_cancel_pending_reflection_delegates_to_repository(self) -> None:
        """cancel_pending_reflection calls repository method."""
        reflection_repository = AsyncMock()
        sources_repository = AsyncMock()
        note_selector_service = AsyncMock()
        model = MockChatOpenAI()

        service = ReflectionService(
            reflection_repository=reflection_repository,
            sources_repository=sources_repository,
            model=model,
            note_selector_service=note_selector_service,
        )

        await service.cancel_pending_reflection(123)

        reflection_repository.cancel_pending_reflection.assert_awaited_once_with(123)

    @pytest.mark.anyio
    async def test_get_pending_reflection_returns_entry(self) -> None:
        """get_pending_reflection returns ReflectionEntry."""
        reflection_repository = AsyncMock()
        sources_repository = AsyncMock()
        note_selector_service = AsyncMock()
        model = MockChatOpenAI()

        pending_reflection = {
            "id": UUID("12345678-1234-5678-1234-567812345678"),
            "telegram_user_id": 123,
            "voice_note_id": "00000000-0000-0000-0000-000000000004",
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
            sources_repository=sources_repository,
            model=model,
            note_selector_service=note_selector_service,
        )

        result = await service.get_pending_reflection(123)

        assert result is not None
        assert isinstance(result, ReflectionEntry)
        assert result.question_type == "reflective"

    @pytest.mark.anyio
    async def test_get_pending_reflection_returns_none_when_empty(self) -> None:
        """get_pending_reflection returns None when no pending reflection."""
        reflection_repository = AsyncMock()
        sources_repository = AsyncMock()
        note_selector_service = AsyncMock()
        model = MockChatOpenAI()

        reflection_repository.get_pending_reflection = AsyncMock(return_value=None)

        service = ReflectionService(
            reflection_repository=reflection_repository,
            sources_repository=sources_repository,
            model=model,
            note_selector_service=note_selector_service,
        )

        result = await service.get_pending_reflection(123)

        assert result is None
