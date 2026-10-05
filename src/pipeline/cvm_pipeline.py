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
from src.pipeline.ingest_log import describe, finish as _finish_row, lineage
from src.pipeline import daily_window

# Per-entity ingest modules (parsing logic lives there)
from src.pipeline.ingest_fi import (
    ingest_fi_diario,
    ingest_fi_cda,
    ingest_fi_cda_acoes,
    ingest_fi_cda_debentures,
    ingest_fi_lamina,
    ingest_fi_extrato,
    ingest_fi_cda_cotas,
    ingest_fi_perfil,
    ingest_fi_balancete,
    ingest_fund_registry_fi,
)
from src.pipeline.ingest_fidc import (
    ingest_fidc_mensal,
    ingest_fidc_tranche,
    ingest_fidc_tranche_flows,
    ingest_fidc_aging,
    ingest_fidc_setor,
    ingest_fidc_scr,
    ingest_fidc_sacado,
    ingest_fidc_cedente,
    ingest_fidc_garantia,
    inadimpl_by_key,
    seed_fund_registry_from_hist,
)
from src.pipeline.ingest_fii import (
    ingest_fii_mensal,
    ingest_fii_periodic,
    ingest_fii_imovel,
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
    ingest_cia_ticker,
)
from src.fetchers.cia_fetcher import CIAFetcher

logger = logging.getLogger(__name__)


# One renderer for every audit writer — see src/pipeline/ingest_log.describe.
_describe = describe

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
# 'trimestral' is retired: it named a ZIP member that does not exist, so it was
# silently ingesting the alienacao-imovel member (see migration 15). The archive
# is multi-table, so each useful member is its own doc_type. trimestral_imovel is
# NOT here — it has a different grain and its own ingest method/table.
FII_PERIODIC_DOC_TYPES: List[str] = [
    "trimestral_geral", "trimestral_complemento", "anual", "dfin",
]

# SECURIT doc types split by target table
SECURIT_MENSAL_TYPES: List[str] = ["cra_mensal", "cri_mensal", "ots_mensal"]
SECURIT_DFIN_TYPES: List[str] = ["dfin_cra", "dfin_cri"]
SECURIT_SERIE_TYPES: List[str] = ["cra_classe", "cri_classe", "ots_classe"]
SECURIT_FLUXO_TYPES: List[str] = ["cra_fluxo", "cri_fluxo", "ots_fluxo"]

