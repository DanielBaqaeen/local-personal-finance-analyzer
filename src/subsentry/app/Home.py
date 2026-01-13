from __future__ import annotations

import streamlit as st

from subsentry.app_config import load_config
from subsentry.db.session import make_session_factory
from subsentry.db.repo import Repo, EncryptionCtx
from subsentry.privacy.encryption import load_key, maybe_decrypt

st.set_page_config(page_title="Home", layout="wide")

cfg = load_config()
SessionFactory = make_session_factory(cfg.db_path)

st.title("Local Personal Finance Analyzer")
st.caption("Import CSV statements locally → detect patterns & changes → review alerts → export insights (no raw transaction export by default)")


# --- Encryption status / unlock ---
with SessionFactory() as s:
    repo = Repo(s, EncryptionCtx(key=None))
    enc_enabled = (repo.get_setting("encryption_enabled") == "1") or bool(repo.get_setting("encryption_salt_b64"))
    enc_salt = repo.get_setting("encryption_salt_b64")
    enc_check = repo.get_setting("encryption_check")

if enc_enabled:
    st.subheader("Encryption")
    if st.session_state.get("encryption_key") is None:
        st.warning("Encryption is enabled, but the app is locked. Enter your passphrase to unlock.")
        passphrase = st.text_input("Passphrase", type="password", key="unlock_passphrase")
        if st.button("Unlock", type="primary", disabled=not bool(passphrase)):
            try:
                if not enc_salt:
                    st.error("Encryption salt is missing. Disable and re-enable encryption in Settings.")
                else:
                    km = load_key(passphrase, enc_salt)
                    # Verify passphrase if a check value exists
                    if enc_check:
                        plain = maybe_decrypt(km.key, enc_check)
                        if plain != "subsentry-ok":
                            raise ValueError("Invalid passphrase")
                    st.session_state["encryption_key"] = km.key
                    st.success("Unlocked. Sensitive fields will decrypt and new data will be encrypted at rest.")
                    st.rerun()
            except Exception:
                st.error("Incorrect passphrase (or corrupted check value).")
    else:
        st.success("Encryption is unlocked.")
        if st.button("Lock now", type="secondary"):
            st.session_state.pop("encryption_key", None)
            st.rerun()
else:
    # keep this quiet; Settings controls enable/disable
    pass


st.subheader("How to use the app")
st.markdown(
    """**Recommended flow**
1) **Statements**: import one or more monthly CSV statements (it does not require an exact column header) but there needs to be few core fields
   that can be interpreted as:
    - a **date** (e.g., `Date`, `Posted`, `Transaction Date`)
    - a **description/merchant** string (e.g., `Description`, `Details`, `Merchant`)
    - an **amount** number (e.g., `Amount`, `Value`)

2) **Subscriptions**: inspect detected recurring charges, including estimated cadence, typical amount, last seen date, next expected charge, and confidence
3) **Alerts**: review price changes, frequency changes, duplicates, new subscriptions, and anomalies (with evidence)
4) **Insights**: trends across months/year, merchant composition, subscription burden, and a calendar heatmap
5) **Export**: export **insights only** (aggregates + alerts + subscription summaries; no raw transactions by default)
"""
)

st.subheader("How it runs")
st.markdown(
    """- **Local-only by default**: the app makes **no external network calls** unless you explicitly enable optional features
- **Local database**: imported transactions and derived results are stored in a **local SQLite DB**
- **Browser UI, local server**: Streamlit runs on localhost
"""
)

with st.expander("Where is my data stored?"):
    st.markdown(
        f"""**Default folders (relative to where you run the app):**
- Database: `{cfg.db_path}`
- Data dir: `{cfg.data_dir}`
- Logs: `{cfg.log_dir}` (redacted)
- Exports: `{cfg.export_dir}`

You can override these via environment variables (e.g., `SUBSENTRY_DATA_DIR`, `SUBSENTRY_LOG_DIR`, `SUBSENTRY_EXPORT_DIR`).  
"""
    )

st.subheader("Optional local-only features")
st.markdown(
    """- **Encryption at rest (optional passphrase):** encrypts sensitive fields (e.g., raw descriptions + alert evidence) in the local DB
- **Local LLM (Ollama):** generates natural-language explanations using localhost only (disabled by default)
- **MCP server:** exposes local tools (list alerts/subscriptions, export insights, etc.) to MCP-capable clients over localhost
"""
)

st.info("Start in **Statements** (left sidebar) to import your first CSV.")
