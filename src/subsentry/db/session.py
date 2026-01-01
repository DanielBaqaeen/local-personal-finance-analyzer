from __future__ import annotations

from pathlib import Path
import sqlite3

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from subsentry.db.models import Base

def make_engine(db_path: Path):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return create_engine(f"sqlite:///{db_path}", future=True)

def _ensure_source_files_columns(db_path: Path) -> None:
    if not db_path.exists():
        return

    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='source_files'")
        if not cur.fetchone():
            return

        cur.execute("PRAGMA table_info(source_files)")
        existing = {row[1] for row in cur.fetchall()}  # row[1] is column name

        needed = {
            "period_start": "TEXT",
            "period_end": "TEXT",
            "statement_year": "INTEGER",
            "statement_month": "INTEGER",
            "statement_label": "TEXT",
        }
        for col, typ in needed.items():
            if col not in existing:
                cur.execute(f"ALTER TABLE source_files ADD COLUMN {col} {typ}")
        conn.commit()
    finally:
        conn.close()

def init_db(db_path: Path) -> None:
    engine = make_engine(db_path)
    Base.metadata.create_all(engine)
    _ensure_source_files_columns(db_path)

def make_session_factory(db_path: Path):
    engine = make_engine(db_path)
    # Ensure schema exists even if user runs a command that doesn't call init_db explicitly
    Base.metadata.create_all(engine)
    _ensure_source_files_columns(db_path)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
