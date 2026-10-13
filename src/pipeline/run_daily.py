"""
Daily incremental update — run by GitHub Actions cron at 06:00 UTC.

Fetches:
  - CVM: current month + previous month for all entities
  - BACEN: last ~30 days
  - IBGE: IPCA item tree with weights, previous + current month
  - ANBIMA: latest monthly boletim, all classes (idempotent — upserts full history)
  - B3 COTAHIST: last 7 calendar days of daily quotation zips (404 → skipped)

Required env vars: POSTGRES_URL
Optional: CVM_REACHABLE=false (set by the workflows when the CVM probe fails)
skips the CVM entities, each with a `skipped` audit row; the rest still run.
"""

import asyncio
import logging
import os
import sys
import time
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.pipeline.cvm_pipeline import CVMIngestor, CVMRunFailed
from src.pipeline.bacen_pipeline import BacenIngestor
from src.pipeline.anbima_pipeline import AnbimaIngestor
from src.pipeline.b3_pipeline import B3Ingestor
from src.pipeline.ibge_pipeline import IbgeIngestor
from src.pipeline import ingest_log

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger("run_daily")

# The CVM probe's answer (scripts/check_cvm_reachable.py), passed in by
# daily_ingest.yml and watchdog.yml as CVM_REACHABLE (#866). Only the literal
# "false" skips CVM; unset or anything else keeps the CVM scope, so a local run
# and every caller that does not probe behave as before.
CVM_SKIP_DOC_TYPE = "daily_scope"


def cvm_reachable() -> bool:
    return os.getenv("CVM_REACHABLE", "").strip().lower() != "false"


def log_cvm_scope_skipped() -> list[str]:
    """One `skipped` audit row per CVM entity in the daily scope. Returns them.

    The probe found dados.cvm.gov.br unreachable from this runner, so the CVM
    scope is not attempted: it would spend ~40 minutes proving the same connect
    refusal (2026-08-29) while BACEN, B3 and the BDI ratchet wait. Never a
    silent skip: every entity gets its row, and a failed audit write raises
    (``ingest_log.start``/``finish`` raise, unlike ``audited``).

    The doc_type is ``daily_scope``, which no real slice uses. Health and the
    watchdog treat a later ``ok`` or ``skipped`` row with the same key as a
    heal, so a skip row on a real slice key would hide that slice's error.
    """
    from src.pipeline.cvm_pipeline import _resolve_daily_entities
    from src.store.pg_client import get_pg_client

    reason = (
        "CVM probe failed: dados.cvm.gov.br unreachable from this runner "
        "(CVM_REACHABLE=false); the CVM daily scope was not attempted (#866)"
    )
    client = get_pg_client()
    entities = sorted(_resolve_daily_entities())
    for entity in entities:
        run_id = str(uuid.uuid4())
        ingest_log.start(client, run_id, entity, CVM_SKIP_DOC_TYPE)
        ingest_log.finish(
            client, run_id, entity, CVM_SKIP_DOC_TYPE,
            status="skipped", rows=0, error=reason,
        )
        logger.error("CVM %s skipped: %s", entity, reason)
    return entities


async def _run_cvm(failures: list) -> dict:
    cvm_ingestor = CVMIngestor()
    # A failed CVM slice writes its 'error' audit row and raises (#691, owner
    # decision 2026-10-06). daily_update runs every other slice first, then
    # raises CVMRunFailed with the totals that did land. Run 33237536770
    # (2026-08-29 06:00) logged 44 CVMHostUnreachable slices and upserted 0
    # CVM rows; the process must fail for that — but AFTER the other sources
    # have run, so a CVM IP block does not skip BACEN/B3.
    try:
        totals = await cvm_ingestor.daily_update()
    except CVMRunFailed as exc:
        totals = dict(exc.totals)
        logger.error(
            "Daily CVM update finished with %d failed slice(s):", len(exc.failures),
        )
        for failure in exc.failures:
            logger.error("  %s", failure)
        failures.append(("cvm", exc))
    return totals


