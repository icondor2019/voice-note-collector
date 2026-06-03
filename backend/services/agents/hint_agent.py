"""HintAgent: provides Socratic hints without revealing the answer."""

from __future__ import annotations

from typing import TYPE_CHECKING

from langchain_openai import ChatOpenAI

from backend.models.agent import AgentResult

if TYPE_CHECKING:
    pass

HINT_PROMPT = """You are a Socratic reflection helper. The user is trying to remember a personal
voice note and only asked for help.

Note (for context only — do NOT reveal verbatim):
{note}

Question being asked:
{question}

User's request (e.g. "give me a hint", "I don't remember", "what was it about?"):
{user_message}

Rules:
- Detect the language of the note above and write your reply in that language.
- Never reveal the answer or the main idea directly.
- Prefer a one-to-three-word hint that triggers recall (matching the note's domain).
- If the user explicitly asks for the note's context, return a short summary
  (2-3 sentences) that paraphrases the note without giving the answer.
- Do not introduce outside knowledge, examples, or follow-up topics.
- Do not pose new questions.
- Keep it under 50 words."""


class HintAgent:
    """Provides Socratic hints without revealing the answer directly."""

    def __init__(self, model: ChatOpenAI) -> None:
        self._model = model

    async def run(
        self,
        note_text: str,
        question_text: str,
        user_message: str,
    ) -> AgentResult:
        """Generate a Socratic hint.

        Returns AgentResult with outcome="hinted", reply=socratic_text.
        """
        prompt = HINT_PROMPT.format(
            note=note_text,
            question=question_text,
            user_message=user_message,
        )

        response = self._model.invoke(prompt)
        content = str(response.content).strip()

        return AgentResult(
            reply=content,
            outcome="hinted",
            updates={},
        )
