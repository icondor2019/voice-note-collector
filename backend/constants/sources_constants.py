"""Single source of truth for source type prefix mappings."""

from __future__ import annotations

from typing import Optional

# Prefix code (without dash) -> canonical type string
SOURCE_PREFIX_TO_TYPE: dict[str, str] = {
    "yt": "youtube",
    "ig": "instagram",
    "fb": "facebook",
    "lkn": "linkedin",
    "wb": "web",
    "bk": "book",
    "cr": "course",
    "th": "thought",
    "ts": "test",
    "ot": "other",
}

# Reverse mapping: canonical type string -> prefix code (without dash)
SOURCE_TYPE_TO_PREFIX: dict[str, str] = {
    v: k for k, v in SOURCE_PREFIX_TO_TYPE.items()
}

# Set of all canonical type strings
VALID_SOURCE_TYPES: set[str] = set(SOURCE_PREFIX_TO_TYPE.values())

# Tuple of all prefix strings with trailing dash (for source name validation)
VALID_PREFIXES: tuple[str, ...] = tuple(
    f"{prefix}-" for prefix in SOURCE_PREFIX_TO_TYPE
)


def resolve_prefix_to_type(prefix_arg: str) -> Optional[str]:
    """Normalize a prefix argument and resolve it to a canonical type.

    Accepts the prefix code without a trailing dash (e.g. "yt", "TS").
    Does NOT strip trailing dashes — "yt-" is NOT accepted.
    Returns the canonical type string or None if not recognized.
    """
    normalized = prefix_arg.strip().lower()
    return SOURCE_PREFIX_TO_TYPE.get(normalized)
