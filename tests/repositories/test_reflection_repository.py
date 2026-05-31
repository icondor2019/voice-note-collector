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

    def in_(self, field: str, values: list[Any]) -> _StubQuery:
        self._filters.append((field, values))
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

    @pytest.mark.anyio
    async def test_get_note_reflection_stats_returns_stats_for_completed_reflections(
        self,
    ) -> None:
        """Verify aggregation of avg_rating and review_count per note_id."""
        reflection_data = [
            {"voice_note_id": "note-1", "rating": 8},
            {"voice_note_id": "note-1", "rating": 9},
            {"voice_note_id": "note-2", "rating": 7},
        ]
        response = _StubResponse(data=reflection_data)
        stub_client = _StubClient(response)
        repository = ReflectionRepository(client=stub_client)

        result = await repository.get_note_reflection_stats("source-1", ["note-1", "note-2"])

        assert result["note-1"]["avg_rating"] == 8.5
        assert result["note-1"]["review_count"] == 2
        assert result["note-2"]["avg_rating"] == 7.0
        assert result["note-2"]["review_count"] == 1

    @pytest.mark.anyio
    async def test_get_note_reflection_stats_returns_empty_for_no_reflections(
        self,
    ) -> None:
        """No completed reflections for given note IDs → empty dict."""
        response = _StubResponse(data=None)
        stub_client = _StubClient(response)
        repository = ReflectionRepository(client=stub_client)

        result = await repository.get_note_reflection_stats("source-1", ["note-1", "note-2"])

        assert result == {}

    @pytest.mark.anyio
    async def test_get_note_reflection_stats_returns_empty_for_empty_note_ids(
        self,
    ) -> None:
        """Empty note_ids list → empty dict."""
        response = _StubResponse(data=None)
        stub_client = _StubClient(response)
        repository = ReflectionRepository(client=stub_client)

        result = await repository.get_note_reflection_stats("source-1", [])

        assert result == {}


class _StubRpcQuery:
    """Stub for supabase.rpc().execute() chain."""

    def __init__(self, response: _StubResponse) -> None:
        self._response = response

    async def execute(self) -> _StubResponse:
        return self._response


class _StubRpc:
    """Stub for supabase.rpc() method."""

    def __init__(self, response: _StubResponse) -> None:
        self._response = response

    def __call__(self, fn_name: str, params: dict[str, Any]) -> _StubRpcQuery:
        self._called_fn = fn_name
        self._called_params = params
        return _StubRpcQuery(self._response)


class TestReflectionRepositoryGetReflectionSummary:
    """Tests for ReflectionRepository.get_reflection_summary()."""

    @pytest.mark.anyio
    async def test_get_reflection_summary_returns_counts(self) -> None:
        """Verify RPC call returns correctly structured dict."""
        rpc_response = _StubResponse(
            data=[
                {
                    "total_notes": 10,
                    "internalized": 3,
                    "in_progress": 4,
                    "pending": 3,
                }
            ]
        )
        stub_rpc = _StubRpc(rpc_response)
        stub_client = _StubClient(rpc_response)
        stub_client.rpc = stub_rpc
        repository = ReflectionRepository(client=stub_client)

        result = await repository.get_reflection_summary(
            source_id="source-1",
            min_reviews=3,
            min_avg_score=7.0,
        )

        assert result["total_notes"] == 10
        assert result["internalized"] == 3
        assert result["in_progress"] == 4
        assert result["pending"] == 3
        # Verify invariant
        assert result["internalized"] + result["in_progress"] + result["pending"] == result["total_notes"]

    @pytest.mark.anyio
    async def test_get_reflection_summary_returns_zero_dict_when_empty(self) -> None:
        """RPC returns no data → all-zero dict."""
        rpc_response = _StubResponse(data=[])
        stub_rpc = _StubRpc(rpc_response)
        stub_client = _StubClient(rpc_response)
        stub_client.rpc = stub_rpc
        repository = ReflectionRepository(client=stub_client)

        result = await repository.get_reflection_summary(
            source_id="source-1",
            min_reviews=3,
            min_avg_score=7.0,
        )

        assert result["total_notes"] == 0
        assert result["internalized"] == 0
        assert result["in_progress"] == 0
        assert result["pending"] == 0

    @pytest.mark.anyio
    async def test_get_reflection_summary_passes_correct_params(self) -> None:
        """Verify RPC called with correct p_source_id, p_min_reviews, p_min_avg_score."""
        rpc_response = _StubResponse(data=[{"total_notes": 5, "internalized": 1, "in_progress": 2, "pending": 2}])
        stub_rpc = _StubRpc(rpc_response)
        stub_client = _StubClient(rpc_response)
        stub_client.rpc = stub_rpc
        repository = ReflectionRepository(client=stub_client)

        await repository.get_reflection_summary(
            source_id="abc-123",
            min_reviews=5,
            min_avg_score=8.0,
        )

        assert stub_rpc._called_fn == "get_reflection_summary"
        assert stub_rpc._called_params["p_source_id"] == "abc-123"
        assert stub_rpc._called_params["p_min_reviews"] == 5
        assert stub_rpc._called_params["p_min_avg_score"] == 8.0

