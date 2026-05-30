"""Note selector service for reflection note selection based on internalization metrics."""

from __future__ import annotations

import random
from typing import TYPE_CHECKING, Any, Optional

from configuration.settings import settings
from backend.repositories.reflection_repository import ReflectionRepository
from backend.repositories.voice_notes_repository import VoiceNotesRepository

if TYPE_CHECKING:
    pass


class NoteSelectorService:
    """Selects a non-internalized note from a source's recent pool for reflection."""

    def __init__(
        self,
        voice_notes_repository: VoiceNotesRepository,
        reflection_repository: ReflectionRepository,
    ) -> None:
        self._voice_notes_repository = voice_notes_repository
        self._reflection_repository = reflection_repository

    async def pick_note(self, source_id: str) -> Optional[dict[str, Any]]:
        """
        Pick a note from the source's recent pool that hasn't been internalized.

        1. Fetch last REFLECTION_NOTES_COUNT notes from source (oldest first)
        2. Get reflection stats for those notes (completed reflections only)
        3. Filter out internalized notes (avg_rating >= REFLECTION_MIN_AVG_SCORE
           AND review_count >= REFLECTION_MIN_REVIEWS)
        4. Note with no reflections are eligible (not internalized)
        5. Return random.choice(eligible_notes) or None if all internalized/empty
        """
        # Fetch last N notes (oldest first - ASC order so we get the oldest N first)
        notes = await self._voice_notes_repository.list_voice_notes(
            source_id=source_id,
            limit=settings.REFLECTION_NOTES_COUNT,
            order="asc",
        )

        if not notes:
            return None

        note_ids = [note["id"] for note in notes]

        # Get reflection stats for those notes (completed only)
        stats = await self._reflection_repository.get_note_reflection_stats(
            source_id=source_id,
            note_ids=note_ids,
        )

        # Filter out internalized notes
        eligible_notes: list[dict[str, Any]] = []
        for note in notes:
            note_id = note["id"]
            note_stats = stats.get(note_id, {"avg_rating": 0.0, "review_count": 0})

            is_internalized = (
                note_stats["avg_rating"] >= settings.REFLECTION_MIN_AVG_SCORE
                and note_stats["review_count"] >= settings.REFLECTION_MIN_REVIEWS
            )

            if not is_internalized:
                eligible_notes.append(note)

        if not eligible_notes:
            return None

        return random.choice(eligible_notes)