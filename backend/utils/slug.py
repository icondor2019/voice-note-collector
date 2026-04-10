import re


def slugify(text: str) -> str:
    normalized = text.lower()
    cleaned = re.sub(r"[^a-z0-9\s-]", "", normalized)
    parts = [part for part in re.split(r"[\s-]+", cleaned.strip()) if part]
    return "-".join(parts).strip("-")


def validate_slug_input(text: str) -> bool:
    if not text:
        return False
    if re.search(r"[^A-Za-z0-9\s-]", text):
        return False
    tokens = text.split()
    if len(tokens) == 1:
        tokens = [segment for segment in tokens[0].split("-") if segment]
    return 2 <= len(tokens) <= 4
