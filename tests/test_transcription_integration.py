from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, Optional

import httpx
import pytest

from configuration.settings import settings
from backend.services.telegram_audio_downloader import TelegramDownloadError
from backend.services.transcription_service import TranscriptionError, TranscriptionService


@pytest.fixture(autouse=True)
def _configure_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setattr(settings, "GROQ_API_KEY", "groq")


class _StreamContext:
    def __init__(self, response: httpx.Response) -> None:
        self._response = response

    def __enter__(self) -> httpx.Response:
        return self._response

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


class _FakeClient:
    def __init__(
        self,
        *,
        get_json: dict[str, Any],
        stream_bytes: bytes,
        groq_status: int = 200,
        groq_json: Optional[dict[str, Any]] = None,
    ) -> None:
        self._get_json = get_json
        self._stream_bytes = stream_bytes
        self._groq_status = groq_status
        self._groq_json = groq_json or {"text": "hello"}
        self.groq_called = False

    def __enter__(self) -> "_FakeClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def get(self, url: str, params: Optional[dict[str, str]] = None) -> httpx.Response:
        request = httpx.Request("GET", url, params=params)
        return httpx.Response(200, request=request, json=self._get_json)

    def stream(self, method: str, url: str) -> _StreamContext:
        request = httpx.Request(method, url)
        response = httpx.Response(200, request=request, content=self._stream_bytes)
        return _StreamContext(response)

    def post(
        self,
        url: str,
        headers: Optional[dict[str, str]] = None,
        files: Optional[dict[str, Any]] = None,
        data: Optional[dict[str, str]] = None,
    ) -> httpx.Response:
        self.groq_called = True
        request = httpx.Request("POST", url)
        return httpx.Response(self._groq_status, request=request, json=self._groq_json)


class TestTranscriptionIntegration:
    def test_full_flow_downloads_transcribes_and_cleans(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_client = _FakeClient(
            get_json={"ok": True, "result": {"file_path": "voice.ogg"}},
            stream_bytes=b"audio",
            groq_status=200,
            groq_json={"text": "hello world"},
        )

        def fake_client_factory(*args: Any, **kwargs: Any) -> _FakeClient:
            return fake_client

        original_named_tempfile = tempfile.NamedTemporaryFile

        def fake_named_tempfile(*args: Any, **kwargs: Any) -> tempfile.NamedTemporaryFile:
            kwargs["delete"] = False
            kwargs["dir"] = tmp_path
            return original_named_tempfile(*args, **kwargs)

        monkeypatch.setattr(httpx, "Client", fake_client_factory)
        monkeypatch.setattr(
            "backend.services.telegram_audio_downloader.tempfile.NamedTemporaryFile",
            fake_named_tempfile,
        )

        service = TranscriptionService()

        transcription = service.transcribe_telegram_audio("file-123")

        assert transcription == "hello world"
        assert fake_client.groq_called
        assert list(tmp_path.iterdir()) == []

    def test_download_failure_skips_transcription(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_client = _FakeClient(
            get_json={"ok": False, "description": "not found"},
            stream_bytes=b"",
        )

        def fake_client_factory(*args: Any, **kwargs: Any) -> _FakeClient:
            return fake_client

        monkeypatch.setattr(httpx, "Client", fake_client_factory)

        service = TranscriptionService()

        with pytest.raises(TelegramDownloadError):
            service.transcribe_telegram_audio("missing")

        assert not fake_client.groq_called

    def test_transcription_failure_cleans_temp_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_client = _FakeClient(
            get_json={"ok": True, "result": {"file_path": "voice.ogg"}},
            stream_bytes=b"audio",
            groq_status=429,
            groq_json={"error": {"message": "rate limit"}},
        )

        def fake_client_factory(*args: Any, **kwargs: Any) -> _FakeClient:
            return fake_client

        original_named_tempfile = tempfile.NamedTemporaryFile

        def fake_named_tempfile(*args: Any, **kwargs: Any) -> tempfile.NamedTemporaryFile:
            kwargs["delete"] = False
            kwargs["dir"] = tmp_path
            return original_named_tempfile(*args, **kwargs)

        monkeypatch.setattr(httpx, "Client", fake_client_factory)
        monkeypatch.setattr(
            "backend.services.telegram_audio_downloader.tempfile.NamedTemporaryFile",
            fake_named_tempfile,
        )

        service = TranscriptionService()

        with pytest.raises(TranscriptionError):
            service.transcribe_telegram_audio("file-123")

        assert fake_client.groq_called
        assert list(tmp_path.iterdir()) == []
