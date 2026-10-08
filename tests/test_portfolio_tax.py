"""Block 17 (engine 1.11): fee paid and tax per position, offline. One test per rule of the owner's resolution of #613.

Synthetic positions only: no real statement is read.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import shutil
import unicodedata
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from src.portfolio.common import REASON_TEXT
from src.portfolio.report import adapt
from src.portfolio.report import labels as reader_text
from src.portfolio.identify import LineId
from src.portfolio.statement import Position, StatementTotalMismatch, parse_rows
from src.portfolio.tax import (
    DATE_MISSING_TEXT,
    RULES_DIR,
    compute_tax,
    in_force,
    load_rules,
    pct_text,
)

ROOT = Path(__file__).resolve().parents[1]
NOTE = ROOT / "docs" / "reference" / "research" / "tax-rules-by-instrument.md"
FIXTURE = ROOT / "tests" / "fixtures" / "portfolio" / "demo_engine_output.json"
D = dt.date(2026, 9, 30)
FORBIDDEN = ("venda", "vendas", "vende", "vender", "venderia", "troque", "trocar", "troca", "troquem", "escolha",
             "escolher", "escolhe", "escolham")
INSTRUMENT_FILES = {"cdb", "lci", "lca", "cri", "cra", "debenture", "debenture_incentivized", "fii", "shares",
                    "etf_equity", "etf_fixed_income", "fund_long", "fund_short", "fund_equity", "pension_regressive",
                    "pension_progressive"}


def pos(n=1, tipo="CDB", valor="100000", aplicacao=None, vencimento=None, taxa=None, estrategia=None, classe=None,
        nome=None):
    return Position(line_no=n, source_row=n, linha_extrato=nome or f"Linha {n}", tipo=tipo, codigo=None,
                    quantidade=None, preco_unitario=None, valor=Decimal(valor), data_posicao=D,
                    vencimento=vencimento, taxa_texto=taxa, estrategia_corretora=estrategia, classe_corretora=classe,
                    data_aplicacao=aplicacao)


def headline_fee(n, per_year=1000.0, rate=1.0, kind="fixa", classe=None, **extra):
    h = {"kind": kind, "rate_pct_year": rate, "per_year_brl": per_year,
         "sources": [{"tool": "portfolio_fees", "call_id": 1, "args": {}, "data_date": "2026-08-31"}], **extra}
    return {"line_no": n, "fee_status": "divulgada", "headline": h,
            "disclosed": {"terms_as_filed": {"classe_anbima": classe}} if classe else {}}


def ret_12m(n, r_pct, base_date="2025-09-30", basis="cota_fundo"):
    return {"line_no": n, "basis": basis,
            "windows": {"12m": {"status": "avaliado", "net_return_pct": r_pct, "base_date": base_date}},
            "sources": [{"tool": "statement", "call_id": None, "args": {"line_no": n}, "data_date": "2026-09-30"}]}


def run(positions, fee_lines=(), ret_lines=(), ident=None):
    lines = [LineId(p, **((ident or {}).get(p.line_no) or {})) for p in positions]
    return compute_tax(lines, {"lines": list(fee_lines)}, {"lines": list(ret_lines)}, D)


def one(p, **kw):
    return run([p], **kw)["lines"][0]


def strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for v in node.values():
            yield from strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from strings(v)


def words(s):
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)).lower()
    return set(re.findall(r"[a-z]+", s))


def norm(s):
    return re.sub(r"\s+", " ", s.replace("**", "").replace("`", "")).strip()


# ---------------------------------------------------------------------------
# The rule files.
# ---------------------------------------------------------------------------


def test_one_file_per_instrument_plus_iof_and_person_and_no_tesouro():
    rules = load_rules()
    assert set(rules) == INSTRUMENT_FILES | {"iof", "person"}
    assert not any("tesouro" in n for n in rules)  # the #611 note does not cover Tesouro Direto


def test_every_quote_and_url_is_in_the_611_note():
    note = NOTE.read_text(encoding="utf-8")
    n = norm(note)
    for rf in load_rules().values():
        for s in rf.data["sources"]:
            assert norm(s["quote"]) in n, f"{rf.name}/{s['id']}: quote not in the #611 note"
            assert s["url"] in note, f"{rf.name}/{s['id']}: URL not in the #611 note"
        assert rf.data["engine_cannot_observe"] is not None and "valid_from" in rf.data


WORD_FORMS = {"20%": "vinte por cento", "15%": "quinze por cento", "10%": "dez por cento", "30%": "trinta por cento",
              "0%": "zero por cento", "5%": "cinco por cento"}


def _rates_with_source(node, out):
    if isinstance(node, dict):
        src = node.get("source")
        rate = node.get("rate")
        if isinstance(rate, dict):
            # an exempt event's 0 is "isento" in the law's words, not a printed rate: its quote is checked above
            _rates_with_source({**rate, "source": rate.get("source", src), "exempt": node.get("exempt")}, out)
        elif isinstance(rate, (int, float)) and src and not node.get("exempt"):
            out.append((rate, src))
        for row in node.get("rows") or []:
            out.append((row["rate"], src))
        for key, val in node.items():
            if key.endswith("_rate") and isinstance(val, (int, float)) and not isinstance(val, bool):
                out.append((val, node.get(key.replace("_rate", "_source")) or src))
            elif key not in ("rate", "rows") and isinstance(val, (dict, list)):
                _rates_with_source(val, out)
    elif isinstance(node, list):
        for v in node:
            _rates_with_source(v, out)


def test_every_rate_in_the_yaml_is_in_the_quote_it_cites():
    checked = 0
    for rf in load_rules().values():
        quotes = {s["id"]: s["quote"] for s in rf.data["sources"]}
        found: list = []
        _rates_with_source({k: v for k, v in rf.data.items() if k != "sources"}, found)
        for rate, sid in found:
            txt = pct_text(rate)
            q = quotes[sid]
            assert txt in q or WORD_FORMS.get(txt, "\0") in q, f"{rf.name}: {txt} not in quote {sid}"
            checked += 1
    assert checked >= 30


def test_rules_files_record_sha256_like_indexer_rules():
    out = run([pos()])
    by = {r["instrument"]: r for r in out["rules_files"]}
    for name in INSTRUMENT_FILES | {"iof", "person"}:
        path = RULES_DIR / f"{name}.yaml"
        assert by[name]["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
        assert by[name]["file"] == f"src/portfolio/rules/tax/{name}.yaml"


def test_a_file_not_yet_in_force_is_refused(tmp_path):
    for f in RULES_DIR.glob("*.yaml"):
        shutil.copy(f, tmp_path / f.name)
    d = yaml.safe_load((tmp_path / "cdb.yaml").read_text(encoding="utf-8"))
    d["valid_from"] = "2027-01-01"
    (tmp_path / "cdb.yaml").write_text(yaml.safe_dump(d, allow_unicode=True), encoding="utf-8")
    rules = load_rules(tmp_path)
    assert not in_force(rules["cdb"], D) and in_force(rules["lci"], D)
    out = compute_tax([LineId(pos(aplicacao=dt.date(2025, 1, 1)))], {"lines": []}, {"lines": []}, D, rules_dir=tmp_path)
    ln = out["lines"][0]
    assert ln["tax"]["status"] == "sem_regra" and "fora de vigência" in ln["tax"]["reason"]


def test_a_rule_citing_an_undefined_source_is_rejected(tmp_path):
    shutil.copy(RULES_DIR / "cdb.yaml", tmp_path / "cdb.yaml")
    d = yaml.safe_load((tmp_path / "cdb.yaml").read_text(encoding="utf-8"))
    d["ir"]["events"][0]["source"] = "nao_existe"
    (tmp_path / "cdb.yaml").write_text(yaml.safe_dump(d, allow_unicode=True), encoding="utf-8")
    with pytest.raises(ValueError, match="undefined source"):
        load_rules(tmp_path)


# ---------------------------------------------------------------------------
# Tax per instrument.
# ---------------------------------------------------------------------------


def test_cdb_without_date_shows_the_bracket_and_no_figure():
    ln = one(pos(tipo="CDB"))
    t = ln["tax"]
    assert t["status"] == "faixa"
    assert t["bracket"]["text"] == DATE_MISSING_TEXT.format(lo="15%", hi="22,5%")
    assert t["bracket"]["text"] == "alíquota entre 15% e 22,5% conforme o prazo; data de aplicação não informada, a conferir"
    assert t["estimate"]["tax_brl"] is None and t["estimate"]["reason_code"] == "data_aplicacao_nao_informada"
    assert ln["a_conferir"][0]["id"] == "data_aplicacao"
    assert not [o for o in ln["optimization"] if o["kind"] == "proxima_faixa"]  # needs the date
    assert ln["iof"] is None


def test_cdb_with_date_rate_today_article_and_next_bracket():
    ln = one(pos(tipo="CDB", aplicacao=D - dt.timedelta(days=300)))
    t = ln["tax"]
    assert t["status"] == "aliquota_hoje" and t["rate_today_pct"] == 20.0 and "rate_text" not in t
    assert reader_text.tax_rate_text(t) == "20%"  # engine 2.0: the report writes the rate as text
    assert t["article"] == "Lei 11.033/2004, art. 1º, I a IV"
    nb = next(o for o in ln["optimization"] if o["kind"] == "proxima_faixa")
    assert nb["days"] == 61 and nb["text"] == "em 61 dias a alíquota cai de 20% para 17,5%"
    assert nb["label"] == "informativo; não é recomendação"
    assert t["estimate"]["tax_brl"] is None and t["estimate"]["reason_code"] == "ganho_12m_indisponivel"


def test_missing_date_never_gives_a_figure_in_the_demo():
    doc = json.loads(FIXTURE.read_text(encoding="utf-8"))
    tax = doc["tax"]
    assert doc["schema_version"] == "2.1" and doc["section_status"]["tax"]["status"] == tax["status"]
    assert all(p["data_aplicacao"] is None for p in doc["statement"]["positions"])
    assert tax["n_tax_estimated"] == 0
    for ln in tax["lines"]:
        assert ln["tax"]["estimate"]["tax_brl"] is None
        assert ln["iof"] is None
        assert not [o for o in ln["optimization"] if o["kind"] == "proxima_faixa"]


def test_exempt_product_with_article_and_gross_up():
    ln = one(pos(tipo="LCI", aplicacao=dt.date(2024, 1, 10), vencimento=dt.date(2027, 1, 10), taxa="95% do CDI"))
    t = ln["tax"]
    assert t["status"] == "isento" and t["exempt"] and reader_text.tax_rate_text(t) == "isento"
    assert t["article"] == "Lei 11.033/2004, art. 3º, II"
    assert t["estimate"]["tax_brl"] is None
    g = next(o for o in ln["optimization"] if o["kind"] == "equivalencia_bruta")
    assert g["label"] == "informativo; não é recomendação"
    assert g["term_days"] > 720 and len(g["brackets"]) == 1
    assert g["brackets"][0]["cdb_rate_pct"] == 15.0 and g["brackets"][0]["equivalent_text"] == "111,76% do CDI"
    assert float(Decimal("95") / (1 - Decimal("0.15"))) == pytest.approx(g["brackets"][0]["equivalent_pct"], abs=0.01)


def test_exempt_without_date_lists_the_four_cdb_brackets():
    for tipo in ("LCA", "CRA", "CRI"):
        ln = one(pos(tipo=tipo, taxa="IPCA + 8,74%"))
        assert ln["tax"]["status"] == "isento"
        g = next(o for o in ln["optimization"] if o["kind"] == "equivalencia_bruta")
        assert [b["cdb_rate_pct"] for b in g["brackets"]] == [22.5, 20.0, 17.5, 15.0]
        assert all(b["equivalent_pct"] is None for b in g["brackets"])  # a spread over an index is not converted


def test_debenture_shows_both_rules_and_no_figure():
    ln = one(pos(tipo="debênture", aplicacao=dt.date(2020, 1, 1)))
    t = ln["tax"]
    assert t["status"] == "candidatos"
    assert {c["instrument"] for c in t["candidates"]} == {"debenture", "debenture_incentivized"}
    assert t["bracket"]["min_pct"] == 0.0 and t["bracket"]["max_pct"] == 15.0
    assert t["estimate"]["tax_brl"] is None and t["estimate"]["reason_code"] == "mais_de_uma_regra"
    assert "debenture_lei_12431" in {a["id"] for a in ln["a_conferir"]}


def test_fund_long_or_short_and_come_cotas_mark():
    ln = one(pos(tipo="fundo"), fee_lines=[headline_fee(1, classe="Renda Fixa Duração Livre Grau de Investimento")])
    t = ln["tax"]
    assert t["status"] == "candidatos" and {c["instrument"] for c in t["candidates"]} == {"fund_long", "fund_short"}
    assert t["bracket"]["min_pct"] == 15.0 and t["bracket"]["max_pct"] == 22.5
    assert all(cc["applies"] is True for cc in t["come_cotas"]) and len(t["come_cotas"]) == 2
    assert {o["kind"] for o in ln["optimization"]} == {"come_cotas"}
    assert "fundo_longo_ou_curto" in {a["id"] for a in ln["a_conferir"]}


def test_fia_from_the_filed_anbima_class_is_15_pct_without_come_cotas():
    ln = one(pos(tipo="fundo", aplicacao=dt.date(2024, 1, 1)), fee_lines=[headline_fee(1, classe="Ações Livre")],
             ret_lines=[ret_12m(1, 10.0)])
    t = ln["tax"]
    assert t["instrument"] == "fund_equity" and t["rate_today_pct"] == 15.0
    assert t["status"] == "condicional"  # the 67% test decides the rate and the statement cannot show it
    assert t["estimate"]["tax_brl"] is None
    assert t["come_cotas"][0]["applies"] is False


def test_fii_rate_and_estimate_with_a_known_date():
    ln = one(pos(tipo="FII", valor="110000", aplicacao=dt.date(2024, 5, 2)), ret_lines=[ret_12m(1, 10.0, basis="close_sem_proventos")])
    t = ln["tax"]
    assert t["status"] == "aliquota_hoje" and t["rate_today_pct"] == 20.0
    e = t["estimate"]
    assert e["label"] == "estimativa"
    assert e["gain_12m_brl"] == 10000.0 and e["tax_brl"] == 2000.0
    assert "fii_isencao_rendimentos" in {a["id"] for a in ln["a_conferir"]}


def test_fii_bought_inside_the_window_has_no_figure():
    ln = one(pos(tipo="FII", aplicacao=dt.date(2026, 3, 1)), ret_lines=[ret_12m(1, 10.0)])
    assert ln["tax"]["estimate"]["tax_brl"] is None
    assert ln["tax"]["estimate"]["reason_code"] == "aplicacao_dentro_da_janela"


def test_shares_exemption_decides_the_rate_so_no_figure():
    ln = one(pos(tipo="ação", aplicacao=dt.date(2020, 1, 1)), ret_lines=[ret_12m(1, 26.0)])
    t = ln["tax"]
    assert t["status"] == "condicional" and t["rate_today_pct"] == 15.0
    assert any("R$ 20.000" in o for o in t["outcomes"])
    assert t["estimate"]["tax_brl"] is None


def test_etf_rule_from_the_return_basis_and_third_party_fee():
    fee = headline_fee(1, per_year=300.0, rate=0.3, kind="etf_site", counted_as_cost=True,
                       basis="taxa informada pelo site etfsbrasil.com.br (fonte de terceiros, não é documento da CVM)")
    eq = one(pos(tipo="ETF"), fee_lines=[fee], ret_lines=[ret_12m(1, 5.0, basis="close_sem_proventos")])
    assert eq["tax"]["instrument"] == "etf_equity" and eq["tax"]["rate_today_pct"] == 15.0
    assert eq["fee"]["third_party"] and "third_party_label" not in eq["fee"] and eq["fee"]["per_year_brl"] == 300.0
    view = adapt._tax_view({"tax": {"lines": [eq]}, "fees": {"lines": [fee]}})["lines"][0]
    assert "terceiros" in view["fee"]["third_party_label"]  # the fee block's own basis, added by the report
    rf = one(pos(tipo="ETF"), ret_lines=[{"line_no": 1, "basis": "last_price_etf_renda_fixa", "windows": {}}])
    assert rf["tax"]["instrument"] == "etf_fixed_income" and rf["tax"]["status"] == "faixa"
    assert rf["tax"]["bracket"]["max_pct"] == 30.0
    unknown = one(pos(tipo="ETF"))
    assert unknown["tax"]["status"] == "candidatos"


def test_pgbl_against_vgbl_two_columns_never_one_regime():
    pg = one(pos(tipo="fundo", estrategia="Previdência PGBL", classe="Previdência"), fee_lines=[headline_fee(1)])
    vg = one(pos(n=1, tipo="fundo", estrategia="Previdência VGBL", classe="Previdência"), fee_lines=[headline_fee(1)])
    for ln, plan, base in ((pg, "PGBL", "valor total do resgate"), (vg, "VGBL", "somente o rendimento")):
        pe = ln["pension"]
        assert ln["tax"]["status"] == "previdencia" and pe["plan"] == plan and pe["base"] == base
        assert pe["regime"] is None and "regime_label" not in pe
        pv = adapt._tax_view({"tax": {"lines": [ln]}})["lines"][0]["pension"]
        assert pv["regime_label"] == "opção do participante; não informada"
        assert pe["regressive"]["text"] == "tabela completa; data de início não informada, a conferir"
        assert [r["rate_pct"] for r in pe["regressive"]["table"]] == [35.0, 30.0, 25.0, 20.0, 15.0, 10.0]
        assert pe["progressive"]["text"] == ("15% antecipado; ajuste anual pela tabela progressiva, depende da renda "
                                             "total; não estimado")
        assert "irretratável" in pv["irrevocable_text"] and pe["irrevocable"] is True
        assert ln["tax"]["estimate"]["tax_brl"] is None
        assert ln["fee"]["loading"]["status"] == "nao_informado"
    assert "aportes_vgbl_ano" in {a["id"] for a in vg["a_conferir"]}
    assert "aportes_vgbl_ano" not in {a["id"] for a in pg["a_conferir"]}


def test_pension_with_a_start_date_shows_the_regressive_rate_and_next_change():
    ln = one(pos(tipo="fundo", estrategia="Previdência VGBL", classe="Previdência", aplicacao=dt.date(2021, 1, 15)))
    pe = ln["pension"]
    assert pe["regressive"]["rate_today_pct"] == 25.0  # 5 years and 8 months: over 4 up to 6
    nb = next(o for o in ln["optimization"] if o["kind"] == "proxima_faixa")
    assert nb["date"] == "2027-01-16" and "cai de 25% para 20%" in nb["text"]
    assert ln["tax"]["estimate"]["tax_brl"] is None


# ---------------------------------------------------------------------------
# Fee, IOF, person level.
# ---------------------------------------------------------------------------


def test_fee_is_the_fee_blocks_headline_labelled_estimate():
    fixa = one(pos(tipo="fundo"), fee_lines=[headline_fee(1, per_year=5292.3, rate=2.0)])
    f = fixa["fee"]
    assert f["status"] == "estimada" and f["per_year_brl"] == 5292.3 and f["label"] == "estimativa"
    assert any("Art. 98" in n for n in f["notes"]) and "taxa de performance não estimada" in f["notes"]
    rng = one(pos(tipo="fundo"), fee_lines=[headline_fee(1, kind="faixa", per_year=None, per_year_min_brl=10.0,
                                                         per_year_max_brl=20.0, rate_min_pct_year=0.1,
                                                         rate_max_pct_year=0.2)])
    assert rng["fee"]["status"] == "faixa" and rng["fee"]["per_year_max_brl"] == 20.0
    zero = one(pos(tipo="fundo"), fee_lines=[headline_fee(1, kind="zero_informado", per_year=None)])
    assert zero["fee"]["status"] == "sem_taxa" and zero["fee"]["per_year_brl"] is None
    cdb = one(pos(tipo="CDB"))
    assert cdb["fee"]["status"] == "nao_se_aplica"


def test_iof_only_when_under_30_days():
    young = dt.date(2026, 9, 20)
    cdb = one(pos(tipo="CDB", aplicacao=young))
    assert cdb["iof"]["text"] == "IOF regressivo nos primeiros 30 dias; a conferir"
    assert cdb["iof"]["article"].startswith("Decreto 6.306/2007, art. 32")
    lca = one(pos(tipo="LCA", aplicacao=young))
    assert lca["iof"]["rate_pct"] == 0.0
    assert one(pos(tipo="CDB", aplicacao=dt.date(2026, 8, 1)))["iof"] is None
    assert one(pos(tipo="CDB"))["iof"] is None  # no date, no IOF line


def test_person_flags_dividends_and_jcp_and_minimum_tax_line():
    out = run([pos(1, tipo="ação"), pos(2, tipo="CDB")])
    person = out["person"]
    flags = {f["id"]: f for f in person["flags"]}
    assert flags["dividends"]["line_nos"] == [1] and flags["dividends"]["rate_pct"] == 10.0
    assert flags["jcp"]["rate_pct"] == 17.5 and not flags["jcp"]["computed"]
    assert person["minimum_tax"]["text"] == "depende da renda total anual; fora do escopo"
    assert "LCI" in person["minimum_tax"]["excluded_income"] and person["minimum_tax"]["computed"] is False


def test_cannot_observe_items_are_printed_a_conferir_per_position():
    ln = one(pos(tipo="ação"))
    assert ln["a_conferir"] and all(a["label"] == "a conferir" for a in ln["a_conferir"])


def test_tesouro_fidc_fip_have_no_rule_and_say_why():
    out = run([pos(1, tipo="tesouro"), pos(2, tipo="FIDC"), pos(3, tipo="FIP")])
    assert out["status"] == "partial" and out["reason_codes"] == ["imposto_linhas_sem_regra"]
    for ln in out["lines"]:
        assert ln["tax"]["status"] == "sem_regra" and "nota #611" not in ln["tax"]["reason"] and "regra" in ln["tax"]["reason"]


def test_reason_codes_have_fixed_text():
    out = run([pos(1, tipo="tesouro"), pos(2, tipo="CDB"), pos(3, tipo="LCI"), pos(4, tipo="debênture"),
               pos(5, tipo="ação"), pos(6, tipo="fundo", estrategia="Previdência PGBL", classe="Previdência"),
               pos(7, tipo="FII", aplicacao=dt.date(2026, 3, 1))], ret_lines=[ret_12m(7, 3.0)])
    codes = set(out["reason_codes"]) | {ln["tax"]["estimate"]["reason_code"] for ln in out["lines"]} | {
        ln["tax"]["reason_code"] for ln in out["lines"]}
    codes.discard(None)
    assert codes and all(c in REASON_TEXT for c in codes)


# ---------------------------------------------------------------------------
# No recommendation.
# ---------------------------------------------------------------------------


def _synthetic_everything():
    return run(
        [pos(1, tipo="CDB", aplicacao=dt.date(2026, 9, 20)), pos(2, tipo="LCI", aplicacao=dt.date(2024, 1, 10),
                                                                  vencimento=dt.date(2027, 1, 10), taxa="95% do CDI"),
         pos(3, tipo="LCA", taxa="CDI + 0,50%"), pos(4, tipo="debênture"), pos(5, tipo="ação"), pos(6, tipo="FII"),
         pos(7, tipo="fundo"), pos(8, tipo="fundo", estrategia="Previdência PGBL", classe="Previdência",
                                     aplicacao=dt.date(2021, 1, 15)),
         pos(9, tipo="ETF"), pos(10, tipo="tesouro")],
        fee_lines=[headline_fee(7, classe="Ações")])


def test_optimization_text_has_no_forbidden_verb():
    docs = [json.loads(FIXTURE.read_text(encoding="utf-8"))["tax"], _synthetic_everything()]
    n_items = 0
    for doc in docs:
        for ln in doc["lines"]:
            for o in ln["optimization"]:
                n_items += 1
                assert o["label"] == "informativo; não é recomendação"
                assert not words(o["text"]) & set(FORBIDDEN), o["text"]
        # the whole section, quotes of the law included
        for s in strings(doc):
            assert not words(s) & set(FORBIDDEN), s
    assert n_items >= 5


# ---------------------------------------------------------------------------
# The statement's optional application date.
# ---------------------------------------------------------------------------


def test_spreadsheet_reads_the_optional_application_date():
    header = ["linha_extrato", "tipo", "valor", "data_posicao", "data_aplicacao"]
    stmt = parse_rows([["total_extrato", 200.0], header, ["CDB X", "CDB", 100.0, D, "15/03/2025"],
                       ["CDB Y", "CDB", 100.0, D, None]])
    assert stmt.positions[0].data_aplicacao == dt.date(2025, 3, 15) and stmt.positions[1].data_aplicacao is None
    with pytest.raises(StatementTotalMismatch, match="data_aplicacao is not a date"):
        parse_rows([["total_extrato", 100.0], header, ["CDB X", "CDB", 100.0, D, "ontem"]])
