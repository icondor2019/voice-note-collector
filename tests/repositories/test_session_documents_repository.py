from __future__ import annotations

from typing import Any, Optional

import pytest

from backend.repositories.session_documents_repository import SessionDocumentsRepository


class _StubResponse:
    def __init__(self, data: Any = None, error: Optional[str] = None) -> None:
        self.data = data
        self.error = error


class _StubQuery:
    def __init__(self, response: _StubResponse) -> None:
        self._response = response
        self._filters: list[tuple[str, Any]] = []

    def select(self, *args: Any, **kwargs: Any) -> _StubQuery:
        return self

    def eq(self, field: str, value: Any) -> _StubQuery:
        self._filters.append((field, value))
        return self

    def in_(self, field: str, values: list[Any]) -> _StubQuery:
        self._filters.append((field, values))
        return self

    def is_(self, field: str, value: Any) -> _StubQuery:
        self._filters.append((field, value))
        return self

    def order(self, field: str, desc: bool = True) -> _StubQuery:
        return self

    def range(self, start: int, end: int) -> _StubQuery:
        return self

    def maybe_single(self) -> _StubQuery:
        return self

    async def execute(self) -> _StubResponse:
        return self._response


class _StubTable:
    def __init__(self, response: _StubResponse) -> None:
        self._response = response
        self.insert_payload: Optional[dict[str, Any]] = None
        self.update_payload: Optional[dict[str, Any]] = None

    def insert(self, payload: dict[str, Any]) -> _StubQuery:
        self.insert_payload = payload
        return _StubQuery(self._response)

    def select(self, *args: Any, **kwargs: Any) -> _StubQuery:
        return _StubQuery(self._response)

    def update(self, payload: dict[str, Any]) -> _StubQuery:
        self.update_payload = payload
        return _StubQuery(self._response)


class _StubClient:
    def __init__(self, response: _StubResponse) -> None:
        self._response = response
        self.table_name: Optional[str] = None
        self.table_instance: Optional[_StubTable] = None
        self._tables: dict[str, _StubTable] = {}

    def table(self, table_name: str) -> _StubTable:
        self.table_name = table_name
        if table_name not in self._tables:
            self._tables[table_name] = _StubTable(self._response)
        self.table_instance = self._tables[table_name]
        return self.table_instance


