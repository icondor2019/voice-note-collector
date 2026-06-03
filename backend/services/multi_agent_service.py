"""Multi-agent service: supervisor + sub-graphs for chat and reflection."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Optional

from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from loguru import logger

from backend.models.agent import AgentMode, AgentState, MultiAgentResult, ReflectionContext
from backend.repositories.chat_memory_repository import ChatMemoryRepository
from backend.repositories.reflection_repository import ReflectionRepository
from backend.repositories.sources_repository import SourcesRepository
from backend.services.chat_mode_service import ChatModeService
from backend.services.note_selector_service import NoteSelectorService
from backend.services.telegram_command_handler import REFLECTION_FEEDBACK_TEMPLATE

if TYPE_CHECKING:
    from backend.services.agents.hint_agent import HintAgent
    from backend.services.agents.question_agent import QuestionAgent
    from backend.services.agents.scorer_agent import ScorerAgent
    from backend.services.chat_agent_service import ChatAgentService
    from backend.services.reflection_service import ReflectionService

INTENT_CLASSIFIER_PROMPT = """You classify the user's message in the context of an active reflection.

Question: {question}
Note preview: {note_text}
User message: {user_message}

Classify the intent as one of:
- HINT: user wants help recalling (e.g. "give me a hint", "I don't remember", "any clue?")
- CONTEXT: user wants the note's content (e.g. "what was that note about?", "show me the note", "remind me")
- ANSWER: default for anything else; the user's message is treated as the final answer (including phrases like "I'm done", "that's my answer", "final answer", "I think the answer is")

