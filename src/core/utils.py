import re

WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def sanitize_name(name: str, fallback: str) -> str:
    fallback_clean = re.sub(r"[^A-Za-z0-9_-]+", "_", str(fallback).strip())
    fallback_clean = re.sub(r"_+", "_", fallback_clean).strip("._ ") or "item"

    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", str(name).strip())
    cleaned = re.sub(r"_+", "_", cleaned).strip("._ ")
    cleaned = cleaned or fallback_clean

    if cleaned.upper() in WINDOWS_RESERVED_NAMES:
        cleaned = f"_{cleaned}"

    return cleaned[:120]
