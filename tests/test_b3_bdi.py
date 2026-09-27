"""Offline tests for the B3 BDI fetcher, parsers and gap calendar.

Every fixture under tests/fixtures/b3_bdi/ is a verbatim clip of a real
2026-09-10 export — preamble, band rows, pt-BR numbers and all — so these
tests fail if B3's layout drifts in a way the parsers would otherwise absorb
silently. HTTP and Postgres are mocked; nothing here touches the network.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.fetchers.b3_bdi_fetcher import B3BdiEmpty, B3BdiFetchError, B3BdiFetcher
from src.parsers.b3_bdi import (
    B3BdiParseError,
    mtd_reference_date,
    monthly_reference_month,
    parse_index_portfolio,
    parse_instrument_registry,
    parse_investor_participation,
    parse_investor_participation_monthly,
    parse_lending_open_position,
    parse_lending_rate,
    parse_number,
    reconcile_span,
)
from src.pipeline import ingest_b3_lending as lending

FIXTURES = Path(__file__).parent / "fixtures" / "b3_bdi"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8-sig")


# ── numbers and dates ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("2.737", Decimal("2737")),
        ("95,561969", Decimal("95.561969")),
        ("40,00%", Decimal("40.00")),
        ("274.811.942.485", Decimal("274811942485")),
        ("", None),
        ("-", None),
        (None, None),
        ("não é número", None),
    ],
)
def test_parse_number_handles_pt_br(raw, expected):
    assert parse_number(raw) == expected


# ── BTBLendingOpenPosition ────────────────────────────────────────────────


def test_open_position_parses_real_export():
    rows = parse_lending_open_position(fixture("lending_open_position.csv"))
    assert rows, "fixture produced no rows"
    bijr = next(r for r in rows if r["codneg"] == "BIJR39" and r["mercado"] == "Registro")
    assert bijr["trade_date"] == date(2026, 9, 10)
    assert bijr["isin"] == "BRBIJRBDR005"
    assert bijr["tipo_emprestimo"] == "DRE"
    assert bijr["saldo_quantidade"] == Decimal("2737")
    assert bijr["saldo_brl"] == Decimal("261553.11")
    assert bijr["is_total"] is False
    # The published row survives verbatim for provenance.
    assert bijr["raw"]["Código IF"] == "BIJR39"


def test_open_position_flags_b3s_own_total_row():
    """The 'Total' row is B3's sum of the others. Summing both doubles the book."""
    rows = parse_lending_open_position(fixture("lending_open_position.csv"))
    totals = [r for r in rows if r["is_total"]]
    assert totals, "fixture has no Total row — the double-count guard is untested"
    assert all(r["mercado"] == "Total" for r in totals)

    for total in totals:
        parts = [
            r for r in rows
            if not r["is_total"]
            and (r["trade_date"], r["codneg"], r["tipo_emprestimo"])
            == (total["trade_date"], total["codneg"], total["tipo_emprestimo"])
        ]
        assert parts, f"Total row for {total['codneg']} has no per-market rows"
        assert sum(p["saldo_quantidade"] for p in parts) == total["saldo_quantidade"]


def test_open_position_header_discovery_survives_extra_preamble():
    """Header is found by label, not by line number."""
    text = fixture("lending_open_position.csv")
    noisy = "Um aviso novo da B3\nOutra linha qualquer\n\n" + text.lstrip("﻿")
    assert parse_lending_open_position(noisy) == parse_lending_open_position(text)


def test_open_position_raises_when_the_header_is_gone():
    with pytest.raises(B3BdiParseError, match="no header row"):
        parse_lending_open_position("Alguma coisa;outra\n1;2\n")


# ── BTBLoanBalance ────────────────────────────────────────────────────────


def test_loan_balance_reads_rates_from_the_band_row():
    rows = parse_lending_rate(fixture("loan_balance.csv"))
    tris = next(r for r in rows if r["codneg"] == "TRIS3")
    assert tris["trade_date"] == date(2026, 9, 10)
    assert tris["num_contratos"] == 12
    assert tris["quantidade"] == Decimal("20829")
    assert tris["valor_brl"] == Decimal("101645.52")
    assert tris["taxa_doador_media"] == Decimal("0.15")
    assert tris["taxa_tomador_media"] == Decimal("0.15")


