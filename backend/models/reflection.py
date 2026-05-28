from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class ReflectionEntry(BaseModel):
    id: UUID
    telegram_user_id: int
    voice_note_id: Optional[UUID]
    question_type: str
    question_text: str
    answer_text: Optional[str]
    rating: Optional[int]
    feedback: Optional[str]
    status: str
    created_at: datetime
    completed_at: Optional[datetime]


class ReflectionQuestionResult(BaseModel):
    """Result returned when a reflection question is generated."""

    reflection_id: UUID
    question_type: str
    question_text: str


class ReflectionRatingResult(BaseModel):
    """Result returned when a reflection is completed with rating."""

    rating: int
    feedback: str
