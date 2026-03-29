from __future__ import annotations

import logging
from typing import Any, Optional, cast

from backend.repositories.repository_errors import RepositoryError
from backend.repositories.supabase_client import get_supabase_client


logger = logging.getLogger(__name__)


class SourcesRepository:
    def __init__(self) -> None:
        self._table = "sources"

    async def create_source(
        self,
        source_name: str,
        author: Optional[str] = None,
        comment: Optional[str] = None,
        status: str = "deactivated",
    ) -> dict[str, Any]:
        client = await get_supabase_client()
        payload = {
            "source_name": source_name,
            "author": author,
            "comment": comment,
            "status": status,
        }
        logger.info("sources.create", extra={"source_name": source_name, "status": status})
        response = await client.table(self._table).insert(payload).execute()
        self._raise_on_error(response)
        record = self._single(response)
        if not record:
            raise RepositoryError("Failed to create source")
        assert record is not None
        return cast(dict[str, Any], record)

    async def get_source(self, source_id: str) -> Optional[dict[str, Any]]:
        client = await get_supabase_client()
        response = (
            await client.table(self._table)
            .select("*")
            .eq("id", source_id)
            .maybe_single()
            .execute()
        )
        self._raise_on_error(response)
        return self._single(response)

    async def get_source_by_name(self, source_name: str) -> Optional[dict[str, Any]]:
        client = await get_supabase_client()
        response = (
            await client.table(self._table)
            .select("*")
            .eq("source_name", source_name)
            .maybe_single()
            .execute()
        )
        self._raise_on_error(response)
        return self._single(response)

    async def list_sources(self, status: Optional[str] = None) -> list[dict[str, Any]]:
        client = await get_supabase_client()
        query = client.table(self._table).select("*")
        if status:
            query = query.eq("status", status)
        response = await query.order("created_at", desc=True).execute()
        self._raise_on_error(response)
        return self._list(response)

    async def deactivate_all_sources(self) -> int:
        client = await get_supabase_client()
        response = await client.table(self._table).update({"status": "deactivated"}).execute()
        self._raise_on_error(response)
        data = self._list(response)
        return len(data)

    async def activate_source(self, source_id: str) -> Optional[dict[str, Any]]:
        client = await get_supabase_client()
        response = (
            await client.table(self._table)
            .update({"status": "active"})
            .eq("id", source_id)
            .execute()
        )
        self._raise_on_error(response)
        return self._single(response)

    async def get_active_source(self) -> Optional[dict[str, Any]]:
        client = await get_supabase_client()
        response = (
            await client.table(self._table)
            .select("*")
            .eq("status", "active")
            .maybe_single()
            .execute()
        )
        self._raise_on_error(response)
        return self._single(response)

    @staticmethod
    def _raise_on_error(response: Any) -> None:
        if response is None:
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
