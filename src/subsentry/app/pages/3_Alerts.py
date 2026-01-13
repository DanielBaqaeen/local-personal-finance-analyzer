from __future__ import annotations

import streamlit as st

from subsentry.app_config import load_config
from subsentry.db.session import make_session_factory
from subsentry.db.repo import Repo, EncryptionCtx
from subsentry.privacy.encryption import load_key
from subsentry.llm.ollama import OllamaConfig
from subsentry.llm.explain import explain_alert as llm_explain

st.set_page_config(page_title="Alerts", layout="wide")
cfg = load_config()
SessionFactory = make_session_factory(cfg.db_path)


def _encryption_enabled() -> bool:
    with SessionFactory() as s:
        repo = Repo(s, EncryptionCtx(key=_encryption_key()))
        return (repo.get_setting("encryption_enabled") == "1") or bool(repo.get_setting("encryption_salt_b64"))

def _encryption_key():
    return st.session_state.get("encryption_key")

def _load_persisted_llm_settings(SessionFactory, cfg):
    with SessionFactory() as s:
        repo = Repo(s, EncryptionCtx(key=_encryption_key()))
        enabled_raw = repo.get_setting("ollama_enabled")
        host_raw = repo.get_setting("ollama_host")
        model_raw = repo.get_setting("ollama_model")
        mode_raw = repo.get_setting("llm_mode")
        np_raw = repo.get_setting("ollama_num_predict")
        to_raw = repo.get_setting("ollama_timeout_s")

    # Overwrite so page reflects latest persisted settings
    st.session_state["ollama_enabled"] = bool(int(enabled_raw)) if enabled_raw is not None else False
    st.session_state["ollama_host"] = (host_raw or "http://127.0.0.1:11434").strip()
    st.session_state["ollama_model"] = (model_raw or "qwen2.5:7b").strip()

    st.session_state["llm_mode"] = (mode_raw or "strict").strip().lower()
    st.session_state["ollama_num_predict"] = int(np_raw) if (np_raw and str(np_raw).isdigit()) else 256
    st.session_state["ollama_timeout_s"] = int(to_raw) if (to_raw and str(to_raw).isdigit()) else 300


    with SessionFactory() as s:
        repo = Repo(s, EncryptionCtx(key=_encryption_key()))
        enabled_raw = repo.get_setting("ollama_enabled")
        host_raw = repo.get_setting("ollama_host")
        model_raw = repo.get_setting("ollama_model")
        mode_raw = repo.get_setting("llm_mode")
        np_raw = repo.get_setting("ollama_num_predict")
        to_raw = repo.get_setting("ollama_timeout_s")

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

st.title("Alerts")

if _encryption_enabled() and _encryption_key() is None:
    st.info("Encryption is enabled but locked. Some fields may appear as <encrypted>. Go to Home to unlock.")

r = get_repo()
events = r.list_events(limit=300)

st.subheader("Filters")
severity_options = ["info", "warn", "high"]
selected = st.multiselect("Severity", severity_options, default=severity_options, help="Filter alerts by severity.")
if selected:
    events = [e for e in events if (e.severity or "info") in set(selected)]
else:
    events = []  # nothing selected -> show nothing

st.divider()

if not events:
    st.info("No alerts to show for the current filter.")
else:
    for e in events:
        with st.expander(f"[{(e.severity or 'info').upper()}] {e.title}"):
            cols = st.columns([1, 3])
            with cols[0]:
                if st.button("Dismiss", key=f"d_{e.id}"):
                    r.dismiss_event(e.id, True)
                    st.rerun()
            with cols[1]:
                st.caption(f"type: `{e.type}`  •  id: `{e.id}`")

            evidence = r.get_event_evidence(e.id)
            st.json(evidence)

            if st.session_state.get("ollama_enabled", False):
                if st.button("Explain with local LLM", key=f"x_{e.id}"):
                    llm_cfg = OllamaConfig(
                        enabled=True,
                        host=st.session_state.get("ollama_host", "http://localhost:11434"),
                        model=st.session_state.get("ollama_model", "qwen2.5:7b"),
                        allow_network=bool(st.session_state.get("allow_network", False)),
                    )
                    try:
                        with st.spinner("Generating explanation..."):
                            ans = llm_explain(llm_cfg, e.title, evidence, mode=st.session_state.get('llm_mode','strict'))
                        st.write(ans)
                    except Exception as ex:
                        st.error(str(ex))

r.s.close()
