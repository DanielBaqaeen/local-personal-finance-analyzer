from __future__ import annotations

import logging
import re
from typing import Any

SENSITIVE_KEYS = {"description", "description_raw", "evidence", "evidence_json", "raw"}

class RedactingFilter(logging.Filter):
    # Strips raw transaction descriptions and other sensitive fields from logs.
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = _redact_text(record.msg)
        if record.args:
            try:
                record.args = tuple(_redact_obj(a) for a in record.args)
            except Exception:
                record.args = ("<redacted>",)
        return True

def _redact_text(s: str) -> str:
    s = re.sub(r"(?i)(description|desc|merchant)\s*=\s*[^\s,;]+", r"\1=<redacted>", s)
    if len(s) > 500:
        s = s[:500] + "...<truncated>"
    return s

def _redact_obj(o: Any) -> Any:
    if isinstance(o, dict):
        return {k: ("<redacted>" if k.lower() in SENSITIVE_KEYS else _redact_obj(v)) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_redact_obj(x) for x in o]
    if isinstance(o, str):
        return _redact_text(o)
    return o
