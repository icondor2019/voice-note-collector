from __future__ import annotations

from datetime import datetime
from typing import Any, Optional, cast

from loguru import logger

from backend.repositories.repository_errors import DuplicateRecordError, RepositoryError
from backend.repositories.supabase_client import get_supabase_client

MAX_LOG_TEXT_LENGTH = 200


def _truncate_text(text: Optional[str], limit: int = MAX_LOG_TEXT_LENGTH) -> str:
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return f"{text[:limit]}..."


class VoiceNotesRepository:
    def __init__(self) -> None:
        self._table = "voice_notes"

    async def create_voice_note(
        self,
        source_id: str,
        raw_text: str,
        clean_text: Optional[str],
        message_id: int,
        audio_file_id: str,
        duration_seconds: Optional[float] = None,
    ) -> dict[str, Any]:
        client = await get_supabase_client()
        payload = {
            "source_id": source_id,
            "raw_text": raw_text,
            "clean_text": clean_text,
            "message_id": message_id,
            "audio_file_id": audio_file_id,
            "duration_seconds": duration_seconds,
        }

        
        response = await client.table(self._table).insert(payload).execute()
        
        self._raise_on_error(response)
        record = self._single(response)
        if not record:
            logger.bind(
                table=self._table,
                message_id=message_id,
                response_is_none=response is None,
            ).error("voice_notes.repository.create.no_record")
            raise RepositoryError("Failed to create voice note")
        assert record is not None
        logger.bind(
            table=self._table,
            message_id=message_id,
            record_id=record.get("id") if isinstance(record, dict) else None,
        ).debug("voice_notes.repository.create.success")
        return cast(dict[str, Any], record)

    async def get_voice_note(self, note_id: str) -> Optional[dict[str, Any]]:
        client = await get_supabase_client()
        logger.bind(table=self._table, note_id=note_id).debug("supabase.query.get.start")
        response = (
            await client.table(self._table)
            .select("*")
            .eq("id", note_id)
            .maybe_single()
            .execute()
        )

        self._raise_on_error(response)
        return self._single(response)

    async def get_voice_note_by_message_id(self, message_id: int) -> Optional[dict[str, Any]]:
        client = await get_supabase_client()
        response = (
            await client.table(self._table)
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
    ) -> list[dict[str, Any]]:
        client = await get_supabase_client()
        query = client.table(self._table).select("*")
        if source_id:
            query = query.eq("source_id", source_id)
        if created_after:
            query = query.gte("created_at", created_after.isoformat())
        if created_before:
            query = query.lte("created_at", created_before.isoformat())
        query = query.order("created_at", desc=True).range(offset, offset + limit - 1)
        logger.bind(
            table=self._table,
            source_id=source_id,
            limit=limit,
            offset=offset,
            created_after=created_after.isoformat() if created_after else None,
            created_before=created_before.isoformat() if created_before else None,
        ).debug("supabase.query.list.start")
        response = await query.execute()
        logger.bind(
            table=self._table,
            response_is_none=response is None,
            response_has_data=bool(getattr(response, "data", None)),
            response_has_error=bool(getattr(response, "error", None)),
        ).debug("supabase.query.list.end")
        self._raise_on_error(response)
        return self._list(response)

    @staticmethod
    def _raise_on_error(response: Any, allow_none_response: bool = False) -> None:
        if response is not None and hasattr(response, "error") and response.error:
            logger.bind(error=str(response.error)).error("supabase.response.error")
            raise RepositoryError(f"Supabase error: {response.error}")
        if response is None:
            if allow_none_response:
                logger.bind(
                    response_is_none=True,
                    allow_none_response=True,
                ).warning("supabase.response.none.allowed")
                return
            logger.bind(response_is_none=True).error("supabase.response.none")
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
