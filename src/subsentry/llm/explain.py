from __future__ import annotations

import json
import re
from typing import Any

from subsentry.llm.ollama import OllamaConfig, chat_text

STRICT_SYSTEM = (
    "You are a careful assistant explaining outputs from a local personal finance app. "
    "Write in plain English. Be concise and specific. "
    "Do not output JSON, tables, code blocks, or schemas. Avoid curly-brace syntax entirely. "
    "Do not invent transactions or numbers; use only the provided evidence/payload."
)

ANALYST_SYSTEM = (
    "You are a thoughtful finance analyst for a local personal finance app. "
    "Write in clear, plain English. "
    "You may draw conclusions and highlight trends, BUT: "
    "(1) you must ground all numeric claims in the provided payload, "
    "(2) label speculation as hypotheses, "
    "(3) do not output JSON, code blocks, or schemas."
)



def _clean_text(s: str) -> str:
    s = (s or "").strip()
    # Strip code fences if the model includes them
    s = re.sub(r"```[a-zA-Z0-9]*\n", "", s)
    s = s.replace("```", "")
    # If it looks like JSON, nudge it to be plain text
    return s.strip()

def _pick_system(mode: str) -> str:
    mode = (mode or "strict").strip().lower()
    return ANALYST_SYSTEM if mode == "analyst" else STRICT_SYSTEM


def _shrink_evidence(evidence: dict) -> dict:
    """Reduce evidence payload so the model doesn't echo raw JSON."""
    if not isinstance(evidence, dict):
        return {}

    out: dict[str, Any] = {}
    for k in ["kind", "merchant", "merchant_id", "period_days", "amount", "prev_amount", "delta", "delta_pct", "threshold"]:
        if k in evidence:
            out[k] = evidence[k]

    # Keep only a small number of recent charge examples if present
    hist = evidence.get("history") or evidence.get("charges") or evidence.get("examples")
    if isinstance(hist, list) and hist:
        out["examples"] = hist[-6:]

    # Keep baseline stats if present
    stats = evidence.get("stats")
    if isinstance(stats, dict):
        out["stats"] = {k: stats.get(k) for k in ["median", "mad", "mean", "std", "n"] if k in stats}

    # Keep time context
    for k in ["as_of", "last_date", "next_expected_date", "confidence"]:
        if k in evidence:
            out[k] = evidence[k]

    return out


def explain_alert(cfg: OllamaConfig, alert_title: str, evidence: dict, mode: str = "strict") -> str:
    shrunk = _shrink_evidence(evidence or {})
    user = (
        "Explain this alert for a non-technical user.\n"
        "Output format (plain text only, no JSON, no tables):\n"
        "- 1 short headline sentence\n"
        "- 2–4 bullet points: what happened, why it was flagged, and any confidence/threshold if present\n"
        "- 1 suggested next step (what the user should check/do)\n\n"
        f"Alert title: {alert_title}\n\n"
        "Evidence (compact JSON):\n"
        + json.dumps(shrunk, ensure_ascii=False, indent=2)
    )
    return _clean_text(chat_text(cfg, system=_pick_system(mode), user=user))


def _shrink_payload(payload: dict) -> dict:
    """Compact payload so analyst mode can narrate trends without dumping giant tables."""
    if not isinstance(payload, dict):
        return {}

    out: dict[str, Any] = {}

    # Monthly spend table (limit rows)
    ms = payload.get("monthly_spend")
    if hasattr(ms, "to_dict"):
        try:
            rows = ms.tail(18).to_dict(orient="records") 
            out["monthly_spend"] = rows
        except Exception:
            pass

    # Alerts summary (limit)
    alerts = payload.get("alerts")
    if isinstance(alerts, list):
        out["alerts"] = alerts[:25]
    elif hasattr(alerts, "to_dict"):
        try:
            out["alerts"] = alerts.head(25).to_dict(orient="records") 
        except Exception:
            pass

    # Subscriptions / recurring charges summary (limit)
    subs = payload.get("subscriptions") or payload.get("recurring_charges")
    if isinstance(subs, list):
        out["recurring_charges"] = subs[:25]
    elif hasattr(subs, "to_dict"):
        try:
            out["recurring_charges"] = subs.head(25).to_dict(orient="records")  
        except Exception:
            pass

    cur = payload.get("currency")
    if cur:
        out["currency"] = cur

    return out


def summarize_trends(cfg: OllamaConfig, question: str, payload: dict, mode: str = "analyst") -> str:
    compact = _shrink_payload(payload or {})
    user = (
        "The user asked a question about their finances.\n"
        "Answer in plain English.\n"
        "If mode is STRICT: only restate what is directly supported by the payload.\n"
        "If mode is ANALYST: identify notable trends/drivers and label hypotheses clearly.\n"
        "Output format (plain text only, no JSON, no tables):\n"
        "- 1 paragraph summary\n"
        "- 3–6 bullet points: key findings (include numbers/dates if present)\n"
        "- Optional: 1–3 hypotheses (label as hypotheses)\n"
        "- 1 recommended next action\n\n"
        f"User question: {question}\n\n"
        "Payload (compact JSON):\n"
        + json.dumps(compact, ensure_ascii=False, indent=2)
    )
    return _clean_text(chat_text(cfg, system=_pick_system(mode), user=user))
