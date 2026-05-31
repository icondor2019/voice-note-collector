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
    ReflectionSummary,
)
from backend.repositories.reflection_repository import ReflectionRepository
from backend.repositories.sources_repository import SourcesRepository
from backend.repositories.voice_notes_repository import VoiceNotesRepository
from configuration.settings import settings

if TYPE_CHECKING:
    from uuid import UUID


QUESTION_GENERATION_PROMPT = """You are a reflection assistant for a personal voice note app.

Your goal is NOT to test general knowledge, intelligence, reasoning ability, or mastery of a topic.

Your goal is to help the user recall the context, observation, example, idea, or conclusion captured in this specific note.

The note may be old, incomplete, contain only an example, a thought, a reminder, or a partial observation. Assume the user may have forgotten most of the original context.

When generating a question:

- Include a very brief reminder of the note's context before asking the question.
- The context reminder should be short (one sentence) and should help the user identify the note.
- Ask about the note itself, not about general knowledge.
- Prefer questions that test whether the user remembers why the note was recorded.
- Prefer questions that recover the original context, observation, example, insight, or conclusion.
- Avoid generic reflective questions that could be answered without remembering the note.
- Avoid asking for information that is not present or implied in the note.
- Do not require word-for-word recall.
- A good answer should demonstrate that the user remembers what the note was about and why it mattered.

Choose the most appropriate question type from these categories:
- follow-up: Ask about the implication or intended next step captured in the note
- reflective: Ask why the observation or idea in the note mattered to the user
- quiz: Test recall of a key detail, example, observation, or conclusion from the note
- elaboration: Ask the user to explain the idea they were trying to capture in the note
- comparison: Ask the user to distinguish or relate ideas mentioned in the note

the question structure should include this sections format already:
- 🧠 context: brief context about the note

- 🤔 question: the question you decide to formulate

- 🔎 hint: a main idea your spect in the answer (one to three words max)

Note:
{note}

Respond in JSON format:
{{
  "question_type": "<one of: follow-up, reflective, quiz, elaboration, comparison>",
  "question_text": "<your question>"
}}"""


RATING_PROMPT = """You are evaluating how well the user remembers the original context and meaning of a personal voice note.

This is NOT a test of intelligence, writing quality, communication skills, expertise, or general knowledge.

The only thing being evaluated is how much evidence the answer provides that the user still remembers the context, observation, example, idea, or conclusion captured in the note.

The user does NOT need to remember the note word-for-word.

A strong answer:
- Recalls the original context of the note.
- Recalls the main observation, example, insight, or conclusion.
- Demonstrates clear recognition of what the note was about.

A weak answer:
- Is generic enough that it could have been written without remembering the note.
- Relies on general knowledge instead of the note's content.
- Misses the main context or purpose of the note.

Scoring guidelines:

10 = Clearly remembers both the context and the main idea of the note.
9 = Remembers almost all important context and meaning.
8 = Remembers the main idea and most of the context.
7 = Remembers the core idea but misses some relevant context.
6 = Shows partial recognition of the note but important elements are missing.
5 = Vaguely related to the note but demonstrates limited recall.
4 = Mostly generic response with little evidence of remembering the note.
3 = Very weak recall of the note's context.
2 = Almost no evidence of remembering the note.
1 = Does not appear to remember the note or directly contradicts it.

You asked the user this question:
{question_text}
Question type: {question_type}

The user's answer:
{answer_text}

Original note for reference:
{note}

Rate the answer from 1 to 10 and provide structured feedback using ONLY bullet points.

Write as if you are talking directly to the user.

IMPORTANT:
- Always use "you", never "the user".
- Keep feedback concise and scannable.
- Use short bullet points, not paragraphs.
- Each bullet should contain only one key idea.
- Focus on recall of the note's context and meaning.
- Do not comment on writing quality, grammar, or communication style.
- Limit each section to 2-4 bullets.
- Prefer concrete observations over generic encouragement.

Format your feedback in these sections:

- ✅ What you remembered
  - Mention the parts of the note you successfully recalled.
  - Use short bullet points.
  - Be specific.

- ❌ What was missing
  - Identify important context, examples, observations, or conclusions that were not recovered.
  - Use short bullet points.
  - Focus on missing recall, not mistakes in reasoning.

- 🎯 Key takeaway
  - Provide 1-3 short bullet points.
  - Reinforce the most important idea, context, or conclusion from the note.
  - Help the user remember why this note was worth saving.

  
Remember, never evalute things that are not explicitly included in the note.  
Respond in JSON format:
{{
  "rating": <integer 1-10>,
  "feedback": "✅ ...\n\n❌ ...\n\n🎯 ..."
}}"""


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
        model: ChatOpenAI,
        note_selector_service: Any,  # NoteSelectorService
    ) -> None:
        self._reflection_repository = reflection_repository
        self._sources_repository = sources_repository
        self._model = model
        self._note_selector_service = note_selector_service

    async def start_reflection(self, telegram_user_id: int) -> ReflectionQuestionResult:
        """Start a new reflection session.

        1. Cancel any existing pending reflection for this user
        2. Get active source; raise if none
        3. Use NoteSelectorService to pick a note
        4. If pick_note returns None, raise AllNotesInternalizedError
        5. Call LLM to generate question (type + text) for single note
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

        # Generate question via LLM (single note)
        question_type, question_text = await self._generate_question(note)

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
        3. Call LLM to rate answer + generate feedback
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
                note = voice_note_response.data[0] if isinstance(voice_note_response.data, list) else voice_note_response.data

        # Rate the answer
        rating, feedback = await self._rate_answer(
            question_type=pending.question_type,
            question_text=pending.question_text,
            answer_text=answer_text,
            note=note,
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

    async def _generate_question(self, note: dict[str, Any]) -> tuple[str, str]:
        """Call LLM to generate a reflection question based on a single note."""
        note_text = note.get("raw_text") or note.get("clean_text", "")
        prompt = QUESTION_GENERATION_PROMPT.format(note=note_text)

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
            question_text = parsed.get("question_text", "What did you learn from this note?")
            return question_type, question_text
        except (json.JSONDecodeError, IndexError, KeyError) as exc:
            logger.warning("reflection.question_parse_failed", extra={"error": str(exc)})
            # Fallback
            return "reflective", "What did you learn from this note?"

    async def _rate_answer(
        self,
        question_type: str,
        question_text: str,
        answer_text: str,
        note: dict[str, Any],
    ) -> tuple[int, str]:
        """Call LLM to rate the user's answer and generate feedback."""
        note_text = note.get("raw_text") or note.get("clean_text", "") or "No notes available."

        prompt = RATING_PROMPT.format(
            question_text=question_text,
            question_type=question_type,
            answer_text=answer_text,
            note=note_text,
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
