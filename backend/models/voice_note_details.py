from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class NoteStatus(str, Enum):
    CREATED = "created"
    ENRICHED = "enriched"
    REVIEWED = "reviewed"


class VoiceNoteDetails(BaseModel):
    voice_note_uuid: UUID
    title: Optional[str]
    status: NoteStatus
    label_ids: list[int]
    created_at: datetime
    updated_at: datetime
