from __future__ import annotations

import os
from typing import Any, Optional

import httpx
import pytest

from backend.services.telegram_audio_downloader import (
    TelegramAudioDownloader,
    TelegramDownloadError,
)


class _StreamContext:
    def __init__(self, response: httpx.Response) -> None:
        self._response = response

    def __enter__(self) -> httpx.Response:
        return self._response

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


def _build_fake_httpx_client(
    *,
    get_json: Optional[dict[str, Any]] = None,
    get_status: int = 200,
    stream_bytes: bytes = b"",
    stream_status: int = 200,
    raise_on_get: Optional[Exception] = None,
    raise_on_stream: Optional[Exception] = None,
) -> type:
    class FakeClient:
        def __init__(self, timeout: Optional[float] = None) -> None:
            self.timeout = timeout

        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

        def get(self, url: str, params: Optional[dict[str, str]] = None) -> httpx.Response:
            if raise_on_get:
                raise raise_on_get
            request = httpx.Request("GET", url, params=params)
            return httpx.Response(get_status, request=request, json=get_json)

        def stream(self, method: str, url: str) -> _StreamContext:
            if raise_on_stream:
                raise raise_on_stream
            request = httpx.Request(method, url)
            response = httpx.Response(stream_status, request=request, content=stream_bytes)
            return _StreamContext(response)

    return FakeClient


class TestTelegramAudioDownloader:
    def test_download_audio_returns_path_and_nonzero_size(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_client = _build_fake_httpx_client(
            get_json={"ok": True, "result": {"file_path": "voice.ogg"}},
            stream_bytes=b"voice-bytes",
        )
        monkeypatch.setattr(httpx, "Client", fake_client)

        downloader = TelegramAudioDownloader(token="token")
        temp_path = downloader.download_audio("file-123")

        try:
            assert os.path.exists(temp_path)
            assert os.path.getsize(temp_path) > 0
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    def test_download_audio_raises_on_invalid_file_id_http_status(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_client = _build_fake_httpx_client(
            get_json={"ok": False, "description": "Not Found"},
            get_status=404,
        )
        monkeypatch.setattr(httpx, "Client", fake_client)

        downloader = TelegramAudioDownloader(token="token")

        with pytest.raises(TelegramDownloadError) as excinfo:
            downloader.download_audio("bad-file")

        assert "HTTP 404" in str(excinfo.value)

    def test_download_audio_raises_on_network_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        request = httpx.Request("GET", "https://api.telegram.org")
        fake_client = _build_fake_httpx_client(
            raise_on_get=httpx.RequestError("boom", request=request),
        )
        monkeypatch.setattr(httpx, "Client", fake_client)

        downloader = TelegramAudioDownloader(token="token")

        with pytest.raises(TelegramDownloadError) as excinfo:
            downloader.download_audio("file-123")

        assert "Network error calling getFile API" in str(excinfo.value)

    def test_download_audio_handles_getfile_error_payload(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_client = _build_fake_httpx_client(
            get_json={"ok": False, "description": "File not found"},
            get_status=200,
        )
        monkeypatch.setattr(httpx, "Client", fake_client)

        downloader = TelegramAudioDownloader(token="token")

        with pytest.raises(TelegramDownloadError) as excinfo:
            downloader.download_audio("bad-file")

        assert "getFile API error" in str(excinfo.value)

    def test_download_audio_requires_file_id(self) -> None:
        downloader = TelegramAudioDownloader(token="token")

        with pytest.raises(TelegramDownloadError) as excinfo:
            downloader.download_audio("")

        assert "file_id is required" in str(excinfo.value)
