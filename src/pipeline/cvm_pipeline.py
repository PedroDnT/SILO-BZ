"""
CVM data ingestor — downloads all entity/doc_type combinations and persists
to Supabase.

Tables written:
  cvm_fi_diario        FI daily snapshot (INF_DIARIO)
  cvm_fi_cda           FI portfolio composition (CDA)
  cvm_fi_perfil        FI investor profile (PERFIL_MENSAL)
  cvm_fidc_mensal      FIDC monthly snapshot
  cvm_fiagro_mensal    FIAGRO monthly snapshot
  cvm_fip_periodic     FIP quarterly/four-monthly reports
  cvm_fii_mensal       FII monthly reports
  cvm_fii_periodic     FII quarterly/annual/dfin reports
  cvm_securit_mensal   SECURIT CRA/CRI/OTS monthly emissions
  cvm_securit_dfin     SECURIT CRA/CRI financial statements
  cvm_ingest_log       Audit log for every ingest run
"""

import asyncio
import logging
import re
import sys
import os
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.fetchers.cvm_fetcher import CVMFetcher
from src.store.supabase_client import get_supabase_client, upsert_rows

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Entity / doc-type matrix  (only endpoints that actually exist on CVM server)
# ---------------------------------------------------------------------------

# FI monthly doc types (all require year + month)
FI_MONTHLY_DOC_TYPES: List[str] = ["inf_diario", "cda", "perfil_mensal", "balancete"]

# FIDC / FIAGRO monthly
FIDC_MENSAL_ENTITY = "fidc"
FIAGRO_MENSAL_ENTITY = "fiagro"

# FIP yearly doc types
FIP_PERIODIC_CONFIGS: List[Tuple[str, str]] = [
    ("fip", "inf_trimestral"),      # 2010–2023
    ("fip", "inf_quadrimestral"),   # 2024+
]

# FII doc types
FII_MENSAL_DOC_TYPES: List[str] = ["mensal_geral", "mensal_ativo_passivo"]
FII_PERIODIC_DOC_TYPES: List[str] = ["trimestral", "anual", "dfin"]

# SECURIT doc types split by target table
SECURIT_MENSAL_TYPES: List[str] = ["cra_mensal", "cri_mensal", "ots_mensal"]
SECURIT_DFIN_TYPES: List[str] = ["dfin_cra", "dfin_cri"]

_PAGE_SIZE = 5000


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize_cnpj(raw: str) -> str:
    return re.sub(r"\D", "", str(raw)) if raw else ""


def _find_field(row: Dict[str, Any], *candidates: str) -> Optional[str]:
    row_lower = {k.lower(): v for k, v in row.items()}
    for c in candidates:
        v = row_lower.get(c.lower())
        if v is not None:
            return str(v) if v != "" else None
    return None


def _find_cnpj_field(row: Dict[str, Any], prefer_suffix: str = "fundo") -> Optional[str]:
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


def _safe_numeric(val: Optional[str]) -> Optional[str]:
    """Return val unchanged; ingestor stores string, Supabase casts to NUMERIC."""
    return val


def _period_to_date(period_str: Optional[str], year: int, month: int) -> str:
    """Normalise a period string to ISO date. Falls back to first-of-month."""
    if period_str:
        try:
            # CVM uses YYYY-MM-DD for DT_COMPTC
            parts = period_str.split("-")
            if len(parts) == 3:
                return period_str
        except Exception:
            pass
    return f"{year}-{month:02d}-01"


# ---------------------------------------------------------------------------
# Ingestor class
# ---------------------------------------------------------------------------

