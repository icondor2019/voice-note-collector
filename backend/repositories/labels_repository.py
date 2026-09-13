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

    async def list_ranked_labels(self) -> list[dict[str, Any]]:
        """Return active labels ranked by distinct notes carrying each label."""
        active_labels = await self.list_labels()
        active_by_id = {
            int(label["id"]): label
            for label in active_labels
            if label.get("id") is not None and label.get("deleted_at") is None
        }
        if not active_by_id:
            return []

        response = (
            await self._client.table("voice_note_labels")
            .select("voice_note_uuid, label_id")
            .is_("deleted_at", "null")
            .execute()
        )
        self._raise_on_error(response)
        notes_by_label: dict[int, set[str]] = {}
        for row in self._list(response):
            label_id = row.get("label_id")
            note_id = row.get("voice_note_uuid")
            if label_id is None or not note_id:
                continue
            try:
                label_id = int(label_id)
            except (TypeError, ValueError):
                continue
            if label_id in active_by_id:
                notes_by_label.setdefault(label_id, set()).add(str(note_id))

        ranked = []
        for label_id, note_ids in notes_by_label.items():
            if not note_ids:
                continue
            label = active_by_id[label_id]
            ranked.append({
                "id": label_id,
                "label": label.get("label") or "",
                "count": len(note_ids),
            })
        ranked.sort(key=lambda item: (-int(item["count"]), str(item["label"]).casefold()))
        return ranked

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
