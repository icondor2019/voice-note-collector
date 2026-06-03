"""Reflection service for spaced-repetition-inspired reflection interactions."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from loguru import logger

from backend.models.reflection import (
    ReflectionEntry,
    ReflectionQuestionResult,
    ReflectionRatingResult,
    ReflectionSummary,
)
from backend.repositories.reflection_repository import ReflectionRepository
from backend.repositories.sources_repository import SourcesRepository
from configuration.settings import settings

if TYPE_CHECKING:
    from uuid import UUID
    from backend.services.agents.question_agent import QuestionAgent
    from backend.services.agents.scorer_agent import ScorerAgent


class NoActiveSourceError(Exception):
    """Raised when no active source exists for the user."""

    pass


class NoNotesError(Exception):
    """Raised when no notes exist in the active source."""

    pass


class AllNotesInternalizedError(Exception):
    """Raised when all notes in the pool have been internalized."""

    pass


class ReflectionService:
    def __init__(
        self,
        reflection_repository: ReflectionRepository,
        sources_repository: SourcesRepository,
        note_selector_service: Any,  # NoteSelectorService
        question_agent: Optional["QuestionAgent"] = None,
        scorer_agent: Optional["ScorerAgent"] = None,
    ) -> None:
        self._reflection_repository = reflection_repository
        self._sources_repository = sources_repository
        self._note_selector_service = note_selector_service
        self._question_agent = question_agent
        self._scorer_agent = scorer_agent
        self.reflection_repository = reflection_repository  # expose for MultiAgentService

    async def start_reflection(self, telegram_user_id: int) -> ReflectionQuestionResult:
        """Start a new reflection session.

        1. Cancel any existing pending reflection for this user
        2. Get active source; raise if none
        3. Use NoteSelectorService to pick a note
        4. If pick_note returns None, raise AllNotesInternalizedError
        5. Call question_agent to generate question (type + text) for single note
        6. Create reflections row (status='pending') with voice_note_id
        7. Return question text for the bot to send
        """
        # Cancel any existing pending reflection
        await self.cancel_pending_reflection(telegram_user_id)

        # Get active source
        active_source = await self._sources_repository.get_active_source()
        if not active_source:
            raise NoActiveSourceError("No active source found for user")

        # Pick a note using NoteSelectorService
        note = await self._note_selector_service.pick_note(active_source["id"])
        if note is None:
            raise AllNotesInternalizedError(
                f"All notes from {active_source['source_name']} have been internalized"
            )

        # Generate question via question_agent
        if self._question_agent is None:
            raise RuntimeError(
                "question_agent is required — inject a QuestionAgent via the constructor"
            )
        result = await self._question_agent.run(note)
        question_type = result.updates.get("question_type", "reflective")
        question_text = result.reply

        # Create reflection row with the selected note's ID
        reflection = await self._reflection_repository.create_reflection(
            telegram_user_id=telegram_user_id,
            voice_note_id=note["id"],
            question_type=question_type,
            question_text=question_text,
        )

        return ReflectionQuestionResult(
            reflection_id=reflection["id"],
            question_type=question_type,
            question_text=question_text,
        )

    async def complete_reflection(
        self, telegram_user_id: int, answer_text: str
    ) -> ReflectionRatingResult:
        """Complete a pending reflection with the user's answer.

        1. Find pending reflection for this user
        2. Fetch the single note by voice_note_id from the pending reflection
        3. Call scorer_agent to rate answer + generate feedback
        4. Update reflections row (status='completed', rating, feedback, answer_text, completed_at)
        5. Return rating + feedback for the bot to send
        """
        # Find pending reflection
        pending = await self.get_pending_reflection(telegram_user_id)
        if not pending:
            raise NoNotesError("No pending reflection found")

        # Fetch the single note associated with this reflection
        note: dict[str, Any] = {"raw_text": "", "clean_text": ""}
        if pending.voice_note_id:
            voice_note_response = await self._reflection_repository._client.table(
                "voice_notes"
            ).select("*").eq("id", pending.voice_note_id).maybe_single().execute()
            if voice_note_response and voice_note_response.data:
                note = (
                    voice_note_response.data[0]
                    if isinstance(voice_note_response.data, list)
                    else voice_note_response.data
                )

        # Rate the answer via scorer_agent
        if self._scorer_agent is None:
            raise RuntimeError(
                "scorer_agent is required — inject a ScorerAgent via the constructor"
            )
        result = await self._scorer_agent.run(
            question_type=pending.question_type,
            question_text=pending.question_text,
            answer_text=answer_text,
            note=note,
        )
        rating = result.updates.get("rating", 5)
        feedback = result.reply

        # Update reflection row
        await self._reflection_repository.complete_reflection(
            reflection_id=str(pending.id),
            answer_text=answer_text,
            rating=rating,
            feedback=feedback,
        )

        return ReflectionRatingResult(rating=rating, feedback=feedback)

    async def cancel_pending_reflection(self, telegram_user_id: int) -> None:
        """Cancel any pending reflection for the user."""
        await self._reflection_repository.cancel_pending_reflection(telegram_user_id)

    async def get_pending_reflection(
        self, telegram_user_id: int
    ) -> Optional[ReflectionEntry]:
        """Get the pending reflection for a user, if any."""
        row = await self._reflection_repository.get_pending_reflection(telegram_user_id)
        if not row:
            return None
        return ReflectionEntry(**row)

    async def get_reflection_summary(self, telegram_user_id: int) -> ReflectionSummary:
        """Get reflection summary for the active source.

        Returns ReflectionSummary with counts and source name.
        Raises NoActiveSourceError if no active source.
        """
        active_source = await self._sources_repository.get_active_source()
        if not active_source:
            raise NoActiveSourceError("No active source found for user")

        stats = await self._reflection_repository.get_reflection_summary(
            source_id=active_source["id"],
            min_reviews=settings.REFLECTION_MIN_REVIEWS,
            min_avg_score=settings.REFLECTION_MIN_AVG_SCORE,
        )

        return ReflectionSummary(
            source_name=active_source["source_name"],
            total_notes=stats["total_notes"],
            internalized=stats["internalized"],
            in_progress=stats["in_progress"],
            pending=stats["pending"],
        )
