"""
CVM schema ORM model stubs.

CVMRecord: stores one document row per CVM CSV record.
- entity + doc_type: identifies the CVM dataset (e.g., FIDC + mensal)
- cnpj_key: fund CNPJ (14 digits, no punctuation) — indexed for fast lookup
- competence_date: the reporting period date
- payload: JSONB column (added in Phase 3; Text stub here for migration baseline)

This stub creates the cvm.records table. Phase 3 will:
  - Change payload from Text to JSONB
  - Add a unique constraint on (entity, doc_type, cnpj_key, competence_date)
  - Add cvm_ingest_log table
"""
from datetime import date
from typing import Optional

from sqlalchemy import Integer, String, Date, Text, Index
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class CVMRecord(Base):
    __tablename__ = "records"
    __table_args__ = (
        Index("ix_cvm_records_cnpj_key", "cnpj_key"),
        Index("ix_cvm_records_entity_doc_type", "entity", "doc_type"),
        {"schema": "cvm"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity: Mapped[str] = mapped_column(String(20), nullable=False)
    doc_type: Mapped[str] = mapped_column(String(50), nullable=False)
    cnpj_key: Mapped[str] = mapped_column(String(18), nullable=False)
    competence_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    # Stub: Phase 3 migrates this to JSONB for flexible CVM schemas
    payload: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
