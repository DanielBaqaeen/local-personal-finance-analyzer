from __future__ import annotations

from datetime import datetime
from datetime import date
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, Date, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

class Base(DeclarativeBase):
    pass

class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)

class SourceFile(Base):
    __tablename__ = "source_files"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    imported_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    original_filename: Mapped[str] = mapped_column(String(255))
    rows_count: Mapped[int] = mapped_column(Integer, default=0)
    schema_version: Mapped[str] = mapped_column(String(32), default="v1")
    period_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    period_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    statement_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    statement_month: Mapped[int | None] = mapped_column(Integer, nullable=True)
    statement_label: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)

class Merchant(Base):
    __tablename__ = "merchants"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    canonical_name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class MerchantAlias(Base):
    __tablename__ = "merchant_aliases"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    merchant_id: Mapped[int] = mapped_column(ForeignKey("merchants.id"), index=True)
    pattern: Mapped[str] = mapped_column(String(255), index=True)
    pattern_type: Mapped[str] = mapped_column(String(32), default="contains")
    confidence: Mapped[float] = mapped_column(Float, default=1.0)

class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (UniqueConstraint("hash_dedupe", name="uq_transactions_hash"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    posted_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    amount: Mapped[float] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(8), default="")
    description_raw: Mapped[str] = mapped_column(Text)
    account_id: Mapped[str] = mapped_column(String(64), default="")
    source_file_id: Mapped[int] = mapped_column(ForeignKey("source_files.id"), index=True)
    merchant_id: Mapped[int | None] = mapped_column(ForeignKey("merchants.id"), nullable=True, index=True)
    hash_dedupe: Mapped[str] = mapped_column(String(64), index=True)

class RecurringSeries(Base):
    __tablename__ = "recurring_series"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    merchant_id: Mapped[int] = mapped_column(ForeignKey("merchants.id"), index=True)
    period_days: Mapped[int] = mapped_column(Integer)
    amount_median: Mapped[float] = mapped_column(Float)
    amount_mad: Mapped[float] = mapped_column(Float)
    gap_median: Mapped[float] = mapped_column(Float)
    gap_mad: Mapped[float] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float)
    last_txn_id: Mapped[int] = mapped_column(ForeignKey("transactions.id"))
    next_expected_at: Mapped[datetime] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(32), default="active")

class Event(Base):
    __tablename__ = "events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    type: Mapped[str] = mapped_column(String(64), index=True)
    severity: Mapped[str] = mapped_column(String(16), default="info")
    title: Mapped[str] = mapped_column(String(255))
    merchant_id: Mapped[int | None] = mapped_column(ForeignKey("merchants.id"), nullable=True, index=True)
    series_id: Mapped[int | None] = mapped_column(ForeignKey("recurring_series.id"), nullable=True, index=True)
    txn_id: Mapped[int | None] = mapped_column(ForeignKey("transactions.id"), nullable=True, index=True)
    evidence_json: Mapped[str] = mapped_column(Text, default="{}")
    is_dismissed: Mapped[bool] = mapped_column(Boolean, default=False)
