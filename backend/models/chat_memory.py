from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class ChatMemoryEntry(BaseModel):
    id: UUID
    telegram_user_id: int
    role: str
    content: str
    created_at: datetime
