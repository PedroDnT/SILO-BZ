"""Implied rates of B3 traded debenture PUs into ``b3_credit_implied_rate`` (#1007).

For every B3 trade group (instrument, trade date, settlement date, classification)
of a debenture whose agenda ANBIMA published (``anbima_debenture*``), it solves the
yield that discounts the agenda to the traded average PU
(``src/credit/implied_rate.py``, ``METHOD_VERSION``). The B3 rows are read from the
latest complete capture of each trade date and are never changed.

A trade that cannot be priced writes no row. Each reason is counted and the counts go
in the ``cvm_ingest_log`` note of the one ``credit/implied_rate`` row of the run. A
holiday list that disagrees with B3's own business-day count for a curve fails that
trade date instead of pricing it.

    python -m src.pipeline.credit_implied_pipeline --from 2026-09-01 --to 2026-10-08
    python -m src.pipeline.credit_implied_pipeline --from 2026-10-01 --to 2026-10-08 --codes CLAG13,RADL14
    python -m src.pipeline.credit_implied_pipeline --refresh-holidays --from ... --to ...
"""

from __future__ import annotations

import argparse
import asyncio
import io
import logging
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Iterable, Optional

import pandas as pd
import requests

from src.credit.implied_rate import (
    METHOD_VERSION, Bond, Calendar, Curve, Event, Market, Unsupported, implied_rate,
)
from src.parsers import anbima_holidays as H
from src.pipeline import ingest_log
from src.store.pg_client import get_pg_client, upsert_rows

logger = logging.getLogger(__name__)

TABLE = "b3_credit_implied_rate"
CDI_LOOKBACK_DAYS = 1100
METRICS = ("avg_price", "quantity", "volume_brl", "trade_count")

LATEST_TRADES_SQL = """
WITH cap AS (
    SELECT c.capture_id, c.observed_at, x.d::date AS trade_date
      FROM b3_credit_capture c
     CROSS JOIN LATERAL jsonb_array_elements_text(c.delivered_dates) AS x(d)
     WHERE c.status = 'complete' AND x.d::date BETWEEN %(a)s AND %(b)s
), latest AS (
    SELECT DISTINCT ON (trade_date) trade_date, capture_id FROM cap
     ORDER BY trade_date, observed_at DESC
)
SELECT f.capture_id, f.instrument_code, f.trade_date, f.settlement_date,
       f.trade_classification, f.metric, f.value
  FROM fact_credit_market f
  JOIN latest l ON l.capture_id = f.capture_id AND l.trade_date = f.trade_date
 WHERE f.instrument_code = ANY(%(codes)s) AND f.metric = ANY(%(metrics)s)
"""


def fetch_holidays() -> list[dict]:
    resp = requests.get(H.SOURCE_URL, timeout=60)
    resp.raise_for_status()
    df = pd.read_excel(io.BytesIO(resp.content), header=None, engine="xlrd")
    return H.parse_holidays(df.itertuples(index=False, name=None))


