from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class Label(BaseModel):
    id: int
    label: str
    created_at: datetime
