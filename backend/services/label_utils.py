from __future__ import annotations

import re

_LABEL_PATTERN = re.compile(r"^[a-z0-9 _-]+$")
_SEPARATOR_PATTERN = re.compile(r"[-_]+")
_WHITESPACE_PATTERN = re.compile(r"\s+")


def validate_label_name(raw: str) -> str | None:
    name = raw.strip().lower()
    if not name or len(name) > 64:
        return None
    if not _LABEL_PATTERN.match(name):
        return None
    return name


def dedup_key(name: str) -> str:
    normalized = _SEPARATOR_PATTERN.sub(" ", name.strip().lower())
    return _WHITESPACE_PATTERN.sub(" ", normalized).strip()
