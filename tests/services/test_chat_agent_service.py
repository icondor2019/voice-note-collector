from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from configuration.settings import settings

from backend.models.chat_memory import ChatMemoryEntry
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

    response = await service.get_response("hello", telegram_user_id=None)

    assert response == "hi there"


@pytest.mark.anyio
async def test_get_response_passes_system_and_human_messages() -> None:
    service = ChatAgentService()
    service._graph = AsyncMock()
    service._graph.ainvoke = AsyncMock(
        return_value={"messages": [AIMessage(content="ok")]}
    )

    await service.get_response("user text", telegram_user_id=None)

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

    response = await service.get_response("hi", telegram_user_id=None)

    assert response == AGENT_ERROR_RESPONSE


def test_graph_compiled_once_at_init() -> None:
    service = ChatAgentService()

    assert service._graph is not None


@pytest.mark.anyio
async def test_get_response_without_user_id_is_stateless() -> None:
    service = ChatAgentService()
    service._graph = AsyncMock()
    service._graph.ainvoke = AsyncMock(
        return_value={"messages": [AIMessage(content="ok")]}
    )

    await service.get_response("hello", telegram_user_id=None)

    call_state = service._graph.ainvoke.call_args.args[0]
    messages = call_state["messages"]
    assert len(messages) == 2
    assert isinstance(messages[0], SystemMessage)
    assert isinstance(messages[1], HumanMessage)


@pytest.mark.anyio
async def test_get_response_with_user_id_prepends_history() -> None:
    memory_repo = AsyncMock()
    now = datetime.now()
    memory_repo.get_last_n_messages = AsyncMock(
        return_value=[
            ChatMemoryEntry(
                id="9b8b602b-5df6-4e4c-8e36-2d0bd3ad8bd3",
                telegram_user_id=123,
                role="user",
                content="hi",
                created_at=now - timedelta(minutes=2),
            ),
            ChatMemoryEntry(
                id="7a0afc75-c30e-4a88-9c27-0e87967d4d79",
                telegram_user_id=123,
                role="assistant",
                content="hello",
                created_at=now - timedelta(minutes=1),
            ),
        ]
    )
    service = ChatAgentService(memory_repository=memory_repo)
    service._graph = AsyncMock()
    service._graph.ainvoke = AsyncMock(return_value={"messages": [AIMessage(content="ok")]})

    await service.get_response("current", telegram_user_id=123)

    call_state = service._graph.ainvoke.call_args.args[0]
    messages = call_state["messages"]
    assert isinstance(messages[0], SystemMessage)
    assert isinstance(messages[1], HumanMessage)
    assert messages[1].content == "hi"
    assert isinstance(messages[2], AIMessage)
    assert messages[2].content == "hello"
    assert isinstance(messages[3], HumanMessage)
    assert messages[3].content == "current"


@pytest.mark.anyio
async def test_get_response_saves_user_and_assistant_messages() -> None:
    memory_repo = AsyncMock()
    memory_repo.get_last_n_messages = AsyncMock(return_value=[])
    memory_repo.save_message = AsyncMock()
    service = ChatAgentService(memory_repository=memory_repo)
    service._graph = AsyncMock()
    service._graph.ainvoke = AsyncMock(
        return_value={"messages": [AIMessage(content="assistant reply")]}
    )

    await service.get_response("user text", telegram_user_id=321)

    memory_repo.save_message.assert_any_await(321, "user", "user text")
    memory_repo.save_message.assert_any_await(321, "assistant", "assistant reply")
    assert memory_repo.save_message.await_count == 2


@pytest.mark.anyio
async def test_get_response_memory_fetch_failure_does_not_raise() -> None:
    memory_repo = AsyncMock()
    memory_repo.get_last_n_messages = AsyncMock(side_effect=RuntimeError("boom"))
    service = ChatAgentService(memory_repository=memory_repo)
    service._graph = AsyncMock()
    service._graph.ainvoke = AsyncMock(return_value={"messages": [AIMessage(content="ok")]})

    response = await service.get_response("hello", telegram_user_id=123)

    assert response == "ok"


@pytest.mark.anyio
async def test_get_response_memory_save_failure_does_not_raise() -> None:
    memory_repo = AsyncMock()
    memory_repo.get_last_n_messages = AsyncMock(return_value=[])
    memory_repo.save_message = AsyncMock(side_effect=RuntimeError("boom"))
    service = ChatAgentService(memory_repository=memory_repo)
    service._graph = AsyncMock()
    service._graph.ainvoke = AsyncMock(return_value={"messages": [AIMessage(content="ok")]})

    response = await service.get_response("hello", telegram_user_id=123)

    assert response == "ok"


@pytest.mark.anyio
async def test_max_memory_messages_respected() -> None:
    memory_repo = AsyncMock()
    memory_repo.get_last_n_messages = AsyncMock(return_value=[])
    service = ChatAgentService(memory_repository=memory_repo)
    service._graph = AsyncMock()
    service._graph.ainvoke = AsyncMock(return_value={"messages": [AIMessage(content="ok")]})

    await service.get_response("hello", telegram_user_id=123)

    memory_repo.get_last_n_messages.assert_awaited_once_with(
        123, settings.AGENT_MAX_MEMORY_MESSAGES
    )
