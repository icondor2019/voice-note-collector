"""Chat agent service powered by a LangGraph StateGraph."""

from __future__ import annotations

from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from configuration.settings import settings

SYSTEM_PROMPT = "You are a helpful assistant for a personal voice note app."
AGENT_ERROR_RESPONSE = "❌ Agent error. Please try again."


class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]


class ChatAgentService:
    def __init__(self) -> None:
        self._model = ChatOpenAI(
            model="gpt-4o-mini",
            api_key=settings.OPENAI_API_KEY,
        )
        graph = StateGraph(AgentState)
        graph.add_node("call_model", self._call_model)
        graph.add_edge(START, "call_model")
        graph.add_edge("call_model", END)
        self._graph = graph.compile()

    def _call_model(self, state: AgentState) -> AgentState:
        response = self._model.invoke(state["messages"])
        return {"messages": [response]}

    async def get_response(self, user_message: str) -> str:
        try:
            initial_state: AgentState = {
                "messages": [
                    SystemMessage(content=SYSTEM_PROMPT),
                    HumanMessage(content=user_message),
                ]
            }
            result = await self._graph.ainvoke(initial_state)
            messages = result.get("messages") or []
            if not messages:
                return ""
            return str(messages[-1].content)
        except Exception:
            return AGENT_ERROR_RESPONSE
