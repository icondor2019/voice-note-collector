"""Repository layer for persistence and storage access."""

from backend.repositories.telegram_ingestion_event_store import FileIngestionEventStore

__all__ = ["FileIngestionEventStore"]
