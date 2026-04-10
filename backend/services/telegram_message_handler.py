"""Orchestration service for Telegram voice/audio ingestion."""

from loguru import logger

from backend.repositories.repository_errors import DuplicateRecordError
from backend.services.telegram_command_handler import TelegramCommandHandler
from backend.services.telegram_ingestion_service import TelegramIngestionService
from backend.services.transcription_service import TranscriptionService
from backend.services.voice_note_service import VoiceNoteService

AUDIO_TYPES = {"voice", "audio"}


class TelegramMessageHandler:
    def __init__(
        self,
        ingestion_service: TelegramIngestionService,
        voice_note_service: VoiceNoteService,
        transcription_service: TranscriptionService,
        command_handler: TelegramCommandHandler,
    ) -> None:
        self._ingestion_service = ingestion_service
        self._voice_note_service = voice_note_service
        self._transcription_service = transcription_service
        self._command_handler = command_handler

    async def handle(self, update: dict) -> dict:
        event = self._ingestion_service._build_ingestion_event(update)
        message_type = event["message_type"]

        if message_type == "text":
            chat_id = update["message"]["chat"]["id"]
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

        # Transcribe (TranscriptionService is sync)
        raw_text = self._transcription_service.transcribe_telegram_audio(telegram_file_id)

        # Persist with real transcription
        try:
            await self._ingestion_service.ingest_update(update, raw_text=raw_text)
        except DuplicateRecordError:
            return {"outcome": "duplicate", "message_type": message_type}

        return {"outcome": "stored", "message_type": message_type}
