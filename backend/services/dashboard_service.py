from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from backend.repositories.session_documents_repository import SessionDocumentsRepository
from backend.repositories.sources_repository import SourcesRepository
from backend.repositories.voice_notes_repository import VoiceNotesRepository


class DashboardService:
    def __init__(
        self,
        sources_repository: SourcesRepository,
        voice_notes_repository: VoiceNotesRepository,
        session_documents_repository: SessionDocumentsRepository,
    ) -> None:
        self._sources = sources_repository
        self._notes = voice_notes_repository
        self._documents = session_documents_repository

    async def get_summary(self) -> dict[str, Any]:
        source_stats = await self._sources.get_web_statistics()
        note_count = await self._notes.count_voice_notes()
        document_count = await self._documents.count_documents()
        latest = await self._notes.get_latest_note_created_at()
        days_since_last_note = None
        if latest:
            parsed = datetime.fromisoformat(latest.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=ZoneInfo("UTC"))
            local_date = parsed.astimezone(ZoneInfo("America/Guayaquil")).date()
            days_since_last_note = (
                datetime.now(ZoneInfo("America/Guayaquil")).date() - local_date
            ).days
        return {
            "sources": source_stats,
            "notes": note_count,
            "documents": document_count,
            "days_since_last_note": days_since_last_note,
        }
