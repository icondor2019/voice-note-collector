from __future__ import annotations

import logging
from typing import Any

from supabase import create_async_client

from configuration.settings import settings
from backend.repositories.repository_errors import SupabaseConfigError


logger = logging.getLogger(__name__)


async def get_supabase_client() -> Any:
    if not settings.SUPABASE_URL or not settings.SUPABASE_SECRET_KEY:
        logger.error(
            "supabase.config.missing",
            extra={
                "has_url": bool(settings.SUPABASE_URL),
                "has_secret_key": bool(settings.SUPABASE_SECRET_KEY),
            },
        )
        raise SupabaseConfigError("Supabase configuration is missing.")

    return await create_async_client(settings.SUPABASE_URL, settings.SUPABASE_SECRET_KEY)
