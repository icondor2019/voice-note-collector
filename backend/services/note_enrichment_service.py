from __future__ import annotations

import json
from typing import Any

from loguru import logger

from backend.services import note_enrichment_prompt


class NoteEnrichmentService:
    def __init__(
        self,
        details_repo: Any,
        voice_notes_repo: Any,
        labels_repo: Any,
        openai_client: Any,
        settings: Any,
    ) -> None:
        self._details_repo = details_repo
        self._voice_notes_repo = voice_notes_repo
        self._labels_repo = labels_repo
        self._openai_client = openai_client
        self._settings = settings

    async def run_process(self) -> None:
        source_id_filter = (
            "a0dcea10-ca65-4314-af78-ce096824aff1"
            if self._settings.ENVIRONMENT == "dev"
            else None
        )
        pending_notes = await self._details_repo.get_pending_notes_with_source(source_id_filter)
        if not pending_notes:
            logger.info("note_enrichment.no_pending_notes")
            return

        labels = await self._labels_repo.list_labels()
        logger.info(
            "note_enrichment.pending_notes_loaded",
            extra={"count": len(pending_notes), "label_count": len(labels)},
        )

        grouped: dict[str, list[dict[str, Any]]] = {}
        for note in pending_notes:
            source_id = note.get("source_id")
            if not source_id:
                logger.warning("note_enrichment.missing_source_id", extra={"note": note})
                continue
            grouped.setdefault(source_id, []).append(note)

        for source_id, notes in grouped.items():
            notes_batch = notes[:5]
            logger.info(
                "note_enrichment.batch_start",
                extra={"source_id": source_id, "batch_size": len(notes_batch)},
            )
            results = await self._enrich_batch(notes_batch, labels)
            logger.info(
                "note_enrichment.batch_complete",
                extra={"source_id": source_id, "result_count": len(results)},
            )
            for result in results:
                await self._details_repo.update_enrichment(
                    result["voice_note_uuid"],
                    result["title"],
                    result["label_ids"],
                )

    async def _enrich_batch(self, notes: list[dict], labels: list[dict]) -> list[dict]:
        prompt = note_enrichment_prompt.render_prompt(labels, notes)
        response = self._openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content if response.choices else ""
        if not content:
            logger.error("note_enrichment.empty_response")
            return []

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            logger.error("note_enrichment.parse_failed", extra={"error": str(exc)})
            return []

        items: list[dict[str, Any]] = []
        if isinstance(parsed, list):
            items = parsed
        elif isinstance(parsed, dict):
            for value in parsed.values():
                if isinstance(value, list):
                    items = value
                    break

        if not items:
            logger.warning("note_enrichment.no_items_parsed")
            return []

        valid_ids = {label["id"] for label in labels}
        enriched: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                logger.warning("note_enrichment.invalid_item", extra={"item": item})
                continue
            if not all(key in item for key in ("voice_note_uuid", "title", "label_ids")):
                logger.warning("note_enrichment.missing_keys", extra={"item": item})
                continue
            raw_ids = item.get("label_ids") or []
            label_ids: list[int] = []
            for raw_id in raw_ids:
                try:
                    label_ids.append(int(raw_id))
                except (TypeError, ValueError):
                    logger.warning(
                        "note_enrichment.invalid_label_id",
                        extra={"label_id": raw_id, "item": item},
                    )
            filtered = [label_id for label_id in label_ids if label_id in valid_ids]
            if len(filtered) != len(label_ids):
                logger.warning(
                    "note_enrichment.filtered_label_ids",
                    extra={"item": item, "filtered": filtered},
                )
            filtered = filtered[:5]
            enriched.append(
                {
                    "voice_note_uuid": item["voice_note_uuid"],
                    "title": item["title"],
                    "label_ids": filtered,
                }
            )

        return enriched
