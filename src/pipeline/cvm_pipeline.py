"""
CVM data orchestrator — downloads entity/doc_type combinations and persists
to Supabase Postgres via per-entity ingest modules.

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
  cvm_securit_serie    SECURIT per-series characteristics
  cvm_securit_fluxo    SECURIT per-tranche cash flows
  cvm_securit_dfin     SECURIT CRA/CRI financial statements
  cvm_ingest_log       Audit log for every ingest run

Parsing is handled by per-entity thin modules in src/pipeline/ingest_*.py
using the declarative field maps in src/parsers/field_maps/.
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
from src.store.pg_client import get_pg_client, upsert_rows

# Per-entity ingest modules (parsing logic lives there)
from src.pipeline.ingest_fi import (
    ingest_fi_diario,
    ingest_fi_cda,
    ingest_fi_perfil,
    ingest_fi_balancete,
    ingest_fund_registry_fi,
)
from src.pipeline.ingest_fidc import (
    ingest_fidc_mensal,
    ingest_fidc_tranche,
    ingest_fidc_tranche_flows,
    ingest_fidc_aging,
    seed_fund_registry_from_hist,
)
from src.pipeline.ingest_fii import (
    ingest_fii_mensal,
    ingest_fii_periodic,
)
from src.pipeline.ingest_securit import (
    ingest_securit_mensal,
    ingest_securit_serie,
    ingest_securit_fluxo,
    ingest_securit_dfin,
)
from src.pipeline.ingest_misc import (
    ingest_fiagro_mensal,
    ingest_fip_periodic,
    ingest_fund_registry,
)
from src.pipeline.ingest_cia import (
    ingest_cia_company,
    ingest_cia_event,
    ingest_cia_account,
    ingest_cia_filing,
)
from src.fetchers.cia_fetcher import CIAFetcher

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Backward-compatibility shims for existing tests / callers
# These helpers were removed from this module in the W1 refactor; they live
# in src/parsers/mapping.py now but are re-exported here to avoid breaking
# any test or script that imported them from cvm_pipeline.
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
    val = _find_field(row, "TAB_VI_B_VL_DIRCRED_INAD", "TAB_VI_B_VL_TOTAL", "TAB_VI_VL_TOTAL_INAD")
    if val is not None:
        return val
    for k, v in row.items():
        if "inadimpl" in k.lower() or "delinq" in k.lower():
            return str(v) if v else None
    return None

# ---------------------------------------------------------------------------
# Entity / doc-type matrix  (only endpoints that actually exist on CVM server)
# ---------------------------------------------------------------------------

# FIDC / FIAGRO monthly
FIDC_MENSAL_ENTITY = "fidc"
FIAGRO_MENSAL_ENTITY = "fiagro"

# FIP yearly doc types
FIP_PERIODIC_CONFIGS: List[Tuple[str, str]] = [
    ("fip", "inf_trimestral"),      # 2010-2023
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
    "cia_company", "cia_event", "cia_filing", "cia_account",
    "cvm_fund_registry", "cvm_etf_registry",
]
_ALL_ENTITIES: Set[str] = {"fi", "fidc", "fip", "fiagro", "fii", "securit", "cia_aberta", "etf"}
# ETF is a distinct entity (curated registry, not a CVM dataset). It self-fetches
# the cad_fi it enriches from, so it is independent of the FI ingest and kept in
# core: the registry refresh is cheap and should run on every daily scope.
_CORE_DAILY_ENTITIES: Set[str] = {"fi", "fidc", "fiagro", "etf"}
_FIAGRO_FIRST_PERIOD = date(2025, 5, 1)

# CIA_ABERTA — IPE material-facts feed first availability (CVM publishes
# yearly ZIPs back to 2009 but the early years are sparse; the W6 backfill
# defaults to the start_year passed in unless callers override).
_CIA_IPE_FIRST_YEAR = 2010

# CIA_ABERTA — ITR/DFP financial statements backfill scope (W7). CVM publishes
# back to ~2010, but per the workstream brief the standard backfill loads
# 2019→present.
_CIA_ITR_DFP_FIRST_YEAR = 2019


@dataclass(frozen=True)
class IngestTask:
    table: str
    description: str
    operation: Awaitable[int]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


# Entities whose ingest invalidates the materialized ETF metrics. etf_daily is a
# matview over cvm_fi_diario joined to cvm_etf_registry, so an FI-only run makes
# it stale just as an ETF-registry run does.
_ETF_REFRESH_ENTITIES: Set[str] = {"etf", "fi"}


def _etf_refresh_disabled() -> bool:
    """True when the ETF matview refresh is deferred to an external step.

    The CI historical-backfill matrix sets CVM_SKIP_ETF_REFRESH so the parallel
    FI/ETF jobs do not each refresh; a single final job refreshes once after all
    of them complete. Unset everywhere else (daily, repair/one-off backfills), so
    those single-process runs refresh in-line.
    """
    return os.getenv("CVM_SKIP_ETF_REFRESH", "").strip().lower() in {"1", "true", "yes"}


def _daily_month_pairs(today: date) -> List[Tuple[int, int]]:
    current = (today.year, today.month)
    if today.month == 1:
        previous = (today.year - 1, 12)
    else:
        previous = (today.year, today.month - 1)
    return [previous, current] if previous != current else [current]


# How many trailing months a daily run probes for monthly datasets. CVM lags
# publication by 1-2 months, so a fixed current+previous window misses a slice
# until the day it is published and then never revisits it. A bounded trailing
# window (default 4 months) self-heals that recent lag without re-fetching deep
# history every day — deep history is run_backfill's job. Clamped to >= 2 so the
# window always covers at least current + previous.
# Parsed via _env_int (the house helper) so a misconfigured value warns and falls
# back instead of crashing import; clamped to >= 2 so the window always covers at
# least current + previous.
_DAILY_LOOKBACK_MONTHS = max(2, _env_int("CVM_DAILY_LOOKBACK_MONTHS", 4))


def _trailing_months(today: date, lookback: int) -> List[Tuple[int, int]]:
    """The last `lookback` (year, month) pairs ending at `today`, oldest first."""
    months: List[Tuple[int, int]] = []
    y, m = today.year, today.month
    for _ in range(max(1, lookback)):
        months.append((y, m))
        m -= 1
        if m == 0:
            m, y = 12, y - 1
    return list(reversed(months))


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


# ---------------------------------------------------------------------------
# Ingestor class
# ---------------------------------------------------------------------------

class CVMIngestor:
    """Downloads CVM data via CVMFetcher and persists to Supabase Postgres."""

    def __init__(self) -> None:
        self._service = CVMFetcher()
        self._cia_fetcher = CIAFetcher()
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

        limit = max(1, concurrency)
        logger.info("%s: %d tasks (concurrency=%d)", label, len(tasks), limit)

        # Semaphore-bounded scheduling: keep up to `limit` tasks in flight at all
        # times instead of fixed batches, so a slow task never stalls the others
        # waiting in the same batch (head-of-line blocking).
        sem = asyncio.Semaphore(limit)

        async def _run(task: IngestTask):
            async with sem:
                return await task.operation

        results = await asyncio.gather(
            *[_run(task) for task in tasks],
            return_exceptions=True,
        )
        for task, result in zip(tasks, results):
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
        # A 404 for a not-yet-published month is an expected non-event, not a
        # failure. The daily window probes a trailing range (see _monthly_targets)
        # and CVM lags publication by 1-2 months, so the leading months 404. The
        # fetcher raises ValueError("Data not found at <url>") on 404; record that
        # as 'skipped' so it isn't a false error and so staleness checks (which
        # count only 'ok') don't treat the slice as loaded. Any other error —
        # including a malformed ZIP ("No CSV file found …") — stays 'error'.
        if error and "Data not found" in error:
            status = "skipped"
        elif error:
            status = "error"
        else:
            status = "ok"
        # The shared connection may have idled out during a long fetch (CVM
        # hangs of 15+ min killed it in the 2026-06-10 backfill, leaving every
        # slice stuck 'running'). Reconnect once and retry so the audit log
        # reflects what actually happened; still best-effort after that.
        for attempt in (1, 2):
            try:
                with self._supabase.cursor() as cur:
                    cur.execute(
                        "UPDATE cvm_ingest_log SET rows_upserted=%s, status=%s,"
                        " error_msg=%s, finished_at=%s WHERE run_id=%s",
                        (
                            rows,
                            status,
                            error,
                            datetime.now(timezone.utc).isoformat(),
                            run_id,
                        ),
                    )
                return
            except Exception as e:
                if attempt == 1:
                    logger.warning(
                        "ingest_log finish failed (%s) — reconnecting to retry", e
                    )
                    try:
                        self._supabase.reconnect()
                    except Exception as reconnect_exc:
                        logger.warning(
                            "ingest_log finish reconnect failed: %s", reconnect_exc
                        )
                        return
                else:
                    logger.warning("ingest_log finish failed after reconnect: %s", e)

    def _monthly_targets(self, entity: str, doc_type: str, today: date) -> List[Tuple[int, int]]:
        """Months a daily run should fetch for a monthly (entity, doc_type).

        Always includes the current and previous month — the current source file
        grows daily and the previous one may have just been finalised. Adds any
        month inside the trailing CVM_DAILY_LOOKBACK_MONTHS window that has no
        successful prior ingest (cvm_ingest_log row with status='ok' and
        rows_upserted > 0), so a slice CVM publishes late is picked up on the next
        run instead of being missed forever. Bounded by the window, so it heals
        recent lag without re-fetching deep history. The (entity, doc_type) pair
        must match the strings the ingest method logs via _log_start. On any DB
        error it degrades to current + previous only.
        """
        base = set(_daily_month_pairs(today))
        window = _trailing_months(today, _DAILY_LOOKBACK_MONTHS)
        try:
            years = sorted({y for y, _ in window})
            with self._supabase.cursor() as cur:
                # rows_upserted > 0 is deliberate: an 'ok' run that wrote 0 rows
                # is an empty/partial publish, not a loaded slice. Treating it as a
                # gap means a month CVM first publishes empty (or partially) gets
                # revisited until it actually has data — re-fetching it within the
                # bounded window is far cheaper than silently missing the slice,
                # which is the exact failure this window exists to prevent. For
                # these aggregate datasets a genuinely-final 0-row month is rare.
                cur.execute(
                    "SELECT DISTINCT period_year, period_month FROM cvm_ingest_log"
                    " WHERE entity=%s AND doc_type=%s AND status='ok'"
                    " AND rows_upserted > 0 AND period_month IS NOT NULL"
                    " AND period_year = ANY(%s)",
                    (entity, doc_type, years),
                )
                loaded = {(py, pm) for py, pm in cur.fetchall()}
        except Exception as e:
            logger.warning(
                "monthly gap-check failed for %s/%s (%s); using current+previous only",
                entity, doc_type, e,
            )
            return sorted(base)
        gaps = {ym for ym in window if ym not in loaded}
        return sorted(base | gaps)

    def _refresh_etf_metrics(self) -> None:
        """Refresh the materialized ETF views after an ETF ingest.

        etf_daily / etf_latest are materialized views (migration 06); refreshing
        here keeps their precomputed metrics current. The pg client runs in
        autocommit, so REFRESH ... CONCURRENTLY — which must not run inside a
        transaction block — is valid and avoids blocking readers. etf_latest is
        derived from etf_daily, so refresh etf_daily first.
        """
        try:
            with self._supabase.cursor() as cur:
                cur.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY etf_daily")
                cur.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY etf_latest")
            logger.info("etf metrics: refreshed etf_daily + etf_latest")
        except Exception as e:
            logger.warning("refresh etf materialized views failed: %s", e)

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
            rows_inserted = ingest_fi_diario(self._supabase, raw_rows)
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

        Flushes every _PAGE_SIZE records to keep peak memory manageable.
        """
        run_id = str(uuid4())
        self._log_start(run_id, "fi", "inf_diario", year, None)
        rows_inserted = 0
        try:
            raw_rows = await self._fetch_all_pages("fi", "hist_inf_diario", year, None)
            # Flush in chunks to bound peak memory
            chunk: List[Dict[str, Any]] = []
            for row in raw_rows:
                chunk.append(row)
                if len(chunk) >= _PAGE_SIZE:
                    rows_inserted += ingest_fi_diario(self._supabase, chunk)
                    chunk = []
            if chunk:
                rows_inserted += ingest_fi_diario(self._supabase, chunk)
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
            # Flush in chunks; use month=1 as placeholder (period normalised in ingest_fi_cda)
            chunk: List[Dict[str, Any]] = []
            for row in raw_rows:
                chunk.append(row)
                if len(chunk) >= _PAGE_SIZE:
                    # For HIST, DT_COMPTC contains the actual date — ingest_fi_cda
                    # will read it from the field map and normalise to first-of-month.
                    # We pass year=0, month=1 so the fallback is safe; apply_map
                    # reads DT_COMPTC directly.
                    rows_inserted += ingest_fi_cda(self._supabase, chunk, year, 1)
                    chunk = []
            if chunk:
                rows_inserted += ingest_fi_cda(self._supabase, chunk, year, 1)
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
            rows_inserted = ingest_fi_cda(self._supabase, raw_rows, year, month)
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
            rows_inserted = ingest_fi_perfil(self._supabase, raw_rows, year, month)
        except Exception as exc:
            logger.warning("ingest_fi_perfil %d-%02d failed: %s", year, month, exc)
            self._log_finish(run_id, 0, str(exc))
            return 0
        self._log_finish(run_id, rows_inserted)
        logger.info("fi/perfil_mensal %d-%02d: %d rows", year, month, rows_inserted)
        return rows_inserted

    # ------------------------------------------------------------------
    # FI — monthly balance sheet  (BALANCETE)
    # ------------------------------------------------------------------

    async def ingest_fi_balancete(self, year: int, month: int) -> int:
        run_id = str(uuid4())
        self._log_start(run_id, "fi", "balancete", year, month)
        rows_inserted = 0
        try:
            raw_rows = await self._fetch_all_pages("fi", "balancete", year, month)
            rows_inserted = ingest_fi_balancete(self._supabase, raw_rows)
        except Exception as exc:
            logger.warning("ingest_fi_balancete %d-%02d failed: %s", year, month, exc)
            self._log_finish(run_id, 0, str(exc))
            return 0
        self._log_finish(run_id, rows_inserted)
        logger.info("fi/balancete %d-%02d: %d rows", year, month, rows_inserted)
        return rows_inserted

    # ------------------------------------------------------------------
    # FIDC — monthly snapshot (current 2025+ format)
    # ------------------------------------------------------------------

    async def ingest_fidc_mensal(self, year: int, month: int) -> int:
        run_id = str(uuid4())
        self._log_start(run_id, "fidc", "mensal", year, month)
        rows_inserted = 0
        try:
            raw_rows = await self._fetch_all_pages("fidc", "mensal", year, month)
            rows_inserted = ingest_fidc_mensal(self._supabase, raw_rows)
        except Exception as exc:
            logger.warning("ingest_fidc_mensal %d-%02d failed: %s", year, month, exc)
            self._log_finish(run_id, 0, str(exc))
            return 0
        self._log_finish(run_id, rows_inserted)
        logger.info("fidc/mensal %d-%02d: %d rows", year, month, rows_inserted)
        return rows_inserted

    # ------------------------------------------------------------------
    # FIDC — historical monthly data (2013-2024) from HIST/ yearly ZIPs
    # ------------------------------------------------------------------

    async def ingest_fidc_hist_mensal(self, year: int) -> int:
        """Ingest one full year of historical FIDC monthly data from HIST/."""
        total = 0
        for month in range(1, 13):
            run_id = str(uuid4())
            self._log_start(run_id, "fidc", "mensal", year, month)
            rows_inserted = 0
            try:
                rows_ii, rows_iii = await asyncio.gather(
                    self._fetch_all_pages("fidc", "hist_mensal_tab_ii", year, month),
                    self._fetch_all_pages("fidc", "hist_mensal_tab_iii", year, month),
                )

                # Seed fund registry from tab_II DENOM_SOCIAL
                seed_fund_registry_from_hist(self._supabase, rows_ii)

                # Build liabilities index from tab_III for PL approximation
                from src.parsers.mapping import apply_map
                from src.parsers.field_maps import fidc_mensal as _fm_mensal
                liab: Dict[tuple, float] = {}
                for row in rows_iii:
                    from src.parsers.mapping import apply_map as _am
                    typed_iii, _ = _am(row, _fm_mensal.FIELD_MAP)
                    cnpj = typed_iii.get("cnpj") or ""
                    period = typed_iii.get("period")
                    try:
                        liab[(cnpj, period)] = float(row.get("TAB_III_VL_PASSIVO") or 0)
                    except (ValueError, TypeError):
                        liab[(cnpj, period)] = 0.0

                # Build mensal records from tab_II
                records: List[Dict[str, Any]] = []
                for row in rows_ii:
                    typed_ii, residual = apply_map(row, _fm_mensal.FIELD_MAP)
                    cnpj = typed_ii.get("cnpj") or ""
                    period = typed_ii.get("period")
                    # Drop rows missing either natural-key part — a single NULL
                    # period (blank DT_COMPTC in the HIST CSV) would otherwise
                    # fail the NOT NULL constraint and roll back the whole
                    # month's upsert. Same guard as ingest_fidc_mensal.
                    if not cnpj or not period:
                        continue
                    try:
                        vl_carteira = float(row.get("TAB_II_VL_CARTEIRA") or 0)
                    except (ValueError, TypeError):
                        vl_carteira = 0.0
                    vl_passivo = liab.get((cnpj, period), 0.0)
                    vl_pl = vl_carteira - vl_passivo if vl_carteira else None
                    records.append({
                        "cnpj":          cnpj,
                        "period":        period,
                        "vl_total":      vl_carteira if vl_carteira else None,
                        "vl_quota":      None,
                        "vl_patrim_liq": vl_pl,
                        "vl_inadimpl":   None,
                        "nr_cotst":      None,
                        "raw":           residual,
                    })

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
        run_id = str(uuid4())
        self._log_start(run_id, "fidc", "mensal_tab_x2", year, month)
        rows_inserted = 0
        try:
            rows_x2, rows_x3, rows_x6 = await asyncio.gather(
                self._fetch_all_pages("fidc", "mensal_tab_X2", year, month),
                self._fetch_all_pages("fidc", "mensal_tab_X3", year, month),
                self._fetch_all_pages("fidc", "mensal_tab_X6", year, month),
            )
            rows_inserted = ingest_fidc_tranche(
                self._supabase, rows_x2, rows_x3, rows_x6, year, month
            )
        except Exception as exc:
            logger.warning("ingest_fidc_tranche %d-%02d failed: %s", year, month, exc)
            self._log_finish(run_id, 0, str(exc))
            return 0
        self._log_finish(run_id, rows_inserted)
        logger.info("fidc/tranche %d-%02d: %d rows", year, month, rows_inserted)
        return rows_inserted

    async def ingest_fidc_tranche_flows(self, year: int, month: int) -> int:
        run_id = str(uuid4())
        self._log_start(run_id, "fidc", "mensal_tab_x4", year, month)
        rows_inserted = 0
        try:
            raw_rows = await self._fetch_all_pages("fidc", "mensal_tab_X4", year, month)
            rows_inserted = ingest_fidc_tranche_flows(self._supabase, raw_rows)
        except Exception as exc:
            logger.warning("ingest_fidc_tranche_flows %d-%02d failed: %s", year, month, exc)
            self._log_finish(run_id, 0, str(exc))
            return 0
        self._log_finish(run_id, rows_inserted)
        logger.info("fidc/tranche_flows %d-%02d: %d rows", year, month, rows_inserted)
        return rows_inserted

    async def ingest_fidc_aging(self, year: int, month: int) -> int:
        run_id = str(uuid4())
        self._log_start(run_id, "fidc", "mensal_tab_vi", year, month)
        rows_inserted = 0
        try:
            raw_rows = await self._fetch_all_pages("fidc", "mensal_tab_VI", year, month)
            rows_inserted = ingest_fidc_aging(self._supabase, raw_rows)
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
            rows_inserted = ingest_fiagro_mensal(self._supabase, raw_rows)
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
            rows_inserted = ingest_fip_periodic(self._supabase, raw_rows, doc_type, year)
        except Exception as exc:
            logger.warning("ingest_fip_periodic %s %d failed: %s", doc_type, year, exc)
            self._log_finish(run_id, 0, str(exc))
            return 0
        self._log_finish(run_id, rows_inserted)
        logger.info("fip/%s %d: %d rows", doc_type, year, rows_inserted)
        return rows_inserted

    # ------------------------------------------------------------------
    # FII — monthly (mensal_geral, mensal_ativo_passivo, mensal_complemento)
    # ------------------------------------------------------------------

    async def ingest_fii_mensal(self, doc_type: str, year: int) -> int:
        """doc_type is one of: mensal_geral | mensal_ativo_passivo | mensal_complemento."""
        run_id = str(uuid4())
        self._log_start(run_id, "fii", doc_type, year, None)
        rows_inserted = 0
        try:
            raw_rows = await self._fetch_all_pages("fii", doc_type, year, None)
            rows_inserted = ingest_fii_mensal(self._supabase, raw_rows, doc_type)
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
            rows_inserted = ingest_fii_periodic(self._supabase, raw_rows, doc_type, year)
        except Exception as exc:
            logger.warning("ingest_fii_periodic %s %d failed: %s", doc_type, year, exc)
            self._log_finish(run_id, 0, str(exc))
            return 0
        self._log_finish(run_id, rows_inserted)
        logger.info("fii/%s %d: %d rows", doc_type, year, rows_inserted)
        return rows_inserted

    # ------------------------------------------------------------------
    # Fund registry — DENOM_SOCIAL + status from CVM cadastral files
    # ------------------------------------------------------------------

    async def ingest_fund_registry(self, entity: str) -> int:
        """Ingest fund registry from CVM cadastral static CSVs for fi and fii."""
        if entity not in ("fi", "fii"):
            return 0
        run_id = str(uuid4())
        self._log_start(run_id, entity, "cad", None, None)
        rows_inserted = 0
        try:
            raw_rows = await self._fetch_all_pages(entity, "cad", None, None)
            if entity == "fi":
                rows_inserted = ingest_fund_registry_fi(self._supabase, raw_rows)
            else:
                rows_inserted = ingest_fund_registry(self._supabase, raw_rows, entity)
        except Exception as exc:
            logger.warning("ingest_fund_registry %s failed: %s", entity, exc)
            self._log_finish(run_id, 0, str(exc))
            return 0
        self._log_finish(run_id, rows_inserted)
        logger.info("%s/cad: %d rows", entity, rows_inserted)
        return rows_inserted

    async def ingest_fund_registry_cvm175(self) -> int:
        """Ingest the CVM-175 unified registry (registro_fundo + registro_classe).

        Covers the post-2023 active universe across all fund families; entity_type
        and is_active are derived per row. Runs after the legacy cad ingest so the
        current CVM-175 status wins for any shared CNPJ.
        """
        from src.pipeline.ingest_misc import ingest_fund_registry_cvm175

        total = 0
        for doc_type in ("registro_fundo", "registro_classe"):
            run_id = str(uuid4())
            self._log_start(run_id, "fi", doc_type, None, None)
            rows = 0
            try:
                raw_rows = await self._fetch_all_pages("fi", doc_type, None, None)
                rows = ingest_fund_registry_cvm175(self._supabase, raw_rows)
            except Exception as exc:
                logger.warning("ingest_fund_registry_cvm175 %s failed: %s", doc_type, exc)
                self._log_finish(run_id, 0, str(exc))
                continue
            self._log_finish(run_id, rows)
            logger.info("fi/%s: %d rows", doc_type, rows)
            total += rows
        return total

    # ------------------------------------------------------------------
    # ETF registry — curated ticker->CNPJ seed enriched from cad_fi
    # ------------------------------------------------------------------

    async def ingest_etf_registry(self) -> int:
        """Load the curated ETF seed, enrich from cad_fi, upsert cvm_etf_registry."""
        from src.pipeline.ingest_etf import load_etf_seed, ingest_etf_registry

        run_id = str(uuid4())
        self._log_start(run_id, "etf", "registry", None, None)
        rows_inserted = 0
        try:
            seed = load_etf_seed()
            cad_rows = await self._fetch_all_pages("fi", "cad", None, None)
            rows_inserted = ingest_etf_registry(self._supabase, seed, cad_rows)
        except Exception as exc:
            logger.warning("ingest_etf_registry failed: %s", exc)
            self._log_finish(run_id, 0, str(exc))
            return 0
        self._log_finish(run_id, rows_inserted)
        logger.info("etf/registry: %d rows", rows_inserted)
        return rows_inserted

    # ------------------------------------------------------------------
    # SECURIT — per-series data (classe CSV) and cash flows (fluxo_caixa CSV)
    # ------------------------------------------------------------------

    async def ingest_securit_serie(self, doc_type: str, year: int) -> int:
        run_id = str(uuid4())
        self._log_start(run_id, "securit", doc_type, year, None)
        rows_inserted = 0
        try:
            raw_rows = await self._fetch_all_pages("securit", doc_type, year, None)
            rows_inserted = ingest_securit_serie(self._supabase, raw_rows, doc_type, year)
        except Exception as exc:
            logger.warning("ingest_securit_serie %s %d failed: %s", doc_type, year, exc)
            self._log_finish(run_id, 0, str(exc))
            return 0
        self._log_finish(run_id, rows_inserted)
        logger.info("securit/%s %d: %d rows", doc_type, year, rows_inserted)
        return rows_inserted

    async def ingest_securit_fluxo(self, doc_type: str, year: int) -> int:
        run_id = str(uuid4())
        self._log_start(run_id, "securit", doc_type, year, None)
        rows_inserted = 0
        try:
            raw_rows = await self._fetch_all_pages("securit", doc_type, year, None)
            rows_inserted = ingest_securit_fluxo(self._supabase, raw_rows, doc_type, year)
        except Exception as exc:
            logger.warning("ingest_securit_fluxo %s %d failed: %s", doc_type, year, exc)
            self._log_finish(run_id, 0, str(exc))
            return 0
        self._log_finish(run_id, rows_inserted)
        logger.info("securit/%s %d: %d rows", doc_type, year, rows_inserted)
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
            rows_inserted = ingest_securit_mensal(self._supabase, raw_rows, instrument_type, year)
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
            rows_inserted = ingest_securit_dfin(self._supabase, raw_rows, instrument_type, year)
        except Exception as exc:
            logger.warning("ingest_securit_dfin %s %d failed: %s", instrument_type, year, exc)
            self._log_finish(run_id, 0, str(exc))
            return 0
        self._log_finish(run_id, rows_inserted)
        logger.info("securit/%s %d: %d rows", instrument_type, year, rows_inserted)
        return rows_inserted

    # ------------------------------------------------------------------
    # CIA_ABERTA — company registry (CAD, static single CSV)
    # ------------------------------------------------------------------

    async def ingest_cia_cad(self) -> int:
        """Ingest the listed-company registry from cad_cia_aberta.csv.

        CAD is a single static CSV (no year/month). Run once per backfill
        and once per daily-update invocation. Follows the same shape as
        ingest_fund_registry.
        """
        run_id = str(uuid4())
        self._log_start(run_id, "cia_aberta", "cad", None, None)
        rows_inserted = 0
        try:
            raw_rows = await self._fetch_all_pages("cia_aberta", "cad", None, None)
            rows_inserted = ingest_cia_company(self._supabase, raw_rows)
        except Exception as exc:
            logger.warning("ingest_cia_cad failed: %s", exc)
            self._log_finish(run_id, 0, str(exc))
            return 0
        self._log_finish(run_id, rows_inserted)
        logger.info("cia_aberta/cad: %d rows", rows_inserted)
        return rows_inserted

    # ------------------------------------------------------------------
    # CIA_ABERTA — IPE material-facts feed (yearly ZIP, one CSV inside)
    # ------------------------------------------------------------------

    async def ingest_cia_ipe(self, year: int) -> int:
        """Ingest one full year of IPE press events into cia_event."""
        run_id = str(uuid4())
        self._log_start(run_id, "cia_aberta", "ipe", year, None)
        rows_inserted = 0
        try:
            raw_rows = await self._fetch_all_pages("cia_aberta", "ipe", year, None)
            rows_inserted = ingest_cia_event(self._supabase, raw_rows)
        except Exception as exc:
            logger.warning("ingest_cia_ipe %d failed: %s", year, exc)
            self._log_finish(run_id, 0, str(exc))
            return 0
        self._log_finish(run_id, rows_inserted)
        logger.info("cia_aberta/ipe %d: %d rows", year, rows_inserted)
        return rows_inserted

    # ------------------------------------------------------------------
    # CIA_ABERTA — ITR / DFP financial statements (yearly ZIP, ~19 CSVs)
    # ------------------------------------------------------------------

    async def ingest_cia_itr_dfp(self, doc_type: str, year: int) -> int:
        """Ingest one yearly ITR or DFP ZIP into cia_filing + cia_account.

        Downloads the multi-CSV archive, routes the summary header to cia_filing
        and the scoped statement members (BPA/BPP/DRE/DFC_*/DMPL/DRA/DVA × con/ind)
        to cia_account. Returns the combined upserted row count.
        """
        run_id = str(uuid4())
        self._log_start(run_id, "cia_aberta", doc_type, year, None)
        rows_inserted = 0
        try:
            members = await self._cia_fetcher.fetch_zip_members_async(
                doc_type, year, include_summary=True
            )
            summary_rows: List[Dict[str, Any]] = []
            account_members = 0
            for m in members:
                if m.is_summary:
                    summary_rows.extend(m.rows)
                elif m.is_account_data:
                    account_members += 1
            rows_inserted += ingest_cia_filing(self._supabase, summary_rows, doc_type)
            rows_inserted += ingest_cia_account(self._supabase, members, doc_type)
            # A real ITR/DFP ZIP always has account members; zero rows from a
            # non-empty publish year signals a bad/truncated fetch (see the
            # serial-only note in backfill) rather than a genuine empty year.
            if rows_inserted == 0 or account_members == 0:
                logger.warning(
                    "cia_aberta/%s %d: suspicious empty load (members=%d, account_members=%d) "
                    "— likely a bad fetch; re-run this slice serially",
                    doc_type, year, len(members), account_members,
                )
        except Exception as exc:
            logger.warning("ingest_cia_itr_dfp %s %d failed: %s", doc_type, year, exc)
            self._log_finish(run_id, 0, str(exc))
            return 0
        self._log_finish(run_id, rows_inserted)
        logger.info("cia_aberta/%s %d: %d rows", doc_type, year, rows_inserted)
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
        """Full historical backfill for all entities from start_year to today.

        Pass entity_filter to restrict to one entity: fi | fidc | fip | fiagro | fii | securit | etf
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
                totals["cvm_fund_registry"] += await self.ingest_fund_registry(entity)

        # -- CVM-175 unified registry (active universe, all fund families) --
        if _want("fi"):
            totals["cvm_fund_registry"] += await self.ingest_fund_registry_cvm175()

        # -- ETF registry (distinct entity: curated seed, self-fetches cad_fi) --
        if _want("etf"):
            totals["cvm_etf_registry"] += await self.ingest_etf_registry()

        # -- FI ----------------------------------------------------------
        if _want("fi"):
            hist_diario_years = [y for y in years if y <= 2020]
            hist_cda_years    = [y for y in years if y <= 2022]
            monthly_years     = years

            for year in hist_diario_years:
                n = await self.ingest_fi_hist_diario(year)
                totals["cvm_fi_diario"] += n

            for year in hist_cda_years:
                n = await self.ingest_fi_hist_cda(year)
                totals["cvm_fi_cda"] += n

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

            for year in hist_years:
                n = await self.ingest_fidc_hist_mensal(year)
                totals["cvm_fidc_mensal"] += n

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

        # -- CIA_ABERTA ---------------------------------------------------
        # CAD: single static file — run once.
        # IPE: one yearly ZIP per year.
        if _want("cia_aberta"):
            n_cad = await self.ingest_cia_cad()
            totals["cia_company"] += n_cad

            cia_years = [y for y in years if y >= _CIA_IPE_FIRST_YEAR]
            cia_tasks: List[IngestTask] = [
                IngestTask(
                    "cia_event",
                    f"cia_aberta/ipe {year}",
                    self.ingest_cia_ipe(year),
                )
                for year in cia_years
            ]
            await self._run_task_batches(
                cia_tasks,
                _get_concurrency("cia_aberta", 3),
                totals,
                "CIA_ABERTA backfill",
            )

            # ITR (quarterly) + DFP (annual) financial statements, 2019→present.
            # Combined cia_filing + cia_account rows are attributed to
            # cia_account (the dominant table); filing headers are a small
            # fraction.
            #
            # These ZIPs are the largest in the whole pipeline (~19 members,
            # millions of line items each). Running them concurrently caused the
            # CVM endpoint to intermittently return content that yielded ZERO
            # rows without raising (observed: 8/16 slices silently empty at
            # concurrency 2). They are therefore loaded STRICTLY SERIALLY — do
            # not raise this above 1.
            itr_dfp_years = [y for y in years if y >= _CIA_ITR_DFP_FIRST_YEAR]
            fin_tasks: List[IngestTask] = []
            for year in itr_dfp_years:
                for doc_type in ("itr", "dfp"):
                    fin_tasks.append(IngestTask(
                        "cia_account",
                        f"cia_aberta/{doc_type} {year}",
                        self.ingest_cia_itr_dfp(doc_type, year),
                    ))
            await self._run_task_batches(
                fin_tasks,
                1,  # serial — see comment above; concurrency here loses data
                totals,
                "CIA_ABERTA ITR/DFP backfill",
            )

        # Refresh the materialized ETF metrics once the underlying data is in.
        # etf_daily is a matview over cvm_fi_diario, so an FI-only backfill makes
        # it stale too — refresh when either entity ran. CI's parallel matrix
        # defers this to a single final job (CVM_SKIP_ETF_REFRESH).
        if any(_want(e) for e in _ETF_REFRESH_ENTITIES) and not _etf_refresh_disabled():
            self._refresh_etf_metrics()

        logger.info("Backfill complete: %s", totals)
        return totals

    async def daily_update(self) -> Dict[str, int]:
        """Incremental update: current month (and previous month for monthly files)."""
        today = date.today()
        year = today.year
        totals = _new_totals()
        tasks: List[IngestTask] = []
        daily_entities = _resolve_daily_entities()

        # Fund registry refresh
        if "fi" in daily_entities:
            totals["cvm_fund_registry"] += await self.ingest_fund_registry("fi")
        if "fii" in daily_entities:
            totals["cvm_fund_registry"] += await self.ingest_fund_registry("fii")

        # CVM-175 unified registry refresh (active universe, all fund families)
        if "fi" in daily_entities:
            totals["cvm_fund_registry"] += await self.ingest_fund_registry_cvm175()

        # ETF registry refresh (distinct entity: curated seed, self-fetches cad_fi)
        if "etf" in daily_entities:
            totals["cvm_etf_registry"] += await self.ingest_etf_registry()

        # FI / FIDC / FIAGRO monthly datasets — gap-aware trailing window.
        # Each spec is (table, log_entity, log_doc_type, label, method). log_entity
        # and log_doc_type MUST match the strings the method passes to _log_start,
        # so _monthly_targets can tell which months are already loaded; label is
        # the friendlier name used in the task description. _monthly_targets always
        # yields current + previous month and self-heals recently-published gaps.
        monthly_specs: List[Tuple[str, str, str, str, Any]] = []
        if "fi" in daily_entities:
            monthly_specs += [
                ("cvm_fi_diario", "fi", "inf_diario", "inf_diario", self.ingest_fi_diario),
                ("cvm_fi_cda", "fi", "cda", "cda", self.ingest_fi_cda),
                ("cvm_fi_perfil", "fi", "perfil_mensal", "perfil_mensal", self.ingest_fi_perfil),
            ]
        if "fidc" in daily_entities:
            monthly_specs += [
                ("cvm_fidc_mensal", "fidc", "mensal", "mensal", self.ingest_fidc_mensal),
                ("cvm_fidc_tranche", "fidc", "mensal_tab_x2", "tranche", self.ingest_fidc_tranche),
                ("cvm_fidc_tranche_flows", "fidc", "mensal_tab_x4", "tranche_flows", self.ingest_fidc_tranche_flows),
                ("cvm_fidc_aging", "fidc", "mensal_tab_vi", "aging", self.ingest_fidc_aging),
            ]
        if "fiagro" in daily_entities:
            monthly_specs.append(
                ("cvm_fiagro_mensal", "fiagro", "mensal", "mensal", self.ingest_fiagro_mensal)
            )

        for table, log_entity, log_doc_type, label, method in monthly_specs:
            for task_year, task_month in self._monthly_targets(log_entity, log_doc_type, today):
                if log_entity == "fiagro" and date(task_year, task_month, 1) < _FIAGRO_FIRST_PERIOD:
                    continue
                tasks.append(IngestTask(
                    table,
                    f"{log_entity}/{label} {task_year}-{task_month:02d}",
                    method(task_year, task_month),
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

        # CIA_ABERTA — refresh registry (once), current year IPE feed, and the
        # current-year ITR + DFP financial statements.
        if "cia_aberta" in daily_entities:
            await self.ingest_cia_cad()
            tasks.append(IngestTask(
                "cia_event",
                f"cia_aberta/ipe {year}",
                self.ingest_cia_ipe(year),
            ))
            for doc_type in ("itr", "dfp"):
                tasks.append(IngestTask(
                    "cia_account",
                    f"cia_aberta/{doc_type} {year}",
                    self.ingest_cia_itr_dfp(doc_type, year),
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

        # Refresh the materialized ETF metrics once the day's data is in — when
        # the ETF registry OR its underlying FI daily rows were ingested.
        if (daily_entities & _ETF_REFRESH_ENTITIES) and not _etf_refresh_disabled():
            self._refresh_etf_metrics()

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
    bf.add_argument("--entity", help="fi | fidc | fip | fiagro | fii | securit | cia_aberta | etf (all if omitted)")
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
