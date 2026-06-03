"""Multi-agent state models for the unified MultiAgentService."""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Any, Literal, Optional, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field


class AgentMode(str, Enum):
    NOTE = "note"
    AGENT = "agent"
    REFLECT = "reflect"


class ReflectionContext(TypedDict, total=False):
    """Lightweight reflection context carried in AgentState."""

    reflection_id: str
    voice_note_id: str
    note_text: str
    question_type: str
    question_text: str
    hint_used: bool
    context_shown: bool


class AgentState(TypedDict, total=False):
    """Shared state for the supervisor and sub-graphs."""

    messages: Annotated[list[BaseMessage], add_messages]
    telegram_user_id: int
    mode: Literal["note", "agent", "reflect"]
    pending_reflection: Optional[ReflectionContext]
    last_outcome: Optional[str]
    last_reply: Optional[str]


class AgentResult(BaseModel):
    """Result returned by each sub-agent."""

    reply: str
    outcome: str
    updates: dict[str, Any] = Field(default_factory=dict)


class MultiAgentResult(BaseModel):
    """Result returned by MultiAgentService.handle()."""

    reply: str
    outcome: str
