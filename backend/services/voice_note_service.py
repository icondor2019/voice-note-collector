from __future__ import annotations

from datetime import datetime
from typing import Any, Optional


from backend.repositories.repository_errors import DuplicateRecordError
from backend.repositories.voice_notes_repository import VoiceNotesRepository
from backend.services.source_service import SourceService

MAX_LOG_TEXT_LENGTH = 200


def _truncate_text(text: Optional[str], limit: int = MAX_LOG_TEXT_LENGTH) -> str:
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return f"{text[:limit]}..."


class VoiceNoteService:
    def __init__(
        self,
        repository: Optional[VoiceNotesRepository] = None,
        source_service: Optional[SourceService] = None,
    ) -> None:
        self._repository = repository or VoiceNotesRepository()
        self._source_service = source_service or SourceService()

    async def create_voice_note_idempotent(
        self,
        raw_text: str,
        clean_text: Optional[str],
        message_id: int,
        audio_file_id: str,
        duration_seconds: Optional[float] = None,
    ) -> dict[str, Any]:
        if raw_text is None:
            raise ValueError("raw_text is required")
        if not audio_file_id:
            raise ValueError("audio_file_id is required")
        if message_id is None:
            raise ValueError("message_id is required")
        existing = await self._repository.get_voice_note_by_message_id(message_id)
        if existing:
            return existing

        active_source = await self._source_service.ensure_default_source()
        try:
            result = await self._repository.create_voice_note(
                source_id=active_source["id"],
                raw_text=raw_text,
                clean_text=clean_text,
                message_id=message_id,
                audio_file_id=audio_file_id,
                duration_seconds=duration_seconds,
            )
            return result
        except DuplicateRecordError:
            existing = await self._repository.get_voice_note_by_message_id(message_id)
            if existing:
                return existing
            raise

    async def get_voice_note(self, note_id: str) -> Optional[dict[str, Any]]:
        return await self._repository.get_voice_note(note_id)

    async def list_voice_notes(
        self,
        source_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
        created_after: Optional[datetime] = None,
        created_before: Optional[datetime] = None,
    ) -> list[dict[str, Any]]:
        return await self._repository.list_voice_notes(
            source_id=source_id,
            limit=limit,
            offset=offset,
            created_after=created_after,
            created_before=created_before,
        )
