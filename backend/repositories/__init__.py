"""Repository layer for persistence and storage access."""

from backend.repositories.sources_repository import SourcesRepository
from backend.repositories.supabase_client import get_supabase_client
from backend.repositories.telegram_ingestion_event_store import FileIngestionEventStore
from backend.repositories.voice_notes_repository import VoiceNotesRepository

__all__ = [
    "FileIngestionEventStore",
    "SourcesRepository",
    "VoiceNotesRepository",
    "get_supabase_client",
]
