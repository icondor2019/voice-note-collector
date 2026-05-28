from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

import pytest

from backend.repositories.reflection_repository import ReflectionRepository


class _StubResponse:
    def __init__(self, data: Any = None, error: Optional[str] = None) -> None:
        self.data = data
        self.error = error


class _StubQuery:
    def __init__(self, response: _StubResponse) -> None:
        self._response = response
        self._filters: list[tuple[str, Any]] = []

    def select(self, *args: Any, **kwargs: Any) -> _StubQuery:
        return self

    def eq(self, field: str, value: Any) -> _StubQuery:
        self._filters.append((field, value))
        return self

    def maybe_single(self) -> _StubQuery:
        return self

    async def execute(self) -> _StubResponse:
        return self._response


class _StubTable:
    def __init__(self, response: _StubResponse) -> None:
        self._response = response
        self.insert_payload: Optional[dict[str, Any]] = None
        self.update_payload: Optional[dict[str, Any]] = None
        self.update_filters: list[tuple[str, Any]] = []

    def insert(self, payload: dict[str, Any]) -> _StubQuery:
        self.insert_payload = payload
        return _StubQuery(self._response)

    def select(self, *args: Any, **kwargs: Any) -> _StubQuery:
        return _StubQuery(self._response)

    def update(self, payload: dict[str, Any]) -> _StubQuery:
        self.update_payload = payload
        query = _StubQuery(self._response)
        return query

    def eq(self, field: str, value: Any) -> _StubQuery:
        self.update_filters.append((field, value))
        return _StubQuery(self._response)


class _StubClient:
    def __init__(self, response: _StubResponse) -> None:
        self._response = response
        self.table_name: Optional[str] = None
        self.table_instance: Optional[_StubTable] = None

    def table(self, table_name: str) -> _StubTable:
        self.table_name = table_name
        self.table_instance = _StubTable(self._response)
        return self.table_instance


class TestReflectionRepository:
    @pytest.mark.anyio
    async def test_create_reflection_inserts_pending_row(self) -> None:
        created_at = datetime.now(timezone.utc)
        reflection_data = {
            "id": "uuid-123",
            "telegram_user_id": 123,
            "voice_note_id": None,
            "question_type": "reflective",
            "question_text": "What did you learn?",
            "answer_text": None,
            "rating": None,
            "feedback": None,
            "status": "pending",
            "created_at": created_at,
            "completed_at": None,
        }
        response = _StubResponse(data=reflection_data)
        client = _StubClient(response)
        repository = ReflectionRepository(client=client)

        result = await repository.create_reflection(
            telegram_user_id=123,
            voice_note_id=None,
            question_type="reflective",
            question_text="What did you learn?",
        )

        assert result["status"] == "pending"
        assert result["telegram_user_id"] == 123
        assert result["question_type"] == "reflective"
        assert result["question_text"] == "What did you learn?"
        assert client.table_name == "reflections"
        assert client.table_instance is not None
        assert client.table_instance.insert_payload is not None
        assert client.table_instance.insert_payload["status"] == "pending"

    @pytest.mark.anyio
    async def test_get_pending_reflection_returns_row(self) -> None:
        created_at = datetime.now(timezone.utc)
        reflection_data = {
            "id": "uuid-123",
            "telegram_user_id": 123,
            "voice_note_id": None,
            "question_type": "reflective",
            "question_text": "What did you learn?",
            "answer_text": None,
            "rating": None,
            "feedback": None,
            "status": "pending",
            "created_at": created_at,
            "completed_at": None,
        }
        response = _StubResponse(data=reflection_data)
        repository = ReflectionRepository(client=_StubClient(response))

        result = await repository.get_pending_reflection(123)

        assert result is not None
        assert result["status"] == "pending"
        assert result["telegram_user_id"] == 123

    @pytest.mark.anyio
    async def test_get_pending_reflection_returns_none_when_no_pending(self) -> None:
        response = _StubResponse(data=None)
        repository = ReflectionRepository(client=_StubClient(response))

        result = await repository.get_pending_reflection(999)

        assert result is None

    @pytest.mark.anyio
    async def test_complete_reflection_updates_row(self) -> None:
        completed_at = datetime.now(timezone.utc)
        reflection_data = {
            "id": "uuid-123",
            "telegram_user_id": 123,
            "voice_note_id": None,
            "question_type": "reflective",
            "question_text": "What did you learn?",
            "answer_text": "I learned a lot",
            "rating": 8,
            "feedback": "Great answer!",
            "status": "completed",
            "created_at": completed_at,
            "completed_at": completed_at,
        }
        response = _StubResponse(data=reflection_data)
        repository = ReflectionRepository(client=_StubClient(response))

        result = await repository.complete_reflection(
            reflection_id="uuid-123",
            answer_text="I learned a lot",
            rating=8,
            feedback="Great answer!",
        )

        assert result["status"] == "completed"
        assert result["rating"] == 8
        assert result["feedback"] == "Great answer!"
        assert result["answer_text"] == "I learned a lot"

    @pytest.mark.anyio
    async def test_cancel_pending_reflection_updates_status(self) -> None:
        response = _StubResponse(data=[{"id": "uuid-123", "status": "cancelled"}])
        stub_client = _StubClient(response)
        repository = ReflectionRepository(client=stub_client)

        await repository.cancel_pending_reflection(123)

        assert stub_client.table_instance is not None
        assert stub_client.table_instance.update_payload is not None
        assert stub_client.table_instance.update_payload["status"] == "cancelled"
