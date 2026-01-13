from __future__ import annotations

import re

PAYPAL_PREFIX = re.compile(r"(?i)\bPAYPAL\b\s*\*\s*")
CARD_SUFFIX = re.compile(r"(?i)\s*(?:\*+\d{2,6}|CARD\s*\d{2,6})\s*$")
MULTISPACE = re.compile(r"\s+")

def clean_merchant(raw: str) -> str:
    s = (raw or "").strip().upper()
    s = PAYPAL_PREFIX.sub("", s)
    s = re.sub(r"[^A-Z0-9\s&.-]", " ", s)
    s = CARD_SUFFIX.sub("", s)
    s = s.replace(".COM", "")
    s = MULTISPACE.sub(" ", s).strip()
    return s

def canonical_hint(cleaned: str) -> str:
    if "NETFLIX" in cleaned:
        return "NETFLIX"
    if "SPOTIFY" in cleaned:
        return "SPOTIFY"
    if "AMAZON" in cleaned:
        return "AMAZON"
    return cleaned[:255]
