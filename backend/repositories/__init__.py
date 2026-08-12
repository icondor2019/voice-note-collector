"""Repository layer for persistence and storage access."""

from backend.repositories.sources_repository import SourcesRepository
from backend.repositories.labels_repository import LabelsRepository
from backend.repositories.session_documents_repository import SessionDocumentsRepository
from backend.repositories.supabase_client import get_supabase_client
from backend.repositories.voice_note_details_repository import VoiceNoteDetailsRepository
from backend.repositories.voice_note_labels_repository import VoiceNoteLabelsRepository
from backend.repositories.voice_notes_repository import VoiceNotesRepository

__all__ = [
    "SourcesRepository",
    "LabelsRepository",
    "SessionDocumentsRepository",
    "VoiceNotesRepository",
    "VoiceNoteDetailsRepository",
    "VoiceNoteLabelsRepository",
    "get_supabase_client",
]
