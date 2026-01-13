from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

from subsentry.core.stats import median, mad, robust_z

def merchant_anomalies(transactions: list[dict], z_thresh: float = 4.0) -> list[dict]:
    by_m = defaultdict(list)
    for t in transactions:
        by_m[t["merchant"]].append(t)

    out: list[dict] = []
    for m, rows in by_m.items():
        if len(rows) < 8:
            continue
        amounts = [abs(float(r["amount"])) for r in rows]
        med = median(amounts)
        m_mad = mad(amounts)
        for r in rows[:80]:
            z = robust_z(abs(float(r["amount"])), med, m_mad)
            if abs(z) >= z_thresh:
                out.append({
                    "type": "merchant_amount_anomaly",
                    "merchant": m,
                    "txn_id": r["txn_id"],
                    "amount": float(r["amount"]),
                    "z": float(z),
                    "baseline_median": med,
                    "baseline_mad": m_mad,
                })
    return out

def daily_spike_anomalies(transactions: list[dict], window_days: int = 60, spike_z: float = 4.0) -> list[dict]:
    by_day = defaultdict(float)
    for t in transactions:
        day = t["posted_at"].date().isoformat()
        by_day[day] += abs(float(t["amount"]))
    days = sorted(by_day.keys())
    if len(days) < 14:
        return []
    out = []
    values = [by_day[d] for d in days]
    for i in range(7, len(days)):
        start = max(0, i - window_days)
        hist = values[start:i]
        med = median(hist)
        m_mad = mad(hist)
        z = robust_z(values[i], med, m_mad)
        if z >= spike_z:
            out.append({
                "type": "daily_spike",
                "day": days[i],
                "total": values[i],
                "z": float(z),
                "baseline_median": med,
                "baseline_mad": m_mad,
            })
    return out

def burst_small_charges(transactions: list[dict], amount_max: float = 5.0, window_minutes: int = 30, count_min: int = 5) -> list[dict]:
    tx = sorted(transactions, key=lambda t: t["posted_at"])
    out = []
    j = 0
    for i in range(len(tx)):
        while tx[i]["posted_at"] - tx[j]["posted_at"] > timedelta(minutes=window_minutes):
            j += 1
            if j >= i:
                break
        window = tx[j:i+1]
        small = [t for t in window if abs(float(t["amount"])) <= amount_max]
        if len(small) >= count_min:
            out.append({
                "type": "burst_small_charges",
                "start": window[0]["posted_at"].isoformat(),
                "end": window[-1]["posted_at"].isoformat(),
                "count": len(small),
            })
            j = i + 1
    return out
