from __future__ import annotations

from datetime import datetime
from typing import Any, Optional, cast

from backend.models.voice_note_details import NoteStatus
from backend.repositories.repository_errors import RepositoryError


class VoiceNoteDetailsRepository:
    def __init__(self, client: Any) -> None:
        self._table = "voice_note_details"
        self._client = client

    async def create_details(self, voice_note_uuid: str) -> dict[str, Any]:
        payload = {
            "voice_note_uuid": voice_note_uuid,
            "status": NoteStatus.CREATED.value,
            "label_ids": [],
        }
        response = await self._client.table(self._table).insert(payload).execute()
        self._raise_on_error(response)
        record = self._single(response)
        if not record:
            raise RepositoryError("Failed to create voice note details")
        assert record is not None
        return cast(dict[str, Any], record)

    async def get_details(self, voice_note_uuid: str) -> Optional[dict[str, Any]]:
        response = (
            await self._client.table(self._table)
            .select("*")
            .eq("voice_note_uuid", voice_note_uuid)
            .maybe_single()
            .execute()
        )
        self._raise_on_error(response, allow_none_response=True)
        return self._single(response)

    async def update_status(self, voice_note_uuid: str, status: str) -> Optional[dict[str, Any]]:
        payload = {"status": status, "updated_at": datetime.utcnow().isoformat()}
        response = (
            await self._client.table(self._table)
            .update(payload)
            .eq("voice_note_uuid", voice_note_uuid)
            .execute()
        )
        self._raise_on_error(response, allow_none_response=True)
        return self._single(response)

    async def update_title(self, voice_note_uuid: str, title: str) -> Optional[dict[str, Any]]:
        payload = {"title": title, "updated_at": datetime.utcnow().isoformat()}
        response = (
            await self._client.table(self._table)
            .update(payload)
            .eq("voice_note_uuid", voice_note_uuid)
            .execute()
        )
        self._raise_on_error(response, allow_none_response=True)
        return self._single(response)

    async def add_label_id(self, voice_note_uuid: str, label_id: int) -> Optional[dict[str, Any]]:
        details = await self.get_details(voice_note_uuid)
        if not details:
            return None
        label_ids = list(details.get("label_ids") or [])
        if label_id not in label_ids:
            label_ids.append(label_id)
        return await self._update_label_ids(voice_note_uuid, label_ids)

    async def remove_label_id(self, voice_note_uuid: str, label_id: int) -> Optional[dict[str, Any]]:
        details = await self.get_details(voice_note_uuid)
        if not details:
            return None
        label_ids = list(details.get("label_ids") or [])
        if label_id in label_ids:
            label_ids.remove(label_id)
        return await self._update_label_ids(voice_note_uuid, label_ids)

    async def _update_label_ids(
        self,
        voice_note_uuid: str,
        label_ids: list[int],
    ) -> Optional[dict[str, Any]]:
        payload = {"label_ids": label_ids, "updated_at": datetime.utcnow().isoformat()}
        response = (
            await self._client.table(self._table)
            .update(payload)
            .eq("voice_note_uuid", voice_note_uuid)
            .execute()
        )
        self._raise_on_error(response, allow_none_response=True)
        return self._single(response)

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
