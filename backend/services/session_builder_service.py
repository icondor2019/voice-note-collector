from __future__ import annotations

import json
from typing import Any, Optional

from loguru import logger

from backend.repositories.session_documents_repository import SessionDocumentsRepository
from backend.repositories.voice_note_details_repository import VoiceNoteDetailsRepository
from backend.repositories.voice_notes_repository import VoiceNotesRepository
from backend.services.note_enrichment_service import NoteEnrichmentService
from backend.services import session_synthesis_prompt


class NoValidNotesError(Exception):
    """Raised when no valid notes remain after validation."""

    pass


class SessionBuilderService:
    def __init__(
        self,
        session_documents_repository: SessionDocumentsRepository,
        voice_notes_repository: VoiceNotesRepository,
        voice_note_details_repository: VoiceNoteDetailsRepository,
        note_enrichment_service: NoteEnrichmentService,
        openai_client: Any,
        settings: Any,
    ) -> None:
        self._session_docs_repo = session_documents_repository
        self._voice_notes_repo = voice_notes_repository
        self._details_repo = voice_note_details_repository
        self._enrichment_service = note_enrichment_service
        self._openai_client = openai_client
        self._settings = settings

    async def build(self, source_id: str, note_ids: list[str]) -> dict[str, Any]:
        """Build a session document from the given note IDs.

        1. Validate note_ids
        2. Enrich un-enriched notes
        3. Synthesize document via LLM
        4. Attach notes
        5. Return the document row
        """
        # Step 1: Validate
        valid_notes = await self._session_docs_repo.get_valid_note_ids(source_id, note_ids)
        filtered_count = len(note_ids) - len(valid_notes)
        if filtered_count > 0:
            logger.info(
                "session_builder.filtered_notes",
                extra={
                    "requested": len(note_ids),
                    "valid": len(valid_notes),
                    "filtered_out": filtered_count,
                },
            )

        if not valid_notes:
            raise NoValidNotesError("No valid notes remain after validation")

        valid_note_ids = [n["voice_note_uuid"] for n in valid_notes]

        # Step A: Enrich un-enriched notes (status='created')
        un_enriched_ids = [
            n["voice_note_uuid"]
            for n in valid_notes
            if n.get("status") == "created"
        ]
        if un_enriched_ids:
            logger.info(
                "session_builder.enriching_notes",
                extra={"count": len(un_enriched_ids)},
            )
            await self._enrichment_service.enrich_specific_notes(un_enriched_ids)

        # Step B: Synthesize
        # B.1: Create document row
        document = await self._session_docs_repo.create_document(source_id=source_id)
        document_id = document["id"]
        logger.info(
            "session_builder.document_created",
            extra={"document_id": document_id},
        )

        # B.2: Build prompt and call LLM
        prompt = session_synthesis_prompt.render_prompt(valid_notes)
        response = self._openai_client.chat.completions.create(
            model=self._settings.SESSION_SYNTHESIS_MODEL,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            reasoning_effort=self._settings.SESSION_SYNTHESIS_REASONING_EFFORT,
        )
        content = response.choices[0].message.content if response.choices else ""
        if not content:
            logger.error("session_builder.empty_llm_response")
            content = "{}"

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            logger.error("session_builder.parse_failed", extra={"error": str(exc)})
            parsed = {}

        title = parsed.get("title")
        llm_content = parsed.get("content")

        # B.3: Update document with LLM output
        updated = await self._session_docs_repo.update_document(
            document_id,
            title=title,
            content=llm_content,
        )
        if updated:
            document.update(updated)

        # B.4: Attach notes to document
        await self._session_docs_repo.attach_notes_to_document(document_id, valid_note_ids)
        logger.info(
            "session_builder.notes_attached",
            extra={"document_id": document_id, "note_count": len(valid_note_ids)},
        )

        # Re-fetch the document to return the latest state
        final_doc = await self._session_docs_repo.get_document(document_id)
        return final_doc or document

    async def preview(self, source_id: str, note_ids: list[str]) -> dict[str, Any]:
        """Read-only preview of pending notes. No DB writes."""
        valid_notes = await self._session_docs_repo.get_valid_note_ids(source_id, note_ids)

        un_enriched_count = sum(
            1 for n in valid_notes if n.get("status") == "created"
        )

        # Compute time range
        time_range: Optional[str] = None
        if valid_notes:
            dates = [n.get("created_at") for n in valid_notes if n.get("created_at")]
            if dates:
                oldest = min(dates)
                newest = max(dates)
                time_range = f"{oldest} → {newest}"

        # Build notes preview list
        notes_preview: list[dict[str, Any]] = []
        for note in valid_notes:
            title_or_preview = note.get("title")
            if not title_or_preview:
                raw_text = note.get("raw_text", "") or ""
                title_or_preview = raw_text[:100]
            notes_preview.append(
                {
                    "voice_note_uuid": note["voice_note_uuid"],
                    "title": title_or_preview,
                    "status": note.get("status", "created"),
                    "created_at": note.get("created_at"),
                }
            )

        return {
            "pending_count": len(valid_notes),
            "un_enriched_count": un_enriched_count,
            "time_range": time_range,
            "notes": notes_preview,
        }
