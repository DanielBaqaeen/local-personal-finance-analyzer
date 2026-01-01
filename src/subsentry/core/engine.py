from __future__ import annotations

import logging
from datetime import datetime, timedelta

from rapidfuzz import fuzz, process

from subsentry.core.normalize import clean_merchant, canonical_hint
from subsentry.core.recurring import detect_recurring
from subsentry.core.stats import median
from subsentry.core.anomalies import merchant_anomalies, daily_spike_anomalies, burst_small_charges
from subsentry.db.repo import Repo

log = logging.getLogger(__name__)

def resolve_merchants(repo: Repo, fuzzy_threshold: int = 92) -> None:
    # Assign merchant_id to each transaction using:
    # - alias table patterns
    # - canonical hint rules
    # - fuzzy match to existing merchants
    aliases = repo.list_aliases()
    merchants = repo.list_merchants()
    merchant_names = [m.canonical_name for m in merchants]

    txns = repo.list_transactions(limit=200000)
    updated = 0

    for t in txns:
        raw = repo.decrypt_field(t.description_raw)
        cleaned = clean_merchant(raw)

        chosen = None

        # alias match
        for a in aliases:
            pat = a.pattern.upper()
            if a.pattern_type == "contains" and pat in cleaned:
                chosen = a.merchant_id
                break
            if a.pattern_type == "exact" and pat == cleaned:
                chosen = a.merchant_id
                break

        # hint / fuzzy / create
        if chosen is None:
            hint = canonical_hint(cleaned)
            for m in merchants:
                if m.canonical_name == hint:
                    chosen = m.id
                    break
            if chosen is None and merchant_names:
                match = process.extractOne(hint, merchant_names, scorer=fuzz.ratio)
                if match and match[1] >= fuzzy_threshold:
                    chosen = merchants[merchant_names.index(match[0])].id
            if chosen is None and cleaned:
                chosen = repo.get_or_create_merchant(hint).id

        if t.merchant_id != chosen:
            repo.set_txn_merchant(t.id, chosen)
            updated += 1

    log.info("merchant_resolution updated=%s", updated)

def recompute(repo: Repo) -> None:
    resolve_merchants(repo)
    repo.clear_recurring_and_events()

    series_rows = []
    merchants = repo.list_merchants()
    for m in merchants:
        tx = list(reversed(repo.list_transactions_for_merchant(m.id, limit=10000)))
        if len(tx) < 3:
            continue
        dates = [t.posted_at for t in tx]
        amounts = [t.amount for t in tx]
        res = detect_recurring(dates, amounts, min_points=3)
        if not res:
            continue
        last_txn_id = tx[-1].id
        series_id = repo.upsert_series(
            merchant_id=m.id,
            period_days=res.period_days,
            amount_median=res.amount_median,
            amount_mad=res.amount_mad,
            gap_median=res.gap_median,
            gap_mad=res.gap_mad,
            confidence=res.confidence,
            last_txn_id=last_txn_id,
            next_expected_at=res.next_expected_at,
            status="active",
        )
        series_rows.append((m, series_id, res, tx))

    _events_for_series(repo, series_rows)
    _events_for_anomalies(repo)
    log.info("recompute_done series=%s events=%s", len(series_rows), len(repo.list_events(include_dismissed=True, limit=10000)))

def _events_for_series(repo: Repo, series_rows):
    for (m, series_id, res, tx) in series_rows:
        # New subscription detected
        if len(tx) >= 3 and (datetime.utcnow() - tx[-1].posted_at) <= timedelta(days=90):
            repo.add_event(
                type_="new_subscription_detected",
                severity="info",
                title=f"Recurring charge detected: {m.canonical_name}",
                merchant_id=m.id,
                series_id=series_id,
                txn_id=tx[-1].id,
                evidence={
                    "merchant": m.canonical_name,
                    "period_days": res.period_days,
                    "confidence": res.confidence,
                    "last_n": [{"date": t.posted_at.isoformat(), "amount": t.amount} for t in tx[-6:]],
                },
            )

        # Price change
        if len(tx) >= 5:
            prev = [t.amount for t in tx[:-1][-6:]]
            base = median(prev)
            last = tx[-1].amount
            if abs(last - base) > max(0.10 * abs(base), 2.0):
                repo.add_event(
                    type_="price_change",
                    severity="warn",
                    title=f"Price change: {m.canonical_name} {base:.2f} → {last:.2f}",
                    merchant_id=m.id,
                    series_id=series_id,
                    txn_id=tx[-1].id,
                    evidence={
                        "baseline_median": base,
                        "last_amount": last,
                        "last_n": [{"date": t.posted_at.isoformat(), "amount": t.amount} for t in tx[-8:]],
                        "rule": "last amount deviates from rolling median",
                    },
                )

        # Duplicate billing
        for i in range(max(0, len(tx) - 10), len(tx) - 1):
            a = tx[i]
            b = tx[i + 1]
            if abs((b.posted_at - a.posted_at).total_seconds()) <= 36 * 3600 and abs(b.amount - a.amount) <= max(0.02 * abs(a.amount), 1.0):
                repo.add_event(
                    type_="possible_duplicate",
                    severity="warn",
                    title=f"Possible duplicate: {m.canonical_name} ({a.amount:.2f})",
                    merchant_id=m.id,
                    series_id=series_id,
                    txn_id=b.id,
                    evidence={
                        "a": {"date": a.posted_at.isoformat(), "amount": a.amount, "txn_id": a.id},
                        "b": {"date": b.posted_at.isoformat(), "amount": b.amount, "txn_id": b.id},
                        "rule": "close timestamps + similar amount",
                    },
                )

def _events_for_anomalies(repo: Repo):
    txns = repo.list_transactions(limit=200000)
    merchants = {m.id: m.canonical_name for m in repo.list_merchants()}
    rows = []
    for t in txns:
        rows.append({
            "txn_id": t.id,
            "posted_at": t.posted_at,
            "amount": t.amount,
            "merchant": merchants.get(t.merchant_id or -1, "UNKNOWN"),
        })

    for a in merchant_anomalies(rows, z_thresh=4.0)[:200]:
        repo.add_event(
            type_="spend_anomaly",
            severity="warn",
            title=f"Unusual charge: {a['amount']:.2f} at {a['merchant']}",
            txn_id=a["txn_id"],
            evidence=a,
        )

    for a in daily_spike_anomalies(rows, spike_z=4.0)[:200]:
        repo.add_event(
            type_="daily_spike",
            severity="info",
            title=f"Daily spend spike: {a['day']} total {a['total']:.2f}",
            evidence=a,
        )

    for a in burst_small_charges(rows)[:50]:
        repo.add_event(
            type_="burst_small_charges",
            severity="high",
            title=f"Burst of small charges ({a['count']} within window)",
            evidence=a,
        )
