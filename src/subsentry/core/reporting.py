from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path

from subsentry.db.repo import Repo

def build_insights_payload(repo: Repo) -> dict:
    monthly = repo.get_monthly_spend()
    subs = []
    merchants = {m.id: m.canonical_name for m in repo.list_merchants()}
    for s in repo.list_series():
        subs.append({
            "merchant": merchants.get(s.merchant_id, "UNKNOWN"),
            "period_days": s.period_days,
            "amount_median": s.amount_median,
            "confidence": s.confidence,
            "last_txn_id": s.last_txn_id,
            "next_expected_at": s.next_expected_at.isoformat(),
        })
    alerts = []
    for e in repo.list_events(include_dismissed=False, limit=500):
        alerts.append({
            "created_at": e.created_at.isoformat(),
            "type": e.type,
            "severity": e.severity,
            "title": e.title,
        })
    return {"monthly_spend": monthly, "subscriptions": subs, "alerts": alerts}

def export_insights(repo: Repo, out_dir: Path, fmt: str = "csv") -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    data = build_insights_payload(repo)

    if fmt.lower() == "json":
        path = out_dir / f"subsentry_insights_{ts}.json"
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    path = out_dir / f"subsentry_insights_{ts}.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["SECTION", "FIELD", "VALUE"])
        for r in data["monthly_spend"]:
            w.writerow(["monthly_spend", r["month"], r["total"]])
        for s in data["subscriptions"]:
            w.writerow(["subscription", s["merchant"], f"{s['period_days']}d | {s['amount_median']:.2f} | next {s['next_expected_at']} | conf {s['confidence']:.2f}"])
        for e in data["alerts"]:
            w.writerow(["alert", e["created_at"], f"{e['severity']} | {e['type']} | {e['title']}"])
    return path
