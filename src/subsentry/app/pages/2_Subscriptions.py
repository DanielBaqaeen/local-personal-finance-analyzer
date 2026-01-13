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
from datetime import datetime

st.set_page_config(page_title="Subscriptions/ Recurring Charges", layout="wide")
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

YEAR_KEY = "ui_selected_year"

def get_available_years(r) -> list[int]:
    years = set()
    for sf in r.list_source_files():
        if getattr(sf, "period_start", None):
            years.add(int(sf.period_start.year))
        if getattr(sf, "period_end", None):
            years.add(int(sf.period_end.year))

    if years:
        return sorted(years)

    tx_years = r.s.execute(
        select(Transaction.posted_at)
        .where(Transaction.posted_at.is_not(None))
    ).scalars().all()
    for ts in tx_years:
        years.add(int(pd.to_datetime(ts).year))

    return sorted(years) if years else [int(pd.Timestamp.utcnow().year)]


def year_select(years: list[int], label="**Year**") -> int:
    years = sorted({int(y) for y in years}) or [int(pd.Timestamp.utcnow().year)]

    st.session_state.setdefault(YEAR_KEY, years[-1])

    if int(st.session_state[YEAR_KEY]) not in years:
        st.session_state[YEAR_KEY] = years[-1]

    st.selectbox(label, years, key=YEAR_KEY)
    return int(st.session_state[YEAR_KEY])

def year_select_shared(years: list[int], *, widget_key: str, label="**Year**") -> int:
    years = sorted({int(y) for y in years}) or [int(pd.Timestamp.utcnow().year)]

    # Ensure canonical exists + is valid
    canon = st.session_state.get(YEAR_KEY)
    if canon is None or int(canon) not in years:
        st.session_state[YEAR_KEY] = years[-1]
        canon = years[-1]
    else:
        canon = int(canon)

    # Ensure the page widget mirrors canonical
    if st.session_state.get(widget_key) is None or int(st.session_state.get(widget_key)) != canon:
        st.session_state[widget_key] = canon

    def _sync_to_canon():
        st.session_state[YEAR_KEY] = int(st.session_state[widget_key])

    st.selectbox(label, years, key=widget_key, on_change=_sync_to_canon)
    return int(st.session_state[YEAR_KEY])

st.title("Subscriptions/ Recurring Charges")

if _encryption_enabled() and _encryption_key() is None:
    st.info("Encryption is enabled but locked. Some fields may appear as <encrypted>. Go to Home to unlock.")

r = get_repo()
merchants = {m.id: m.canonical_name for m in r.list_merchants()}

# ---- Year selector (derive from imported statements, fallback to transactions) ----

years = get_available_years(r)
year = year_select_shared(years, widget_key="ui_selected_year__subs", label="**Year**")




series = r.list_series()

start = datetime(int(year), 1, 1)
end = datetime(int(year) + 1, 1, 1)

rows = []
timeline_rows = []

for s in series:
    tx = r.s.execute(
        select(Transaction.posted_at, Transaction.amount)
        .where(Transaction.merchant_id == s.merchant_id)
        .where(Transaction.posted_at >= start)
        .where(Transaction.posted_at < end)
        .order_by(Transaction.posted_at.asc())
    ).all()

    if not tx:
        continue

    dfm = pd.DataFrame(tx, columns=["posted_at", "amount"])
    dfm["posted_at"] = pd.to_datetime(dfm["posted_at"])

    # expenses only (so payroll doesn't confuse recurring patterns)
    dfm_exp = dfm[dfm["amount"] < 0].copy()
    if dfm_exp.empty:
        continue

    last_tx_dt = dfm_exp["posted_at"].max()
    next_dt = last_tx_dt + pd.Timedelta(days=int(s.period_days))

    med_amt = float((-dfm_exp["amount"]).median())

    rows.append({
        "Merchant": merchants.get(s.merchant_id, "UNKNOWN"),
        "Frequency (days)": int(s.period_days),
        "Median amount": round(med_amt, 2),
        "Last charged": last_tx_dt.strftime("%Y-%m-%d"),
        "Next expected": next_dt.strftime("%Y-%m-%d"),
        "Confidence": round(float(s.confidence), 2),
        "Status": s.status,
    })

    timeline_rows.append({
        "Merchant": merchants.get(s.merchant_id, "UNKNOWN"),
        "Last charged": last_tx_dt,
        "Next expected": next_dt,
        "Confidence": round(float(s.confidence), 2),
        "Period (days)": int(s.period_days),
    })

st.dataframe(rows, use_container_width=True, hide_index=True)

st.subheader("Patterns Visualized")
st.caption("Bars show last charge → next expected date (filtered by selected year).")

if not timeline_rows:
    st.info("No recurring charges detected for the selected year.")
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