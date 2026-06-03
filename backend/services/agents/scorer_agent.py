"""ScorerAgent: rates a user's answer to a reflection question."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from langchain_openai import ChatOpenAI
from loguru import logger

from backend.models.agent import AgentResult

if TYPE_CHECKING:
    pass

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


class ScorerAgent:
    """Rates a user's answer to a reflection question and provides feedback."""

    def __init__(self, model: ChatOpenAI) -> None:
        self._model = model

    async def run(
        self,
        question_type: str,
        question_text: str,
        answer_text: str,
        note: dict[str, Any],
    ) -> AgentResult:
        """Score the answer against the original note.

        Returns AgentResult with outcome="scored", reply=feedback,
        and updates containing rating.
        """
        note_text = (
            note.get("raw_text")
            or note.get("clean_text", "")
            or "No notes available."
        )

        prompt = RATING_PROMPT.format(
            question_text=question_text,
            question_type=question_type,
            answer_text=answer_text,
            note=note_text,
        )

        response = self._model.invoke(prompt)
        content = str(response.content)

        try:
            json_str = content
            if "```json" in content:
                json_str = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                json_str = content.split("```")[1].split("```")[0]

            parsed = json.loads(json_str.strip())
            rating = max(1, min(10, int(parsed.get("rating", 5))))
            feedback = parsed.get("feedback", "Good effort!")
        except (json.JSONDecodeError, IndexError, KeyError, ValueError) as exc:
            logger.warning(
                "scorer_agent.parse_failed", extra={"error": str(exc)}
            )
            rating = 5
            feedback = "Good effort! Try to be more specific in your answer."

        return AgentResult(
            reply=feedback,
            outcome="scored",
            updates={"rating": rating},
        )
