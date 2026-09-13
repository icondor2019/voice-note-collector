from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from backend.services.note_enrichment_service import (
    ENRICHMENT_MAX_BATCH_SIZE,
    NoteEnrichmentService,
    split_into_balanced_batches,
)


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
        note_labels_repo = AsyncMock()
        openai_client = _StubOpenAI("[]")
        settings = SimpleNamespace(ENVIRONMENT="dev", MAX_LLM_LABEL_CREATIONS_PER_RUN=20)
        service = NoteEnrichmentService(
            details_repo, None, labels_repo, note_labels_repo, openai_client, settings
        )

        await service.run_process()

        details_repo.get_pending_notes_with_source.assert_awaited_once_with(
            "a0dcea10-ca65-4314-af78-ce096824aff1"
        )

    @pytest.mark.anyio
    async def test_run_process_non_dev_environment_no_filter(self) -> None:
        details_repo = AsyncMock()
        details_repo.get_pending_notes_with_source.return_value = []
        labels_repo = AsyncMock()
        note_labels_repo = AsyncMock()
        openai_client = _StubOpenAI("[]")
        settings = SimpleNamespace(ENVIRONMENT="prod", MAX_LLM_LABEL_CREATIONS_PER_RUN=20)
        service = NoteEnrichmentService(
            details_repo, None, labels_repo, note_labels_repo, openai_client, settings
        )

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
        note_labels_repo = AsyncMock()
        labels_repo.list_labels.return_value = []
        openai_client = _StubOpenAI("[]")
        settings = SimpleNamespace(ENVIRONMENT="dev", MAX_LLM_LABEL_CREATIONS_PER_RUN=20)
        service = NoteEnrichmentService(
            details_repo, None, labels_repo, note_labels_repo, openai_client, settings
        )
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
        note_labels_repo = AsyncMock()
        labels_repo.list_labels.return_value = []
        openai_client = _StubOpenAI("[]")
        settings = SimpleNamespace(ENVIRONMENT="dev", MAX_LLM_LABEL_CREATIONS_PER_RUN=20)
        service = NoteEnrichmentService(
            details_repo, None, labels_repo, note_labels_repo, openai_client, settings
        )
        service._enrich_batch = AsyncMock(
            return_value=[
                {"voice_note_uuid": "note-1", "title": "Title 1", "label_ids": [1]},
                {"voice_note_uuid": "note-2", "title": "Title 2", "label_ids": [2]},
            ]
        )

        await service.run_process()

        assert details_repo.update_enrichment.await_count == 2
        details_repo.update_enrichment.assert_any_await("note-1", "Title 1")
        details_repo.update_enrichment.assert_any_await("note-2", "Title 2")

        assert note_labels_repo.replace_llm_labels.await_count == 2
        note_labels_repo.replace_llm_labels.assert_any_await("note-1", [1])
        note_labels_repo.replace_llm_labels.assert_any_await("note-2", [2])

    @pytest.mark.anyio
    async def test_invalid_label_ids_filtered_before_update(self) -> None:
        details_repo = AsyncMock()
        details_repo.get_pending_notes_with_source.return_value = [
            {"voice_note_uuid": "note-1", "source_id": "source-1", "raw_text": "hi"}
        ]
        labels_repo = AsyncMock()
        note_labels_repo = AsyncMock()
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
        settings = SimpleNamespace(ENVIRONMENT="dev", MAX_LLM_LABEL_CREATIONS_PER_RUN=20)
        service = NoteEnrichmentService(
            details_repo, None, labels_repo, note_labels_repo, openai_client, settings
        )

        await service.run_process()

        details_repo.update_enrichment.assert_awaited_once_with("note-1", "Hello")
        note_labels_repo.replace_llm_labels.assert_awaited_once_with("note-1", [1])

    @pytest.mark.anyio
    async def test_label_ids_truncated_before_update(self) -> None:
        details_repo = AsyncMock()
        details_repo.get_pending_notes_with_source.return_value = [
            {"voice_note_uuid": "note-1", "source_id": "source-1", "raw_text": "hi"}
        ]
        labels_repo = AsyncMock()
        note_labels_repo = AsyncMock()
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
        settings = SimpleNamespace(ENVIRONMENT="dev", MAX_LLM_LABEL_CREATIONS_PER_RUN=20)
        service = NoteEnrichmentService(
            details_repo, None, labels_repo, note_labels_repo, openai_client, settings
        )

        await service.run_process()

        details_repo.update_enrichment.assert_awaited_once_with("note-1", "Hello")
        note_labels_repo.replace_llm_labels.assert_awaited_once_with(
            "note-1", [1, 2, 3, 4, 5]
        )

    @pytest.mark.anyio
    async def test_no_pending_notes_skips_openai(self) -> None:
        details_repo = AsyncMock()
        details_repo.get_pending_notes_with_source.return_value = []
        labels_repo = AsyncMock()
        note_labels_repo = AsyncMock()
        openai_client = _StubOpenAI("[]")
        openai_client.chat.completions.create = AsyncMock()
        settings = SimpleNamespace(ENVIRONMENT="dev", MAX_LLM_LABEL_CREATIONS_PER_RUN=20)
        service = NoteEnrichmentService(
            details_repo, None, labels_repo, note_labels_repo, openai_client, settings
        )

        await service.run_process()

        openai_client.chat.completions.create.assert_not_called()

    @pytest.mark.anyio
    async def test_malformed_json_from_openai_is_handled(self) -> None:
        details_repo = AsyncMock()
        details_repo.get_pending_notes_with_source.return_value = [
            {"voice_note_uuid": "note-1", "source_id": "source-1", "raw_text": "hi"}
        ]
        labels_repo = AsyncMock()
        note_labels_repo = AsyncMock()
        labels_repo.list_labels.return_value = []
        openai_client = _StubOpenAI("not-json")
        settings = SimpleNamespace(ENVIRONMENT="dev", MAX_LLM_LABEL_CREATIONS_PER_RUN=20)
        service = NoteEnrichmentService(
            details_repo, None, labels_repo, note_labels_repo, openai_client, settings
        )

        await service.run_process()

        details_repo.update_enrichment.assert_not_called()
        note_labels_repo.replace_llm_labels.assert_not_called()

    @pytest.mark.anyio
    async def test_new_label_is_created_and_attached(self) -> None:
        details_repo = AsyncMock()
        details_repo.get_pending_notes_with_source.return_value = [
            {"voice_note_uuid": "note-1", "source_id": "source-1", "raw_text": "vegan cake"}
        ]
        labels_repo = AsyncMock()
        note_labels_repo = AsyncMock()
        labels_repo.list_labels.return_value = [{"id": 1, "label": "cake"}]
        labels_repo.create_label.return_value = {"id": 2, "label": "vegan"}
        openai_client = _StubOpenAI(
            json.dumps(
                [
                    {
                        "voice_note_uuid": "note-1",
                        "title": "Vegan cake recipe",
                        "label_ids": [1],
                        "new_labels": ["vegan"],
                    }
                ]
            )
        )
        settings = SimpleNamespace(ENVIRONMENT="dev", MAX_LLM_LABEL_CREATIONS_PER_RUN=20)
        service = NoteEnrichmentService(
            details_repo, None, labels_repo, note_labels_repo, openai_client, settings
        )

        await service.run_process()

        labels_repo.create_label.assert_awaited_once_with("vegan", created_by="llm")
        note_labels_repo.replace_llm_labels.assert_awaited_once_with("note-1", [1, 2])

    @pytest.mark.anyio
    async def test_new_label_matching_existing_is_reused_not_created(self) -> None:
        details_repo = AsyncMock()
        details_repo.get_pending_notes_with_source.return_value = [
            {"voice_note_uuid": "note-1", "source_id": "source-1", "raw_text": "future plans"}
        ]
        labels_repo = AsyncMock()
        note_labels_repo = AsyncMock()
        labels_repo.list_labels.return_value = [{"id": 3, "label": "future-plans"}]
        openai_client = _StubOpenAI(
            json.dumps(
                [
                    {
                        "voice_note_uuid": "note-1",
                        "title": "Future plans",
                        "label_ids": [],
                        "new_labels": ["future plans"],
                    }
                ]
            )
        )
        settings = SimpleNamespace(ENVIRONMENT="dev", MAX_LLM_LABEL_CREATIONS_PER_RUN=20)
        service = NoteEnrichmentService(
            details_repo, None, labels_repo, note_labels_repo, openai_client, settings
        )

        await service.run_process()

        labels_repo.create_label.assert_not_called()
        note_labels_repo.replace_llm_labels.assert_awaited_once_with("note-1", [3])

    @pytest.mark.anyio
    async def test_new_label_skipped_when_budget_exhausted(self) -> None:
        details_repo = AsyncMock()
        details_repo.get_pending_notes_with_source.return_value = [
            {"voice_note_uuid": "note-1", "source_id": "source-1", "raw_text": "vegan cake"}
        ]
        labels_repo = AsyncMock()
        note_labels_repo = AsyncMock()
        labels_repo.list_labels.return_value = [{"id": 1, "label": "cake"}]
        openai_client = _StubOpenAI(
            json.dumps(
                [
                    {
                        "voice_note_uuid": "note-1",
                        "title": "Vegan cake recipe",
                        "label_ids": [1],
                        "new_labels": ["vegan"],
                    }
                ]
            )
        )
        settings = SimpleNamespace(ENVIRONMENT="dev", MAX_LLM_LABEL_CREATIONS_PER_RUN=0)
        service = NoteEnrichmentService(
            details_repo, None, labels_repo, note_labels_repo, openai_client, settings
        )

        await service.run_process()

        labels_repo.create_label.assert_not_called()
        note_labels_repo.replace_llm_labels.assert_awaited_once_with("note-1", [1])

    @pytest.mark.anyio
    async def test_invalid_new_label_name_is_skipped(self) -> None:
        details_repo = AsyncMock()
        details_repo.get_pending_notes_with_source.return_value = [
            {"voice_note_uuid": "note-1", "source_id": "source-1", "raw_text": "hi"}
        ]
        labels_repo = AsyncMock()
        note_labels_repo = AsyncMock()
        labels_repo.list_labels.return_value = []
        openai_client = _StubOpenAI(
            json.dumps(
                [
                    {
                        "voice_note_uuid": "note-1",
                        "title": "Hello",
                        "label_ids": [],
                        "new_labels": ["Not! Valid$$"],
                    }
                ]
            )
        )
        settings = SimpleNamespace(ENVIRONMENT="dev", MAX_LLM_LABEL_CREATIONS_PER_RUN=20)
        service = NoteEnrichmentService(
            details_repo, None, labels_repo, note_labels_repo, openai_client, settings
        )

        await service.run_process()

        labels_repo.create_label.assert_not_called()
        note_labels_repo.replace_llm_labels.assert_awaited_once_with("note-1", [])

    @pytest.mark.anyio
    async def test_label_created_in_earlier_batch_is_reused_in_later_batch(self) -> None:
        details_repo = AsyncMock()
        details_repo.get_pending_notes_with_source.return_value = [
            {"voice_note_uuid": "note-1", "source_id": "source-1", "raw_text": "vegan cake"},
            {"voice_note_uuid": "note-2", "source_id": "source-2", "raw_text": "vegan soup"},
        ]
        labels_repo = AsyncMock()
        note_labels_repo = AsyncMock()
        labels_repo.list_labels.return_value = []
        labels_repo.create_label.return_value = {"id": 9, "label": "vegan"}

        async def _create(notes: list, labels: list) -> list:
            note = notes[0]
            return [
                {
                    "voice_note_uuid": note["voice_note_uuid"],
                    "title": "Vegan recipe",
                    "label_ids": [],
                    "new_labels": ["vegan"],
                }
            ]

        openai_client = _StubOpenAI("[]")
        settings = SimpleNamespace(ENVIRONMENT="dev", MAX_LLM_LABEL_CREATIONS_PER_RUN=20)
        service = NoteEnrichmentService(
            details_repo, None, labels_repo, note_labels_repo, openai_client, settings
        )
        service._enrich_batch = AsyncMock(side_effect=_create)

        await service.run_process()

        labels_repo.create_label.assert_awaited_once_with("vegan", created_by="llm")
        note_labels_repo.replace_llm_labels.assert_any_await("note-1", [9])
        note_labels_repo.replace_llm_labels.assert_any_await("note-2", [9])


