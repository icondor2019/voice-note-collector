from __future__ import annotations

import json
import math
from typing import Any, Optional

from loguru import logger

from backend.repositories.repository_errors import RepositoryError
from backend.services import label_utils, note_enrichment_prompt


ENRICHMENT_MAX_BATCH_SIZE = 5


def split_into_balanced_batches(
    notes: list[Any], max_batch_size: int = ENRICHMENT_MAX_BATCH_SIZE
) -> list[list[Any]]:
    """Split notes into k = ceil(N/max_batch_size) batches whose sizes differ by at most 1.

    Order is preserved. Empty input returns [].
    """
    if not notes:
        return []
    n = len(notes)
    k = math.ceil(n / max_batch_size)
    # r batches of size (q + 1), then (k - r) batches of size q — sizes differ by at most 1
    q, r = divmod(n, k)
    batches: list[list[Any]] = []
    idx = 0
    for i in range(k):
        size = q + 1 if i < r else q
        batches.append(notes[idx : idx + size])
        idx += size
    return batches


class NoteEnrichmentService:
    def __init__(
        self,
        details_repo: Any,
        voice_notes_repo: Any,
        labels_repo: Any,
        note_labels_repo: Any,
        openai_client: Any,
        settings: Any,
    ) -> None:
        self._details_repo = details_repo
        self._voice_notes_repo = voice_notes_repo
        self._labels_repo = labels_repo
        self._note_labels_repo = note_labels_repo
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

        labels_by_dedup_key = {label_utils.dedup_key(label["label"]): label for label in labels}
        remaining_budget = self._settings.MAX_LLM_LABEL_CREATIONS_PER_RUN

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
                label_ids = list(result["label_ids"])
                for raw_name in result.get("new_labels", []):
                    resolved_id, remaining_budget = await self._resolve_new_label(
                        raw_name, labels, labels_by_dedup_key, remaining_budget
                    )
                    if resolved_id is not None and resolved_id not in label_ids:
                        label_ids.append(resolved_id)

                await self._details_repo.update_enrichment(
                    result["voice_note_uuid"],
                    result["title"],
                )
                await self._note_labels_repo.replace_llm_labels(
                    result["voice_note_uuid"],
                    label_ids,
                )

    async def enrich_specific_notes(self, note_ids: list[str]) -> None:
        """Enrich only the given note IDs.

        Same prompt, same JSON parsing, same MAX_LLM_LABEL_CREATIONS_PER_RUN cap
        as run_process(). Used by SessionBuilderService.build() before synthesis.
        """
        if not note_ids:
            return

        # Fetch all pending notes with source, then filter to the requested IDs
        all_pending = await self._details_repo.get_pending_notes_with_source()
        pending_notes = [
            note
            for note in all_pending
            if note.get("voice_note_uuid") in note_ids
        ]
        if not pending_notes:
            logger.info("note_enrichment.enrich_specific.no_matching_notes")
            return

        labels = await self._labels_repo.list_labels()
        logger.info(
            "note_enrichment.enrich_specific.start",
            extra={"count": len(pending_notes), "label_count": len(labels)},
        )

        labels_by_dedup_key = {label_utils.dedup_key(label["label"]): label for label in labels}
        remaining_budget = self._settings.MAX_LLM_LABEL_CREATIONS_PER_RUN

        grouped: dict[str, list[dict[str, Any]]] = {}
        for note in pending_notes:
            source_id = note.get("source_id")
            if not source_id:
                logger.warning("note_enrichment.enrich_specific.missing_source_id", extra={"note": note})
                continue
            grouped.setdefault(source_id, []).append(note)

        for source_id, notes in grouped.items():
            for notes_batch in split_into_balanced_batches(notes):
                logger.info(
                    "note_enrichment.enrich_specific.batch_start",
                    extra={"source_id": source_id, "batch_size": len(notes_batch)},
                )
                results = await self._enrich_batch(notes_batch, labels)
                logger.info(
                    "note_enrichment.enrich_specific.batch_complete",
                    extra={"source_id": source_id, "result_count": len(results)},
                )
                for result in results:
                    label_ids = list(result["label_ids"])
                    for raw_name in result.get("new_labels", []):
                        resolved_id, remaining_budget = await self._resolve_new_label(
                            raw_name, labels, labels_by_dedup_key, remaining_budget
                        )
                        if resolved_id is not None and resolved_id not in label_ids:
                            label_ids.append(resolved_id)

                    await self._details_repo.update_enrichment(
                        result["voice_note_uuid"],
                        result["title"],
                    )
                    await self._note_labels_repo.replace_llm_labels(
                        result["voice_note_uuid"],
                        label_ids,
                    )

    async def _resolve_new_label(
        self,
        raw_name: str,
        labels: list[dict[str, Any]],
        labels_by_dedup_key: dict[str, dict[str, Any]],
        remaining_budget: int,
    ) -> tuple[Optional[int], int]:
        name = label_utils.validate_label_name(raw_name)
        if not name:
            logger.warning("note_enrichment.invalid_new_label", extra={"name": raw_name})
            return None, remaining_budget

        key = label_utils.dedup_key(name)
        existing = labels_by_dedup_key.get(key)
        if existing:
            return existing["id"], remaining_budget

        if remaining_budget <= 0:
            logger.warning("note_enrichment.label_cap_reached", extra={"name": name})
            return None, remaining_budget

        try:
            created = await self._labels_repo.create_label(name, created_by="llm")
        except RepositoryError as exc:
            if "unique" not in str(exc).lower():
                raise
            created = await self._labels_repo.get_label_by_name(name)
            if not created:
                logger.warning("note_enrichment.new_label_race_unresolved", extra={"name": name})
                return None, remaining_budget

        labels_by_dedup_key[key] = created
        labels.append(created)
        logger.info(
            "note_enrichment.new_label_created",
            extra={"name": name, "label_id": created["id"]},
        )
        return created["id"], remaining_budget - 1

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
            if all(
                key in parsed for key in ("voice_note_uuid", "title", "label_ids")
            ):
                items = [parsed]
            else:
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

            raw_new_labels = item.get("new_labels") or []
            new_labels: list[str] = []
            if isinstance(raw_new_labels, list):
                new_labels = [
                    raw_name
                    for raw_name in raw_new_labels
                    if isinstance(raw_name, str) and raw_name.strip()
                ][:2]

            enriched.append(
                {
                    "voice_note_uuid": item["voice_note_uuid"],
                    "title": item["title"],
                    "label_ids": filtered,
                    "new_labels": new_labels,
                }
            )

        return enriched
