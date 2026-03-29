from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status

from backend.repositories.telegram_ingestion_event_store import FileIngestionEventStore
from backend.services.telegram_ingestion_service import TelegramIngestionService


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/telegram", tags=["Telegram"])


def get_event_store(file_path: Optional[Path] = None) -> FileIngestionEventStore:
    return FileIngestionEventStore(file_path or "./data/telegram_ingestion_events.jsonl")


def get_ingestion_service(
    event_store: FileIngestionEventStore = Depends(get_event_store),
) -> TelegramIngestionService:
    return TelegramIngestionService(event_store)


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
        result = ingestion_service.ingest_update(payload)
    except OSError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to persist ingestion event",
        )

    return {"status": "ok", **result}
