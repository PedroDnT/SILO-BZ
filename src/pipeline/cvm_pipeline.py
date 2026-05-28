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
from dataclasses import dataclass
import logging
import re
import sys
import os
from datetime import date, datetime, timezone
from typing import Any, Awaitable, Dict, List, Optional, Set, Tuple
from uuid import uuid4

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.fetchers.cvm_fetcher import CVMFetcher
from src.store.supabase_client import get_pg_client, upsert_rows

# Backward-compatible alias retained for older tests/callers.
get_supabase_client = get_pg_client

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
FII_MENSAL_DOC_TYPES: List[str] = ["mensal_geral", "mensal_ativo_passivo", "mensal_complemento"]
FII_PERIODIC_DOC_TYPES: List[str] = ["trimestral", "anual", "dfin"]

# SECURIT doc types split by target table
SECURIT_MENSAL_TYPES: List[str] = ["cra_mensal", "cri_mensal", "ots_mensal"]
SECURIT_DFIN_TYPES: List[str] = ["dfin_cra", "dfin_cri"]
SECURIT_SERIE_TYPES: List[str] = ["cra_classe", "cri_classe", "ots_classe"]
SECURIT_FLUXO_TYPES: List[str] = ["cra_fluxo", "cri_fluxo", "ots_fluxo"]

_PAGE_SIZE = 5000
_ALL_TABLES: List[str] = [
    "cvm_fi_diario", "cvm_fi_cda", "cvm_fi_perfil",
    "cvm_fidc_mensal", "cvm_fidc_tranche", "cvm_fidc_tranche_flows", "cvm_fidc_aging",
    "cvm_fiagro_mensal",
    "cvm_fip_periodic", "cvm_fii_mensal", "cvm_fii_periodic",
    "cvm_securit_mensal", "cvm_securit_serie", "cvm_securit_fluxo", "cvm_securit_dfin",
]
_ALL_ENTITIES: Set[str] = {"fi", "fidc", "fip", "fiagro", "fii", "securit"}
_CORE_DAILY_ENTITIES: Set[str] = {"fi", "fidc", "fiagro"}
_FIAGRO_FIRST_PERIOD = date(2025, 5, 1)
FII_SUBTYPE_BY_DOC_TYPE: Dict[str, str] = {
    "mensal_geral": "geral",
    "mensal_complemento": "complemento",
    "mensal_ativo_passivo": "ativo_passivo",
}
SECURIT_DOC_TO_INSTRUMENT: Dict[str, str] = {
    "cra_classe": "cra_mensal",
    "cri_classe": "cri_mensal",
    "ots_classe": "ots_mensal",
    "cra_fluxo": "cra_mensal",
    "cri_fluxo": "cri_mensal",
    "ots_fluxo": "ots_mensal",
}


@dataclass(frozen=True)
class IngestTask:
    table: str
    description: str
    operation: Awaitable[int]


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
    # Try specific known headers first
    val = _find_field(row, "TAB_VI_B_VL_DIRCRED_INAD", "TAB_VI_B_VL_TOTAL", "TAB_VI_VL_TOTAL_INAD")
    if val is not None:
        return val
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


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError:
        logger.warning("Invalid %s=%r; using default %d", name, raw, default)
        return default
    if value < 1:
        logger.warning("Non-positive %s=%r; using default %d", name, raw, default)
        return default
    return value


def _get_concurrency(name: str, default: int) -> int:
    key = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_").upper()
    return _env_int(f"CVM_{key}_CONCURRENCY", _env_int("CVM_INGEST_CONCURRENCY", default))


def _new_totals() -> Dict[str, int]:
    return {table: 0 for table in _ALL_TABLES}


def _resolve_daily_entities() -> Set[str]:
    raw = os.getenv("CVM_DAILY_SCOPE", "core").strip().lower()
    if not raw or raw == "core":
        return set(_CORE_DAILY_ENTITIES)
    if raw == "all":
        return set(_ALL_ENTITIES)

    requested = {part.strip() for part in raw.split(",") if part.strip()}
    invalid = requested - _ALL_ENTITIES
    if invalid:
        logger.warning(
            "Ignoring unknown CVM_DAILY_SCOPE entities: %s",
            ", ".join(sorted(invalid)),
        )
    resolved = requested & _ALL_ENTITIES
    return resolved or set(_CORE_DAILY_ENTITIES)


def _daily_month_pairs(today: date) -> List[Tuple[int, int]]:
    current = (today.year, today.month)
    if today.month == 1:
        previous = (today.year - 1, 12)
    else:
        previous = (today.year, today.month - 1)
    return [previous, current] if previous != current else [current]


def _iter_month_pairs(
    years: List[int],
    today: date,
    available_from: Optional[date] = None,
) -> List[Tuple[int, int]]:
    pairs: List[Tuple[int, int]] = []
    for year in years:
        if available_from and year < available_from.year:
            continue
        start_month = available_from.month if available_from and year == available_from.year else 1
        last_month = today.month if year == today.year else 12
        for month in range(start_month, last_month + 1):
            pairs.append((year, month))
    return pairs


def _resolve_securit_instrument_type(doc_type: str) -> str:
    return SECURIT_DOC_TO_INSTRUMENT.get(doc_type, doc_type.rsplit("_", 1)[0] + "_mensal")


# ---------------------------------------------------------------------------
# Ingestor class
# ---------------------------------------------------------------------------

