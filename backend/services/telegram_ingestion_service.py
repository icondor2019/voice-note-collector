from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from loguru import logger

from backend.repositories.repository_errors import DuplicateRecordError
from backend.services.voice_note_service import VoiceNoteService

SUPPORTED_MESSAGE_TYPES = {"text", "voice", "audio"}


class TelegramIngestionService:
    """Parse Telegram updates and persist voice notes."""

    def __init__(self, voice_note_service: VoiceNoteService) -> None:
        self._voice_note_service = voice_note_service

    async def ingest_update(
        self, update: dict[str, Any], raw_text: str = ""
    ) -> dict[str, Any]:
        ingestion_event = self._build_ingestion_event(update)

        if ingestion_event["message_type"] not in SUPPORTED_MESSAGE_TYPES:
            return {"outcome": "ignored", "message_type": ingestion_event["message_type"]}

        if ingestion_event["message_type"] == "text":
            return {"outcome": "ignored", "message_type": "text"}

        if not ingestion_event.get("telegram_file_id"):
            logger.warning(
                "Voice message ignored — missing telegram_file_id: message_id={}",
                ingestion_event.get("message_id"),
            )
            return {"outcome": "ignored", "message_type": ingestion_event["message_type"]}

        try:
            await self._voice_note_service.create_voice_note_idempotent(
                message_id=ingestion_event["message_id"],
                audio_file_id=ingestion_event["telegram_file_id"],
                duration_seconds=ingestion_event.get("duration_seconds"),
                raw_text=raw_text,
                clean_text=None,
            )
        except DuplicateRecordError:
            return {"outcome": "duplicate", "message_type": ingestion_event["message_type"]}

        return {"outcome": "stored", "message_type": ingestion_event["message_type"]}

    def _build_ingestion_event(self, update: dict[str, Any]) -> dict[str, Any]:
        message: Optional[dict[str, Any]] = update.get("message")
        message_type = "unsupported"
        text_preview: Optional[str] = None
        telegram_file_id: Optional[str] = None
        duration_seconds: Optional[int] = None
        mime_type: Optional[str] = None

        if "message" in update:
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
            raw_update_body = update
            idempotency_key = self._build_idempotency_key(chat_id, message_id, update_id)
        else:
            received_at = update.get("received_at") or datetime.now(timezone.utc).isoformat()
            update_id = update.get("update_id")
            chat_id = update.get("chat_id")
            from_user_id = update.get("from_user_id")
            message_id = update.get("message_id")
            message_date = update.get("message_date")
            message_type = update.get("message_type", "unsupported")
            text_preview = update.get("text_preview")
            telegram_file_id = update.get("telegram_file_id")
            duration_seconds = update.get("duration_seconds")
            mime_type = update.get("mime_type")
            raw_update_body = update.get("raw_update_body", update)
            idempotency_key = update.get("idempotency_key") or self._build_idempotency_key(
                chat_id, message_id, update_id
            )

        if isinstance(text_preview, str):
            text_preview = text_preview.strip()[:200]

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
            "raw_update_body": raw_update_body,
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
