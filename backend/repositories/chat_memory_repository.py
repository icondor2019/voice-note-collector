from __future__ import annotations

from typing import Any, cast

from backend.models.chat_memory import ChatMemoryEntry
from backend.repositories.repository_errors import RepositoryError


class ChatMemoryRepository:
    def __init__(self, client: Any) -> None:
        self._table = "voice_note_chat_memory"
        self._client = client

    async def get_last_n_messages(
        self, telegram_user_id: int, n: int
    ) -> list[ChatMemoryEntry]:
        response = (
            await self._client.table(self._table)
            .select("*")
            .eq("telegram_user_id", telegram_user_id)
            .order("created_at", desc=True)
            .limit(n)
            .execute()
        )

        self._raise_on_error(response)
        entries = [ChatMemoryEntry(**entry) for entry in self._list(response)]
        entries.reverse()
        return entries

    async def save_message(self, telegram_user_id: int, role: str, content: str) -> None:
        payload = {
            "telegram_user_id": telegram_user_id,
            "role": role,
            "content": content,
        }
        response = await self._client.table(self._table).insert(payload).execute()
        self._raise_on_error(response)

    @staticmethod
    def _raise_on_error(response: Any) -> None:
        if response is not None and hasattr(response, "error") and response.error:
            raise RepositoryError(f"Supabase error: {response.error}")
        if response is None:
            raise RepositoryError("Supabase returned None response")

    @staticmethod
    def _list(response: Any) -> list[dict[str, Any]]:
        if not response or not response.data:
            return []
        if isinstance(response.data, list):
            return cast(list[dict[str, Any]], response.data)
        return [cast(dict[str, Any], response.data)]
