from __future__ import annotations

from datetime import date
from calendar import monthrange

import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
from sqlalchemy import select

from subsentry.app_config import load_config
from subsentry.db.session import make_session_factory
from subsentry.db.repo import Repo, EncryptionCtx
from subsentry.db.models import Transaction
from subsentry.privacy.encryption import load_key
from subsentry.core.reporting import build_insights_payload, export_insights
from subsentry.llm.ollama import OllamaConfig
from subsentry.llm.intents import parse_intent
from subsentry.llm.explain import summarize_trends

st.set_page_config(page_title="Insights", layout="wide")
cfg = load_config()
SessionFactory = make_session_factory(cfg.db_path)


def _encryption_enabled() -> bool:
    with SessionFactory() as s:
        repo = Repo(s, EncryptionCtx(key=_encryption_key()))
        return (repo.get_setting("encryption_enabled") == "1") or bool(repo.get_setting("encryption_salt_b64"))

def _encryption_key():
    return st.session_state.get("encryption_key")

def _load_persisted_llm_settings(SessionFactory, cfg):
    """Load LLM settings from DB into session_state.

    Important: always sync on page load so changes in Settings are reflected
    immediately when navigating between pages (no manual refresh required).
    """
    with SessionFactory() as s:
        repo = Repo(s, EncryptionCtx(key=_encryption_key()))
        enabled_raw = repo.get_setting("ollama_enabled")
        host_raw = repo.get_setting("ollama_host")
        model_raw = repo.get_setting("ollama_model")

    # Overwrite so page reflects latest persisted settings.
    st.session_state["ollama_enabled"] = bool(int(enabled_raw)) if enabled_raw is not None else False
    st.session_state["ollama_host"] = (host_raw or "http://127.0.0.1:11434").strip()
    st.session_state["ollama_model"] = (model_raw or "qwen2.5:7b").strip()

    mode_raw = repo.get_setting("llm_mode")
    st.session_state["llm_mode"] = (mode_raw or "strict").strip().lower()


    with SessionFactory() as s:
        repo = Repo(s, EncryptionCtx(key=_encryption_key()))
        enabled_raw = repo.get_setting("ollama_enabled")
        host_raw = repo.get_setting("ollama_host")
        model_raw = repo.get_setting("ollama_model")

    if "ollama_enabled" not in st.session_state:
        if enabled_raw is not None:
            st.session_state["ollama_enabled"] = enabled_raw == "1"
        else:
            st.session_state["ollama_enabled"] = bool(getattr(cfg, "ollama_enabled", False))

    if "ollama_host" not in st.session_state:
        st.session_state["ollama_host"] = host_raw or getattr(cfg, "ollama_host", "http://127.0.0.1:11434")

    if "ollama_model" not in st.session_state:
        st.session_state["ollama_model"] = model_raw or getattr(cfg, "ollama_model", "qwen2.5:7b")
    st.session_state["_llm_settings_loaded"] = True

_load_persisted_llm_settings(SessionFactory, cfg)

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

    # Fallback: derive from transactions
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

st.title("Insights")

if _encryption_enabled() and _encryption_key() is None:
    st.info("Encryption is enabled but locked. Some fields may appear as <encrypted>. Go to Home to unlock.")

r = get_repo()

# base payload (tables + exports + LLM intents) 
payload = build_insights_payload(r)

# load transaction frame (no descriptions to preserve privacy)
rows = r.s.execute(select(Transaction.posted_at, Transaction.amount, Transaction.currency, Transaction.merchant_id)).all()
df = pd.DataFrame(rows, columns=["posted_at", "amount", "currency", "merchant_id"])
if not df.empty:
    df["posted_at"] = pd.to_datetime(df["posted_at"])
    df["month"] = df["posted_at"].dt.strftime("%Y-%m")
    df["date"] = df["posted_at"].dt.date
else:
    df["posted_at"] = pd.to_datetime(df.get("posted_at", []))

merchants = {m.id: m.canonical_name for m in r.list_merchants()}


# ---- Ask (optional local LLM) ----
st.subheader("Ask (optional local LLM)")
st.caption("Runs locally if enabled; does not call external services by default")

q = st.text_input(
    "Question",
    key="ask_q",
    placeholder="e.g., Why did spending spike in April? Any new recurring charges? Summarize 2025 so far.",
)

if not st.session_state.get("ollama_enabled", False):
    st.info("Enable Local LLM in Settings to use natural-language queries")
