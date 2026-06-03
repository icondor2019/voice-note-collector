"""Orchestration service for Telegram voice/audio ingestion."""

from loguru import logger

from backend.repositories.repository_errors import DuplicateRecordError
from backend.services.chat_mode_service import ChatModeService
from backend.services.multi_agent_service import MultiAgentService
from backend.services.reflection_service import ReflectionService
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
        chat_mode_service: ChatModeService,
        multi_agent_service: MultiAgentService,
        reflection_service: ReflectionService,
    ) -> None:
        self._ingestion_service = ingestion_service
        self._voice_note_service = voice_note_service
        self._transcription_service = transcription_service
        self._command_handler = command_handler
        self._bot_client = bot_client
        self._chat_mode_service = chat_mode_service
        self._multi_agent_service = multi_agent_service
        self._reflection_service = reflection_service

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
        from_user_id = event.get("from_user_id")
        if from_user_id != settings.TELEGRAM_ALLOWED_USER_ID:
            return {"outcome": "ignored", "reason": "unauthorized"}
        message_type = event["message_type"]
        chat_id = event.get("chat_id")

        # ── Text messages ────────────────────────────────────────────
        if message_type == "text":
            text = update["message"]["text"]

            if text.strip().startswith("/"):
                # Slash-cancels-reflect rule
                if self._chat_mode_service.get_mode() == "reflect":
                    try:
                        await self._reflection_service.cancel_pending_reflection(
                            from_user_id
                        )
                    except Exception as exc:
                        logger.warning(
                            "multi_agent.cancel_failed",
                            extra={"error": str(exc), "user_id": from_user_id},
                        )
                    self._chat_mode_service.set_mode("agent")
                await self._command_handler.handle_text(text, chat_id, from_user_id)
                return {"outcome": "command", "message_type": "text"}

            # Route to MultiAgentService for agent/reflect modes
            if self._chat_mode_service.get_mode() in ("agent", "reflect"):
                return await self._route_to_multi_agent(
                    text, from_user_id, chat_id, "text"
                )

            # Non-slash text in note mode → ignored
            return {"outcome": "ignored", "message_type": "text"}

        # ── Audio messages ───────────────────────────────────────────
        if message_type in AUDIO_TYPES:
            telegram_file_id = event.get("telegram_file_id")
            if not telegram_file_id:
                logger.warning(
                    "Voice message ignored — missing telegram_file_id: message_id={}",
                    event.get("message_id"),
                )
                return {"outcome": "ignored", "message_type": message_type}

            # Transcribe
            try:
                raw_text = self._transcription_service.transcribe_telegram_audio(
                    telegram_file_id
                )
            except Exception as exc:
                logger.error(
                    "telegram.transcription_failed",
                    extra={"error": str(exc), "user_id": from_user_id},
                )
                await self._notify(
                    chat_id, "❌ Failed to process your voice note. Please try again."
                )
                raise

            # Route to MultiAgentService for agent/reflect modes
            if self._chat_mode_service.get_mode() in ("agent", "reflect"):
                return await self._route_to_multi_agent(
                    raw_text, from_user_id, chat_id, message_type
                )

            # Note mode: save-as-note path
            message_id = event["message_id"]
            # Idempotency check BEFORE any expensive I/O
            existing = await self._voice_note_service._repository.get_voice_note_by_message_id(
                message_id
            )
            if existing:
                return {"outcome": "duplicate", "message_type": message_type}

            try:
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
            source_name = ingest_result.get("source_name")
            preview = raw_text[:100]
            preview_suffix = "..." if len(raw_text) > 100 else ""
            if source_name:
                success_message = (
                    f"✅ Note saved!\n📂 Source: {source_name}\n📝 {preview}{preview_suffix}"
                )
            else:
                success_message = f"✅ Note saved!\n📝 {preview}{preview_suffix}"
            await self._notify(chat_id, success_message)

            return {"outcome": "stored", "message_type": message_type}

        # ── Unsupported message types ────────────────────────────────
        return {"outcome": "ignored", "message_type": message_type}

    # ------------------------------------------------------------------ #
    #  Helpers
    # ------------------------------------------------------------------ #

    async def _route_to_multi_agent(
        self,
        user_message: str,
        from_user_id: int | None,
        chat_id: int | None,
        message_type: str,
    ) -> dict:
        """Route a text or transcribed message through MultiAgentService."""
        if from_user_id is None:
            return {"outcome": "ignored", "reason": "no_user_id"}

        result = await self._multi_agent_service.handle(
            user_message, telegram_user_id=from_user_id
        )

        if chat_id and result.reply:
            await self._bot_client.send_message(chat_id, result.reply)

        outcome = result.outcome if result.outcome else "agent_response"
        return {"outcome": outcome, "message_type": message_type}
