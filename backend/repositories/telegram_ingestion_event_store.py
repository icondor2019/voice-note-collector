from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IngestionWriteResult:
    event_id: str
    written: bool


class FileIngestionEventStore:
    """Simple JSONL-backed store for Telegram ingestion events."""

    def __init__(self, file_path: Path | str = "./data/telegram_ingestion_events.jsonl") -> None:
        self._file_path = Path(file_path)

    @property
    def file_path(self) -> Path:
        return self._file_path

    def append_event(self, event: dict[str, Any]) -> IngestionWriteResult:
        event_id = str(event.get("idempotency_key", ""))
        if not event_id:
            raise ValueError("Event missing idempotency_key")

        if self._is_duplicate(event_id):
            logger.info("telegram.ingestion.duplicate", extra={"idempotency_key": event_id})
            return IngestionWriteResult(event_id=event_id, written=False)

        try:
            self._file_path.parent.mkdir(parents=True, exist_ok=True)
            with self._file_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, ensure_ascii=False))
                handle.write("\n")
        except OSError as exc:
            logger.exception("telegram.ingestion.persistence_failed", extra={"idempotency_key": event_id})
            raise exc

        return IngestionWriteResult(event_id=event_id, written=True)

    def _is_duplicate(self, event_id: str) -> bool:
        if not self._file_path.exists():
            return False

        try:
            with self._file_path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    try:
                        payload = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if str(payload.get("idempotency_key")) == event_id:
                        return True
        except OSError as exc:
            logger.exception("telegram.ingestion.persistence_read_failed", extra={"idempotency_key": event_id})
            return False

        return False
