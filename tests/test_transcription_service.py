from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import pytest

from configuration.settings import settings
from backend.services.telegram_audio_downloader import TelegramDownloadError
from backend.services.transcription_service import (
    TranscriptionError,
    TranscriptionService,
)


@pytest.fixture(autouse=True)
def _configure_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setattr(settings, "GROQ_API_KEY", "groq")


class TestTranscriptionService:
    def test_transcribe_returns_text_and_cleans_temp_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        temp_file = tmp_path / "audio.ogg"
        temp_file.write_bytes(b"audio")

        def fake_download(self, file_id: str) -> str:
            return str(temp_file)

        def fake_transcribe(self, file_path: str, file_id: str) -> str:
            return "hola"

        monkeypatch.setattr(
            "backend.services.transcription_service.TelegramAudioDownloader.download_audio",
            fake_download,
        )
        monkeypatch.setattr(
            "backend.services.transcription_service.TranscriptionService._transcribe_audio_file",
            fake_transcribe,
        )

        service = TranscriptionService()

        result = service.transcribe_telegram_audio("file-123")

        assert result == "hola"
        assert not temp_file.exists()

    def test_transcribe_raises_on_download_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_download(self, file_id: str) -> str:
            raise TelegramDownloadError(file_id=file_id, message="invalid")

        monkeypatch.setattr(
            "backend.services.transcription_service.TelegramAudioDownloader.download_audio",
            fake_download,
        )

        service = TranscriptionService()

        with pytest.raises(TelegramDownloadError):
            service.transcribe_telegram_audio("bad-file")

    def test_transcribe_raises_on_groq_failure_and_cleans_temp_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        temp_file = tmp_path / "audio.ogg"
        temp_file.write_bytes(b"audio")

        def fake_download(self, file_id: str) -> str:
            return str(temp_file)

        def fake_transcribe(self, file_path: str, file_id: str) -> str:
            raise TranscriptionError(message="rate limited", file_id=file_id)

        monkeypatch.setattr(
            "backend.services.transcription_service.TelegramAudioDownloader.download_audio",
            fake_download,
        )
        monkeypatch.setattr(
            "backend.services.transcription_service.TranscriptionService._transcribe_audio_file",
            fake_transcribe,
        )

        service = TranscriptionService()

        with pytest.raises(TranscriptionError):
            service.transcribe_telegram_audio("file-123")

        assert not temp_file.exists()

    def test_cleanup_handles_missing_file(self, monkeypatch: pytest.MonkeyPatch) -> None:
        service = TranscriptionService()
        called = {"exists": False}

        def fake_exists(path: str) -> bool:
            called["exists"] = True
            return False

        monkeypatch.setattr(os.path, "exists", fake_exists)

        service._cleanup_temp_file("missing-path", "file-123")

        assert called["exists"]

    def test_transcribe_requires_file_id(self) -> None:
        service = TranscriptionService()

        with pytest.raises(TranscriptionError) as excinfo:
            service.transcribe_telegram_audio("")

        assert "file_id is required" in str(excinfo.value)
