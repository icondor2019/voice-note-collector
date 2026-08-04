from __future__ import annotations

from datetime import datetime
from typing import Any, Optional, cast

from backend.repositories.repository_errors import RepositoryError


class VoiceNoteLabelsRepository:
    """Join table between voice notes and labels.

    Pairings are soft-deleted so that removing a label from a note leaves a trace.
    A partial unique index on (voice_note_uuid, label_id) WHERE deleted_at IS NULL
    keeps at most one active pairing while allowing any number of historical ones.
    """

    def __init__(self, client: Any) -> None:
        self._table = "voice_note_labels"
        self._client = client

    async def attach_label(
        self, voice_note_uuid: str, label_id: int, applied_by: str = "llm"
    ) -> dict[str, Any]:
        """Attach a label, reviving the pairing if it was previously detached."""
        active, archived = await self._find_pairing(voice_note_uuid, label_id)
        if active:
            return active
        if archived:
            return await self._revive(archived["id"], applied_by)

        payload = {
            "voice_note_uuid": voice_note_uuid,
            "label_id": label_id,
            "applied_by": applied_by,
        }
        response = await self._client.table(self._table).insert(payload).execute()
        self._raise_on_error(response)
        record = self._single(response)
        if not record:
            raise RepositoryError("Failed to attach label")
        return cast(dict[str, Any], record)

    async def detach_label(
        self, voice_note_uuid: str, label_id: int
    ) -> Optional[dict[str, Any]]:
        """Soft-delete the active pairing. Returns None when there is nothing to detach."""
        payload = {"deleted_at": datetime.utcnow().isoformat()}
        response = (
            await self._client.table(self._table)
            .update(payload)
            .eq("voice_note_uuid", voice_note_uuid)
            .eq("label_id", label_id)
            .is_("deleted_at", "null")
            .execute()
        )
        self._raise_on_error(response, allow_none_response=True)
        return self._single(response)

    async def list_labels_for_note(self, voice_note_uuid: str) -> list[dict[str, Any]]:
        response = (
            await self._client.table(self._table)
            .select("*, labels(id, label)")
            .eq("voice_note_uuid", voice_note_uuid)
            .is_("deleted_at", "null")
            .execute()
        )
        self._raise_on_error(response)
        return self._list(response)

    async def list_notes_by_label(self, label_id: int) -> list[str]:
        """Reverse lookup: every note currently carrying this label."""
        response = (
            await self._client.table(self._table)
            .select("voice_note_uuid")
            .eq("label_id", label_id)
            .is_("deleted_at", "null")
            .execute()
        )
        self._raise_on_error(response)
        return [
            row["voice_note_uuid"]
            for row in self._list(response)
            if row.get("voice_note_uuid")
        ]

    async def list_labels_for_notes(
        self, note_ids: list[str]
    ) -> dict[str, list[dict[str, Any]]]:
        """Batch form of list_labels_for_note, grouped by note uuid.

        Grouping happens in Python since PostgREST cannot group server-side.
        """
        if not note_ids:
            return {}

        response = (
            await self._client.table(self._table)
            .select("*, labels(id, label)")
            .in_("voice_note_uuid", note_ids)
            .is_("deleted_at", "null")
            .execute()
        )
        self._raise_on_error(response)

        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in self._list(response):
            note_id = row.get("voice_note_uuid")
            if not note_id:
                continue
            grouped.setdefault(note_id, []).append(row)
        return grouped

    async def replace_llm_labels(
        self, voice_note_uuid: str, label_ids: list[int]
    ) -> dict[str, list[int]]:
        """Sync the LLM-applied labels for a note, leaving user-applied ones untouched.

        Returns {"attached": [...], "detached": [...]} of label ids that changed.
        """
        rows = await self._list_active_pairings(voice_note_uuid)
        wanted = list(dict.fromkeys(label_ids))  # dedupe, preserve order
        desired = set(wanted)
        active_ids = {row["label_id"] for row in rows}

        detached: list[int] = []
        for row in rows:
            if row.get("applied_by") != "llm":
                continue
            if row["label_id"] not in desired:
                await self.detach_label(voice_note_uuid, row["label_id"])
                detached.append(row["label_id"])

        attached: list[int] = []
        for label_id in wanted:
            if label_id in active_ids:
                continue
            await self.attach_label(voice_note_uuid, label_id, applied_by="llm")
            attached.append(label_id)

        return {"attached": attached, "detached": detached}

    async def _list_active_pairings(self, voice_note_uuid: str) -> list[dict[str, Any]]:
        response = (
            await self._client.table(self._table)
            .select("*")
            .eq("voice_note_uuid", voice_note_uuid)
            .is_("deleted_at", "null")
            .execute()
        )
        self._raise_on_error(response)
        return self._list(response)

    async def _find_pairing(
        self, voice_note_uuid: str, label_id: int
    ) -> tuple[Optional[dict[str, Any]], Optional[dict[str, Any]]]:
        """Return (active_pairing, most_recent_archived_pairing) for this note/label."""
        response = (
            await self._client.table(self._table)
            .select("*")
            .eq("voice_note_uuid", voice_note_uuid)
            .eq("label_id", label_id)
            .execute()
        )
        self._raise_on_error(response, allow_none_response=True)
        rows = self._list(response)

        active = next((row for row in rows if row.get("deleted_at") is None), None)
        archived = [row for row in rows if row.get("deleted_at") is not None]
        archived.sort(key=lambda row: str(row.get("deleted_at") or ""), reverse=True)
        return active, archived[0] if archived else None

    async def _revive(self, pairing_id: str, applied_by: str) -> dict[str, Any]:
        payload = {"deleted_at": None, "applied_by": applied_by}
        response = (
            await self._client.table(self._table)
            .update(payload)
            .eq("id", pairing_id)
            .execute()
        )
        self._raise_on_error(response)
        record = self._single(response)
        if not record:
            raise RepositoryError("Failed to revive label pairing")
        return cast(dict[str, Any], record)

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
