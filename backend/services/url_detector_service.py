"""URL detection service — identifies URL-only messages."""

from __future__ import annotations

import re

# Anchored regex: the ENTIRE string (after stripping) must be a URL.
# Matches:
#   https?://...
#   www....
#   bare domains like youtube.com/path
_URL_PATTERN = re.compile(
    r"^(?:"
    r"https?://"  # http:// or https://
    r"|www\."  # www.
    r"|(?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}"  # bare domain (e.g. youtube.com)
    r")"
    r"[^\s]*$"  # rest of URL (no whitespace)
)


class UrlDetectorService:
    """Detects whether an entire message is a URL."""

    @staticmethod
    def is_url(text: str) -> bool:
        """Return True only if the entire message (after trimming) is a URL.

        A message like 'check this https://youtube.com/abc' returns False
        because it contains additional text beyond the URL.
        """
        stripped = text.strip()
        if not stripped:
            return False
        return bool(_URL_PATTERN.match(stripped))

    @staticmethod
    def extract_url(text: str) -> str:
        """Return the trimmed URL if is_url() is True, else empty string."""
        stripped = text.strip()
        if UrlDetectorService.is_url(stripped):
            return stripped
        return ""
