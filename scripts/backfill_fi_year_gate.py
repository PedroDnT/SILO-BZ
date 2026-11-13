"""Decide whether one FI year of a backfill dispatch can be skipped.

backfill.yml's FI matrix runs one job per year. Before it fetches anything,
this script reads ``cvm_ingest_log`` (and, for the 2019/2020 HIST years, the
diario partition) and writes ``skip=true`` to ``$GITHUB_OUTPUT`` when that year
is already complete. It was an inline heredoc in the workflow, with the
dispatch inputs pasted into its source (#1111); now the inputs arrive as
environment variables and the connection comes from ``src.store.pg_client``.

Environment:

- ``POSTGRES_URL``: empty means "run the year" (nothing to read).
- ``YEAR``: the matrix year.
- ``FI_DOC_TYPE``: ``all`` or one FI document type.
- ``FI_REPAIR_GAPS`` / ``FI_FORCE``: ``true`` or anything else.
- ``FI_MONTHS``: the free-text ``fi_months`` input, never evaluated.
- ``GITHUB_OUTPUT``: where ``skip=true`` goes.

It fails open: a failed coverage query prints its traceback and runs the
year, because skipping on an error would leave a gap that looks filled.
Read-only: it never writes to the database.

    YEAR=2024 FI_DOC_TYPE=cda python scripts/backfill_fi_year_gate.py
"""
from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.store import pg_client  # noqa: E402

# Doc types whose "ok months" in cvm_ingest_log say whether a year is done.
# extrato is deliberately absent: its yearly files are re-filed weekly and
# logged with no month, so "ok months" says nothing and the year always runs
# (about 10 MB; years before 2021 are skipped inside the ingest).
MONTHLY_DOC_TYPES = (
    "inf_diario",
    "perfil_mensal",
    "balancete",
    "cda",
    "cda_acoes",
    "cda_cotas",
    "cda_debentures",
    "lamina",
)

_OK_MONTHS_SQL = """
    SELECT COUNT(DISTINCT period_month)
    FROM cvm_ingest_log
    WHERE entity='fi' AND doc_type=%s
      AND period_year=%s AND status='ok'
"""

# Pre-2023 CDA holdings (and other yearly HIST files) log period_month NULL.
# COUNT(DISTINCT period_month) ignores NULL, so a finished or unpublished-block
# year looks like 0 months and the job re-downloads forever. The latest yearly
# row is the ground truth for that archive.
_YEARLY_STATUS_SQL = """
    SELECT status
    FROM cvm_ingest_log
    WHERE entity='fi' AND doc_type=%s
      AND period_year=%s AND period_month IS NULL
    ORDER BY finished_at DESC NULLS LAST
    LIMIT 1
"""


def _flag(value: Optional[str]) -> bool:
    return (value or "").strip() == "true"


def read_coverage(conn: Any, year: int, requested_doc: str) -> Dict[str, Any]:
    """Return the ok-month counts, the yearly HIST status and the diario rows."""
    with conn.cursor() as cur:
        counts = {}
        for doc in MONTHLY_DOC_TYPES:
            cur.execute(_OK_MONTHS_SQL, (doc, year))
            counts[doc] = cur.fetchone()[0]
        yearly_status = None
        if requested_doc != "all":
            cur.execute(_YEARLY_STATUS_SQL, (requested_doc, year))
            row = cur.fetchone()
            yearly_status = row[0] if row else None
        diario_rows = None
        if year in (2019, 2020):
            # year is one of two literals here, never caller text.
            cur.execute(f"SELECT COUNT(*) FROM cvm_fi_diario_{year}")
            diario_rows = cur.fetchone()[0]
    return {
        "counts": counts,
        "yearly_status": yearly_status,
        "diario_rows": diario_rows,
    }


