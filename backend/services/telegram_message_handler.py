"""Orchestration service for Telegram voice/audio ingestion."""

from loguru import logger

from backend.repositories.repository_errors import DuplicateRecordError
from backend.services.telegram_bot_client import TelegramBotClient
from backend.services.telegram_command_handler import TelegramCommandHandler
from backend.services.telegram_ingestion_service import TelegramIngestionService
from backend.services.transcription_service import TranscriptionService
from backend.services.voice_note_service import VoiceNoteService
from configuration.settings import settings

AUDIO_TYPES = {"voice", "audio"}


class TelegramMessageHandler:
    def __init__(
        self,
        ingestion_service: TelegramIngestionService,
        voice_note_service: VoiceNoteService,
        transcription_service: TranscriptionService,
        command_handler: TelegramCommandHandler,
        bot_client: TelegramBotClient,
    ) -> None:
        self._ingestion_service = ingestion_service
        self._voice_note_service = voice_note_service
        self._transcription_service = transcription_service
        self._command_handler = command_handler
        self._bot_client = bot_client

    async def _notify(self, chat_id: int | None, text: str) -> None:
        if not settings.TELEGRAM_NOTIFY_ON_TRANSCRIPTION:
            return
        if not chat_id:
            return
        try:
            await self._bot_client.send_message(chat_id, text)
        except Exception as exc:
            logger.error(
                "telegram.notify.failed",
                extra={"chat_id": chat_id, "error": str(exc)},
            )

    async def handle(self, update: dict) -> dict:
        event = self._ingestion_service._build_ingestion_event(update)
        message_type = event["message_type"]
        chat_id = event.get("chat_id")

        if message_type == "text":
            text = update["message"]["text"]
            await self._command_handler.handle_text(text, chat_id)
            return {"outcome": "command", "message_type": "text"}

        if message_type not in AUDIO_TYPES:
            return {"outcome": "ignored", "message_type": message_type}

        message_id = event["message_id"]
        telegram_file_id = event["telegram_file_id"]

        if not telegram_file_id:
            logger.warning(
                "Voice message ignored — missing telegram_file_id: message_id={}",
                message_id,
            )
            return {"outcome": "ignored", "message_type": message_type}

        # Idempotency check BEFORE any expensive I/O
        existing = await self._voice_note_service._repository.get_voice_note_by_message_id(
            message_id
        )
        if existing:
            return {"outcome": "duplicate", "message_type": message_type}

        try:
            # Transcribe (TranscriptionService is sync)
            raw_text = self._transcription_service.transcribe_telegram_audio(telegram_file_id)

            # Persist with real transcription
            ingest_result = await self._ingestion_service.ingest_update(
                update, raw_text=raw_text
            )
        except DuplicateRecordError:
            return {"outcome": "duplicate", "message_type": message_type}
        except Exception:
            await self._notify(
                chat_id, "❌ Failed to process your voice note. Please try again."
            )
            raise

        if ingest_result.get("outcome") == "duplicate":
            return {"outcome": "duplicate", "message_type": message_type}
        if ingest_result.get("outcome") != "stored":
            return ingest_result

        voice_note_id = ingest_result.get("voice_note_id")
        preview = raw_text[:100]
        preview_suffix = "..." if len(raw_text) > 100 else ""
        success_message = f"✅ Note saved!\n📝 {preview}{preview_suffix}"
        await self._notify(chat_id, success_message)

        return {"outcome": "stored", "message_type": message_type}
