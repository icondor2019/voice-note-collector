from __future__ import annotations


class RepositoryError(RuntimeError):
    """Base error for repository failures."""


class DuplicateRecordError(RepositoryError):
    """Raised when a unique constraint is violated."""


class SupabaseConfigError(RepositoryError):
    """Raised when Supabase configuration is missing."""
