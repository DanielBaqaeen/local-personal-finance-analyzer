from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Iterable

from sqlalchemy import select, delete, func
from sqlalchemy.orm import Session

from subsentry.db.models import Setting, SourceFile, Transaction, Merchant, MerchantAlias, RecurringSeries, Event
from subsentry.privacy.encryption import maybe_encrypt, maybe_decrypt

log = logging.getLogger(__name__)

def _is_encrypted(v: str | None) -> bool:
    return bool(v) and isinstance(v, str) and v.startswith("enc:")


def _encrypt_if_needed(key: bytes | None, v: str | None) -> str | None:
    if v is None:
        return None
    if _is_encrypted(v):
        return v
    if key is None:
        return v
    return maybe_encrypt(key, v)


@dataclass(frozen=True)
class EncryptionCtx:
    key: Optional[bytes]

class Repo:
    def __init__(self, session: Session, crypto: EncryptionCtx):
        self.s = session
        self.crypto = crypto

    # settings
    def get_setting(self, key: str) -> Optional[str]:
        obj = self.s.get(Setting, key)
        return obj.value if obj else None

    def set_setting(self, key: str, value: str) -> None:
        obj = self.s.get(Setting, key)
        if obj:
            obj.value = value
        else:
            self.s.add(Setting(key=key, value=value))
        self.s.commit()

    # encryption helpers
    def encrypt_field(self, plaintext: str) -> str:
        return maybe_encrypt(self.crypto.key, plaintext)

    def decrypt_field(self, ciphertext: str) -> str:
        return maybe_decrypt(self.crypto.key, ciphertext)

    def encrypt_existing_plaintext(self) -> tuple[int, int]:
        if self.crypto.key is None:
            raise ValueError("Encryption key not available. Unlock first.")

        tx_updated = 0
        ev_updated = 0

        # Transactions: description_raw
        txs = (
            self.s.query(Transaction)
            .filter(Transaction.description_raw.isnot(None))
            .all()
        )
        for t in txs:
            if t.description_raw and not _is_encrypted(t.description_raw):
                t.description_raw = maybe_encrypt(self.crypto.key, t.description_raw)
                tx_updated += 1

        # Events: evidence_json
        evs = (
            self.s.query(Event)
            .filter(Event.evidence_json.isnot(None))
            .all()
        )
        for e in evs:
            if e.evidence_json and not _is_encrypted(e.evidence_json):
                e.evidence_json = maybe_encrypt(self.crypto.key, e.evidence_json)
                ev_updated += 1

        self.s.commit()
        return tx_updated, ev_updated

    # import
    def create_source_file(
        self,
        filename: str,
        rows_count: int,
        *,
        period_start=None,
        period_end=None,
        statement_year: int | None = None,
        statement_month: int | None = None,
        statement_label: str | None = None,
    ) -> int:
        sf = SourceFile(
            original_filename=filename,
            rows_count=rows_count,
            period_start=period_start,
            period_end=period_end,
            statement_year=statement_year,
            statement_month=statement_month,
            statement_label=statement_label,
        )
        self.s.add(sf)
        self.s.commit()
        return sf.id


    # statements / source files
    def list_source_files(self):
        return list(self.s.execute(select(SourceFile).order_by(SourceFile.imported_at.desc())).scalars())

    def delete_source_file(self, source_file_id: int) -> tuple[int, int]:
        # Deletes all transactions tied to a statement, then deletes the statement record
        # Returns (transactions_deleted, source_files_deleted)
        tx_deleted = self.s.execute(
            delete(Transaction).where(Transaction.source_file_id == source_file_id)
        ).rowcount or 0
        sf_deleted = self.s.execute(
            delete(SourceFile).where(SourceFile.id == source_file_id)
        ).rowcount or 0
        self.s.commit()
        return tx_deleted, sf_deleted

    def _dedupe_hash(self, posted_at: datetime, amount: float, description_raw: str) -> str:
        h = hashlib.sha256()
        h.update(posted_at.isoformat().encode("utf-8"))
        h.update(f"|{amount:.2f}|".encode("utf-8"))
        h.update(description_raw.strip().upper().encode("utf-8")[:200])
        return h.hexdigest()

    def insert_transactions(self, source_file_id: int, rows: Iterable[dict]) -> tuple[int, int]:
        inserted = 0
        skipped = 0
        for r in rows:
            raw = r["description_raw"]
            h = self._dedupe_hash(r["posted_at"], float(r["amount"]), raw)
            txn = Transaction(
                posted_at=r["posted_at"],
                amount=float(r["amount"]),
                currency=r.get("currency", "") or "",
                description_raw=self.encrypt_field(raw),
                account_id=r.get("account_id", "") or "",
                source_file_id=source_file_id,
                hash_dedupe=h,
                merchant_id=None,
            )
            try:
                self.s.add(txn)
                self.s.flush()
                inserted += 1
            except Exception:
                self.s.rollback()
                skipped += 1
        self.s.commit()
        log.info("import_complete inserted=%s skipped=%s", inserted, skipped)
        return inserted, skipped

    # merchants
    def get_or_create_merchant(self, canonical_name: str) -> Merchant:
        canonical_name = canonical_name.strip().upper()
        m = self.s.execute(select(Merchant).where(Merchant.canonical_name == canonical_name)).scalar_one_or_none()
        if m:
            return m
        m = Merchant(canonical_name=canonical_name)
        self.s.add(m)
        self.s.commit()
        return m

    def list_merchants(self) -> list[Merchant]:
        return list(self.s.execute(select(Merchant).order_by(Merchant.canonical_name)).scalars())

    def upsert_alias(self, merchant_id: int, pattern: str, pattern_type: str = "contains", confidence: float = 1.0) -> None:
        pattern = pattern.strip()
        obj = self.s.execute(select(MerchantAlias).where(
            MerchantAlias.merchant_id == merchant_id,
            MerchantAlias.pattern == pattern,
            MerchantAlias.pattern_type == pattern_type
        )).scalar_one_or_none()
        if obj:
            obj.confidence = confidence
        else:
            self.s.add(MerchantAlias(merchant_id=merchant_id, pattern=pattern, pattern_type=pattern_type, confidence=confidence))
        self.s.commit()

    def list_aliases(self) -> list[MerchantAlias]:
        return list(self.s.execute(select(MerchantAlias)).scalars())

    def set_txn_merchant(self, txn_id: int, merchant_id: int | None) -> None:
        txn = self.s.get(Transaction, txn_id)
        if not txn:
            return
        txn.merchant_id = merchant_id
        self.s.commit()

    # queries
    def list_transactions(self, limit: int = 5000) -> list[Transaction]:
        return list(self.s.execute(select(Transaction).order_by(Transaction.posted_at.desc()).limit(limit)).scalars())

    def list_transactions_for_merchant(self, merchant_id: int, limit: int = 5000) -> list[Transaction]:
        return list(self.s.execute(
            select(Transaction).where(Transaction.merchant_id == merchant_id).order_by(Transaction.posted_at.desc()).limit(limit)
        ).scalars())

    # recurring / events
    def clear_recurring_and_events(self) -> None:
        self.s.execute(delete(Event))
        self.s.execute(delete(RecurringSeries))
        self.s.commit()

    def upsert_series(self, merchant_id: int, period_days: int, amount_median: float, amount_mad: float,
                     gap_median: float, gap_mad: float, confidence: float,
                     last_txn_id: int, next_expected_at: datetime, status: str = "active") -> int:
        self.s.execute(delete(RecurringSeries).where(RecurringSeries.merchant_id == merchant_id))
        rs = RecurringSeries(
            merchant_id=merchant_id,
            period_days=period_days,
            amount_median=amount_median,
            amount_mad=amount_mad,
            gap_median=gap_median,
            gap_mad=gap_mad,
            confidence=confidence,
            last_txn_id=last_txn_id,
            next_expected_at=next_expected_at,
            status=status,
        )
        self.s.add(rs)
        self.s.commit()
        return rs.id

    def list_series(self) -> list[RecurringSeries]:
        return list(self.s.execute(select(RecurringSeries).order_by(RecurringSeries.confidence.desc())).scalars())

    def add_event(self, type_: str, severity: str, title: str, evidence: dict,
                  merchant_id: int | None = None, series_id: int | None = None, txn_id: int | None = None) -> int:
        ev = Event(
            type=type_,
            severity=severity,
            title=title,
            merchant_id=merchant_id,
            series_id=series_id,
            txn_id=txn_id,
            evidence_json=self.encrypt_field(json.dumps(evidence, ensure_ascii=False)),
            is_dismissed=False,
        )
        self.s.add(ev)
        self.s.commit()
        return ev.id

    def list_events(self, include_dismissed: bool = False, limit: int = 200) -> list[Event]:
        q = select(Event).order_by(Event.created_at.desc()).limit(limit)
        if not include_dismissed:
            q = q.where(Event.is_dismissed == False)  # noqa: E712
        return list(self.s.execute(q).scalars())

    def dismiss_event(self, event_id: int, dismissed: bool = True) -> None:
        ev = self.s.get(Event, event_id)
        if not ev:
            return
        ev.is_dismissed = dismissed
        self.s.commit()

    def get_event_evidence(self, event_id: int) -> dict:
        ev = self.s.get(Event, event_id)
        if not ev:
            return {}
        try:
            return json.loads(self.decrypt_field(ev.evidence_json))
        except Exception:
            return {"error": "Could not decrypt/parse evidence"}

    # export helper
    def get_monthly_spend(self) -> list[dict]:
        rows = self.s.execute(
            select(func.strftime("%Y-%m", Transaction.posted_at).label("month"),
                   func.sum(Transaction.amount).label("total"))
            .group_by("month")
            .order_by("month")
        ).all()
        return [{"month": m, "total": float(t or 0.0)} for m, t in rows]

    # purge
    def delete_all_rows(self) -> None:
        for model in (Event, RecurringSeries, Transaction, MerchantAlias, Merchant, SourceFile, Setting):
            self.s.execute(delete(model))
        self.s.commit()
