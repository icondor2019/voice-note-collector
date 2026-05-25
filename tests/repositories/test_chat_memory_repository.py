from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from backend.models.chat_memory import ChatMemoryEntry
from backend.repositories.chat_memory_repository import ChatMemoryRepository
from backend.repositories.repository_errors import RepositoryError


@pytest.mark.anyio
async def test_get_last_n_messages_returns_ordered_entries() -> None:
    client = Mock()
    table = Mock()
    client.table.return_value = table
    table.select.return_value = table
    table.eq.return_value = table
    table.order.return_value = table
    table.limit.return_value = table
    now = datetime.now()
    table.execute = AsyncMock(
        return_value=SimpleNamespace(
            error=None,
            data=[
                {
                    "id": "7a0afc75-c30e-4a88-9c27-0e87967d4d79",
                    "telegram_user_id": 123,
                    "role": "assistant",
                    "content": "second",
                    "created_at": (now - timedelta(minutes=1)).isoformat(),
                },
                {
                    "id": "9b8b602b-5df6-4e4c-8e36-2d0bd3ad8bd3",
                    "telegram_user_id": 123,
                    "role": "user",
                    "content": "first",
                    "created_at": (now - timedelta(minutes=2)).isoformat(),
                },
            ],
        )
    )
    repo = ChatMemoryRepository(client)

    results = await repo.get_last_n_messages(123, 2)

    assert [entry.content for entry in results] == ["first", "second"]
    assert all(isinstance(entry, ChatMemoryEntry) for entry in results)
    table.order.assert_called_once_with("created_at", desc=True)
    table.limit.assert_called_once_with(2)


@pytest.mark.anyio
async def test_get_last_n_messages_returns_empty_list_when_no_rows() -> None:
    client = Mock()
    table = Mock()
    client.table.return_value = table
    table.select.return_value = table
    table.eq.return_value = table
    table.order.return_value = table
    table.limit.return_value = table
    table.execute = AsyncMock(return_value=SimpleNamespace(error=None, data=[]))
    repo = ChatMemoryRepository(client)

    results = await repo.get_last_n_messages(123, 2)

    assert results == []


@pytest.mark.anyio
async def test_save_message_calls_insert_with_correct_payload() -> None:
    client = Mock()
    table = Mock()
    client.table.return_value = table
    table.insert.return_value = table
    table.execute = AsyncMock(return_value=SimpleNamespace(error=None, data=None))
    repo = ChatMemoryRepository(client)

    await repo.save_message(123, "user", "hello")

    table.insert.assert_called_once_with(
        {"telegram_user_id": 123, "role": "user", "content": "hello"}
    )


@pytest.mark.anyio
async def test_get_last_n_messages_raises_repository_error_on_supabase_error() -> None:
    client = Mock()
    table = Mock()
    client.table.return_value = table
    table.select.return_value = table
    table.eq.return_value = table
    table.order.return_value = table
    table.limit.return_value = table
    table.execute = AsyncMock(return_value=SimpleNamespace(error="boom", data=None))
    repo = ChatMemoryRepository(client)

    with pytest.raises(RepositoryError):
        await repo.get_last_n_messages(123, 2)
