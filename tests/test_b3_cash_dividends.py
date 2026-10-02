"""Offline tests for the full B3 cash-distribution history (migration 51).

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

from src.fetchers.b3_corporate_events_fetcher import (
    B3CorporateEventsFetcher,
    cash_dividend_query_name,
)
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


def test_a_null_total_is_an_error_not_an_empty_history():
    """Over B3's page-size cap the reply is HTTP 200, no rows and a null
    total (research §1, P1); read as 0 it would publish "no dividends"."""
    f = B3CorporateEventsFetcher(sleep_between=0)
    capped = {"page": {"pageNumber": 1, "pageSize": 200,
                       "totalRecords": None, "totalPages": None},
              "results": []}
    with patch.object(f, "_call", return_value=capped):
        with pytest.raises(ValueError, match="no totalRecords"):
            f.fetch_cash_dividends("PETROBRAS", page_size=200)


@pytest.mark.parametrize("published, sent", [
    # docs/reference/research/cash-dividends-mapping.md §1: each "sent" form was probed
    # live and returned the same total as B3's page; the slashed ones return 0.
    ("KLABIN S/A", "KLABINSA"),
    ("TIM PART S/A", "TIMPART SA"),
    ("SUZANO S.A.", "SUZANOS.A."),
    ("FRAS-LE", "FRASLE"),
    ("REDE D OR", "REDED OR"),
    (" petrobras ", "PETROBRAS"),
])
def test_query_name_is_normalized_as_b3s_own_page_does(published, sent):
    assert cash_dividend_query_name(published) == sent


def test_a_slashed_name_is_queried_without_its_slash():
    """KLABIN S/A as published gets totalRecords 0, which the count check
    would accept as "no dividends": the slash must go before the call."""
    f = B3CorporateEventsFetcher(sleep_between=0)
    with patch.object(f, "_call", return_value=_page([ROW_ON_2026], 1, 1, 1)) as call:
        f.fetch_cash_dividends("KLABIN S/A")
    assert call.call_args.args[1]["tradingName"] == "KLABINSA"


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
    sql = (ROOT / "src/store/migrations/51_b3_cash_dividend.sql").read_text(encoding="utf-8")
    assert "CREATE UNIQUE INDEX IF NOT EXISTS uq_b3_cash_dividend" in sql
    assert "NULLS NOT DISTINCT" in sql
    table = sql.split("CREATE TABLE IF NOT EXISTS b3_cash_dividend", 1)[1].split(");", 1)[0]
    assert "isin" not in table.lower(), "the ISIN is resolved in the view, never stored"
    assert "CREATE OR REPLACE VIEW vw_b3_cash_dividend_isin" in sql
    assert "c.n_isins = 1" in sql, "ambiguous resolutions must stay NULL"


def test_schema_sql_carries_the_table_but_leaves_the_view_to_the_migration():
    """The view reads cia_ticker, which only migration 25 creates: in
    schema.sql it would fail on a fresh database, before migrations run."""
    schema = (ROOT / "src/store/schema.sql").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS b3_cash_dividend" in schema
    assert "CREATE OR REPLACE VIEW vw_b3_cash_dividend_isin" not in schema
    assert "CREATE TABLE IF NOT EXISTS cia_ticker" not in schema


def test_daily_job_wires_cash_dividends_without_making_them_fatal():
    """Their own daily step since 2026-09-30 (src/pipeline/run_b3_events.py),
    after the deploy hook, so a failure cannot skip the analytical apply or
    the dashboard publish. tests/test_run_b3_events.py pins the workflow."""
    step = (ROOT / "src/pipeline/run_b3_events.py").read_text(encoding="utf-8")
    assert "ingest_cash_dividends()" in step
    assert 'failures.append(("b3_cash_dividends", exc))' in step


def test_backfill_flag_exists():
    src = (ROOT / "src/pipeline/run_backfill.py").read_text(encoding="utf-8")
    assert "--b3-cash-dividends-only" in src
    assert "full_history=True" in src


# -- sweep status ---------------------------------------------------------------
@pytest.fixture(autouse=True)
def _audit(audit_log):
    """Every ingest here writes its audit row through the capture, never a database."""
    return audit_log


@pytest.mark.asyncio
async def test_sweep_upserts_parsed_rows_and_skips_codes_without_a_name(audit_log):
    with patch("src.pipeline.b3_pipeline.get_pg_client", return_value=MagicMock()), \
         patch("src.pipeline.ingest_b3_cash_dividends.ingest_b3_cash_dividends",
               return_value=2) as ingest, \
         patch("src.fetchers.b3_corporate_events_fetcher.B3CorporateEventsFetcher") as Fetcher:
        fetcher = Fetcher.return_value
        fetcher.trading_names.return_value = {"PETR": [_NAME_PETR]}
        fetcher.fetch_cash_dividends.return_value = [ROW_ON_2026, ROW_PN_1996]
        ing = B3Ingestor(fetcher=MagicMock())
        finishes = audit_log.finished
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
        await ing.ingest_cash_dividends(issuers=["PETR"], since=date(2025, 1, 1))

    records = ingest.call_args.args[1]
    assert [r["last_date_prior_ex"] for r in records] == [date(2026, 8, 21)]


@pytest.mark.asyncio
async def test_one_company_failing_fails_the_slice_but_not_the_sweep(audit_log):
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
        finishes = audit_log.finished
        n = await ing.ingest_cash_dividends(issuers=["PETR", "VALE"], full_history=True)

    assert n == 1 and ingest.called
    assert finishes[-1]["status"] == "error"
    assert "PETR/PETROBRAS" in finishes[-1]["error"]


@pytest.mark.asyncio
async def test_no_fetchable_company_is_an_error_not_a_clean_empty_run(audit_log):
    with patch("src.pipeline.b3_pipeline.get_pg_client", return_value=MagicMock()), \
         patch("src.pipeline.ingest_b3_cash_dividends.ingest_b3_cash_dividends") as ingest, \
         patch("src.fetchers.b3_corporate_events_fetcher.B3CorporateEventsFetcher") as Fetcher:
        Fetcher.return_value.trading_names.return_value = {}
        ing = B3Ingestor(fetcher=MagicMock())
        finishes = audit_log.finished
        n = await ing.ingest_cash_dividends(issuers=["XXXX"], full_history=True)

    assert n == 0
    ingest.assert_not_called()
    assert finishes[-1]["status"] == "error"


@pytest.mark.asyncio
async def test_a_company_reached_by_two_codes_is_fetched_once(audit_log):
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
        await ing.ingest_cash_dividends(issuers=["AXIA", "AXIB", "ELET"], full_history=True)

    assert fetcher.fetch_cash_dividends.call_count == 1


def test_view_reaches_pre_rename_tickers_through_cia_ticker():
    sql = (ROOT / "src/store/migrations/51_b3_cash_dividend.sql").read_text(encoding="utf-8")
    assert "t.cnpj_cia = d.cnpj" in sql


def test_identical_installments_are_kept_apart_by_occurrence():
    """PETR lists equal installments as byte-identical rows; both must survive."""
    recs = parse_cash_dividends("PETR", "PETROBRAS", [ROW_ON_2026, dict(ROW_ON_2026), ROW_PN_2026])
    keys = [tuple(r[c] for c in CONFLICT_COLS.split(",")) for r in recs]
    assert len(set(keys)) == 3
    assert [r["occurrence"] for r in recs] == [1, 2, 1]


# -- codes B3's catalog no longer lists (delisted or renamed) --------------------

_AXIA = {"trading_name": "AXIA ENERGIA", "cnpj": "00001180000126"}


async def _sweep_with_tape(catalog, tape, issuers, audit_log):
    """Run the sweep with B3's catalog and the tape lookup both faked."""
    with patch("src.pipeline.b3_pipeline.get_pg_client", return_value=MagicMock()), \
         patch("src.pipeline.ingest_b3_cash_dividends.ingest_b3_cash_dividends",
               return_value=1) as ingest, \
         patch("src.fetchers.b3_corporate_events_fetcher.B3CorporateEventsFetcher") as Fetcher:
        fetcher = Fetcher.return_value
        fetcher.trading_names.return_value = catalog
        fetcher.fetch_cash_dividends.return_value = [ROW_ON_2026]
        ing = B3Ingestor(fetcher=MagicMock())
        ing._tape_names = MagicMock(return_value=tape)
        finishes = audit_log.finished
        await ing.ingest_cash_dividends(issuers=issuers, full_history=True)
    fetched = [c.args[0] for c in fetcher.fetch_cash_dividends.call_args_list]
    records = ingest.call_args.args[1] if ingest.called else []
    return fetched, records, finishes, ing._tape_names