class CVMIngestor:
    """Downloads CVM data via CVMFetcher and persists to Supabase."""

    def __init__(self) -> None:
        self._service = CVMFetcher()
        self._supabase = get_supabase_client()

    # ------------------------------------------------------------------
    # Ingest log helpers
    # ------------------------------------------------------------------

    def _log_start(self, run_id: str, entity: str, doc_type: str,
                   year: Optional[int], month: Optional[int]) -> None:
        try:
            upsert_rows(self._supabase, "cvm_ingest_log", [{
                "run_id":       run_id,
                "entity":       entity,
                "doc_type":     doc_type,
                "period_year":  year,
                "period_month": month,
                "status":       "running",
                "started_at":   datetime.now(timezone.utc).isoformat(),
            }])
        except Exception as e:
            logger.warning("ingest_log start failed: %s", e)

    def _log_finish(self, run_id: str, rows: int, error: Optional[str] = None) -> None:
        try:
            upsert_rows(self._supabase, "cvm_ingest_log", [{
                "run_id":       run_id,
                "rows_upserted": rows,
                "status":       "error" if error else "ok",
                "error_msg":    error,
                "finished_at":  datetime.now(timezone.utc).isoformat(),
            }], conflict_columns="run_id")
        except Exception as e:
            logger.warning("ingest_log finish failed: %s", e)

    # ------------------------------------------------------------------
    # Generic paginated fetch helper
    # ------------------------------------------------------------------

    async def _fetch_all_pages(
        self,
        entity: str,
        doc_type: str,
        year: Optional[int],
        month: Optional[int],
    ) -> List[Dict[str, Any]]:
        """Fetch the full CVM dataset for the entity/doc_type/year/month combo."""
        return await self._service.fetch(
            entity=entity, doc_type=doc_type, year=year, month=month,
        )

    # ------------------------------------------------------------------
    # FI — daily snapshot  (INF_DIARIO)
    # ------------------------------------------------------------------

    async def ingest_fi_diario(self, year: int, month: int) -> int:
        run_id = str(uuid4())
        self._log_start(run_id, "fi", "inf_diario", year, month)
        rows_inserted = 0
        try:
            raw_rows = await self._fetch_all_pages("fi", "inf_diario", year, month)
            records: List[Dict[str, Any]] = []
            for row in raw_rows:
                cnpj_raw = _find_cnpj_field(row, prefer_suffix="classe") or _find_cnpj_field(row)
                cnpj = _normalize_cnpj(cnpj_raw) if cnpj_raw else ""
                records.append({
                    "cnpj":          cnpj,
                    "tp_fundo":      _find_field(row, "TP_FUNDO_CLASSE"),
                    "dt_comptc":     _find_field(row, "DT_COMPTC"),
                    "vl_total":      _find_field(row, "VL_TOTAL"),
                    "vl_quota":      _find_field(row, "VL_QUOTA"),
                    "vl_patrim_liq": _find_field(row, "VL_PATRIM_LIQ"),
                    "captc_dia":     _find_field(row, "CAPTC_DIA"),
                    "resg_dia":      _find_field(row, "RESG_DIA"),
                    "nr_cotst":      _find_field(row, "NR_COTST"),
                    "raw":           row,
                })
            rows_inserted = upsert_rows(
                self._supabase, "cvm_fi_diario", records,
                conflict_columns="cnpj,dt_comptc",
            )
        except Exception as exc:
            logger.warning("ingest_fi_diario %d-%02d failed: %s", year, month, exc)
            self._log_finish(run_id, 0, str(exc))
            return 0
        self._log_finish(run_id, rows_inserted)
        logger.info("fi/inf_diario %d-%02d: %d rows", year, month, rows_inserted)
        return rows_inserted

    # ------------------------------------------------------------------
    # FI — portfolio composition  (CDA)
    # ------------------------------------------------------------------

    async def ingest_fi_cda(self, year: int, month: int) -> int:
        run_id = str(uuid4())
        self._log_start(run_id, "fi", "cda", year, month)
        rows_inserted = 0
        try:
            raw_rows = await self._fetch_all_pages("fi", "cda", year, month)
            records: List[Dict[str, Any]] = []
            for row in raw_rows:
                cnpj_raw = _find_cnpj_field(row)
                cnpj = _normalize_cnpj(cnpj_raw) if cnpj_raw else ""
                period = f"{year}-{month:02d}-01"
                records.append({
                    "cnpj":               cnpj,
                    "period":             period,
                    "tp_aplic":           _find_field(row, "TP_APLIC"),
                    "tp_ativo":           _find_field(row, "TP_ATIVO"),
                    "vl_merc_pos_final":  _find_field(row, "VL_MERC_POS_FINAL"),
                    "raw":                row,
                })
            rows_inserted = upsert_rows(
                self._supabase, "cvm_fi_cda", records,
                conflict_columns="cnpj,period,tp_aplic,tp_ativo",
            )
        except Exception as exc:
            logger.warning("ingest_fi_cda %d-%02d failed: %s", year, month, exc)
            self._log_finish(run_id, 0, str(exc))
            return 0
        self._log_finish(run_id, rows_inserted)
        logger.info("fi/cda %d-%02d: %d rows", year, month, rows_inserted)
        return rows_inserted

    # ------------------------------------------------------------------
    # FI — investor profile  (PERFIL_MENSAL)
    # ------------------------------------------------------------------

    async def ingest_fi_perfil(self, year: int, month: int) -> int:
        run_id = str(uuid4())
        self._log_start(run_id, "fi", "perfil_mensal", year, month)
        rows_inserted = 0
        try:
            raw_rows = await self._fetch_all_pages("fi", "perfil_mensal", year, month)
            records: List[Dict[str, Any]] = []
            period = f"{year}-{month:02d}-01"
            for row in raw_rows:
                cnpj_raw = _find_cnpj_field(row)
                cnpj = _normalize_cnpj(cnpj_raw) if cnpj_raw else ""
                records.append({"cnpj": cnpj, "period": period, "raw": row})
            rows_inserted = upsert_rows(
                self._supabase, "cvm_fi_perfil", records,
                conflict_columns="cnpj,period",
            )
        except Exception as exc:
            logger.warning("ingest_fi_perfil %d-%02d failed: %s", year, month, exc)
            self._log_finish(run_id, 0, str(exc))
            return 0
        self._log_finish(run_id, rows_inserted)
        logger.info("fi/perfil_mensal %d-%02d: %d rows", year, month, rows_inserted)
        return rows_inserted

    # ------------------------------------------------------------------
    # FIDC — monthly snapshot
    # ------------------------------------------------------------------

    async def ingest_fidc_mensal(self, year: int, month: int) -> int:
        run_id = str(uuid4())
        self._log_start(run_id, "fidc", "mensal", year, month)
        rows_inserted = 0
        try:
            raw_rows = await self._fetch_all_pages("fidc", "mensal", year, month)
            records: List[Dict[str, Any]] = []
            for row in raw_rows:
                cnpj_raw = _find_cnpj_field(row)
                cnpj = _normalize_cnpj(cnpj_raw) if cnpj_raw else ""
                period = _period_to_date(_find_field(row, "DT_COMPTC"), year, month)
                records.append({
                    "cnpj":          cnpj,
                    "period":        period,
                    "vl_total":      _find_field(row, "VL_TOTAL", "VL_CARTEIRA_TOTAL"),
                    "vl_quota":      _find_field(row, "VL_QUOTA"),
                    "vl_patrim_liq": _find_field(row, "VL_PATRIM_LIQ"),
                    "vl_inadimpl":   _find_inadimpl(row),
                    "nr_cotst":      _find_field(row, "NR_COTST"),
                    "raw":           row,
                })
            rows_inserted = upsert_rows(
                self._supabase, "cvm_fidc_mensal", records,
                conflict_columns="cnpj,period",
            )
        except Exception as exc:
            logger.warning("ingest_fidc_mensal %d-%02d failed: %s", year, month, exc)
            self._log_finish(run_id, 0, str(exc))
            return 0
        self._log_finish(run_id, rows_inserted)
        logger.info("fidc/mensal %d-%02d: %d rows", year, month, rows_inserted)
        return rows_inserted

    # ------------------------------------------------------------------
    # FIAGRO — monthly snapshot
    # ------------------------------------------------------------------

    async def ingest_fiagro_mensal(self, year: int, month: int) -> int:
        run_id = str(uuid4())
        self._log_start(run_id, "fiagro", "mensal", year, month)
        rows_inserted = 0
        try:
            raw_rows = await self._fetch_all_pages("fiagro", "mensal", year, month)
            records: List[Dict[str, Any]] = []
            for row in raw_rows:
                cnpj_raw = _find_cnpj_field(row)
                cnpj = _normalize_cnpj(cnpj_raw) if cnpj_raw else ""
                period = _period_to_date(_find_field(row, "DT_COMPTC"), year, month)
                records.append({
                    "cnpj":          cnpj,
                    "period":        period,
                    "vl_total":      _find_field(row, "VL_TOTAL", "VL_CARTEIRA_TOTAL"),
                    "vl_quota":      _find_field(row, "VL_QUOTA"),
                    "vl_patrim_liq": _find_field(row, "VL_PATRIM_LIQ"),
                    "vl_inadimpl":   _find_inadimpl(row),
                    "nr_cotst":      _find_field(row, "NR_COTST"),
                    "raw":           row,
                })
            rows_inserted = upsert_rows(
                self._supabase, "cvm_fiagro_mensal", records,
                conflict_columns="cnpj,period",
            )
        except Exception as exc:
            logger.warning("ingest_fiagro_mensal %d-%02d failed: %s", year, month, exc)
            self._log_finish(run_id, 0, str(exc))
            return 0
        self._log_finish(run_id, rows_inserted)
        logger.info("fiagro/mensal %d-%02d: %d rows", year, month, rows_inserted)
        return rows_inserted

    # ------------------------------------------------------------------
    # FIP — periodic (trimestral / inf_quadrimestral)
    # ------------------------------------------------------------------

    async def ingest_fip_periodic(self, doc_type: str, year: int) -> int:
        run_id = str(uuid4())
        self._log_start(run_id, "fip", doc_type, year, None)
        rows_inserted = 0
        try:
            raw_rows = await self._fetch_all_pages("fip", doc_type, year, None)
            records: List[Dict[str, Any]] = []
            for row in raw_rows:
                cnpj_raw = _find_cnpj_field(row)
                cnpj = _normalize_cnpj(cnpj_raw) if cnpj_raw else None
                records.append({
                    "cnpj":          cnpj,
                    "doc_type":      doc_type,
                    "period_year":   year,
                    "vl_patrim_liq": _find_field(row, "VL_PATRIM_LIQ"),
                    "raw":           row,
                })
            rows_inserted = upsert_rows(
                self._supabase, "cvm_fip_periodic", records,
                conflict_columns="cnpj,doc_type,period_year",
            )
        except Exception as exc:
            logger.warning("ingest_fip_periodic %s %d failed: %s", doc_type, year, exc)
            self._log_finish(run_id, 0, str(exc))
            return 0
        self._log_finish(run_id, rows_inserted)
        logger.info("fip/%s %d: %d rows", doc_type, year, rows_inserted)
        return rows_inserted

    # ------------------------------------------------------------------
    # FII — monthly (mensal_geral, mensal_ativo_passivo)
    # ------------------------------------------------------------------

    async def ingest_fii_mensal(self, doc_type: str, year: int) -> int:
        """doc_type is 'mensal_geral' or 'mensal_ativo_passivo'."""
        run_id = str(uuid4())
        self._log_start(run_id, "fii", doc_type, year, None)
        rows_inserted = 0
        subtype = "geral" if "geral" in doc_type else "ativo_passivo"
        try:
            raw_rows = await self._fetch_all_pages("fii", doc_type, year, None)
            records: List[Dict[str, Any]] = []
            for row in raw_rows:
                cnpj_raw = _find_cnpj_field(row)
                cnpj = _normalize_cnpj(cnpj_raw) if cnpj_raw else ""
                # FII uses Data_Referencia (YYYY-MM-DD format)
                period_str = _find_field(row, "Data_Referencia", "DT_COMPTC")
                period = period_str[:7] + "-01" if period_str and len(period_str) >= 7 else f"{year}-01-01"
                records.append({
                    "cnpj":          cnpj,
                    "period":        period,
                    "doc_subtype":   subtype,
                    "vl_patrim_liq": _find_field(row, "Patrimonio_Liquido", "VL_PATRIM_LIQ"),
                    "raw":           row,
                })
            rows_inserted = upsert_rows(
                self._supabase, "cvm_fii_mensal", records,
                conflict_columns="cnpj,period,doc_subtype",
            )
        except Exception as exc:
            logger.warning("ingest_fii_mensal %s %d failed: %s", doc_type, year, exc)
            self._log_finish(run_id, 0, str(exc))
            return 0
        self._log_finish(run_id, rows_inserted)
        logger.info("fii/%s %d: %d rows", doc_type, year, rows_inserted)
        return rows_inserted

    # ------------------------------------------------------------------
    # FII — periodic (trimestral, anual, dfin)
    # ------------------------------------------------------------------

    async def ingest_fii_periodic(self, doc_type: str, year: int) -> int:
        run_id = str(uuid4())
        self._log_start(run_id, "fii", doc_type, year, None)
        rows_inserted = 0
        try:
            raw_rows = await self._fetch_all_pages("fii", doc_type, year, None)
            records: List[Dict[str, Any]] = []
            for row in raw_rows:
                cnpj_raw = _find_cnpj_field(row)
                cnpj = _normalize_cnpj(cnpj_raw) if cnpj_raw else None
                records.append({
                    "cnpj":        cnpj,
                    "doc_type":    doc_type,
                    "period_year": year,
                    "raw":         row,
                })
            rows_inserted = upsert_rows(
                self._supabase, "cvm_fii_periodic", records,
                conflict_columns="cnpj,doc_type,period_year",
            )
        except Exception as exc:
            logger.warning("ingest_fii_periodic %s %d failed: %s", doc_type, year, exc)
            self._log_finish(run_id, 0, str(exc))
            return 0
        self._log_finish(run_id, rows_inserted)
        logger.info("fii/%s %d: %d rows", doc_type, year, rows_inserted)
        return rows_inserted

    # ------------------------------------------------------------------
    # SECURIT — monthly emissions (cra_mensal, cri_mensal, ots_mensal)
    # ------------------------------------------------------------------

    async def ingest_securit_mensal(self, instrument_type: str, year: int) -> int:
        run_id = str(uuid4())
        self._log_start(run_id, "securit", instrument_type, year, None)
        rows_inserted = 0
        try:
            raw_rows = await self._fetch_all_pages("securit", instrument_type, year, None)
            records: List[Dict[str, Any]] = []
            for row in raw_rows:
                cnpj_raw = _find_cnpj_field(row, prefer_suffix="securit")
                cnpj = _normalize_cnpj(cnpj_raw) if cnpj_raw else None
                records.append({
                    "instrument_type": instrument_type,
                    "period_year":     year,
                    "cnpj_securit":    cnpj,
                    "dt_emissao":      _find_field(row, "DT_EMISSAO"),
                    "dt_vencto":       _find_field(row, "DT_VENCTO", "DT_VENCIMENTO"),
                    "vl_emissao":      _find_field(row, "VL_EMISSAO"),
                    "vl_unit":         _find_field(row, "VL_UNIT", "PU_EMISSAO", "VL_PU_EMISSAO"),
                    "qt_titulos":      _find_field(row, "QT_TITULOS"),
                    "vl_total":        _find_field(row, "VL_TOTAL"),
                    "tp_ativo":        _find_field(row, "TP_ATIVO"),
                    "raw":             row,
                })
            rows_inserted = upsert_rows(
                self._supabase, "cvm_securit_mensal", records,
                conflict_columns="instrument_type,period_year,cnpj_securit,dt_emissao,dt_vencto,vl_emissao",
            )
        except Exception as exc:
            logger.warning("ingest_securit_mensal %s %d failed: %s", instrument_type, year, exc)
            self._log_finish(run_id, 0, str(exc))
            return 0
        self._log_finish(run_id, rows_inserted)
        logger.info("securit/%s %d: %d rows", instrument_type, year, rows_inserted)
        return rows_inserted

    # ------------------------------------------------------------------
    # SECURIT — financial statements (dfin_cra, dfin_cri)
    # ------------------------------------------------------------------

    async def ingest_securit_dfin(self, instrument_type: str, year: int) -> int:
        run_id = str(uuid4())
        self._log_start(run_id, "securit", instrument_type, year, None)
        rows_inserted = 0
        try:
            raw_rows = await self._fetch_all_pages("securit", instrument_type, year, None)
            records: List[Dict[str, Any]] = []
            for row in raw_rows:
                cnpj_raw = _find_cnpj_field(row, prefer_suffix="securit")
                cnpj = _normalize_cnpj(cnpj_raw) if cnpj_raw else None
                records.append({
                    "instrument_type": instrument_type,
                    "period_year":     year,
                    "cnpj_securit":    cnpj,
                    "raw":             row,
                })
            rows_inserted = upsert_rows(
                self._supabase, "cvm_securit_dfin", records,
                conflict_columns="instrument_type,period_year,cnpj_securit",
            )
        except Exception as exc:
            logger.warning("ingest_securit_dfin %s %d failed: %s", instrument_type, year, exc)
            self._log_finish(run_id, 0, str(exc))
            return 0
        self._log_finish(run_id, rows_inserted)
        logger.info("securit/%s %d: %d rows", instrument_type, year, rows_inserted)
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

        Pass entity_filter to restrict to one entity: fi | fidc | fip | fiagro | fii | securit
        """
        today = date.today()
        end_year = end_year or today.year
        years = list(range(start_year, end_year + 1))

        totals: Dict[str, int] = {t: 0 for t in [
            "cvm_fi_diario", "cvm_fi_cda", "cvm_fi_perfil",
            "cvm_fidc_mensal", "cvm_fiagro_mensal",
            "cvm_fip_periodic", "cvm_fii_mensal", "cvm_fii_periodic",
            "cvm_securit_mensal", "cvm_securit_dfin",
        ]}

        def _want(entity: str) -> bool:
            return entity_filter is None or entity_filter == entity

        # -- FI monthly (batch: 6 at a time to avoid overwhelming CVM) ----
        if _want("fi"):
            fi_tasks: List[Tuple[str, Any]] = []
            for year in years:
                last_month = today.month if year == today.year else 12
                for month in range(1, last_month + 1):
                    fi_tasks.append(("cvm_fi_diario",  self.ingest_fi_diario(year, month)))
                    fi_tasks.append(("cvm_fi_cda",     self.ingest_fi_cda(year, month)))
                    fi_tasks.append(("cvm_fi_perfil",  self.ingest_fi_perfil(year, month)))
            for i in range(0, len(fi_tasks), 6):
                batch = fi_tasks[i:i + 6]
                results = await asyncio.gather(*[t[1] for t in batch], return_exceptions=True)
                for (tbl, _), r in zip(batch, results):
                    if isinstance(r, int):
                        totals[tbl] += r

        # -- FIDC monthly -------------------------------------------------
        if _want("fidc"):
            tasks: List[Any] = []
            for year in years:
                last_month = today.month if year == today.year else 12
                for month in range(1, last_month + 1):
                    tasks.append(self.ingest_fidc_mensal(year, month))
            for i in range(0, len(tasks), 10):
                results = await asyncio.gather(*tasks[i:i + 10], return_exceptions=True)
                for r in results:
                    if isinstance(r, int):
                        totals["cvm_fidc_mensal"] += r

        # -- FIAGRO monthly  (data only from 2025-05) ---------------------
        if _want("fiagro"):
            tasks = []
            for year in years:
                last_month = today.month if year == today.year else 12
                for month in range(1, last_month + 1):
                    tasks.append(self.ingest_fiagro_mensal(year, month))
            for i in range(0, len(tasks), 10):
                results = await asyncio.gather(*tasks[i:i + 10], return_exceptions=True)
                for r in results:
                    if isinstance(r, int):
                        totals["cvm_fiagro_mensal"] += r

        # -- FIP periodic -------------------------------------------------
        if _want("fip"):
            tasks = []
            for entity, doc_type in FIP_PERIODIC_CONFIGS:
                for year in years:
                    tasks.append(self.ingest_fip_periodic(doc_type, year))
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for r in results:
                if isinstance(r, int):
                    totals["cvm_fip_periodic"] += r

        # -- FII ----------------------------------------------------------
        if _want("fii"):
            tasks = []
            for doc_type in FII_MENSAL_DOC_TYPES:
                for year in years:
                    tasks.append(("cvm_fii_mensal", self.ingest_fii_mensal(doc_type, year)))
            for doc_type in FII_PERIODIC_DOC_TYPES:
                for year in years:
                    tasks.append(("cvm_fii_periodic", self.ingest_fii_periodic(doc_type, year)))
            results = await asyncio.gather(*[t[1] for t in tasks], return_exceptions=True)
            for (tbl, _), r in zip(tasks, results):
                if isinstance(r, int):
                    totals[tbl] += r

        # -- SECURIT ------------------------------------------------------
        if _want("securit"):
            tasks = []
            for t in SECURIT_MENSAL_TYPES:
                for year in years:
                    tasks.append(("cvm_securit_mensal", self.ingest_securit_mensal(t, year)))
            for t in SECURIT_DFIN_TYPES:
                for year in years:
                    tasks.append(("cvm_securit_dfin", self.ingest_securit_dfin(t, year)))
            results = await asyncio.gather(*[t[1] for t in tasks], return_exceptions=True)
            for (tbl, _), r in zip(tasks, results):
                if isinstance(r, int):
                    totals[tbl] += r

        logger.info("Backfill complete: %s", totals)
        return totals

    async def daily_update(self) -> Dict[str, int]:
        """Incremental update: current month (and previous month for monthly files)."""
        today = date.today()
        year, month = today.year, today.month

        totals: Dict[str, int] = {t: 0 for t in [
            "cvm_fi_diario", "cvm_fi_cda", "cvm_fi_perfil",
            "cvm_fidc_mensal", "cvm_fiagro_mensal",
            "cvm_fip_periodic", "cvm_fii_mensal", "cvm_fii_periodic",
            "cvm_securit_mensal", "cvm_securit_dfin",
        ]}

        tasks: List[Tuple[str, Any]] = []

        # FI — current + previous month
        for m in ([month - 1, month] if month > 1 else [month]):
            tasks += [
                ("cvm_fi_diario", self.ingest_fi_diario(year, m)),
                ("cvm_fi_cda",    self.ingest_fi_cda(year, m)),
                ("cvm_fi_perfil", self.ingest_fi_perfil(year, m)),
            ]

        # FIDC / FIAGRO — current + previous month
        for m in ([month - 1, month] if month > 1 else [month]):
            tasks.append(("cvm_fidc_mensal",   self.ingest_fidc_mensal(year, m)))
            tasks.append(("cvm_fiagro_mensal",  self.ingest_fiagro_mensal(year, m)))

        # FIP — refresh current year
        for _, doc_type in FIP_PERIODIC_CONFIGS:
            tasks.append(("cvm_fip_periodic", self.ingest_fip_periodic(doc_type, year)))

        # FII — refresh current year
        for doc_type in FII_MENSAL_DOC_TYPES:
            tasks.append(("cvm_fii_mensal", self.ingest_fii_mensal(doc_type, year)))
        for doc_type in FII_PERIODIC_DOC_TYPES:
            tasks.append(("cvm_fii_periodic", self.ingest_fii_periodic(doc_type, year)))

        # SECURIT — refresh current year
        for t in SECURIT_MENSAL_TYPES:
            tasks.append(("cvm_securit_mensal", self.ingest_securit_mensal(t, year)))
        for t in SECURIT_DFIN_TYPES:
            tasks.append(("cvm_securit_dfin", self.ingest_securit_dfin(t, year)))

        results = await asyncio.gather(*[t[1] for t in tasks], return_exceptions=True)
        for (tbl, _), r in zip(tasks, results):
            if isinstance(r, int):
                totals[tbl] += r
            else:
                logger.error("daily_update task error [%s]: %s", tbl, r)

        logger.info("Daily update complete: %s", totals)
        return totals
