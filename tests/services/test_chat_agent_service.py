from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from backend.services.chat_agent_service import (
    AGENT_ERROR_RESPONSE,
    SYSTEM_PROMPT,
    ChatAgentService,
)


@pytest.fixture(autouse=True)
def _set_openai_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")


@pytest.mark.anyio
async def test_get_response_returns_llm_content() -> None:
    service = ChatAgentService()
    service._graph = AsyncMock()
    service._graph.ainvoke = AsyncMock(
        return_value={
            "messages": [
                SystemMessage(content=SYSTEM_PROMPT),
                HumanMessage(content="hello"),
                AIMessage(content="hi there"),
            ]
        }
    )

    response = await service.get_response("hello")

    assert response == "hi there"


@pytest.mark.anyio
async def test_get_response_passes_system_and_human_messages() -> None:
    service = ChatAgentService()
    service._graph = AsyncMock()
    service._graph.ainvoke = AsyncMock(
        return_value={"messages": [AIMessage(content="ok")]}
    )

    await service.get_response("user text")

    assert service._graph.ainvoke.await_count == 1
    call_state = service._graph.ainvoke.call_args.args[0]
    messages = call_state["messages"]
    assert isinstance(messages[0], SystemMessage)
    assert messages[0].content == SYSTEM_PROMPT
    assert isinstance(messages[1], HumanMessage)
    assert messages[1].content == "user text"


@pytest.mark.anyio
async def test_get_response_on_exception_returns_error_string() -> None:
    service = ChatAgentService()
    service._graph = AsyncMock()
    service._graph.ainvoke = AsyncMock(side_effect=Exception("boom"))

    response = await service.get_response("hi")

    assert response == AGENT_ERROR_RESPONSE


def test_graph_compiled_once_at_init() -> None:
    service = ChatAgentService()

    assert service._graph is not None
