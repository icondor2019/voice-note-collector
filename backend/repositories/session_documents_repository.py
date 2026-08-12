from __future__ import annotations

from datetime import datetime
from typing import Any, Optional, cast

from backend.repositories.repository_errors import RepositoryError


class SessionDocumentsRepository:
    def __init__(self, client: Any) -> None:
        self._table = "session_documents"
        self._client = client

    async def create_document(
        self,
        source_id: str,
        title: Optional[str] = None,
        content: Optional[str] = None,
        telegram_user_id: Optional[int] = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "source_id": source_id,
            "status": "ready",
        }
        if title is not None:
            payload["title"] = title
        if content is not None:
            payload["content"] = content
        if telegram_user_id is not None:
            payload["telegram_user_id"] = telegram_user_id

        response = await self._client.table(self._table).insert(payload).execute()
        self._raise_on_error(response)
        record = self._single(response)
        if not record:
            raise RepositoryError("Failed to create session document")
        assert record is not None
        return cast(dict[str, Any], record)

    async def get_document(self, document_id: str) -> Optional[dict[str, Any]]:
        response = (
            await self._client.table(self._table)
            .select("*")
            .eq("id", document_id)
            .maybe_single()
            .execute()
        )
        self._raise_on_error(response, allow_none_response=True)
        return self._single(response)

    async def update_document(
        self, document_id: str, **fields: Any
    ) -> Optional[dict[str, Any]]:
        fields["updated_at"] = datetime.utcnow().isoformat()
        response = (
            await self._client.table(self._table)
            .update(fields)
            .eq("id", document_id)
            .execute()
        )
        self._raise_on_error(response, allow_none_response=True)
        return self._single(response)

    async def update_content(
        self, document_id: str, content: str
    ) -> Optional[dict[str, Any]]:
        """Update the content field and updated_at timestamp for a document."""
        return await self.update_document(document_id, content=content)

    async def list_documents(
        self,
        source_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        query = self._client.table(self._table).select("*")
        if source_id:
            query = query.eq("source_id", source_id)
        query = query.order("created_at", desc=True).range(offset, offset + limit - 1)
        response = await query.execute()
        self._raise_on_error(response)
        return self._list(response)

    async def get_document_labels(self, document_id: str) -> list[dict[str, Any]]:
        """Compute-on-read: return distinct active labels for all notes attached to this document."""
        # Step 1: Get voice_note_uuids attached to this document
        details_response = (
            await self._client.table("voice_note_details")
            .select("voice_note_uuid")
            .eq("document_uuid", document_id)
            .execute()
        )
        self._raise_on_error(details_response)
        note_uuids = [
            row["voice_note_uuid"]
            for row in self._list(details_response)
            if row.get("voice_note_uuid")
        ]
        if not note_uuids:
            return []

        # Step 2: Get labels for those notes (active only)
        labels_response = (
            await self._client.table("voice_note_labels")
            .select("labels(id, label)")
            .in_("voice_note_uuid", note_uuids)
            .is_("deleted_at", "null")
            .execute()
        )
        self._raise_on_error(labels_response)

        # Deduplicate labels by id
        seen_ids: set[int] = set()
        unique_labels: list[dict[str, Any]] = []
        for row in self._list(labels_response):
            label_data = row.get("labels")
            if not label_data or not isinstance(label_data, dict):
                continue
            label_id = label_data.get("id")
            if label_id is not None and label_id not in seen_ids:
                seen_ids.add(label_id)
                unique_labels.append(label_data)

        unique_labels.sort(key=lambda l: l.get("label", ""))
        return unique_labels

    async def get_pending_note_ids(self, source_id: str) -> list[str]:
        """Get note IDs where document_uuid IS NULL for the given source.

        Uses !inner join pattern from voice_note_details_repository.
        """
        response = (
            await self._client.table("voice_note_details")
            .select("voice_note_uuid, voice_notes!inner(id, source_id)")
            .is_("document_uuid", "null")
            .eq("voice_notes.source_id", source_id)
            .order("voice_note_uuid")
            .execute()
        )
        self._raise_on_error(response)
        return [
            row["voice_note_uuid"]
            for row in self._list(response)
            if row.get("voice_note_uuid")
        ]

    async def get_valid_note_ids(
        self, source_id: str, note_ids: list[str]
    ) -> list[dict[str, Any]]:
        """Validate note_ids: return only those belonging to source_id AND document_uuid IS NULL.

        Returns the note rows with raw_text for synthesis.
        """
        if not note_ids:
            return []

        response = (
            await self._client.table("voice_note_details")
            .select("voice_note_uuid, status, voice_notes!inner(id, source_id, raw_text, created_at)")
            .in_("voice_note_uuid", note_ids)
            .is_("document_uuid", "null")
            .eq("voice_notes.source_id", source_id)
            .execute()
        )
        self._raise_on_error(response)

        results: list[dict[str, Any]] = []
        for row in self._list(response):
            nested = row.pop("voice_notes", None) or {}
            row["source_id"] = nested.get("source_id")
            row["raw_text"] = nested.get("raw_text")
            row["created_at"] = nested.get("created_at")
            results.append(row)
        return results

    async def attach_notes_to_document(
        self, document_id: str, note_ids: list[str]
    ) -> None:
        """Set document_uuid = document_id on voice_note_details for the given note UUIDs."""
        if not note_ids:
            return

        response = (
            await self._client.table("voice_note_details")
            .update({"document_uuid": document_id})
            .in_("voice_note_uuid", note_ids)
            .execute()
        )
        self._raise_on_error(response)

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