class TestEnrichSpecificNotes:
    @pytest.mark.anyio
    async def test_enrich_specific_notes_processes_all_notes_in_batches(self) -> None:
        details_repo = AsyncMock()
        details_repo.get_pending_notes_with_source.return_value = [
            {
                "voice_note_uuid": f"note-{index}",
                "source_id": "source-1",
                "raw_text": f"text-{index}",
            }
            for index in range(6)
        ]
        labels_repo = AsyncMock()
        labels_repo.list_labels.return_value = []
        note_labels_repo = AsyncMock()
        service = NoteEnrichmentService(
            details_repo,
            None,
            labels_repo,
            note_labels_repo,
            _StubOpenAI("[]"),
            SimpleNamespace(ENVIRONMENT="dev", MAX_LLM_LABEL_CREATIONS_PER_RUN=20),
        )
        service._enrich_batch = AsyncMock(return_value=[])

        await service.enrich_specific_notes([f"note-{index}" for index in range(6)])

        assert service._enrich_batch.await_count == 2
        assert [len(call.args[0]) for call in service._enrich_batch.await_args_list] == [3, 3]

    @pytest.mark.anyio
    async def test_enrich_specific_notes_enriches_only_given_ids(self) -> None:
        details_repo = AsyncMock()
        details_repo.get_pending_notes_with_source.return_value = [
            {"voice_note_uuid": "note-1", "source_id": "source-1", "raw_text": "hi"},
            {"voice_note_uuid": "note-2", "source_id": "source-1", "raw_text": "hey"},
            {"voice_note_uuid": "note-3", "source_id": "source-1", "raw_text": "hello"},
        ]
        labels_repo = AsyncMock()
        note_labels_repo = AsyncMock()
        labels_repo.list_labels.return_value = []
        openai_client = _StubOpenAI("[]")
        settings = SimpleNamespace(ENVIRONMENT="dev", MAX_LLM_LABEL_CREATIONS_PER_RUN=20)
        service = NoteEnrichmentService(
            details_repo, None, labels_repo, note_labels_repo, openai_client, settings
        )
        service._enrich_batch = AsyncMock(
            return_value=[
                {"voice_note_uuid": "note-1", "title": "Title 1", "label_ids": []},
            ]
        )

        await service.enrich_specific_notes(["note-1"])

        # Only note-1 should be in the batch
        batch_notes = service._enrich_batch.call_args.args[0]
        assert len(batch_notes) == 1
        assert batch_notes[0]["voice_note_uuid"] == "note-1"

    @pytest.mark.anyio
    async def test_enrich_specific_notes_honors_label_cap(self) -> None:
        details_repo = AsyncMock()
        details_repo.get_pending_notes_with_source.return_value = [
            {"voice_note_uuid": "note-1", "source_id": "source-1", "raw_text": "vegan cake"},
        ]
        labels_repo = AsyncMock()
        note_labels_repo = AsyncMock()
        labels_repo.list_labels.return_value = [{"id": 1, "label": "cake"}]
        openai_client = _StubOpenAI(
            json.dumps(
                [
                    {
                        "voice_note_uuid": "note-1",
                        "title": "Vegan cake recipe",
                        "label_ids": [1],
                        "new_labels": ["vegan"],
                    }
                ]
            )
        )
        settings = SimpleNamespace(ENVIRONMENT="dev", MAX_LLM_LABEL_CREATIONS_PER_RUN=0)
        service = NoteEnrichmentService(
            details_repo, None, labels_repo, note_labels_repo, openai_client, settings
        )

        await service.enrich_specific_notes(["note-1"])

        # Label cap is 0, so no new labels should be created
        labels_repo.create_label.assert_not_called()
        note_labels_repo.replace_llm_labels.assert_awaited_once_with("note-1", [1])

    @pytest.mark.anyio
    async def test_enrich_specific_notes_no_matching_notes(self) -> None:
        details_repo = AsyncMock()
        details_repo.get_pending_notes_with_source.return_value = [
            {"voice_note_uuid": "note-1", "source_id": "source-1", "raw_text": "hi"},
        ]
        labels_repo = AsyncMock()
        note_labels_repo = AsyncMock()
        openai_client = _StubOpenAI("[]")
        settings = SimpleNamespace(ENVIRONMENT="dev", MAX_LLM_LABEL_CREATIONS_PER_RUN=20)
        service = NoteEnrichmentService(
            details_repo, None, labels_repo, note_labels_repo, openai_client, settings
        )

        await service.enrich_specific_notes(["nonexistent-note"])

        # No LLM call should be made
        labels_repo.list_labels.assert_not_called()

    @pytest.mark.anyio
    async def test_enrich_specific_notes_empty_ids(self) -> None:
        details_repo = AsyncMock()
        labels_repo = AsyncMock()
        note_labels_repo = AsyncMock()
        openai_client = _StubOpenAI("[]")
        settings = SimpleNamespace(ENVIRONMENT="dev", MAX_LLM_LABEL_CREATIONS_PER_RUN=20)
        service = NoteEnrichmentService(
            details_repo, None, labels_repo, note_labels_repo, openai_client, settings
        )

        await service.enrich_specific_notes([])

        # No DB calls
        details_repo.get_pending_notes_with_source.assert_not_called()


