from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from backend.services.note_enrichment_service import NoteEnrichmentService


def _make_response(content: str) -> Any:
    message = SimpleNamespace(content=content)
    choice = SimpleNamespace(message=message)
    return SimpleNamespace(choices=[choice])


class _StubOpenAI:
    def __init__(self, content: str) -> None:
        self._content = content
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=self._create),
        )

    def _create(self, *args: Any, **kwargs: Any) -> Any:
        return _make_response(self._content)


class TestNoteEnrichmentService:
    @pytest.mark.anyio
    async def test_run_process_dev_environment_filters_source(self) -> None:
        details_repo = AsyncMock()
        details_repo.get_pending_notes_with_source.return_value = []
        labels_repo = AsyncMock()
        openai_client = _StubOpenAI("[]")
        settings = SimpleNamespace(ENVIRONMENT="dev")
        service = NoteEnrichmentService(details_repo, None, labels_repo, openai_client, settings)

        await service.run_process()

        details_repo.get_pending_notes_with_source.assert_awaited_once_with(
            "a0dcea10-ca65-4314-af78-ce096824aff1"
        )

    @pytest.mark.anyio
    async def test_run_process_non_dev_environment_no_filter(self) -> None:
        details_repo = AsyncMock()
        details_repo.get_pending_notes_with_source.return_value = []
        labels_repo = AsyncMock()
        openai_client = _StubOpenAI("[]")
        settings = SimpleNamespace(ENVIRONMENT="prod")
        service = NoteEnrichmentService(details_repo, None, labels_repo, openai_client, settings)

        await service.run_process()

        details_repo.get_pending_notes_with_source.assert_awaited_once_with(None)

    @pytest.mark.anyio
    async def test_run_process_caps_batch_size(self) -> None:
        details_repo = AsyncMock()
        notes = [
            {"voice_note_uuid": f"note-{idx}", "source_id": "source-1", "raw_text": "hi"}
            for idx in range(7)
        ]
        details_repo.get_pending_notes_with_source.return_value = notes
        labels_repo = AsyncMock()
        labels_repo.list_labels.return_value = []
        openai_client = _StubOpenAI("[]")
        settings = SimpleNamespace(ENVIRONMENT="dev")
        service = NoteEnrichmentService(details_repo, None, labels_repo, openai_client, settings)
        service._enrich_batch = AsyncMock(return_value=[])

        await service.run_process()

        service._enrich_batch.assert_awaited_once()
        batch_notes = service._enrich_batch.call_args.args[0]
        assert len(batch_notes) == 5

    @pytest.mark.anyio
    async def test_update_enrichment_called_for_each_result(self) -> None:
        details_repo = AsyncMock()
        details_repo.get_pending_notes_with_source.return_value = [
            {"voice_note_uuid": "note-1", "source_id": "source-1", "raw_text": "hi"},
            {"voice_note_uuid": "note-2", "source_id": "source-1", "raw_text": "hey"},
        ]
        labels_repo = AsyncMock()
        labels_repo.list_labels.return_value = []
        openai_client = _StubOpenAI("[]")
        settings = SimpleNamespace(ENVIRONMENT="dev")
        service = NoteEnrichmentService(details_repo, None, labels_repo, openai_client, settings)
        service._enrich_batch = AsyncMock(
            return_value=[
                {"voice_note_uuid": "note-1", "title": "Title 1", "label_ids": [1]},
                {"voice_note_uuid": "note-2", "title": "Title 2", "label_ids": [2]},
            ]
        )

        await service.run_process()

        assert details_repo.update_enrichment.await_count == 2
        details_repo.update_enrichment.assert_any_await("note-1", "Title 1", [1])
        details_repo.update_enrichment.assert_any_await("note-2", "Title 2", [2])

    @pytest.mark.anyio
    async def test_invalid_label_ids_filtered_before_update(self) -> None:
        details_repo = AsyncMock()
        details_repo.get_pending_notes_with_source.return_value = [
            {"voice_note_uuid": "note-1", "source_id": "source-1", "raw_text": "hi"}
        ]
        labels_repo = AsyncMock()
        labels_repo.list_labels.return_value = [
            {"id": 1, "label": "Work"},
            {"id": 2, "label": "Personal"},
        ]
        openai_client = _StubOpenAI(
            json.dumps(
                [
                    {
                        "voice_note_uuid": "note-1",
                        "title": "Hello",
                        "label_ids": [1, 999],
                    }
                ]
            )
        )
        settings = SimpleNamespace(ENVIRONMENT="dev")
        service = NoteEnrichmentService(details_repo, None, labels_repo, openai_client, settings)

        await service.run_process()

        details_repo.update_enrichment.assert_awaited_once_with("note-1", "Hello", [1])

    @pytest.mark.anyio
    async def test_label_ids_truncated_before_update(self) -> None:
        details_repo = AsyncMock()
        details_repo.get_pending_notes_with_source.return_value = [
            {"voice_note_uuid": "note-1", "source_id": "source-1", "raw_text": "hi"}
        ]
        labels_repo = AsyncMock()
        labels_repo.list_labels.return_value = [
            {"id": 1, "label": "A"},
            {"id": 2, "label": "B"},
            {"id": 3, "label": "C"},
            {"id": 4, "label": "D"},
            {"id": 5, "label": "E"},
            {"id": 6, "label": "F"},
        ]
        openai_client = _StubOpenAI(
            json.dumps(
                [
                    {
                        "voice_note_uuid": "note-1",
                        "title": "Hello",
                        "label_ids": [1, 2, 3, 4, 5, 6],
                    }
                ]
            )
        )
        settings = SimpleNamespace(ENVIRONMENT="dev")
        service = NoteEnrichmentService(details_repo, None, labels_repo, openai_client, settings)

        await service.run_process()

        details_repo.update_enrichment.assert_awaited_once_with(
            "note-1", "Hello", [1, 2, 3, 4, 5]
        )

    @pytest.mark.anyio
    async def test_no_pending_notes_skips_openai(self) -> None:
        details_repo = AsyncMock()
        details_repo.get_pending_notes_with_source.return_value = []
        labels_repo = AsyncMock()
        openai_client = _StubOpenAI("[]")
        openai_client.chat.completions.create = AsyncMock()
        settings = SimpleNamespace(ENVIRONMENT="dev")
        service = NoteEnrichmentService(details_repo, None, labels_repo, openai_client, settings)

        await service.run_process()

        openai_client.chat.completions.create.assert_not_called()

    @pytest.mark.anyio
    async def test_malformed_json_from_openai_is_handled(self) -> None:
        details_repo = AsyncMock()
        details_repo.get_pending_notes_with_source.return_value = [
            {"voice_note_uuid": "note-1", "source_id": "source-1", "raw_text": "hi"}
        ]
        labels_repo = AsyncMock()
        labels_repo.list_labels.return_value = []
        openai_client = _StubOpenAI("not-json")
        settings = SimpleNamespace(ENVIRONMENT="dev")
        service = NoteEnrichmentService(details_repo, None, labels_repo, openai_client, settings)

        await service.run_process()

        details_repo.update_enrichment.assert_not_called()
