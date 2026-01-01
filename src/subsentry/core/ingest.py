from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
from dateutil import parser as dtparser

log = logging.getLogger(__name__)

@dataclass
class UnifiedRow:
    posted_at: datetime
    amount: float
    currency: str
    description_raw: str
    account_id: str = ""

def _guess_col(cols: list[str], candidates: list[str]) -> str | None:
    lc = {c.lower(): c for c in cols}
    for cand in candidates:
        for k, orig in lc.items():
            if cand in k:
                return orig
    return None

def detect_schema(df: pd.DataFrame) -> dict[str, str]:
    cols = list(df.columns)
    date_col = _guess_col(cols, ["date", "posted", "transaction date", "time"])
    desc_col = _guess_col(cols, ["description", "merchant", "details", "narrative"])
    amount_col = _guess_col(cols, ["amount", "debit", "credit", "value"])
    currency_col = _guess_col(cols, ["currency", "curr"])
    if not (date_col and desc_col and amount_col):
        raise ValueError(f"Could not auto-detect schema from columns: {cols}")
    return {"date": date_col, "description": desc_col, "amount": amount_col, "currency": currency_col or ""}

def parse_amount(val: Any) -> float:
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip().replace(",", "")
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    return float(s)

def read_csv(path: Path) -> pd.DataFrame:
    for enc in ("utf-8", "utf-8-sig", "cp1252"):
        try:
            return pd.read_csv(path, encoding=enc)
        except Exception:
            continue
    return pd.read_csv(path)

def ingest_csv(path: Path) -> list[UnifiedRow]:
    df = read_csv(path)
    mapping = detect_schema(df)
    rows: list[UnifiedRow] = []
    for _, r in df.iterrows():
        posted_at = dtparser.parse(str(r[mapping["date"]]))
        amount = parse_amount(r[mapping["amount"]])
        desc = str(r[mapping["description"]]) if r[mapping["description"]] is not None else ""
        currency = str(r[mapping["currency"]]) if mapping["currency"] else ""
        rows.append(UnifiedRow(posted_at=posted_at, amount=amount, currency=currency, description_raw=desc))
    log.info("csv_ingested path=%s rows=%s", str(path), len(rows))
    return rows
