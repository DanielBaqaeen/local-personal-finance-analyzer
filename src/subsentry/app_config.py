from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

def _env_bool(name: str, default: bool = False) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "y", "on"}

@dataclass(frozen=True)
class AppConfig:
    data_dir: Path
    db_path: Path
    log_dir: Path
    export_dir: Path

    allow_network: bool

    ollama_enabled: bool
    ollama_host: str
    ollama_model: str

def load_config() -> AppConfig:
    data_dir = Path(os.environ.get("SUBSENTRY_DATA_DIR", "./data")).resolve()
    db_name = os.environ.get("SUBSENTRY_DB_NAME", "subsentry.sqlite3")
    log_dir = Path(os.environ.get("SUBSENTRY_LOG_DIR", "./logs")).resolve()
    export_dir = Path(os.environ.get("SUBSENTRY_EXPORT_DIR", "./exports")).resolve()

    allow_network = _env_bool("SUBSENTRY_ALLOW_NETWORK", False)

    ollama_enabled = _env_bool("SUBSENTRY_OLLAMA_ENABLED", False)
    ollama_host = os.environ.get("SUBSENTRY_OLLAMA_HOST", "http://localhost:11434")
    ollama_model = os.environ.get("SUBSENTRY_OLLAMA_MODEL", "qwen2.5:7b")

    return AppConfig(
        data_dir=data_dir,
        db_path=(data_dir / db_name),
        log_dir=log_dir,
        export_dir=export_dir,
        allow_network=allow_network,
        ollama_enabled=ollama_enabled,
        ollama_host=ollama_host,
        ollama_model=ollama_model,
    )
