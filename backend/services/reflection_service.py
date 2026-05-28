"""Reflection service for spaced-repetition-inspired reflection interactions."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Optional

from langchain_openai import ChatOpenAI
from loguru import logger

from backend.models.reflection import (
    ReflectionEntry,
    ReflectionQuestionResult,
    ReflectionRatingResult,
)
from backend.repositories.reflection_repository import ReflectionRepository
from backend.repositories.sources_repository import SourcesRepository
from backend.repositories.voice_notes_repository import VoiceNotesRepository
from configuration.settings import settings

if TYPE_CHECKING:
    from uuid import UUID


QUESTION_GENERATION_PROMPT = """You are a reflection assistant for a personal voice note app. Given the following notes from the user, generate a question to test their recall and understanding.

Choose the most appropriate question type from these categories:
- follow-up: Ask about implications or next steps related to a note
- reflective: Ask the user to reflect on why something matters or what they learned
- quiz: Test factual recall from the notes
- elaboration: Ask the user to expand on a concept mentioned in the notes
- comparison: Ask the user to compare or contrast ideas from different notes

IMPORTANT: Pick a question type that is DIFFERENT from what you might have asked recently. Aim for variety across reflection sessions. If the notes are similar, try a different angle (e.g., if many are about the same topic, ask about relationships between ideas or practical applications).

Notes:
{notes}

Respond in JSON format:
{{
  "question_type": "<one of: follow-up, reflective, quiz, elaboration, comparison>",
  "question_text": "<your question>"
}}"""


RATING_PROMPT = """You are a supportive reflection partner talking directly with the user — like a mentor having a one-on-one chat. Be warm, specific, and constructive.

You asked the user this question:
{question_text}
Question type: {question_type}

The user's answer:
{answer_text}

Original notes for reference:
{notes}

Rate the answer from 1 to 10 and provide structured feedback using ONLY bullet points. Be concise — this is a quick chat, not an essay.

Format your feedback in these sections:
- ✅ What was good (specific things they got right or well)
- 💡 What to improve (gaps, missing details, or misconceptions)
- 🎯 Next time (a concrete tip for the next reflection)

Be direct and personal. Use "you" not "the user". Keep each bullet to one short sentence.

Respond in JSON format:
{{
  "rating": <integer 1-10>,
  "feedback": "✅ ...\n\n💡 ...\n\n🎯 ..."
}}"""


class NoActiveSourceError(Exception):
    """Raised when no active source exists for the user."""

    pass


class NoNotesError(Exception):
    """Raised when no notes exist in the active source."""

    pass


class ReflectionService:
    def __init__(
        self,
        reflection_repository: ReflectionRepository,
        voice_notes_repository: VoiceNotesRepository,
        sources_repository: SourcesRepository,
        model: ChatOpenAI,
    ) -> None:
        self._reflection_repository = reflection_repository
        self._voice_notes_repository = voice_notes_repository
        self._sources_repository = sources_repository
        self._model = model

    async def start_reflection(self, telegram_user_id: int) -> ReflectionQuestionResult:
        """Start a new reflection session.

        1. Cancel any existing pending reflection for this user
        2. Get active source; raise if none
        3. Fetch last N notes from active source
        4. Raise if no notes found
        5. Call LLM to generate question (type + text)
        6. Create reflections row (status='pending')
        7. Return question text for the bot to send
        """
        # Cancel any existing pending reflection
        await self.cancel_pending_reflection(telegram_user_id)

        # Get active source
        active_source = await self._sources_repository.get_active_source()
        if not active_source:
            raise NoActiveSourceError("No active source found for user")

        # Fetch last N notes from active source
        notes = await self._voice_notes_repository.list_voice_notes(
            source_id=active_source["id"],
            limit=settings.REFLECTION_NOTES_COUNT,
        )

        if not notes:
            raise NoNotesError("No notes found in active source")

        # Generate question via LLM
        question_type, question_text = await self._generate_question(notes)

        # Create reflection row
        reflection = await self._reflection_repository.create_reflection(
            telegram_user_id=telegram_user_id,
            voice_note_id=None,  # Question may synthesize multiple notes
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
        2. Call LLM to rate answer + generate feedback
        3. Update reflections row (status='completed', rating, feedback, answer_text, completed_at)
        4. Return rating + feedback for the bot to send
        """
        # Find pending reflection
        pending = await self.get_pending_reflection(telegram_user_id)
        if not pending:
            raise NoNotesError("No pending reflection found")

        # Fetch notes for context
        active_source = await self._sources_repository.get_active_source()
        notes: list[dict[str, Any]] = []
        if active_source:
            notes = await self._voice_notes_repository.list_voice_notes(
                source_id=active_source["id"],
                limit=settings.REFLECTION_NOTES_COUNT,
            )

        # Rate the answer
        rating, feedback = await self._rate_answer(
            question_type=pending.question_type,
            question_text=pending.question_text,
            answer_text=answer_text,
            notes=notes,
        )

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

    async def _generate_question(self, notes: list[dict[str, Any]]) -> tuple[str, str]:
        """Call LLM to generate a reflection question based on notes."""
        notes_text = "\n\n".join(
            f"- {note.get('raw_text', note.get('clean_text', ''))}" for note in notes
        )
        prompt = QUESTION_GENERATION_PROMPT.format(notes=notes_text)

        response = self._model.invoke(prompt)
        content = str(response.content)

        # Parse JSON response
        try:
            # Try to extract JSON from the response
            json_str = content
            if "```json" in content:
                json_str = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                json_str = content.split("```")[1].split("```")[0]

            parsed = json.loads(json_str.strip())
            question_type = parsed.get("question_type", "reflective")
            question_text = parsed.get("question_text", "What did you learn from these notes?")
            return question_type, question_text
        except (json.JSONDecodeError, IndexError, KeyError) as exc:
            logger.warning("reflection.question_parse_failed", extra={"error": str(exc)})
            # Fallback
            return "reflective", "What did you learn from these notes?"

    async def _rate_answer(
        self,
        question_type: str,
        question_text: str,
        answer_text: str,
        notes: list[dict[str, Any]],
    ) -> tuple[int, str]:
        """Call LLM to rate the user's answer and generate feedback."""
        notes_text = "\n\n".join(
            f"- {note.get('raw_text', note.get('clean_text', ''))}" for note in notes
        ) or "No notes available."

        prompt = RATING_PROMPT.format(
            question_text=question_text,
            question_type=question_type,
            answer_text=answer_text,
            notes=notes_text,
        )

        response = self._model.invoke(prompt)
        content = str(response.content)

        # Parse JSON response
        try:
            # Try to extract JSON from the response
            json_str = content
            if "```json" in content:
                json_str = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                json_str = content.split("```")[1].split("```")[0]

            parsed = json.loads(json_str.strip())
            rating = max(1, min(10, int(parsed.get("rating", 5))))
            feedback = parsed.get("feedback", "Good effort!")
            return rating, feedback
        except (json.JSONDecodeError, IndexError, KeyError, ValueError) as exc:
            logger.warning("reflection.rating_parse_failed", extra={"error": str(exc)})
            # Fallback
            return 5, "Good effort! Try to be more specific in your answer."
