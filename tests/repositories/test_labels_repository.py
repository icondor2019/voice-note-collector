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
    def __init__(self, response: _StubResponse) -> None:
        self._response = response

    def select(self, *args: Any, **kwargs: Any) -> _StubQuery:
        return self

    def eq(self, *args: Any, **kwargs: Any) -> _StubQuery:
        return self

    def maybe_single(self) -> _StubQuery:
        return self

    def order(self, *args: Any, **kwargs: Any) -> _StubQuery:
        return self

    async def execute(self) -> _StubResponse:
        return self._response


class _StubTable:
    def __init__(self, response: _StubResponse) -> None:
        self._response = response
        self.insert_payload: Optional[dict[str, Any]] = None

    def insert(self, payload: dict[str, Any]) -> _StubQuery:
        self.insert_payload = payload
        return _StubQuery(self._response)

    def select(self, *args: Any, **kwargs: Any) -> _StubQuery:
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
        assert client.table_instance.insert_payload == {"label": "python"}

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
    async def test_list_labels_returns_all_rows(self) -> None:
        response = _StubResponse(data=[{"id": 1, "label": "alpha"}, {"id": 2, "label": "beta"}])
        repository = LabelsRepository(_StubClient(response))

        result = await repository.list_labels()

        assert result == response.data