@pytest.mark.asyncio
async def test_a_delisted_code_is_fetched_under_the_name_the_tape_printed(audit_log):
    """ENBR left B3's catalog in 2023; its COTAHIST name still answers (34 rows)."""
    fetched, records, finishes, _ = await _sweep_with_tape(
        {"PETR": [_NAME_PETR]},
        {"ENBR": ("ENERGIAS BR", ["99999999000191"])},
        ["PETR", "ENBR"], audit_log)
    assert fetched == ["PETROBRAS", "ENERGIAS BR"]
    enbr = [r for r in records if r["issuing_company"] == "ENBR"]
    assert enbr and enbr[0]["trading_name"] == "ENERGIAS BR"
    assert enbr[0]["cnpj"] == "99999999000191"
    assert finishes[-1]["status"] == "ok"


@pytest.mark.asyncio
async def test_a_renamed_code_is_skipped_so_its_history_is_not_counted_twice(audit_log):
    """ELET's history arrives under AXIA ENERGIA; ELETROBRAS would repeat it."""
    fetched, _, _, tape = await _sweep_with_tape(
        {"AXIA": [_AXIA]},
        {"ELET": ("ELETROBRAS", ["00001180000126"])},
        ["AXIA", "ELET"], audit_log)
    assert fetched == ["AXIA ENERGIA"]
    assert tape.call_args.args[0] == ["ELET"], "only codes missing from the catalog"


