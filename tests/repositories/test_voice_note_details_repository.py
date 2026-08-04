from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

import pytest

from backend.models.voice_note_details import NoteStatus
from backend.repositories.repository_errors import RepositoryError
from backend.repositories.voice_note_details_repository import VoiceNoteDetailsRepository


class _StubResponse:
    def __init__(self, data: Any = None, error: Optional[str] = None) -> None:
        self.data = data
        self.error = error


class _StubQuery:
    def __init__(self, response: _StubResponse) -> None:
        self._response = response

    def select(self, *args: Any, **kwargs: Any) -> _StubQuery:
        return self

    def eq(self, *args: Any, **kwargs: Any) -> _StubQuery:
        return self

    def maybe_single(self) -> _StubQuery:
        return self

    def update(self, *args: Any, **kwargs: Any) -> _StubQuery:
        return self

    async def execute(self) -> _StubResponse:
        return self._response


class _StubTable:
    def __init__(self, response: _StubResponse) -> None:
        self._response = response
        self.insert_payload: Optional[dict[str, Any]] = None
        self.update_payload: Optional[dict[str, Any]] = None
        self.updated_voice_note_uuid: Optional[str] = None
        self.selected: Optional[str] = None

    def insert(self, payload: dict[str, Any]) -> _StubQuery:
        self.insert_payload = payload
        return _StubQuery(self._response)

    def update(self, payload: dict[str, Any]) -> _StubQuery:
        self.update_payload = payload
        return _StubQuery(self._response)

    def select(self, *args: Any, **kwargs: Any) -> _StubQuery:
        self.selected = args[0] if args else None
        return _StubQuery(self._response)


class _StubClient:
    def __init__(self, response: _StubResponse) -> None:
        self._response = response
        self.table_name: Optional[str] = None
        self.table_instance: Optional[_StubTable] = None

    def table(self, table_name: str) -> _StubTable:
        self.table_name = table_name
        self.table_instance = _StubTable(self._response)
        return self.table_instance


class TestVoiceNoteDetailsRepository:
    @pytest.mark.anyio
    async def test_create_details_inserts_defaults(self) -> None:
        created_at = datetime.now(timezone.utc)
        response = _StubResponse(
            data={
                "voice_note_uuid": "note-1",
                "status": NoteStatus.CREATED.value,
                "created_at": created_at,
            }
        )
        client = _StubClient(response)
        repository = VoiceNoteDetailsRepository(client)

        result = await repository.create_details("note-1")

        assert result == response.data
        assert client.table_name == "voice_note_details"
        assert client.table_instance is not None
        assert client.table_instance.insert_payload == {
            "voice_note_uuid": "note-1",
            "status": NoteStatus.CREATED.value,
        }

    @pytest.mark.anyio
    async def test_create_details_raises_on_error(self) -> None:
        response = _StubResponse(error="bad insert")
        repository = VoiceNoteDetailsRepository(_StubClient(response))

        with pytest.raises(RepositoryError):
            await repository.create_details("note-1")

    @pytest.mark.anyio
    async def test_get_details_returns_row(self) -> None:
        response = _StubResponse(data={"voice_note_uuid": "note-1"})
        repository = VoiceNoteDetailsRepository(_StubClient(response))

        result = await repository.get_details("note-1")

        assert result == response.data

    @pytest.mark.anyio
    async def test_get_details_returns_none_when_missing(self) -> None:
        response = _StubResponse(data=None)
        repository = VoiceNoteDetailsRepository(_StubClient(response))

        result = await repository.get_details("note-1")

        assert result is None

    @pytest.mark.anyio
    async def test_update_status_sets_timestamp(self) -> None:
        response = _StubResponse(
            data={"voice_note_uuid": "note-1", "status": NoteStatus.ENRICHED.value}
        )
        client = _StubClient(response)
        repository = VoiceNoteDetailsRepository(client)

        result = await repository.update_status("note-1", NoteStatus.ENRICHED.value)

        assert result == response.data
        assert client.table_instance is not None
        assert client.table_instance.update_payload is not None
        assert client.table_instance.update_payload["status"] == NoteStatus.ENRICHED.value
        assert "updated_at" in client.table_instance.update_payload

    @pytest.mark.anyio
    async def test_update_title_sets_timestamp(self) -> None:
        response = _StubResponse(data={"voice_note_uuid": "note-1", "title": "Hello"})
        client = _StubClient(response)
        repository = VoiceNoteDetailsRepository(client)

        result = await repository.update_title("note-1", "Hello")

        assert result == response.data
        assert client.table_instance is not None
        assert client.table_instance.update_payload is not None
        assert client.table_instance.update_payload["title"] == "Hello"
        assert "updated_at" in client.table_instance.update_payload

    @pytest.mark.anyio
    async def test_get_pending_notes_uses_inner_join_on_voice_notes(self) -> None:
        """Without !inner PostgREST returns every pending note with voice_notes nulled
        out, so the source filter silently degrades into caller-side discarding."""
        client = _StubClient(_StubResponse(data=[]))
        repository = VoiceNoteDetailsRepository(client)

        await repository.get_pending_notes_with_source("source-1")

        assert client.table_instance is not None
        assert client.table_instance.selected == "*, voice_notes!inner(source_id, raw_text)"

    @pytest.mark.anyio
    async def test_get_pending_notes_flattens_nested_voice_note(self) -> None:
        response = _StubResponse(
            data=[
                {
                    "voice_note_uuid": "note-1",
                    "status": NoteStatus.CREATED.value,
                    "voice_notes": {"source_id": "source-1", "raw_text": "hello"},
                }
            ]
        )
        repository = VoiceNoteDetailsRepository(_StubClient(response))

        result = await repository.get_pending_notes_with_source("source-1")

        assert result == [
            {
                "voice_note_uuid": "note-1",
                "status": NoteStatus.CREATED.value,
                "source_id": "source-1",
                "raw_text": "hello",
            }
        ]

    @pytest.mark.anyio
    async def test_update_enrichment_sets_title_and_status(self) -> None:
        response = _StubResponse(data={"voice_note_uuid": "note-1", "title": "Hello"})
        client = _StubClient(response)
        repository = VoiceNoteDetailsRepository(client)

        result = await repository.update_enrichment("note-1", "Hello")

        assert result == response.data
        assert client.table_instance is not None
        payload = client.table_instance.update_payload
        assert payload is not None
        assert payload["title"] == "Hello"
        assert payload["status"] == NoteStatus.ENRICHED.value
        assert "label_ids" not in payload
