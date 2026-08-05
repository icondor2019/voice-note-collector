from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

import pytest

from backend.repositories.labels_repository import LabelsRepository
from backend.repositories.repository_errors import RepositoryError


class _StubResponse:
    def __init__(self, data: Any = None, error: Optional[str] = None) -> None:
        self.data = data
        self.error = error


class _StubQuery:
    def __init__(self, response: _StubResponse, calls: Optional[list[tuple[str, Any]]] = None) -> None:
        self._response = response
        self.calls = calls if calls is not None else []

    def select(self, *args: Any, **kwargs: Any) -> _StubQuery:
        self.calls.append(("select", args))
        return self

    def eq(self, *args: Any, **kwargs: Any) -> _StubQuery:
        self.calls.append(("eq", args))
        return self

    def is_(self, *args: Any, **kwargs: Any) -> _StubQuery:
        self.calls.append(("is_", args))
        return self

    def maybe_single(self) -> _StubQuery:
        self.calls.append(("maybe_single", ()))
        return self

    def order(self, *args: Any, **kwargs: Any) -> _StubQuery:
        self.calls.append(("order", args))
        return self

    async def execute(self) -> _StubResponse:
        return self._response


class _StubTable:
    def __init__(self, response: _StubResponse) -> None:
        self._response = response
        self.insert_payload: Optional[dict[str, Any]] = None
        self.last_query: Optional[_StubQuery] = None

    def insert(self, payload: dict[str, Any]) -> _StubQuery:
        self.insert_payload = payload
        self.last_query = _StubQuery(self._response)
        return self.last_query

    def select(self, *args: Any, **kwargs: Any) -> _StubQuery:
        self.last_query = _StubQuery(self._response)
        self.last_query.calls.append(("select", args))
        return self.last_query


class _StubClient:
    def __init__(self, response: _StubResponse) -> None:
        self._response = response
        self.table_name: Optional[str] = None
        self.table_instance: Optional[_StubTable] = None

    def table(self, table_name: str) -> _StubTable:
        self.table_name = table_name
        self.table_instance = _StubTable(self._response)
        return self.table_instance


class TestLabelsRepository:
    @pytest.mark.anyio
    async def test_create_label_returns_record(self) -> None:
        created_at = datetime.now(timezone.utc)
        response = _StubResponse(data={"id": 1, "label": "python", "created_at": created_at})
        client = _StubClient(response)
        repository = LabelsRepository(client)

        result = await repository.create_label("python")

        assert result == response.data
        assert client.table_name == "labels"
        assert client.table_instance is not None
        assert client.table_instance.insert_payload == {"label": "python", "created_by": "user"}

    @pytest.mark.anyio
    async def test_create_label_defaults_to_user_created_by(self) -> None:
        response = _StubResponse(data={"id": 1, "label": "python"})
        client = _StubClient(response)
        repository = LabelsRepository(client)

        await repository.create_label("python")

        assert client.table_instance is not None
        assert client.table_instance.insert_payload["created_by"] == "user"

    @pytest.mark.anyio
    async def test_create_label_accepts_llm_created_by(self) -> None:
        response = _StubResponse(data={"id": 1, "label": "python"})
        client = _StubClient(response)
        repository = LabelsRepository(client)

        await repository.create_label("python", created_by="llm")

        assert client.table_instance is not None
        assert client.table_instance.insert_payload == {"label": "python", "created_by": "llm"}

    @pytest.mark.anyio
    async def test_create_label_raises_on_error(self) -> None:
        response = _StubResponse(error="duplicate key value")
        repository = LabelsRepository(_StubClient(response))

        with pytest.raises(RepositoryError):
            await repository.create_label("python")

    @pytest.mark.anyio
    async def test_get_label_by_id_returns_row(self) -> None:
        response = _StubResponse(data={"id": 10, "label": "python"})
        repository = LabelsRepository(_StubClient(response))

        result = await repository.get_label_by_id(10)

        assert result == response.data

    @pytest.mark.anyio
    async def test_get_label_by_id_returns_none_when_missing(self) -> None:
        response = _StubResponse(data=None)
        repository = LabelsRepository(_StubClient(response))

        result = await repository.get_label_by_id(10)

        assert result is None

    @pytest.mark.anyio
    async def test_get_label_by_name_returns_row(self) -> None:
        response = _StubResponse(data={"id": 11, "label": "python"})
        repository = LabelsRepository(_StubClient(response))

        result = await repository.get_label_by_name("python")

        assert result == response.data

    @pytest.mark.anyio
    async def test_get_label_by_name_returns_none_when_missing(self) -> None:
        response = _StubResponse(data=None)
        repository = LabelsRepository(_StubClient(response))

        result = await repository.get_label_by_name("missing")

        assert result is None

    @pytest.mark.anyio
    async def test_get_label_by_name_filters_deleted(self) -> None:
        response = _StubResponse(data={"id": 11, "label": "python"})
        client = _StubClient(response)
        repository = LabelsRepository(client)

        await repository.get_label_by_name("python")

        assert client.table_instance is not None
        query = client.table_instance.last_query
        assert query is not None
        assert ("is_", ("deleted_at", "null")) in query.calls

    @pytest.mark.anyio
    async def test_list_labels_returns_all_rows(self) -> None:
        response = _StubResponse(data=[{"id": 1, "label": "alpha"}, {"id": 2, "label": "beta"}])
        repository = LabelsRepository(_StubClient(response))

        result = await repository.list_labels()

        assert result == response.data

    @pytest.mark.anyio
    async def test_list_labels_filters_deleted_by_default(self) -> None:
        response = _StubResponse(data=[{"id": 1, "label": "alpha"}])
        client = _StubClient(response)
        repository = LabelsRepository(client)

        await repository.list_labels()

        assert client.table_instance is not None
        query = client.table_instance.last_query
        assert query is not None
        assert ("is_", ("deleted_at", "null")) in query.calls

    @pytest.mark.anyio
    async def test_list_labels_includes_deleted_when_requested(self) -> None:
        response = _StubResponse(data=[{"id": 1, "label": "alpha"}])
        client = _StubClient(response)
        repository = LabelsRepository(client)

        result = await repository.list_labels(include_deleted=True)

        assert result == response.data
        assert client.table_instance is not None
        query = client.table_instance.last_query
        assert query is not None
        assert all(call[0] != "is_" for call in query.calls)
