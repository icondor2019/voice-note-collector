from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from langchain_openai import ChatOpenAI
from loguru import logger

from backend.repositories.chat_memory_repository import ChatMemoryRepository
from backend.repositories.labels_repository import LabelsRepository
from backend.repositories.reflection_repository import ReflectionRepository
from backend.repositories.repository_errors import RepositoryError
from backend.utils.security import verify_telegram_secret
from backend.repositories.sources_repository import SourcesRepository
from backend.repositories.supabase_client import get_supabase_client
from backend.repositories.voice_note_details_repository import VoiceNoteDetailsRepository
from backend.repositories.voice_notes_repository import VoiceNotesRepository
from backend.services.chat_mode_service import ChatModeService
from backend.services.chat_agent_service import ChatAgentService
from backend.services.reflection_service import ReflectionService
from backend.services.source_service import SourceService
from backend.services.telegram_bot_client import TelegramBotClient
from backend.services.telegram_command_handler import TelegramCommandHandler
from backend.services.telegram_ingestion_service import TelegramIngestionService
from backend.services.telegram_message_handler import TelegramMessageHandler
from backend.services.transcription_service import TranscriptionError, TranscriptionService
from backend.services.telegram_audio_downloader import TelegramDownloadError
from backend.services.voice_note_service import VoiceNoteService
from configuration.settings import settings

router = APIRouter(prefix="/api/telegram", tags=["Telegram"])

_chat_mode_service = ChatModeService()


async def get_supabase() -> Any:
    return await get_supabase_client()


def get_voice_notes_repository(
    client: Any = Depends(get_supabase),
) -> VoiceNotesRepository:
    return VoiceNotesRepository(client=client)


def get_voice_note_details_repository(
    client: Any = Depends(get_supabase),
) -> VoiceNoteDetailsRepository:
    return VoiceNoteDetailsRepository(client=client)


def get_sources_repository(
    client: Any = Depends(get_supabase),
) -> SourcesRepository:
    return SourcesRepository(client=client)


def get_labels_repository(
    client: Any = Depends(get_supabase),
) -> LabelsRepository:
    return LabelsRepository(client=client)


def get_source_service(
    sources_repository: SourcesRepository = Depends(get_sources_repository),
) -> SourceService:
    return SourceService(repository=sources_repository)


def get_voice_note_service(
    voice_notes_repository: VoiceNotesRepository = Depends(get_voice_notes_repository),
    source_service: SourceService = Depends(get_source_service),
    details_repository: VoiceNoteDetailsRepository = Depends(
        get_voice_note_details_repository
    ),
) -> VoiceNoteService:
    return VoiceNoteService(
        repository=voice_notes_repository,
        source_service=source_service,
        details_repository=details_repository,
    )


def get_ingestion_service(
    voice_note_service: VoiceNoteService = Depends(get_voice_note_service),
) -> TelegramIngestionService:
    return TelegramIngestionService(voice_note_service)


def get_transcription_service() -> TranscriptionService:
    return TranscriptionService()


def get_telegram_bot_client() -> TelegramBotClient:
    return TelegramBotClient(settings.TELEGRAM_BOT_TOKEN or "")


def get_chat_mode_service() -> ChatModeService:
    return _chat_mode_service


async def get_chat_memory_repository(
    client: Any = Depends(get_supabase),
) -> ChatMemoryRepository:
    return ChatMemoryRepository(client=client)


async def get_chat_agent_service(
    memory_repository: ChatMemoryRepository = Depends(get_chat_memory_repository),
) -> ChatAgentService:
    return ChatAgentService(memory_repository=memory_repository)


def get_reflection_repository(
    client: Any = Depends(get_supabase),
) -> ReflectionRepository:
    return ReflectionRepository(client=client)


def get_reflection_service(
    reflection_repository: ReflectionRepository = Depends(get_reflection_repository),
    voice_notes_repository: VoiceNotesRepository = Depends(get_voice_notes_repository),
    sources_repository: SourcesRepository = Depends(get_sources_repository),
) -> ReflectionService:
    model = ChatOpenAI(
        model=settings.REFLECTION_LLM_MODEL,
        api_key=settings.OPENAI_API_KEY,
    )
    return ReflectionService(
        reflection_repository=reflection_repository,
        voice_notes_repository=voice_notes_repository,
        sources_repository=sources_repository,
        model=model,
    )


def get_command_handler(
    source_service: SourceService = Depends(get_source_service),
    bot_client: TelegramBotClient = Depends(get_telegram_bot_client),
    labels_repository: LabelsRepository = Depends(get_labels_repository),
    chat_mode_service: ChatModeService = Depends(get_chat_mode_service),
    reflection_service: ReflectionService = Depends(get_reflection_service),
) -> TelegramCommandHandler:
    return TelegramCommandHandler(
        source_service=source_service,
        bot_client=bot_client,
        labels_repository=labels_repository,
        chat_mode_service=chat_mode_service,
        reflection_service=reflection_service,
    )


def get_message_handler(
    ingestion_service: TelegramIngestionService = Depends(get_ingestion_service),
    voice_note_service: VoiceNoteService = Depends(get_voice_note_service),
    transcription_service: TranscriptionService = Depends(get_transcription_service),
    command_handler: TelegramCommandHandler = Depends(get_command_handler),
    bot_client: TelegramBotClient = Depends(get_telegram_bot_client),
    chat_mode_service: ChatModeService = Depends(get_chat_mode_service),
    chat_agent_service: ChatAgentService = Depends(get_chat_agent_service),
    reflection_service: ReflectionService = Depends(get_reflection_service),
) -> TelegramMessageHandler:
    return TelegramMessageHandler(
        ingestion_service=ingestion_service,
        voice_note_service=voice_note_service,
        transcription_service=transcription_service,
        command_handler=command_handler,
        bot_client=bot_client,
        chat_mode_service=chat_mode_service,
        chat_agent_service=chat_agent_service,
        reflection_service=reflection_service,
    )


@router.post("/webhook", dependencies=[Depends(verify_telegram_secret)])
async def telegram_webhook(
    request: Request,
    handler: TelegramMessageHandler = Depends(get_message_handler),
) -> dict[str, Any]:
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON payload",
        )

    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON payload",
        )

    # Accept update payloads even if message type is unsupported.
    try:
        result = await handler.handle(payload)
    except RepositoryError as exc:
        logger.exception("telegram.webhook.repository_error | {}", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to persist ingestion event",
        )
    except (TelegramDownloadError, TranscriptionError) as exc:
        logger.exception("telegram.webhook.processing_error | {}", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to process audio message",
        )

    return {"status": "ok", **result}
