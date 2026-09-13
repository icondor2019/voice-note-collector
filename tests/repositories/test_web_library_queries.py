from __future__ import annotations

from typing import Any

import pytest

from backend.repositories.session_documents_repository import SessionDocumentsRepository
from backend.repositories.labels_repository import LabelsRepository
from backend.repositories.voice_notes_repository import VoiceNotesRepository


class Response:
    def __init__(self, data: Any) -> None:
        self.data = data
        self.error = None


class Query:
    def __init__(self, data: Any, calls: list[tuple[str, str, Any]], table: str) -> None:
        self.data = data
        self.calls = calls
        self.table = table
        self.filters: list[tuple[str, str, Any]] = []
        self.range_value: tuple[int, int] | None = None

    def select(self, *args: Any, **kwargs: Any) -> "Query":
        self.calls.append((self.table, "select", args[0] if args else None))
        return self

    def eq(self, field: str, value: Any) -> "Query":
        self.calls.append((self.table, "eq", (field, value)))
        self.filters.append(("eq", field, value))
        return self
    def gte(self, *args: Any, **kwargs: Any) -> "Query": return self
    def lte(self, *args: Any, **kwargs: Any) -> "Query": return self
    def in_(self, field: str, values: list[Any]) -> "Query":
        self.calls.append((self.table, "in", (field, values)))
        self.filters.append(("in", field, values))
        return self

    def is_(self, field: str, value: Any) -> "Query":
        self.calls.append((self.table, "is", (field, value)))
        self.filters.append(("is", field, value))
        return self

    def order(self, *args: Any, **kwargs: Any) -> "Query":
        self.calls.append((self.table, "order", args[0] if args else None))
        return self

    def range(self, start: int, end: int) -> "Query":
        self.calls.append((self.table, "range", (start, end)))
        self.range_value = (start, end)
        return self
    def limit(self, *args: Any, **kwargs: Any) -> "Query": return self
    def maybe_single(self) -> "Query": return self

    async def execute(self) -> Response:
        rows = list(self.data)
        for operation, field, expected in self.filters:
            expected_values = expected if operation == "in" else [expected]
            filtered = []
            for row in rows:
                values: list[Any] = [row]
                for part in field.split("."):
                    next_values: list[Any] = []
                    for value in values:
                        child = value.get(part) if isinstance(value, dict) else None
                        next_values.extend(child if isinstance(child, list) else [child])
                    values = next_values
                if operation == "is" and expected == "null":
                    matches = any(value is None for value in values)
                else:
                    matches = any(value in expected_values for value in values)
                if matches:
                    filtered.append(row)
            rows = filtered
        if self.range_value:
            start, end = self.range_value
            rows = rows[start : end + 1]
        return Response(rows)


class Table:
    def __init__(self, data: Any, calls: list[tuple[str, str, Any]], table: str) -> None:
        self.data = data
        self.calls = calls
        self.table = table

    def select(self, *args: Any, **kwargs: Any) -> Query:
        query = Query(self.data, self.calls, self.table)
        return query.select(*args, **kwargs)


class Client:
    def __init__(self, tables: dict[str, Any]) -> None:
        self.tables = tables
        self.calls: list[tuple[str, str, Any]] = []

    def table(self, name: str) -> Table:
        return Table(self.tables.get(name, []), self.calls, name)


@pytest.mark.anyio
async def test_web_notes_use_enrichment_fallback_and_or_label_filter() -> None:
    client = Client({
        "voice_notes": [
            {"id": "n1", "raw_text": "raw one", "clean_text": "clean one", "created_at": "2026-09-10", "sources": {"source_name": "Source"}, "voice_note_details": {"title": "Title", "status": "enriched"}, "voice_note_labels": [{"label_id": 1, "deleted_at": None}]},
            {"id": "n2", "raw_text": "raw two", "clean_text": None, "created_at": "2026-09-09", "sources": {"source_name": "Source"}, "voice_note_details": {"title": None, "status": "created"}, "voice_note_labels": [{"label_id": 2, "deleted_at": None}]},
        ],
        "voice_note_labels": [
            {"voice_note_uuid": "n1", "labels": {"id": 1, "label": "architecture"}},
            {"voice_note_uuid": "n2", "labels": {"id": 2, "label": "writing"}},
        ],
    })
    repo = VoiceNotesRepository(client)

    result = await repo.list_web_notes(label_ids=[1, 99])

    assert [row["id"] for row in result] == ["n1"]
    assert result[0]["display_title"] == "Title"
    assert result[0]["preview"] == "clean one"
    assert ("voice_notes", "in", ("voice_note_labels.label_id", [1, 99])) in client.calls
    assert ("voice_notes", "is", ("voice_note_labels.deleted_at", "null")) in client.calls


