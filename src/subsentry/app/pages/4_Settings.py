from __future__ import annotations

import shutil
import streamlit as st

from subsentry.app_config import load_config
from subsentry.db.session import make_session_factory
from subsentry.db.repo import Repo, EncryptionCtx
from subsentry.privacy.encryption import init_key, maybe_encrypt

st.set_page_config(page_title="Settings", layout="wide")
cfg = load_config()
SessionFactory = make_session_factory(cfg.db_path)


def _encryption_enabled() -> bool:
    with SessionFactory() as s:
        repo = Repo(s, EncryptionCtx(key=None))
        return (repo.get_setting("encryption_enabled") == "1") or bool(repo.get_setting("encryption_salt_b64"))

def _encryption_key():
    return st.session_state.get("encryption_key")



def _load_persisted_llm_settings(SessionFactory, cfg):
    """Sync persisted LLM settings into Streamlit session_state."""
    with SessionFactory() as s:
        repo = Repo(s, EncryptionCtx(key=None))
        enabled_raw = repo.get_setting("ollama_enabled")
        host_raw = repo.get_setting("ollama_host")
        model_raw = repo.get_setting("ollama_model")
        mode_raw = repo.get_setting("llm_mode")
        resp_raw = repo.get_setting("ollama_resp_len")
        np_raw = repo.get_setting("ollama_num_predict")
        to_raw = repo.get_setting("ollama_timeout_s")
        allow_raw = repo.get_setting("allow_network")

    
    if allow_raw is None:
        st.session_state["allow_network"] = bool(getattr(cfg, "allow_network", False))
    else:
        st.session_state["allow_network"] = (allow_raw == "1")

    enabled = (enabled_raw == "1") if enabled_raw is not None else bool(getattr(cfg, "ollama_enabled", False))
    host = (host_raw or getattr(cfg, "ollama_host", "http://127.0.0.1:11434")).strip()
    model = (model_raw or getattr(cfg, "ollama_model", "qwen2.5:7b")).strip()

    st.session_state["ollama_enabled"] = enabled
    st.session_state["ollama_host"] = host
    st.session_state["ollama_model"] = model
    st.session_state["llm_mode"] = (mode_raw or "strict").strip().lower()

    # Persist response length as label (Short/Medium/Long) so it doesn't reset to a default index.
    resp = (resp_raw or "").strip().title()
    if resp not in {"Short", "Medium", "Long"}:
        try:
            npv = int(np_raw) if np_raw is not None else 256
        except Exception:
            npv = 256
        resp = "Short" if npv <= 160 else ("Long" if npv >= 400 else "Medium")
    st.session_state["ollama_resp_len"] = resp
    st.session_state["ollama_num_predict"] = {"Short": 128, "Medium": 256, "Long": 512}[resp]

    try:
        st.session_state["ollama_timeout_s"] = int(to_raw) if to_raw is not None else 300
    except Exception:
        st.session_state["ollama_timeout_s"] = 300


def _save_llm_settings(SessionFactory):
    resp = str(st.session_state.get("ollama_resp_len", "Medium")).strip().title()
    if resp not in {"Short", "Medium", "Long"}:
        resp = "Medium"
    st.session_state["ollama_num_predict"] = {"Short": 128, "Medium": 256, "Long": 512}[resp]

    with SessionFactory() as s:
        repo = Repo(s, EncryptionCtx(key=None))
        repo.set_setting("ollama_enabled", "1" if st.session_state.get("ollama_enabled") else "0")
        repo.set_setting("ollama_host", str(st.session_state.get("ollama_host", "http://127.0.0.1:11434")))
        repo.set_setting("ollama_model", str(st.session_state.get("ollama_model", "qwen2.5:7b")))
        repo.set_setting("llm_mode", str(st.session_state.get("llm_mode", "strict")))
        repo.set_setting("ollama_resp_len", resp)
        repo.set_setting("ollama_num_predict", str(int(st.session_state.get("ollama_num_predict", 256))))
        repo.set_setting("ollama_timeout_s", str(int(st.session_state.get("ollama_timeout_s", 300))))
        repo.set_setting("allow_network", "1" if st.session_state.get("allow_network") else "0")


st.title("Settings")

_load_persisted_llm_settings(SessionFactory, cfg)

