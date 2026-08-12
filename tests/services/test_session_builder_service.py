from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.services.session_builder_service import (
    NoValidNotesError,
    SessionBuilderService,
)


def _make_llm_response(content: str) -> Any:
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
        return _make_llm_response(self._content)


def _make_service(
    valid_notes: list[dict] | None = None,
    llm_content: str | None = None,
) -> tuple[SessionBuilderService, AsyncMock, AsyncMock, AsyncMock, AsyncMock]:
    """Create a SessionBuilderService with mocked dependencies."""
    session_docs_repo = AsyncMock()
    voice_notes_repo = AsyncMock()
    details_repo = AsyncMock()
    enrichment_service = AsyncMock()

    if valid_notes is None:
        valid_notes = []

    session_docs_repo.get_valid_note_ids = AsyncMock(return_value=valid_notes)
    session_docs_repo.create_document = AsyncMock(
        return_value={
            "id": "new-doc-id",
            "source_id": "source-1",
            "status": "ready",
            "title": None,
            "content": None,
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
        }
    )
    session_docs_repo.update_document = AsyncMock(return_value=None)
    session_docs_repo.attach_notes_to_document = AsyncMock()
    session_docs_repo.get_document = AsyncMock(
        return_value={
            "id": "new-doc-id",
            "source_id": "source-1",
            "status": "ready",
            "title": "Test Title",
            "content": "# Test Title\n\n## Summary\nTest Summary\n\n## Key Ideas\n- idea 1\n- idea 2\n- idea 3\n\n## Open Questions\n_(To be explored during Socratic review.)_\n\n## Knowledge Gaps\n_(To be identified during reflection.)_\n\n## Reflections\n_(To be added during review.)_\n\n## Mind Changes\n_(To be recorded when understanding shifts.)_",
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
        }
    )

    if llm_content is None:
        llm_content = json.dumps(
            {
                "title": "Test Title",
                "content": "# Test Title\n\n## Summary\nTest Summary\n\n## Key Ideas\n- idea 1\n- idea 2\n- idea 3\n\n## Open Questions\n_(To be explored during Socratic review.)_\n\n## Knowledge Gaps\n_(To be identified during reflection.)_\n\n## Reflections\n_(To be added during review.)_\n\n## Mind Changes\n_(To be recorded when understanding shifts.)_",
            }
        )

    openai_client = _StubOpenAI(llm_content)
    settings = SimpleNamespace(
        ENVIRONMENT="dev",
        MAX_LLM_LABEL_CREATIONS_PER_RUN=20,
        SESSION_SYNTHESIS_MODEL="gpt-5.6-luna",
        SESSION_SYNTHESIS_REASONING_EFFORT="medium",
    )

    service = SessionBuilderService(
        session_documents_repository=session_docs_repo,
        voice_notes_repository=voice_notes_repo,
        voice_note_details_repository=details_repo,
        note_enrichment_service=enrichment_service,
        openai_client=openai_client,
        settings=settings,
    )

    return service, session_docs_repo, enrichment_service, voice_notes_repo, details_repo


