"""
BACEN schema ORM model stubs.

SGSObservation: one row per (series_code, obs_date) from BACEN SGS time series.
PTAXRate: one row per (currency_code, rate_datetime) from BACEN PTAX exchange rates.

These match the column types specified in BACEN-01 and BACEN-02.
Phase 2 adds unique constraints and upsert logic.
"""
from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy import Integer, String, Date, Numeric, Index
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class SGSObservation(Base):
    __tablename__ = "sgs_observations"
    __table_args__ = (
        Index("ix_bacen_sgs_series_date", "series_code", "obs_date"),
        {"schema": "bacen"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    series_code: Mapped[int] = mapped_column(Integer, nullable=False)
    obs_date: Mapped[date] = mapped_column(Date, nullable=False)
    # Nullable: some SGS series have missing observations
    value: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(precision=20, scale=8), nullable=True
    )


class PTAXRate(Base):
    __tablename__ = "ptax_rates"
    __table_args__ = (
        Index("ix_bacen_ptax_currency_date", "currency_code", "rate_datetime"),
        {"schema": "bacen"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False)
    rate_datetime: Mapped[date] = mapped_column(Date, nullable=False)
    bid: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(precision=20, scale=8), nullable=True
    )
    ask: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(precision=20, scale=8), nullable=True
    )