st.subheader("Network policy")
st.toggle(
    "Allow network calls",
    key="allow_network",
    on_change=_save_llm_settings,
    args=(SessionFactory,),
    help="Safety switch for the LLM integration.",
)
st.caption(
    "When OFF (default): the app will only allow a local Ollama host loopback address.\n"
    "When ON: the app will allow the Ollama host to be a non-local address."
)

st.subheader("Local LLM (Ollama)")


st.toggle("Enable Local LLM", key="ollama_enabled", on_change=_save_llm_settings, args=(SessionFactory,))
st.text_input("Ollama host", key="ollama_host", on_change=_save_llm_settings, args=(SessionFactory,))
st.text_input("Ollama model", key="ollama_model", on_change=_save_llm_settings, args=(SessionFactory,))

st.selectbox(
    "Response length",
    options=["Short", "Medium", "Long"],
    key="ollama_resp_len",
    on_change=_save_llm_settings,
    args=(SessionFactory,),
    help="Controls max generated tokens. If responses time out, pick Short or use a smaller model",
)
st.session_state["ollama_num_predict"] = {"Short": 128, "Medium": 256, "Long": 512}[st.session_state.get("ollama_resp_len", "Medium")]

st.number_input(
    "LLM timeout (seconds)",
    min_value=30,
    max_value=1800,
    step=30,
    key="ollama_timeout_s",
    on_change=_save_llm_settings,
    args=(SessionFactory,),
    help="Increase if your local model is slow. Decrease if you want faster failure",
)


st.selectbox(
    "LLM behavior mode",
    options=["strict", "analyst"],
    key="llm_mode",
    on_change=_save_llm_settings,
    args=(SessionFactory,),
    format_func=lambda v: "Strict (grounded)" if v == "strict" else "Analyst (interpretive)",
    help="Strict: only uses computed facts. Analyst: interprets trends and may form hypotheses (still grounded in your data)",
)


st.divider()
st.subheader("Encryption at rest")
with SessionFactory() as s:
    repo = Repo(s, EncryptionCtx(key=None))
    salt = repo.get_setting("encryption_salt_b64")

if salt:
    st.success("Encryption is enabled. Enter passphrase on Home to unlock")
else:
    st.info("Encryption is disabled. Enable to encrypt sensitive fields going forward")
    passphrase = st.text_input("New passphrase", type="password")
    if st.button("Enable encryption") and passphrase:
        km = init_key(passphrase)
        with SessionFactory() as s:
            repo = Repo(s, EncryptionCtx(key=None))
            repo.set_setting("encryption_salt_b64", km.salt_b64)
            repo.set_setting("encryption_enabled", "1")
            repo.set_setting("encryption_check", maybe_encrypt(km.key, "subsentry-ok"))
        st.success("Enabled. Go to Home and unlock with your passphrase")
        st.stop()



st.markdown("### Encrypt existing plaintext data (optional)")
st.caption("Encryption only applies to data written after enabling + unlocking. Use this once to encrypt older plaintext fields in-place")
if st.session_state.get("encryption_key") is None:
    st.info("Unlock on Home to encrypt existing data")
else:
    if st.button("Encrypt existing plaintext data now", type="primary"):
        with SessionFactory() as s:
            repo2 = Repo(s, EncryptionCtx(key=st.session_state.get("encryption_key")))
            tx_u, ev_u = repo2.encrypt_existing_plaintext()
        st.success(f"Encrypted {tx_u} transactions and {ev_u} alert evidence records.")

st.divider()
st.subheader("Danger zone")
if st.button("Delete ALL data (type DELETE to confirm)"):
    st.session_state["confirm_purge"] = True

if st.session_state.get("confirm_purge"):
    confirm = st.text_input("Confirm", placeholder="DELETE")
    if confirm.strip() == "DELETE":
        try:
            if cfg.db_path.exists():
                cfg.db_path.unlink()
            for suf in ("-wal", "-shm"):
                p = cfg.db_path.with_name(cfg.db_path.name + suf)
                if p.exists():
                    p.unlink()
            for d in (cfg.log_dir, cfg.export_dir):
                if d.exists():
                    shutil.rmtree(d)
        except Exception as ex:
            st.error(str(ex))
        st.success("Deleted DB + logs + exports")
