"""
CVM data ingestor — downloads all entity/doc_type combinations and persists
to Supabase tables: cvm_cadastral, cvm_mensal, cvm_periodic, cvm_securit_emissions.

Reuses CVMCreditDataService for fetch/parse/cache logic.
"""

import asyncio
import logging
import re
import sys
import os
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

# Allow running from repo root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.cvm_api.services import CVMCreditDataService
from src.ingestor.supabase_client import get_supabase_client, upsert_rows

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Entity / doc-type matrix
# ---------------------------------------------------------------------------

CADASTRAL_ENTITIES: List[str] = ["fidc", "fip", "fiagro"]

MENSAL_ENTITIES: List[str] = ["fidc", "fiagro"]

PERIODIC_CONFIGS: List[Tuple[str, str]] = [
    ("fidc",   "trimestral"),
    ("fidc",   "anual"),
    ("fip",    "inf_trimestral"),
    ("fip",    "inf_quadrimestral"),
    ("fip",    "dfin"),
    ("fiagro", "trimestral"),
    ("fiagro", "anual"),
]

SECURIT_TYPES: List[str] = [
    "cra_mensal", "cri_mensal", "ots_mensal", "lca_mensal", "lci_mensal"
]

# Large page size for ingestion (max supported)
_PAGE_SIZE = 5000


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize_cnpj(raw: str) -> str:
    """Strip non-digit characters from a CNPJ string."""
    return re.sub(r"\D", "", str(raw)) if raw else ""


def _find_field(row: Dict[str, Any], *candidates: str) -> Optional[str]:
    """Return the value of the first matching key (case-insensitive)."""
    row_lower = {k.lower(): v for k, v in row.items()}
    for c in candidates:
        v = row_lower.get(c.lower())
        if v is not None:
            return str(v) if v != "" else None
    return None


def _find_cnpj_field(row: Dict[str, Any], prefer_suffix: str = "fundo") -> Optional[str]:
    """Detect the CNPJ column regardless of entity-specific naming."""
    for k, v in row.items():
        if "cnpj" in k.lower() and prefer_suffix.lower() in k.lower():
            return str(v) if v else None
    for k, v in row.items():
        if "cnpj" in k.lower():
            return str(v) if v else None
    return None


def _find_inadimpl(row: Dict[str, Any]) -> Optional[str]:
    for k, v in row.items():
        if "inadimpl" in k.lower() or "delinq" in k.lower():
            return str(v) if v else None
    return None


# ---------------------------------------------------------------------------
# Ingestor class
# ---------------------------------------------------------------------------

