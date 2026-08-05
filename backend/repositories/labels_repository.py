from __future__ import annotations

from typing import Any, Optional, cast

from backend.repositories.repository_errors import RepositoryError


class LabelsRepository:
    def __init__(self, client: Any) -> None:
        self._table = "labels"
        self._client = client

    async def create_label(self, label: str, created_by: str = "user") -> dict[str, Any]:
        payload = {"label": label, "created_by": created_by}
        response = await self._client.table(self._table).insert(payload).execute()
        self._raise_on_error(response)
        record = self._single(response)
        if not record:
            raise RepositoryError("Failed to create label")
        assert record is not None
        return cast(dict[str, Any], record)

    async def get_label_by_id(self, label_id: int) -> Optional[dict[str, Any]]:
        response = (
            await self._client.table(self._table)
            .select("*")
            .eq("id", label_id)
            .maybe_single()
            .execute()
        )
        self._raise_on_error(response, allow_none_response=True)
        return self._single(response)

    async def get_label_by_name(self, label: str) -> Optional[dict[str, Any]]:
        response = (
            await self._client.table(self._table)
            .select("*")
            .eq("label", label)
            .is_("deleted_at", "null")
            .maybe_single()
            .execute()
        )
        self._raise_on_error(response, allow_none_response=True)
        return self._single(response)

    async def list_labels(self, include_deleted: bool = False) -> list[dict[str, Any]]:
        query = self._client.table(self._table).select("*")
        if not include_deleted:
            query = query.is_("deleted_at", "null")
        response = await query.order("label", desc=False).execute()
        self._raise_on_error(response)
        return self._list(response)

    @staticmethod
    def _raise_on_error(response: Any, allow_none_response: bool = False) -> None:
        if response is None:
            if allow_none_response:
                return
            raise RepositoryError("Supabase returned no response")
        error = getattr(response, "error", None)
        if error:
            raise RepositoryError(str(error))

    @staticmethod
    def _single(response: Any) -> Optional[dict[str, Any]]:
        if not response or not response.data:
            return None
        if isinstance(response.data, list):
            return response.data[0] if response.data else None
        return response.data

    @staticmethod
    def _list(response: Any) -> list[dict[str, Any]]:
        if not response or not response.data:
            return []
        if isinstance(response.data, list):
            return response.data
        return [response.data]
