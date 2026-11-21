from __future__ import annotations

import re
import secrets
import time
import unicodedata

_SENTENCE_SPLIT = re.compile(r"(?<=[.;!?])\s+(?=[A-ZĄĆĘŁŃÓŚŹŻ0-9])")


def fold(text: str) -> str:
    """Małe litery bez polskich znaków (bez zmiany długości poza złożonymi znakami)."""
    decomposed = unicodedata.normalize("NFD", text.lower())
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn").replace("ł", "l")


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", fold(text)).strip()


def collapse_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_SPLIT.split(collapse_whitespace(text)) if s.strip()]


def truncate(text: str, max_len: int = 220) -> str:
    clean = collapse_whitespace(text)
    if len(clean) <= max_len:
        return clean
    cut = clean[:max_len]
    return re.sub(r"[,;:]$", "", cut[: cut.rfind(" ")]) + "…"


def match_stems(text: str, stems: list[str]) -> list[str]:
    haystack = normalize(text)
    return [s for s in stems if normalize(s) in haystack]


def new_id(prefix: str) -> str:
    alphabet = "0123456789abcdefghijklmnopqrstuvwxyz"
    rand = "".join(secrets.choice(alphabet) for _ in range(6))
    stamp = int(time.time() * 1000)
    tail = ""
    while stamp:
        stamp, r = divmod(stamp, 36)
        tail = alphabet[r] + tail
    return f"{prefix}-{rand}{tail[-4:]}"