def test_loan_balance_raises_when_the_doador_tomador_band_is_missing():
    """Without the band the two identical rate trios cannot be told apart.

    Guessing an order would silently swap lender and borrower rates — a
    plausible-looking wrong number, which is the one thing this repo will not
    ship.
    """
    lines = fixture("loan_balance.csv").splitlines()
    header_i = next(i for i, l in enumerate(lines) if l.startswith("Data;"))
    without_band = "\n".join(lines[:header_i - 1] + lines[header_i:])
    with pytest.raises(B3BdiParseError, match="band"):
        parse_lending_rate(without_band)


def test_loan_balance_raises_when_the_band_sits_over_the_wrong_columns():
    lines = fixture("loan_balance.csv").splitlines()
    header_i = next(i for i, l in enumerate(lines) if l.startswith("Data;"))
    lines[header_i - 1] = "Taxa doador;Taxa tomador;;;;;;;;;;;;"
    with pytest.raises(B3BdiParseError, match="expected"):
        parse_lending_rate("\n".join(lines))


# ── SharesInvesVolum ──────────────────────────────────────────────────────


def test_investor_participation_dates_by_the_caption_not_the_request():
    """B3 publishes T+2: the 2026-09-10 export is captioned 08/09/2026."""
    text = fixture("investor_participation.csv")
    assert mtd_reference_date(text) == date(2026, 9, 8)

    rows = parse_investor_participation(text)
    assert {r["reference_date"] for r in rows} == {date(2026, 9, 8)}
    estrangeiro = next(r for r in rows if r["investor_type"] == "Investidor Estrangeiro")
    assert estrangeiro["compras_brl_mil"] == Decimal("102641915")
    assert estrangeiro["vendas_brl_mil"] == Decimal("96657202")
    assert estrangeiro["vendas_participacao_pct"] == Decimal("29.43")


def test_investor_participation_raises_without_a_caption():
    text = fixture("investor_participation.csv").replace("até o dia", "sem data")
    with pytest.raises(B3BdiParseError, match="caption"):
        parse_investor_participation(text)


# ── SharesInvesVolumMonthly ───────────────────────────────────────────────


def test_monthly_participation_reads_the_market_band():
    rows = parse_investor_participation_monthly(
        fixture("investor_participation_monthly.csv"), request_date=date(2026, 9, 10)
    )
    assert {r["reference_month"] for r in rows} == {date(2026, 8, 1)}
    assert {"À vista", "A termo", "Opções", "Total geral"} <= {r["market"] for r in rows}
    vista = next(
        r for r in rows
        if r["investor_type"] == "Investidor Estrangeiro" and r["market"] == "À vista"
    )
    assert vista["valor_brl"] == Decimal("638327183953")
    assert vista["participacao_pct"] == Decimal("59.00")


def test_monthly_participation_rejects_a_month_that_contradicts_the_request():
    """The caption names a month but never a year. A mismatch must not be filed."""
    text = fixture("investor_participation_monthly.csv")
    with pytest.raises(B3BdiParseError, match="previous month"):
        # Requested in March, so the caption should say Fevereiro, not Agosto.
        monthly_reference_month(text, request_date=date(2026, 3, 10))


def test_monthly_participation_january_rolls_into_december():
    assert monthly_reference_month("(Dezembro)", request_date=date(2026, 1, 8)) == date(2025, 12, 1)


# ── InstrumentsEquities ───────────────────────────────────────────────────


def test_instrument_registry_keeps_only_the_cash_market():
    rows = parse_instrument_registry(
        fixture("instruments_equities.csv"), reference_date=date(2026, 9, 10)
    )
    assert rows
    assert {r["mercado"] for r in rows} == {"EQUITY-CASH"}
    petr = next(r for r in rows if r["instrumento"] == "PETR4")
    assert petr["isin"] == "BRPETRACNPR6"
    assert petr["capital_social"] == Decimal("5446501379")
    assert petr["nivel_governanca"] == "NIVEL 2"
    assert petr["categoria"] == "SHARES"


# ── index portfolio ───────────────────────────────────────────────────────


