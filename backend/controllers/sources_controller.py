from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.repositories.repository_errors import RepositoryError, SupabaseConfigError
from backend.repositories.sources_repository import SourcesRepository
from backend.repositories.supabase_client import get_supabase_client
from backend.services.source_service import SourceService


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sources", tags=["Sources"])


class SourceCreateRequest(BaseModel):
    source_name: str = Field(..., min_length=1)
    author: Optional[str] = None
    comment: Optional[str] = None
    activate: bool = False


class ActivateByNameRequest(BaseModel):
    source_name: str = Field(..., min_length=1)


async def get_supabase() -> Any:
    return await get_supabase_client()


def get_sources_repository(
    client: Any = Depends(get_supabase),
) -> SourcesRepository:
    return SourcesRepository(client=client)


def get_source_service(
    repository: SourcesRepository = Depends(get_sources_repository),
) -> SourceService:
    return SourceService(repository=repository)


@router.post("", status_code=201)
async def create_source(
    payload: SourceCreateRequest,
    service: SourceService = Depends(get_source_service),
) -> dict[str, Any]:
    try:
        source = await service.create_source_and_optionally_activate(
            source_name=payload.source_name,
            author=payload.author,
            comment=payload.comment,
            activate=payload.activate,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except SupabaseConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except RepositoryError:
        logger.exception("sources.create.failed")
        raise HTTPException(
            status_code=503,
            detail="Supabase unavailable",
        )
    return source


@router.get("")
async def list_sources(
    status: Optional[str] = None,
    service: SourceService = Depends(get_source_service),
) -> list[dict[str, Any]]:
    try:
        return await service.list_sources(status=status)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except SupabaseConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except RepositoryError:
        logger.exception("sources.list.failed")
        raise HTTPException(
            status_code=503,
            detail="Supabase unavailable",
        )


@router.get("/active")
async def get_active_source(
    service: SourceService = Depends(get_source_service),
) -> dict[str, Any]:
    try:
        source = await service.get_active_source()
    except SupabaseConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except RepositoryError:
        logger.exception("sources.active.failed")
        raise HTTPException(
            status_code=503,
            detail="Supabase unavailable",
        )
    if not source:
        raise HTTPException(status_code=404, detail="Active source not found")
    return source


@router.post("/{source_id}/activate")
async def activate_source(
    source_id: str,
    service: SourceService = Depends(get_source_service),
) -> dict[str, Any]:
    try:
        activated = await service.activate_source_by_id(source_id)
    except SupabaseConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except RepositoryError:
        logger.exception("sources.activate.failed", extra={"source_id": source_id})
        raise HTTPException(
            status_code=503,
            detail="Supabase unavailable",
        )
    if not activated:
        raise HTTPException(status_code=404, detail="Source not found")
    return activated


@router.post("/activate-by-name")
async def activate_source_by_name(
    payload: ActivateByNameRequest,
    service: SourceService = Depends(get_source_service),
) -> dict[str, Any]:
    try:
        activated = await service.activate_source_by_name(payload.source_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except SupabaseConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except RepositoryError:
        logger.exception("sources.activate_by_name.failed", extra={"source_name": payload.source_name})
        raise HTTPException(
            status_code=503,
            detail="Supabase unavailable",
        )
    return activated