async def main() -> None:
    start_ts = time.monotonic()
    logger.info("Daily update starting")

    # Sub-ingest failures are COLLECTED, not swallowed. Each source still runs
    # even if an earlier one failed (one bad source must not skip the rest), but
    # the process exits non-zero at the end so CI goes red. Previously each of
    # these blocks logged a warning and continued: that is how the ANBIMA ingest
    # failed on every single daily run for months without anyone noticing, and it
    # contradicts the repo's own "no silent except" data-integrity rule (AGENTS.md).
    failures: list[tuple[str, Exception]] = []

    totals: dict[str, int] = {}
    if not cvm_reachable():
        # The workflow's own gate step turns the run red for this; here the
        # skip is recorded, and every non-CVM source below still runs.
        try:
            skipped = log_cvm_scope_skipped()
            logger.error(
                "CVM unreachable — skipped %d CVM entities: %s",
                len(skipped), ", ".join(skipped),
            )
        except Exception as exc:
            logger.error("Could not record the CVM skip: %s", exc, exc_info=True)
            failures.append(("cvm", exc))
    else:
        totals = await _run_cvm(failures)

    # BACEN: incremental refresh — re-fetches the last ~30 days; cheap.
    try:
        bacen_ingestor = BacenIngestor()
        from datetime import date, timedelta
        bacen_start = (date.today() - timedelta(days=30)).isoformat()
        bacen_totals = await bacen_ingestor.backfill(start=bacen_start)
        totals.update(bacen_totals)
    except Exception as exc:
        logger.error("BACEN daily refresh failed: %s", exc, exc_info=True)
        failures.append(("bacen", exc))

    # IBGE: the IPCA item tree with weights, previous + current month. IBGE
    # releases month M around the 10th of M+1; an unreleased month answers
    # header-only and lands 0 rows, which is not a failure.
    try:
        ibge_totals = await IbgeIngestor().daily_update()
        totals.update(ibge_totals)
    except Exception as exc:
        logger.error("IBGE IPCA daily refresh failed: %s", exc, exc_info=True)
        failures.append(("ibge", exc))

    # FNET (the B3 Fundos.NET document register) is NOT run here. It is its
    # own step in daily_ingest.yml, after the analytical layer and the
    # dashboard hook: FNET answers GitHub runners slowly, and on 2026-09-25
    # (run 36101156388) one fund's ReadTimeout failed this process, which
    # skipped ANALYZE, the analytics apply and the deploy for data that had
    # all landed. `python -m src.pipeline.fnet_pipeline`; it still fails the run.


    # ANBIMA: fetch latest monthly boletim (every ANBIMA class + type);
    # idempotent upsert.
    try:
        anbima_ingestor = AnbimaIngestor()
        anbima_totals = await anbima_ingestor.daily_update()
        totals.update(anbima_totals)
    except Exception as exc:
        logger.error("ANBIMA daily refresh failed: %s", exc, exc_info=True)
        failures.append(("anbima", exc))

    # B3 COTAHIST: public daily quotation zips. Weekends/holidays 404 and are
    # logged skipped; a real fetch/parse failure fails the daily run.
    try:
        b3_ingestor = B3Ingestor()
        b3_totals = await b3_ingestor.daily_update()
        totals.update(b3_totals)
    except Exception as exc:
        logger.error("B3 COTAHIST daily refresh failed: %s", exc, exc_info=True)
        failures.append(("b3", exc))

    # B3 BDI: securities lending (short balances + rates), investor-type
    # participation, index free float and the cash-market instrument registry.
    #
    # THIS ONE IS A RATCHET. B3 retains ~21 business days and then the session
    # is gone at any price (see src/fetchers/b3_bdi_fetcher.py), so unlike
    # every CVM slice a miss here is permanent, not merely late. It still does
    # not fail the whole daily run — the CVM sources have their own value and
    # must land — but the failure is recorded loudly and check_staleness.py
    # escalates a lending gap harder than a CVM one.
    try:
        bdi_totals = await B3Ingestor().daily_update_bdi()
        totals.update(bdi_totals)
    except Exception as exc:
        logger.error("B3 BDI lending/flow refresh failed: %s", exc, exc_info=True)
        failures.append(("b3_bdi", exc))

    # B3's consolidated trade file (migration 57, fixed income ETFs) is NOT run
    # here either: it is on arquivos.b3.com.br, the Cloudflare-fronted host of
    # the BDI ratchet above, and a failure here would skip the apply and the
    # deploy. It runs in run_b3_events.
    #
    # B3 corporate events and cash distributions are NOT run here. They are
    # their own step in daily_ingest.yml, after the dashboard deploy hook
    # (`python -m src.pipeline.run_b3_events`): a few hundred per-issuer calls
    # to B3's listed-companies proxy, and on 2026-08-29 a corporate-events SSL
    # EOF failed this process, which skipped ANALYZE, the analytics apply and
    # the deploy for data that had all landed. They still fail their own step.

    # ETF market snapshot: scrape etfsbrasil.com.br via Apify (NAV/price/cotistas
    # the post-CVM-175 daily file no longer exposes). Not a CVM source: it reads
    # its tickers from the stored cvm_etf_registry, so it runs when CVM is
    # unreachable. The ETF registry itself (CVM entity `etf`, cad_fi) does not. Runs only when APIFY_TOKEN
    # is set. ``ingest_etf_market`` writes a ``skipped`` audit row and returns 0
    # when Apify never delivered a dataset (403/408/ABORTED/usage-limit) — it
    # logs loudly there and does not re-raise, so a usage-limit day cannot skip
    # ANALYZE and analytics. A scrape that ran and returned bad/empty data still
    # raises, which adds to ``failures``.
    if os.getenv("APIFY_TOKEN"):
        try:
            from src.pipeline.ingest_etf_market import ingest_etf_market
            from src.store.pg_client import get_pg_client
            etf_rows = await ingest_etf_market(get_pg_client())
            totals["etf_market_snapshot"] = etf_rows
        except Exception as exc:
            logger.error("ETF market scrape failed: %s", exc, exc_info=True)
            failures.append(("etf_market", exc))
    else:
        logger.info("APIFY_TOKEN unset — skipping ETF market scrape")

    elapsed = time.monotonic() - start_ts
    total_rows = sum(totals.values())
    logger.info(
        "Daily update done in %.1fs — %d rows upserted: %s",
        elapsed, total_rows, totals,
    )

    if failures:
        summary = "; ".join(f"{name}: {exc}" for name, exc in failures)
        logger.error("Daily update FAILED for %d source(s) — %s",
                     len(failures), summary)
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