class TestSessionBuilderServiceBuild:
    @pytest.mark.anyio
    async def test_build_enriches_un_enriched_notes(self) -> None:
        valid_notes = [
            {
                "voice_note_uuid": "note-1",
                "status": "created",
                "raw_text": "hello",
                "source_id": "source-1",
                "created_at": "2026-01-01T00:00:00Z",
            },
        ]
        service, session_docs_repo, enrichment_service, _, _ = _make_service(
            valid_notes=valid_notes
        )

        await service.build("source-1", ["note-1"])

        enrichment_service.enrich_specific_notes.assert_awaited_once_with(["note-1"])

    @pytest.mark.anyio
    async def test_build_skips_already_enriched_notes(self) -> None:
        valid_notes = [
            {
                "voice_note_uuid": "note-1",
                "status": "enriched",
                "raw_text": "hello",
                "source_id": "source-1",
                "created_at": "2026-01-01T00:00:00Z",
            },
            {
                "voice_note_uuid": "note-2",
                "status": "created",
                "raw_text": "world",
                "source_id": "source-1",
                "created_at": "2026-01-01T00:00:00Z",
            },
        ]
        service, _, enrichment_service, _, _ = _make_service(valid_notes=valid_notes)

        await service.build("source-1", ["note-1", "note-2"])

        # Only note-2 should be enriched (status='created')
        enrichment_service.enrich_specific_notes.assert_awaited_once_with(["note-2"])

    @pytest.mark.anyio
    async def test_build_synthesizes_document(self) -> None:
        valid_notes = [
            {
                "voice_note_uuid": "note-1",
                "status": "enriched",
                "raw_text": "hello world",
                "source_id": "source-1",
                "created_at": "2026-01-01T00:00:00Z",
            },
        ]
        service, session_docs_repo, _, _, _ = _make_service(valid_notes=valid_notes)

        result = await service.build("source-1", ["note-1"])

        # Document was created
        session_docs_repo.create_document.assert_awaited_once_with(source_id="source-1")
        # Document was updated with LLM output
        session_docs_repo.update_document.assert_awaited_once()
        call_kwargs = session_docs_repo.update_document.call_args.kwargs
        assert call_kwargs["title"] == "Test Title"
        assert "## Summary" in call_kwargs["content"]
        assert "## Key Ideas" in call_kwargs["content"]

    @pytest.mark.anyio
    async def test_build_attaches_notes_to_document(self) -> None:
        valid_notes = [
            {
                "voice_note_uuid": "note-1",
                "status": "enriched",
                "raw_text": "hello",
                "source_id": "source-1",
                "created_at": "2026-01-01T00:00:00Z",
            },
            {
                "voice_note_uuid": "note-2",
                "status": "enriched",
                "raw_text": "world",
                "source_id": "source-1",
                "created_at": "2026-01-01T00:00:00Z",
            },
        ]
        service, session_docs_repo, _, _, _ = _make_service(valid_notes=valid_notes)

        await service.build("source-1", ["note-1", "note-2"])

        session_docs_repo.attach_notes_to_document.assert_awaited_once_with(
            "new-doc-id", ["note-1", "note-2"]
        )

    @pytest.mark.anyio
    async def test_build_excludes_already_grouped_notes(self) -> None:
        """get_valid_note_ids already filters; build uses its result."""
        valid_notes = [
            {
                "voice_note_uuid": "note-1",
                "status": "enriched",
                "raw_text": "hello",
                "source_id": "source-1",
                "created_at": "2026-01-01T00:00:00Z",
            },
        ]
        service, session_docs_repo, _, _, _ = _make_service(valid_notes=valid_notes)

        await service.build("source-1", ["note-1", "note-2"])

        # get_valid_note_ids was called with both IDs
        session_docs_repo.get_valid_note_ids.assert_awaited_once_with(
            "source-1", ["note-1", "note-2"]
        )
        # But only note-1 was attached (the valid one)
        session_docs_repo.attach_notes_to_document.assert_awaited_once_with(
            "new-doc-id", ["note-1"]
        )

    @pytest.mark.anyio
    async def test_build_raises_on_zero_valid_notes(self) -> None:
        service, _, _, _, _ = _make_service(valid_notes=[])

        with pytest.raises(NoValidNotesError):
            await service.build("source-1", ["note-1"])

    @pytest.mark.anyio
    async def test_build_returns_document(self) -> None:
        valid_notes = [
            {
                "voice_note_uuid": "note-1",
                "status": "enriched",
                "raw_text": "hello",
                "source_id": "source-1",
                "created_at": "2026-01-01T00:00:00Z",
            },
        ]
        service, _, _, _, _ = _make_service(valid_notes=valid_notes)

        result = await service.build("source-1", ["note-1"])

        assert result["id"] == "new-doc-id"
        assert result["title"] == "Test Title"
        assert result["content"] is not None
        assert "## Summary" in result["content"]


class TestSessionBuilderServicePreview:
    @pytest.mark.anyio
    async def test_preview_returns_count_and_range(self) -> None:
        valid_notes = [
            {
                "voice_note_uuid": "note-1",
                "status": "created",
                "raw_text": "hello world",
                "source_id": "source-1",
                "created_at": "2026-01-01T00:00:00Z",
            },
            {
                "voice_note_uuid": "note-2",
                "status": "enriched",
                "title": "Note 2",
                "raw_text": "foo bar",
                "source_id": "source-1",
                "created_at": "2026-01-02T00:00:00Z",
            },
        ]
        service, _, _, _, _ = _make_service(valid_notes=valid_notes)

        result = await service.preview("source-1", ["note-1", "note-2"])

        assert result["pending_count"] == 2
        assert result["un_enriched_count"] == 1
        assert result["time_range"] is not None
        assert "2026-01-01" in result["time_range"]
        assert "2026-01-02" in result["time_range"]
        assert len(result["notes"]) == 2

    @pytest.mark.anyio
    async def test_preview_does_not_write(self) -> None:
        valid_notes = [
            {
                "voice_note_uuid": "note-1",
                "status": "created",
                "raw_text": "hello",
                "source_id": "source-1",
                "created_at": "2026-01-01T00:00:00Z",
            },
        ]
        service, session_docs_repo, enrichment_service, _, _ = _make_service(
            valid_notes=valid_notes
        )

        await service.preview("source-1", ["note-1"])

        # No writes
        session_docs_repo.create_document.assert_not_awaited()
        session_docs_repo.update_document.assert_not_awaited()
        session_docs_repo.attach_notes_to_document.assert_not_awaited()
        enrichment_service.enrich_specific_notes.assert_not_awaited()

    @pytest.mark.anyio
    async def test_preview_note_title_falls_back_to_raw_text(self) -> None:
        valid_notes = [
            {
                "voice_note_uuid": "note-1",
                "status": "created",
                "raw_text": "A" * 200,
                "source_id": "source-1",
                "created_at": "2026-01-01T00:00:00Z",
            },
        ]
        service, _, _, _, _ = _make_service(valid_notes=valid_notes)

        result = await service.preview("source-1", ["note-1"])

        # Title should be first 100 chars of raw_text
        assert len(result["notes"][0]["title"]) == 100

    @pytest.mark.anyio
    async def test_preview_empty_notes(self) -> None:
        service, _, _, _, _ = _make_service(valid_notes=[])

        result = await service.preview("source-1", [])

        assert result["pending_count"] == 0
        assert result["un_enriched_count"] == 0
        assert result["time_range"] is None
        assert result["notes"] == []
