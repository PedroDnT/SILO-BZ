"""ETFs carry a fee (owner, 2026-10-03; catalog v56, engine 1.5).

Measured on production 2026-10-03: CVM's Extrato, lâmina and cad_fi hold no administration fee for any of the 178
active ETFs in cvm_etf_registry (whose own taxa_adm is 0 of 187), and api.lookup returns no CNPJ for a ticker, so
before 1.5 an ETF bought by ticker never reached the fee section. Now portfolio_resolve maps the ticker to the ETF's
CNPJ (match_kind etf_ticker) and portfolio_fees serves the fee etfsbrasil.com.br prints (etf_site_*), a third-party
value with its date, summed apart from the CVM-disclosed fees.

Offline: the demo statement plus three lines typed ``outro`` with a ticker, as the BTG PDF reader writes them:
BOVA11 (0.10, in lookup), B5P211 (0.20, a fixed income ETF that lookup does not find because it is not in COTAHIST)
and POSB11 (0.0 on the site: shown, to check, never summed); and one spreadsheet line typed ``ETF`` and named by its
bare ticker, IVVB11 (0.23), which the first portfolio_resolve call already matches. The ETF rows are canned in the
shape of the v56 columns; every number in the assertions comes from them.

Engine 1.6 (catalog v57, owner, 2026-10-03): the same snapshot's cotistas and PL. The canned values are the ones
etf_market_snapshot held on production for the 2026-10-03 snapshot (read 2026-10-03): BOVA11 106,027 cotistas and
R$ 15,323,200,000; B5P211 43,321 and R$ 4,334,310,000; IVVB11 241,779 and R$ 7,776,690,000; POSB11 7,170 and
R$ 590,800,000. They are descriptive: never summed, never a fee base.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import re
from decimal import Decimal
from pathlib import Path

import pytest

from src.portfolio.client import FakeClient, load_fake_rows
from src.portfolio.common import is_ticker
from src.portfolio.diagnose import FAKE_CLOCK
from src.portfolio.engine import default_params, run_engine
from src.portfolio.fees import ETF_FACTS_LABEL, ETF_SITE_LABEL, ZERO_LABEL, _etf_site
from src.portfolio.report import adapt, build
from src.portfolio.statement import read_statement

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "docs" / "reference" / "portfolio" / "statement-template.xlsx"
FAKE_ROWS = ROOT / "tests" / "fixtures" / "portfolio" / "fake_silo_rows.json"

ETFS = {  # ticker: (CNPJ, registry name, site fee, value on the statement)
    "BOVA11": ("10406511000161", "ISHARES IBOVESPA CLASSE DE ÍNDICE - RESPONSABILIDADE LIMITADA", 0.10, Decimal("100000.00")),
    "B5P211": ("38354864000184", "IT NOW IMA-B5 P2 FUNDO DE INDICE RESPONSABILIDADE LIMITADA", 0.20, Decimal("50000.00")),
    "POSB11": ("65180394000152", "POSB11 ETF (fee 0 on the site, 2026-10-03)", 0.0, Decimal("30000.00")),
}
NAMED = {  # a line typed ETF and named by its bare ticker (the spreadsheet template invites it)
    "IVVB11": ("19909560000191", "ISHARES S&P 500 CLASSE DE ÍNDICE EM COTAS DE CLASSES DE ÍNDICE IE - RESPONSABILIDADE LIMITADA",
               0.23, Decimal("80000.00")),
}
ALL = {**ETFS, **NAMED}
SNAPSHOT = "2026-10-03"
FACTS = {  # ticker: (cotistas, PL in R$), etf_market_snapshot on production, snapshot 2026-10-03
    "BOVA11": (106027, 15323200000), "B5P211": (43321, 4334310000), "IVVB11": (241779, 7776690000), "POSB11": (7170, 590800000),
}


def _etf_resolve_row(line_no: int, t: str) -> dict:
    return {"line_no": line_no, "input_name": t, "candidate_cnpj": ALL[t][0], "candidate_name": ALL[t][1],
            "matched_name": ALL[t][1], "matched_period": None, "entity_type": "fii", "match_kind": "etf_ticker",
            "similarity": 1.0, "rank": 1, "quota_on_date": None, "quota_rel_diff": None, "ambiguous": False,
            "reason": "the name is the ticker of an ETF in SILO's curated ETF registry (cvm_etf_registry, ticker to CNPJ)"}


def _fee_row(ticker: str, facts: bool = True) -> dict:
    cnpj, name, fee, _ = ALL[ticker]
    cot, pl = FACTS[ticker] if facts else (None, None)
    return {
        "cnpj": cnpj, "fund_name": name, "month": None, "nav": None, "adm_fee_flow": None, "adm_fee_pct_annual_est": None,
        "perf_fee_flow": None, "perf_fee_pct_annual_est": None, "fiscal_reset_suspect": False,
        "disclosed_taxa_adm": None, "disclosed_taxa_adm_min": None, "disclosed_taxa_adm_max": None,
        "disclosed_taxa_perfm": None, "disclosed_taxa_adm_info": None, "disclosed_taxa_perfm_info": None,
        "disclosed_source": None, "disclosed_as_of": None, "disclosed_age_months": None, "disclosed_n_classes": None,
        "disclosed_note": "no disclosed fee in the Extrato, the lâmina or cad_fi: NULL is not a zero fee",
        "estimate_label": "no estimate: no balancete filed", "disclosed_origin": None, "disclosed_age_days": None,
        "filed_zero": False, "implausible_filed": False, "taxa_adm_filed_raw": None, "fee_resolution": None,
        "lamina_as_of": None, "lamina_pr_pl_despesa": None, "extrato_taxa_adm_filed": None, "extrato_scale_factor": None,
        "etf_ticker": ticker, "etf_site_taxa_adm": fee, "etf_site_as_of": SNAPSHOT, "etf_site_source": "etfsbrasil",
        "etf_site_note": f"ETF {ticker}: 'Taxa de administração total' as printed on etfsbrasil.com.br on {SNAPSHOT}, "
                         "a third-party site, not a CVM filing",
        "etf_site_nr_cotistas": cot, "etf_site_pl": pl,  # v57, the same snapshot
    }


class EtfClient(FakeClient):
    """The canned rows, plus the ETF rows: portfolio_fees answers the ETF CNPJs and passes the rest through."""

    facts = True

    def _request(self, tool: str, args: dict) -> list[dict]:
        if tool == "portfolio_fees":
            by_cnpj = {v[0]: k for k, v in ALL.items()}
            etf = [c for c in args["p_cnpjs"] if c in by_cnpj]
            rest = [c for c in args["p_cnpjs"] if c not in by_cnpj]
            rows = super()._request(tool, {**args, "p_cnpjs": rest}) if rest else []
            return rows + [_fee_row(by_cnpj[c], self.facts) for c in etf]
        return super()._request(tool, args)


def _canned() -> dict:
    canned = load_fake_rows(FAKE_ROWS)
    canned["lookup"] = [
        {"match": {"p_query": "BOVA11"}, "rows": [{"id": "BOVA11", "id_type": "ticker", "asset_class": "fund_quota",
                                                     "name": "ISHARES BOVACI", "isin": "BRBOVACTF003", "cnpj": None}]},
        {"match": {"p_query": "B5P211"}, "rows": []},  # a fixed income ETF: not in COTAHIST, so not in api.quotes
        {"match": {"p_query": "POSB11"}, "rows": [{"id": "POSB11", "id_type": "ticker", "asset_class": "fund_quota",
                                                     "name": "POSB11 CI", "isin": None, "cnpj": None}]},
        {"match": {"p_query": "IVVB11"}, "rows": [{"id": "IVVB11", "id_type": "ticker", "asset_class": "fund_quota",
                                                     "name": "ISHARES SP500CI", "isin": "BRIVVBCTF007", "cnpj": None}]},
        *canned["lookup"],
    ]
    canned["quote_latest"] = [{"match": {"p_ticker": t}, "rows": []} for t in ("BOVA11", "POSB11", "IVVB11")] + canned["quote_latest"]
    # the demo's fund lines plus IVVB11 in the first call; the three outro tickers in the ETF probe
    first = canned["portfolio_resolve"][0]
    names = [*first["match"]["p_names"], "IVVB11"]
    canned["portfolio_resolve"] = [
        {"match": {"p_names": list(ETFS)}, "rows": [_etf_resolve_row(i, t) for i, t in enumerate(ETFS, start=1)]},
        {"match": {"p_names": names}, "rows": [*first["rows"], _etf_resolve_row(len(names), "IVVB11")]},
        *canned["portfolio_resolve"],
    ]
    return canned


def _statement():
    stmt = read_statement(TEMPLATE)
    base = stmt.positions[-1]
    extra = tuple(
        dataclasses.replace(base, line_no=base.line_no + i, source_row=base.source_row + i, linha_extrato=t,
                            tipo="ETF" if t in NAMED else "outro", codigo=t, quantidade=None, preco_unitario=None, valor=v[3])
        for i, (t, v) in enumerate(ALL.items(), start=1)
    )
    added = sum(v[3] for v in ALL.values())
    return dataclasses.replace(stmt, positions=stmt.positions + extra, sum_of_lines=stmt.sum_of_lines + added,
                               stated_total=stmt.stated_total + added)


def _run(facts: bool = True) -> dict:
    stmt = _statement()
    client = EtfClient(_canned(), clock=lambda: FAKE_CLOCK)
    client.facts = facts
    return run_engine(stmt, client, default_params(stmt.position_date), clock=lambda: FAKE_CLOCK)


@pytest.fixture(scope="module")
def doc() -> dict:
    return _run()


def _fee_line(doc: dict, ticker: str) -> dict:
    return next(ln for ln in doc["fees"]["lines"] if ln["cnpj"] == ALL[ticker][0])


def test_etf_tickers_with_a_digit_in_the_root_are_tickers():
    for t in ("B5P211", "5PRE11", "TD3511", "B3SA3", "BOVA11", "PETR4"):
        assert is_ticker(t), t
    for not_t in ("123456", "32113885000121", "NTN-B 2035-05-15"):
        assert not is_ticker(not_t), not_t


def test_an_etf_bought_by_ticker_gets_its_cnpj_for_the_fee_only(doc):
    by_no = {ln["codigo"]: ln for ln in doc["identification"]["lines"]}
    for t in ALL:
        ln = by_no[t]
        assert ln["status"] == "identified" and ln["identity"]["kind"] == "ticker"  # still a ticker for look-through
        assert ln["identity"]["etf_cnpj"] == ALL[t][0]
        assert ln["etf_match"]["match_kind"] == "etf_ticker" and ln["etf_match"]["cnpj"] == ALL[t][0]
        assert ln["identity"]["cnpj"] is None  # no fund CNPJ: movement, restatements and signals do not see it
    # the line typed ETF and named by its ticker never becomes a fund: an ETF files no CDA (none in 2026, measured
    # 2026-10-03), so look-through, movement and restatements must not open it
    line_no = by_no["IVVB11"]["line_no"]
    assert all(lt["line_no"] != line_no or lt.get("status") != "complete" for lt in doc["look_through"]["lines"])
    assert line_no not in {m.get("line_no") for m in doc["movement"].get("lines") or []}
    assert line_no not in {r.get("line_no") for r in doc["restatements"].get("lines") or []}
    # lookup does not know the fixed income ETF; the ETF registry does
    assert "lookup não o encontrou" in by_no["B5P211"]["reason"]


def test_an_etf_carries_the_sites_fee_with_origin_and_date_and_enters_its_own_sum(doc):
    for t in ("BOVA11", "B5P211", "IVVB11"):
        ln = _fee_line(doc, t)
        h = ln["headline"]
        fee, value = ALL[t][2], float(ALL[t][3])
        assert ln["fee_status"] == ETF_SITE_LABEL and ln["needs_manual_check"] is False
        assert h["kind"] == "etf_site" and h["origin"] == "etf_site" and h["as_of"] == SNAPSHOT and h["ticker"] == t
        assert h["rate_pct_year"] == fee and h["counted_as_cost"] is True
        assert h["per_year_brl"] == round(value * fee / 100, 2) == {"IVVB11": 184.0}.get(t, 100.0)
        assert ln["disclosed"] is None  # never a CVM-disclosed fee
        assert ln["etf_site"]["used_as_fee"] is True and ln["etf_site"]["source"] == "etfsbrasil"
    t = doc["fees"]["totals"]
    assert t["adm_etf_site_per_year_brl"] == 384.0
    assert t["adm_fee_per_year_brl"] == pytest.approx(t["adm_disclosed_fixed_per_year_brl"] + 384.0, abs=0.01)
    assert t["fund_value_with_etf_site_fee_brl"] == 230000.0
    total = float(_statement().sum_of_lines)
    assert t["adm_etf_site_portfolio_pct"] == round(384.0 / total * 100, 4)


def test_a_zero_on_the_site_is_shown_to_check_and_never_summed(doc):
    ln = _fee_line(doc, "POSB11")
    h = ln["headline"]
    assert ln["fee_status"] == ZERO_LABEL and ln["needs_manual_check"] is True
    assert h["kind"] == "etf_site" and h["counted_as_cost"] is False and h["rate_pct_year"] is None
    assert h["filed_pct_year"] == 0.0 and h["per_year_brl"] is None
    t = doc["fees"]["totals"]
    assert t["fund_value_with_etf_site_fee_to_check_brl"] == 30000.0
    assert t["adm_etf_site_per_year_brl"] == 384.0  # BOVA11, B5P211 and IVVB11 only
    assert t["fund_value_brl"] == pytest.approx(sum(x["position_value_brl"] for x in doc["fees"]["lines"]))


def test_the_report_says_the_fee_is_from_a_third_party_site(doc):
    view = adapt.to_view(doc)
    bl = next(b for b in view["fees"]["by_line"] if b["cnpj"] == ETFS["BOVA11"][0])
    assert bl["disclosed_pct_year"] == 0.1 and bl["disclosed_brl_year"] == 100.0
    assert bl["disclosed_origin_label"] == "site etfsbrasil.com.br (terceiros)" and bl["disclosed_as_of"] == SNAPSHOT
    assert view["fees"]["total_etf_site_brl_year"] == 384.0
    html_text, narrative = build.build(view, "fake")
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html_text))
    assert "etfsbrasil.com.br (fonte de terceiros, não documento da CVM), somadas à parte: R$ 384,00 por ano" in text
    assert "0,10% a.a." in text and "03/10/2026" in text
    # its own source with the snapshot date, never credited to the CVM
    assert view["data_dates"]["ETFSBRASIL"] == SNAPSHOT
    assert "etfsbrasil.com.br (site de terceiros: taxa, cotistas e PL dos ETFs, não é documento da CVM): dados até 03/10/2026" in text
    kept = [f for f in narrative.kept if f.section == "taxas"]
    assert any("etf_site_label" in f.text for f in kept)
    # the summary says it too ("importante ressaltar que ETFs também têm taxa")
    assert any(f.section == "resumo" and "total_etf_site_brl_year" in f.text for f in narrative.kept)
    for f in kept:
        assert not re.search(r"\d", re.sub(r"\{\{[^}]+\}\}", "", f.text))  # every number is a placeholder


# --- engine 1.6 (catalog v57): the ETF's cotistas and PL from the same snapshot -------------------------


def test_every_etf_line_carries_the_sites_cotistas_and_pl_with_the_fees_date(doc):
    for t, (cot, pl) in FACTS.items():
        es = _fee_line(doc, t)["etf_site"]
        assert es["nr_cotistas"] == cot and isinstance(es["nr_cotistas"], int)  # a count, printed without decimals
        assert es["pl_brl"] == float(pl)  # as stored, never rescaled
        assert es["as_of"] == SNAPSHOT and es["facts_label"] == ETF_FACTS_LABEL
        assert "nunca somados" in es["facts_note"]


def test_cotistas_and_pl_never_enter_a_total_or_a_fee():
    with_facts, without = _run(True), _run(False)
    assert with_facts["fees"]["totals"] == without["fees"]["totals"]
    for t in FACTS:
        a, b = _fee_line(with_facts, t), _fee_line(without, t)
        assert a["headline"] == b["headline"] and a["estimate"] == b["estimate"]
        assert a["fund_nav_brl"] == b["fund_nav_brl"]  # the site's PL is never the NAV the estimate divides by
        assert a["position_value_brl"] == b["position_value_brl"]
    assert with_facts["statement"] == without["statement"]
    assert with_facts["look_through"] == without["look_through"]
    # and the facts are absent when the row carries none: null, never zero
    es = _fee_line(without, "BOVA11")["etf_site"]
    assert es["nr_cotistas"] is None and es["pl_brl"] is None


def test_a_row_without_a_snapshot_has_no_facts_and_the_report_prints_none():
    row = {"etf_ticker": "YDRO11", "etf_site_taxa_adm": None, "etf_site_as_of": None, "etf_site_source": None,
           "etf_site_note": "no etfsbrasil.com.br snapshot with a fee for this ticker; NULL is not a zero fee",
           "etf_site_nr_cotistas": None, "etf_site_pl": None}
    es = _etf_site(row, {"tool": "portfolio_fees", "call_id": 1})
    assert es["nr_cotistas"] is None and es["pl_brl"] is None
    view = adapt._fee_line_view(9, {"cnpj": "1", "etf_site": es}, {})
    assert view["etf_facts_label"] is None and view["etf_site_as_of"] is None
    from src.portfolio.report.render import _etf_facts_html
    assert _etf_facts_html({"x": view}, "x", view) == ""
    # a non-integral count is not a count: None, never rounded into one
    assert _etf_site({**row, "etf_site_nr_cotistas": "12.5"}, {})["nr_cotistas"] is None


def test_the_report_shows_cotistas_and_pl_with_source_and_date(doc):
    view = adapt.to_view(doc)
    by_cnpj = {b["cnpj"]: b for b in view["fees"]["by_line"]}
    bl = by_cnpj[ETFS["BOVA11"][0]]
    assert bl["etf_site_nr_cotistas"] == 106027 and bl["etf_site_pl_brl"] == 15323200000.0
    assert bl["etf_site_as_of"] == SNAPSHOT and bl["etf_facts_label"] == ETF_FACTS_LABEL
    # the POSB11 fee is to check (0 on the site), but its cotistas and PL still show
    posb = by_cnpj[ETFS["POSB11"][0]]
    assert posb["etf_site_check_label"] and posb["etf_site_nr_cotistas"] == 7170
    html_text, narrative = build.build(view, "fake")
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html_text))
    assert "Cotistas: 106.027 ; PL: R$ 15,32 bilhões (etfsbrasil.com.br, site de terceiro, coleta de 03/10/2026)" in text
    assert "Cotistas: 7.170 ; PL: R$ 590,8 milhões (etfsbrasil.com.br, site de terceiro, coleta de 03/10/2026)" in text
    kept = [f for f in narrative.kept if f.section == "taxas" and "etf_site_nr_cotistas" in f.text]
    assert len(kept) == len(FACTS)
    for f in kept:
        assert "etf_site_pl_brl" in f.text and "etf_facts_label" in f.text and "etf_site_as_of" in f.text
        assert not re.search(r"\d", re.sub(r"\{\{[^}]+\}\}", "", f.text))  # every number is a placeholder
    # the totals the report prints are the ones without the facts
    assert view["fees"]["total_etf_site_brl_year"] == 384.0