Return JSON:
{{
  "intent": "HINT" | "CONTEXT" | "ANSWER",
  "answer_text": "<the verbatim user message>"
}}"""

_CONTEXT_BANNER = "📋 Here's what the note said:\n\n"
_CONTEXT_TRUNCATE = 500


class MultiAgentService:
    """Unified entry point that supervises chat and reflection sub-graphs.

    Flat StateGraph:  supervisor_node → chat_node | reflect_node → END.
    """

    def __init__(
        self,
        chat_agent: "ChatAgentService",
        reflection_service: "ReflectionService",
        question_agent: "QuestionAgent",
        scorer_agent: "ScorerAgent",
        hint_agent: "HintAgent",
        chat_mode_service: ChatModeService,
        sources_repository: SourcesRepository,
        note_selector_service: NoteSelectorService,
        memory_repository: ChatMemoryRepository,
        agent_model: ChatOpenAI,
    ) -> None:
        self._chat_agent = chat_agent
        self._reflection_service = reflection_service
        self._reflection_repository: ReflectionRepository = (
            reflection_service.reflection_repository
        )
        self._question_agent = question_agent
        self._scorer_agent = scorer_agent
        self._hint_agent = hint_agent
        self._mode_service = chat_mode_service
        self._sources_repository = sources_repository
        self._note_selector_service = note_selector_service
        self._memory_repository = memory_repository
        self._agent_model = agent_model

        # Build flat graph
        graph = StateGraph(AgentState)
        graph.add_node("supervisor", self._supervisor_node)
        graph.add_node("chat_node", self._chat_node)
        graph.add_node("reflect_node", self._reflect_node)

        graph.add_edge(START, "supervisor")
        graph.add_conditional_edges(
            "supervisor",
            self._route_supervisor,
            {
                "chat_node": "chat_node",
                "reflect_node": "reflect_node",
                "__end__": END,
            },
        )
        graph.add_edge("chat_node", END)
        graph.add_edge("reflect_node", END)

        self._graph = graph.compile()

    # ------------------------------------------------------------------ #
    #  Public API
    # ------------------------------------------------------------------ #

    async def handle(
        self, user_message: str, telegram_user_id: int
    ) -> MultiAgentResult:
        """Hydrate state, invoke the graph, and return a result."""

        # 1. Hydrate pending_reflection from DB
        pending = await self._hydrate_pending_reflection(telegram_user_id)

        # 2. Build initial state
        state: AgentState = {
            "messages": [HumanMessage(content=user_message)],
            "telegram_user_id": telegram_user_id,
            "mode": self._mode_service.get_mode(),  # type: ignore[typeddict-item]
            "pending_reflection": pending,
            "last_outcome": None,
            "last_reply": None,
        }

        # 3. Invoke
        final_state = await self._graph.ainvoke(state)

        return MultiAgentResult(
            reply=final_state.get("last_reply", "") or "",
            outcome=final_state.get("last_outcome", "chat_reply") or "chat_reply",
        )

    # ------------------------------------------------------------------ #
    #  Supervisor
    # ------------------------------------------------------------------ #

    @staticmethod
    def _supervisor_node(state: AgentState) -> dict:
        """Deterministic router — no LLM call."""
        mode = state.get("mode", "note")
        if mode == "agent":
            return {"next": "chat_node"}
        if mode == "reflect":
            return {"next": "reflect_node"}
        return {"next": "__end__"}

    @staticmethod
    def _route_supervisor(state: AgentState) -> str:
        return MultiAgentService._supervisor_node(state).get("next", "__end__")

    # ------------------------------------------------------------------ #
    #  Chat node
    # ------------------------------------------------------------------ #

    async def _chat_node(self, state: AgentState) -> dict:
        """Wrap existing ChatAgentService.get_response()."""
        user_message = ""
        msgs = state.get("messages", [])
        if msgs:
            user_message = str(msgs[-1].content)

        telegram_user_id: int = state.get("telegram_user_id", 0)

        try:
            response = await self._chat_agent.get_response(
                user_message, telegram_user_id=telegram_user_id
            )
        except Exception:
            response = "❌ Agent error. Please try again."

        return {"last_reply": response, "last_outcome": "chat_reply"}

    # ------------------------------------------------------------------ #
    #  Reflect node (flat dispatch via Python if/else)
    # ------------------------------------------------------------------ #

    async def _reflect_node(self, state: AgentState) -> dict:
        pending: Optional[ReflectionContext] = state.get("pending_reflection")

        # Check for slash commands at the top — cancels even if no pending is active
        msgs = state.get("messages", [])
        user_message = str(msgs[-1].content) if msgs else ""
        if user_message.startswith("/"):
            return await self._cancel_reflection(state)

        if pending is None:
            return await self._start_reflection(state)

        return await self._classify_and_route(state, user_message)

    # ------------------------------------------------------------------ #
    #  Reflection sub-nodes
    # ------------------------------------------------------------------ #

    async def _start_reflection(self, state: AgentState) -> dict:
        """Pick a note, generate a question, persist, return question text."""
        telegram_user_id: int = state.get("telegram_user_id", 0)

        # Resolve active source
        active_source = await self._sources_repository.get_active_source()
        if not active_source:
            self._mode_service.set_mode("agent")
            return {
                "last_reply": "⚠️ No active source. Use /switch or /default to set one.",
                "last_outcome": "no_active_source",
                "pending_reflection": None,
            }

        # Pick a note
        note = await self._note_selector_service.pick_note(active_source["id"])
        if note is None:
            self._mode_service.set_mode("agent")
            source_name = active_source.get("source_name", "your source")
            return {
                "last_reply": f"🎉 You've reviewed all notes from {source_name}!",
                "last_outcome": "exhausted",
                "pending_reflection": None,
            }

        note_text = note.get("raw_text") or note.get("clean_text", "")

        # Generate question
        result = await self._question_agent.run(note)
        question_type = result.updates.get("question_type", "reflective")
        question_text = result.reply

        # Persist
        try:
            reflection = await self._reflection_repository.create_reflection(
                telegram_user_id=telegram_user_id,
                voice_note_id=note["id"],
                question_type=question_type,
                question_text=question_text,
            )
            reflection_id = str(reflection["id"])
        except Exception as exc:
            logger.error(
                "multi_agent.create_reflection_failed",
                extra={"error": str(exc), "telegram_user_id": telegram_user_id},
            )
            return {
                "last_reply": "⚠️ Failed to start reflection. Please try again.",
                "last_outcome": "error",
                "pending_reflection": None,
            }

        pending: ReflectionContext = {
            "reflection_id": reflection_id,
            "voice_note_id": str(note["id"]),
            "note_text": note_text,
            "question_type": question_type,
            "question_text": question_text,
            "hint_used": False,
            "context_shown": False,
        }

        return {
            "last_reply": question_text,
            "last_outcome": "asked",
            "pending_reflection": pending,
        }

    async def _cancel_reflection(self, state: AgentState) -> dict:
        """Cancel the pending reflection and exit reflect mode."""
        telegram_user_id: int = state.get("telegram_user_id", 0)
        try:
            await self._reflection_service.cancel_pending_reflection(telegram_user_id)
        except Exception as exc:
            logger.warning(
                "multi_agent.cancel_failed",
                extra={"error": str(exc), "telegram_user_id": telegram_user_id},
            )

        self._mode_service.set_mode("agent")
        return {
            "last_reply": "Reflection cancelled.",
            "last_outcome": "cancelled",
            "pending_reflection": None,
            "mode": "agent",
        }

    async def _classify_and_route(
        self, state: AgentState, user_message: str
    ) -> dict:
        """Classify user intent and dispatch to hint/context/answer."""
        pending = state.get("pending_reflection")
        if pending is None:
            # Shouldn't happen, but defensive
            return await self._start_reflection(state)

        question = pending.get("question_text", "")
        note_text = pending.get("note_text", "")

        intent = await self._classify_intent(
            question=question,
            note_text=note_text[:200],
            user_message=user_message,
        )

        if intent == "HINT":
            return await self._hint(state, user_message)
        elif intent == "CONTEXT":
            return await self._context(state)
        else:
            return await self._answer(state, user_message)

    async def _classify_intent(
        self,
        question: str,
        note_text: str,
        user_message: str,
    ) -> str:
        """Small LLM call to classify user intent as HINT | CONTEXT | ANSWER."""
        prompt = INTENT_CLASSIFIER_PROMPT.format(
            question=question,
            note_text=note_text,
            user_message=user_message,
        )

        try:
            response = self._agent_model.invoke(prompt)
            content = str(response.content)

            # Parse JSON
            json_str = content
            if "```json" in content:
                json_str = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                json_str = content.split("```")[1].split("```")[0]

            parsed = json.loads(json_str.strip())
            intent = parsed.get("intent", "ANSWER")
            if intent not in ("HINT", "CONTEXT", "ANSWER"):
                intent = "ANSWER"
            return intent
        except (json.JSONDecodeError, IndexError, KeyError) as exc:
            logger.warning(
                "multi_agent.intent_parse_failed",
                extra={"error": str(exc)},
            )
            return "ANSWER"

    async def _hint(self, state: AgentState, user_message: str) -> dict:
        """Provide a Socratic hint."""
        pending: Optional[ReflectionContext] = state.get("pending_reflection")
        if pending is None:
            return await self._start_reflection(state)

        note_text = pending.get("note_text", "")
        question_text = pending.get("question_text", "")

        result = await self._hint_agent.run(note_text, question_text, user_message)

        # Mark hint used
        pending["hint_used"] = True

        return {
            "last_reply": result.reply,
            "last_outcome": "hinted",
            "pending_reflection": pending,
        }

    async def _context(self, state: AgentState) -> dict:
        """Return the note text (no LLM call)."""
        pending: Optional[ReflectionContext] = state.get("pending_reflection")
        if pending is None:
            return await self._start_reflection(state)

        note_text = pending.get("note_text", "")
        if len(note_text) > _CONTEXT_TRUNCATE:
            note_text = note_text[:_CONTEXT_TRUNCATE] + "..."

        # Mark context shown
        pending["context_shown"] = True

        return {
            "last_reply": _CONTEXT_BANNER + note_text,
            "last_outcome": "context_shown",
            "pending_reflection": pending,
        }

    async def _answer(self, state: AgentState, user_message: str) -> dict:
        """Score the answer, persist, and auto-loop to next question."""
        pending: Optional[ReflectionContext] = state.get("pending_reflection")
        if pending is None:
            return await self._start_reflection(state)

        telegram_user_id: int = state.get("telegram_user_id", 0)

        # Build note dict for scorer
        note_text = pending.get("note_text", "")
        note: dict[str, Any] = {"raw_text": note_text, "clean_text": note_text}

        # Score
        result = await self._scorer_agent.run(
            question_type=pending.get("question_type", "reflective"),
            question_text=pending.get("question_text", ""),
            answer_text=user_message,
            note=note,
        )
        rating = result.updates.get("rating", 5)
        feedback = result.reply

        # Persist
        try:
            await self._reflection_repository.complete_reflection(
                reflection_id=pending.get("reflection_id", ""),
                answer_text=user_message,
                rating=rating,
                feedback=feedback,
            )
        except Exception as exc:
            logger.error(
                "multi_agent.complete_reflection_failed",
                extra={"error": str(exc), "telegram_user_id": telegram_user_id},
            )

        reply = REFLECTION_FEEDBACK_TEMPLATE.format(rating=rating, feedback=feedback)
        outcome = "scored"

        # ------------------------------------------------------------------ #
        #  Auto-loop: start the next reflection immediately
        # ------------------------------------------------------------------ #
        # Build a fresh state snippet so _start_reflection can work
        auto_state: AgentState = {
            "messages": state.get("messages", []),
            "telegram_user_id": telegram_user_id,
            "mode": "reflect",  # type: ignore[typeddict-item]
            "pending_reflection": None,  # will be set by _start_reflection
        }
        auto_result = await self._start_reflection(auto_state)

        auto_outcome = auto_result.get("last_outcome", "")
        next_pending: Optional[ReflectionContext] = auto_result.get(
            "pending_reflection"
        )

        if auto_outcome == "asked" and next_pending is not None:
            # Append next question
            reply += f"\n\n🧠 Next one:\n\n{auto_result['last_reply']}"
            pending = next_pending
        elif auto_outcome == "exhausted":
            # No more notes — exit reflect mode
            reply += f"\n\n{auto_result['last_reply']}"
            pending = None
            outcome = "exhausted"
        else:
            # Error or no active source → exit reflect mode
            pending = None
            outcome = "scored"

        return {
            "last_reply": reply,
            "last_outcome": outcome,
            "pending_reflection": pending,
        }

    # ------------------------------------------------------------------ #
    #  Helpers
    # ------------------------------------------------------------------ #

    async def _hydrate_pending_reflection(
        self, telegram_user_id: int
    ) -> Optional[ReflectionContext]:
        """Look up the user's pending reflection from the DB."""
        entry = await self._reflection_service.get_pending_reflection(
            telegram_user_id
        )
        if entry is None:
            return None

        # Fetch note text for the hint/context nodes
        note_text = ""
        if entry.voice_note_id:
            try:
                client = self._reflection_repository._client
                note_response = (
                    await client.table("voice_notes")
                    .select("*")
                    .eq("id", entry.voice_note_id)
                    .maybe_single()
                    .execute()
                )
                if note_response and note_response.data:
                    note_data = (
                        note_response.data[0]
                        if isinstance(note_response.data, list)
                        else note_response.data
                    )
                    note_text = note_data.get("raw_text") or note_data.get(
                        "clean_text", ""
                    )
            except Exception as exc:
                logger.warning(
                    "multi_agent.hydrate_note_failed",
                    extra={"error": str(exc)},
                )

        return ReflectionContext(
            reflection_id=str(entry.id),
            voice_note_id=str(entry.voice_note_id) if entry.voice_note_id else "",
            note_text=note_text,
            question_type=entry.question_type,
            question_text=entry.question_text,
            hint_used=False,
            context_shown=False,
        )
