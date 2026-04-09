"""Telegram audio file downloader service.

Downloads audio files from Telegram Bot API given a file_id.
"""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
from typing import Optional

import httpx
from loguru import logger


class TelegramDownloadError(Exception):
    """Raised when Telegram audio download fails.

    Attributes:
        file_id: The Telegram file_id that failed to download.
        message: Human-readable error description.
        original_error: The underlying exception, if any.
    """

    def __init__(
        self,
        file_id: str,
        message: str,
        original_error: Optional[Exception] = None,
    ) -> None:
        self.file_id = file_id
        self.message = message
        self.original_error = original_error
        super().__init__(f"TelegramDownloadError(file_id={file_id}): {message}")


class TelegramAudioDownloader:
    """Downloads audio files from Telegram Bot API.

    This class handles the two-step process of:
    1. Calling getFile API to retrieve the file_path
    2. Downloading the actual file from Telegram's file server

    Attributes:
        token: Telegram Bot API token.
    """

    TELEGRAM_API_BASE = "https://api.telegram.org"
    DEFAULT_TIMEOUT = 60.0  # seconds

    def __init__(self, token: str) -> None:
        """Initialize the downloader with a Telegram Bot token.

        Args:
            token: Telegram Bot API token (from BotFather).
        """
        if not token:
            raise ValueError("Telegram bot token is required")
        self._token = token

    def download_audio(self, file_id: str) -> str:
        """Download audio file from Telegram and save to temporary file.

        Args:
            file_id: Telegram file_id from voice/audio message.

        Returns:
            Path to the downloaded temporary file. Caller is responsible
            for cleanup.

        Raises:
            TelegramDownloadError: If download fails for any reason
                (invalid file_id, network error, API error).
        """
        if not file_id:
            raise TelegramDownloadError(file_id="", message="file_id is required")

        log_ctx = {"file_id": file_id}
        logger.info("telegram.audio.download.start", extra=log_ctx)

        # Step 1: Get file_path from Telegram API
        file_path = self._get_file_path(file_id)
        logger.debug(
            "telegram.audio.download.file_path_retrieved",
            extra={**log_ctx, "file_path": file_path},
        )

        # Step 2: Download the actual file
        temp_file_path = self._download_file(file_id, file_path)

        file_size = os.path.getsize(temp_file_path)
        logger.info(
            "telegram.audio.download.complete",
            extra={**log_ctx, "file_path": file_path, "file_size_bytes": file_size},
        )

        return temp_file_path

    def _get_file_path(self, file_id: str) -> str:
        """Call Telegram getFile API to retrieve file_path.

        Args:
            file_id: Telegram file_id.

        Returns:
            The file_path from Telegram API response.

        Raises:
            TelegramDownloadError: If API call fails.
        """
        url = f"{self.TELEGRAM_API_BASE}/bot{self._token}/getFile"
        params = {"file_id": file_id}

        try:
            with httpx.Client(timeout=self.DEFAULT_TIMEOUT) as client:
                response = client.get(url, params=params)
                response.raise_for_status()
                data = response.json()

        except httpx.TimeoutException as e:
            raise TelegramDownloadError(
                file_id=file_id,
                message="Timeout while calling getFile API",
                original_error=e,
            ) from e
        except httpx.HTTPStatusError as e:
            status_code = e.response.status_code
            raise TelegramDownloadError(
                file_id=file_id,
                message=f"getFile API returned HTTP {status_code}",
                original_error=e,
            ) from e
        except httpx.RequestError as e:
            raise TelegramDownloadError(
                file_id=file_id,
                message=f"Network error calling getFile API: {e}",
                original_error=e,
            ) from e

        if not data.get("ok"):
            error_description = data.get("description", "Unknown error")
            raise TelegramDownloadError(
                file_id=file_id,
                message=f"getFile API error: {error_description}",
            )

        result = data.get("result", {})
        file_path = result.get("file_path")
        if not file_path:
            raise TelegramDownloadError(
                file_id=file_id,
                message="getFile API returned no file_path",
            )

        return file_path

    def _download_file(self, file_id: str, file_path: str) -> str:
        """Download file from Telegram file server to temporary file.

        Args:
            file_id: Telegram file_id (for error context).
            file_path: File path from getFile API response.

        Returns:
            Path to the downloaded temporary file.

        Raises:
            TelegramDownloadError: If download fails.
        """
        tmp_dir = Path(__file__).resolve().parents[2] / "tmp"
        os.makedirs(tmp_dir, exist_ok=True)
        url = f"{self.TELEGRAM_API_BASE}/file/bot{self._token}/{file_path}"

        # Determine file extension from file_path
        _, ext = os.path.splitext(file_path)
        if not ext:
            ext = ".ogg"  # Default for Telegram voice messages
        if ext == ".oga":
            ext = ".ogg"

        try:
            with httpx.Client(timeout=self.DEFAULT_TIMEOUT) as client:
                with client.stream("GET", url) as response:
                    response.raise_for_status()

                    # Create temp file with appropriate extension
                    temp_file = tempfile.NamedTemporaryFile(
                        delete=False,
                        suffix=ext,
                        prefix="telegram_audio_",
                        dir=tmp_dir,
                    )

                    try:
                        for chunk in response.iter_bytes(chunk_size=8192):
                            temp_file.write(chunk)
                        temp_file.close()
                        return temp_file.name
                    except Exception:
                        # Clean up on partial download failure
                        temp_file.close()
                        if os.path.exists(temp_file.name):
                            os.unlink(temp_file.name)
                        raise

        except httpx.TimeoutException as e:
            raise TelegramDownloadError(
                file_id=file_id,
                message="Timeout while downloading audio file",
                original_error=e,
            ) from e
        except httpx.HTTPStatusError as e:
            status_code = e.response.status_code
            raise TelegramDownloadError(
                file_id=file_id,
                message=f"File download returned HTTP {status_code}",
                original_error=e,
            ) from e
        except httpx.RequestError as e:
            raise TelegramDownloadError(
                file_id=file_id,
                message=f"Network error downloading file: {e}",
                original_error=e,
            ) from e
