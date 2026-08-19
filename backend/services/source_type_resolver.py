"""Source type resolver — maps URL domains to source types."""

from __future__ import annotations

from urllib.parse import urlparse


class SourceTypeResolver:
    """Resolves source type from a URL's domain."""

    _DOMAIN_MAP: dict[str, str] = {
        "youtube.com": "youtube",
        "youtu.be": "youtube",
        "www.youtube.com": "youtube",
        "m.youtube.com": "youtube",
        "instagram.com": "instagram",
        "www.instagram.com": "instagram",
        "facebook.com": "facebook",
        "www.facebook.com": "facebook",
        "m.facebook.com": "facebook",
        "fb.com": "facebook",
        "www.fb.com": "facebook",
        "linkedin.com": "linkedin",
        "www.linkedin.com": "linkedin",
    }

    @staticmethod
    def resolve_type(url: str) -> str:
        """Map a URL's domain to a source type.

        Returns one of: youtube, instagram, facebook, linkedin, web.
        Non-URL source types (book, course, thought) are set by the agent.
        """
        try:
            # Handle bare domains without scheme
            if "://" not in url:
                url = "https://" + url
            parsed = urlparse(url)
            hostname = (parsed.hostname or "").lower()
        except Exception:
            return "web"

        return SourceTypeResolver._DOMAIN_MAP.get(hostname, "web")