class TestSplitIntoBalancedBatches:
    def test_empty_input(self) -> None:
        assert split_into_balanced_batches([]) == []

    def test_single_note(self) -> None:
        notes = ["n1"]
        result = split_into_balanced_batches(notes)
        assert result == [["n1"]]

    def test_two_notes(self) -> None:
        notes = ["n1", "n2"]
        result = split_into_balanced_batches(notes)
        assert result == [["n1", "n2"]]

    def test_four_notes(self) -> None:
        notes = ["n1", "n2", "n3", "n4"]
        result = split_into_balanced_batches(notes)
        assert result == [["n1", "n2", "n3", "n4"]]

    def test_five_notes(self) -> None:
        notes = ["n1", "n2", "n3", "n4", "n5"]
        result = split_into_balanced_batches(notes)
        assert result == [["n1", "n2", "n3", "n4", "n5"]]

    def test_six_notes_splits_3_3(self) -> None:
        notes = [f"n{i}" for i in range(6)]
        result = split_into_balanced_batches(notes)
        assert [len(b) for b in result] == [3, 3]
        # Order preserved
        flat = [n for b in result for n in b]
        assert flat == notes

    def test_seven_notes_splits_4_3(self) -> None:
        notes = [f"n{i}" for i in range(7)]
        result = split_into_balanced_batches(notes)
        assert [len(b) for b in result] == [4, 3]
        flat = [n for b in result for n in b]
        assert flat == notes

    def test_eight_notes_splits_4_4(self) -> None:
        notes = [f"n{i}" for i in range(8)]
        result = split_into_balanced_batches(notes)
        assert [len(b) for b in result] == [4, 4]

    def test_nine_notes_splits_5_4(self) -> None:
        notes = [f"n{i}" for i in range(9)]
        result = split_into_balanced_batches(notes)
        assert [len(b) for b in result] == [5, 4]

    def test_ten_notes_splits_5_5(self) -> None:
        notes = [f"n{i}" for i in range(10)]
        result = split_into_balanced_batches(notes)
        assert [len(b) for b in result] == [5, 5]

    def test_eleven_notes_splits_4_4_3(self) -> None:
        notes = [f"n{i}" for i in range(11)]
        result = split_into_balanced_batches(notes)
        assert [len(b) for b in result] == [4, 4, 3]

    def test_twelve_notes_splits_4_4_4(self) -> None:
        notes = [f"n{i}" for i in range(12)]
        result = split_into_balanced_batches(notes)
        assert [len(b) for b in result] == [4, 4, 4]

    def test_no_batch_of_one_when_n_gte_2(self) -> None:
        for n in range(2, 25):
            notes = [f"n{i}" for i in range(n)]
            result = split_into_balanced_batches(notes)
            for batch in result:
                assert len(batch) > 1, f"batch of 1 found for N={n}"

    def test_no_batch_exceeds_max(self) -> None:
        for n in range(1, 25):
            notes = [f"n{i}" for i in range(n)]
            result = split_into_balanced_batches(notes)
            for batch in result:
                assert len(batch) <= ENRICHMENT_MAX_BATCH_SIZE

    def test_order_preserved(self) -> None:
        for n in range(1, 25):
            notes = [f"n{i}" for i in range(n)]
            result = split_into_balanced_batches(notes)
            flat = [item for batch in result for item in batch]
            assert flat == notes