def test_index_portfolio_parses_free_float_and_sector():
    rows = parse_index_portfolio([{
        "cod": "WEGE3", "asset": "WEG", "type": "ON      NM",
        "segment": "Bens Indls / Máqs e Equips", "part": "2,840",
        "theoricalQty": "1.460.506.056",
        "index_code": "IBOV", "header_date": "16/09/26",
    }])
    assert rows[0]["reference_date"] == date(2026, 9, 16)
    assert rows[0]["theoretical_qty"] == Decimal("1460506056")
    assert rows[0]["b3_sector"] == "Bens Indls / Máqs e Equips"
    assert rows[0]["participacao_pct"] == Decimal("2.840")


# ── the clamp guard ───────────────────────────────────────────────────────


def test_reconcile_span_reports_what_b3_actually_delivered():
    """B3 answers an over-wide range with 200 and a truncated window.

    Verified live: 2024-01-02..2026-09-10 came back 5.2 MB with 18 sessions.
    A 200 is not evidence the span arrived.
    """
    rows = [{"trade_date": date(2026, 9, d)} for d in (8, 9, 10)]
    requested = [date(2026, 9, d) for d in (1, 2, 8, 9, 10)]
    delivered, missing = reconcile_span(rows, "trade_date", requested)
    assert delivered == [date(2026, 9, 8), date(2026, 9, 9), date(2026, 9, 10)]
    assert missing == [date(2026, 9, 1), date(2026, 9, 2)]



# ── the publication-lag guard ─────────────────────────────────────────────


def _span_ingestor(delivered_dates):
    """A B3Ingestor whose BDI span fetch returns exactly `delivered_dates`."""
    from unittest.mock import AsyncMock, MagicMock, patch
    import src.pipeline.b3_pipeline as bp

    with patch.object(bp, "get_pg_client", return_value=MagicMock()):
        ing = bp.B3Ingestor(fetcher=MagicMock(), bdi_fetcher=MagicMock())
    ing._bdi.fetch_table = AsyncMock(return_value="csv")
    ing._log_start = MagicMock()
    ing._log_finish = MagicMock()
    parse = lambda _text: [{"trade_date": d} for d in delivered_dates]
    return ing, parse


def _run_span(ing, parse, targets):
    import asyncio
    return asyncio.run(ing._ingest_bdi_span(
        doc_type="lending_open_position",
        b3_table="BTBLendingOpenPosition",
        parse=parse,
        upsert=lambda _conn, rows: len(rows),
        targets=targets,
        date_field="trade_date",
    ))


def test_a_missing_newest_session_is_ok_when_older_sessions_landed():
    """B3 publishes these tables on their own lags, and the cron runs at 03:03 BRT.

    Verified 2026-09-17 03:36 BRT: BTBTrade had 2026-09-16 (40,021 rows) while
    BTBLendingOpenPosition for the same session did not exist yet. The gap
    calendar always re-requests the newest two sessions, so filing that as an
    error made DB Health red EVERY morning over a gap the next run heals by
    itself. And since rows DID land, the slice is `ok`, not `skipped`:
    `coverage().landed_at` counts only `ok` rows, so `skipped` made our
    pipeline read a day stale over the source's calendar (register item 9).
    The shortfall is still recorded on the audit row as a note.
    """
    targets = [date(2026, 9, 15), date(2026, 9, 16)]
    ing, parse = _span_ingestor([date(2026, 9, 15)])
    _run_span(ing, parse, targets)

    _args, kwargs = ing._log_finish.call_args
    assert not kwargs.get("skipped"), "rows landed: this run succeeded"
    assert not kwargs.get("error"), "a not-yet-published newest session is not an error"
    # The fact must survive: provenance, not silence.
    assert "2026-09-16" in str(kwargs.get("note", ""))


def test_a_span_of_only_the_unpublished_newest_session_is_skipped():
    """Nothing landed, so nothing succeeded: `skipped` keeps landed_at honest."""
    targets = [date(2026, 9, 16)]
    ing, parse = _span_ingestor([])
    _run_span(ing, parse, targets)

    _args, kwargs = ing._log_finish.call_args
    assert kwargs.get("skipped") is True
    assert "2026-09-16" in " ".join(str(a) for a in _args)


