"""Unit tests for NoteSelectorService."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from backend.services.note_selector_service import NoteSelectorService
from configuration.settings import settings


class TestNoteSelectorService:
    """Tests for NoteSelectorService.pick_note method."""

    @pytest.mark.anyio
    async def test_pick_note_returns_note_when_eligible_notes_exist(self) -> None:
        """When 5 notes in pool, 2 internalized, 3 eligible → returns one of the 3."""
        voice_notes_repository = AsyncMock()
        reflection_repository = AsyncMock()

        notes = [
            {"id": "note-1", "raw_text": "Note 1"},
            {"id": "note-2", "raw_text": "Note 2"},
            {"id": "note-3", "raw_text": "Note 3"},
            {"id": "note-4", "raw_text": "Note 4"},
            {"id": "note-5", "raw_text": "Note 5"},
        ]
        voice_notes_repository.list_voice_notes = AsyncMock(return_value=notes)

        # note-1 and note-2 are internalized (avg_rating >= 8 AND review_count >= 2)
        reflection_repository.get_note_reflection_stats = AsyncMock(
            return_value={
                "note-1": {"avg_rating": 9.0, "review_count": 3},
                "note-2": {"avg_rating": 8.5, "review_count": 2},
            }
        )

        service = NoteSelectorService(
            voice_notes_repository=voice_notes_repository,
            reflection_repository=reflection_repository,
        )

        result = await service.pick_note("source-1")

        assert result is not None
        assert result["id"] in ["note-3", "note-4", "note-5"]
        voice_notes_repository.list_voice_notes.assert_awaited_once_with(
            source_id="source-1", limit=settings.REFLECTION_NOTES_COUNT, order="asc"
        )

    @pytest.mark.anyio
    async def test_pick_note_returns_none_when_all_notes_internalized(self) -> None:
        """When all notes have avg_rating >= 8 and review_count >= 2 → returns None."""
        voice_notes_repository = AsyncMock()
        reflection_repository = AsyncMock()

        notes = [
            {"id": "note-1", "raw_text": "Note 1"},
            {"id": "note-2", "raw_text": "Note 2"},
        ]
        voice_notes_repository.list_voice_notes = AsyncMock(return_value=notes)

        # All notes are internalized
        reflection_repository.get_note_reflection_stats = AsyncMock(
            return_value={
                "note-1": {"avg_rating": 9.0, "review_count": 3},
                "note-2": {"avg_rating": 8.0, "review_count": 2},
            }
        )

        service = NoteSelectorService(
            voice_notes_repository=voice_notes_repository,
            reflection_repository=reflection_repository,
        )

        result = await service.pick_note("source-1")

        assert result is None

    @pytest.mark.anyio
    async def test_pick_note_returns_none_when_source_empty(self) -> None:
        """When no notes in source → returns None."""
        voice_notes_repository = AsyncMock()
        reflection_repository = AsyncMock()

        voice_notes_repository.list_voice_notes = AsyncMock(return_value=[])

        service = NoteSelectorService(
            voice_notes_repository=voice_notes_repository,
            reflection_repository=reflection_repository,
        )

        result = await service.pick_note("source-1")

        assert result is None

    @pytest.mark.anyio
    async def test_pick_note_includes_notes_with_no_reflections(self) -> None:
        """Notes with no reflection stats (not in stats dict) are eligible."""
        voice_notes_repository = AsyncMock()
        reflection_repository = AsyncMock()

        notes = [
            {"id": "note-1", "raw_text": "Note 1"},
            {"id": "note-2", "raw_text": "Note 2"},
        ]
        voice_notes_repository.list_voice_notes = AsyncMock(return_value=notes)

        # note-1 has no reflections, note-2 is internalized
        reflection_repository.get_note_reflection_stats = AsyncMock(
            return_value={
                "note-2": {"avg_rating": 9.0, "review_count": 3},
            }
        )

        service = NoteSelectorService(
            voice_notes_repository=voice_notes_repository,
            reflection_repository=reflection_repository,
        )

        result = await service.pick_note("source-1")

        assert result is not None
        assert result["id"] == "note-1"

    @pytest.mark.anyio
    async def test_pick_note_excludes_partially_internalized_notes(self) -> None:
        """Note with avg_rating=9 but review_count=1 is NOT internalized (still eligible)."""
        voice_notes_repository = AsyncMock()
        reflection_repository = AsyncMock()

        notes = [
            {"id": "note-1", "raw_text": "Note 1"},
        ]
        voice_notes_repository.list_voice_notes = AsyncMock(return_value=notes)

        # Partially internalized: review_count < 2
        reflection_repository.get_note_reflection_stats = AsyncMock(
            return_value={
                "note-1": {"avg_rating": 9.0, "review_count": 1},
            }
        )

        service = NoteSelectorService(
            voice_notes_repository=voice_notes_repository,
            reflection_repository=reflection_repository,
        )

        result = await service.pick_note("source-1")

        assert result is not None
        assert result["id"] == "note-1"

    @pytest.mark.anyio
    async def test_pick_note_excludes_fully_internalized_notes(self) -> None:
        """Note with avg_rating=8 and review_count=2 IS internalized (excluded)."""
        voice_notes_repository = AsyncMock()
        reflection_repository = AsyncMock()

        notes = [
            {"id": "note-1", "raw_text": "Note 1"},
            {"id": "note-2", "raw_text": "Note 2"},
        ]
        voice_notes_repository.list_voice_notes = AsyncMock(return_value=notes)

        # note-1 is internalized, note-2 has no reflections
        reflection_repository.get_note_reflection_stats = AsyncMock(
            return_value={
                "note-1": {"avg_rating": 8.0, "review_count": 2},
            }
        )

        service = NoteSelectorService(
            voice_notes_repository=voice_notes_repository,
            reflection_repository=reflection_repository,
        )

        result = await service.pick_note("source-1")

        assert result is not None
        assert result["id"] == "note-2"

    @pytest.mark.anyio
    async def test_pick_note_uses_reflection_notes_count_as_pool_limit(self) -> None:
        """Verify list_voice_notes called with limit=settings.REFLECTION_NOTES_COUNT."""
        voice_notes_repository = AsyncMock()
        reflection_repository = AsyncMock()

        voice_notes_repository.list_voice_notes = AsyncMock(return_value=[])
        reflection_repository.get_note_reflection_stats = AsyncMock(return_value={})

        service = NoteSelectorService(
            voice_notes_repository=voice_notes_repository,
            reflection_repository=reflection_repository,
        )

        await service.pick_note("source-1")

        voice_notes_repository.list_voice_notes.assert_awaited_once_with(
            source_id="source-1", limit=settings.REFLECTION_NOTES_COUNT, order="asc"
        )

    @pytest.mark.anyio
    async def test_pick_note_fetches_notes_oldest_first(self) -> None:
        """Verify list_voice_notes called with order='asc' to get oldest first."""
        voice_notes_repository = AsyncMock()
        reflection_repository = AsyncMock()

        voice_notes_repository.list_voice_notes = AsyncMock(return_value=[])
        reflection_repository.get_note_reflection_stats = AsyncMock(return_value={})

        service = NoteSelectorService(
            voice_notes_repository=voice_notes_repository,
            reflection_repository=reflection_repository,
        )

        await service.pick_note("source-1")

        voice_notes_repository.list_voice_notes.assert_awaited_once_with(
            source_id="source-1", limit=settings.REFLECTION_NOTES_COUNT, order="asc"
        )
