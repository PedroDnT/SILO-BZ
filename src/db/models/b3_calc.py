"""
B3 CALC schema ORM model stubs.

B3Security: master record for a fixed-income security (debenture, CRA, CRI).
B3PricingSnapshot: one pricing snapshot per (security_code, snapshot_date).

Phase 4 adds JSONB payload columns, unique constraints, and the three-level
fallback chain (DB -> live upstream -> sample data).

Note: Sample data values from config.py are NEVER written to these tables (B3-03).
"""
from datetime import date
from typing import Optional

from sqlalchemy import Integer, String, Date, Text, Index
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class B3Security(Base):
    __tablename__ = "securities"
    __table_args__ = (
        Index("ix_b3_securities_code", "security_code"),
        {"schema": "b3_calc"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    security_code: Mapped[str] = mapped_column(String(20), nullable=False)
    security_type: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # debenture | cra | cri
    # Stub: Phase 4 migrates to JSONB for flexible B3 security attributes
    payload: Mapped[str] = mapped_column(Text, nullable=False, default="{}")


class B3PricingSnapshot(Base):
    __tablename__ = "pricing_snapshots"
    __table_args__ = (
        Index("ix_b3_pricing_code_date", "security_code", "snapshot_date"),
        {"schema": "b3_calc"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    security_code: Mapped[str] = mapped_column(String(20), nullable=False)
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    # Stub: Phase 4 migrates to JSONB for flexible pricing data
    payload: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
