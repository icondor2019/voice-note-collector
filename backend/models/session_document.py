from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class SessionDocument(BaseModel):
    id: UUID
    source_id: UUID
    title: Optional[str] = None
    content: Optional[str] = None
    status: str
    parent_document_id: Optional[UUID] = None
    telegram_user_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime


class SessionDocumentPreview(BaseModel):
    source_name: str
    pending_count: int
    un_enriched_count: int
    time_range: Optional[str] = None
    notes: list[dict]


class SessionDocumentCreateRequest(BaseModel):
    source_id: UUID
    note_ids: list[UUID]
    title: Optional[str] = None