class TestEnrichBatchSingleObjectParsing:
    @pytest.mark.anyio
    async def test_enrich_batch_parses_single_object_response(self) -> None:
        """Regression test: top-level single-object JSON response returns 1 result."""
        details_repo = AsyncMock()
        details_repo.get_pending_notes_with_source.return_value = [
            {"voice_note_uuid": "note-1", "source_id": "source-1", "raw_text": "hi"},
        ]
        labels_repo = AsyncMock()
        labels_repo.list_labels.return_value = [{"id": 1, "label": "work"}]
        note_labels_repo = AsyncMock()
        # LLM returns a single object (not a list, not a wrapper dict)
        single_object_response = json.dumps(
            {
                "voice_note_uuid": "note-1",
                "title": "Hello Title",
                "label_ids": [1],
            }
        )
        openai_client = _StubOpenAI(single_object_response)
        settings = SimpleNamespace(ENVIRONMENT="dev", MAX_LLM_LABEL_CREATIONS_PER_RUN=20)
        service = NoteEnrichmentService(
            details_repo, None, labels_repo, note_labels_repo, openai_client, settings
        )

        await service.enrich_specific_notes(["note-1"])

        details_repo.update_enrichment.assert_awaited_once_with("note-1", "Hello Title")
        note_labels_repo.replace_llm_labels.assert_awaited_once_with("note-1", [1])

    @pytest.mark.anyio
    async def test_enrich_batch_still_parses_wrapper_dict(self) -> None:
        """Ensure the existing wrapper-dict heuristic still works (no regression)."""
        details_repo = AsyncMock()
        details_repo.get_pending_notes_with_source.return_value = [
            {"voice_note_uuid": "note-1", "source_id": "source-1", "raw_text": "hi"},
        ]
        labels_repo = AsyncMock()
        labels_repo.list_labels.return_value = [{"id": 1, "label": "work"}]
        note_labels_repo = AsyncMock()
        wrapper_response = json.dumps(
            {
                "notes": [
                    {
                        "voice_note_uuid": "note-1",
                        "title": "Wrapped Title",
                        "label_ids": [1],
                    }
                ]
            }
        )
        openai_client = _StubOpenAI(wrapper_response)
        settings = SimpleNamespace(ENVIRONMENT="dev", MAX_LLM_LABEL_CREATIONS_PER_RUN=20)
        service = NoteEnrichmentService(
            details_repo, None, labels_repo, note_labels_repo, openai_client, settings
        )

        await service.enrich_specific_notes(["note-1"])

        details_repo.update_enrichment.assert_awaited_once_with("note-1", "Wrapped Title")