def test_log_finish_writes_a_note_on_an_ok_row():
    """`note` lands in error_msg while the status stays `ok`."""
    from unittest.mock import MagicMock, patch
    import src.pipeline.b3_pipeline as bp

    with patch.object(bp, "get_pg_client", return_value=MagicMock()):
        ing = bp.B3Ingestor(fetcher=MagicMock(), bdi_fetcher=MagicMock())
    with patch.object(bp.ingest_log, "finish") as finish:
        ing._log_finish("r1", 5, note="missing 2026-09-16")
    kwargs = finish.call_args.kwargs
    assert kwargs["status"] == "ok"
    assert kwargs["error"] == "missing 2026-09-16"


def test_a_missing_older_session_is_still_an_error():
    """The silent-clamp guard must not be weakened by the lag allowance.

    An older session has had a full publication cycle. If it is absent, B3
    truncated the window or the series has a real hole — and for these tables
    a hole never fills in, so it has to stay loud.
    """
    targets = [date(2026, 9, 11), date(2026, 9, 15), date(2026, 9, 16)]
    ing, parse = _span_ingestor([date(2026, 9, 15), date(2026, 9, 16)])
    _run_span(ing, parse, targets)

    _args, kwargs = ing._log_finish.call_args
    assert not kwargs.get("skipped"), "an older missing session is a real shortfall"
    assert "2026-09-11" in str(kwargs.get("error", ""))


def test_newest_plus_older_missing_is_an_error():
    """A shortfall is only forgiven when it is EXACTLY the newest session.

    If the newest is missing AND something older is too, the older one decides:
    that is a truncated window, not a publication lag.
    """
    targets = [date(2026, 9, 11), date(2026, 9, 15), date(2026, 9, 16)]
    ing, parse = _span_ingestor([date(2026, 9, 15)])
    _run_span(ing, parse, targets)

    _args, kwargs = ing._log_finish.call_args
    assert not kwargs.get("skipped")
    assert "2026-09-11" in str(kwargs.get("error", ""))


def test_a_complete_span_is_plain_ok():
    targets = [date(2026, 9, 15), date(2026, 9, 16)]
    ing, parse = _span_ingestor(targets)
    _run_span(ing, parse, targets)

    _args, kwargs = ing._log_finish.call_args
    assert not kwargs.get("skipped")
    assert not kwargs.get("error")

# ── fetcher ───────────────────────────────────────────────────────────────


def _response(status: int, text: str) -> httpx.Response:
    return httpx.Response(
        status, text=text, request=httpx.Request("POST", "https://arquivos.b3.com.br/x")
    )


@pytest.mark.asyncio
async def test_fetch_table_sends_filters_as_an_object():
    """A list makes the endpoint return HTTP 400 — it wants a dictionary."""
    import json

    captured = {}

    async def fake_post(url, content=None, **kw):
        captured["url"] = url
        captured["body"] = json.loads(content)
        return _response(200, "Data;Código IF\n10/09/2026;PETR4\n")

    with patch("httpx.AsyncClient.post", new=AsyncMock(side_effect=fake_post)):
        await B3BdiFetcher().fetch_table("BTBLendingOpenPosition", date(2026, 9, 10))

    assert captured["body"]["Filters"] == {}
    assert captured["body"]["Name"] == "BTBLendingOpenPosition"
    assert captured["body"]["Date"] == captured["body"]["FinalDate"] == "2026-09-10"


@pytest.mark.asyncio
async def test_fetch_table_raises_b3bdiempty_for_nenhum_resultado():
    """Outside retention is a skip, not a failure — and never an empty ingest."""
    body = "Data;Código IF;Mercado\nNenhum resultado\n"
    with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=_response(200, body))):
        with pytest.raises(B3BdiEmpty):
            await B3BdiFetcher(max_retries=1).fetch_table("BTBLoanBalance", date(2020, 1, 2))


@pytest.mark.asyncio
async def test_fetch_table_retries_cloudflare_403_then_raises():
    """403 here is a throttle, not authorization. It must never look like no data."""
    challenge = _response(403, "<!DOCTYPE html><html><title>Attention Required!</title>")
    post = AsyncMock(return_value=challenge)
    with patch("httpx.AsyncClient.post", new=post):
        with pytest.raises(B3BdiFetchError):
            await B3BdiFetcher(max_retries=3, retry_delay=0).fetch_table(
                "BTBTrade", date(2026, 9, 10)
            )
    assert post.await_count == 3


