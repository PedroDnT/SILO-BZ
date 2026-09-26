"""Offline tests for the full B3 cash-distribution history (migration 48).

Fixtures are verbatim rows from GetListedCashDividends / GetInitialCompanies,
captured live on 2026-09-26 (tradingName PETROBRAS), so a change in B3's field
names or formats fails here instead of producing an empty or wrong table.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.fetchers.b3_corporate_events_fetcher import B3CorporateEventsFetcher
from src.pipeline.b3_pipeline import B3Ingestor
from src.pipeline.ingest_b3_cash_dividends import CONFLICT_COLS, parse_cash_dividends

ROOT = Path(__file__).resolve().parents[1]

ROW_ON_2026 = {
    "typeStock": "ON", "dateApproval": "06/08/2026", "valueCash": "0,67407131",
    "ratio": "1", "corporateAction": "JRS CAP PROPRIO", "lastDatePriorEx": "21/08/2026",
    "dateClosingPricePriorExDate": "21/08/2026", "closingPricePriorExDate": "49,34",
    "quotedPerShares": "1", "corporateActionPrice": "1,366176",
    "lastDateTimePriorEx": "2026-08-21T00:00:00",
}
ROW_PN_2026 = {
    "typeStock": "PN", "dateApproval": "06/08/2026", "valueCash": "0,20250435",
    "ratio": "1", "corporateAction": "JRS CAP PROPRIO", "lastDatePriorEx": "21/08/2026",
    "dateClosingPricePriorExDate": "21/08/2026", "closingPricePriorExDate": "44,30",
    "quotedPerShares": "1", "corporateActionPrice": "0,457120",
    "lastDateTimePriorEx": "2026-08-21T00:00:00",
}
# The per-thousand-shares era: value and close are both per 1000 shares.
ROW_PN_1996 = {
    "typeStock": "PN", "dateApproval": "21/03/1996", "valueCash": "5,1471",
    "ratio": "1000", "corporateAction": "DIVIDENDO", "lastDatePriorEx": "21/03/1996",
    "dateClosingPricePriorExDate": "20/03/1996", "closingPricePriorExDate": "114,99",
    "quotedPerShares": "1000", "corporateActionPrice": "4,476128",
    "lastDateTimePriorEx": "1996-03-21T00:00:00",
}
COMPANY_PETR = {
    "codeCVM": "9512", "issuingCompany": "PETR",
    "companyName": "PETROLEO BRASILEIRO S.A. PETROBRAS", "tradingName": "PETROBRAS",
    "cnpj": "33000167000101", "status": "A",
}


_NAME_PETR = {"trading_name": "PETROBRAS", "cnpj": "33000167000101"}


def _page(results, number, total_pages, total_records):
    return {
        "page": {"pageNumber": number, "pageSize": 120,
                 "totalRecords": total_records, "totalPages": total_pages},
        "results": results,
    }


# -- fetcher ------------------------------------------------------------------

def test_fetch_pages_to_the_end_because_b3_sorts_by_class_first():
    """Page one of PETR is all ON; stopping there would lose every PN row."""
    f = B3CorporateEventsFetcher(sleep_between=0)
    pages = [_page([ROW_ON_2026], 1, 2, 2), _page([ROW_PN_2026], 2, 2, 2)]
    with patch.object(f, "_call", side_effect=pages) as call:
        rows = f.fetch_cash_dividends("PETROBRAS")
    assert [r["typeStock"] for r in rows] == ["ON", "PN"]
    assert call.call_count == 2
    endpoint, payload = call.call_args_list[0].args
    assert endpoint == "GetListedCashDividends"
    assert payload["tradingName"] == "PETROBRAS"


def test_short_read_against_totalrecords_raises():
    """Publishing a truncated history would claim dividends that exist do not."""
    f = B3CorporateEventsFetcher(sleep_between=0)
    with patch.object(f, "_call", return_value=_page([ROW_ON_2026], 1, 1, 343)):
        with pytest.raises(ValueError, match="totalRecords=343"):
            f.fetch_cash_dividends("PETROBRAS")


def test_a_company_with_no_distributions_is_an_empty_list_not_an_error():
    f = B3CorporateEventsFetcher(sleep_between=0)
    with patch.object(f, "_call", return_value=_page([], 1, 0, 0)):
        assert f.fetch_cash_dividends("NEWCO") == []


def test_trading_names_come_from_b3s_catalog():
    f = B3CorporateEventsFetcher(sleep_between=0)
    with patch.object(f, "list_companies", return_value=iter([
        COMPANY_PETR,
        {"issuingCompany": "PETR", "tradingName": "PETROBRAS  "},  # padded repeat
        {"issuingCompany": "ITSA", "tradingName": "ITAUSA"},
        {"issuingCompany": "BBAS", "tradingName": "BRASIL", "cnpj": "191"},
        {"issuingCompany": "", "tradingName": "ORPHAN"},
    ])):
        names = f.trading_names()
    assert names == {
        "PETR": [{"trading_name": "PETROBRAS", "cnpj": "33000167000101"}],
        "ITSA": [{"trading_name": "ITAUSA", "cnpj": ""}],
        "BBAS": [{"trading_name": "BRASIL", "cnpj": "00000000000191"}],
    }


# -- parser -------------------------------------------------------------------

def test_fields_are_parsed_verbatim():
    [rec] = parse_cash_dividends("petr", " PETROBRAS ", [ROW_ON_2026])
    assert rec["issuing_company"] == "PETR"
    assert rec["trading_name"] == "PETROBRAS"
    assert rec["type_stock"] == "ON"
    assert rec["corporate_action"] == "JRS CAP PROPRIO"
    assert rec["last_date_prior_ex"] == date(2026, 8, 21)
    assert rec["date_approval"] == date(2026, 8, 6)
    assert rec["value_cash"] == Decimal("0.67407131")
    assert rec["closing_price_prior_ex"] == Decimal("49.34")
    assert rec["corporate_action_price"] == Decimal("1.366176")
    assert rec["raw"] is ROW_ON_2026


def test_per_thousand_era_is_stored_as_published_not_rescaled():
    [rec] = parse_cash_dividends("PETR", "PETROBRAS", [ROW_PN_1996])
    assert rec["value_cash"] == Decimal("5.1471")
    assert rec["quoted_per_shares"] == Decimal("1000")
    # B3's published yield reproduces from the stored fields.
    yld = rec["value_cash"] / rec["closing_price_prior_ex"] * 100
    assert abs(yld - rec["corporate_action_price"]) < Decimal("0.0001")


def test_since_keeps_only_the_recent_tail():
    recs = parse_cash_dividends(
        "PETR", "PETROBRAS", [ROW_ON_2026, ROW_PN_1996], since=date(2025, 1, 1)
    )
    assert [r["last_date_prior_ex"].year for r in recs] == [2026]


def test_rows_without_class_or_action_are_dropped_not_filled():
    bad = dict(ROW_ON_2026, typeStock="")
    worse = dict(ROW_ON_2026, corporateAction=None)
    assert parse_cash_dividends("PETR", "PETROBRAS", [bad, worse]) == []


def test_unparseable_value_is_null_never_zero():
    [rec] = parse_cash_dividends("PETR", "PETROBRAS", [dict(ROW_ON_2026, valueCash="n/d")])
    assert rec["value_cash"] is None


def test_conflict_columns_are_a_comma_separated_string():
    assert isinstance(CONFLICT_COLS, str)
    assert CONFLICT_COLS.split(",") == [
        "trading_name", "type_stock", "corporate_action",
        "last_date_prior_ex", "date_approval", "value_cash", "occurrence",
    ]


# -- schema and wiring ----------------------------------------------------------

def test_migration_declares_the_key_and_carries_no_synthesised_isin():
    sql = (ROOT / "src/store/migrations/48_b3_cash_dividend.sql").read_text(encoding="utf-8")
    assert "CREATE UNIQUE INDEX IF NOT EXISTS uq_b3_cash_dividend" in sql
    assert "NULLS NOT DISTINCT" in sql
    table = sql.split("CREATE TABLE IF NOT EXISTS b3_cash_dividend", 1)[1].split(");", 1)[0]
    assert "isin" not in table.lower(), "the ISIN is resolved in the view, never stored"
    assert "CREATE OR REPLACE VIEW vw_b3_cash_dividend_isin" in sql
    assert "c.n_isins = 1" in sql, "ambiguous resolutions must stay NULL"


def test_schema_sql_carries_the_table_and_view():
    schema = (ROOT / "src/store/schema.sql").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS b3_cash_dividend" in schema
    assert "CREATE OR REPLACE VIEW vw_b3_cash_dividend_isin" in schema


def test_daily_run_wires_cash_dividends_without_making_them_fatal():
    run_daily = (ROOT / "src/pipeline/run_daily.py").read_text(encoding="utf-8")
    assert "ingest_cash_dividends()" in run_daily
    assert 'failures.append(("b3_cash_dividends", exc))' in run_daily


def test_backfill_flag_exists():
    src = (ROOT / "src/pipeline/run_backfill.py").read_text(encoding="utf-8")
    assert "--b3-cash-dividends-only" in src
    assert "full_history=True" in src


# -- sweep status ---------------------------------------------------------------

def _finish_recorder(ing):
    recorded: list[dict] = []

    def _finish(run_id, rows, error=None, *, skipped=False):
        recorded.append({"rows": rows, "error": error,
                         "status": "skipped" if skipped else ("error" if error else "ok")})

    ing._log_start = lambda *a, **k: None
    ing._log_finish = _finish
    return recorded


@pytest.mark.asyncio
async def test_sweep_upserts_parsed_rows_and_skips_codes_without_a_name():
    with patch("src.pipeline.b3_pipeline.get_pg_client", return_value=MagicMock()), \
         patch("src.pipeline.ingest_b3_cash_dividends.ingest_b3_cash_dividends",
               return_value=2) as ingest, \
         patch("src.fetchers.b3_corporate_events_fetcher.B3CorporateEventsFetcher") as Fetcher:
        fetcher = Fetcher.return_value
        fetcher.trading_names.return_value = {"PETR": [_NAME_PETR]}
        fetcher.fetch_cash_dividends.return_value = [ROW_ON_2026, ROW_PN_1996]
        ing = B3Ingestor(fetcher=MagicMock())
        finishes = _finish_recorder(ing)
        n = await ing.ingest_cash_dividends(issuers=["PETR", "ADMF"], full_history=True)

    assert n == 2
    records = ingest.call_args.args[1]
    assert {r["type_stock"] for r in records} == {"ON", "PN"}
    assert {r["cnpj"] for r in records} == {"33000167000101"}
    assert finishes[-1]["status"] == "ok"


@pytest.mark.asyncio
async def test_daily_window_drops_old_history_before_upsert():
    with patch("src.pipeline.b3_pipeline.get_pg_client", return_value=MagicMock()), \
         patch("src.pipeline.ingest_b3_cash_dividends.ingest_b3_cash_dividends",
               return_value=1) as ingest, \
         patch("src.fetchers.b3_corporate_events_fetcher.B3CorporateEventsFetcher") as Fetcher:
        fetcher = Fetcher.return_value
        fetcher.trading_names.return_value = {"PETR": [_NAME_PETR]}
        fetcher.fetch_cash_dividends.return_value = [ROW_ON_2026, ROW_PN_1996]
        ing = B3Ingestor(fetcher=MagicMock())
        _finish_recorder(ing)
        await ing.ingest_cash_dividends(issuers=["PETR"], since=date(2025, 1, 1))

    records = ingest.call_args.args[1]
    assert [r["last_date_prior_ex"] for r in records] == [date(2026, 8, 21)]


@pytest.mark.asyncio
async def test_one_company_failing_fails_the_slice_but_not_the_sweep():
    with patch("src.pipeline.b3_pipeline.get_pg_client", return_value=MagicMock()), \
         patch("src.pipeline.ingest_b3_cash_dividends.ingest_b3_cash_dividends",
               return_value=1) as ingest, \
         patch("src.fetchers.b3_corporate_events_fetcher.B3CorporateEventsFetcher") as Fetcher:
        fetcher = Fetcher.return_value
        fetcher.trading_names.return_value = {
            "PETR": [_NAME_PETR], "VALE": [{"trading_name": "VALE", "cnpj": ""}],
        }

        def _fetch(name):
            if name == "PETROBRAS":
                raise RuntimeError("SSL SYSCALL error: EOF detected")
            return [ROW_ON_2026]

        fetcher.fetch_cash_dividends.side_effect = _fetch
        ing = B3Ingestor(fetcher=MagicMock())
        finishes = _finish_recorder(ing)
        n = await ing.ingest_cash_dividends(issuers=["PETR", "VALE"], full_history=True)

    assert n == 1 and ingest.called
    assert finishes[-1]["status"] == "error"
    assert "PETR/PETROBRAS" in finishes[-1]["error"]


@pytest.mark.asyncio
async def test_no_fetchable_company_is_an_error_not_a_clean_empty_run():
    with patch("src.pipeline.b3_pipeline.get_pg_client", return_value=MagicMock()), \
         patch("src.pipeline.ingest_b3_cash_dividends.ingest_b3_cash_dividends") as ingest, \
         patch("src.fetchers.b3_corporate_events_fetcher.B3CorporateEventsFetcher") as Fetcher:
        Fetcher.return_value.trading_names.return_value = {}
        ing = B3Ingestor(fetcher=MagicMock())
        finishes = _finish_recorder(ing)
        n = await ing.ingest_cash_dividends(issuers=["XXXX"], full_history=True)

    assert n == 0
    ingest.assert_not_called()
    assert finishes[-1]["status"] == "error"


@pytest.mark.asyncio
async def test_a_company_reached_by_two_codes_is_fetched_once():
    """A renamed issuer (ELET -> AXIA) must not be swept twice under one name."""
    with patch("src.pipeline.b3_pipeline.get_pg_client", return_value=MagicMock()), \
         patch("src.pipeline.ingest_b3_cash_dividends.ingest_b3_cash_dividends",
               return_value=1), \
         patch("src.fetchers.b3_corporate_events_fetcher.B3CorporateEventsFetcher") as Fetcher:
        fetcher = Fetcher.return_value
        axia = {"trading_name": "AXIA ENERGIA", "cnpj": "00001180000126"}
        fetcher.trading_names.return_value = {"AXIA": [axia], "AXIB": [axia]}
        fetcher.fetch_cash_dividends.return_value = [ROW_ON_2026]
        ing = B3Ingestor(fetcher=MagicMock())
        _finish_recorder(ing)
        await ing.ingest_cash_dividends(issuers=["AXIA", "AXIB", "ELET"], full_history=True)

    assert fetcher.fetch_cash_dividends.call_count == 1


def test_view_reaches_pre_rename_tickers_through_cia_ticker():
    sql = (ROOT / "src/store/migrations/48_b3_cash_dividend.sql").read_text(encoding="utf-8")
    assert "t.cnpj_cia = d.cnpj" in sql


def test_identical_installments_are_kept_apart_by_occurrence():
    """PETR lists equal installments as byte-identical rows; both must survive."""
    recs = parse_cash_dividends("PETR", "PETROBRAS", [ROW_ON_2026, dict(ROW_ON_2026), ROW_PN_2026])
    keys = [tuple(r[c] for c in CONFLICT_COLS.split(",")) for r in recs]
    assert len(set(keys)) == 3
    assert [r["occurrence"] for r in recs] == [1, 2, 1]
