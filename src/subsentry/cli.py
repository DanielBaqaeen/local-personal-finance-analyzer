from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path

import streamlit.web.cli as stcli

from subsentry.app_config import load_config
from subsentry.logging_setup import setup_logging
from subsentry.privacy.encryption import load_key
from subsentry.db.session import init_db, make_session_factory
from subsentry.db.repo import Repo, EncryptionCtx
from subsentry.core.ingest import ingest_csv
from subsentry.core.engine import recompute
from subsentry.core.reporting import export_insights
from subsentry.privacy.encryption import init_key
from subsentry.mcp_server import create_mcp

def _cli_encryption_ctx(cfg, SessionFactory):
    passphrase = os.environ.get("SUBSENTRY_PASSPHRASE") or os.environ.get("SUBSENTRY_ENCRYPTION_PASSPHRASE")
    with SessionFactory() as s:
        repo0 = Repo(s, EncryptionCtx(key=None))
        salt = repo0.get_setting("encryption_salt_b64")
        enabled = (repo0.get_setting("encryption_enabled") == "1") or bool(salt)
    if not enabled:
        return EncryptionCtx(key=None)
    if not passphrase or not salt:
        return EncryptionCtx(key=None)
    km = load_key(passphrase, salt)
    return EncryptionCtx(key=km.key)

def cmd_init(cfg):
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    cfg.export_dir.mkdir(parents=True, exist_ok=True)
    cfg.log_dir.mkdir(parents=True, exist_ok=True)
    setup_logging(cfg.log_dir)
    init_db(cfg.db_path)
    print(f"Initialized: {cfg.db_path}")

def cmd_import_many(cfg, csv_paths: list[str]):
    setup_logging(cfg.log_dir)
    init_db(cfg.db_path)
    SessionFactory = make_session_factory(cfg.db_path)

    total_inserted = 0
    total_skipped = 0
    imported = []

    with SessionFactory() as s:
        repo = Repo(s, EncryptionCtx(key=None))

        for csv_path in csv_paths:
            p = Path(csv_path).expanduser().resolve()
            rows = ingest_csv(p)

            # Infer statement period from transaction dates inside the CSV
            if rows:
                dates = [r.posted_at.date() for r in rows]
                period_start = min(dates)
                period_end = max(dates)
                statement_year = period_end.year
                statement_month = period_end.month
                statement_label = f"{statement_year:04d}-{statement_month:02d}"
            else:
                period_start = None
                period_end = None
                statement_year = None
                statement_month = None
                statement_label = None

            sfid = repo.create_source_file(
                p.name,
                rows_count=len(rows),
                period_start=period_start,
                period_end=period_end,
                statement_year=statement_year,
                statement_month=statement_month,
                statement_label=statement_label,
            )
            inserted, skipped = repo.insert_transactions(sfid, [r.__dict__ for r in rows])

            total_inserted += inserted
            total_skipped += skipped
            imported.append((sfid, p.name, statement_label, inserted, skipped))

        # recompute once
        recompute(repo)

    print(f"Imported {len(csv_paths)} file(s): {total_inserted} rows inserted (skipped {total_skipped} duplicates).")
    for sfid, name, label, ins, skip in imported:
        print(f"  - Statement ID={sfid} Period={label or 'N/A'} File={name} inserted={ins} skipped={skip}")


def cmd_import(cfg, csv_path: str):
    setup_logging(cfg.log_dir)
    init_db(cfg.db_path)
    SessionFactory = make_session_factory(cfg.db_path)
    p = Path(csv_path).expanduser().resolve()
    rows = ingest_csv(p)

    # Infer statement period from transaction dates inside the CSV
    if rows:
        dates = [r.posted_at.date() for r in rows]
        period_start = min(dates)
        period_end = max(dates)
        statement_year = period_end.year
        statement_month = period_end.month
        statement_label = f"{statement_year:04d}-{statement_month:02d}"
    else:
        period_start = None
        period_end = None
        statement_year = None
        statement_month = None
        statement_label = None

    with SessionFactory() as s:
        repo = Repo(s, EncryptionCtx(key=None))
        sfid = repo.create_source_file(
            p.name,
            rows_count=len(rows),
            period_start=period_start,
            period_end=period_end,
            statement_year=statement_year,
            statement_month=statement_month,
            statement_label=statement_label,
        )
        inserted, skipped = repo.insert_transactions(sfid, [r.__dict__ for r in rows])

    with SessionFactory() as s:
        repo = Repo(s, EncryptionCtx(key=None))
        recompute(repo)

    print(f"Imported {inserted} rows (skipped {skipped} duplicates). Statement ID={sfid} Period={statement_label or 'N/A'}")


def cmd_recompute(cfg):
    setup_logging(cfg.log_dir)
    SessionFactory = make_session_factory(cfg.db_path)
    with SessionFactory() as s:
        repo = Repo(s, EncryptionCtx(key=None))
        recompute(repo)
    print("Recompute complete.")

def cmd_export(cfg, fmt: str):
    setup_logging(cfg.log_dir)
    SessionFactory = make_session_factory(cfg.db_path)
    with SessionFactory() as s:
        repo = Repo(s, EncryptionCtx(key=None))
        out = export_insights(repo, cfg.export_dir, fmt=fmt)
    print(f"Exported: {out}")

