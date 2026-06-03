"""QuestionAgent: generates a reflection question from a voice note."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from langchain_openai import ChatOpenAI
from loguru import logger

from backend.models.agent import AgentResult

if TYPE_CHECKING:
    pass

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


class QuestionAgent:
    """Generates a reflection question from a single voice note."""

    def __init__(self, model: ChatOpenAI) -> None:
        self._model = model

    async def run(self, note: dict[str, Any]) -> AgentResult:
        """Generate a question for the given note.

        Returns AgentResult with outcome="asked", reply=question_text,
        and updates containing question_type and question_text.
        """
        note_text = note.get("raw_text") or note.get("clean_text", "")
        prompt = QUESTION_GENERATION_PROMPT.format(note=note_text)

        response = self._model.invoke(prompt)
        content = str(response.content)

        try:
            json_str = content
            if "```json" in content:
                json_str = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                json_str = content.split("```")[1].split("```")[0]

            parsed = json.loads(json_str.strip())
            question_type = parsed.get("question_type", "reflective")
            question_text = parsed.get(
                "question_text", "What did you learn from this note?"
            )
        except (json.JSONDecodeError, IndexError, KeyError) as exc:
            logger.warning(
                "question_agent.parse_failed", extra={"error": str(exc)}
            )
            question_type = "reflective"
            question_text = "What did you learn from this note?"

        return AgentResult(
            reply=question_text,
            outcome="asked",
            updates={
                "question_type": question_type,
                "question_text": question_text,
            },
        )
