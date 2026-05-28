from __future__ import annotations

from typing import Any, Optional, cast

from backend.repositories.repository_errors import RepositoryError


class ReflectionRepository:
    def __init__(self, client: Any) -> None:
        self._table = "reflections"
        self._client = client

    async def get_pending_reflection(self, telegram_user_id: int) -> Optional[dict[str, Any]]:
        response = (
            await self._client.table(self._table)
            .select("*")
            .eq("telegram_user_id", telegram_user_id)
            .eq("status", "pending")
            .maybe_single()
            .execute()
        )
        self._raise_on_error(response, allow_none_response=True)
        return self._single(response)

    async def create_reflection(
        self,
        telegram_user_id: int,
        voice_note_id: Optional[str],
        question_type: str,
        question_text: str,
    ) -> dict[str, Any]:
        payload = {
            "telegram_user_id": telegram_user_id,
            "voice_note_id": voice_note_id,
            "question_type": question_type,
            "question_text": question_text,
            "status": "pending",
        }
        response = await self._client.table(self._table).insert(payload).execute()
        self._raise_on_error(response)
        record = self._single(response)
        if not record:
            raise RepositoryError("Failed to create reflection")
        assert record is not None
        return cast(dict[str, Any], record)

    async def complete_reflection(
        self,
        reflection_id: str,
        answer_text: str,
        rating: int,
        feedback: str,
    ) -> dict[str, Any]:
        payload = {
            "status": "completed",
            "answer_text": answer_text,
            "rating": rating,
            "feedback": feedback,
            "completed_at": "NOW()",
        }
        response = (
            await self._client.table(self._table)
            .update(payload)
            .eq("id", reflection_id)
            .execute()
        )
        self._raise_on_error(response)
        record = self._single(response)
        if not record:
            raise RepositoryError("Failed to complete reflection")
        assert record is not None
        return cast(dict[str, Any], record)

    async def cancel_pending_reflection(self, telegram_user_id: int) -> None:
        payload = {
            "status": "cancelled",
            "completed_at": "NOW()",
        }
        response = (
            await self._client.table(self._table)
            .update(payload)
            .eq("telegram_user_id", telegram_user_id)
            .eq("status", "pending")
            .execute()
        )
        self._raise_on_error(response, allow_none_response=True)

    @staticmethod
    def _raise_on_error(response: Any, allow_none_response: bool = False) -> None:
        if response is None:
            if allow_none_response:
                return
            raise RepositoryError("Supabase returned no response")
        error = getattr(response, "error", None)
        if error:
            raise RepositoryError(str(error))

    @staticmethod
    def _single(response: Any) -> Optional[dict[str, Any]]:
        if not response or not response.data:
            return None
        if isinstance(response.data, list):
            return response.data[0] if response.data else None
        return response.data

    @staticmethod
    def _list(response: Any) -> list[dict[str, Any]]:
        if not response or not response.data:
            return []
        if isinstance(response.data, list):
            return response.data
        return [response.data]