class CreditImpliedIngestor:
    def __init__(self, conn=None) -> None:
        self.conn = conn if conn is not None else get_pg_client()

    async def ingest(self, start: date, end: date, codes: Optional[Iterable[str]] = None,
                     refresh_holidays: bool = False) -> int:
        if end < start:
            raise ValueError("--to is before --from")
        codes = list(codes) if codes else None

        async def work() -> ingest_log.Outcome:
            return await asyncio.to_thread(self._run, start, end, codes, refresh_holidays)

        return await ingest_log.audited(self.conn, "credit", "implied_rate", work, upsert=upsert_rows)

    # -- reads ------------------------------------------------------------------

    def _rows(self, sql: str, params) -> list[tuple]:
        with self.conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()

    def _calendar(self, refresh: bool) -> Calendar:
        have = self._rows("SELECT holiday_date FROM anbima_holiday", None)
        if refresh or not have:
            rows = fetch_holidays()
            now = datetime.now(timezone.utc)
            for r in rows:
                r["observed_at"] = now
            upsert_rows(self.conn, "anbima_holiday", rows, conflict_columns="holiday_date")
            have = [(r["holiday_date"],) for r in rows]
        return Calendar(r[0] for r in have)

    def _bonds(self, codes: Optional[list[str]]) -> dict[str, Bond]:
        where, params = ("AND d.codigo = ANY(%s)", (codes,)) if codes else ("", None)
        heads = self._rows(f"""
            SELECT d.codigo, d.indexador, d.forma_remuneracao, d.taxa_remuneracao_pct, d.vne_brl,
                   d.data_inicio_rentabilidade, d.data_vencimento
              FROM anbima_debenture d
             WHERE EXISTS (SELECT 1 FROM anbima_debenture_event e WHERE e.codigo = d.codigo) {where}
        """, params)
        events: dict[str, list[Event]] = defaultdict(list)
        for codigo, de, ev, dl, pct in self._rows("""
            SELECT e.codigo, e.data_evento, e.evento, e.data_liquidacao, e.percentual_taxa_pct
              FROM anbima_debenture_event e
             WHERE e.observed_at = (SELECT max(x.observed_at) FROM anbima_debenture_event x
                                     WHERE x.codigo = e.codigo)
        """, None):
            events[codigo].append(Event(de, ev, dl or de, None if pct is None else float(pct)))
        return {
            c: Bond(c, idx, forma, None if tx is None else float(tx), float(vne), start, venc, tuple(events[c]))
            for c, idx, forma, tx, vne, start, venc in heads if events.get(c) and vne is not None
        }

    def _trades(self, start: date, end: date, codes: list[str]) -> list[dict]:
        groups: dict[tuple, dict] = {}
        for cap, code, td, sd, cls, metric, value in self._rows(
                LATEST_TRADES_SQL, {"a": start, "b": end, "codes": codes, "metrics": list(METRICS)}):
            g = groups.setdefault((code, td, sd, cls), {
                "codigo": code, "trade_date": td, "settlement_date": sd,
                "trade_classification": cls, "b3_capture_id": cap})
            g[metric] = None if value is None else float(value)
        return sorted(groups.values(), key=lambda g: (g["trade_date"], g["codigo"], g["trade_classification"]))

    def _focus(self, td: date) -> dict:
        """Focus median for each month, from the latest survey on or before the trade date."""
        out = {}
        for horizon, median in self._rows("""
            SELECT DISTINCT ON (horizon) horizon, median FROM bacen_expectativas
             WHERE endpoint_name = 'ExpectativaMercadoMensais' AND indicador = 'IPCA'
               AND reference_date <= %s AND reference_date > %s AND median IS NOT NULL
             ORDER BY horizon, reference_date DESC
        """, (td, td - timedelta(days=14))):
            mm, yy = horizon.split("/")
            out[(int(yy), int(mm))] = float(median)
        return out

    def _market(self, td: date, cal: Calendar, cdi: dict, ipca: dict) -> Market:
        focus = self._focus(td)
        curves: dict[str, list[tuple[int, float, int]]] = defaultdict(list)
        for curve, bd, cd, rate in self._rows("""
            SELECT curve, business_days, calendar_days, rate FROM b3_reference_rate
             WHERE trade_date = %s AND curve = 'PRE'
        """, (td,)):
            curves[curve].append((bd, float(rate), cd))
        if "PRE" not in curves:
            raise Unsupported("curve_missing", f"PRE {td}")
        for bd, _, cd in curves["PRE"]:
            if cal.du(td, td + timedelta(days=cd)) != bd:
                raise Unsupported("calendar_mismatch", f"{td}: {cd} calendar days = {bd} business days at B3")
        return Market(td, Curve([(bd, r) for bd, r, _ in curves["PRE"]]), cdi, ipca, focus)

    # -- the run ---------------------------------------------------------------

    def _run(self, start: date, end: date, codes: Optional[list[str]], refresh: bool) -> ingest_log.Outcome:
        cal = self._calendar(refresh)
        bonds = self._bonds(codes)
        wanted = codes or sorted(bonds)
        trades = self._trades(start, end, wanted) if wanted else []
        cdi = {d: float(v) for d, v in self._rows(
            "SELECT reference_date, value FROM bacen_sgs WHERE series_code = 12 AND reference_date >= %s",
            (start - timedelta(days=CDI_LOOKBACK_DAYS),)) if v is not None}
        ipca = {(d.year, d.month): float(v) for d, v in self._rows(
            "SELECT reference_date, value FROM bacen_sgs WHERE series_code = 433 AND reference_date >= '2000-01-01'",
            None) if v is not None}

        skipped: Counter = Counter()
        rows, markets = [], {}
        now = datetime.now(timezone.utc)
        for t in trades:
            td = t["trade_date"]
            if td not in markets:
                try:
                    markets[td] = self._market(td, cal, cdi, ipca)
                except Unsupported as exc:
                    markets[td] = exc
            market = markets[td]
            if isinstance(market, Unsupported):
                skipped[market.reason] += 1
                continue
            bond = bonds.get(t["codigo"])
            if bond is None:
                skipped["no_schedule"] += 1
                continue
            try:
                res = implied_rate(bond, t.get("avg_price") or 0.0, t["settlement_date"], market, cal)
            except Unsupported as exc:
                skipped[exc.reason] += 1
                continue
            rows.append({
                "codigo": t["codigo"], "trade_date": td, "settlement_date": t["settlement_date"],
                "trade_classification": t["trade_classification"], "method_version": METHOD_VERSION,
                "is_calculated": True, "b3_capture_id": t["b3_capture_id"], "pu_brl": t["avg_price"],
                "quantity": t.get("quantity"), "volume_brl": t.get("volume_brl"),
                "trade_count": None if t.get("trade_count") is None else int(t["trade_count"]),
                "indexador": bond.indexador, "forma_remuneracao": bond.forma_remuneracao,
                "contract_rate_pct": bond.taxa_remuneracao_pct, "implied_rate_pct": res.implied_rate_pct,
                "rate_basis": res.rate_basis, "flows_used": res.flows_used,
                "inputs": res.inputs, "solver": res.solver, "computed_at": now,
            })
        n = upsert_rows(
            self.conn, TABLE, rows,
            conflict_columns="codigo,trade_date,settlement_date,trade_classification,method_version",
        ) if rows else 0
        note = (f"{METHOD_VERSION}: {len(trades)} trade groups, {len(rows)} priced, "
                f"skipped " + (", ".join(f"{k}={v}" for k, v in sorted(skipped.items())) or "none"))
        logger.info("credit/implied_rate %s", note)
        if trades and not rows:
            # Nothing priced is not "ok": trades were there and none could be used.
            raise ingest_log.PartialIngestError(note, rows=0)
        return ingest_log.Outcome(n, "ok", note)


def main(argv: Optional[list[str]] = None) -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--from", dest="start", type=date.fromisoformat, required=True)
    p.add_argument("--to", dest="end", type=date.fromisoformat, required=True)
    p.add_argument("--codes", help="Comma-separated ANBIMA codes; blank: every bond with a stored agenda")
    p.add_argument("--refresh-holidays", action="store_true", help="Re-read ANBIMA's holiday list first")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    codes = [c.strip().upper() for c in args.codes.split(",") if c.strip()] if args.codes else None
    asyncio.run(CreditImpliedIngestor().ingest(args.start, args.end, codes, args.refresh_holidays))


if __name__ == "__main__":
    main()
