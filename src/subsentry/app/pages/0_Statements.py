from __future__ import annotations

import tempfile
from pathlib import Path

import streamlit as st

from subsentry.app_config import load_config
from subsentry.logging_setup import setup_logging
from subsentry.db.session import init_db, make_session_factory
from subsentry.db.repo import Repo, EncryptionCtx
from subsentry.privacy.encryption import load_key
from subsentry.core.ingest import ingest_csv
from subsentry.core.engine import recompute

st.set_page_config(page_title="Statements", layout="wide")

cfg = load_config()
cfg.data_dir.mkdir(parents=True, exist_ok=True)
cfg.export_dir.mkdir(parents=True, exist_ok=True)
cfg.log_dir.mkdir(parents=True, exist_ok=True)
setup_logging(cfg.log_dir)
init_db(cfg.db_path)

SessionFactory = make_session_factory(cfg.db_path)


def _encryption_enabled() -> bool:
    with SessionFactory() as s:
        repo = Repo(s, EncryptionCtx(key=_encryption_key()))
        return (repo.get_setting("encryption_enabled") == "1") or bool(repo.get_setting("encryption_salt_b64"))

def _encryption_key():
    return st.session_state.get("encryption_key")


def get_repo():
    key = None
    if st.session_state.get("encryption_salt_b64") and st.session_state.get("passphrase"):
        key = load_key(st.session_state["passphrase"], st.session_state["encryption_salt_b64"]).key
    s = SessionFactory()
    return Repo(s, EncryptionCtx(key=key))

st.title("Statements")

if _encryption_enabled() and _encryption_key() is None:
    st.warning("Encryption is enabled but locked. Go to Home and unlock with your passphrase to import or recompute.")
    st.stop()


st.subheader("Maintenance")
st.markdown(
    "If you changed settings or imported/deleted statements and want to refresh derived outputs, run a recompute:"
)
if st.button("Recompute subscriptions, alerts, and insights", type="secondary"):
    r = get_repo()
    recompute(r)
    r.s.close()
    st.success("Recompute complete.")


st.subheader("Import statement CSVs")
st.markdown("You can import one or multiple statements at a time. Imports are tracked by detected period and `YYYY-MM` label")

uploads = st.file_uploader(
    "Choose one or more CSV files",
    type=["csv"],
    accept_multiple_files=True,
)

if uploads:
    if st.button(f"Import {len(uploads)} file(s)", type="primary"):
        total_inserted = 0
        total_skipped = 0
        imported_meta = []

        r = get_repo()
        for up in uploads:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
                tmp.write(up.getvalue())
                tmp_path = Path(tmp.name)

            rows = ingest_csv(tmp_path)

            if rows:
                dates = [r0.posted_at.date() for r0 in rows]
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

            sfid = r.create_source_file(
                up.name,
                rows_count=len(rows),
                period_start=period_start,
                period_end=period_end,
                statement_year=statement_year,
                statement_month=statement_month,
                statement_label=statement_label,
            )
            inserted, skipped = r.insert_transactions(sfid, [r1.__dict__ for r1 in rows])
            total_inserted += inserted
            total_skipped += skipped
            imported_meta.append((sfid, up.name, statement_label, inserted, skipped))

        # Recompute once after batch import?
        recompute(r)
        r.s.close()

        st.success(f"Imported {len(uploads)} file(s): {total_inserted} rows inserted, {total_skipped} duplicates skipped.")
        with st.expander("Import details"):
            for sfid, name, label, ins, skip in imported_meta:
                st.write(f"- Statement ID={sfid} | {label or 'N/A'} | {name} | inserted={ins}, skipped={skip}")
st.divider()

st.subheader("Imported statements")
r = get_repo()
sfs = r.list_source_files()
rows = []
for sf in sfs:
    rows.append({
        "ID": sf.id,
        "Label": sf.statement_label,
        "Period start": sf.period_start.isoformat() if sf.period_start else "",
        "Period end": sf.period_end.isoformat() if sf.period_end else "",
        "Rows": sf.rows_count,
        "Imported at": sf.imported_at.strftime("%Y-%m-%d %H:%M:%S") if sf.imported_at else "",
        "Filename": sf.original_filename,
    })

st.dataframe(rows, use_container_width=True, hide_index=True)

st.subheader("Delete a statement (and its transactions)")
col1, col2 = st.columns([1, 2])
with col1:
    stmt_id = st.number_input("Statement ID", min_value=1, step=1)
with col2:
    st.warning("This permanently removes the statement and all its transactions from the local database, then recomputes subscriptions & alerts")
if st.button("Delete statement", type="secondary"):
    tx_deleted, sf_deleted = r.delete_source_file(int(stmt_id))
    recompute(r)
    st.success(f"Deleted statement id={int(stmt_id)} (source_files={sf_deleted}, transactions={tx_deleted}). Recomputed.")

r.s.close()
