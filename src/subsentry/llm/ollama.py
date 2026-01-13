from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import requests

log = logging.getLogger(__name__)

@dataclass(frozen=True)
class OllamaConfig:
    enabled: bool
    host: str
    model: str
    allow_network: bool
    timeout_s: int = 300
    num_predict: int = 256
    temperature: float = 0.2

def _assert_allowed(url: str, allow_network: bool) -> None:
    u = urlparse(url)
    host = (u.hostname or "").lower()
    if allow_network:
        return
    if host not in {"localhost", "127.0.0.1"}:
        raise RuntimeError(f"Network disabled: refusing to call {url}")

def chat_json(cfg: OllamaConfig, system: str, user: str, schema: dict | None = None) -> dict[str, Any]:
    if not cfg.enabled:
        raise RuntimeError("Local LLM disabled")
    endpoint = cfg.host.rstrip("/") + "/api/chat"
    _assert_allowed(endpoint, cfg.allow_network)

    payload: dict[str, Any] = {
        "model": cfg.model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "options": {
            "num_predict": cfg.num_predict,
            "temperature": cfg.temperature,
        },
    }
    if schema is not None:
        payload["format"] = schema

    try:
        r = requests.post(endpoint, json=payload, timeout=(10, cfg.timeout_s))
    except requests.exceptions.ReadTimeout as ex:
        raise RuntimeError(
            f"Local LLM timed out after {cfg.timeout_s}s. Try a smaller model or shorten output (Settings → LLM), then retry."
        ) from ex
    except requests.exceptions.ConnectTimeout as ex:
        raise RuntimeError("Could not connect to Ollama. Is it running on the configured host?") from ex
    r.raise_for_status()
    data = r.json()
    content = data.get("message", {}).get("content", "")
    try:
        return json.loads(content)
    except Exception:
        return {"raw": content}

def chat_text(cfg: OllamaConfig, system: str, user: str) -> str:
    res = chat_json(cfg, system=system, user=user, schema=None)
    return res.get("raw", json.dumps(res, ensure_ascii=False))
