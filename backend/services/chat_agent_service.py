"""Chat agent service powered by a LangGraph StateGraph."""

from __future__ import annotations

from typing import Annotated, TypedDict

from loguru import logger
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from backend.repositories.chat_memory_repository import ChatMemoryRepository
from configuration.settings import settings

SYSTEM_PROMPT = "You are a helpful assistant for a personal voice note app."
AGENT_ERROR_RESPONSE = "❌ Agent error. Please try again."


class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]


class ChatAgentService:

    def __init__(
        self,
        memory_repository: ChatMemoryRepository | None = None,
        max_memory_messages: int = settings.AGENT_MAX_MEMORY_MESSAGES,
    ) -> None:
        self._model = ChatOpenAI(
            model= settings.AGENT_LLM_MODEL,
            api_key=settings.OPENAI_API_KEY,
        )
        self._memory_repository = memory_repository
        self._max_memory_messages = max_memory_messages
        graph = StateGraph(AgentState)
        graph.add_node("call_model", self._call_model)
        graph.add_edge(START, "call_model")
        graph.add_edge("call_model", END)
        self._graph = graph.compile()

    def _call_model(self, state: AgentState) -> AgentState:
        response = self._model.invoke(state["messages"])
        return {"messages": [response]}

    async def get_response(self, user_message: str, telegram_user_id: int | None = None) -> str:
        try:
            history_messages: list[BaseMessage] = []
            if telegram_user_id is not None and self._memory_repository is not None:
                try:
                    history_entries = await self._memory_repository.get_last_n_messages(
                        telegram_user_id, self._max_memory_messages
                    )
                    for entry in history_entries:
                        if entry.role == "assistant":
                            history_messages.append(AIMessage(content=entry.content))
                        else:
                            history_messages.append(HumanMessage(content=entry.content))
                except Exception as exc:
                    logger.error(
                        "chat_agent.memory.fetch_failed",
                        extra={
                            "telegram_user_id": telegram_user_id,
                            "error": str(exc),
                        },
                    )
            initial_state: AgentState = {
                "messages": [SystemMessage(content=SYSTEM_PROMPT)]
                + history_messages
                + [HumanMessage(content=user_message)]
            }
            result = await self._graph.ainvoke(initial_state)
            messages = result.get("messages") or []
            if not messages:
                return ""
            response_text = str(messages[-1].content)
            if telegram_user_id is not None and self._memory_repository is not None:
                try:
                    await self._memory_repository.save_message(
                        telegram_user_id, "user", user_message
                    )
                except Exception as exc:
                    logger.error(
                        "chat_agent.memory.save_failed",
                        extra={
                            "telegram_user_id": telegram_user_id,
                            "role": "user",
                            "error": str(exc),
                        },
                    )
                try:
                    await self._memory_repository.save_message(
                        telegram_user_id, "assistant", response_text
                    )
                except Exception as exc:
                    logger.error(
                        "chat_agent.memory.save_failed",
                        extra={
                            "telegram_user_id": telegram_user_id,
                            "role": "assistant",
                            "error": str(exc),
                        },
                    )
            return response_text
        except Exception:
            return AGENT_ERROR_RESPONSE