def decide(
    year: int,
    requested_doc: str,
    *,
    repair_gaps: bool,
    months: str,
    force: bool,
    coverage: Optional[Dict[str, Any]],
) -> Tuple[bool, str]:
    """Return ``(skip, message)`` for one year. ``coverage`` None means unread."""
    # A repair run must never be gated on cvm_ingest_log: counting 'ok' audit
    # months is precisely the signal that was wrong. fi/balancete 2026-06
    # carried a fresh 'error' row over 2,178,163 real rows, and 32 other months
    # carried no 'ok' row at all. --repair-gaps / --months decide what to fetch
    # by reading the table itself.
    # No pre-2023 exclusion for holdings blocks 4 and 2: they live in the same
    # yearly HIST archive as `cda`, from 2005. Block 6 (cda_debentures) is
    # absent from the 2005 archive (sibling blocks present, BLC_6 never
    # released). That is logged skipped, not a gap; the yearly status below
    # keeps the job from re-downloading it. A month repair still cannot reach
    # hist years: gaps.FI_MONTHLY_TABLES carries that cutoff and says so.
    if repair_gaps or months.strip():
        return False, f"RUN: {year} (repair mode — coverage is decided from the table, not the audit log)"
    if force and requested_doc != "all":
        # Coverage says what landed, not whether it landed at the right grain.
        # After a key fix (migration 49: cvm_fi_cda kept one bond per fund)
        # every "complete" year is complete and wrong, and only a re-ingest
        # restores it. Scoped to one doc type so a force can never re-fetch
        # all of FI.
        return False, f"RUN: {year} {requested_doc} (forced — coverage gate bypassed)"
    if coverage is None:
        return False, f"RUN: {year} (coverage unread — not skipping)"

    counts = coverage["counts"]
    if requested_doc != "all":
        # .get, not []: a doc type the gate has not learned yet must run the
        # year, not abort the dispatch. Unknown means run the year.
        n = counts.get(requested_doc)
        if n is None:
            return False, f"RUN: {year} {requested_doc} (no coverage rule — not skipping)"
        if n >= 11:
            return True, f"SKIP: {year} {requested_doc} complete ({n} ok months)"
        yearly_status = coverage.get("yearly_status")
        if year <= 2022 and yearly_status in ("ok", "skipped"):
            # Yearly HIST archives (inf_diario through 2020, CDA through 2022)
            # log period_month NULL. 2023+ is monthly; a stray yearly row must
            # not skip an incomplete monthly year.
            return True, f"SKIP: {year} {requested_doc} yearly HIST {yearly_status}"
        return False, f"RUN: {year} {requested_doc} incomplete ({n} ok months)"

    # Gate the whole-FI skip on BOTH inf_diario AND perfil_mensal so a
    # complete diario cannot skip the run that fills cvm_fi_perfil.
    diario_months = counts["inf_diario"]
    perfil_months = counts["perfil_mensal"]
    if year in (2019, 2020):
        diario_rows = coverage.get("diario_rows")
        if (diario_rows or 0) > 2_000_000 and perfil_months >= 11:
            return True, (
                f"SKIP: {year} hist complete ({diario_rows} diario rows, "
                f"{perfil_months} perfil months)"
            )
        return False, (
            f"RUN: {year} hist incomplete (diario rows={diario_rows}, "
            f"perfil months={perfil_months})"
        )
    if diario_months >= 11 and perfil_months >= 11:
        return True, (
            f"SKIP: {year} complete ({diario_months} diario months, "
            f"{perfil_months} perfil months)"
        )
    return False, (
        f"RUN: {year} incomplete (diario months={diario_months}, "
        f"perfil months={perfil_months})"
    )


def main(environ: Optional[Dict[str, str]] = None) -> int:
    env = os.environ if environ is None else environ
    year = int(env["YEAR"])
    requested_doc = (env.get("FI_DOC_TYPE") or "all").strip()
    repair_gaps = _flag(env.get("FI_REPAIR_GAPS"))
    months = env.get("FI_MONTHS") or ""
    force = _flag(env.get("FI_FORCE"))

    coverage = None
    # Repair and force never read coverage, so they need no connection.
    needs_coverage = not (repair_gaps or months.strip()) and not (
        force and requested_doc != "all"
    )
    url = "".join((env.get("POSTGRES_URL") or "").split())
    if needs_coverage:
        if not url:
            print("POSTGRES_URL missing; running the year")
        else:
            try:
                conn = pg_client.connect(url, connect_timeout=20)
                try:
                    coverage = read_coverage(conn, year, requested_doc)
                finally:
                    conn.close()
            except Exception:
                traceback.print_exc()
                print("Coverage query failed; running the year (fail-open)")

    skip, message = decide(
        year,
        requested_doc,
        repair_gaps=repair_gaps,
        months=months,
        force=force,
        coverage=coverage,
    )
    print(message)
    if skip:
        with open(env["GITHUB_OUTPUT"], "a") as f:
            f.write("skip=true\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