else:
    llm_cfg = OllamaConfig(
        enabled=True,
        host=st.session_state.get("ollama_host", "http://127.0.0.1:11434"),
        model=st.session_state.get("ollama_model", "qwen2.5:7b"),
        allow_network=bool(st.session_state.get("allow_network", False)),
        timeout_s=int(st.session_state.get("ollama_timeout_s", 300)),
        num_predict=int(st.session_state.get("ollama_num_predict", 256)),
    )

    mode = st.session_state.get("llm_mode", "strict")
    mode_label = "Analyst (interpretive)" if mode == "analyst" else "Strict (grounded)"
    st.caption(f"LLM mode: **{mode_label}** (change in Settings)")

    run = st.button("Answer", type="primary", disabled=not bool(q))

    if run:
        try:
            with st.spinner("Thinking..."):
                intent = parse_intent(llm_cfg, q)
            st.session_state["ask_intent"] = intent

            # Auto-generate narrative only in Analyst mode.
            if mode == "analyst":
                with st.spinner("Generating narrative..."):
                    narrative = summarize_trends(llm_cfg, q, payload, mode=mode)
                st.session_state["ask_narrative"] = narrative
            else:
                st.session_state.pop("ask_narrative", None)

        except Exception as ex:
            st.error(str(ex))

    # Narrative output (Analyst mode only)
    if st.session_state.get("ask_narrative"):
        st.write(st.session_state["ask_narrative"])

    # Always show underlying data/tables
    intent = st.session_state.get("ask_intent")
    if intent:
        st.markdown("### Underlying data used")
        if intent.get("intent") == "monthly_spend":
            st.dataframe(payload["monthly_spend"], use_container_width=True)
        elif intent.get("intent") == "recent_alerts":
            st.dataframe(payload["alerts"][:50], use_container_width=True)
        elif intent.get("intent") == "new_subscriptions":
            st.dataframe(payload["subscriptions"][:50], use_container_width=True)
        else:
            st.write("Unknown intent. Extend in subsentry/llm/intents.py")


st.divider()

# ---- Charts ----
st.subheader("Visuals")

if df.empty:
    st.info("No transactions yet. Import at least one statement to see visuals.")
