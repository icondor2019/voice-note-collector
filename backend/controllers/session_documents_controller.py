from __future__ import annotations

from typing import Any

import openai
from fastapi import APIRouter, Depends, HTTPException
from loguru import logger

from backend.models.session_document import SessionDocumentCreateRequest
from backend.repositories.labels_repository import LabelsRepository
from backend.repositories.session_documents_repository import SessionDocumentsRepository
from backend.repositories.supabase_client import get_supabase_client
from backend.repositories.voice_note_details_repository import VoiceNoteDetailsRepository
from backend.repositories.voice_note_labels_repository import VoiceNoteLabelsRepository
from backend.repositories.voice_notes_repository import VoiceNotesRepository
from backend.services.note_enrichment_service import NoteEnrichmentService
from backend.services.session_builder_service import (
    EnrichmentIncompleteError,
    NoValidNotesError,
    SessionBuilderService,
)
from backend.utils.security import verify_api_key
from configuration.settings import settings


router = APIRouter(
    prefix="/api/session-documents",
    tags=["Session Documents"],
    dependencies=[Depends(verify_api_key)],
)


async def get_supabase() -> Any:
    return await get_supabase_client()


def get_session_documents_repository(
    client: Any = Depends(get_supabase),
) -> SessionDocumentsRepository:
    return SessionDocumentsRepository(client=client)


def get_voice_notes_repository(
    client: Any = Depends(get_supabase),
) -> VoiceNotesRepository:
    return VoiceNotesRepository(client=client)


def get_voice_note_details_repository(
    client: Any = Depends(get_supabase),
) -> VoiceNoteDetailsRepository:
    return VoiceNoteDetailsRepository(client=client)


def get_labels_repository(
    client: Any = Depends(get_supabase),
) -> LabelsRepository:
    return LabelsRepository(client=client)


def get_voice_note_labels_repository(
    client: Any = Depends(get_supabase),
) -> VoiceNoteLabelsRepository:
    return VoiceNoteLabelsRepository(client=client)


def get_enrichment_service(
    details_repository: VoiceNoteDetailsRepository = Depends(
        get_voice_note_details_repository
    ),
    voice_notes_repository: VoiceNotesRepository = Depends(get_voice_notes_repository),
    labels_repository: LabelsRepository = Depends(get_labels_repository),
    note_labels_repository: VoiceNoteLabelsRepository = Depends(
        get_voice_note_labels_repository
    ),
) -> NoteEnrichmentService:
    openai_client = openai.OpenAI(api_key=settings.OPENAI_API_KEY)
    return NoteEnrichmentService(
        details_repo=details_repository,
        voice_notes_repo=voice_notes_repository,
        labels_repo=labels_repository,
        note_labels_repo=note_labels_repository,
        openai_client=openai_client,
        settings=settings,
    )


def get_session_builder_service(
    session_documents_repository: SessionDocumentsRepository = Depends(
        get_session_documents_repository
    ),
    voice_notes_repository: VoiceNotesRepository = Depends(get_voice_notes_repository),
    voice_note_details_repository: VoiceNoteDetailsRepository = Depends(
        get_voice_note_details_repository
    ),
    note_enrichment_service: NoteEnrichmentService = Depends(get_enrichment_service),
) -> SessionBuilderService:
    openai_client = openai.OpenAI(api_key=settings.OPENAI_API_KEY)
    return SessionBuilderService(
        session_documents_repository=session_documents_repository,
        voice_notes_repository=voice_notes_repository,
        voice_note_details_repository=voice_note_details_repository,
        note_enrichment_service=note_enrichment_service,
        openai_client=openai_client,
        settings=settings,
    )


@router.post("", status_code=201)
async def create_session_document(
    payload: SessionDocumentCreateRequest,
    service: SessionBuilderService = Depends(get_session_builder_service),
) -> dict[str, Any]:
    """Create a session document from explicit note_ids."""
    try:
        note_ids_str = [str(nid) for nid in payload.note_ids]
        document = await service.build(
            source_id=str(payload.source_id),
            note_ids=note_ids_str,
        )
        return document
    except NoValidNotesError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except EnrichmentIncompleteError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@router.get("/{document_id}")
async def get_session_document(
    document_id: str,
    repository: SessionDocumentsRepository = Depends(
        get_session_documents_repository
    ),
) -> dict[str, Any]:
    """Fetch a session document with its attached labels."""
    document = await repository.get_document(document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Session document not found")

    labels = await repository.get_document_labels(document_id)

    return {
        **document,
        "labels": labels,
    }