@pytest.mark.asyncio
async def test_fetch_table_retries_499_then_succeeds():
    """B3's edge reports the same stalled BTBTrade request as 499 or 504.

    Observed in production 2026-09-16: 504, 504, then 499 on the same URL
    within minutes. 504 was retried and 499 was not, so 3 of 5 BTBTrade
    sessions failed on a table B3 keeps for 21 business days. A closed
    connection is not a statement about the data.
    """
    ok = _response(200, "Data;Código IF\n15/09/2026;PETR4\n")
    post = AsyncMock(side_effect=[_response(504, ""), _response(499, ""), ok])
    with patch("httpx.AsyncClient.post", new=post):
        text = await B3BdiFetcher(max_retries=4, retry_delay=0).fetch_table(
            "BTBTrade", date(2026, 9, 15)
        )
    assert "PETR4" in text
    assert post.await_count == 3


@pytest.mark.asyncio
async def test_fetch_table_retries_an_html_body_served_with_200():
    ok = _response(200, "Data;Código IF\n10/09/2026;PETR4\n")
    post = AsyncMock(side_effect=[_response(200, "<!DOCTYPE html><html>nope</html>"), ok])
    with patch("httpx.AsyncClient.post", new=post):
        text = await B3BdiFetcher(max_retries=3, retry_delay=0).fetch_table(
            "BTBLoanBalance", date(2026, 9, 10)
        )
    assert "PETR4" in text
    assert post.await_count == 2


@pytest.mark.asyncio
async def test_fetch_table_rejects_a_backwards_range():
    with pytest.raises(ValueError):
        await B3BdiFetcher().fetch_table("X", date(2026, 9, 10), date(2026, 9, 1))


# ── the gap calendar ──────────────────────────────────────────────────────


def _conn(rows_by_query):
    """A psycopg2-shaped connection whose cursor replays canned result sets."""
    calls = {"n": 0}
    cur = MagicMock()
    cur.__enter__ = MagicMock(return_value=cur)
    cur.__exit__ = MagicMock(return_value=False)

    def execute(sql, params=None):
        calls["n"] += 1
        cur._rows = rows_by_query[calls["n"] - 1]

    cur.execute = MagicMock(side_effect=execute)
    cur.fetchall = MagicMock(side_effect=lambda: cur._rows)
    conn = MagicMock()
    conn.cursor = MagicMock(return_value=cur)
    return conn


def test_sessions_to_fetch_returns_only_missing_plus_the_fresh_tail():
    sessions = [(date(2026, 9, d),) for d in (1, 2, 3, 4, 8, 9, 10)]
    have = [(date(2026, 9, d),) for d in (1, 2, 4, 8, 9, 10)]
    targets = lending.sessions_to_fetch(
        _conn([sessions, have]), "b3_lending_open_position", "trade_date"
    )
    # 09-03 is the hole; 09-09 and 09-10 are the always-refresh tail.
    assert targets == [date(2026, 9, 3), date(2026, 9, 9), date(2026, 9, 10)]


def test_sessions_to_fetch_never_invents_a_holiday():
    """Candidates come from sessions the tape proves happened, not from weekdays."""
    sessions = [(date(2026, 9, d),) for d in (8, 9, 10)]   # 09-07 is a holiday
    have = [(date(2026, 9, d),) for d in (8, 9, 10)]
    targets = lending.sessions_to_fetch(
        _conn([sessions, have]), "b3_lending_open_position", "trade_date"
    )
    assert date(2026, 9, 7) not in targets


def test_sessions_to_fetch_is_capped_per_run():
    many = [(date(2026, 1, 1) + __import__("datetime").timedelta(days=i),) for i in range(60)]
    targets = lending.sessions_to_fetch(
        _conn([many, []]), "b3_lending_open_position", "trade_date", limit=60
    )
    assert len(targets) == lending.MAX_REQUESTS_PER_RUN
    # The newest survive: the oldest are about to age out of B3 anyway.
    assert targets[-1] == many[-1][0]


