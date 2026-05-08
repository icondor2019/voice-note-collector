from __future__ import annotations

from typing import Any, Optional

import pytest

from backend.services.voice_note_service import VoiceNoteService


class _StubVoiceNotesRepository:
    def __init__(self, *, existing: Optional[dict[str, Any]] = None) -> None:
        self.existing = existing
        self.created_payload: Optional[dict[str, Any]] = None
        self.create_result = {"id": "note-1"}

    async def get_voice_note_by_message_id(self, message_id: int) -> Optional[dict[str, Any]]:
        return self.existing

    async def create_voice_note(
        self,
        source_id: str,
        raw_text: str,
        clean_text: Optional[str],
        message_id: int,
        audio_file_id: str,
        duration_seconds: Optional[float] = None,
    ) -> dict[str, Any]:
        self.created_payload = {
            "source_id": source_id,
            "raw_text": raw_text,
            "clean_text": clean_text,
            "message_id": message_id,
            "audio_file_id": audio_file_id,
            "duration_seconds": duration_seconds,
        }
        return self.create_result


class _StubSourceService:
    async def ensure_default_source(self) -> dict[str, Any]:
        return {"id": "source-1"}


class _StubDetailsRepository:
    def __init__(self) -> None:
        self.created_for: list[str] = []

    async def create_details(self, voice_note_uuid: str) -> dict[str, Any]:
        self.created_for.append(voice_note_uuid)
        return {"voice_note_uuid": voice_note_uuid}


class TestVoiceNoteService:
    @pytest.mark.anyio
    async def test_create_voice_note_idempotent_creates_details_on_new_insert(self) -> None:
        repository = _StubVoiceNotesRepository(existing=None)
        details_repo = _StubDetailsRepository()
        service = VoiceNoteService(
            repository=repository,
            source_service=_StubSourceService(),
            details_repository=details_repo,
        )

        result = await service.create_voice_note_idempotent(
            raw_text="hello",
            clean_text=None,
            message_id=10,
            audio_file_id="file-1",
            duration_seconds=None,
        )

        assert result == repository.create_result
        assert details_repo.created_for == ["note-1"]

    @pytest.mark.anyio
    async def test_create_voice_note_idempotent_skips_details_on_duplicate(self) -> None:
        repository = _StubVoiceNotesRepository(existing={"id": "note-1"})
        details_repo = _StubDetailsRepository()
        service = VoiceNoteService(
            repository=repository,
            source_service=_StubSourceService(),
            details_repository=details_repo,
        )

        result = await service.create_voice_note_idempotent(
            raw_text="hello",
            clean_text=None,
            message_id=10,
            audio_file_id="file-1",
            duration_seconds=None,
        )

        assert result == {"id": "note-1"}
        assert details_repo.created_for == []
