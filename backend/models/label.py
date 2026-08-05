from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from backend.models.voice_note_label import LabelOrigin


class Label(BaseModel):
    id: int
    label: str
    created_by: LabelOrigin
    created_at: datetime
    deleted_at: Optional[datetime] = None
