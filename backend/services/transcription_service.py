"""Transcription service for Telegram audio files.

Orchestrates audio download from Telegram and transcription via Groq Whisper API.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import httpx

from backend.services.telegram_audio_downloader import (
    TelegramAudioDownloader,
    TelegramDownloadError,
)
from configuration.settings import settings

logger = logging.getLogger(__name__)


class TranscriptionError(Exception):
    """Raised when audio transcription fails.

    Attributes:
        file_id: The Telegram file_id that failed to transcribe (if available).
        message: Human-readable error description.
        original_error: The underlying exception, if any.
    """

    def __init__(
        self,
        message: str,
        file_id: Optional[str] = None,
        original_error: Optional[Exception] = None,
    ) -> None:
        self.file_id = file_id
        self.message = message
        self.original_error = original_error
        prefix = f"TranscriptionError(file_id={file_id})" if file_id else "TranscriptionError"
        super().__init__(f"{prefix}: {message}")


class TranscriptionService:
    """Transcribes Telegram audio files using Groq Whisper API.

    This service is stateless and purely functional:
    - Input: Telegram file_id
    - Output: Transcription text string
    - No persistence or idempotency (caller's responsibility)

    Temporary files are always cleaned up, even on error.
    """

    GROQ_WHISPER_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
    GROQ_WHISPER_MODEL = "whisper-large-v3"
    DEFAULT_TIMEOUT = 120.0  # seconds (transcription can take time)

    def __init__(self) -> None:
        """Initialize the transcription service.

        Reads configuration from settings singleton.

        Raises:
            ValueError: If required configuration is missing.
        """
        if not settings.TELEGRAM_BOT_TOKEN:
            raise ValueError("TELEGRAM_BOT_TOKEN is not configured")
        if not settings.GROQ_API_KEY:
            raise ValueError("GROQ_API_KEY is not configured")

        self._telegram_token = settings.TELEGRAM_BOT_TOKEN
        self._groq_api_key = settings.GROQ_API_KEY

    def transcribe_telegram_audio(self, file_id: str) -> str:
        """Transcribe a Telegram audio file.

        Downloads the audio file from Telegram, sends it to Groq Whisper API,
        and returns the transcription text.

        Args:
            file_id: Telegram file_id from voice/audio message.

        Returns:
            Transcription text as a string.

        Raises:
            TelegramDownloadError: If audio download from Telegram fails.
            TranscriptionError: If transcription via Groq API fails.
        """
        if not file_id:
            raise TranscriptionError(message="file_id is required")

        log_ctx = {"file_id": file_id}
        logger.info("transcription.start", extra=log_ctx)

        downloader = TelegramAudioDownloader(token=self._telegram_token)
        temp_file_path: Optional[str] = None

        try:
            # Step 1: Download audio from Telegram
            temp_file_path = downloader.download_audio(file_id)
            logger.debug(
                "transcription.download.complete",
                extra={**log_ctx, "temp_file_path": temp_file_path},
            )

            # Step 2: Transcribe via Groq Whisper API
            transcription = self._transcribe_audio_file(temp_file_path, file_id)

            logger.info(
                "transcription.complete",
                extra={
                    **log_ctx,
                    "transcription_length": len(transcription),
                },
            )

            return transcription

        finally:
            # Always clean up temp file
            self._cleanup_temp_file(temp_file_path, file_id)

    def _transcribe_audio_file(self, file_path: str, file_id: str) -> str:
        """Send audio file to Groq Whisper API for transcription.

        Args:
            file_path: Local path to the audio file.
            file_id: Original Telegram file_id (for error context).

        Returns:
            Transcription text.

        Raises:
            TranscriptionError: If Groq API call fails.
        """
        headers = {
            "Authorization": f"Bearer {self._groq_api_key}",
        }

        try:
            with open(file_path, "rb") as audio_file:
                files = {
                    "file": (os.path.basename(file_path), audio_file),
                }
                data = {
                    "model": self.GROQ_WHISPER_MODEL,
                }

                with httpx.Client(timeout=self.DEFAULT_TIMEOUT) as client:
                    response = client.post(
                        self.GROQ_WHISPER_URL,
                        headers=headers,
                        files=files,
                        data=data,
                    )
                    response.raise_for_status()
                    result = response.json()

        except httpx.TimeoutException as e:
            raise TranscriptionError(
                message="Timeout while calling Groq Whisper API",
                file_id=file_id,
                original_error=e,
            ) from e
        except httpx.HTTPStatusError as e:
            status_code = e.response.status_code
            # Try to extract error message from response
            try:
                error_body = e.response.json()
                error_msg = error_body.get("error", {}).get("message", str(e))
            except Exception:
                error_msg = str(e)

            if status_code == 401:
                raise TranscriptionError(
                    message="Groq API authentication failed (invalid API key)",
                    file_id=file_id,
                    original_error=e,
                ) from e
            elif status_code == 429:
                raise TranscriptionError(
                    message="Groq API rate limit exceeded",
                    file_id=file_id,
                    original_error=e,
                ) from e
            else:
                raise TranscriptionError(
                    message=f"Groq API returned HTTP {status_code}: {error_msg}",
                    file_id=file_id,
                    original_error=e,
                ) from e
        except httpx.RequestError as e:
            raise TranscriptionError(
                message=f"Network error calling Groq API: {e}",
                file_id=file_id,
                original_error=e,
            ) from e
        except OSError as e:
            raise TranscriptionError(
                message=f"Failed to read audio file: {e}",
                file_id=file_id,
                original_error=e,
            ) from e

        # Extract transcription text from response
        text = result.get("text")
        if text is None:
            raise TranscriptionError(
                message="Groq API response missing 'text' field",
                file_id=file_id,
            )

        return text

    def _cleanup_temp_file(self, file_path: Optional[str], file_id: str) -> None:
        """Clean up temporary audio file.

        Handles cases where:
        - file_path is None (download failed before file creation)
        - file doesn't exist (already deleted or permission error)

        Args:
            file_path: Path to temp file, or None.
            file_id: Original file_id (for logging context).
        """
        if file_path is None:
            return

        log_ctx = {"file_id": file_id, "temp_file_path": file_path}

        try:
            if os.path.exists(file_path):
                os.unlink(file_path)
                logger.debug("transcription.temp_file.cleaned", extra=log_ctx)
            else:
                logger.debug("transcription.temp_file.already_gone", extra=log_ctx)
        except OSError as e:
            # Log but don't raise - cleanup failure shouldn't mask other errors
            logger.warning(
                "transcription.temp_file.cleanup_failed",
                extra={**log_ctx, "error": str(e)},
            )