_PAGE_SIZE = 5000
_ALL_TABLES: List[str] = [
    "cvm_fi_diario", "cvm_fi_cda", "cvm_fi_cda_acoes", "cvm_fi_cda_cotas",
    "cvm_fi_cda_debentures",
    "cvm_fi_perfil", "cvm_fi_balancete_resumo", "cvm_fi_lamina", "cvm_fi_extrato",
    "cvm_fidc_mensal", "cvm_fidc_tranche", "cvm_fidc_tranche_flows", "cvm_fidc_aging",
    "cvm_fidc_setor", "cvm_fidc_scr", "cvm_fidc_sacado", "cvm_fidc_cedente",
    "cvm_fidc_garantia",
    "cvm_fiagro_mensal",
    "cvm_fip_periodic", "cvm_fii_mensal", "cvm_fii_periodic", "cvm_fii_imovel",
    "cvm_securit_mensal", "cvm_securit_serie", "cvm_securit_fluxo", "cvm_securit_dfin",
    "cia_company", "cia_event", "cia_filing", "cia_account", "cia_ticker",
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

# cvm_fi_diario is RANGE-partitioned on dt_comptc and the earliest partition in
# schema.sql starts 2019-01-01. CVM publishes HIST daily archives back to 2000,
# and the fetcher will happily serve them, but the upsert then dies with "no
# partition of relation cvm_fi_diario found for row" — a whole year downloaded
# and thrown away. Declaring partitions back to 2000 would add roughly a decade
# of daily fund rows to a table that is already the largest in the warehouse, so
# the floor is the answer, not more partitions.
# A test pins this to the earliest partition actually declared in schema.sql.
_FI_DIARIO_FIRST_YEAR = 2019
# The Extrato das Informacoes yearly files (extrato_fi_YYYY.csv) are loaded from 2021
# (owner decision, issue #515); the directory also holds 2015..2020, not read.
_FI_EXTRATO_FIRST_YEAR = 2021


@dataclass(frozen=True)
class IngestTask:
    table: str
    description: str
    operation: Awaitable[int]


@dataclass(frozen=True)
class SliceFailure:
    """One (entity, doc_type, period) that this run recorded as 'error'.

    Exists because every ingest_* method catches its own exception, writes the
    audit row and returns 0 — so a run could finish with a third of history
    missing and still exit 0 (the 2026-08-27 balancete backfill did exactly
    that). The ledger carries that fact back to the CLI without changing the
    `-> int` contract of ~50 ingest methods or the one-audit-row-per-attempt
    rule.
    """
    entity: str
    doc_type: str
    year: Optional[int]
    month: Optional[int]
    error: str
    rows: int = 0
    # Set when the slice identity is already a rendered string (the
    # _run_task_batches path, which has a task description but no run_id).
    label: Optional[str] = None

    def __str__(self) -> str:
        if self.label:
            return f"{self.label}: {self.error}"
        period = ""
        if self.year:
            period = f" {self.year}" + (f"-{self.month:02d}" if self.month else "")
        return f"{self.entity}/{self.doc_type}{period}: {self.error}"


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
_DAILY_LOOKBACK_MONTHS = max(
    2, _env_int("CVM_DAILY_LOOKBACK_MONTHS", daily_window.DAILY_LOOKBACK_MONTHS)
)


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


# The four CDA blocks (issue #551). CVM publishes a CDA month partial and
# completes it about 90 days after month-end (measured 2026-10-03, #549: block 1
# of 2026-06 held ~7.3k funds against 11.5k-12.6k in a complete month). A month
# that landed partial has an ok log row, so the gap-aware window never re-reads
# it. These doc types are therefore re-fetched on every daily run, loaded or not,
# for every month up to M+5 (month M stays in until month M+5 ends): a fixed
# floor, also kept when the gap check cannot reach the database. One archive per
# month serves all four blocks (the fetcher's URL-keyed cache, per run).
# The defaults live in daily_window, which DB Health and the watchdog read too.
_CDA_DOC_TYPES = daily_window.CDA_DOC_TYPES
_CDA_REFRESH_MONTHS = max(
    1, _env_int("CVM_CDA_REFRESH_MONTHS", daily_window.CDA_REFRESH_MONTHS)
)


def _cda_refresh_months(today: date) -> List[Tuple[int, int]]:
    """Months M with M <= today's month <= M + _CDA_REFRESH_MONTHS, oldest first."""
    return _trailing_months(today, _CDA_REFRESH_MONTHS + 1)


def _fii_daily_years(today: date) -> List[int]:
    """Years whose FII yearly files the daily run re-fetches.

    The current year, plus the previous one from January to March: December's
    monthly reports and the year's last periodic filings are delivered (and
    restated) early in the next year, into last year's file (issue #551).
    """
    if today.month <= daily_window.FII_PREVIOUS_YEAR_THROUGH_MONTH:
        return [today.year - 1, today.year]
    return [today.year]


# FIDC tabs I, II, VIII, X and X_7: HIST/ yearly ZIPs cover 2013-2024 and the
# monthly ZIPs start 2025-01 — the same boundary backfill() splits
# cvm_fidc_mensal on. The header is identical across that boundary, but not
# across the whole HIST range (measured member-by-member, 2013-2026):
#   tab_II   2013-01 →  key column is CNPJ_FUNDO before 2020 (map fallback)
#   tab_VIII 2013-01 →  six columns throughout
#   tab_I    2019-11 →  the 36 cedente slots (TAB_I2{A,B}12_*) appear here;
#                       2013-01..2019-10 is a 67-column form with one
#                       TAB_I2B1_* block whose meaning is not the same
#   tab_X    2023-10 →  the member does not exist before this month
#   tab_X_7  2019-11 →  the member does not exist before this month (migration
#                       45); key column is CNPJ_FUNDO through 2020-10
#   tab_VI   2013-01 →  same value columns throughout; key column is
#                       CNPJ_FUNDO through 2020-10 (map fallback)
#   tab_X_2, X_3, X_4, X_6
#            2013-01 →  same value columns throughout; key column is
#                       CNPJ_FUNDO through 2023-09 (map fallback). Measured on
#                       every HIST archive 2013-2024 by probe_cvm_headers.yml
#                       (issue #556).
# Asking for a month before a tab exists is not a gap to heal, it is a
# member that was never published, so backfill bounds each tab here.
_FIDC_HIST_LAST_YEAR = 2024
_FIDC_TAB_FIRST_PERIOD: Dict[str, date] = {
    "i":    date(2019, 11, 1),
    "ii":   date(2013, 1, 1),
    "viii": date(2013, 1, 1),
    "x":    date(2023, 10, 1),
    "x7":   date(2019, 11, 1),
    "vi":   date(2013, 1, 1),
    "x2":   date(2013, 1, 1),
    "x3":   date(2013, 1, 1),
    "x4":   date(2013, 1, 1),
    "x6":   date(2013, 1, 1),
}


def _fidc_tab_doc_type(tab: str, year: int) -> str:
    """The cvm_config key for one of the two-era FIDC tabs (i, ii, vi, viii, x, x2..x7)."""
    return f"hist_mensal_tab_{tab}" if year <= _FIDC_HIST_LAST_YEAR else f"mensal_tab_{tab}"


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

_NOT_PUBLISHED_MARKERS = (
    # 404 from dados.cvm.gov.br: the month/year file does not exist yet.
    "Data not found",
    # The archive exists and sibling CDA blocks for the same period are in
    # it, but the requested block is not: CVM has not released it (partial
    # current-month archive, or a year that predates the block). The fetcher
    # uses this wording ONLY when the siblings prove the archive is the right
    # one — a renamed member says "not found in archive" and stays an error.
    "not published in this archive",
)


def _classify_finish(
    error: Optional[str], fetched: Optional[int], rows: int
) -> Tuple[str, Optional[str]]:
    """Audit status for a finished slice, and the message to store with it.

    Pure so it can be tested without a database. The three outcomes:

    * 'skipped' — the source has not published this slice yet. Not a failure,
      and staleness checks (which count only 'ok') still do not treat it as
      loaded. Before 2026-09-01 only a 404 qualified; health run 33558708450
      showed cda_debentures 2026-08 and 2005 red every day because the
      archive existed but carried no BLC_6 member.
    * 'error' — anything else that raised, PLUS the data-contract case: the
      source returned rows but none survived parsing/validation. Logging that
      'ok' is exactly how cvm_fiagro_mensal sat empty behind 34 'ok' slices.
    * 'ok' — rows landed, or the published file was genuinely empty
      (fetched == 0).
    """
    if error and any(marker in error for marker in _NOT_PUBLISHED_MARKERS):
        return "skipped", error
    if error:
        return "error", error
    if fetched and rows == 0:
        return "error", (
            f"fetched {fetched} source row(s) but upserted 0 — every row was "
            f"dropped (check the field map against the current source header "
            f"and the DataValidator rules)"
        )
    return "ok", None


class CVMIngestor:
    """Downloads CVM data via CVMFetcher and persists to Supabase Postgres."""

    def __init__(
        self,
        *,
        service: Optional[CVMFetcher] = None,
        cia_fetcher: Optional[CIAFetcher] = None,
        client: Optional[Any] = None,
    ) -> None:
        self._service = service if service is not None else CVMFetcher()
        self._cia_fetcher = cia_fetcher if cia_fetcher is not None else CIAFetcher()
        self._supabase = client if client is not None else get_pg_client()

    # Lazily created rather than set in __init__: tests build the ingestor with
    # CVMIngestor.__new__(CVMIngestor) to skip the DB connection, and the audit
    # path has to work there too. Per-instance (never class-level mutable
    # state), so two ingestors cannot share a ledger.
    @property
    def failures(self) -> List["SliceFailure"]:
        """Slices this run recorded as 'error'. run_backfill exits non-zero if any."""
        if not hasattr(self, "_failures"):
            self._failures: List[SliceFailure] = []
        return self._failures

    @property
    def skips(self) -> List[str]:
        """Slices this run recorded as 'skipped', rendered for the operator.

        A skip is CVM not having published something — a 404 for a month inside
        the daily window, or a CDA block absent from an archive whose siblings
        prove it is the right archive. Never a failure: nothing is missing that
        the source has.

        But it is not nothing either. When a run's ONLY requested slice is
        skipped, the run upserts zero rows, and ensure_rows_landed() reads that
        zero as "every fetch failed" and exits 1 — which is exactly what run
        33659046190 did to fi/cda_debentures/2005 after #184 had correctly
        classified it. Strings, not SliceFailure records: this ledger exists to
        explain a zero, and naming a skip a "failure" is the confusion being
        fixed.
        """
        if not hasattr(self, "_skips"):
            self._skips: List[str] = []
        return self._skips

    @property
    def _slice_of_run(self) -> Dict[str, Tuple[str, str, Optional[int], Optional[int]]]:
        """run_id -> slice identity from _log_start, so _log_finish can name it."""
        if not hasattr(self, "_slice_of_run_map"):
            self._slice_of_run_map: Dict[
                str, Tuple[str, str, Optional[int], Optional[int]]
            ] = {}
        return self._slice_of_run_map

    async def _store(self, fn, *args):
        """Run a synchronous parse+upsert off the event loop.

        upsert_rows() is psycopg2 (plus time.sleep on its own retry path), so
        calling it straight from a coroutine blocks the loop for as long as the
        write takes — minutes, for the ~2M-row FI monthly slices. Meanwhile
        aiohttp's ClientTimeout(total=) is a wall-clock timer, so co-scheduled
        downloads that cannot read their sockets simply expire. That is what
        produced the 2026-08-27 balancete failures: co-scheduled slices sharing
        an elapsed time, one 'ok' and its siblings 'TimeoutError'.

        Writes still serialise (one connection, one lock in _PgClient.cursor),
        which is intended; the gain is that a thread waiting on that lock is not
        holding the loop hostage.

        Applied to the four FI monthly ingests — the ones that run many-at-once
        over millions of rows. The remaining ingest_* methods still call their
        store function inline: they are either sequential or small enough that
        the loop pause is not observable. Convert them if that stops being true.
        """
        return await asyncio.to_thread(fn, *args)

    def _record_failure(
        self, run_id: str, error: str, rows: int = 0,
    ) -> None:
        """Append a slice to the run's failure ledger.

        Called only from _log_finish, and only when it resolved the status to
        'error' — so 'skipped' (a 404 for a month CVM has not published) never
        counts as a failure, and the ledger cannot drift from the audit table.
        """
        entity, doc_type, year, month = self._slice_of_run.get(
            run_id, ("unknown", "unknown", None, None)
        )
        self.failures.append(
            SliceFailure(entity=entity, doc_type=doc_type, year=year,
                         month=month, error=error, rows=rows)
        )

    def _record_skip(self, run_id: str, reason: str) -> None:
        """Append a slice to the run's skip ledger.

        Called only from _log_finish, and only when it resolved the status to
        'skipped' — so the ledger cannot drift from the audit table, exactly as
        _record_failure cannot.
        """
        entity, doc_type, year, month = self._slice_of_run.get(
            run_id, ("unknown", "unknown", None, None)
        )
        period = ""
        if year:
            period = f" {year}" + (f"-{month:02d}" if month else "")
        self.skips.append(f"{entity}/{doc_type}{period}: {reason}")

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
                # An exception that escaped the ingest method itself never
                # reached _log_finish, so the ledger would miss it. Record it
                # here instead — with the task description as the identity,
                # since there is no run_id to look up.
                self.failures.append(SliceFailure(
                    entity=task.table, doc_type=task.description,
                    year=None, month=None,
                    error=_describe(result) if isinstance(result, BaseException)
                    else str(result),
                    label=task.description,
                ))

    # ------------------------------------------------------------------
    # Ingest log helpers
    # ------------------------------------------------------------------

    def _log_start(self, run_id: str, entity: str, doc_type: str,
                   year: Optional[int], month: Optional[int]) -> None:
        # Remember the slice identity so _log_finish can name it in the failure
        # ledger. Recorded before the (best-effort) audit write, so a slice that
        # fails while the audit table is unreachable is still nameable.
        self._slice_of_run[run_id] = (entity, doc_type, year, month)
        try:
            upsert_rows(self._supabase, "cvm_ingest_log", [{
                "run_id":       run_id,
                "entity":       entity,
                "doc_type":     doc_type,
                "period_year":  year,
                "period_month": month,
                "status":       "running",
                "started_at":   datetime.now(timezone.utc).isoformat(),
                # Which code produced this slice (migration 44): the same
                # lineage() every other audit writer stamps, never invented.
                **lineage(),
            }])
        except Exception as e:
            logger.warning("ingest_log start failed: %s", _describe(e))

    def _log_finish(
        self,
        run_id: str,
        rows: int,
        error: Optional[str] = None,
        fetched: Optional[int] = None,
        deleted: Optional[int] = None,
    ) -> None:
        # `deleted` is how many stored rows a per-fund replace removed (the
        # monthly CDA blocks, migration 68). It is written only when given, so
        # every other slice leaves rows_deleted NULL ("does not replace"), not 0.
        #
        # A 404 for a not-yet-published month is an expected non-event, not a
        # failure. The daily window probes a trailing range (see _monthly_targets)
        # and CVM lags publication by 1-2 months, so the leading months 404. The
        # fetcher raises ValueError("Data not found at <url>") on 404; record that
        # as 'skipped' so it isn't a false error and so staleness checks (which
        # count only 'ok') don't treat the slice as loaded. Any other error —
        # including a malformed ZIP ("No CSV file found …") — stays 'error'.
        # A present archive that lacks the requested CDA block, with sibling
        # blocks for the same period proving it is the right archive, is the
        # same not-yet-published condition as a 404 and is logged the same way.
        # The fetcher composes that wording only when the siblings are there;
        # a renamed or missing member with no siblings keeps the fatal wording
        # and stays 'error'. See _classify_finish and health run 33558708450.
        status, error = _classify_finish(error, fetched, rows)
        # Single point where a slice becomes a run-level failure: exactly the
        # branches above that resolve to 'error', so the ledger and the audit
        # table can never disagree, and 'skipped' (unpublished month) is never
        # counted. Every ingest_* method routes through here, so this covers all
        # of them without touching ~50 except blocks.
        if status == "error":
            self._record_failure(run_id, error or "unknown error", rows)
        elif status == "skipped":
            self._record_skip(run_id, error or "not published")
        # The shared connection may have idled out during a long fetch (CVM
        # hangs of 15+ min killed it in the 2026-06-10 backfill, leaving every
        # slice stuck 'running'). Reconnect once and retry so the audit log
        # reflects what actually happened; still best-effort after that.
        lin = lineage()
        for attempt in (1, 2):
            try:
                deleted_set = "" if deleted is None else ", rows_deleted=%s"
                deleted_arg = () if deleted is None else (deleted,)
                with self._supabase.cursor() as cur:
                    cur.execute(
                        "UPDATE cvm_ingest_log SET rows_upserted=%s, status=%s,"
                        " error_msg=%s, finished_at=%s, git_sha=%s, parser_version=%s"
                        + deleted_set +
                        " WHERE run_id=%s",
                        (
                            rows,
                            status,
                            error,
                            datetime.now(timezone.utc).isoformat(),
                            lin["git_sha"],
                            lin["parser_version"],
                            *deleted_arg,
                            run_id,
                        ),
                    )
                    landed = getattr(cur, "rowcount", None)
                if landed == 0:
                    self._finish_without_start_row(run_id, rows, status, error, deleted)
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

    def _finish_without_start_row(
        self, run_id: str, rows: int, status: str, error: Optional[str],
        deleted: Optional[int] = None,
    ) -> None:
        """Insert the terminal row when the UPDATE found no start row to finish.

        The start write is best-effort (see _log_start), so after a failed one
        the UPDATE above matches 0 rows and the slice would leave no audit row
        at all (integrity rule 3). ingest_log.finish is an upsert for exactly
        this case. The period key is passed: without it the row would carry a
        NULL period that a later dated 'ok' never heals.
        """
        slice_ = self._slice_of_run.get(run_id)
        if slice_ is None:
            logger.warning("ingest_log finish: no start row and no slice for run %s", run_id)
            return
        entity, doc_type, year, month = slice_
        _finish_row(
            self._supabase, run_id, entity, doc_type,
            status=status, rows=rows, error=error,
            period_year=year, period_month=month, upsert=upsert_rows,
            rows_deleted=deleted,
        )

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

        The four CDA blocks also always get every month up to M+5
        (_cda_refresh_months), loaded or not, because CVM completes them late;
        that floor holds on a DB error too.
        """
        base = set(_daily_month_pairs(today))
        if entity == "fi" and doc_type in _CDA_DOC_TYPES:
            base |= set(_cda_refresh_months(today))
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
        """No-op: etf_daily / etf_latest are PLAIN VIEWS and are always current.

        This used to run `REFRESH MATERIALIZED VIEW CONCURRENTLY` on both, and
        logged a warning on every single daily run:

            refresh etf materialized views failed:
            "etf_daily" is not a table or materialized view

        The call could never succeed. Migration 06 creates the pair as
        materialized views, but migration 10_fix_etf_view_kind.sql runs after it
        (10 > 06 lexically) and deliberately converts them back to PLAIN VIEWS —
        that is the intended end state, and its whole purpose is to keep 06 from
        winning. So by the end of every schema apply they are views, and a view
        cannot be refreshed. Nothing was ever stale as a result: a plain view is
        computed at query time, so it is always current by construction.

        Kept as a no-op rather than deleted because the ETF ingest calls it and
        the honest thing to record is why there is nothing to do. If the pair is
        ever converted back to materialized views, the REFRESH belongs here —
        and migration 10 has to go first.
        """
        logger.debug(
            "etf metrics: etf_daily / etf_latest are plain views (migration 10) "
            "— nothing to refresh"
        )

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
            rows_inserted = await self._store(ingest_fi_diario, self._supabase, raw_rows)
        except Exception as exc:
            logger.warning("ingest_fi_diario %d-%02d failed: %s", year, month, _describe(exc))
            self._log_finish(run_id, 0, _describe(exc))
            return 0
        self._log_finish(run_id, rows_inserted, fetched=len(raw_rows))
        logger.info("fi/inf_diario %d-%02d: %d rows", year, month, rows_inserted)
        return rows_inserted

    # ------------------------------------------------------------------
    # FI — historical daily snapshot (2000-2020) from HIST/ yearly ZIPs
    # ------------------------------------------------------------------

    async def ingest_fi_hist_diario(self, year: int) -> int:
        """Ingest one full year of historical FI daily data from HIST/.

        The HIST archive holds TWELVE monthly members (inf_diario_fi_{year}{MM}.csv),
        not one yearly CSV, so this loops the months and extracts one member per
        pass. The yearly ZIP is downloaded once and served from the fetcher's
        on-disk cache for the remaining eleven.

        Before this loop existed the config asked for a member that does not
        exist and the fetcher fell back to the first CSV in the archive — every
        HIST year ingested January twelve times over and lost eleven months.

        Flushes every _PAGE_SIZE records to keep peak memory manageable (a full
        year of FI daily rows does not fit comfortably in memory at once).
        """
        run_id = str(uuid4())
        self._log_start(run_id, "fi", "inf_diario", year, None)
        rows_inserted = 0
        fetched = 0
        errors: List[str] = []
        for month in range(1, 13):
            try:
                raw_rows = await self._fetch_all_pages("fi", "hist_inf_diario", year, month)
            except Exception as exc:
                # A month missing from an old archive is normal (the series starts
                # mid-year in 2000). Record it and keep going — the other months
                # are still real data.
                logger.warning("ingest_fi_hist_diario %d-%02d failed: %s", year, month, _describe(exc))
                errors.append(f"{month:02d}: {exc}")
                continue
            fetched += len(raw_rows)
            chunk: List[Dict[str, Any]] = []
            for row in raw_rows:
                chunk.append(row)
                if len(chunk) >= _PAGE_SIZE:
                    rows_inserted += ingest_fi_diario(self._supabase, chunk)
                    chunk = []
            if chunk:
                rows_inserted += ingest_fi_diario(self._supabase, chunk)

        if errors and rows_inserted == 0:
            self._log_finish(run_id, 0, "; ".join(errors))
            return 0
        self._log_finish(run_id, rows_inserted, fetched=fetched)
        logger.info(
            "fi/hist_inf_diario %d: %d rows from %d month(s)",
            year, rows_inserted, 12 - len(errors),
        )
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
            # Flush in chunks: a yearly archive does not fit comfortably in memory.
            chunk: List[Dict[str, Any]] = []
            for row in raw_rows:
                chunk.append(row)
                if len(chunk) >= _PAGE_SIZE:
                    # month=None: this archive is twelve competency months in one
                    # file, so each row's own DT_COMPTC decides its period. The
                    # comment that used to sit here claimed that already, but the
                    # code passed month=1 and ingest_fi_cda overwrote period with
                    # January — collapsing every pre-2023 year onto one month
                    # under the (cnpj, period, tp_aplic, tp_ativo) key.
                    rows_inserted += ingest_fi_cda(self._supabase, chunk, year, None)
                    chunk = []
            if chunk:
                rows_inserted += ingest_fi_cda(self._supabase, chunk, year, None)
        except Exception as exc:
            logger.warning("ingest_fi_hist_cda %d failed: %s", year, _describe(exc))
            self._log_finish(run_id, 0, _describe(exc))
            return 0
        self._log_finish(run_id, rows_inserted, fetched=len(raw_rows))
        logger.info("fi/hist_cda %d: %d rows", year, rows_inserted)
        return rows_inserted

    async def _ingest_hist_cda_block(self, doc_type: str, dataset: str, fn: Any, year: int) -> int:
        """One yearly HIST holdings block (BLC_4 or BLC_2).

        Same shape as ingest_fi_hist_cda, with two differences that matter:

        month=None — the archive is twelve competency months in ONE csv, so each
        row's DT_COMPTC decides its period. Passing a month here is what
        collapsed twelve months of cvm_fi_cda onto January for every pre-2023
        year, and this path must not repeat it.

        Its own doc_type in cvm_ingest_log — `cda_acoes` / `cda_cotas`, not
        `cda`. Sharing the aggregate's audit rows would make a failed holdings
        year look like a successful CDA year to the backfill coverage gate.
        """
        run_id = str(uuid4())
        self._log_start(run_id, "fi", doc_type, year, None)
        rows_inserted = 0
        try:
            raw_rows = await self._fetch_all_pages("fi", dataset, year, None)
            chunk: List[Dict[str, Any]] = []
            for row in raw_rows:
                chunk.append(row)
                if len(chunk) >= _PAGE_SIZE:
                    rows_inserted += fn(self._supabase, chunk, year, None)
                    chunk = []
            if chunk:
                rows_inserted += fn(self._supabase, chunk, year, None)
        except Exception as exc:
            logger.warning("ingest_fi_hist_%s %d failed: %s", doc_type, year, _describe(exc))
            self._log_finish(run_id, 0, _describe(exc))
            return 0
        self._log_finish(run_id, rows_inserted, fetched=len(raw_rows))
        logger.info("fi/hist_%s %d: %d rows", doc_type, year, rows_inserted)
        return rows_inserted

    async def ingest_fi_hist_cda_acoes(self, year: int) -> int:
        """One year of pre-2023 equity holdings (CDA block 4) from HIST/."""
        return await self._ingest_hist_cda_block(
            "cda_acoes", "hist_cda_acoes", ingest_fi_cda_acoes, year
        )

    async def ingest_fi_hist_cda_cotas(self, year: int) -> int:
        """One year of pre-2023 fund-of-fund holdings (CDA block 2) from HIST/."""
        return await self._ingest_hist_cda_block(
            "cda_cotas", "hist_cda_cotas", ingest_fi_cda_cotas, year
        )

    async def ingest_fi_hist_cda_debentures(self, year: int) -> int:
        """One year of pre-2023 debenture holdings (CDA block 6) from HIST/."""
        return await self._ingest_hist_cda_block(
            "cda_debentures", "hist_cda_debentures", ingest_fi_cda_debentures, year
        )

    # ------------------------------------------------------------------
    # FI — portfolio composition  (CDA)
    # ------------------------------------------------------------------

    async def ingest_fi_cda(self, year: int, month: int) -> int:
        return await self._ingest_cda_block("cda", ingest_fi_cda, year, month)

    async def _ingest_cda_block(
        self, doc_type: str, fn: Any, year: int, month: int
    ) -> int:
        """One CDA block of one month: block 1 (`cda`) or a holdings block.

        All four are members of the same archive. Each block still writes its
        own cvm_ingest_log row: if block 4 parses and block 2 does not, the
        audit log has to say so per slice, not report one blended outcome.
        """
        run_id = str(uuid4())
        self._log_start(run_id, "fi", doc_type, year, month)
        rows_inserted = 0
        # Each fund in the file replaces its stored rows of this month
        # (ingest_fi._store_cda_block); the rows that removed go in the slice's
        # rows_deleted, also when a later batch fails after earlier ones
        # committed.
        stats: Dict[str, int] = {"rows_deleted": 0}
        try:
            raw_rows = await self._fetch_all_pages("fi", doc_type, year, month)
            rows_inserted = await self._store(fn, self._supabase, raw_rows, year, month, stats)
        except Exception as exc:
            logger.warning("ingest fi/%s %d-%02d failed: %s", doc_type, year, month, _describe(exc))
            self._log_finish(
                run_id, 0, _describe(exc), deleted=stats["rows_deleted"] or None
            )
            return 0
        self._log_finish(
            run_id, rows_inserted, fetched=len(raw_rows), deleted=stats["rows_deleted"]
        )
        logger.info(
            "fi/%s %d-%02d: %d rows, %d stale removed",
            doc_type, year, month, rows_inserted, stats["rows_deleted"],
        )
        return rows_inserted

    async def ingest_fi_cda_acoes(self, year: int, month: int) -> int:
        """FI equity holdings — the fund-to-ticker edge."""
        return await self._ingest_cda_block("cda_acoes", ingest_fi_cda_acoes, year, month)

    async def ingest_fi_cda_cotas(self, year: int, month: int) -> int:
        """FI fund-of-fund holdings — the fund-to-fund edge."""
        return await self._ingest_cda_block("cda_cotas", ingest_fi_cda_cotas, year, month)

    async def ingest_fi_cda_debentures(self, year: int, month: int) -> int:
        """FI debenture holdings — the fund-to-corporate-credit edge."""
        return await self._ingest_cda_block(
            "cda_debentures", ingest_fi_cda_debentures, year, month
        )

    # ------------------------------------------------------------------
    # FI — investor profile  (PERFIL_MENSAL)
    # ------------------------------------------------------------------

    async def ingest_fi_perfil(self, year: int, month: int) -> int:
        run_id = str(uuid4())
        self._log_start(run_id, "fi", "perfil_mensal", year, month)
        rows_inserted = 0
        try:
            raw_rows = await self._fetch_all_pages("fi", "perfil_mensal", year, month)
            rows_inserted = await self._store(ingest_fi_perfil, self._supabase, raw_rows, year, month)
        except Exception as exc:
            logger.warning("ingest_fi_perfil %d-%02d failed: %s", year, month, _describe(exc))
            self._log_finish(run_id, 0, _describe(exc))
            return 0
        self._log_finish(run_id, rows_inserted, fetched=len(raw_rows))
        logger.info("fi/perfil_mensal %d-%02d: %d rows", year, month, rows_inserted)
        return rows_inserted

    # ------------------------------------------------------------------
    # FI — lamina (CVM fi-doc-lamina): the fees and redemption terms a fund files
    # ------------------------------------------------------------------

    async def ingest_fi_lamina(self, year: int, month: int) -> int:
        """One monthly lamina_fi_YYYYMM.zip, its main member only.

        The zip also holds lamina_fi_carteira_, _rentab_ano_ and _rentab_mes_
        members; they are not ingested. A month CVM has not published 404s and is
        logged `skipped` by _log_finish, not `error`.
        """
        run_id = str(uuid4())
        self._log_start(run_id, "fi", "lamina", year, month)
        rows_inserted = 0
        try:
            raw_rows = await self._fetch_all_pages("fi", "lamina", year, month)
            rows_inserted = await self._store(ingest_fi_lamina, self._supabase, raw_rows)
        except Exception as exc:
            logger.warning("ingest_fi_lamina %d-%02d failed: %s", year, month, _describe(exc))
            self._log_finish(run_id, 0, _describe(exc))
            return 0
        self._log_finish(run_id, rows_inserted, fetched=len(raw_rows))
        logger.info("fi/lamina %d-%02d: %d rows", year, month, rows_inserted)
        return rows_inserted

    # ------------------------------------------------------------------
    # FI - Extrato das Informacoes (CVM fi-doc-extrato): the fees and terms a fund files
    # ------------------------------------------------------------------

    async def ingest_fi_extrato(self) -> int:
        """The current extrato_fi.csv: the latest version of every fund or class.

        A snapshot with no year or month (one audit row, fi / extrato, period
        NULL). CVM refreshes it daily, so the daily run reads it whole. A 404 is
        logged `skipped` by _log_finish, not `error`. Only cvm_fi_extrato is
        written; no other table is locked.
        """
        run_id = str(uuid4())
        self._log_start(run_id, "fi", "extrato", None, None)
        rows_inserted = 0
        try:
            raw_rows = await self._fetch_all_pages("fi", "extrato", None, None)
            rows_inserted = await self._store(
                ingest_fi_extrato, self._supabase, raw_rows, "extrato_fi.csv",
            )
        except Exception as exc:
            logger.warning("ingest_fi_extrato failed: %s", _describe(exc))
            self._log_finish(run_id, 0, _describe(exc))
            return 0
        self._log_finish(run_id, rows_inserted, fetched=len(raw_rows))
        logger.info("fi/extrato: %d rows", rows_inserted)
        return rows_inserted

    async def ingest_fi_extrato_ano(self, year: int) -> int:
        """One extrato_fi_YYYY.csv: every version filed in that year.

        Yearly, so the audit row carries period_year and a NULL month. The files
        are refreshed weekly with re-filings; history from 2021 is backfill's job.
        """
        run_id = str(uuid4())
        self._log_start(run_id, "fi", "extrato_ano", year, None)
        rows_inserted = 0
        try:
            raw_rows = await self._fetch_all_pages("fi", "extrato_ano", year, None)
            rows_inserted = await self._store(
                ingest_fi_extrato, self._supabase, raw_rows, f"extrato_fi_{year}.csv",
            )
        except Exception as exc:
            logger.warning("ingest_fi_extrato_ano %d failed: %s", year, _describe(exc))
            self._log_finish(run_id, 0, _describe(exc))
            return 0
        self._log_finish(run_id, rows_inserted, fetched=len(raw_rows))
        logger.info("fi/extrato_ano %d: %d rows", year, rows_inserted)
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
            rows_inserted = await self._store(ingest_fi_balancete, self._supabase, raw_rows)
        except Exception as exc:
            logger.warning("ingest_fi_balancete %d-%02d failed: %s", year, month, _describe(exc))
            self._log_finish(run_id, 0, _describe(exc))
            return 0
        self._log_finish(run_id, rows_inserted, fetched=len(raw_rows))
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
            # tab_IV has no delinquency column; the figure downstream screens
            # read lives in tab_VI of the same ZIP. A tab_VI failure must not
            # cost us the PL snapshot, so it degrades to NULL inadimplencia.
            try:
                rows_vi = await self._fetch_all_pages("fidc", "mensal_tab_VI", year, month)
            except Exception as vi_exc:
                logger.warning(
                    "ingest_fidc_mensal %d-%02d: tab_VI unavailable, "
                    "vl_inadimpl stays NULL: %s", year, month, _describe(vi_exc),
                )
                rows_vi = []
            # Same for the portfolio total: tab_IV does not carry it, tab_II
            # does (TAB_II_VL_CARTEIRA). Degrades to NULL, never to a guess.
            try:
                rows_ii = await self._fetch_all_pages("fidc", "mensal_tab_ii", year, month)
            except Exception as ii_exc:
                logger.warning(
                    "ingest_fidc_mensal %d-%02d: tab_II unavailable, "
                    "vl_total stays NULL: %s", year, month, _describe(ii_exc),
                )
                rows_ii = []
            rows_inserted = ingest_fidc_mensal(self._supabase, raw_rows, rows_vi, rows_ii)
        except Exception as exc:
            logger.warning("ingest_fidc_mensal %d-%02d failed: %r", year, month, exc)
            self._log_finish(run_id, 0, _describe(exc))
            return 0
        self._log_finish(run_id, rows_inserted, fetched=len(raw_rows))
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

                # Delinquency as filed in tab_VI (TAB_VI_B_VL_DIRCRED_INAD),
                # the same column and helper as the 2025+ path. Its own fetch,
                # so a tab_VI failure costs only vl_inadimpl (NULL, never a
                # guess), not the month's PL; ingest_fidc_aging logs the same
                # member's failure under mensal_tab_vi.
                try:
                    rows_vi = await self._fetch_all_pages(
                        "fidc", "hist_mensal_tab_vi", year, month,
                    )
                except Exception as vi_exc:
                    logger.warning(
                        "ingest_fidc_hist_mensal %d-%02d: tab_VI unavailable, "
                        "vl_inadimpl stays NULL: %s", year, month, _describe(vi_exc),
                    )
                    rows_vi = []
                inadimpl = inadimpl_by_key(rows_vi)

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
                        "vl_inadimpl":   inadimpl.get((cnpj, period)),
                        "nr_cotst":      None,
                        "raw":           residual,
                    })

                rows_inserted = upsert_rows(
                    self._supabase, "cvm_fidc_mensal", records,
                    conflict_columns="cnpj,period",
                )
            except Exception as exc:
                logger.warning("ingest_fidc_hist_mensal %d-%02d failed: %s", year, month, _describe(exc))
                self._log_finish(run_id, 0, _describe(exc))
                continue
            self._log_finish(run_id, rows_inserted)
            logger.info("fidc/hist_mensal %d-%02d: %d rows", year, month, rows_inserted)
            total += rows_inserted
        return total

    # ------------------------------------------------------------------
    # FIDC — tranche-level data (tabs X_2 + X_3 + X_6, flows X_4, aging VI)
    # ------------------------------------------------------------------
    # Both eras: the archive is picked by year (_fidc_tab_doc_type), the log
    # doc_type stays the current-format key so one (entity, doc_type) series
    # covers 2013-present, as for the concentration tabs below.

    async def ingest_fidc_tranche(self, year: int, month: int) -> int:
        run_id = str(uuid4())
        self._log_start(run_id, "fidc", "mensal_tab_x2", year, month)
        rows_inserted = 0
        try:
            rows_x2, rows_x3, rows_x6 = await asyncio.gather(
                self._fetch_all_pages("fidc", _fidc_tab_doc_type("x2", year), year, month),
                self._fetch_all_pages("fidc", _fidc_tab_doc_type("x3", year), year, month),
                self._fetch_all_pages("fidc", _fidc_tab_doc_type("x6", year), year, month),
            )
            rows_inserted = ingest_fidc_tranche(
                self._supabase, rows_x2, rows_x3, rows_x6, year, month
            )
        except Exception as exc:
            logger.warning("ingest_fidc_tranche %d-%02d failed: %s", year, month, _describe(exc))
            self._log_finish(run_id, 0, _describe(exc))
            return 0
        self._log_finish(
            run_id, rows_inserted,
            fetched=len(rows_x2) + len(rows_x3) + len(rows_x6),
        )
        logger.info("fidc/tranche %d-%02d: %d rows", year, month, rows_inserted)
        return rows_inserted

    async def ingest_fidc_tranche_flows(self, year: int, month: int) -> int:
        run_id = str(uuid4())
        self._log_start(run_id, "fidc", "mensal_tab_x4", year, month)
        rows_inserted = 0
        try:
            raw_rows = await self._fetch_all_pages("fidc", _fidc_tab_doc_type("x4", year), year, month)
            rows_inserted = ingest_fidc_tranche_flows(self._supabase, raw_rows)
        except Exception as exc:
            logger.warning("ingest_fidc_tranche_flows %d-%02d failed: %s", year, month, _describe(exc))
            self._log_finish(run_id, 0, _describe(exc))
            return 0
        self._log_finish(run_id, rows_inserted, fetched=len(raw_rows))
        logger.info("fidc/tranche_flows %d-%02d: %d rows", year, month, rows_inserted)
        return rows_inserted

    async def ingest_fidc_aging(self, year: int, month: int) -> int:
        run_id = str(uuid4())
        self._log_start(run_id, "fidc", "mensal_tab_vi", year, month)
        rows_inserted = 0
        try:
            raw_rows = await self._fetch_all_pages(
                "fidc", _fidc_tab_doc_type("vi", year), year, month,
            )
            rows_inserted = ingest_fidc_aging(self._supabase, raw_rows)
        except Exception as exc:
            logger.warning("ingest_fidc_aging %d-%02d failed: %s", year, month, _describe(exc))
            self._log_finish(run_id, 0, _describe(exc))
            return 0
        self._log_finish(run_id, rows_inserted, fetched=len(raw_rows))
        logger.info("fidc/aging %d-%02d: %d rows", year, month, rows_inserted)
        return rows_inserted

    # ------------------------------------------------------------------
    # FIDC — concentration and credit quality (tabs I, II, VIII, X, X_7; both eras)
    # ------------------------------------------------------------------
    # One method per tab, each its own cvm_ingest_log row so the daily
    # gap-aware window heals each slice on its own. The log doc_type is the
    # current-format key whatever the era, so one (entity, doc_type) series
    # covers 2013-present in _monthly_targets.

    async def _ingest_fidc_tab(
        self, tab: str, label: str, store: Any, year: int, month: int,
    ) -> int:
        run_id = str(uuid4())
        self._log_start(run_id, "fidc", f"mensal_tab_{tab}", year, month)
        rows_inserted = 0
        raw_rows: List[Dict[str, Any]] = []
        try:
            raw_rows = await self._fetch_all_pages(
                "fidc", _fidc_tab_doc_type(tab, year), year, month,
            )
            rows_inserted = store(self._supabase, raw_rows)
        except Exception as exc:
            logger.warning("ingest_fidc_%s %d-%02d failed: %s", label, year, month, _describe(exc))
            self._log_finish(run_id, 0, _describe(exc))
            return 0
        self._log_finish(run_id, rows_inserted, fetched=len(raw_rows))
        logger.info("fidc/%s %d-%02d: %d rows", label, year, month, rows_inserted)
        return rows_inserted

    async def ingest_fidc_setor(self, year: int, month: int) -> int:
        return await self._ingest_fidc_tab("ii", "setor", ingest_fidc_setor, year, month)

    async def ingest_fidc_scr(self, year: int, month: int) -> int:
        return await self._ingest_fidc_tab("x", "scr", ingest_fidc_scr, year, month)

    async def ingest_fidc_sacado(self, year: int, month: int) -> int:
        return await self._ingest_fidc_tab("viii", "sacado", ingest_fidc_sacado, year, month)

    async def ingest_fidc_cedente(self, year: int, month: int) -> int:
        return await self._ingest_fidc_tab("i", "cedente", ingest_fidc_cedente, year, month)

    async def ingest_fidc_garantia(self, year: int, month: int) -> int:
        return await self._ingest_fidc_tab("x7", "garantia", ingest_fidc_garantia, year, month)

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
            logger.warning("ingest_fiagro_mensal %d-%02d failed: %s", year, month, _describe(exc))
            self._log_finish(run_id, 0, _describe(exc))
            return 0
        self._log_finish(run_id, rows_inserted, fetched=len(raw_rows))
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
            logger.warning("ingest_fip_periodic %s %d failed: %s", doc_type, year, _describe(exc))
            self._log_finish(run_id, 0, _describe(exc))
            return 0
        self._log_finish(run_id, rows_inserted, fetched=len(raw_rows))
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
            logger.warning("ingest_fii_mensal %s %d failed: %s", doc_type, year, _describe(exc))
            self._log_finish(run_id, 0, _describe(exc))
            return 0
        self._log_finish(run_id, rows_inserted, fetched=len(raw_rows))
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
            logger.warning("ingest_fii_periodic %s %d failed: %s", doc_type, year, _describe(exc))
            self._log_finish(run_id, 0, _describe(exc))
            return 0
        self._log_finish(run_id, rows_inserted, fetched=len(raw_rows))
        logger.info("fii/%s %d: %d rows", doc_type, year, rows_inserted)
        return rows_inserted

    # ------------------------------------------------------------------
    # FII — property register (INF_TRIMESTRAL _imovel_ member -> cvm_fii_imovel)
    #
    # Kept separate from ingest_fii_periodic because the grain differs: many
    # properties per fund per quarter, so it cannot share cvm_fii_periodic's
    # one-row-per-fund-per-period key.
    # ------------------------------------------------------------------

    async def ingest_fii_imovel(self, year: int) -> int:
        run_id = str(uuid4())
        self._log_start(run_id, "fii", "trimestral_imovel", year, None)
        rows_inserted = 0
        try:
            raw_rows = await self._fetch_all_pages("fii", "trimestral_imovel", year, None)
            rows_inserted = ingest_fii_imovel(self._supabase, raw_rows, year)
        except Exception as exc:
            logger.warning("ingest_fii_imovel %d failed: %s", year, _describe(exc))
            self._log_finish(run_id, 0, _describe(exc))
            return 0
        self._log_finish(run_id, rows_inserted, fetched=len(raw_rows))
        logger.info("fii/trimestral_imovel %d: %d rows", year, rows_inserted)
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
            logger.warning("ingest_fund_registry %s failed: %s", entity, _describe(exc))
            self._log_finish(run_id, 0, _describe(exc))
            return 0
        self._log_finish(run_id, rows_inserted, fetched=len(raw_rows))
        logger.info("%s/cad: %d rows", entity, rows_inserted)
        return rows_inserted

    async def ingest_fund_registry_cvm175(self) -> int:
        """Ingest the CVM-175 unified registry: registro_fundo, registro_classe
        and registro_subclasse, three members of one zip (one download, cached).

        Covers the post-2023 active universe across all fund families; entity_type
        and is_active are derived per row. Runs after the legacy cad ingest so the
        current CVM-175 status wins for any shared CNPJ.

        Each member is one slice and one cvm_ingest_log row. registro_fundo and
        registro_classe are written twice from the same parsed file: to
        cvm_fund_registry (keyed on cnpj, entity_type, what the dashboards and
        api read) and to their level table cvm_registro_fundo / _classe (keyed on
        the registry ids, migration 67), so a class can be walked to its fund. A
        failure in either write logs the slice 'error'; rows_upserted counts the
        level-table rows, the measure of what this slice made walkable.
        registro_subclasse has no CNPJ and goes to cvm_registro_subclasse only.
        """
        from src.pipeline.ingest_misc import (
            ingest_fund_registry_cvm175, ingest_registro_level,
        )

        total = 0
        for doc_type in ("registro_fundo", "registro_classe", "registro_subclasse"):
            run_id = str(uuid4())
            self._log_start(run_id, "fi", doc_type, None, None)
            rows = 0
            raw_rows: List[Dict[str, Any]] = []
            try:
                raw_rows = await self._fetch_all_pages("fi", doc_type, None, None)
                if doc_type != "registro_subclasse":
                    ingest_fund_registry_cvm175(self._supabase, raw_rows)
                rows = ingest_registro_level(self._supabase, raw_rows, doc_type)
            except Exception as exc:
                logger.warning("ingest_fund_registry_cvm175 %s failed: %s", doc_type, _describe(exc))
                self._log_finish(run_id, 0, _describe(exc))
                continue
            self._log_finish(run_id, rows, fetched=len(raw_rows))
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
            logger.warning("ingest_etf_registry failed: %s", _describe(exc))
            self._log_finish(run_id, 0, _describe(exc))
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
            logger.warning("ingest_securit_serie %s %d failed: %s", doc_type, year, _describe(exc))
            self._log_finish(run_id, 0, _describe(exc))
            return 0
        self._log_finish(run_id, rows_inserted, fetched=len(raw_rows))
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
            logger.warning("ingest_securit_fluxo %s %d failed: %s", doc_type, year, _describe(exc))
            self._log_finish(run_id, 0, _describe(exc))
            return 0
        self._log_finish(run_id, rows_inserted, fetched=len(raw_rows))
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
            logger.warning("ingest_securit_mensal %s %d failed: %s", instrument_type, year, _describe(exc))
            self._log_finish(run_id, 0, _describe(exc))
            return 0
        self._log_finish(run_id, rows_inserted, fetched=len(raw_rows))
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
            logger.warning("ingest_securit_dfin %s %d failed: %s", instrument_type, year, _describe(exc))
            self._log_finish(run_id, 0, _describe(exc))
            return 0
        self._log_finish(run_id, rows_inserted, fetched=len(raw_rows))
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
            logger.warning("ingest_cia_cad failed: %s", _describe(exc))
            self._log_finish(run_id, 0, _describe(exc))
            return 0
        self._log_finish(run_id, rows_inserted, fetched=len(raw_rows))
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
            logger.warning("ingest_cia_ipe %d failed: %s", year, _describe(exc))
            self._log_finish(run_id, 0, _describe(exc))
            return 0
        self._log_finish(run_id, rows_inserted, fetched=len(raw_rows))
        logger.info("cia_aberta/ipe %d: %d rows", year, rows_inserted)
        return rows_inserted

    # ------------------------------------------------------------------
    # CIA_ABERTA — FCA valores mobiliários (the published CNPJ↔ticker map)
    # ------------------------------------------------------------------

    async def ingest_cia_fca(self, year: int) -> int:
        """Ingest one year of FCA valores-mobiliários rows into cia_ticker.

        Same yearly-ZIP shape as IPE, but the ZIP holds ~10 member CSVs and
        csv_name_pattern selects only the valor_mobiliario one. ~1k rows per
        year — CVM's published company↔ticker mapping.
        """
        run_id = str(uuid4())
        self._log_start(run_id, "cia_aberta", "fca_valor_mobiliario", year, None)
        rows_inserted = 0
        try:
            raw_rows = await self._fetch_all_pages(
                "cia_aberta", "fca_valor_mobiliario", year, None
            )
            rows_inserted = ingest_cia_ticker(self._supabase, raw_rows)
        except Exception as exc:
            logger.warning("ingest_cia_fca %d failed: %s", year, _describe(exc))
            self._log_finish(run_id, 0, _describe(exc))
            return 0
        self._log_finish(run_id, rows_inserted, fetched=len(raw_rows))
        logger.info("cia_aberta/fca_valor_mobiliario %d: %d rows", year, rows_inserted)
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
            # One pass over a lazy iterator: each member is parsed, upserted and
            # released before the next is read, so peak memory is one member,
            # not the whole ~19-CSV archive.
            members = await self._cia_fetcher.fetch_zip_members_async(
                doc_type, year, include_summary=True
            )
            n_members = 0
            account_members = 0
            for m in members:
                n_members += 1
                if m.is_summary:
                    rows_inserted += ingest_cia_filing(self._supabase, m.rows, doc_type)
                elif m.is_account_data:
                    account_members += 1
                    rows_inserted += ingest_cia_account(self._supabase, [m], doc_type)
            # A real ITR/DFP ZIP always has account members; zero rows from a
            # non-empty publish year signals a bad/truncated fetch (see the
            # serial-only note in backfill) rather than a genuine empty year.
            if rows_inserted == 0 or account_members == 0:
                logger.warning(
                    "cia_aberta/%s %d: suspicious empty load (members=%d, account_members=%d) "
                    "— likely a bad fetch; re-run this slice serially",
                    doc_type, year, n_members, account_members,
                )
        except Exception as exc:
            logger.warning("ingest_cia_itr_dfp %s %d failed: %s", doc_type, year, _describe(exc))
            self._log_finish(run_id, 0, _describe(exc))
            return 0
        # account_members counts the source rows seen; the contract in _log_finish
        # turns "saw source rows, wrote none" into an error rather than the
        # warning-only check above.
        self._log_finish(run_id, rows_inserted, fetched=account_members)
        logger.info("cia_aberta/%s %d: %d rows", doc_type, year, rows_inserted)
        return rows_inserted

    def _held_cia_documents(
        self, doc_type: str, ref_dates: List[date]
    ) -> Set[Tuple[str, date, Optional[int]]]:
        """(cd_cvm, dt_refer, versao) of every ITR/DFP header SILO holds for these dates."""
        if not ref_dates:
            return set()
        with self._supabase.cursor() as cur:
            cur.execute(
                "SELECT cd_cvm, dt_refer, versao FROM cia_filing"
                " WHERE doc_type = %s AND dt_refer = ANY(%s)",
                (doc_type, list(ref_dates)),
            )
            return {(r[0], r[1], r[2]) for r in cur.fetchall()}

    async def ingest_cia_itr_dfp_new_versions(self, doc_type: str, year: int) -> int:
        """Ingest only the ITR/DFP documents of one year that SILO does not hold (#383).

        The daily run re-reads the current year in full. A DFP filed in the
        next year, or a restatement of a prior-year document, lands in the
        PREVIOUS year's ZIP, and re-reading that one in full every day costs
        about 4.7M upserts (measured 2026-09-28). This reads the year's header
        CSV first and compares its (cd_cvm, dt_refer, versao) with cia_filing.
        When nothing is new it stops there, before any statement member is
        parsed. Otherwise it upserts the new headers and only the statement
        lines of those documents. CVM's statement CSVs carry the latest
        version of each document, so a new version's lines are in the file.

        A document's header is written only AFTER its lines, and only when
        lines were found: a header in cia_filing is what marks the document
        held, so a statement member that came back empty (the concurrency
        failure noted in backfill) must not mark it held. The latest version of
        a document with no lines is left out, logged, and compared again on
        the next run; a superseded version has no lines by construction and
        its header is written as published.
        """
        from src.fetchers.cia_fetcher import CIAMember
        from src.parsers.field_maps import cia_filing as _filing_map
        from src.parsers.mapping import apply_map

        key_map = {k: _filing_map.FIELD_MAP[k] for k in ("cd_cvm", "dt_refer", "versao")}

        def doc_key(row: Dict[str, Any]) -> Tuple[Any, Any, Any]:
            typed, _ = apply_map(row, key_map)
            return typed.get("cd_cvm"), typed.get("dt_refer"), typed.get("versao")

        run_id = str(uuid4())
        self._log_start(run_id, "cia_aberta", doc_type, year, None)
        rows_inserted = 0
        fetched = 0
        try:
            members = await self._cia_fetcher.fetch_zip_members_async(
                doc_type, year, include_summary=True
            )
            new_docs: Optional[Set[Tuple[Any, Any, Any]]] = None
            with_lines: Set[Tuple[Any, Any, Any]] = set()
            header: List[Dict[str, Any]] = []
            for m in members:
                if m.is_summary:
                    published = {doc_key(r) for r in m.rows}
                    held = self._held_cia_documents(
                        doc_type, sorted({k[1] for k in published if k[1] is not None})
                    )
                    if not m.rows:
                        raise ValueError(f"cia_aberta/{doc_type} {year}: the header CSV is empty")
                    new_docs = {k for k in published if k[0] and k[1] is not None} - held
                    if not new_docs:
                        break
                    header = [r for r in m.rows if doc_key(r) in new_docs]
                elif m.is_account_data:
                    if new_docs is None:
                        # The header member sorts first in every published ZIP;
                        # without it there is nothing to compare against.
                        raise ValueError(
                            f"cia_aberta/{doc_type} {year}: statement member "
                            f"{m.member_name} came before the header CSV"
                        )
                    lines = [r for r in m.rows if doc_key(r) in new_docs]
                    if lines:
                        fetched += len(lines)
                        with_lines.update(doc_key(r) for r in lines)
                        rows_inserted += ingest_cia_account(
                            self._supabase,
                            [CIAMember(m.member_name, m.grupo, m.escopo, lines)],
                            doc_type,
                        )
            if new_docs is None:
                raise ValueError(f"cia_aberta/{doc_type} {year}: no header CSV in the ZIP")
            if new_docs:
                # A version the header lists with a newer one beside it has no
                # lines by construction (the statement CSVs carry only the
                # latest), so its header is written as published. Only the
                # latest version of a document without lines is suspect.
                latest: Dict[Tuple[Any, Any], int] = {}
                for k in published:
                    if k[2] is not None:
                        latest[(k[0], k[1])] = max(latest.get((k[0], k[1]), k[2]), k[2])
                superseded = {
                    k for k in new_docs
                    if k[2] is not None and k[2] < latest.get((k[0], k[1]), k[2])
                }
                with_lines |= superseded
                lineless = new_docs - with_lines
                if lineless:
                    logger.warning(
                        "cia_aberta/%s %d: %d new document(s) have no statement lines in "
                        "the ZIP; their headers are not written, so the next run "
                        "compares them again (first: %s)",
                        doc_type, year, len(lineless), sorted(lineless, key=str)[0],
                    )
                done = [r for r in header if doc_key(r) in with_lines]
                fetched += len(done)
                if done:
                    rows_inserted += ingest_cia_filing(self._supabase, done, doc_type)
        except Exception as exc:
            logger.warning(
                "ingest_cia_itr_dfp_new_versions %s %d failed: %s", doc_type, year, _describe(exc)
            )
            self._log_finish(run_id, 0, _describe(exc))
            return 0
        self._log_finish(run_id, rows_inserted, fetched=fetched)
        logger.info(
            "cia_aberta/%s %d new versions: %d document(s), %d rows",
            doc_type, year, len(new_docs), rows_inserted,
        )
        return rows_inserted

    # ------------------------------------------------------------------
    # Orchestrated runs
    # ------------------------------------------------------------------

    async def backfill(
        self,
        start_year: int = 2019,
        end_year: Optional[int] = None,
        entity_filter: Optional[str] = None,
        doc_type_filter: Optional[str] = None,
        months: Optional[List[Tuple[int, int]]] = None,
    ) -> Dict[str, int]:
        """Full historical backfill for all entities from start_year to today.

        Pass entity_filter to restrict to one entity. doc_type_filter is an
        FI-only repair control: inf_diario | cda | perfil_mensal | balancete | lamina | extrato.

        months is an explicit [(year, month), ...] whitelist for the FI monthly
        loop — the gap-repair path. It replaces the generated year x month grid
        rather than intersecting with it, so a repair fetches exactly the named
        slices and nothing else: re-downloading the 59 good balancete months to
        reach the 32 bad ones would be ~120 GB of source data for no reason.
        It requires doc_type_filter, because "these months, all four FI
        documents" is not a repair anyone has asked for and quietly triples the
        work.
        """
        # Every doc type the year loop below can schedule. Kept in step with
        # backfill.yml's dropdown, run_backfill's argparse choices and
        # gaps.FI_MONTHLY_TABLES by a parity test — a value in one list and not
        # the others is a dispatch that dies before fetching anything.
        fi_doc_types = {
            "inf_diario", "cda", "cda_acoes", "cda_cotas", "cda_debentures",
            "perfil_mensal", "balancete", "lamina", "extrato",
        }
        if doc_type_filter not in fi_doc_types | {None}:
            raise ValueError(f"unsupported FI doc_type_filter: {doc_type_filter}")
        if months is not None and doc_type_filter is None:
            raise ValueError("months requires doc_type_filter")
        if doc_type_filter is not None and entity_filter != "fi":
            raise ValueError("doc_type_filter requires entity_filter='fi'")

        today = date.today()
        end_year = end_year or today.year
        years = list(range(start_year, end_year + 1))

        totals = _new_totals()

        def _want(entity: str) -> bool:
            return entity_filter is None or entity_filter == entity

        def _want_fi_doc(doc_type: str) -> bool:
            return doc_type_filter is None or doc_type_filter == doc_type

        # -- Fund registry (static cadastral file — run once per backfill) --
        # FII is deliberately absent: CVM retired the whole FII/CAD/ tree (the
        # directory itself 404s), and registro_fundo already carries every FII
        # with its Denominacao_Social, so the legacy fetch only logged a daily
        # error while adding nothing.
        if _want("fi") and doc_type_filter is None:
            totals["cvm_fund_registry"] += await self.ingest_fund_registry("fi")

        # -- CVM-175 unified registry (active universe, all fund families) --
        if _want("fi") and doc_type_filter is None:
            totals["cvm_fund_registry"] += await self.ingest_fund_registry_cvm175()

        # -- ETF registry (distinct entity: curated seed, self-fetches cad_fi) --
        if _want("etf"):
            totals["cvm_etf_registry"] += await self.ingest_etf_registry()

        # -- FI ----------------------------------------------------------
        if _want("fi"):
            hist_diario_years = [
                y for y in years if _FI_DIARIO_FIRST_YEAR <= y <= 2020
            ]
            hist_cda_years    = [y for y in years if y <= 2022]
            monthly_years     = years

            # The yearly HIST archives are whole-year downloads; a targeted
            # month repair must not drag them in.
            if _want_fi_doc("inf_diario") and months is None:
                for year in hist_diario_years:
                    n = await self.ingest_fi_hist_diario(year)
                    totals["cvm_fi_diario"] += n

            if _want_fi_doc("cda") and months is None:
                for year in hist_cda_years:
                    n = await self.ingest_fi_hist_cda(year)
                    totals["cvm_fi_cda"] += n

            # Holdings for the same pre-2023 span, from blocks 4 and 2 of the
            # archive hist_cda already downloaded. Separate loops rather than
            # one, so selecting a single doc type fetches a single block.
            if _want_fi_doc("cda_acoes") and months is None:
                for year in hist_cda_years:
                    totals["cvm_fi_cda_acoes"] += await self.ingest_fi_hist_cda_acoes(year)

            if _want_fi_doc("cda_cotas") and months is None:
                for year in hist_cda_years:
                    totals["cvm_fi_cda_cotas"] += await self.ingest_fi_hist_cda_cotas(year)

            if _want_fi_doc("cda_debentures") and months is None:
                for year in hist_cda_years:
                    totals["cvm_fi_cda_debentures"] += (
                        await self.ingest_fi_hist_cda_debentures(year)
                    )

            # The Extrato is a snapshot plus yearly files of versions, not monthly:
            # a named month has no file of its own, so a month repair refuses it
            # instead of scheduling nothing. Yearly files first, the current file
            # last, so the newest version of a (cnpj, dt_comptc) wins.
            if _want_fi_doc("extrato"):
                if months is not None:
                    raise ValueError(
                        "extrato has no monthly files: use the yearly backfill "
                        "(extrato_fi_YYYY.csv), not --months or --repair-gaps"
                    )
                for year in (y for y in years if y >= _FI_EXTRATO_FIRST_YEAR):
                    totals["cvm_fi_extrato"] += await self.ingest_fi_extrato_ano(year)
                # backfill.yml runs one job per year: only the job that reaches
                # the current year reads the 34 MB current file, not all of them.
                if end_year >= today.year:
                    totals["cvm_fi_extrato"] += await self.ingest_fi_extrato()

            month_pairs = (
                sorted(set(months)) if months is not None
                else _iter_month_pairs(monthly_years, today)
            )
            if months is not None:
                logger.info(
                    "FI targeted repair: %s %s",
                    doc_type_filter,
                    ", ".join(f"{y}-{m:02d}" for y, m in month_pairs),
                )

            fi_tasks: List[IngestTask] = []
            for year, month in month_pairs:
                if year >= 2021 and _want_fi_doc("inf_diario"):
                    fi_tasks.append(IngestTask(
                        "cvm_fi_diario",
                        f"fi/inf_diario {year}-{month:02d}",
                        self.ingest_fi_diario(year, month),
                    ))
                if year >= 2023 and _want_fi_doc("cda"):
                    fi_tasks.append(IngestTask(
                        "cvm_fi_cda",
                        f"fi/cda {year}-{month:02d}",
                        self.ingest_fi_cda(year, month),
                    ))
                # Same 2023+ gate as `cda`: these are members of the same
                # archive, so where that one has no monthly file neither do they.
                if year >= 2023 and _want_fi_doc("cda_acoes"):
                    fi_tasks.append(IngestTask(
                        "cvm_fi_cda_acoes",
                        f"fi/cda_acoes {year}-{month:02d}",
                        self.ingest_fi_cda_acoes(year, month),
                    ))
                if year >= 2023 and _want_fi_doc("cda_cotas"):
                    fi_tasks.append(IngestTask(
                        "cvm_fi_cda_cotas",
                        f"fi/cda_cotas {year}-{month:02d}",
                        self.ingest_fi_cda_cotas(year, month),
                    ))
                if year >= 2023 and _want_fi_doc("cda_debentures"):
                    fi_tasks.append(IngestTask(
                        "cvm_fi_cda_debentures",
                        f"fi/cda_debentures {year}-{month:02d}",
                        self.ingest_fi_cda_debentures(year, month),
                    ))
                if _want_fi_doc("perfil_mensal"):
                    fi_tasks.append(IngestTask(
                        "cvm_fi_perfil",
                        f"fi/perfil_mensal {year}-{month:02d}",
                        self.ingest_fi_perfil(year, month),
                    ))
                # Monthly files from 2019-01 (HIST/ holds 2014-2018 as other zips
                # that this dataset does not read).
                if year >= 2019 and _want_fi_doc("lamina"):
                    fi_tasks.append(IngestTask(
                        "cvm_fi_lamina",
                        f"fi/lamina {year}-{month:02d}",
                        self.ingest_fi_lamina(year, month),
                    ))
                if _want_fi_doc("balancete"):
                    fi_tasks.append(IngestTask(
                        "cvm_fi_balancete_resumo",
                        f"fi/balancete {year}-{month:02d}",
                        self.ingest_fi_balancete(year, month),
                    ))
            # inf_diario before 2021 and cda before 2023 come from the yearly
            # HIST archives, so a named month there schedules nothing. Say so
            # rather than reporting a silent success over fewer slices than the
            # operator asked for.
            if months is not None and len(fi_tasks) < len(month_pairs):
                scheduled = {
                    tuple(int(p) for p in t.description.split()[-1].split("-"))
                    for t in fi_tasks
                }
                dropped = [f"{y}-{m:02d}" for y, m in month_pairs
                           if (y, m) not in scheduled]
                logger.warning(
                    "FI targeted repair: %d of %d requested month(s) not "
                    "available as monthly %s files (pre-HIST-cutoff): %s",
                    len(dropped), len(month_pairs), doc_type_filter,
                    ", ".join(dropped),
                )
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
                for year, month in _iter_month_pairs(current_years, today):
                    mensal_tasks.append(IngestTask(
                        "cvm_fidc_mensal",
                        f"fidc/mensal {year}-{month:02d}",
                        self.ingest_fidc_mensal(year, month),
                    ))
                await self._run_task_batches(
                    mensal_tasks,
                    _get_concurrency("fidc", 4),
                    totals,
                    "FIDC current mensal backfill",
                )

            # Tranche (X_2+X_3+X_6), flows (X_4) and aging (VI) exist in both
            # eras from 2013-01 (issue #556), so like the concentration tabs
            # below they run for every requested year; the method picks the
            # archive by year.
            tranche_tasks: List[IngestTask] = []
            for tab, table, label, method in (
                ("x2", "cvm_fidc_tranche",       "tranche",       self.ingest_fidc_tranche),
                ("x4", "cvm_fidc_tranche_flows", "tranche_flows", self.ingest_fidc_tranche_flows),
                ("vi", "cvm_fidc_aging",         "aging",         self.ingest_fidc_aging),
            ):
                for year, month in _iter_month_pairs(
                    years, today, available_from=_FIDC_TAB_FIRST_PERIOD[tab],
                ):
                    tranche_tasks.append(IngestTask(
                        table,
                        f"fidc/{label} {year}-{month:02d}",
                        method(year, month),
                    ))
            await self._run_task_batches(
                tranche_tasks,
                _get_concurrency("fidc_tranche", 3),
                totals,
                "FIDC tranche backfill",
            )

            # Tabs I, II, VIII, X, X_7 exist in both eras, so these run for every
            # requested year from each tab's first published month
            # (_FIDC_TAB_FIRST_PERIOD); the method picks the archive by year.
            # HIST months after the first hit the fetcher's on-disk ZIP cache.
            concentration_tasks: List[IngestTask] = []
            for tab, table, label, method in (
                ("ii",   "cvm_fidc_setor",   "setor",   self.ingest_fidc_setor),
                ("x",    "cvm_fidc_scr",     "scr",     self.ingest_fidc_scr),
                ("viii", "cvm_fidc_sacado",  "sacado",  self.ingest_fidc_sacado),
                ("i",    "cvm_fidc_cedente", "cedente", self.ingest_fidc_cedente),
                ("x7",   "cvm_fidc_garantia", "garantia", self.ingest_fidc_garantia),
            ):
                for year, month in _iter_month_pairs(
                    years, today, available_from=_FIDC_TAB_FIRST_PERIOD[tab],
                ):
                    concentration_tasks.append(IngestTask(
                        table,
                        f"fidc/{label} {year}-{month:02d}",
                        method(year, month),
                    ))
            await self._run_task_batches(
                concentration_tasks,
                _get_concurrency("fidc_tranche", 3),
                totals,
                "FIDC concentration backfill",
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
            for year in years:
                tasks.append(IngestTask(
                    "cvm_fii_imovel",
                    f"fii/trimestral_imovel {year}",
                    self.ingest_fii_imovel(year),
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
            # FCA valores mobiliários — the published CNPJ↔ticker map, ~1k
            # rows per yearly ZIP; cheap enough to fill alongside IPE.
            cia_tasks += [
                IngestTask(
                    "cia_ticker",
                    f"cia_aberta/fca_valor_mobiliario {year}",
                    self.ingest_cia_fca(year),
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
        fi_prices_changed = _want("fi") and _want_fi_doc("inf_diario")
        etf_registry_changed = _want("etf")
        if (fi_prices_changed or etf_registry_changed) and not _etf_refresh_disabled():
            self._refresh_etf_metrics()

        logger.info("Backfill complete: %s", totals)
        return totals

    def _plan_daily_monthly_tasks(
        self, daily_entities: Set[str], today: date
    ) -> List[IngestTask]:
        """Plan monthly slices; execution and audit happen later."""
        tasks: List[IngestTask] = []
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
                # Members of the same archive as `cda`; each gets its own
                # spec so the gap-aware window tracks them independently —
                # a month where block 4 landed and block 2 did not must be
                # re-probed for block 2 alone.
                ("cvm_fi_cda_acoes", "fi", "cda_acoes", "cda_acoes", self.ingest_fi_cda_acoes),
                ("cvm_fi_cda_debentures", "fi", "cda_debentures", "cda_debentures", self.ingest_fi_cda_debentures),
                ("cvm_fi_cda_cotas", "fi", "cda_cotas", "cda_cotas", self.ingest_fi_cda_cotas),
                ("cvm_fi_perfil", "fi", "perfil_mensal", "perfil_mensal", self.ingest_fi_perfil),
                # CVM updates the lamina zips weekly; the trailing window re-reads
                # the current and previous month and probes any month with no ok row.
                ("cvm_fi_lamina", "fi", "lamina", "lamina", self.ingest_fi_lamina),
                # balancete used to live only on the deleted ingest Flask and
                # sat empty in production. It is now on the daily/backfill specs.
                # CVM publishes it monthly from 2019 (verified by ranged GET
                # against the BALANCETE endpoint). Only its summary is stored
                # (migration 62 retired the account table).
                ("cvm_fi_balancete_resumo", "fi", "balancete", "balancete", self.ingest_fi_balancete),
            ]
        if "fidc" in daily_entities:
            monthly_specs += [
                ("cvm_fidc_mensal", "fidc", "mensal", "mensal", self.ingest_fidc_mensal),
                ("cvm_fidc_tranche", "fidc", "mensal_tab_x2", "tranche", self.ingest_fidc_tranche),
                ("cvm_fidc_tranche_flows", "fidc", "mensal_tab_x4", "tranche_flows", self.ingest_fidc_tranche_flows),
                ("cvm_fidc_aging", "fidc", "mensal_tab_vi", "aging", self.ingest_fidc_aging),
                ("cvm_fidc_setor", "fidc", "mensal_tab_ii", "setor", self.ingest_fidc_setor),
                ("cvm_fidc_scr", "fidc", "mensal_tab_x", "scr", self.ingest_fidc_scr),
                ("cvm_fidc_sacado", "fidc", "mensal_tab_viii", "sacado", self.ingest_fidc_sacado),
                ("cvm_fidc_cedente", "fidc", "mensal_tab_i", "cedente", self.ingest_fidc_cedente),
                ("cvm_fidc_garantia", "fidc", "mensal_tab_x7", "garantia", self.ingest_fidc_garantia),
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

        return tasks

    def _plan_daily_annual_tasks(
        self, daily_entities: Set[str], year: int, today: Optional[date] = None
    ) -> List[IngestTask]:
        """Plan current-year slices without executing or auditing them.

        FII also gets the previous year from January to March when `today` is
        given (_fii_daily_years).
        """
        tasks: List[IngestTask] = []
        fii_years = _fii_daily_years(today) if today is not None else [year]
        # FIP — refresh current year
        if "fip" in daily_entities:
            for _, doc_type in FIP_PERIODIC_CONFIGS:
                tasks.append(IngestTask(
                    "cvm_fip_periodic",
                    f"fip/{doc_type} {year}",
                    self.ingest_fip_periodic(doc_type, year),
                ))

        # FII: the current year, plus the previous one in Q1 (issue #551)
        if "fii" in daily_entities:
            for fii_year in fii_years:
                for doc_type in FII_MENSAL_DOC_TYPES:
                    tasks.append(IngestTask(
                        "cvm_fii_mensal",
                        f"fii/{doc_type} {fii_year}",
                        self.ingest_fii_mensal(doc_type, fii_year),
                    ))
                for doc_type in FII_PERIODIC_DOC_TYPES:
                    tasks.append(IngestTask(
                        "cvm_fii_periodic",
                        f"fii/{doc_type} {fii_year}",
                        self.ingest_fii_periodic(doc_type, fii_year),
                    ))
                tasks.append(IngestTask(
                    "cvm_fii_imovel",
                    f"fii/trimestral_imovel {fii_year}",
                    self.ingest_fii_imovel(fii_year),
                ))

        # CIA_ABERTA — current-year IPE, FCA, ITR, and DFP slices.
        if "cia_aberta" in daily_entities:
            tasks.append(IngestTask(
                "cia_event",
                f"cia_aberta/ipe {year}",
                self.ingest_cia_ipe(year),
            ))
            # FCA valores mobiliários: the published CNPJ↔ticker map. The
            # current-year ZIP carries the full current registry, so the
            # daily refresh alone keeps vw_company_ticker fresh.
            tasks.append(IngestTask(
                "cia_ticker",
                f"cia_aberta/fca_valor_mobiliario {year}",
                self.ingest_cia_fca(year),
            ))
            for doc_type in ("itr", "dfp"):
                tasks.append(IngestTask(
                    "cia_account",
                    f"cia_aberta/{doc_type} {year}",
                    self.ingest_cia_itr_dfp(doc_type, year),
                ))
            # A DFP filed in January and a restated prior-year document land in
            # last year's ZIP: read its header, ingest only what is new (#383).
            for doc_type in ("itr", "dfp"):
                tasks.append(IngestTask(
                    "cia_account",
                    f"cia_aberta/{doc_type} {year - 1} new versions",
                    self.ingest_cia_itr_dfp_new_versions(doc_type, year - 1),
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

        return tasks

    async def daily_update(self) -> Dict[str, int]:
        """Incremental update: current month (and previous month for monthly files)."""
        today = date.today()
        year = today.year
        totals = _new_totals()
        tasks: List[IngestTask] = []
        daily_entities = _resolve_daily_entities()

        # Fund registry refresh
        # FII omitted on purpose — CVM retired FII/CAD/; registro_fundo covers it.
        if "fi" in daily_entities:
            totals["cvm_fund_registry"] += await self.ingest_fund_registry("fi")

        # CVM-175 unified registry refresh (active universe, all fund families)
        if "fi" in daily_entities:
            totals["cvm_fund_registry"] += await self.ingest_fund_registry_cvm175()

        # ETF registry refresh (distinct entity: curated seed, self-fetches cad_fi)
        if "etf" in daily_entities:
            totals["cvm_etf_registry"] += await self.ingest_etf_registry()

        tasks.extend(self._plan_daily_monthly_tasks(daily_entities, today))

        # Extrato das Informacoes: the current file, a snapshot CVM refreshes daily.
        # One slice (fi/extrato), whole file, its own table only.
        if "fi" in daily_entities:
            tasks.append(IngestTask(
                "cvm_fi_extrato",
                "fi/extrato",
                self.ingest_fi_extrato(),
            ))

        # Registry refresh is a sequential prerequisite for CIA slices.
        if "cia_aberta" in daily_entities:
            await self.ingest_cia_cad()

        tasks.extend(self._plan_daily_annual_tasks(daily_entities, year, today))

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
