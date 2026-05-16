from __future__ import annotations

from typing import Any

import openai
from fastapi import APIRouter, BackgroundTasks, Depends
from fastapi.responses import JSONResponse

from backend.repositories.labels_repository import LabelsRepository
from backend.repositories.supabase_client import get_supabase_client
from backend.repositories.voice_note_details_repository import VoiceNoteDetailsRepository
from backend.repositories.voice_notes_repository import VoiceNotesRepository
from backend.services.note_enrichment_service import NoteEnrichmentService
from backend.utils.security import verify_api_key
from configuration.settings import settings


router = APIRouter(
    prefix="/api/enrichment",
    tags=["Enrichment"],
    dependencies=[Depends(verify_api_key)],
)


async def get_supabase() -> Any:
    return await get_supabase_client()


def get_voice_note_details_repository(
    client: Any = Depends(get_supabase),
) -> VoiceNoteDetailsRepository:
    return VoiceNoteDetailsRepository(client=client)


def get_voice_notes_repository(
    client: Any = Depends(get_supabase),
) -> VoiceNotesRepository:
    return VoiceNotesRepository(client=client)


def get_labels_repository(
    client: Any = Depends(get_supabase),
) -> LabelsRepository:
    return LabelsRepository(client=client)


def get_enrichment_service(
    details_repository: VoiceNoteDetailsRepository = Depends(
        get_voice_note_details_repository
    ),
    voice_notes_repository: VoiceNotesRepository = Depends(get_voice_notes_repository),
    labels_repository: LabelsRepository = Depends(get_labels_repository),
) -> NoteEnrichmentService:
    openai_client = openai.OpenAI(api_key=settings.OPENAI_API_KEY)
    return NoteEnrichmentService(
        details_repo=details_repository,
        voice_notes_repo=voice_notes_repository,
        labels_repo=labels_repository,
        openai_client=openai_client,
        settings=settings,
    )


@router.post("/run")
async def run_enrichment(
    background_tasks: BackgroundTasks,
    service: NoteEnrichmentService = Depends(get_enrichment_service),
) -> JSONResponse:
    background_tasks.add_task(service.run_process)
    return JSONResponse(
        {"message": "batch enrichment process initiated"},
        status_code=202,
    )
