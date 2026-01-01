from __future__ import annotations

import pandas as pd
import streamlit as st
import plotly.express as px
from sqlalchemy import select

from subsentry.app_config import load_config
from subsentry.db.session import make_session_factory
from subsentry.db.repo import Repo, EncryptionCtx
from subsentry.db.models import Transaction
from subsentry.privacy.encryption import load_key

st.set_page_config(page_title="Subscriptions/ Periodic Patterns", layout="wide")
cfg = load_config()
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

st.title("Subscriptions/ Periodic Patterns")

if _encryption_enabled() and _encryption_key() is None:
    st.info("Encryption is enabled but locked. Some fields may appear as <encrypted>. Go to Home to unlock.")

r = get_repo()
merchants = {m.id: m.canonical_name for m in r.list_merchants()}

series = r.list_series()

rows = []
timeline_rows = []
for s in series:
    rows.append({
        "Merchant": merchants.get(s.merchant_id, "UNKNOWN"),
        "Frequency (days)": s.period_days,
        "Median amount": round(s.amount_median, 2),
        "Next expected": s.next_expected_at.isoformat(),
        "Confidence": round(s.confidence, 2),
        "Status": s.status,
    })

    last_tx = r.s.execute(select(Transaction.posted_at).where(Transaction.id == s.last_txn_id)).scalar()
    if last_tx is not None:
        timeline_rows.append({
            "Merchant": merchants.get(s.merchant_id, "UNKNOWN"),
            "Last charged": pd.to_datetime(last_tx),
            "Next expected": pd.to_datetime(s.next_expected_at),
            "Confidence": float(s.confidence),
            "Period (days)": int(s.period_days),
        })

st.dataframe(rows, use_container_width=True, hide_index=True)

st.subheader("Patterns Visualized")
st.caption("Bars show last charge → next expected date.")
if not timeline_rows:
    st.info("No recurring series detected yet.")
else:
    df_t = pd.DataFrame(timeline_rows).sort_values(["Confidence", "Merchant"], ascending=[False, True])
    fig = px.timeline(
        df_t,
        x_start="Last charged",
        x_end="Next expected",
        y="Merchant",
        color="Confidence",
        hover_data=["Period (days)"],
    )
    fig.update_yaxes(autorange="reversed")
    fig.update_layout(xaxis_title="", yaxis_title="")
    st.plotly_chart(fig, use_container_width=True)

r.s.close()
