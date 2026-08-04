from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class LabelOrigin(str, Enum):
    LLM = "llm"
    USER = "user"


class VoiceNoteLabel(BaseModel):
    id: UUID
    voice_note_uuid: UUID
    label_id: int
    applied_by: LabelOrigin
    created_at: datetime
    deleted_at: Optional[datetime] = None
