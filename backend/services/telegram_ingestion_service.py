from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from backend.repositories.telegram_ingestion_event_store import FileIngestionEventStore


logger = logging.getLogger(__name__)

SUPPORTED_MESSAGE_TYPES = {"text", "voice", "audio"}


class TelegramIngestionService:
    """Parse Telegram updates and persist ingestion events."""

    def __init__(self, event_store: FileIngestionEventStore) -> None:
        self._event_store = event_store

    def ingest_update(self, update: dict[str, Any]) -> dict[str, Any]:
        ingestion_event = self._build_ingestion_event(update)
        event_context = {
            "update_id": ingestion_event.get("update_id"),
            "chat_id": ingestion_event.get("chat_id"),
            "message_id": ingestion_event.get("message_id"),
            "message_type": ingestion_event.get("message_type"),
        }
        logger.info("telegram.ingestion.received", extra=event_context)

        if ingestion_event["message_type"] not in SUPPORTED_MESSAGE_TYPES:
            logger.info("telegram.ingestion.ignored", extra=event_context)
            return {"outcome": "ignored", "message_type": ingestion_event["message_type"]}

        try:
            write_result = self._event_store.append_event(ingestion_event)
        except OSError:
            # Decision: return 500 to encourage Telegram retry on persistence failure.
            logger.exception("telegram.ingestion.persistence_error", extra=event_context)
            raise

        if not write_result.written:
            return {"outcome": "duplicate", "message_type": ingestion_event["message_type"]}

        return {"outcome": "stored", "message_type": ingestion_event["message_type"]}

    def _build_ingestion_event(self, update: dict[str, Any]) -> dict[str, Any]:
        message: Optional[dict[str, Any]] = update.get("message")
        message_type = "unsupported"
        text_preview: Optional[str] = None
        telegram_file_id: Optional[str] = None
        duration_seconds: Optional[int] = None
        mime_type: Optional[str] = None

        if isinstance(message, dict):
            if isinstance(message.get("text"), str):
                message_type = "text"
                text_preview = message.get("text")
            elif isinstance(message.get("voice"), dict):
                voice = message.get("voice") or {}
                message_type = "voice"
                telegram_file_id = voice.get("file_id")
                duration_seconds = voice.get("duration")
                mime_type = voice.get("mime_type")
            elif isinstance(message.get("audio"), dict):
                audio = message.get("audio") or {}
                message_type = "audio"
                telegram_file_id = audio.get("file_id")
                duration_seconds = audio.get("duration")
                mime_type = audio.get("mime_type")

        received_at = datetime.now(timezone.utc).isoformat()
        update_id = update.get("update_id")
        chat_id = message.get("chat", {}).get("id") if isinstance(message, dict) else None
        from_user_id = message.get("from", {}).get("id") if isinstance(message, dict) else None
        message_id = message.get("message_id") if isinstance(message, dict) else None
        message_date = message.get("date") if isinstance(message, dict) else None

        if isinstance(text_preview, str):
            text_preview = text_preview.strip()[:200]

        idempotency_key = self._build_idempotency_key(chat_id, message_id, update_id)

        return {
            "received_at": received_at,
            "request_id": None,
            "update_id": update_id,
            "chat_id": chat_id,
            "from_user_id": from_user_id,
            "message_id": message_id,
            "message_date": message_date,
            "message_type": message_type,
            "text_preview": text_preview,
            "telegram_file_id": telegram_file_id,
            "duration_seconds": duration_seconds,
            "mime_type": mime_type,
            "raw_update_body": update,
            "idempotency_key": idempotency_key,
        }

    @staticmethod
    def _build_idempotency_key(
        chat_id: Optional[int], message_id: Optional[int], update_id: Optional[int]
    ) -> str:
        if chat_id is not None and message_id is not None:
            return f"{chat_id}:{message_id}"
        if update_id is not None:
            return str(update_id)
        return "unknown"
