"""Pydantic models for source creation."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, field_validator

VALID_SOURCE_TYPES = {
    "youtube",
    "instagram",
    "facebook",
    "linkedin",
    "web",
    "book",
    "course",
    "thought",
}

VALID_PREFIXES = ("yt-", "ig-", "fb-", "lkn-", "wb-", "bk-", "cr-", "th-")


class SourceCreateByAgentRequest(BaseModel):
    """Source creation request validated by the agent conversation flow."""

    source_name: str = Field(..., min_length=1)
    type: str = Field(...)
    url: Optional[str] = None
    author: Optional[str] = None
    comment: Optional[str] = None

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        if v not in VALID_SOURCE_TYPES:
            raise ValueError(
                f"Invalid source type '{v}'. Must be one of: {', '.join(sorted(VALID_SOURCE_TYPES))}"
            )
        return v

    @field_validator("source_name")
    @classmethod
    def validate_source_name_prefix(cls, v: str) -> str:
        if not any(v.startswith(prefix) for prefix in VALID_PREFIXES):
            raise ValueError(
                f"Source name must start with one of: {', '.join(VALID_PREFIXES)}. "
                f"Got: '{v}'"
            )
        return v


class SourceUpdateRequest(BaseModel):
    """Source update request for the enrich phase (all fields optional)."""

    source_name: Optional[str] = None
    author: Optional[str] = None
    comment: Optional[str] = None

    @field_validator("source_name")
    @classmethod
    def validate_source_name_prefix(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if not any(v.startswith(prefix) for prefix in VALID_PREFIXES):
            raise ValueError(
                f"Source name must start with one of: {', '.join(VALID_PREFIXES)}. "
                f"Got: '{v}'"
            )
        return v