else:
    df["year"] = df["posted_at"].dt.year.astype(int)

    available_years = get_available_years(r)

    years = available_years if available_years else sorted(df["year"].dropna().unique().tolist())
    year = year_select_shared(years, widget_key="ui_selected_year__insights", label="**Year**")

    df_year = df[df["year"] == int(year)].copy()
    if df_year.empty:
        st.info("No transactions found for the selected year.")

    currency = "USD"
    if not df_year.empty and "currency" in df_year.columns and not df_year["currency"].dropna().empty:
        currency = df_year["currency"].dropna().mode().iloc[0]


    st.markdown("### Year overview")
    yc1, yc2 = st.columns(2)

    # 1) Monthly spend trend (income/expense/net) - per selected year
    with yc1:
        st.markdown("**Monthly spend trend**")
        g = df_year.groupby("month", as_index=False).agg(
            income=("amount", lambda x: float(x[x > 0].sum())),
            expense=("amount", lambda x: float((-x[x < 0]).sum())),
        )
        g["net"] = g["income"] - g["expense"]
        g = g.sort_values("month")

        fig = px.line(g, x="month", y=["expense", "income", "net"], markers=True)
        fig.update_layout(legend_title_text="", xaxis_title="", yaxis_title=currency)
        fig.update_xaxes(type="category", categoryorder="category ascending", tickmode="array", tickvals=g["month"].tolist())
        st.plotly_chart(fig, use_container_width=True)

    # 2) Top merchants (grouped by normalized merchant) - per selected year
    with yc2:
        st.markdown("**Top merchants (expenses)**")
        col_m1, col_m2 = st.columns([1, 1])
        with col_m1:
            top_n = st.select_slider("Top N", options=[5, 8, 10, 12, 15], value=10, key="top_merchants_n")
        with col_m2:
            chart_kind = st.radio("View", options=["Bar", "Treemap"], horizontal=True, key="top_merchants_kind")

        df_exp = df_year[df_year["amount"] < 0].copy()

        # Using merchant_id -> canonical merchant name 
        df_exp["merchant"] = df_exp["merchant_id"].map(merchants).fillna("UNRESOLVED")

        agg = (
            df_exp.assign(expense=lambda d: -d["amount"])
            .groupby("merchant", as_index=False)["expense"]
            .sum()
            .sort_values("expense", ascending=False)
        )

        if agg.empty:
            st.info("No expense data available for this year selection.")
        else:
            top = agg.head(int(top_n)).copy()
            rest = agg.iloc[int(top_n):]["expense"].sum()
            if rest > 0:
                top = pd.concat(
                    [top, pd.DataFrame([{"merchant": "Other", "expense": float(rest)}])],
                    ignore_index=True,
                )

            if chart_kind == "Bar":
                fig2 = px.bar(
                    top.sort_values("expense", ascending=True),
                    x="expense",
                    y="merchant",
                    orientation="h",
                    labels={"expense": currency, "merchant": "Merchant"},
                )
                fig2.update_layout(legend_title_text="", xaxis_title=currency, yaxis_title="")
                st.plotly_chart(fig2, use_container_width=True)
            else:
                fig2 = px.treemap(top, path=["merchant"], values="expense")
                fig2.update_traces(root_color="lightgrey")
                st.plotly_chart(fig2, use_container_width=True)


    # 3) Subscription burden over time - per selected year, month-by-month ticks only
    st.markdown("**Subscription burden over time**")
    series = r.list_series()
    series_merchants = {s.merchant_id for s in series}
    df_sub = df_year[(df_year["merchant_id"].isin(series_merchants)) & (df_year["amount"] < 0)].copy()
    if df_sub.empty:
        st.info("No recurring charges detected yet.")
    else:
        sub_month = (
            df_sub.assign(subscription_spend=lambda d: -d["amount"])
            .groupby("month", as_index=False)["subscription_spend"]
            .sum()
            .sort_values("month")
        )
        fig3 = px.bar(sub_month, x="month", y="subscription_spend")
        fig3.update_layout(xaxis_title="", yaxis_title=currency)
        fig3.update_xaxes(type="category", categoryorder="category ascending", tickmode="array", tickvals=sub_month["month"].tolist())
        st.plotly_chart(fig3, use_container_width=True)


    months = sorted(df_year["month"].dropna().unique().tolist())
    month = st.selectbox("**Month**", months, index=len(months) - 1)
    df_month = df_year[df_year["month"] == month].copy()

    st.markdown("### Month overview")
    mc1, mc2 = st.columns([2,1])

    # 4) Calendar heatmap (spend intensity) - per selected month
    with mc1:
        st.markdown("**Calendar heatmap (daily expenses)**")

        if df_month.empty:
            st.info("No data in this month.")
        else:
            daily = (
                df_month[df_month["amount"] < 0]
                .assign(expense=lambda d: -d["amount"])
                .groupby("date", as_index=False)["expense"]
                .sum()
            )

            y, m = map(int, month.split("-"))
            first = date(y, m, 1)
            last = date(y, m, monthrange(y, m)[1])

            cal = pd.DataFrame({"date": pd.date_range(first, last, freq="D")})
            cal["weekday"] = cal["date"].dt.weekday  # Mon=0
            cal["week"] = ((cal["date"].dt.day + first.weekday() - 1) // 7).astype(int)

            # Keep consistent dtype for merge keys
            cal["date"] = pd.to_datetime(cal["date"])
            daily = daily.copy()
            daily["date"] = pd.to_datetime(daily["date"])

            cal = cal.merge(daily.rename(columns={"expense": "value"}), on="date", how="left")

            # 0 means "no expenses recorded that day" (still a real in-month day)
            cal["value"] = cal["value"].fillna(0.0)

            # Labels for each in-month day
            cal["day_label"] = cal["date"].dt.day.astype(str)
            cal["date_str"] = cal["date"].dt.strftime("%Y-%m-%d")

            weekdays = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

            pivot_val = (
                cal.pivot(index="week", columns="weekday", values="value")
                .reindex(columns=range(7))
            )
            pivot_day = (
                cal.pivot(index="week", columns="weekday", values="day_label")
                .reindex(columns=range(7))
            )
            pivot_date = (
                cal.pivot(index="week", columns="weekday", values="date_str")
                .reindex(columns=range(7))
            )

            # Only hide cells that are truly outside the month (no date),
            # but keep in-month zeros visible.
            in_month = pivot_date.notna()
            pivot_val = pivot_val.where(in_month)              # outside-month => NaN (transparent)
            pivot_day = pivot_day.where(in_month, "")          # outside-month => no day label

            fig4 = go.Figure(
                data=go.Heatmap(
                    z=pivot_val.values,
                    x=weekdays,
                    y=[f"Week {i+1}" for i in pivot_val.index],
                    text=pivot_day.values,
                    texttemplate="%{text}",
                    textfont=dict(size=12),
                    hoverongaps=False,
                    xgap=1,
                    ygap=1,
                    colorscale="RdYlGn_r",
                    customdata=pivot_date.values,
                    hovertemplate=(
                        "Date: %{customdata}<br>"
                        "Spend: %{z:.2f} " + currency +
                        "<extra></extra>"
                    ),
                )
            )
            fig4.update_layout(xaxis_title="", yaxis_title="", margin=dict(l=10, r=10, t=40, b=10))
            st.plotly_chart(fig4, use_container_width=True)


    with mc2:
        st.markdown("**Month summary**")
        if df_month.empty:
            st.write("—")
        else:
            income = float(df_month[df_month["amount"] > 0]["amount"].sum())
            expense = float((-df_month[df_month["amount"] < 0]["amount"]).sum())
            st.metric("Income", f"{income:,.2f} {currency}")
            st.metric("Expenses", f"{expense:,.2f} {currency}")
            st.metric("Net", f"{(income-expense):,.2f} {currency}")


st.divider()

# ---- Exports ----
st.subheader("Export")
fmt = st.selectbox("Format", ["csv", "json"], index=0)
if st.button("Export insights (no raw transactions)", type="primary"):
    path = export_insights(payload, cfg.export_dir, fmt=fmt)
    st.success(f"Exported to: {path}")

r.s.close()