@pytest.mark.asyncio
async def test_a_tape_prefix_that_is_not_the_catalog_key_is_fetched_by_catalog_name(audit_log):
    """ADMF3 trades as B100 S.A.: B100 is never a tape prefix, so without the
    CNPJ link its history would never be fetched at all."""
    fetched, records, _, _ = await _sweep_with_tape(
        {"B100": [{"trading_name": "B100", "cnpj": "88888888000188"}]},
        {"ADMF": ("B100 S.A.", ["88888888000188"])},
        ["ADMF"], audit_log)
    assert fetched == ["B100"]
    assert {(r["issuing_company"], r["cnpj"]) for r in records} == {("ADMF", "88888888000188")}


@pytest.mark.asyncio
async def test_several_cnpjs_for_a_tape_code_leave_the_cnpj_null(audit_log):
    _, records, _, _ = await _sweep_with_tape(
        {}, {"OLDX": ("OLD CO", ["11111111000111", "22222222000122"])}, ["OLDX"], audit_log)
    assert [r["cnpj"] for r in records] == [None]


@pytest.mark.asyncio
async def test_a_tape_name_already_fetched_from_the_catalog_is_not_fetched_again(audit_log):
    """Same name, normalized: KLABIN S/A from the catalog, KLABIN SA elsewhere."""
    fetched, _, _, _ = await _sweep_with_tape(
        {"KLBN": [{"trading_name": "KLABIN S/A", "cnpj": ""}]},
        {"KLBX": ("KLABIN SA", [])},
        ["KLBN", "KLBX"], audit_log)
    assert fetched == ["KLABIN S/A"]


@pytest.mark.asyncio
async def test_a_code_with_no_catalog_name_and_no_tape_name_is_reported_not_guessed(audit_log):
    fetched, _, finishes, _ = await _sweep_with_tape({}, {}, ["XXXX"], audit_log)
    assert fetched == []
    assert finishes[-1]["status"] == "error"


def test_tape_lookup_reads_the_tapes_own_name_and_cvms_ticker_history():
    import inspect
    src = inspect.getsource(B3Ingestor._tape_names)
    assert "nome_resumido" in src and "cia_ticker" in src
    assert "ORDER BY left(codneg, 4), trade_date DESC" in src, "latest session's name"
