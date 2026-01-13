from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from mcp.server.fastmcp import FastMCP

from subsentry.app_config import load_config
from subsentry.db.session import init_db, make_session_factory
from subsentry.db.repo import Repo, EncryptionCtx
from subsentry.privacy.encryption import load_key
from subsentry.core.ingest import ingest_csv
from subsentry.core.engine import recompute
from subsentry.core.reporting import build_insights_payload, export_insights

log = logging.getLogger(__name__)

def _maybe_key(session, passphrase: Optional[str]) -> Optional[bytes]:
    if not passphrase:
        return None
    try:
        row = session.get_bind().execute("SELECT value FROM settings WHERE key='encryption_salt_b64'").fetchone()
        if not row:
            return None
        return load_key(passphrase, row[0]).key
    except Exception:
        return None

def create_mcp(passphrase: Optional[str] = None) -> FastMCP:
    cfg = load_config()
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    init_db(cfg.db_path)

    mcp = FastMCP("SubSentry", json_response=True)

    @mcp.tool()
    def list_subscriptions() -> dict:
        SessionFactory = make_session_factory(cfg.db_path)
        with SessionFactory() as s:
            repo = Repo(s, EncryptionCtx(key=_maybe_key(s, passphrase)))
            merchants = {m.id: m.canonical_name for m in repo.list_merchants()}
            subs = []
            for rs in repo.list_series():
                subs.append({
                    "merchant": merchants.get(rs.merchant_id, "UNKNOWN"),
                    "period_days": rs.period_days,
                    "amount_median": rs.amount_median,
                    "confidence": rs.confidence,
                    "next_expected_at": rs.next_expected_at.isoformat(),
                })
            return {"subscriptions": subs}

    @mcp.tool()
    def list_alerts(limit: int = 50) -> dict:
        SessionFactory = make_session_factory(cfg.db_path)
        with SessionFactory() as s:
            repo = Repo(s, EncryptionCtx(key=_maybe_key(s, passphrase)))
            out = []
            for e in repo.list_events(limit=limit):
                out.append({
                    "id": e.id,
                    "created_at": e.created_at.isoformat(),
                    "severity": e.severity,
                    "type": e.type,
                    "title": e.title,
                })
            return {"alerts": out}

    @mcp.tool()
    def explain_alert(alert_id: int) -> dict:
        SessionFactory = make_session_factory(cfg.db_path)
        with SessionFactory() as s:
            repo = Repo(s, EncryptionCtx(key=_maybe_key(s, passphrase)))
            return {"alert_id": alert_id, "evidence": repo.get_event_evidence(alert_id)}

    @mcp.tool()
    def import_statement_csv(path: str) -> dict:
        p = Path(path).expanduser().resolve()
        rows = ingest_csv(p)
        SessionFactory = make_session_factory(cfg.db_path)
        with SessionFactory() as s:
            repo = Repo(s, EncryptionCtx(key=_maybe_key(s, passphrase)))
            sfid = repo.create_source_file(p.name, rows_count=len(rows))
            inserted, skipped = repo.insert_transactions(sfid, [r.__dict__ for r in rows])

        with SessionFactory() as s2:
            repo2 = Repo(s2, EncryptionCtx(key=_maybe_key(s2, passphrase)))
            recompute(repo2)

        return {"imported": inserted, "skipped_duplicates": skipped}

    @mcp.tool()
    def export_insights_csv() -> dict:
        SessionFactory = make_session_factory(cfg.db_path)
        with SessionFactory() as s:
            repo = Repo(s, EncryptionCtx(key=_maybe_key(s, passphrase)))
            out_path = export_insights(repo, cfg.export_dir, fmt="csv")
        return {"export_path": str(out_path)}

    @mcp.tool()
    def purge_all_data(confirm: bool = False) -> dict:
        if not confirm:
            return {"ok": False, "message": "Set confirm=true to purge."}
        SessionFactory = make_session_factory(cfg.db_path)
        with SessionFactory() as s:
            repo = Repo(s, EncryptionCtx(key=_maybe_key(s, passphrase)))
            repo.delete_all_rows()
        return {"ok": True}

    @mcp.resource("subsentry://insights")
    def insights_resource() -> str:
        SessionFactory = make_session_factory(cfg.db_path)
        with SessionFactory() as s:
            repo = Repo(s, EncryptionCtx(key=_maybe_key(s, passphrase)))
            data = build_insights_payload(repo)
        return json.dumps(data, ensure_ascii=False, indent=2)

    return mcp
