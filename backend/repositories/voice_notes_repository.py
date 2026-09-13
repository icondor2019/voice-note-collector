from __future__ import annotations

from datetime import datetime
from typing import Any, Optional, cast


from backend.repositories.repository_errors import DuplicateRecordError, RepositoryError

MAX_LOG_TEXT_LENGTH = 200
DASHBOARD_STATISTICS_PAGE_SIZE = 1000


def _truncate_text(text: Optional[str], limit: int = MAX_LOG_TEXT_LENGTH) -> str:
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return f"{text[:limit]}..."


class VoiceNotesRepository:
    def __init__(self, client: Any) -> None:
        self._table = "voice_notes"
        self._client = client

    async def create_voice_note(
        self,
        source_id: str,
        raw_text: str,
        clean_text: Optional[str],
        message_id: int,
        audio_file_id: str,
        duration_seconds: Optional[float] = None,
    ) -> dict[str, Any]:
        payload = {
            "source_id": source_id,
            "raw_text": raw_text,
            "clean_text": clean_text,
            "message_id": message_id,
            "audio_file_id": audio_file_id,
            "duration_seconds": duration_seconds,
        }

        response = await self._client.table(self._table).insert(payload).execute()

        self._raise_on_error(response)
        record = self._single(response)
        if not record:
            raise RepositoryError("Failed to create voice note")
        assert record is not None
        return cast(dict[str, Any], record)

    async def get_voice_note(self, note_id: str) -> Optional[dict[str, Any]]:
        response = (
            await self._client.table(self._table)
            .select("*")
            .eq("id", note_id)
            .maybe_single()
            .execute()
        )

        self._raise_on_error(response)
        return self._single(response)

    async def get_voice_note_by_message_id(self, message_id: int) -> Optional[dict[str, Any]]:
        response = (
            await self._client.table(self._table)
            .select("*")
            .eq("message_id", message_id)
            .maybe_single()
            .execute()
        )

        self._raise_on_error(response, allow_none_response=True)
        return self._single(response)

    async def list_voice_notes(
        self,
        source_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
        created_after: Optional[datetime] = None,
        created_before: Optional[datetime] = None,
        order: str = "desc",
    ) -> list[dict[str, Any]]:
        query = self._client.table(self._table).select("*")
        if source_id:
            query = query.eq("source_id", source_id)
        if created_after:
            query = query.gte("created_at", created_after.isoformat())
        if created_before:
            query = query.lte("created_at", created_before.isoformat())
        query = query.order("created_at", desc=(order == "desc")).range(offset, offset + limit - 1)
        response = await query.execute()
        self._raise_on_error(response)
        return self._list(response)

    async def count_voice_notes(self) -> int:
        response = await self._client.table(self._table).select("id", count="exact").execute()
        self._raise_on_error(response)
        count = getattr(response, "count", None)
        return int(count) if count is not None else len(self._list(response))

    async def get_latest_note_created_at(self) -> Optional[str]:
        response = (
            await self._client.table(self._table)
            .select("created_at")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        self._raise_on_error(response)
        rows = self._list(response)
        return rows[0].get("created_at") if rows else None

    async def get_dashboard_recording_statistics(self) -> dict[str, float | int]:
        """Return global recording duration and pending-note totals for the dashboard."""
        total_duration_seconds = 0.0
        pending_notes = 0
        offset = 0

        while True:
            response = (
                await self._client.table(self._table)
                .select("duration_seconds, voice_note_details(status)")
                .order("id")
                .range(offset, offset + DASHBOARD_STATISTICS_PAGE_SIZE - 1)
                .execute()
            )
            self._raise_on_error(response)
            rows = self._list(response)

            for row in rows:
                duration = row.get("duration_seconds")
                if duration is not None:
                    total_duration_seconds += float(duration)

                details = row.get("voice_note_details") or {}
                if isinstance(details, list):
                    is_pending = any(
                        isinstance(detail, dict) and detail.get("status") == "created"
                        for detail in details
                    )
                else:
                    is_pending = (
                        isinstance(details, dict) and details.get("status") == "created"
                    )
                if is_pending:
                    pending_notes += 1

            if len(rows) < DASHBOARD_STATISTICS_PAGE_SIZE:
                break
            offset += DASHBOARD_STATISTICS_PAGE_SIZE

        return {
            "total_duration_seconds": total_duration_seconds,
            "pending_notes": pending_notes,
        }

    async def list_web_notes(
        self,
        *,
        source_id: Optional[str] = None,
        source_type: Optional[str] = None,
        source_author: Optional[str] = None,
        source_usage_status: Optional[str] = None,
        status: Optional[str] = None,
        label_ids: Optional[list[int]] = None,
        offset: int = 0,
        limit: int = 24,
    ) -> list[dict[str, Any]]:
        """Return the enriched projection used by the server-rendered note library."""
        details_relation = (
            "voice_note_details!inner(title, status, created_at, updated_at)"
            if status
            else "voice_note_details(title, status, created_at, updated_at)"
        )
        projection = [
            "*",
            "sources!inner(id, source_name, type, author, usage_status)",
            details_relation,
        ]
        if label_ids:
            projection.append("voice_note_labels!inner(label_id, deleted_at)")

        query = self._client.table(self._table).select(", ".join(projection))
        if source_id:
            query = query.eq("source_id", source_id)
        if source_type:
            query = query.eq("sources.type", source_type)
        if source_author:
            query = query.eq("sources.author", source_author)
        if source_usage_status:
            query = query.eq("sources.usage_status", source_usage_status)
        if status:
            query = query.eq("voice_note_details.status", status)
        if label_ids:
            query = query.in_("voice_note_labels.label_id", label_ids)
            query = query.is_("voice_note_labels.deleted_at", "null")

        response = await (
            query.order("created_at", desc=True)
            .range(offset, offset + limit - 1)
            .execute()
        )
        self._raise_on_error(response)
        rows = self._list(response)

        note_ids = [str(row.get("id")) for row in rows if row.get("id")]
        labels_by_note = await self._labels_for_notes(note_ids)
        items: list[dict[str, Any]] = []
        for row in rows:
            source = row.get("sources") or {}
            if isinstance(source, list):
                source = source[0] if source else {}
            details = row.get("voice_note_details") or {}
            if isinstance(details, list):
                details = details[0] if details else {}
            labels = labels_by_note.get(str(row.get("id")), [])
            item = dict(row)
            item.pop("voice_note_labels", None)
            item["details"] = details
            item["labels"] = labels
            item["source"] = source
            item["display_title"] = details.get("title") or "Untitled note"
            item["preview"] = (row.get("clean_text") or row.get("raw_text") or "")[:280]
            items.append(item)
        return items

    async def get_web_note(self, note_id: str) -> Optional[dict[str, Any]]:
        notes = await self.list_web_notes(offset=0, limit=10000)
        return next((note for note in notes if str(note.get("id")) == note_id), None)

    async def _labels_for_notes(self, note_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
        if not note_ids:
            return {}
        response = (
            await self._client.table("voice_note_labels")
            .select("voice_note_uuid, labels(id, label)")
            .in_("voice_note_uuid", note_ids)
            .is_("deleted_at", "null")
            .execute()
        )
        self._raise_on_error(response)
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in self._list(response):
            label = row.get("labels")
            note_id = row.get("voice_note_uuid")
            if note_id and isinstance(label, dict):
                grouped.setdefault(str(note_id), []).append(label)
        for labels in grouped.values():
            labels.sort(key=lambda label: str(label.get("label") or ""))
        return grouped

    @staticmethod
    def _raise_on_error(response: Any, allow_none_response: bool = False) -> None:
        if response is not None and hasattr(response, "error") and response.error:
            raise RepositoryError(f"Supabase error: {response.error}")
        if response is None:
            if allow_none_response:
                return
            raise RepositoryError("Supabase returned None response")

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