def cmd_set_passphrase(cfg, passphrase: str):
    setup_logging(cfg.log_dir)
    init_db(cfg.db_path)
    km = init_key(passphrase)
    SessionFactory = make_session_factory(cfg.db_path)
    with SessionFactory() as s:
        repo = Repo(s, EncryptionCtx(key=None))
        repo.set_setting("encryption_salt_b64", km.salt_b64)
    print("Encryption enabled. Restart UI and enter passphrase to unlock.")

def cmd_purge(cfg):
    setup_logging(cfg.log_dir)
    if cfg.db_path.exists():
        cfg.db_path.unlink()
    for suf in ("-wal", "-shm"):
        p = cfg.db_path.with_name(cfg.db_path.name + suf)
        if p.exists():
            p.unlink()
    for d in (cfg.log_dir, cfg.export_dir):
        if d.exists():
            shutil.rmtree(d)
    print("Purged DB + logs + exports.")

def cmd_ui(cfg):
    import subprocess
    import sys
    from pathlib import Path

    app_path = Path(__file__).resolve().parent / "app" / "Home.py"

    try:
        subprocess.run([sys.executable, "-m", "streamlit", "run", str(app_path)], check=True)
    except KeyboardInterrupt:
        return



def cmd_mcp(cfg, transport: str, port: int, passphrase: str | None):
    setup_logging(cfg.log_dir)
    init_db(cfg.db_path)
    mcp = create_mcp(passphrase=passphrase)
    if transport == "streamable-http":
        os.environ["MCP_STREAMABLE_HTTP_HOST"] = "127.0.0.1"
        os.environ["MCP_STREAMABLE_HTTP_PORT"] = str(port)
        mcp.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")


def cmd_statements(cfg, as_json: bool = False):
    setup_logging(cfg.log_dir)
    init_db(cfg.db_path)
    SessionFactory = make_session_factory(cfg.db_path)
    with SessionFactory() as s:
        repo = Repo(s, EncryptionCtx(key=None))
        sfs = repo.list_source_files()

    rows = []
    for sf in sfs:
        rows.append({
            "id": sf.id,
            "label": sf.statement_label,
            "period_start": sf.period_start.isoformat() if sf.period_start else None,
            "period_end": sf.period_end.isoformat() if sf.period_end else None,
            "year": sf.statement_year,
            "month": sf.statement_month,
            "rows": sf.rows_count,
            "imported_at": sf.imported_at.strftime("%Y-%m-%d %H:%M:%S") if sf.imported_at else None,
            "filename": sf.original_filename,
        })

    if as_json:
        print(json.dumps(rows, indent=2))
        return

    # simple console table
    if not rows:
        print("No statements imported yet.")
        return

    headers = ["id", "label", "period_start", "period_end", "rows", "filename"]
    print(" | ".join(headers))
    print("-" * 120)
    for r in rows:
        print(f"{r['id']} | {r['label'] or ''} | {r['period_start'] or ''} | {r['period_end'] or ''} | {r['rows']} | {r['filename']}")


def cmd_delete_statement(cfg, statement_id: int):
    setup_logging(cfg.log_dir)
    init_db(cfg.db_path)
    SessionFactory = make_session_factory(cfg.db_path)
    with SessionFactory() as s:
        repo = Repo(s, EncryptionCtx(key=None))
        tx_deleted, sf_deleted = repo.delete_source_file(statement_id)
    with SessionFactory() as s:
        repo = Repo(s, EncryptionCtx(key=None))
        recompute(repo)

    print(f"Deleted statement id={statement_id} (source_files={sf_deleted}, transactions={tx_deleted}). Recomputed subscriptions & alerts.")

def main():
    cfg = load_config()
    ap = argparse.ArgumentParser(prog="subsentry")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init")
    p_import = sub.add_parser("import-csv")
    p_import.add_argument("path")
    sub.add_parser("recompute")
    p_export = sub.add_parser("export-insights")
    p_export.add_argument("--fmt", choices=["csv", "json"], default="csv")
    p_pass = sub.add_parser("set-passphrase")
    p_pass.add_argument("passphrase")
    sub.add_parser("purge")
    p_stmt = sub.add_parser("statements")
    p_stmt.add_argument("--json", action="store_true")
    p_del = sub.add_parser("delete-statement")
    p_del.add_argument("id", type=int)
    sub.add_parser("ui")
    p_mcp = sub.add_parser("mcp")
    p_mcp.add_argument("--transport", choices=["streamable-http", "stdio"], default="streamable-http")
    p_mcp.add_argument("--port", type=int, default=8765)
    p_mcp.add_argument("--passphrase", default=None)

    args = ap.parse_args()

    if args.cmd == "init":
        cmd_init(cfg)
    elif args.cmd == "import-csv":
        cmd_import(cfg, args.path)
    elif args.cmd == "recompute":
        cmd_recompute(cfg)
    elif args.cmd == "export-insights":
        cmd_export(cfg, args.fmt)
    elif args.cmd == "set-passphrase":
        cmd_set_passphrase(cfg, args.passphrase)
    elif args.cmd == "purge":
        cmd_purge(cfg)
    elif args.cmd == "statements":
        cmd_statements(cfg, args.json)
    elif args.cmd == "delete-statement":
        cmd_delete_statement(cfg, args.id)
    elif args.cmd == "ui":
        cmd_ui(cfg)
    elif args.cmd == "mcp":
        cmd_mcp(cfg, args.transport, args.port, args.passphrase)
    else:
        raise SystemExit("unknown command")

if __name__ == "__main__":
    main()