class TestSessionDocumentsRepository:
    @pytest.mark.anyio
    async def test_create_document_inserts_row(self) -> None:
        doc_data = {
            "id": "doc-uuid-123",
            "source_id": "source-1",
            "title": None,
            "content": None,
            "status": "ready",
            "parent_document_id": None,
            "telegram_user_id": None,
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
        }
        response = _StubResponse(data=doc_data)
        client = _StubClient(response)
        repo = SessionDocumentsRepository(client=client)

        result = await repo.create_document(source_id="source-1")

        assert result["status"] == "ready"
        assert result["source_id"] == "source-1"
        assert client.table_name == "session_documents"
        assert client.table_instance is not None
        assert client.table_instance.insert_payload is not None
        assert client.table_instance.insert_payload["status"] == "ready"
        assert client.table_instance.insert_payload["source_id"] == "source-1"

    @pytest.mark.anyio
    async def test_create_document_with_optional_fields(self) -> None:
        doc_data = {
            "id": "doc-uuid-123",
            "source_id": "source-1",
            "title": "Test Title",
            "content": "# Test Title\n\n## Summary\nSome content",
            "status": "ready",
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
        }
        response = _StubResponse(data=doc_data)
        client = _StubClient(response)
        repo = SessionDocumentsRepository(client=client)

        result = await repo.create_document(
            source_id="source-1",
            title="Test Title",
            content="# Test Title\n\n## Summary\nSome content",
        )

        assert result["title"] == "Test Title"
        assert client.table_instance.insert_payload["title"] == "Test Title"
        assert client.table_instance.insert_payload["content"] == "# Test Title\n\n## Summary\nSome content"

    @pytest.mark.anyio
    async def test_get_document_returns_row(self) -> None:
        doc_data = {
            "id": "doc-uuid-123",
            "source_id": "source-1",
            "title": "Test",
            "status": "ready",
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
        }
        response = _StubResponse(data=doc_data)
        client = _StubClient(response)
        repo = SessionDocumentsRepository(client=client)

        result = await repo.get_document("doc-uuid-123")

        assert result is not None
        assert result["id"] == "doc-uuid-123"

    @pytest.mark.anyio
    async def test_get_document_returns_none_when_not_found(self) -> None:
        response = _StubResponse(data=None)
        client = _StubClient(response)
        repo = SessionDocumentsRepository(client=client)

        result = await repo.get_document("nonexistent")

        assert result is None

    @pytest.mark.anyio
    async def test_update_document_updates_fields(self) -> None:
        doc_data = {
            "id": "doc-uuid-123",
            "source_id": "source-1",
            "title": "Updated Title",
            "status": "ready",
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T01:00:00Z",
        }
        response = _StubResponse(data=doc_data)
        client = _StubClient(response)
        repo = SessionDocumentsRepository(client=client)

        result = await repo.update_document("doc-uuid-123", title="Updated Title")

        assert result is not None
        assert result["title"] == "Updated Title"
        assert client.table_instance.update_payload["title"] == "Updated Title"
        assert "updated_at" in client.table_instance.update_payload

    @pytest.mark.anyio
    async def test_update_content_updates_content_field(self) -> None:
        doc_data = {
            "id": "doc-uuid-123",
            "source_id": "source-1",
            "title": "Test",
            "content": "# Updated Content\n\n## Summary\nNew content here",
            "status": "ready",
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T01:00:00Z",
        }
        response = _StubResponse(data=doc_data)
        client = _StubClient(response)
        repo = SessionDocumentsRepository(client=client)

        result = await repo.update_content("doc-uuid-123", "# Updated Content\n\n## Summary\nNew content here")

        assert result is not None
        assert result["content"] == "# Updated Content\n\n## Summary\nNew content here"
        assert client.table_instance.update_payload["content"] == "# Updated Content\n\n## Summary\nNew content here"
        assert "updated_at" in client.table_instance.update_payload

    @pytest.mark.anyio
    async def test_list_documents_returns_list(self) -> None:
        docs = [
            {"id": "doc-1", "source_id": "source-1", "status": "ready"},
            {"id": "doc-2", "source_id": "source-1", "status": "ready"},
        ]
        response = _StubResponse(data=docs)
        client = _StubClient(response)
        repo = SessionDocumentsRepository(client=client)

        result = await repo.list_documents(source_id="source-1")

        assert len(result) == 2

    @pytest.mark.anyio
    async def test_get_document_labels_returns_union(self) -> None:
        """Labels from all attached notes are returned, deduplicated."""
        # First call: voice_note_details → get note UUIDs
        details_response = _StubResponse(data=[
            {"voice_note_uuid": "note-1"},
            {"voice_note_uuid": "note-2"},
        ])
        # Second call: voice_note_labels → get labels
        labels_response = _StubResponse(data=[
            {"labels": {"id": 1, "label": "python"}},
            {"labels": {"id": 2, "label": "testing"}},
            {"labels": {"id": 1, "label": "python"}},  # duplicate
        ])

        call_count = 0

        class _MultiResponseClient:
            def __init__(self) -> None:
                self.table_name: Optional[str] = None

            def table(self, table_name: str) -> _StubTable:
                self.table_name = table_name
                nonlocal call_count
                call_count += 1
                if table_name == "voice_note_details":
                    return _StubTable(details_response)
                return _StubTable(labels_response)

        client = _MultiResponseClient()
        repo = SessionDocumentsRepository(client=client)

        result = await repo.get_document_labels("doc-1")

        # Should deduplicate label id=1
        assert len(result) == 2
        label_ids = {l["id"] for l in result}
        assert label_ids == {1, 2}

    @pytest.mark.anyio
    async def test_get_document_labels_returns_empty_when_no_notes(self) -> None:
        details_response = _StubResponse(data=[])
        client = _StubClient(details_response)
        repo = SessionDocumentsRepository(client=client)

        result = await repo.get_document_labels("doc-1")

        assert result == []

    @pytest.mark.anyio
    async def test_get_pending_note_ids_excludes_grouped(self) -> None:
        """Notes with document_uuid IS NOT NULL are excluded (handled by is_ filter)."""
        response = _StubResponse(data=[
            {"voice_note_uuid": "note-1", "voice_notes": {"id": "note-1", "source_id": "source-1"}},
            {"voice_note_uuid": "note-2", "voice_notes": {"id": "note-2", "source_id": "source-1"}},
        ])
        client = _StubClient(response)
        repo = SessionDocumentsRepository(client=client)

        result = await repo.get_pending_note_ids("source-1")

        assert len(result) == 2
        assert "note-1" in result
        assert "note-2" in result

    @pytest.mark.anyio
    async def test_get_pending_note_ids_returns_empty_when_all_grouped(self) -> None:
        response = _StubResponse(data=[])
        client = _StubClient(response)
        repo = SessionDocumentsRepository(client=client)

        result = await repo.get_pending_note_ids("source-1")

        assert result == []

    @pytest.mark.anyio
    async def test_get_valid_note_ids_excludes_already_grouped(self) -> None:
        """Notes with document_uuid IS NOT NULL are filtered out."""
        response = _StubResponse(data=[
            {
                "voice_note_uuid": "note-1",
                "status": "created",
                "voice_notes": {
                    "id": "note-1",
                    "source_id": "source-1",
                    "raw_text": "hello",
                    "created_at": "2026-01-01T00:00:00Z",
                },
            },
        ])
        client = _StubClient(response)
        repo = SessionDocumentsRepository(client=client)

        result = await repo.get_valid_note_ids("source-1", ["note-1", "note-2"])

        # Only note-1 returned (note-2 filtered by is_ document_uuid null + source match)
        assert len(result) == 1
        assert result[0]["voice_note_uuid"] == "note-1"
        assert result[0]["raw_text"] == "hello"

    @pytest.mark.anyio
    async def test_get_valid_note_ids_returns_empty_for_empty_input(self) -> None:
        client = _StubClient(_StubResponse(data=[]))
        repo = SessionDocumentsRepository(client=client)

        result = await repo.get_valid_note_ids("source-1", [])

        assert result == []

    @pytest.mark.anyio
    async def test_attach_notes_to_document_sets_uuid(self) -> None:
        response = _StubResponse(data=[])
        client = _StubClient(response)
        repo = SessionDocumentsRepository(client=client)

        await repo.attach_notes_to_document("doc-1", ["note-1", "note-2"])

        assert client.table_name == "voice_note_details"
        assert client.table_instance.update_payload["document_uuid"] == "doc-1"
        assert "updated_at" in client.table_instance.update_payload

    @pytest.mark.anyio
    async def test_attach_notes_to_document_noop_for_empty_list(self) -> None:
        client = _StubClient(_StubResponse(data=[]))
        repo = SessionDocumentsRepository(client=client)

        await repo.attach_notes_to_document("doc-1", [])

        # No table call should have been made
        assert client.table_name is None
