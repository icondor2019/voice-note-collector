from __future__ import annotations

import httpx
from loguru import logger


class TelegramBotClient:
    def __init__(self, bot_token: str) -> None:
        self._bot_token = bot_token

    async def send_message(self, chat_id: int | str, text: str) -> None:
        url = f"https://api.telegram.org/bot{self._bot_token}/sendMessage"
        payload = {"chat_id": chat_id, "text": text}
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=payload)
            response.raise_for_status()
            logger.info("telegram.send_message.success", extra={"chat_id": chat_id})
        except Exception as exc:
            logger.error(
                "telegram.send_message.failed", extra={"chat_id": chat_id, "error": str(exc)}
            )
