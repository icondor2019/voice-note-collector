from __future__ import annotations

import json

from backend.services.note_enrichment_prompt import render_prompt


def _extract_labels_block(prompt: str) -> str:
    _, _, after_labels = prompt.partition("Available labels:\n")
    labels_block, _, _ = after_labels.partition("\n\nNotes to enrich:")
    return labels_block


def _extract_transcriptions(prompt: str) -> str:
    _, _, after_notes = prompt.partition("Notes to enrich:\n")
    transcriptions_block, _, _ = after_notes.partition("\n\nRespond with a JSON array")
    return transcriptions_block


class TestNoteEnrichmentPrompt:
    def test_render_prompt_replaces_available_labels(self) -> None:
        labels = [
            {"id": 1, "label": "Work"},
            {"id": 2, "label": "Personal"},
        ]
        notes = [{"voice_note_uuid": "note-1", "raw_text": "hello"}]

        prompt = render_prompt(labels, notes)

        assert "{{AVAILABLE_LABELS}}" not in prompt
        labels_block = _extract_labels_block(prompt)
        assert "- 1: Work" in labels_block
        assert "- 2: Personal" in labels_block

    def test_render_prompt_replaces_transcriptions_with_json(self) -> None:
        labels = [{"id": 1, "label": "Work"}]
        notes = [
            {"voice_note_uuid": "note-1", "raw_text": "hello"},
            {"voice_note_uuid": "note-2", "raw_text": "hola"},
        ]

        prompt = render_prompt(labels, notes)

        assert "{{TRANSCRIPTIONS}}" not in prompt
        transcriptions_block = _extract_transcriptions(prompt)
        parsed = json.loads(transcriptions_block)
        assert parsed == [
            {"voice_note_uuid": "note-1", "transcription": "hello"},
            {"voice_note_uuid": "note-2", "transcription": "hola"},
        ]

    def test_render_prompt_with_empty_labels(self) -> None:
        prompt = render_prompt([], [{"voice_note_uuid": "note-1", "raw_text": "hello"}])

        labels_block = _extract_labels_block(prompt)
        assert labels_block == ""

    def test_render_prompt_with_empty_notes(self) -> None:
        prompt = render_prompt([{"id": 1, "label": "Work"}], [])

        transcriptions_block = _extract_transcriptions(prompt)
        parsed = json.loads(transcriptions_block)
        assert parsed == []
