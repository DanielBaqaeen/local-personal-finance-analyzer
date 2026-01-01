from __future__ import annotations

from typing import Any
from subsentry.llm.ollama import OllamaConfig, chat_json

INTENT_SCHEMA = {
  "type": "object",
  "properties": {
    "intent": {
      "type": "string",
      "enum": ["monthly_spend", "new_subscriptions", "recent_alerts", "unknown"]
    },
    "params": {"type": "object"}
  },
  "required": ["intent", "params"]
}

SYSTEM = (
  "You are an intent router for a local personal finance app. "
  "Return ONLY valid JSON matching the schema. "
  "Prefer privacy-preserving answers: aggregates over raw transactions."
)

def parse_intent(cfg: OllamaConfig, query: str) -> dict[str, Any]:
    user = "Classify the user's request into one of the supported intents.\n\nUser query: " + query
    return chat_json(cfg, system=SYSTEM, user=user, schema=INTENT_SCHEMA)
