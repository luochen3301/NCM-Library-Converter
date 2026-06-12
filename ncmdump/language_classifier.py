from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from pathlib import Path


LANGUAGE_ORDER = ("all", "zh", "en", "ja", "ko", "mixed", "other", "unknown")

LANGUAGE_NAMES = {
    "zh": "Chinese",
    "en": "English",
    "ja": "Japanese",
    "ko": "Korean",
    "mixed": "Mixed",
    "other": "Other",
    "unknown": "Unknown",
}


@dataclass(frozen=True)
class LanguageClassification:
    language: str
    confidence: int
    signal: str


def classify_track_text(value: str) -> LanguageClassification:
    text = _normalize_source_text(value)
    if not text:
        return LanguageClassification("unknown", 0, "no text")

    counts = {"zh": 0, "en": 0, "ja": 0, "ko": 0, "other": 0}
    for char in text:
        bucket = _script_bucket(char)
        if bucket:
            counts[bucket] += 1

    total = sum(counts.values())
    if total == 0:
        return LanguageClassification("unknown", 0, "no letters")

    ranked = sorted(counts.items(), key=lambda item: item[1], reverse=True)
    primary, primary_count = ranked[0]
    secondary, secondary_count = ranked[1]
    active = [key for key, count in counts.items() if count > 0]

    if counts["ja"] and (counts["ja"] + counts["zh"]) >= 2:
        primary_count = counts["ja"] + counts["zh"]
        confidence = _confidence(int((primary_count / total) * 100), mixed=False)
        return LanguageClassification("ja", confidence, _signal(counts, total))

    if len(active) > 1 and secondary_count >= 2 and secondary_count / total >= 0.18:
        confidence = _confidence(int((primary_count / total) * 100), mixed=True)
        return LanguageClassification("mixed", confidence, _signal(counts, total))

    confidence = _confidence(int((primary_count / total) * 100), mixed=False)
    return LanguageClassification(primary, confidence, _signal(counts, total))


def classify_path(value: str | Path) -> LanguageClassification:
    path = Path(value)
    parts = [path.stem, *path.parts[:-1]]
    return classify_track_text(" ".join(str(part) for part in parts if part))


def _normalize_source_text(value: str) -> str:
    path = Path(value)
    text = str(path.with_suffix("")) if path.suffix else str(value)
    return " ".join(text.replace("_", " ").replace("-", " ").split())


def _script_bucket(char: str) -> str:
    codepoint = ord(char)
    if 0x3040 <= codepoint <= 0x30FF:
        return "ja"
    if 0xAC00 <= codepoint <= 0xD7AF or 0x1100 <= codepoint <= 0x11FF or 0x3130 <= codepoint <= 0x318F:
        return "ko"
    if (
        0x3400 <= codepoint <= 0x4DBF
        or 0x4E00 <= codepoint <= 0x9FFF
        or 0xF900 <= codepoint <= 0xFAFF
    ):
        return "zh"
    if char.isascii() and char.isalpha():
        return "en"
    if unicodedata.category(char).startswith("L"):
        name = unicodedata.name(char, "")
        return "en" if "LATIN" in name else "other"
    return ""


def _confidence(value: int, mixed: bool) -> int:
    if mixed:
        return max(48, min(82, value))
    return max(52, min(96, value))


def _signal(counts: dict[str, int], total: int) -> str:
    parts = []
    for key in ("zh", "en", "ja", "ko", "other"):
        count = counts.get(key, 0)
        if count:
            percent = int((count / total) * 100)
            parts.append(f"{LANGUAGE_NAMES[key]} {percent}%")
    return ", ".join(parts) if parts else "no signal"
