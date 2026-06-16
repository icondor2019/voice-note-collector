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

    async def send_message_with_inline_keyboard(
        self, chat_id: int | str, text: str, reply_markup: dict
    ) -> dict | None:
        url = f"https://api.telegram.org/bot{self._bot_token}/sendMessage"
        payload = {"chat_id": chat_id, "text": text, "reply_markup": reply_markup}
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=payload)
            response.raise_for_status()
            logger.info(
                "telegram.send_message_with_inline_keyboard.success",
                extra={"chat_id": chat_id},
            )
            return response.json()
        except Exception as exc:
            logger.error(
                "telegram.send_message_with_inline_keyboard.failed",
                extra={"chat_id": chat_id, "error": str(exc)},
            )
            return None

    async def edit_message_text(
        self,
        chat_id: int | str,
        message_id: int,
        text: str,
        reply_markup: dict | None = None,
    ) -> None:
        url = f"https://api.telegram.org/bot{self._bot_token}/editMessageText"
        payload: dict = {"chat_id": chat_id, "message_id": message_id, "text": text}
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=payload)
            response.raise_for_status()
            logger.info(
                "telegram.edit_message_text.success",
                extra={"chat_id": chat_id, "message_id": message_id},
            )
        except httpx.HTTPStatusError as exc:
            if "message is not modified" in str(exc):
                logger.debug(
                    "telegram.edit_message_text.not_modified",
                    extra={"chat_id": chat_id, "message_id": message_id},
                )
                return
            logger.error(
                "telegram.edit_message_text.failed",
                extra={
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "status_code": exc.response.status_code,
                    "error": str(exc),
                },
            )
        except Exception as exc:
            logger.error(
                "telegram.edit_message_text.failed",
                extra={
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "error": str(exc),
                },
            )

    async def answer_callback_query(
        self,
        callback_query_id: str,
        text: str | None = None,
        show_alert: bool = False,
    ) -> None:
        url = f"https://api.telegram.org/bot{self._bot_token}/answerCallbackQuery"
        payload: dict = {"callback_query_id": callback_query_id}
        if text is not None:
            payload["text"] = text
            payload["show_alert"] = show_alert
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=payload)
            response.raise_for_status()
            logger.info(
                "telegram.answer_callback_query.success",
                extra={"callback_query_id": callback_query_id},
            )
        except Exception as exc:
            logger.error(
                "telegram.answer_callback_query.failed",
                extra={"callback_query_id": callback_query_id, "error": str(exc)},
            )
