from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger
from pydantic import BaseModel, Field

from backend.repositories.repository_errors import RepositoryError, SupabaseConfigError
from backend.repositories.sources_repository import SourcesRepository
from backend.repositories.supabase_client import get_supabase_client
from backend.repositories.voice_notes_repository import VoiceNotesRepository
from backend.services.voice_note_service import VoiceNoteService
from backend.services.source_service import SourceService
from backend.utils.security import verify_api_key


MAX_LOG_TEXT_LENGTH = 200


def _truncate_text(text: Optional[str], limit: int = MAX_LOG_TEXT_LENGTH) -> str:
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return f"{text[:limit]}..."


class VoiceNoteCreateRequest(BaseModel):
    raw_text: str = Field(..., min_length=1)
    clean_text: Optional[str] = None
    message_id: int
    audio_file_id: str
    duration_seconds: Optional[float] = None


router = APIRouter(
    prefix="/api/voice-notes",
    tags=["Voice Notes"],
    dependencies=[Depends(verify_api_key)],
)


async def get_supabase() -> Any:
    return await get_supabase_client()


def get_voice_notes_repository(
    client: Any = Depends(get_supabase),
) -> VoiceNotesRepository:
    return VoiceNotesRepository(client=client)


def get_sources_repository(
    client: Any = Depends(get_supabase),
) -> SourcesRepository:
    return SourcesRepository(client=client)


def get_source_service(
    repository: SourcesRepository = Depends(get_sources_repository),
) -> SourceService:
    return SourceService(repository=repository)


def get_voice_note_service(
    repository: VoiceNotesRepository = Depends(get_voice_notes_repository),
    source_service: SourceService = Depends(get_source_service),
) -> VoiceNoteService:
    return VoiceNoteService(repository=repository, source_service=source_service)


@router.post("/add/voice-notes", tags=["Voice Notes"])
async def create_voice_note(
    payload: VoiceNoteCreateRequest,
    service: VoiceNoteService = Depends(get_voice_note_service),
) -> dict[str, Any]:
    logger.bind(
        message_id=payload.message_id,
        audio_file_id=payload.audio_file_id,
        duration_seconds=payload.duration_seconds,
        raw_text_length=len(payload.raw_text) if payload.raw_text else 0,
        raw_text_preview=_truncate_text(payload.raw_text),
        clean_text_length=len(payload.clean_text) if payload.clean_text else 0,
    ).debug("voice_notes.create.controller.entry")
    try:
        result = await service.create_voice_note_idempotent(
            raw_text=payload.raw_text,
            clean_text=payload.clean_text,
            message_id=payload.message_id,
            audio_file_id=payload.audio_file_id,
            duration_seconds=payload.duration_seconds,
        )
        logger.bind(
            message_id=payload.message_id,
            result_id=result.get("id") if isinstance(result, dict) else None,
            result_present=bool(result),
        ).debug("voice_notes.create.controller.response")
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except SupabaseConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except RepositoryError:
        logger.bind(message_id=payload.message_id).exception("voice_notes.create.failed")
        raise HTTPException(
            status_code=503,
            detail="Supabase unavailable",
        )


@router.get("")
async def list_voice_notes(
    source_id: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    created_after: Optional[datetime] = Query(None),
    created_before: Optional[datetime] = Query(None),
    service: VoiceNoteService = Depends(get_voice_note_service),
) -> list[dict[str, Any]]:
    try:
        return await service.list_voice_notes(
            source_id=source_id,
            limit=limit,
            offset=offset,
            created_after=created_after,
            created_before=created_before,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except SupabaseConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except RepositoryError:
        logger.exception("voice_notes.list.failed")
        raise HTTPException(
            status_code=503,
            detail="Supabase unavailable",
        )


@router.get("/{note_id}")
async def get_voice_note(
    note_id: str,
    service: VoiceNoteService = Depends(get_voice_note_service),
) -> dict[str, Any]:
    try:
        note = await service.get_voice_note(note_id)
    except SupabaseConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except RepositoryError:
        logger.exception("voice_notes.get.failed", extra={"note_id": note_id})
        raise HTTPException(
            status_code=503,
            detail="Supabase unavailable",
        )
    if not note:
        raise HTTPException(status_code=404, detail="Voice note not found")
    return note
