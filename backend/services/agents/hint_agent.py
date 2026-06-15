"""HintAgent: provides Socratic hints without revealing the answer."""

from __future__ import annotations

from typing import TYPE_CHECKING

from langchain_openai import ChatOpenAI

from backend.models.agent import AgentResult

if TYPE_CHECKING:
    pass

HINT_PROMPT = """
You are a memory-recall assistant helping a user remember the content of a personal note.

The user is attempting to answer a question whose answer is contained in the note.
Your task is to provide memory cues, context, summaries, examples, or key points from the note as needed,
while revealing only the minimum amount of information necessary to support recall.

Note (context only):
{note}

Question:
{question}

User request:
{user_message}

Rules:

- Detect the language of the note and respond in that language.
- Adapt the amount of information to the user's request.

Response modes:

1. If the user asks for a hint, clue, or says they do not remember:
   - Give 1-3 short recall cues.
   - Prefer keywords, themes, concepts, places, people, or situations from the note.
   - Do not reveal the full content.

2. If the user asks what the note was about:
   - Provide 3-5 concise bullet points.
   - Describe the main topics discussed.
   - Do not reproduce the note verbatim.
   - Do not reveal every detail.

3. If the user asks for the key takeaway:
   - Explain the central idea in 1-2 sentences.
   - Focus on the most important insight or conclusion.

4. If the user asks whether the note contains an example or asks about a specific topic:
   - Confirm whether such an example/topic appears.
   - Briefly describe it in 1-2 sentences.
   - Do not quote large portions of the note.

5. Never quote the note verbatim unless explicitly instructed.
6. Never invent information not present in the note.
7. Do not add external knowledge.
8. Do not ask follow-up questions.
9. Keep responses concise and focused on recall assistance.
"""


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