@pytest.mark.anyio
async def test_web_notes_apply_source_metadata_filters_before_pagination() -> None:
    client = Client({
        "voice_notes": [
            *[
                {"id": f"other-{index}", "raw_text": "other", "created_at": "2026-09-11", "source_id": "s2",
                 "sources": {"source_name": "Other", "type": "podcast", "author": "B", "usage_status": "archive"},
                 "voice_note_details": {"status": "created"}}
                for index in range(1000)
            ],
            {"id": "n1", "raw_text": "one", "created_at": "2026-09-10", "source_id": "s1",
             "sources": {"source_name": "Book", "type": "book", "author": "A", "usage_status": "active"},
             "voice_note_details": {"status": "created"}},
        ],
        "voice_note_labels": [],
    })

    result = await VoiceNotesRepository(client).list_web_notes(
        source_type="book", source_author="A", source_usage_status="active", offset=0, limit=1
    )

    assert [row["id"] for row in result] == ["n1"]
    note_calls = [call for call in client.calls if call[0] == "voice_notes"]
    assert ("voice_notes", "eq", ("sources.type", "book")) in note_calls
    assert ("voice_notes", "eq", ("sources.author", "A")) in note_calls
    assert ("voice_notes", "eq", ("sources.usage_status", "active")) in note_calls
    assert note_calls.index(("voice_notes", "eq", ("sources.author", "A"))) < note_calls.index(
        ("voice_notes", "range", (0, 0))
    )


@pytest.mark.anyio
async def test_web_documents_filter_in_supabase_and_resolve_label_documents() -> None:
    client = Client({
        "session_documents": [
            {"id": "d1", "source_id": "s1", "status": "ready", "created_at": "2026-09-10",
             "content": "# Result", "sources": {"source_name": "Talk", "type": "video", "author": "Miguel Anxo Bastos", "usage_status": "active"}},
            {"id": "d2", "source_id": "s2", "status": "reviewed", "created_at": "2026-09-09",
             "content": "Other", "sources": {"source_name": "Other", "type": "book", "author": "Other", "usage_status": "archive"}},
        ],
        "voice_note_labels": [
            {"voice_note_uuid": "n1", "label_id": 4, "deleted_at": None, "labels": {"id": 4, "label": "economy"}},
        ],
        "voice_note_details": [{"voice_note_uuid": "n1", "document_uuid": "d1"}],
    })

    result = await SessionDocumentsRepository(client).list_web_documents(
        source_type="video", source_author="Miguel Anxo Bastos",
        source_usage_status="active", status="ready", label_ids=[4], limit=24,
    )

    assert [row["id"] for row in result] == ["d1"]
    document_calls = [call for call in client.calls if call[0] == "session_documents"]
    assert ("session_documents", "eq", ("sources.author", "Miguel Anxo Bastos")) in document_calls
    assert ("session_documents", "in", ("id", ["d1"])) in document_calls
    assert document_calls[-2:] == [
        ("session_documents", "order", "created_at"),
        ("session_documents", "range", (0, 23)),
    ]


@pytest.mark.anyio
async def test_document_label_frequencies_count_and_sort_active_pairs() -> None:
    client = Client({
        "voice_note_details": [
            {"voice_note_uuid": "n1", "document_uuid": "d1"},
            {"voice_note_uuid": "n2", "document_uuid": "d1"},
        ],
        "voice_note_labels": [
            {"voice_note_uuid": "n1", "labels": {"id": 2, "label": "writing"}},
            {"voice_note_uuid": "n1", "labels": {"id": 1, "label": "architecture"}},
            {"voice_note_uuid": "n2", "labels": {"id": 1, "label": "architecture"}},
        ],
    })
    repo = SessionDocumentsRepository(client)

    result = await repo.get_label_frequencies_for_documents(["d1"])

    assert result["d1"] == [
        {"id": 1, "label": "architecture", "count": 2},
        {"id": 2, "label": "writing", "count": 1},
    ]


@pytest.mark.anyio
async def test_ranked_labels_counts_distinct_notes_and_excludes_deleted_labels() -> None:
    client = Client({
        "labels": [
            {"id": 1, "label": "common", "deleted_at": None},
            {"id": 2, "label": "rare", "deleted_at": None},
            {"id": 3, "label": "deleted", "deleted_at": "2026-01-01"},
        ],
        "voice_note_labels": [
            {"voice_note_uuid": "n1", "label_id": 1},
            {"voice_note_uuid": "n1", "label_id": 1},
            {"voice_note_uuid": "n2", "label_id": 1},
            {"voice_note_uuid": "n3", "label_id": 2},
            {"voice_note_uuid": "n4", "label_id": 3},
            {"voice_note_uuid": "n5", "label_id": 99},
        ],
    })

    result = await LabelsRepository(client).list_ranked_labels()

    assert result == [
        {"id": 1, "label": "common", "count": 2},
        {"id": 2, "label": "rare", "count": 1},
    ]