class CVMIngestor:
    """
    Downloads CVM data via CVMCreditDataService and persists to Supabase.

    Example usage::

        ingestor = CVMIngestor()
        await ingestor.backfill(start_year=2019)
        # or incremental:
        await ingestor.daily_update()
    """

    def __init__(self) -> None:
        self._service = CVMCreditDataService()
        self._supabase = get_supabase_client()

    # ------------------------------------------------------------------
    # Cadastral (yearly CSV)
    # ------------------------------------------------------------------

    async def ingest_cadastral(self, entity: str, year: int) -> int:
        """Download and upsert the cadastral CSV for one entity/year."""
        logger.info("Cadastral: entity=%s year=%d", entity, year)
        rows_inserted = 0
        page = 1
        while True:
            try:
                resp = await self._service.get_data(
                    entity=entity,
                    doc_type="cadastral",
                    year=year,
                    month=None,
                    page=page,
                    page_size=_PAGE_SIZE,
                )
            except Exception as exc:
                logger.warning("Cadastral fetch failed entity=%s year=%d page=%d: %s",
                               entity, year, page, exc)
                break

            if not resp.data:
                break

            records: List[Dict[str, Any]] = []
            for row in resp.data:
                cnpj_raw = _find_cnpj_field(row, prefer_suffix="fundo")
                cnpj = _normalize_cnpj(cnpj_raw) if cnpj_raw else ""
                records.append({
                    "entity":       entity,
                    "year":         year,
                    "cnpj":         cnpj,
                    "denom_social": _find_field(row, "DENOM_SOCIAL", "NM_FUNDO"),
                    "dt_reg":       _find_field(row, "DT_REG", "DT_CONST"),
                    "dt_cancel":    _find_field(row, "DT_CANCEL", "DT_ENCERRAMENTO"),
                    "sit":          _find_field(row, "SIT", "SIT_FUNDO"),
                    "tp_fundo":     _find_field(row, "TP_FUNDO", "CLASSE", "CATEG_FUNDO"),
                    "raw":          row,
                })

            n = upsert_rows(
                self._supabase, "cvm_cadastral", records,
                conflict_columns="entity,cnpj,year"
            )
            rows_inserted += n
            logger.debug("  page=%d upserted=%d", page, n)

            if not resp.pagination.has_next:
                break
            page += 1

        logger.info("Cadastral done: entity=%s year=%d total=%d", entity, year, rows_inserted)
        return rows_inserted

    # ------------------------------------------------------------------
    # Mensal (monthly ZIP)
    # ------------------------------------------------------------------

    async def ingest_mensal(self, entity: str, year: int, month: int) -> int:
        """Download and upsert one month of mensal data."""
        logger.info("Mensal: entity=%s year=%d month=%02d", entity, year, month)
        rows_inserted = 0
        page = 1
        while True:
            try:
                resp = await self._service.get_data(
                    entity=entity,
                    doc_type="mensal",
                    year=year,
                    month=month,
                    page=page,
                    page_size=_PAGE_SIZE,
                )
            except Exception as exc:
                logger.warning("Mensal fetch failed entity=%s %d-%02d page=%d: %s",
                               entity, year, month, page, exc)
                break

            if not resp.data:
                break

            records: List[Dict[str, Any]] = []
            for row in resp.data:
                cnpj_raw = _find_cnpj_field(row, prefer_suffix="fundo")
                cnpj = _normalize_cnpj(cnpj_raw) if cnpj_raw else ""
                period = _find_field(row, "DT_COMPTC") or f"{year}-{month:02d}-01"
                records.append({
                    "entity":       entity,
                    "cnpj":         cnpj,
                    "period":       period,
                    "vl_total":     _find_field(row, "VL_TOTAL", "VL_CARTEIRA_TOTAL"),
                    "vl_quota":     _find_field(row, "VL_QUOTA"),
                    "vl_patrim_liq": _find_field(row, "VL_PATRIM_LIQ"),
                    "vl_inadimpl":  _find_inadimpl(row),
                    "nr_cotst":     _find_field(row, "NR_COTST"),
                    "raw":          row,
                })

            n = upsert_rows(
                self._supabase, "cvm_mensal", records,
                conflict_columns="entity,cnpj,period"
            )
            rows_inserted += n

            if not resp.pagination.has_next:
                break
            page += 1

        logger.info("Mensal done: entity=%s %d-%02d total=%d", entity, year, month, rows_inserted)
        return rows_inserted

    # ------------------------------------------------------------------
    # Periodic (trimestral / anual / dfin / etc.)
    # ------------------------------------------------------------------

    async def ingest_periodic(self, entity: str, doc_type: str, year: int) -> int:
        """Download and insert one periodic (non-monthly) dataset."""
        logger.info("Periodic: entity=%s doc_type=%s year=%d", entity, doc_type, year)
        rows_inserted = 0
        page = 1
        while True:
            try:
                resp = await self._service.get_data(
                    entity=entity,
                    doc_type=doc_type,
                    year=year,
                    month=None,
                    page=page,
                    page_size=_PAGE_SIZE,
                )
            except Exception as exc:
                logger.warning("Periodic fetch failed %s/%s %d page=%d: %s",
                               entity, doc_type, year, page, exc)
                break

            if not resp.data:
                break

            records: List[Dict[str, Any]] = []
            for row in resp.data:
                cnpj_raw = _find_cnpj_field(row, prefer_suffix="fundo")
                cnpj = _normalize_cnpj(cnpj_raw) if cnpj_raw else None
                records.append({
                    "entity":   entity,
                    "doc_type": doc_type,
                    "year":     year,
                    "cnpj":     cnpj,
                    "raw":      row,
                })

            n = upsert_rows(self._supabase, "cvm_periodic", records,
                            conflict_columns="entity,doc_type,year,cnpj")
            rows_inserted += n

            if not resp.pagination.has_next:
                break
            page += 1

        logger.info("Periodic done: %s/%s %d total=%d", entity, doc_type, year, rows_inserted)
        return rows_inserted

    # ------------------------------------------------------------------
    # SECURIT emissions (yearly ZIP → all months)
    # ------------------------------------------------------------------

    async def ingest_securit(self, instrument_type: str, year: int) -> int:
        """Download and insert all SECURIT emission records for one instrument/year."""
        logger.info("SECURIT: type=%s year=%d", instrument_type, year)
        rows_inserted = 0
        page = 1
        while True:
            try:
                resp = await self._service.get_data(
                    entity="securit",
                    doc_type=instrument_type,
                    year=year,
                    month=None,
                    page=page,
                    page_size=_PAGE_SIZE,
                )
            except Exception as exc:
                logger.warning("SECURIT fetch failed type=%s year=%d page=%d: %s",
                               instrument_type, year, page, exc)
                break

            if not resp.data:
                break

            records: List[Dict[str, Any]] = []
            for row in resp.data:
                cnpj_raw = _find_cnpj_field(row, prefer_suffix="securit")
                cnpj = _normalize_cnpj(cnpj_raw) if cnpj_raw else None

                unit_price = (
                    _find_field(row, "VL_UNIT", "PU_EMISSAO", "VL_PU_EMISSAO")
                )
                records.append({
                    "instrument_type": instrument_type,
                    "year":            year,
                    "cnpj_securit":    cnpj,
                    "dt_emissao":      _find_field(row, "DT_EMISSAO"),
                    "dt_vencto":       _find_field(row, "DT_VENCTO", "DT_VENCIMENTO"),
                    "vl_emissao":      _find_field(row, "VL_EMISSAO"),
                    "vl_unit":         unit_price,
                    "qt_titulos":      _find_field(row, "QT_TITULOS"),
                    "vl_total":        _find_field(row, "VL_TOTAL"),
                    "tp_ativo":        _find_field(row, "TP_ATIVO"),
                    "raw":             row,
                })

            n = upsert_rows(self._supabase, "cvm_securit_emissions", records,
                            conflict_columns="instrument_type,year,cnpj_securit,dt_emissao,dt_vencto,vl_emissao")
            rows_inserted += n

            if not resp.pagination.has_next:
                break
            page += 1

        logger.info("SECURIT done: type=%s year=%d total=%d", instrument_type, year, rows_inserted)
        return rows_inserted

    # ------------------------------------------------------------------
    # Orchestrated runs
    # ------------------------------------------------------------------

    async def backfill(
        self,
        start_year: int = 2019,
        end_year: Optional[int] = None,
        entity_filter: Optional[str] = None,
    ) -> Dict[str, int]:
        """
        Full historical backfill for all entities from start_year to today.

        Args:
            start_year:    First year to download (default 2019).
            end_year:      Last year (inclusive). Defaults to current year.
            entity_filter: If set, only process this entity (fidc|fip|fiagro|securit).

        Returns:
            Dict of table → rows_inserted.
        """
        today = date.today()
        if end_year is None:
            end_year = today.year

        totals: Dict[str, int] = {
            "cvm_cadastral":         0,
            "cvm_mensal":            0,
            "cvm_periodic":          0,
            "cvm_securit_emissions": 0,
        }

        years = list(range(start_year, end_year + 1))

        # -- Cadastral (one CSV per year per entity) ----------------------
        cad_tasks = []
        for entity in CADASTRAL_ENTITIES:
            if entity_filter and entity_filter != entity:
                continue
            for year in years:
                cad_tasks.append(self.ingest_cadastral(entity, year))

        if cad_tasks:
            results = await asyncio.gather(*cad_tasks, return_exceptions=True)
            for r in results:
                if isinstance(r, int):
                    totals["cvm_cadastral"] += r
                else:
                    logger.error("Cadastral task error: %s", r)

        # -- Mensal (one ZIP per month per entity) ------------------------
        mensal_tasks = []
        for entity in MENSAL_ENTITIES:
            if entity_filter and entity_filter != entity:
                continue
            for year in years:
                last_month = today.month if year == today.year else 12
                for month in range(1, last_month + 1):
                    mensal_tasks.append(self.ingest_mensal(entity, year, month))

        if mensal_tasks:
            # Batch to avoid hammering CVM with too many simultaneous requests
            for i in range(0, len(mensal_tasks), 10):
                batch = mensal_tasks[i : i + 10]
                results = await asyncio.gather(*batch, return_exceptions=True)
                for r in results:
                    if isinstance(r, int):
                        totals["cvm_mensal"] += r
                    else:
                        logger.error("Mensal task error: %s", r)

        # -- Periodic (one CSV per year) ----------------------------------
        periodic_tasks = []
        for entity, doc_type in PERIODIC_CONFIGS:
            if entity_filter and entity_filter != entity:
                continue
            for year in years:
                periodic_tasks.append(self.ingest_periodic(entity, doc_type, year))

        if periodic_tasks:
            results = await asyncio.gather(*periodic_tasks, return_exceptions=True)
            for r in results:
                if isinstance(r, int):
                    totals["cvm_periodic"] += r
                else:
                    logger.error("Periodic task error: %s", r)

        # -- SECURIT (one ZIP per year) -----------------------------------
        securit_tasks = []
        if not entity_filter or entity_filter == "securit":
            for instrument_type in SECURIT_TYPES:
                for year in years:
                    securit_tasks.append(self.ingest_securit(instrument_type, year))

        if securit_tasks:
            results = await asyncio.gather(*securit_tasks, return_exceptions=True)
            for r in results:
                if isinstance(r, int):
                    totals["cvm_securit_emissions"] += r
                else:
                    logger.error("SECURIT task error: %s", r)

        logger.info("Backfill complete: %s", totals)
        return totals

    async def daily_update(self) -> Dict[str, int]:
        """
        Incremental update: current month's data for all entities.

        Downloads the current month (and current year for yearly CSVs)
        so the DB stays current after the daily cron run.
        """
        today = date.today()
        year = today.year
        month = today.month

        totals: Dict[str, int] = {
            "cvm_cadastral":         0,
            "cvm_mensal":            0,
            "cvm_periodic":          0,
            "cvm_securit_emissions": 0,
        }

        tasks = []

        # Cadastral: refresh current year
        for entity in CADASTRAL_ENTITIES:
            tasks.append(("cvm_cadastral", self.ingest_cadastral(entity, year)))

        # Mensal: current month + previous month (in case previous was late)
        for entity in MENSAL_ENTITIES:
            tasks.append(("cvm_mensal", self.ingest_mensal(entity, year, month)))
            if month > 1:
                tasks.append(("cvm_mensal", self.ingest_mensal(entity, year, month - 1)))

        # Periodic: refresh current year
        for entity, doc_type in PERIODIC_CONFIGS:
            tasks.append(("cvm_periodic", self.ingest_periodic(entity, doc_type, year)))

        # SECURIT: refresh current year
        for instrument_type in SECURIT_TYPES:
            tasks.append(("cvm_securit_emissions", self.ingest_securit(instrument_type, year)))

        labels = [t[0] for t in tasks]
        coros  = [t[1] for t in tasks]

        results = await asyncio.gather(*coros, return_exceptions=True)
        for label, r in zip(labels, results):
            if isinstance(r, int):
                totals[label] += r
            else:
                logger.error("Daily update task error [%s]: %s", label, r)

        logger.info("Daily update complete: %s", totals)
        return totals