def test_investor_request_dates_apply_the_t_plus_two_lag():
    sessions = [date(2026, 9, d) for d in (1, 2, 3, 4, 8, 9, 10)]
    missing = [date(2026, 9, 2), date(2026, 9, 10)]
    requests = lending.investor_request_dates(sessions, missing)
    # 09-02 is delivered two sessions later, on 09-04. 09-10 is the newest
    # session, so nothing can deliver it yet — it is left for a later run.
    assert requests == [date(2026, 9, 4)]


# ── BTBTrade (individual lending trades) ──────────────────────────────────


def test_lending_trade_parses_real_export():
    from src.parsers.b3_bdi import parse_lending_trade

    rows = parse_lending_trade(fixture("lending_trade.csv"))
    assert rows
    natu = next(r for r in rows if r["codneg"] == "NATU3")
    assert natu["trade_date"] == date(2026, 9, 10)
    assert natu["numero_negocio"] == 113392202
    assert natu["quantidade"] == Decimal("497549")
    assert natu["taxa_pct"] == Decimal("40.00")     # percentage points, not 0.40
    assert natu["mercado"] == "Balcão"
    assert natu["hora"] == "19:14:32"


def test_lending_trade_reads_participants_from_the_band_row():
    """The header says `Código` twice; only the band distinguishes the legs.

    Swapping doador and tomador would invert every flow this table exists to
    show, so this pins the mapping against a trade whose two legs differ.
    """
    from src.parsers.b3_bdi import parse_lending_trade

    rows = parse_lending_trade(fixture("lending_trade.csv"))
    smft = next(r for r in rows if r["codneg"] == "SMFT3")
    assert smft["doador_codigo"] == "39"
    assert smft["doador_nome"].startswith("AGORA")
    assert smft["tomador_codigo"] == "3"
    assert smft["tomador_nome"].startswith("XP")


def test_lending_trade_raises_without_the_participant_band():
    from src.parsers.b3_bdi import parse_lending_trade

    lines = fixture("lending_trade.csv").splitlines()
    header_i = next(i for i, l in enumerate(lines) if l.startswith("Código IF;"))
    with pytest.raises(B3BdiParseError, match="band"):
        parse_lending_trade("\n".join(lines[:header_i - 1] + lines[header_i:]))


def test_lending_trade_key_is_unique_within_a_session():
    """`Número do negócio` keys the row with its date — 0 duplicates in 43,165
    rows on 2026-09-10. If that ever stopped holding, rows would silently
    overwrite each other on upsert."""
    from src.parsers.b3_bdi import CONFLICT_LENDING_TRADE, parse_lending_trade

    rows = parse_lending_trade(fixture("lending_trade.csv"))
    keys = {tuple(r[c] for c in CONFLICT_LENDING_TRADE) for r in rows}
    assert len(keys) == len(rows)
    assert CONFLICT_LENDING_TRADE == ("trade_date", "numero_negocio")


def test_lending_trade_stores_no_raw_but_warns_on_an_unmapped_column(caplog):
    """This table has no `raw` column, so a new B3 column must not vanish.

    Detection replaces storage: the parser names the unmapped label loudly and
    still returns the rows, because losing a session that can never be
    re-fetched is worse than temporarily not storing one field.
    """
    from src.parsers.b3_bdi import parse_lending_trade

    rows = parse_lending_trade(fixture("lending_trade.csv"))
    assert "raw" not in rows[0]

    lines = fixture("lending_trade.csv").splitlines()
    hi = next(i for i, l in enumerate(lines) if l.startswith("Código IF;"))
    lines[hi - 1] += ";"
    lines[hi] += ";Novo Campo B3"
    lines[hi + 1:] = [l + ";valor" for l in lines[hi + 1:] if l.strip()]

    with caplog.at_level("WARNING"):
        drifted = parse_lending_trade("\n".join(lines), origin="drift")
    assert len(drifted) == len(rows)
    assert "Novo Campo B3" in caplog.text


def test_trade_sessions_are_capped_harder_than_the_other_tables():
    """BTBTrade is ~43k rows / 5.9 MB per session and cannot be range-fetched.

    A cold start against the full 21-session window would be ~124 MB in one
    run, so it claims the newest sessions first and walks back over later runs.
    """
    assert lending.MAX_TRADE_SESSIONS_PER_RUN < lending.MAX_REQUESTS_PER_RUN
    assert lending.MAX_TRADE_SESSIONS_PER_RUN <= 5
