import re


def normalize_item_name(name: str) -> str:
    if not name:
        return ""

    normalized = str(name)
    normalized = (
        normalized
        .replace("\u00A0", " ")
        .replace("\u200B", " ")
        .replace("\u202F", " ")
        .replace("–", "-")
        .replace("—", "-")
        .replace("\u2013", "-")
        .replace("\u2014", "-")
    )
    normalized = normalized.strip()
    normalized = re.sub(r"\s*-\s*", " - ", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.casefold()
