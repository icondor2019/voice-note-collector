from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status

from backend.repositories.repository_errors import RepositoryError
from backend.repositories.sources_repository import SourcesRepository
from backend.repositories.supabase_client import get_supabase_client
from backend.repositories.voice_notes_repository import VoiceNotesRepository
from backend.services.source_service import SourceService
from backend.services.telegram_ingestion_service import TelegramIngestionService
from backend.services.voice_note_service import VoiceNoteService

router = APIRouter(prefix="/api/telegram", tags=["Telegram"])


async def get_supabase() -> Any:
    return await get_supabase_client()


def get_voice_notes_repository(
    _: Any = Depends(get_supabase),
) -> VoiceNotesRepository:
    return VoiceNotesRepository()


def get_sources_repository(
    _: Any = Depends(get_supabase),
) -> SourcesRepository:
    return SourcesRepository()


def get_source_service(
    sources_repository: SourcesRepository = Depends(get_sources_repository),
) -> SourceService:
    return SourceService(repository=sources_repository)


def get_voice_note_service(
    voice_notes_repository: VoiceNotesRepository = Depends(get_voice_notes_repository),
    source_service: SourceService = Depends(get_source_service),
) -> VoiceNoteService:
    return VoiceNoteService(
        repository=voice_notes_repository,
        source_service=source_service,
    )


def get_ingestion_service(
    voice_note_service: VoiceNoteService = Depends(get_voice_note_service),
) -> TelegramIngestionService:
    return TelegramIngestionService(voice_note_service)


@router.post("/webhook")
async def telegram_webhook(
    request: Request,
    ingestion_service: TelegramIngestionService = Depends(get_ingestion_service),
) -> dict[str, Any]:
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON payload",
        )

    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON payload",
        )

    # Accept update payloads even if message type is unsupported.
    try:
        result = await ingestion_service.ingest_update(payload)
    except RepositoryError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to persist ingestion event",
        )

    return {"status": "ok", **result}
