from __future__ import annotations

from fastapi import HTTPException, Request
from loguru import logger

from configuration.settings import settings


async def verify_telegram_secret(request: Request) -> None:
    if settings.TELEGRAM_WEBHOOK_SECRET is None:
        logger.debug("telegram.webhook.secret.skip")
        return

    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    if not secret or secret != settings.TELEGRAM_WEBHOOK_SECRET:
        logger.warning("telegram.webhook.secret.invalid")
        raise HTTPException(status_code=403, detail="Forbidden")


async def verify_api_key(request: Request) -> None:
    if settings.API_KEY is None:
        logger.debug("api.key.skip")
        return

    api_key = request.headers.get("X-API-Key")
    if not api_key or api_key != settings.API_KEY:
        logger.warning("api.key.invalid")
        raise HTTPException(status_code=401, detail="Invalid API key")