class CVMIngestor:
    """Downloads CVM data via CVMFetcher and persists to Supabase."""

    def __init__(self) -> None:
        self._service = CVMFetcher()
        self._supabase = get_pg_client()

    async def _run_task_batches(
        self,
        tasks: List[IngestTask],
        concurrency: int,
        totals: Dict[str, int],
        label: str,
    ) -> None:
        if not tasks:
            return

        batch_size = max(1, concurrency)
        logger.info("%s: %d tasks (concurrency=%d)", label, len(tasks), batch_size)
        for i in range(0, len(tasks), batch_size):
            batch = tasks[i:i + batch_size]
            results = await asyncio.gather(
                *[task.operation for task in batch],
                return_exceptions=True,
            )
            for task, result in zip(batch, results):
                if isinstance(result, int):
                    totals[task.table] += result
                else:
                    logger.error("%s failed [%s]: %s", label, task.description, result)

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
            with self._supabase.cursor() as cur:
                cur.execute(
                    "UPDATE cvm_ingest_log SET rows_upserted=%s, status=%s,"
                    " error_msg=%s, finished_at=%s WHERE run_id=%s",
                    (
                        rows,
                        "error" if error else "ok",
                        error,
                        datetime.now(timezone.utc).isoformat(),
                        run_id,
                    ),
                )
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
    # FI — historical daily snapshot (2000-2020) from HIST/ yearly ZIPs
    # ------------------------------------------------------------------

    async def ingest_fi_hist_diario(self, year: int) -> int:
        """Ingest one full year of historical FI daily data from HIST/.

        Each yearly ZIP contains a single CSV with all trading days for all funds.
        Flushes every 5 000 records to keep peak memory manageable (~3 GB/year).
        """
        run_id = str(uuid4())
        self._log_start(run_id, "fi", "inf_diario", year, None)
        rows_inserted = 0
        try:
            raw_rows = await self._fetch_all_pages("fi", "hist_inf_diario", year, None)
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
                if len(records) >= _PAGE_SIZE:
                    rows_inserted += upsert_rows(
                        self._supabase, "cvm_fi_diario", records,
                        conflict_columns="cnpj,dt_comptc",
                    )
                    records = []
            if records:
                rows_inserted += upsert_rows(
                    self._supabase, "cvm_fi_diario", records,
                    conflict_columns="cnpj,dt_comptc",
                )
        except Exception as exc:
            logger.warning("ingest_fi_hist_diario %d failed: %s", year, exc)
            self._log_finish(run_id, 0, str(exc))
            return 0
        self._log_finish(run_id, rows_inserted)
        logger.info("fi/hist_inf_diario %d: %d rows", year, rows_inserted)
        return rows_inserted

    # ------------------------------------------------------------------
    # FI — historical portfolio composition (2005-2022) from HIST/ ZIPs
    # ------------------------------------------------------------------

    async def ingest_fi_hist_cda(self, year: int) -> int:
        """Ingest one full year of historical FI portfolio composition from HIST/."""
        run_id = str(uuid4())
        self._log_start(run_id, "fi", "cda", year, None)
        rows_inserted = 0
        try:
            raw_rows = await self._fetch_all_pages("fi", "hist_cda", year, None)
            records: List[Dict[str, Any]] = []
            for row in raw_rows:
                cnpj_raw = _find_cnpj_field(row)
                cnpj = _normalize_cnpj(cnpj_raw) if cnpj_raw else ""
                period = _find_field(row, "DT_COMPTC")
                if period and len(period) >= 7:
                    period = period[:7] + "-01"
                records.append({
                    "cnpj":               cnpj,
                    "period":             period,
                    "tp_aplic":           _find_field(row, "TP_APLIC"),
                    "tp_ativo":           _find_field(row, "TP_ATIVO"),
                    "vl_merc_pos_final":  _find_field(row, "VL_MERC_POS_FINAL"),
                    "raw":                row,
                })
                if len(records) >= _PAGE_SIZE:
                    rows_inserted += upsert_rows(
                        self._supabase, "cvm_fi_cda", records,
                        conflict_columns="cnpj,period,tp_aplic,tp_ativo",
                    )
                    records = []
            if records:
                rows_inserted += upsert_rows(
                    self._supabase, "cvm_fi_cda", records,
                    conflict_columns="cnpj,period,tp_aplic,tp_ativo",
                )
        except Exception as exc:
            logger.warning("ingest_fi_hist_cda %d failed: %s", year, exc)
            self._log_finish(run_id, 0, str(exc))
            return 0
        self._log_finish(run_id, rows_inserted)
        logger.info("fi/hist_cda %d: %d rows", year, rows_inserted)
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
                records.append({
                    "cnpj":                              cnpj,
                    "period":                            period,
                    "mod_var":                           _find_field(row, "MOD_VAR"),
                    "vedac_taxa_perfm":                  _find_field(row, "VEDAC_TAXA_PERFM"),
                    "pr_var_carteira":                   _find_field(row, "PR_VAR_CARTEIRA"),
                    "prazo_carteira_titulo":             _find_field(row, "PRAZO_CARTEIRA_TITULO"),
                    "pr_variacao_diaria_cota":           _find_field(row, "PR_VARIACAO_DIARIA_COTA"),
                    "pr_variacao_diaria_cota_estresse":  _find_field(row, "PR_VARIACAO_DIARIA_COTA_ESTRESSE"),
                    "pr_ativo_cred_priv":                _find_field(row, "PR_ATIVO_CRED_PRIV"),
                    "pr_ativo_emissor_ligado":           _find_field(row, "PR_ATIVO_EMISSOR_LIGADO"),
                    "pr_patrim_liq_maior_cotst":         _find_field(row, "PR_PATRIM_LIQ_MAIOR_COTST"),
                    "nr_cotst_pf_pb":                    _find_field(row, "NR_COTST_PF_PB"),
                    "nr_cotst_pj_financ":                _find_field(row, "NR_COTST_PJ_FINANC"),
                    "nr_cotst_pj_nao_financ_pb":         _find_field(row, "NR_COTST_PJ_NAO_FINANC_PB"),
                    "nr_cotst_pj_nao_financ_varejo":     _find_field(row, "NR_COTST_PJ_NAO_FINANC_VAREJO"),
                    "nr_cotst_banco":                    _find_field(row, "NR_COTST_BANCO"),
                    "nr_cotst_fi_clube":                 _find_field(row, "NR_COTST_FI_CLUBE"),
                    "nr_cotst_distrib":                  _find_field(row, "NR_COTST_DISTRIB"),
                    "raw":                               row,
                })
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
                    "tp_fundo":      _find_field(row, "TP_FUNDO_CLASSE", "TP_FUNDO"),
                    "vl_total":      _find_field(row, "VL_TOTAL", "VL_CARTEIRA_TOTAL", "TAB_II_VL_CARTEIRA"),
                    "vl_quota":      _find_field(row, "VL_QUOTA"),
                    "vl_patrim_liq": _find_field(row, "TAB_IV_A_VL_PL", "VL_PATRIM_LIQ"),
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
    # FIDC — historical monthly data (2013–2024) from HIST/ yearly ZIPs
    #
    # CVM changed FIDC reporting format in 2025 (ICVM 175).  Pre-2025 data
    # lives in HIST/inf_mensal_fidc_{year}.zip, with tab_II (assets) and
    # tab_III (liabilities) CSVs for each month inside the ZIP.
    #
    # PL = TAB_II_VL_CARTEIRA - TAB_III_VL_PASSIVO (approximation; no
    # direct PL field in historical format).
    # Tranche-level tabs (X_2…X_6, VI) are not present historically.
    # ------------------------------------------------------------------

    async def ingest_fidc_hist_mensal(self, year: int) -> int:
        """Ingest one full year of historical FIDC monthly data from HIST/."""
        total = 0
        for month in range(1, 13):
            run_id = str(uuid4())
            self._log_start(run_id, "fidc", "mensal", year, month)
            rows_inserted = 0
            try:
                # Fetch tab_II (assets) and tab_III (liabilities) concurrently.
                # Both download from the same yearly ZIP — the second fetch hits cache.
                rows_ii, rows_iii = await asyncio.gather(
                    self._fetch_all_pages("fidc", "hist_mensal_tab_ii", year, month),
                    self._fetch_all_pages("fidc", "hist_mensal_tab_iii", year, month),
                )

                # Index tab_III by (cnpj, period) for O(1) join
                liab: Dict[tuple, float] = {}
                for row in rows_iii:
                    cnpj_raw = _find_cnpj_field(row)
                    cnpj = _normalize_cnpj(cnpj_raw) if cnpj_raw else ""
                    period = _find_field(row, "DT_COMPTC") or f"{year}-{month:02d}-01"
                    try:
                        liab[(cnpj, period)] = float(_find_field(row, "TAB_III_VL_PASSIVO") or 0)
                    except (ValueError, TypeError):
                        liab[(cnpj, period)] = 0.0

                records: List[Dict[str, Any]] = []
                for row in rows_ii:
                    cnpj_raw = _find_cnpj_field(row)
                    cnpj = _normalize_cnpj(cnpj_raw) if cnpj_raw else ""
                    if not cnpj:
                        continue
                    period = _find_field(row, "DT_COMPTC") or f"{year}-{month:02d}-01"
                    try:
                        vl_carteira = float(_find_field(row, "TAB_II_VL_CARTEIRA") or 0)
                    except (ValueError, TypeError):
                        vl_carteira = 0.0
                    vl_passivo = liab.get((cnpj, period), 0.0)
                    vl_pl = vl_carteira - vl_passivo if vl_carteira else None
                    records.append({
                        "cnpj":          cnpj,
                        "period":        period,
                        "vl_total":      str(vl_carteira) if vl_carteira else None,
                        "vl_quota":      None,
                        "vl_patrim_liq": str(vl_pl) if vl_pl is not None else None,
                        "vl_inadimpl":   None,
                        "nr_cotst":      None,
                        "raw":           row,
                    })

                # Also seed fund names from DENOM_SOCIAL into cvm_fund_registry
                registry: List[Dict[str, Any]] = []
                seen_cnpj: set = set()
                for row in rows_ii:
                    cnpj_raw = _find_cnpj_field(row)
                    cnpj = _normalize_cnpj(cnpj_raw) if cnpj_raw else ""
                    if cnpj and cnpj not in seen_cnpj:
                        seen_cnpj.add(cnpj)
                        name = _find_field(row, "DENOM_SOCIAL")
                        if name:
                            registry.append({
                                "cnpj":        cnpj,
                                "entity_type": "fidc",
                                "fund_name":   name,
                                "raw":         {},
                            })
                if registry:
                    upsert_rows(
                        self._supabase, "cvm_fund_registry", registry,
                        conflict_columns="cnpj,entity_type",
                    )

                rows_inserted = upsert_rows(
                    self._supabase, "cvm_fidc_mensal", records,
                    conflict_columns="cnpj,period",
                )
            except Exception as exc:
                logger.warning("ingest_fidc_hist_mensal %d-%02d failed: %s", year, month, exc)
                self._log_finish(run_id, 0, str(exc))
                continue
            self._log_finish(run_id, rows_inserted)
            logger.info("fidc/hist_mensal %d-%02d: %d rows", year, month, rows_inserted)
            total += rows_inserted
        return total

    # ------------------------------------------------------------------
    # FIDC — tranche-level data (tabs X_2 + X_3 + X_6, flows X_4, aging VI)
    # ------------------------------------------------------------------

    async def ingest_fidc_tranche(self, year: int, month: int) -> int:
        """Ingest per-tranche quota, return, and performance (tabs X_2 + X_3 + X_6 joined)."""
        run_id = str(uuid4())
        self._log_start(run_id, "fidc", "mensal_tab_x2", year, month)
        rows_inserted = 0
        try:
            rows_x2, rows_x3, rows_x6 = await asyncio.gather(
                self._fetch_all_pages("fidc", "mensal_tab_X2", year, month),
                self._fetch_all_pages("fidc", "mensal_tab_X3", year, month),
                self._fetch_all_pages("fidc", "mensal_tab_X6", year, month),
            )

            def _key(row: Dict[str, Any]) -> tuple:
                cnpj = _normalize_cnpj(_find_cnpj_field(row) or "")
                period = _period_to_date(_find_field(row, "DT_COMPTC"), year, month)
                return (cnpj, period, _find_field(row, "TAB_X_CLASSE_SERIE") or "")

            x3 = {_key(r): r for r in rows_x3}
            x6 = {_key(r): r for r in rows_x6}

            records: List[Dict[str, Any]] = []
            for row in rows_x2:
                cnpj_raw = _find_cnpj_field(row)
                cnpj = _normalize_cnpj(cnpj_raw) if cnpj_raw else ""
                period = _period_to_date(_find_field(row, "DT_COMPTC"), year, month)
                classe = _find_field(row, "TAB_X_CLASSE_SERIE") or ""
                r3 = x3.get((cnpj, period, classe), {})
                r6 = x6.get((cnpj, period, classe), {})
                records.append({
                    "cnpj":               cnpj,
                    "period":             period,
                    "classe_serie":       classe,
                    "qt_cota":            _find_field(row, "TAB_X_QT_COTA"),
                    "vl_cota":            _find_field(row, "TAB_X_VL_COTA"),
                    "vl_rentab_mes":      _find_field(r3, "TAB_X_VL_RENTAB_MES"),
                    "pr_desemp_esperado": _find_field(r6, "TAB_X_PR_DESEMP_ESPERADO"),
                    "pr_desemp_real":     _find_field(r6, "TAB_X_PR_DESEMP_REAL"),
                    "raw":                row,
                })
            rows_inserted = upsert_rows(
                self._supabase, "cvm_fidc_tranche", records,
                conflict_columns="cnpj,period,classe_serie",
            )
        except Exception as exc:
            logger.warning("ingest_fidc_tranche %d-%02d failed: %s", year, month, exc)
            self._log_finish(run_id, 0, str(exc))
            return 0
        self._log_finish(run_id, rows_inserted)
        logger.info("fidc/tranche %d-%02d: %d rows", year, month, rows_inserted)
        return rows_inserted

    async def ingest_fidc_tranche_flows(self, year: int, month: int) -> int:
        """Ingest per-tranche monthly flows (tab_X_4: captações / resgates)."""
        run_id = str(uuid4())
        self._log_start(run_id, "fidc", "mensal_tab_x4", year, month)
        rows_inserted = 0
        try:
            raw_rows = await self._fetch_all_pages("fidc", "mensal_tab_X4", year, month)
            records: List[Dict[str, Any]] = []
            for row in raw_rows:
                cnpj_raw = _find_cnpj_field(row)
                cnpj = _normalize_cnpj(cnpj_raw) if cnpj_raw else ""
                period = _period_to_date(_find_field(row, "DT_COMPTC"), year, month)
                records.append({
                    "cnpj":        cnpj,
                    "period":      period,
                    "classe_serie": _find_field(row, "TAB_X_CLASSE_SERIE") or "",
                    "tp_oper":     _find_field(row, "TAB_X_TP_OPER") or "",
                    "vl_total":    _find_field(row, "TAB_X_VL_TOTAL"),
                    "qt_cota":     _find_field(row, "TAB_X_QT_COTA"),
                })
            rows_inserted = upsert_rows(
                self._supabase, "cvm_fidc_tranche_flows", records,
                conflict_columns="cnpj,period,classe_serie,tp_oper",
            )
        except Exception as exc:
            logger.warning("ingest_fidc_tranche_flows %d-%02d failed: %s", year, month, exc)
            self._log_finish(run_id, 0, str(exc))
            return 0
        self._log_finish(run_id, rows_inserted)
        logger.info("fidc/tranche_flows %d-%02d: %d rows", year, month, rows_inserted)
        return rows_inserted

    async def ingest_fidc_aging(self, year: int, month: int) -> int:
        """Ingest FIDC delinquency aging buckets from tab_VI (credits without risk).

        Column candidates follow CVM's TAB_VI_A_VL_N (maturity) / TAB_VI_B_VL_N
        (delinquency) naming. Verify against actual CSV headers after first run.
        """
        run_id = str(uuid4())
        self._log_start(run_id, "fidc", "mensal_tab_vi", year, month)
        rows_inserted = 0
        try:
            raw_rows = await self._fetch_all_pages("fidc", "mensal_tab_VI", year, month)
            records: List[Dict[str, Any]] = []
            for row in raw_rows:
                cnpj_raw = _find_cnpj_field(row)
                cnpj = _normalize_cnpj(cnpj_raw) if cnpj_raw else ""
                period = _period_to_date(_find_field(row, "DT_COMPTC"), year, month)
                records.append({
                    "cnpj":               cnpj,
                    "period":             period,
                    "vl_prazo_30":        _find_field(row, "TAB_VI_A1_VL_PRAZO_VENC_30", "TAB_VI_A_VL_1",  "TAB_VI_VL_PRAZO_1_30"),
                    "vl_prazo_60":        _find_field(row, "TAB_VI_A2_VL_PRAZO_VENC_60", "TAB_VI_A_VL_2",  "TAB_VI_VL_PRAZO_31_60"),
                    "vl_prazo_90":        _find_field(row, "TAB_VI_A3_VL_PRAZO_VENC_90", "TAB_VI_A_VL_3",  "TAB_VI_VL_PRAZO_61_90"),
                    "vl_prazo_120":       _find_field(row, "TAB_VI_A4_VL_PRAZO_VENC_120", "TAB_VI_A_VL_4",  "TAB_VI_VL_PRAZO_91_120"),
                    "vl_prazo_150":       _find_field(row, "TAB_VI_A5_VL_PRAZO_VENC_150", "TAB_VI_A_VL_5",  "TAB_VI_VL_PRAZO_121_150"),
                    "vl_prazo_180":       _find_field(row, "TAB_VI_A6_VL_PRAZO_VENC_180", "TAB_VI_A_VL_6",  "TAB_VI_VL_PRAZO_151_180"),
                    "vl_prazo_360":       _find_field(row, "TAB_VI_A7_VL_PRAZO_VENC_360", "TAB_VI_A_VL_7",  "TAB_VI_VL_PRAZO_181_360"),
                    "vl_prazo_720":       _find_field(row, "TAB_VI_A8_VL_PRAZO_VENC_720", "TAB_VI_A_VL_8",  "TAB_VI_VL_PRAZO_361_720"),
                    "vl_prazo_1080":      _find_field(row, "TAB_VI_A9_VL_PRAZO_VENC_1080", "TAB_VI_A_VL_9",  "TAB_VI_VL_PRAZO_721_1080"),
                    "vl_prazo_maior_1080": _find_field(row, "TAB_VI_A10_VL_PRAZO_VENC_MAIOR_1080", "TAB_VI_A_VL_10", "TAB_VI_VL_PRAZO_MAIS_1080"),
                    "vl_inad_30":         _find_field(row, "TAB_VI_B1_VL_INAD_30", "TAB_VI_B_VL_1",  "TAB_VI_VL_INAD_1_30"),
                    "vl_inad_60":         _find_field(row, "TAB_VI_B2_VL_INAD_60", "TAB_VI_B_VL_2",  "TAB_VI_VL_INAD_31_60"),
                    "vl_inad_90":         _find_field(row, "TAB_VI_B3_VL_INAD_90", "TAB_VI_B_VL_3",  "TAB_VI_VL_INAD_61_90"),
                    "vl_inad_120":        _find_field(row, "TAB_VI_B4_VL_INAD_120", "TAB_VI_B_VL_4",  "TAB_VI_VL_INAD_91_120"),
                    "vl_inad_150":        _find_field(row, "TAB_VI_B5_VL_INAD_150", "TAB_VI_B_VL_5",  "TAB_VI_VL_INAD_121_150"),
                    "vl_inad_180":        _find_field(row, "TAB_VI_B6_VL_INAD_180", "TAB_VI_B_VL_6",  "TAB_VI_VL_INAD_151_180"),
                    "vl_inad_360":        _find_field(row, "TAB_VI_B7_VL_INAD_360", "TAB_VI_B_VL_7",  "TAB_VI_VL_INAD_181_360"),
                    "vl_inad_720":        _find_field(row, "TAB_VI_B8_VL_INAD_720", "TAB_VI_B_VL_8",  "TAB_VI_VL_INAD_361_720"),
                    "vl_inad_1080":       _find_field(row, "TAB_VI_B9_VL_INAD_1080", "TAB_VI_B_VL_9",  "TAB_VI_VL_INAD_721_1080"),
                    "vl_inad_maior_1080": _find_field(row, "TAB_VI_B10_VL_INAD_MAIOR_1080", "TAB_VI_B_VL_10", "TAB_VI_VL_INAD_MAIS_1080"),
                    "vl_total_inad":      _find_field(row, "TAB_VI_B_VL_DIRCRED_INAD", "TAB_VI_B_VL_TOTAL", "TAB_VI_VL_TOTAL_INAD"),
                    "raw":                row,
                })
            rows_inserted = upsert_rows(
                self._supabase, "cvm_fidc_aging", records,
                conflict_columns="cnpj,period",
            )
        except Exception as exc:
            logger.warning("ingest_fidc_aging %d-%02d failed: %s", year, month, exc)
            self._log_finish(run_id, 0, str(exc))
            return 0
        self._log_finish(run_id, rows_inserted)
        logger.info("fidc/aging %d-%02d: %d rows", year, month, rows_inserted)
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
                    "tp_fundo":      _find_field(row, "Tipo_Fundo_Classe", "TP_FUNDO_CLASSE", "TP_FUNDO"),
                    "vl_total":      _find_field(row, "VL_TOTAL", "VL_CARTEIRA_TOTAL", "Valor_Ativo", "Total_Investido"),
                    "vl_quota":      _find_field(row, "VL_QUOTA", "Valor_Patrimonial_Cotas"),
                    "vl_patrim_liq": _find_field(row, "VL_PATRIM_LIQ", "Patrimonio_Liquido"),
                    "vl_inadimpl":   _find_inadimpl(row) or _find_field(row, "Vencidos"),
                    "nr_cotst":      _find_field(row, "NR_COTST", "Numero_Cotistas"),
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
        """doc_type is one of: mensal_geral | mensal_ativo_passivo | mensal_complemento."""
        run_id = str(uuid4())
        self._log_start(run_id, "fii", doc_type, year, None)
        rows_inserted = 0
        subtype = FII_SUBTYPE_BY_DOC_TYPE.get(doc_type, "ativo_passivo")
        try:
            raw_rows = await self._fetch_all_pages("fii", doc_type, year, None)
            records: List[Dict[str, Any]] = []
            for row in raw_rows:
                cnpj_raw = _find_cnpj_field(row)
                cnpj = _normalize_cnpj(cnpj_raw) if cnpj_raw else ""
                # FII uses Data_Referencia (YYYY-MM-DD format)
                period_str = _find_field(row, "Data_Referencia", "DT_COMPTC")
                period = period_str[:7] + "-01" if period_str and len(period_str) >= 7 else f"{year}-01-01"
                record: Dict[str, Any] = {
                    "cnpj":          cnpj,
                    "period":        period,
                    "doc_subtype":   subtype,
                    "tp_fundo":      _find_field(row, "Tipo_Fundo_Classe", "TP_FUNDO_CLASSE", "TP_FUNDO"),
                    "vl_patrim_liq": _find_field(row, "Patrimonio_Liquido", "VL_PATRIM_LIQ"),
                    "cotas_emitidas": _find_field(row, "Cotas_Emitidas", "Quantidade_Cotas_Emitidas"),
                    "raw":           row,
                }
                if subtype == "complemento":
                    record.update({
                        "nr_cotst":               _find_field(row, "Total_Numero_Cotistas"),
                        "vl_ativo":               _find_field(row, "Valor_Ativo"),
                        "vl_patrimonial_cotas":   _find_field(row, "Valor_Patrimonial_Cotas"),
                        "pct_rentab_efetiva_mes": _find_field(row, "Percentual_Rentabilidade_Efetiva_Mes"),
                        "pct_rentab_patrimonial": _find_field(row, "Percentual_Rentabilidade_Patrimonial_Mes"),
                        "pct_dividend_yield_mes": _find_field(row, "Percentual_Dividend_Yield_Mes"),
                        "pct_amortizacao_mes":    _find_field(row, "Percentual_Amortizacao_Cotas_Mes"),
                    })
                elif subtype == "ativo_passivo":
                    record["rendimentos_distribuir"] = _find_field(row, "Rendimentos_Distribuir")
                    record["vl_ativo"] = _find_field(row, "Total_Investido", "Valor_Ativo")
                records.append(record)
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
                    "cnpj":                  cnpj,
                    "doc_type":              doc_type,
                    "period_year":           year,
                    "data_referencia":       _find_field(row, "Data_Referencia"),
                    "nome_imovel":           _find_field(row, "Nome_Imovel"),
                    "endereco":              _find_field(row, "Endereco"),
                    "area":                  _find_field(row, "Area"),
                    "numero_unidades":       _find_field(row, "Numero_Unidades"),
                    "percentual_imovel_pl":  _find_field(row, "Percentual_Imovel_PL"),
                    "raw":                   row,
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
                    "dt_emissao":      _find_field(row, "Data_Referencia", "DT_EMISSAO"),
                    "dt_vencto":       _find_field(row, "DT_VENCTO", "DT_VENCIMENTO"),
                    "vl_emissao":      _find_field(row, "Valor_Atualizado_Emissao", "VL_EMISSAO"),
                    "vl_unit":         _find_field(row, "VL_UNIT", "PU_EMISSAO", "VL_PU_EMISSAO"),
                    "qt_titulos":      _find_field(row, "QT_TITULOS"),
                    "vl_total":        _find_field(row, "Ativo", "VL_TOTAL"),
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
    # Fund registry — DENOM_SOCIAL + status from CVM cadastral files
    # ------------------------------------------------------------------

    async def ingest_fund_registry(self, entity: str) -> int:
        """
        Ingest fund names for fi and fii from CVM cadastral static CSVs.
        FIDC / FIP / FIAGRO names are seeded directly from raw JSONB via SQL
        migration (seed_fidc_fip_fiagro_fii_fund_registry) — no HTTP needed.
        """
        if entity not in ("fi", "fii"):
            return 0
        run_id = str(uuid4())
        self._log_start(run_id, entity, "cad", None, None)
        rows_inserted = 0
        try:
            raw_rows = await self._fetch_all_pages(entity, "cad", None, None)
            records: List[Dict[str, Any]] = []
            for row in raw_rows:
                cnpj_raw = _find_cnpj_field(row)
                cnpj = _normalize_cnpj(cnpj_raw) if cnpj_raw else ""
                if not cnpj:
                    continue
                records.append({
                    "cnpj":        cnpj,
                    "entity_type": entity,
                    "fund_name":   _find_field(row, "DENOM_SOCIAL", "NM_FUNDO"),
                    "status":      _find_field(row, "SIT", "SITUACAO"),
                    "tp_fundo":    _find_field(row, "TP_FUNDO", "TP_FUNDO_CLASSE"),
                    "dt_reg":      _find_field(row, "DT_REG", "DT_CONST"),
                    "dt_cancel":   _find_field(row, "DT_CANCEL"),
                    "raw":         row,
                })
            rows_inserted = upsert_rows(
                self._supabase, "cvm_fund_registry", records,
                conflict_columns="cnpj,entity_type",
            )
        except Exception as exc:
            logger.warning("ingest_fund_registry %s failed: %s", entity, exc)
            self._log_finish(run_id, 0, str(exc))
            return 0
        self._log_finish(run_id, rows_inserted)
        logger.info("%s/cad: %d rows", entity, rows_inserted)
        return rows_inserted

    # ------------------------------------------------------------------
    # SECURIT — per-series data (classe CSV) and cash flows (fluxo_caixa CSV)
    # ------------------------------------------------------------------

    async def ingest_securit_serie(self, doc_type: str, year: int) -> int:
        """Ingest per-series status, rating, and yield from the classe CSV.

        doc_type is one of: cra_classe | cri_classe | ots_classe
        instrument_type stored in DB is derived by replacing suffix with _mensal.
        """
        run_id = str(uuid4())
        self._log_start(run_id, "securit", doc_type, year, None)
        instrument_type = _resolve_securit_instrument_type(doc_type)
        rows_inserted = 0
        try:
            raw_rows = await self._fetch_all_pages("securit", doc_type, year, None)
            records: List[Dict[str, Any]] = []
            for row in raw_rows:
                cnpj_raw = _find_cnpj_field(row, prefer_suffix="securit")
                cnpj = _normalize_cnpj(cnpj_raw) if cnpj_raw else None
                data_ref = _find_field(row, "Data_Referencia", "DT_COMPETENCIA")
                records.append({
                    "instrument_type":           instrument_type,
                    "cnpj_securit":              cnpj,
                    "codigo_identificacao":      _find_field(row, "Codigo_Identificacao_Certificado",
                                                                  "Codigo_Identificacao", "CNPJ_Fundo") or "",
                    "data_referencia":           data_ref,
                    "classe":                    _find_field(row, "Classe"),
                    "numero_serie":              _find_field(row, "Numero_Serie"),
                    "tipo_oferta":               _find_field(row, "Tipo_Oferta"),
                    "codigo_cetip":              _find_field(row, "Codigo_CETIP"),
                    "codigo_isin":               _find_field(row, "Codigo_ISIN"),
                    "data_vencimento":           _find_field(row, "Data_Vencimento"),
                    "situacao":                  _find_field(row, "Situacao"),
                    "valor_total_integralizado": _find_field(row, "Valor_Total_Integralizado"),
                    "taxa_juros":                _find_field(row, "Taxa_Juros"),
                    "pagamento_periodicidade":   _find_field(row, "Pagamento_Periodicidade"),
                    "quantidade_certificados":   _find_field(row, "Quantidade_Certificados"),
                    "valor_certificados":        _find_field(row, "Valor_Certificados"),
                    "rendimentos":               _find_field(row, "Rendimentos"),
                    "amortizacoes":              _find_field(row, "Amortizacoes"),
                    "rentabilidade":             _find_field(row, "Rentabilidade"),
                    "classificacao_risco_atual": _find_field(row, "Classificacao_Risco_Atual"),
                    "indice_subordinacao_minimo": _find_field(row, "Indice_Subordinacao_Minimo"),
                    "indice_subordinacao_data_base": _find_field(row, "Indice_Subordinacao_Data_Base"),
                    "pagamento_mes_base":        _find_field(row, "Pagamento_Mes_Base"),
                    "periodicidade_amortizacao": _find_field(row, "Periodicidade_Amortizacao"),
                    "taxas_indexadores":         _find_field(row, "Taxas_Indexadores"),
                    "nivel_subordinacao":        _find_field(row, "Nivel_Subordinacao"),
                    "raw":                       row,
                })
            rows_inserted = upsert_rows(
                self._supabase, "cvm_securit_serie", records,
                conflict_columns="instrument_type,cnpj_securit,codigo_identificacao,data_referencia,numero_serie",
            )
        except Exception as exc:
            logger.warning("ingest_securit_serie %s %d failed: %s", doc_type, year, exc)
            self._log_finish(run_id, 0, str(exc))
            return 0
        self._log_finish(run_id, rows_inserted)
        logger.info("securit/%s %d: %d rows", doc_type, year, rows_inserted)
        return rows_inserted

    async def ingest_securit_fluxo(self, doc_type: str, year: int) -> int:
        """Ingest monthly cash flows by tranche from the fluxo_caixa CSV.

        doc_type is one of: cra_fluxo | cri_fluxo | ots_fluxo
        """
        run_id = str(uuid4())
        self._log_start(run_id, "securit", doc_type, year, None)
        instrument_type = _resolve_securit_instrument_type(doc_type)
        rows_inserted = 0
        try:
            raw_rows = await self._fetch_all_pages("securit", doc_type, year, None)
            records: List[Dict[str, Any]] = []
            for row in raw_rows:
                cnpj_raw = _find_cnpj_field(row, prefer_suffix="securit")
                cnpj = _normalize_cnpj(cnpj_raw) if cnpj_raw else None
                data_ref = _find_field(row, "Data_Referencia", "DT_COMPETENCIA")
                records.append({
                    "instrument_type":                   instrument_type,
                    "cnpj_securit":                      cnpj,
                    "codigo_identificacao":              _find_field(row, "Codigo_Identificacao_Certificado", "Codigo_Identificacao", "CNPJ_Fundo") or "",
                    "data_referencia":                   data_ref,
                    "recebimentos_direitos_creditorios": _find_field(row, "Recebimentos_Direitos_Creditorios", "Recebimentos_Creditos"),
                    "recebimentos_alienacao_caixa":      _find_field(row, "Recebimentos_Alienacao_Caixa"),
                    "outros_recebimentos":               _find_field(row, "Outros_Recebimentos"),
                    "aquisicao_caixa":                   _find_field(row, "Aquisicao_Caixa"),
                    "aquisicao_novos_creditos":          _find_field(row, "Aquisicao_Novos_Creditos"),
                    "pagamentos_despesas":               _find_field(row, "Pagamentos_Despesas"),
                    "outros_pagamentos":                 _find_field(row, "Outros_Pagamentos"),
                    "pagamentos_classe_senior":          _find_field(row, "Pagamentos_Classe_Senior"),
                    "pagamentos_senior_principal":       _find_field(row, "Pagamentos_Classe_Senior_Amortizacao_Principal", "Pagamentos_Classe_Senior_Principal", "Pagamentos_Senior_Principal"),
                    "pagamentos_senior_juros":           _find_field(row, "Pagamentos_Classe_Senior_Juros", "Pagamentos_Senior_Juros"),
                    "pagamentos_mezanino":               _find_field(row, "Pagamentos_Classe_Subordinada_Mezanino"),
                    "pagamentos_mezanino_principal":     _find_field(row, "Pagamentos_Classe_Subordinada_Mezanino_Amortizacao_Principal", "Pagamentos_Classe_Subordinada_Mezanino_Principal"),
                    "pagamentos_mezanino_juros":         _find_field(row, "Pagamentos_Classe_Subordinada_Mezanino_Juros"),
                    "pagamentos_junior":                 _find_field(row, "Pagamentos_Classe_Subordinada_Junior"),
                    "pagamentos_junior_principal":       _find_field(row, "Pagamentos_Classe_Subordinada_Junior_Amortizacao_Principal", "Pagamentos_Classe_Subordinada_Junior_Principal"),
                    "pagamentos_junior_juros":           _find_field(row, "Pagamentos_Classe_Subordinada_Junior_Juros"),
                    "variacao_liquida_caixa":            _find_field(row, "Variacao_Liquida_Caixa"),
                    "raw":                               row,
                })
            rows_inserted = upsert_rows(
                self._supabase, "cvm_securit_fluxo", records,
                conflict_columns="instrument_type,cnpj_securit,codigo_identificacao,data_referencia",
            )
        except Exception as exc:
            logger.warning("ingest_securit_fluxo %s %d failed: %s", doc_type, year, exc)
            self._log_finish(run_id, 0, str(exc))
            return 0
        self._log_finish(run_id, rows_inserted)
        logger.info("securit/%s %d: %d rows", doc_type, year, rows_inserted)
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

        totals = _new_totals()

        def _want(entity: str) -> bool:
            return entity_filter is None or entity_filter == entity

        # -- Fund registry (static cadastral files — run once per backfill) --
        for entity in ("fi", "fii"):
            if _want(entity):
                await self.ingest_fund_registry(entity)

        # -- FI ----------------------------------------------------------
        # inf_diario HIST covers 2000-2020; monthly ZIP works from 2021+.
        # cda        HIST covers 2005-2022; monthly ZIP works from 2023+.
        # perfil_mensal is always a monthly direct CSV — no HIST needed.
        if _want("fi"):
            hist_diario_years = [y for y in years if y <= 2020]
            hist_cda_years    = [y for y in years if y <= 2022]
            monthly_years     = years  # perfil_mensal + inf_diario 2021+ + cda 2023+

            # Historical inf_diario (yearly ZIPs — sequential, each ~89MB)
            for year in hist_diario_years:
                n = await self.ingest_fi_hist_diario(year)
                totals["cvm_fi_diario"] += n

            # Historical cda (yearly ZIPs — sequential)
            for year in hist_cda_years:
                n = await self.ingest_fi_hist_cda(year)
                totals["cvm_fi_cda"] += n

            # Monthly format: inf_diario 2021+, cda 2023+, perfil_mensal all years
            fi_tasks: List[IngestTask] = []
            for year, month in _iter_month_pairs(monthly_years, today):
                if year >= 2021:
                    fi_tasks.append(IngestTask(
                        "cvm_fi_diario",
                        f"fi/inf_diario {year}-{month:02d}",
                        self.ingest_fi_diario(year, month),
                    ))
                if year >= 2023:
                    fi_tasks.append(IngestTask(
                        "cvm_fi_cda",
                        f"fi/cda {year}-{month:02d}",
                        self.ingest_fi_cda(year, month),
                    ))
                fi_tasks.append(IngestTask(
                    "cvm_fi_perfil",
                    f"fi/perfil_mensal {year}-{month:02d}",
                    self.ingest_fi_perfil(year, month),
                ))
            await self._run_task_batches(fi_tasks, _get_concurrency("fi", 2), totals, "FI monthly backfill")

        # -- FIDC ---------------------------------------------------------
        if _want("fidc"):
            hist_years    = [y for y in years if y <= 2024]
            current_years = [y for y in years if y >= 2025]

            # Historical (2013–2024): yearly HIST/ ZIPs, tab_II + tab_III only.
            # Run one year at a time — each year downloads a single ZIP (~6-23 MB)
            # and iterates 12 months internally.
            for year in hist_years:
                n = await self.ingest_fidc_hist_mensal(year)
                totals["cvm_fidc_mensal"] += n

            # Current (2025+): monthly ZIPs with tab_IV, X_2, X_4, tab_VI.
            if current_years:
                mensal_tasks: List[IngestTask] = []
                tranche_tasks: List[IngestTask] = []
                for year, month in _iter_month_pairs(current_years, today):
                    mensal_tasks.append(IngestTask(
                        "cvm_fidc_mensal",
                        f"fidc/mensal {year}-{month:02d}",
                        self.ingest_fidc_mensal(year, month),
                    ))
                    tranche_tasks.extend([
                        IngestTask(
                            "cvm_fidc_tranche",
                            f"fidc/tranche {year}-{month:02d}",
                            self.ingest_fidc_tranche(year, month),
                        ),
                        IngestTask(
                            "cvm_fidc_tranche_flows",
                            f"fidc/tranche_flows {year}-{month:02d}",
                            self.ingest_fidc_tranche_flows(year, month),
                        ),
                        IngestTask(
                            "cvm_fidc_aging",
                            f"fidc/aging {year}-{month:02d}",
                            self.ingest_fidc_aging(year, month),
                        ),
                    ])
                await self._run_task_batches(
                    mensal_tasks,
                    _get_concurrency("fidc", 4),
                    totals,
                    "FIDC current mensal backfill",
                )
                await self._run_task_batches(
                    tranche_tasks,
                    _get_concurrency("fidc_tranche", 3),
                    totals,
                    "FIDC tranche backfill",
                )

        # -- FIAGRO monthly  (data only from 2025-05) ---------------------
        if _want("fiagro"):
            fiagro_tasks = [
                IngestTask(
                    "cvm_fiagro_mensal",
                    f"fiagro/mensal {year}-{month:02d}",
                    self.ingest_fiagro_mensal(year, month),
                )
                for year, month in _iter_month_pairs(years, today, available_from=_FIAGRO_FIRST_PERIOD)
            ]
            await self._run_task_batches(
                fiagro_tasks,
                _get_concurrency("fiagro", 10),
                totals,
                "FIAGRO backfill",
            )

        # -- FIP periodic -------------------------------------------------
        if _want("fip"):
            tasks: List[IngestTask] = []
            for entity, doc_type in FIP_PERIODIC_CONFIGS:
                for year in years:
                    tasks.append(IngestTask(
                        "cvm_fip_periodic",
                        f"fip/{doc_type} {year}",
                        self.ingest_fip_periodic(doc_type, year),
                    ))
            await self._run_task_batches(tasks, _get_concurrency("fip", 4), totals, "FIP backfill")

        # -- FII ----------------------------------------------------------
        if _want("fii"):
            tasks: List[IngestTask] = []
            for doc_type in FII_MENSAL_DOC_TYPES:
                for year in years:
                    tasks.append(IngestTask(
                        "cvm_fii_mensal",
                        f"fii/{doc_type} {year}",
                        self.ingest_fii_mensal(doc_type, year),
                    ))
            for doc_type in FII_PERIODIC_DOC_TYPES:
                for year in years:
                    tasks.append(IngestTask(
                        "cvm_fii_periodic",
                        f"fii/{doc_type} {year}",
                        self.ingest_fii_periodic(doc_type, year),
                    ))
            await self._run_task_batches(tasks, _get_concurrency("fii", 4), totals, "FII backfill")

        # -- SECURIT ------------------------------------------------------
        if _want("securit"):
            tasks: List[IngestTask] = []
            for t in SECURIT_MENSAL_TYPES:
                for year in years:
                    tasks.append(IngestTask(
                        "cvm_securit_mensal",
                        f"securit/{t} {year}",
                        self.ingest_securit_mensal(t, year),
                    ))
            for t in SECURIT_SERIE_TYPES:
                for year in years:
                    tasks.append(IngestTask(
                        "cvm_securit_serie",
                        f"securit/{t} {year}",
                        self.ingest_securit_serie(t, year),
                    ))
            for t in SECURIT_FLUXO_TYPES:
                for year in years:
                    tasks.append(IngestTask(
                        "cvm_securit_fluxo",
                        f"securit/{t} {year}",
                        self.ingest_securit_fluxo(t, year),
                    ))
            for t in SECURIT_DFIN_TYPES:
                for year in years:
                    tasks.append(IngestTask(
                        "cvm_securit_dfin",
                        f"securit/{t} {year}",
                        self.ingest_securit_dfin(t, year),
                    ))
            await self._run_task_batches(
                tasks,
                _get_concurrency("securit", 3),
                totals,
                "SECURIT backfill",
            )

        logger.info("Backfill complete: %s", totals)
        return totals

    async def daily_update(self) -> Dict[str, int]:
        """Incremental update: current month (and previous month for monthly files)."""
        today = date.today()
        year = today.year
        totals = _new_totals()
        tasks: List[IngestTask] = []
        daily_entities = _resolve_daily_entities()
        month_pairs = _daily_month_pairs(today)

        # Fund registry refresh (static cadastral — names/status may change)
        if "fi" in daily_entities:
            await self.ingest_fund_registry("fi")
        if "fii" in daily_entities:
            await self.ingest_fund_registry("fii")

        # FI — current + previous month
        if "fi" in daily_entities:
            for task_year, task_month in month_pairs:
                tasks += [
                    IngestTask("cvm_fi_diario", f"fi/inf_diario {task_year}-{task_month:02d}", self.ingest_fi_diario(task_year, task_month)),
                    IngestTask("cvm_fi_cda", f"fi/cda {task_year}-{task_month:02d}", self.ingest_fi_cda(task_year, task_month)),
                    IngestTask("cvm_fi_perfil", f"fi/perfil_mensal {task_year}-{task_month:02d}", self.ingest_fi_perfil(task_year, task_month)),
                ]

        # FIDC / FIAGRO — current + previous month
        for task_year, task_month in month_pairs:
            if "fidc" in daily_entities:
                tasks.extend([
                    IngestTask("cvm_fidc_mensal", f"fidc/mensal {task_year}-{task_month:02d}", self.ingest_fidc_mensal(task_year, task_month)),
                    IngestTask("cvm_fidc_tranche", f"fidc/tranche {task_year}-{task_month:02d}", self.ingest_fidc_tranche(task_year, task_month)),
                    IngestTask("cvm_fidc_tranche_flows", f"fidc/tranche_flows {task_year}-{task_month:02d}", self.ingest_fidc_tranche_flows(task_year, task_month)),
                    IngestTask("cvm_fidc_aging", f"fidc/aging {task_year}-{task_month:02d}", self.ingest_fidc_aging(task_year, task_month)),
                ])
            if "fiagro" in daily_entities and date(task_year, task_month, 1) >= _FIAGRO_FIRST_PERIOD:
                tasks.append(IngestTask(
                    "cvm_fiagro_mensal",
                    f"fiagro/mensal {task_year}-{task_month:02d}",
                    self.ingest_fiagro_mensal(task_year, task_month),
                ))

        # FIP — refresh current year
        if "fip" in daily_entities:
            for _, doc_type in FIP_PERIODIC_CONFIGS:
                tasks.append(IngestTask(
                    "cvm_fip_periodic",
                    f"fip/{doc_type} {year}",
                    self.ingest_fip_periodic(doc_type, year),
                ))

        # FII — refresh current year
        if "fii" in daily_entities:
            for doc_type in FII_MENSAL_DOC_TYPES:
                tasks.append(IngestTask(
                    "cvm_fii_mensal",
                    f"fii/{doc_type} {year}",
                    self.ingest_fii_mensal(doc_type, year),
                ))
            for doc_type in FII_PERIODIC_DOC_TYPES:
                tasks.append(IngestTask(
                    "cvm_fii_periodic",
                    f"fii/{doc_type} {year}",
                    self.ingest_fii_periodic(doc_type, year),
                ))

        # SECURIT — refresh current year
        if "securit" in daily_entities:
            for t in SECURIT_MENSAL_TYPES:
                tasks.append(IngestTask(
                    "cvm_securit_mensal",
                    f"securit/{t} {year}",
                    self.ingest_securit_mensal(t, year),
                ))
            for t in SECURIT_SERIE_TYPES:
                tasks.append(IngestTask(
                    "cvm_securit_serie",
                    f"securit/{t} {year}",
                    self.ingest_securit_serie(t, year),
                ))
            for t in SECURIT_FLUXO_TYPES:
                tasks.append(IngestTask(
                    "cvm_securit_fluxo",
                    f"securit/{t} {year}",
                    self.ingest_securit_fluxo(t, year),
                ))
            for t in SECURIT_DFIN_TYPES:
                tasks.append(IngestTask(
                    "cvm_securit_dfin",
                    f"securit/{t} {year}",
                    self.ingest_securit_dfin(t, year),
                ))

        await self._run_task_batches(
            tasks,
            _get_concurrency("daily", 6),
            totals,
            "Daily update",
        )

        logger.info("Daily update complete: %s", totals)
        return totals


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(description="CVM pipeline runner")
    sub = parser.add_subparsers(dest="cmd", required=True)

    bf = sub.add_parser("backfill", help="Historical backfill")
    bf.add_argument("--entity", help="fi | fidc | fip | fiagro | fii | securit (all if omitted)")
    bf.add_argument("--start", type=int, default=2019, help="Start year (default 2019)")
    bf.add_argument("--end", type=int, help="End year (default current year)")

    sub.add_parser("daily", help="Incremental daily update")

    args = parser.parse_args()
    ingestor = CVMIngestor()

    if args.cmd == "backfill":
        result = asyncio.run(ingestor.backfill(
            start_year=args.start,
            end_year=args.end,
            entity_filter=args.entity,
        ))
        print("Backfill complete:", result)
    elif args.cmd == "daily":
        result = asyncio.run(ingestor.daily_update())
        print("Daily update complete:", result)
