"""Builds fake_silo_rows.json: SYNTHETIC canned rows for FakeClient, in the shape of the merged api.portfolio_* contract (python tests/fixtures/portfolio/build_fake_silo_rows.py OUT.json). Regenerate demo_engine_output.json after changing it."""
import json, sys

PERIOD = "2026-05-01"
M = 1_000_000.0

FUNDS = {
    "35377390000106": dict(name="XP BANCOS MASTER FIF RENDA FIXA", nav=7999.802 * M),
    "54891935000134": dict(name="XP CASH S1 FIF RENDA FIXA", nav=839.593 * M),
    "37525998000158": dict(name="SANTANDER CASH BLACK FIF RENDA FIXA", nav=3878.630 * M),
    "50088190000119": dict(name="XP BANCOS FIC FIF RENDA FIXA", nav=1839.409 * M),
    "51488342000133": dict(name="XP LIQUIDEZ FIC FIF RENDA FIXA", nav=3360.184 * M),
    "42592315000115": dict(name="BB RENDA FIXA CURTO PRAZO AUTOMATICO FIC FIF RESPONSABILIDADE LIMITADA", nav=198605.787 * M),
    "46133770000103": dict(name="BB TOP RF CP AUTOMATICO II FIF RESPONSABILIDADE LIMITADA", nav=198595.918 * M),
    "08935128000159": dict(name="GERACAO L. PAR FUNDO DE INVESTIMENTO EM ACOES", nav=6075.736 * M),
}

LFT_ISIN = {
    "2032-03-01": "BRSTNCLF1S08", "2030-03-01": "BRSTNCLF1RO9", "2028-09-01": "BRSTNCLF1RK7",
    "2029-09-01": "BRSTNCLF1RM3", "2030-09-01": "BRSTNCLF1RR2", "2027-03-01": "BRSTNCLF1RG5",
    "2031-09-01": "BRSTNCLF1RS0", "2030-06-01": "BRSTNCLF1RQ4", "2028-03-01": "BRSTNCLF1RI1",
}


def lft(mat, v, compromissada=False):
    return dict(block=1, asset_kind="repo" if compromissada else "government_bond", key=LFT_ISIN[mat], name="LETRAS FINANCEIRAS DO TESOURO " + mat,
                isin=LFT_ISIN[mat], tp_aplic="Operações Compromissadas" if compromissada else "Títulos Públicos",
                tp_ativo="Título público federal", tp_titpub="LETRAS FINANCEIRAS DO TESOURO", maturity=mat, value=v)


def stock(t, v, emprestada=False):
    return dict(block=4, asset_kind="stock", key=t, name=t, tp_aplic="Ações e outros TVM cedidos em empréstimo" if emprestada else "Ações",
                tp_ativo="Ações", value=v)


# leaves and child funds per fund (values in BRL); a filler LFT closes each fund to 99.7% of its NAV.
LEAVES = {
    "35377390000106": [lft("2032-03-01", 475.112 * M), lft("2030-03-01", 381.322 * M), lft("2028-09-01", 95.482 * M), lft("2029-09-01", 95.377 * M),
                       dict(block=6, asset_kind="private_credit", key="PETRDBS0X2", name="DEBENTURE EXEMPLO PETROBRAS", isin="BRPETRDBS0X2",
                            issuer_cnpj="33000167000101", issuer_code="PETR", tp_aplic="Debêntures", tp_ativo="Debênture", indexer="DI1", maturity="2031-06-15", value=300.0 * M),
                       dict(block=6, asset_kind="private_credit", key="ENEVDBS0Y1", name="DEBENTURE EXEMPLO ENEVA", isin="BRENEVDBS0Y1",
                            issuer_code="ENEV", tp_aplic="Debêntures", tp_ativo="Debênture", indexer="IAP", maturity="2034-03-15", value=120.0 * M),
                       dict(block=6, asset_kind="private_credit", key="XXXXDBS0Z9", name="DEBENTURE EXEMPLO SEM INDEXADOR", isin="BRXXXXDBS0Z9",
                            issuer_code="XXXX", tp_aplic="Debêntures", tp_ativo="Debênture", indexer=None, maturity="2029-01-15", value=50.0 * M),
                       dict(block=4, asset_kind="debenture", key="VALEDBS000", name="VALE DEBENTURE BLOCO 4", isin="BRVALEDBS000",
                            issuer_code="VALE", tp_aplic="Debêntures", tp_ativo="Debêntures", value=150.0 * M)],
    "54891935000134": [lft("2030-06-01", 142.991 * M), lft("2030-03-01", 81.508 * M), lft("2028-03-01", 58.266 * M)],
    "37525998000158": [lft("2028-09-01", 1566.981 * M),
                       dict(block=1, asset_kind="repo", key="BRSTNCNTB0A6", name="NOTAS DO TESOURO NACIONAL SERIE B 2045-05-15", isin="BRSTNCNTB0A6",
                            tp_aplic="Operações Compromissadas", tp_ativo="Título público federal", tp_titpub="NOTAS DO TESOURO NACIONAL SERIE B", maturity="2045-05-15", value=764.857 * M),
                       lft("2028-03-01", 584.930 * M), lft("2030-06-01", 575.091 * M), lft("2031-09-01", 387.419 * M)],
    "50088190000119": [],
    "51488342000133": [],
    "46133770000103": [lft("2030-09-01", 61322.450 * M, True), lft("2027-03-01", 18806.471 * M), lft("2029-09-01", 18517.316 * M, True),
                       lft("2030-06-01", 11374.094 * M, True)],
    "08935128000159": [stock("AXIA7", 1491.223 * M), stock("PETR4", 1007.855 * M), stock("BRAP4", 929.524 * M), stock("VALE3", 471.036 * M),
                       stock("VALE3", 439.984 * M, True), stock("USIM5", 422.285 * M), stock("CLSC4", 397.292 * M), stock("HYPE3", 328.650 * M)],
}
CHILDREN = {
    "35377390000106": [("54891935000134", 220.611 * M)],
    "54891935000134": [("37525998000158", 429.958 * M)],
    "50088190000119": [("35377390000106", 1832.556 * M), ("54891935000134", 19.229 * M)],
    "51488342000133": [("35377390000106", 3358.500 * M), ("54891935000134", 24.265 * M)],
    "42592315000115": [("46133770000103", 198595.918 * M)],
}
FILLER = {"35377390000106", "54891935000134", "37525998000158", "46133770000103"}


def row(root, path, depth, holder, block, kind, key, name, value, weight, **kw):
    return dict(root_cnpj=root, path=path, depth=depth, holder_cnpj=holder, block=block, asset_kind=kind, asset_key=key, asset_name=name,
                isin=kw.get("isin"), issuer_cnpj=kw.get("issuer_cnpj"), issuer_code=kw.get("issuer_code"), tp_aplic=kw.get("tp_aplic"),
                tp_ativo=kw.get("tp_ativo"), tp_titpub=kw.get("tp_titpub"), indexer_code=kw.get("indexer"), maturity=kw.get("maturity"),
                value_brl=round(value, 2), weight_in_root=round(weight, 10), period=PERIOD, is_cycle=False)


def expand(root, fund, path, depth, scale, out, max_depth=4):
    f = FUNDS[fund]
    leaves = list(LEAVES.get(fund, []))
    kids = CHILDREN.get(fund, [])
    used = sum(l["value"] for l in leaves) + sum(v for _, v in kids)
    if fund in FILLER:
        leaves.append(lft("2031-09-01", f["nav"] * 0.997 - used) | dict(name="LFT (linha agregada sintética)"))
    for l in leaves:
        out.append(row(root, path, depth, fund, l["block"], l["asset_kind"], l["key"], l["name"], l["value"], scale * l["value"] / f["nav"],
                       isin=l.get("isin"), issuer_cnpj=l.get("issuer_cnpj"), issuer_code=l.get("issuer_code"), tp_aplic=l.get("tp_aplic"),
                       tp_ativo=l.get("tp_ativo"), tp_titpub=l.get("tp_titpub"), indexer=l.get("indexer"), maturity=l.get("maturity")))
    for child, v in kids:
        w = scale * v / f["nav"]
        out.append(row(root, path, depth, fund, 2, "fund_quota", child, FUNDS[child]["name"], v, w, tp_aplic="Cotas de Fundos"))
        expand(root, child, path + [child], depth + 1, w, out, max_depth)


def lookthrough(root):
    out = []
    expand(root, root, [root], 0, 1.0, out)
    return out


canned = {}

# --- block 1
fund_names = ["GERAÇÃO L. PAR FIA", "XP BANCOS FIC", "XP LIQUIDEZ FIC", "MN I FIDC",
              "BB RENDA FIXA CURTO PRAZO AUTOMÁTICO FUNDO DE INVESTIMENTO EM COTAS DE FUNDOS DE INVESTIMENTO", "HGLG11 CSHG LOGISTICA FII"]


def rr(line_no, cnpj, cname, matched, period, kind, sim, rank, qod, qdiff, amb, reason, etype="fi"):
    return dict(line_no=line_no, input_name=fund_names[line_no - 1], candidate_cnpj=cnpj, candidate_name=cname, matched_name=matched,
                matched_period=period, entity_type=etype, match_kind=kind, similarity=sim, rank=rank, quota_on_date=qod, quota_rel_diff=qdiff,
                ambiguous=amb, reason=reason)


resolve_rows = [
    rr(1, "08935128000159", FUNDS["08935128000159"]["name"], FUNDS["08935128000159"]["name"], "2026-05-01", "name_history", 0.62, 1, 176.38, 0.0002, False,
       "Nome abreviado no extrato; a cota na data confirma."),
    rr(2, "50088190000119", FUNDS["50088190000119"]["name"], FUNDS["50088190000119"]["name"], "2026-05-01", "name_history", 0.74, 1, 1.542011, 0.0, False,
       "Nome abreviado; dois fundos plausíveis (FIC e master); a cota na data desempata."),
    rr(2, "35377390000106", FUNDS["35377390000106"]["name"], FUNDS["35377390000106"]["name"], "2026-05-01", "name_history", 0.71, 2, 1.952607, 0.2662, False,
       "A cota na data é 26,6% diferente da informada: descartado."),
    rr(3, "51488342000133", FUNDS["51488342000133"]["name"], FUNDS["51488342000133"]["name"], "2026-05-01", "cnpj", 1.0, 1, 1.289417, 0.0, False, "CNPJ informado no extrato."),
    rr(4, "32113885000121", "MN I FUNDO DE INVESTIMENTO EM DIREITOS CREDITORIOS", "MN I FUNDO DE INVESTIMENTO EM DIREITOS CREDITORIOS", "2026-05-31", "cnpj", 1.0, 1, None, None, False,
       "CNPJ informado no extrato.", etype="fidc"),
    rr(5, "42592315000115", FUNDS["42592315000115"]["name"],
       "BB RENDA FIXA CURTO PRAZO AUTOMÁTICO FUNDO DE INVESTIMENTO EM COTAS DE FUNDOS DE INVESTIMENTO", "2024-01-01", "name_history", 0.98, 1, 1.541233, 0.0, False,
       "O nome do extrato é um nome antigo do fundo."),
    rr(6, "11728688000147", "CSHG LOGISTICA FUNDO DE INVESTIMENTO IMOBILIARIO", "CSHG LOGISTICA FUNDO DE INVESTIMENTO IMOBILIARIO", "2026-05-01", "name_history", 0.55, 1, None, None, False,
       "Nome abreviado; candidato único.", etype="fii"),
]

# engine 1.7 splits portfolio_resolve: the lines with a CNPJ in one call, the others in chunks of 3. Each call's
# answer numbers its lines 1..n in ITS p_names, so the rows above (numbered in fund_names) are renumbered per call.
RESOLVE_CALLS = [[3, 4], [1, 2, 5], [6]]  # fund_names positions: CNPJ lines (XP LIQUIDEZ, MN I), then chunks of 3
canned["portfolio_resolve"] = [
    dict(match={"p_names": [fund_names[i - 1] for i in call]},
         rows=[dict(r, line_no=call.index(r["line_no"]) + 1) for r in resolve_rows if r["line_no"] in call])
    for call in RESOLVE_CALLS
]

canned["lookup"] = [
    dict(match={"p_query": "PETR4"}, rows=[dict(id="PETR4", id_type="ticker", asset_class="equity", name="PETROBRAS", isin="BRPETRACNPR6", cnpj=None, tickers=None)]),
    dict(match={"p_query": "HGLG11"}, rows=[dict(id="HGLG11", id_type="ticker", asset_class="fund_quota", name="FII HGLG PAX", isin="BRHGLGCTF004", cnpj=None, tickers=None)]),
]
canned["quote_latest"] = [
    dict(match={"p_ticker": "PETR4"}, rows=[dict(ticker="PETR4", trade_date="2026-10-01", board="02", short_name="PETROBRAS", close=49.77, isin="BRPETRACNPR6", source="b3_cotahist", asset_class="equity")]),
    dict(match={"p_ticker": "HGLG11"}, rows=[dict(ticker="HGLG11", trade_date="2026-10-01", board="12", short_name="FII HGLG PAX", close=146.99, isin="BRHGLGCTF004", source="b3_cotahist", asset_class="fund_quota")]),
]
setores = {"PETR4": ("33000167000101", "PETROLEO BRASILEIRO S.A. PETROBRAS", "Petróleo e Gás"), "AXIA7": ("00001180000126", "AXIA ENERGIA S.A.", "Energia Elétrica"),
           "BRAP4": ("03847461000192", "BRADESPAR S.A.", "Emp. Adm. Part. - Extração Mineral"), "VALE3": ("33592510000154", "VALE S.A.", "Extração Mineral"),
           "USIM5": ("60894730000105", "USINAS SIDERURGICAS DE MINAS GERAIS S.A. USIMINAS", "Metalurgia e Siderurgia"),
           "CLSC4": ("83878892000155", "CENTRAIS ELETRICAS DE SANTA CATARINA S.A.", "Energia Elétrica"), "HYPE3": ("02932074000191", "HYPERA S.A.", "Saúde")}
canned["company_financials"] = [
    dict(match={"p_id": t}, rows=[dict(id=t, id_type="ticker", cnpj=c, company=n, ticker=t, doc_type="DFP", scope="con", ref_date="2026-06-30", setor=s, segmento="Categoria A")])
    for t, (c, n, s) in setores.items()
]

# --- block 3
cnpjs_fee = sorted(["08935128000159", "50088190000119", "51488342000133", "32113885000121", "42592315000115", "11728688000147"])
label = "estimativa a partir do balancete"


EXTRATO_NOTE_CLASS = ("class-level row (CVM 175): the Extrato has no subclass column, so this is the class's fee; "
                      "a fee that differs by subclass is not visible and no subclass fee is assumed")
EXTRATO_NOTE_FUND = "fund-level row (ICVM 555): the fee of the fund as filed"
EST_OK = "estimate from the balancete accruals: (previous minus current accumulated fee) x 12 / NAV, not the disclosed fee"


def fee(cnpj, name, nav, adm_est, perf_est=None, suspect=False, origin=None, adm=None, raw=None, d_min=None, d_max=None, d_perf=None,
        asof=None, age_m=None, age_d=None, ncls=None, note=None, est_label=None, month="2026-08-31", zero=False, implausible=False,
        extrato=None, desp=None, lam=None):
    """One portfolio_fees row in the catalog v55 shape: the 21 v51 columns, the 25 of v52, then the 10 of v55.
    ``lam`` is the lâmina beside an Extrato fee (adm, as_of, age_m), synthetic."""
    src = {"extrato": "cvm_fi_extrato", "lamina": "cvm_fi_lamina", "cad_fi": "cvm_fund_registry (cad_fi)"}.get(origin)
    ex = extrato or {}
    row = dict(cnpj=cnpj, fund_name=name, month=month, nav=nav, adm_fee_flow=None if adm_est is None else round(nav * adm_est / 1200, 2),
               adm_fee_pct_annual_est=adm_est, perf_fee_flow=None, perf_fee_pct_annual_est=perf_est, fiscal_reset_suspect=suspect,
               disclosed_taxa_adm=None if implausible else adm, disclosed_taxa_adm_min=d_min if d_min is not None else (None if implausible else adm if origin == "extrato" else None),
               disclosed_taxa_adm_max=d_max if d_max is not None else (None if implausible else adm if origin == "extrato" else None),
               disclosed_taxa_perfm=d_perf, disclosed_taxa_adm_info=None, disclosed_taxa_perfm_info=None, disclosed_source=src,
               disclosed_as_of=asof, disclosed_age_months=age_m, disclosed_n_classes=ncls, disclosed_note=note, estimate_label=est_label or EST_OK)
    row.update(
        disclosed_origin=origin, disclosed_age_days=age_d, filed_zero=zero, implausible_filed=implausible,
        taxa_adm_filed_raw=raw if raw is not None else adm,
        extrato_tp_fundo_classe=ex.get("tp"), extrato_classe_anbima=ex.get("classe"),
        extrato_class_note=(EXTRATO_NOTE_CLASS if ex.get("tp") == "CLASSES - FIF" else EXTRATO_NOTE_FUND if ex.get("tp") else None),
        extrato_existe_taxa_perfm=ex.get("existe_perfm"), extrato_taxa_perfm=ex.get("perfm"), extrato_param_taxa_perfm=ex.get("param"),
        extrato_calc_taxa_perfm=ex.get("calc"), extrato_inf_taxa_perfm=ex.get("inf"), extrato_existe_taxa_ingresso=ex.get("existe_ing"),
        extrato_taxa_ingresso_pr=ex.get("ing_pr"), extrato_taxa_ingresso_real=None, extrato_existe_taxa_saida=ex.get("existe_saida"),
        extrato_taxa_saida_pr=ex.get("saida_pr"), extrato_taxa_saida_real=None, extrato_taxa_custodia_max=ex.get("custodia"),
        lamina_pr_pl_despesa=(desp or {}).get("pct"), lamina_dt_ini_despesa=(desp or {}).get("ini"), lamina_dt_fim_despesa=(desp or {}).get("fim"),
        lamina_as_of=(desp or {}).get("as_of"),
        lamina_expense_note=None if desp else "no lâmina filed an expense ratio for this fund",
    )
    # catalog v55 (#552): the rule that applied and the other document's fee, as the SQL computes them
    filed = raw if raw is not None else adm
    lam_adm = (lam or {}).get("adm") if lam else (adm if origin == "lamina" else None)
    lam_min = (lam or {}).get("adm") if lam else (d_min if d_min is not None else adm) if origin == "lamina" else None
    lam_max = (lam or {}).get("adm") if lam else (d_max if d_max is not None else adm) if origin == "lamina" else None
    to_check = origin == "extrato" and filed is not None and (filed == 0 or filed > 5)
    ext_filed = filed if origin == "extrato" else None
    row.update(
        fee_resolution=("extrato_lamina_beside" if lam else "extrato_to_check") if to_check else origin,
        lamina_taxa_adm=lam_adm, lamina_taxa_adm_min=lam_min, lamina_taxa_adm_max=lam_max,
        lamina_n_classes=1 if lam else (ncls if origin == "lamina" else None),
        lamina_age_months=(lam or {}).get("age_m") if lam else (age_m if origin == "lamina" else None),
        extrato_taxa_adm_filed=ext_filed, extrato_as_of=asof if origin == "extrato" else None,
        extrato_lamina_ratio=round(ext_filed / lam_adm, 4) if ext_filed and lam_adm else None,
        extrato_scale_factor=None,
    )
    if lam:
        row["lamina_as_of"] = lam["as_of"]
    return row


NO_DISC = "no disclosed fee in the Extrato, the lâmina or cad_fi: NULL is not a zero fee"
statement_rows = [
    # Extrato fee, CVM 175 class, performance fee as filed text, expense ratio from the lâmina
    fee("08935128000159", FUNDS["08935128000159"]["name"], 6075735724.70, 1.98, 0.35, origin="extrato", adm=2.0, asof="2026-07-31", age_m=1, age_d=64, ncls=1,
        d_perf="20% do que exceder 100% do Ibovespa",
        extrato=dict(tp="CLASSES - FIF", classe="Ações", existe_perfm="S", perfm=20.0, param="Ibovespa", calc="semestral", inf="20% do que exceder 100% do Ibovespa",
                     existe_ing="N", existe_saida="N", custodia=0.05),
        desp=dict(pct=2.31, ini="2025-07-01", fim="2026-06-30", as_of="2026-06-30")),
    # lâmina older than 24 months: defasada
    fee("42592315000115", FUNDS["42592315000115"]["name"], 198605786912.83, 1.97, origin="lamina", adm=1.5, asof="2024-03-31", age_m=29, age_d=915, ncls=1),
    # lâmina with classes that differ: the range as filed
    fee("50088190000119", FUNDS["50088190000119"]["name"], 1780000000.0, 0.20, origin="lamina", d_min=0.15, d_max=0.30, asof="2026-07-31", age_m=1, age_d=64, ncls=2,
        note="the fund's 2 classes disclose different fees: the single value is NULL, read the min and max"),
    # Extrato filed 0 while the balancete books a fee: shown, never counted as a zero cost
    # ... and a synthetic lâmina fee, older than the Extrato, shown beside it (catalog v55, #552)
    fee("51488342000133", FUNDS["51488342000133"]["name"], 3360184376.89, 0.35, origin="extrato", adm=0.0, zero=True, asof="2026-06-30", age_m=2, age_d=95, ncls=1,
        note="the Extrato filed an administration fee of exactly 0: returned as filed (filed_zero); read it as not informed, never as a zero cost",
        extrato=dict(tp="CLASSES - FIF", classe="Renda Fixa", existe_perfm="N", existe_ing="N", existe_saida="N"),
        lam=dict(adm=0.5, as_of="2026-03-31", age_m=5)),
]
underlying_rows = [
    # lâmina filed 0 and the balancete books a fee: the attention finding
    fee("35377390000106", FUNDS["35377390000106"]["name"], 7999802012.71, 0.11, origin="lamina", adm=0.0, zero=True, asof="2026-07-31", age_m=1, age_d=64, ncls=1,
        note="the lâmina filed an administration fee of exactly 0: returned as filed (filed_zero); read it as not informed, never as a zero cost"),
    # Extrato value above 5: scale error, withheld, raw kept
    fee("37525998000158", FUNDS["37525998000158"]["name"], 3878630268.71, 0.05, origin="extrato", adm=14638.0, raw=14638.0, implausible=True, asof="2025-12-31", age_m=8, age_d=276, ncls=1,
        note="the Extrato filed an administration fee of 14638, outside 0 to 5 % a year: treated as a scale error and not used; the value as filed is in taxa_adm_filed_raw",
        extrato=dict(tp="FI", classe="Renda Fixa", existe_perfm="N")),
    fee("46133770000103", FUNDS["46133770000103"]["name"], 198595917706.26, 1.41, origin="lamina", adm=0.20, asof="2026-07-31", age_m=1, age_d=64, ncls=1),
    # Extrato 30 months old: not defasada (the Extrato threshold is 36), fiscal-year reset month: no estimate
    fee("54891935000134", FUNDS["54891935000134"]["name"], 839592972.0, None, suspect=True, origin="extrato", adm=0.50, asof="2024-02-29", age_m=30, age_d=947, ncls=1,
        est_label="no estimate: the accumulated administration fee fell, the fund's fiscal-year reset month, and no cad_fi DT_INI_EXERC confirms it",
        extrato=dict(tp="CLASSES - FIF", classe="Renda Fixa", existe_perfm="N", existe_ing="N", existe_saida="N")),
]
canned["portfolio_fees"] = [
    dict(match={"p_cnpjs": cnpjs_fee, "p_month": "2026-08-01"}, rows=statement_rows),
    dict(match={"p_cnpjs": ["35377390000106", "37525998000158", "46133770000103", "54891935000134"], "p_month": "2026-08-01"}, rows=underlying_rows),
]

# --- block 2
for root in ["08935128000159", "50088190000119", "51488342000133", "42592315000115"]:
    canned.setdefault("portfolio_lookthrough", []).append(dict(match={"p_cnpjs": [root]}, rows=lookthrough(root)))
for root in ["32113885000121", "11728688000147"]:
    canned["portfolio_lookthrough"].append(dict(match={"p_cnpjs": [root]}, rows=[]))

# --- movimento incomum (api.portfolio_movement, catalog v54), 2026-09, the 18 columns in the SQL's order. Synthetic z, class
# mean and sd; the funds outside the Extrato / not FI follow what production answered on 2026-10-03.
MOV_MONTH = "2026-09-01"


def mov(cnpj, name, cls=None, n=None, own=None, mean=None, sd=None, p01=None, p99=None, z=None, level="nao_avaliado", reason=None):
    head, sub = (None, None) if cls is None else (cls.split(" - ", 1) + [None])[:2]
    return dict(cnpj=cnpj, fund_name=name, month=MOV_MONTH, **{"class": head}, subclass=sub, class_as_filed=cls,
                class_as_of="2026-09-12" if cls else None, n_peers=n, own_value_pct=own, class_mean_pct=mean, class_sd_pct=sd,
                class_p01_pct=p01, class_p99_pct=p99, z=z, level=level, investigator_trigger=level == "forte", min_peers=30, reason=reason)


COMPARED = "retorno de cota de 2026-09 comparado com {n} fundos da classe {c} (média e desvio padrão winsorizados no 1º e 99º percentil)"
mov_rows = [
    # atenção: 2 < z <= 3, table only
    mov("08935128000159", FUNDS["08935128000159"]["name"], "AÇÕES - ATIVO - LIVRE", 1773, 11.0, 4.360422, 3.081534, -4.60308, 16.36046, 2.1549, "atencao",
        COMPARED.format(n=1773, c="AÇÕES - ATIVO - LIVRE")),
    mov("42592315000115", FUNDS["42592315000115"]["name"], "RENDA FIXA - PASSIVO - ÍNDICES", 193, 1.95, 1.956172, 1.001702, -0.856962, 3.825901, -0.0062, "normal",
        COMPARED.format(n=193, c="RENDA FIXA - PASSIVO - ÍNDICES")),
    # forte: z < -3, goes in the text and sets the Investigator trigger
    mov("51488342000133", FUNDS["51488342000133"]["name"], "RENDA FIXA LIVRE DURAÇÃO - CRÉDITO LIVRE", 2243, -2.9, 0.535, 0.9566, -2.0, 3.1, -3.5911, "forte",
        COMPARED.format(n=2243, c="RENDA FIXA LIVRE DURAÇÃO - CRÉDITO LIVRE")),
    # the XP FIC is absent from the Extrato on production (2026-10-03): not evaluated, with the reason
    mov("50088190000119", FUNDS["50088190000119"]["name"], own=1.073045, reason="fundo fora do Extrato da CVM: sem classe ANBIMA informada"),
    mov("32113885000121", "MN I FUNDO DE INVESTIMENTO EM DIREITOS CREDITORIOS", reason="não é fundo FI com cota diária no SILO (fidc); sem retorno de cota mensal"),
    mov("11728688000147", "FII EXEMPLO", reason="não é fundo FI com cota diária no SILO (fii); sem retorno de cota mensal"),
]
canned["portfolio_movement"] = [dict(match={"p_cnpjs": cnpjs_fee, "p_month": MOV_MONTH}, rows=sorted(mov_rows, key=lambda r: r["cnpj"]))]

# --- block 11 (FIDC)
fp = lambda code, parent, item, v: dict(cnpj="32113885000121", period="2026-08-01", kind="sector", code=code, parent=parent, item=item, value=v)
canned["fidc_portfolio"] = [dict(match={"p_cnpj": "32113885000121"}, rows=[
    fp("TOTAL", None, "Total", 480000000.0), fp("A", None, "Indústria", 96000000.0), fp("B", None, "Comércio", 72000000.0),
    fp("C", None, "Serviços", 120000000.0), fp("C1", "C", "Serviços - transporte", 40000000.0), fp("D", None, "Agronegócio", 150000000.0)])]

# --- block 4
canned["fund_restatements"] = [
    dict(match={"p_cnpj": "32113885000121"}, rows=[
        dict(fnet_id=1298163, cnpj="32113885000121", tipo_fundo="FIDC", fund_name="MN I FUNDO DE INVESTIMENTO EM DIREITOS CREDITORIOS", tipo_documento="Informe Mensal Estruturado",
             reference_raw="07/2026", reference_date="2026-07-31", versao=2, modalidade="RE", delivered_at="2026-08-21 13:04:00", previous_fnet_id=1293383,
             previous_delivered_at="2026-08-14 17:34:00", lag_days=7, n_fields_changed=2, diff_status="compared"),
        dict(fnet_id=1120221, cnpj="32113885000121", tipo_fundo="FIDC", fund_name="MN I FUNDO DE INVESTIMENTO EM DIREITOS CREDITORIOS", tipo_documento="Informe Mensal Estruturado",
             reference_raw="01/2026", reference_date="2026-01-31", versao=2, modalidade="RE", delivered_at="2026-02-24 16:13:00", previous_fnet_id=1113801,
             previous_delivered_at="2026-02-13 13:32:00", lag_days=11, n_fields_changed=2, diff_status="compared"),
        dict(fnet_id=1086024, cnpj="32113885000121", tipo_fundo="FIDC", fund_name="MN I FUNDO DE INVESTIMENTO EM DIREITOS CREDITORIOS", tipo_documento="Informe Mensal Estruturado",
             reference_raw="12/2025", reference_date="2025-12-31", versao=2, modalidade="RE", delivered_at="2026-01-16 11:16:00", previous_fnet_id=1085168,
             previous_delivered_at="2026-01-15 19:38:00", lag_days=1, n_fields_changed=2, diff_status="compared")]),
    dict(match={"p_cnpj": "11728688000147"}, rows=[]),
]


def leaf(fid, prev, ref, delivered, prev_delivered, lag, path, blk, lf, old, new, oldn, newn):
    return dict(fnet_id=fid, previous_fnet_id=prev, cnpj="32113885000121", tipo_documento="Informe Mensal Estruturado", reference_raw=ref, versao=2, modalidade="RE",
                delivered_at=delivered, previous_delivered_at=prev_delivered, lag_days=lag, field_path=path, block=blk, leaf=lf, change_kind="changed", old_value=old,
                new_value=new, old_num=oldn, new_num=newn, delta=round(newn - oldn, 2), match_basis="path", cvm_column=None, diff_version=1,
                source_url=f"https://fnet.bmfbovespa.com.br/fnet/publico/downloadDocumento?id={fid}", previous_source_url=f"https://fnet.bmfbovespa.com.br/fnet/publico/downloadDocumento?id={prev}")


INAD = "LISTA_INFORM/APLIC_ATIVO/CRED_EXISTE/VL_CRED_EXISTE_INAD"
PL = "LISTA_INFORM/PATRLIQ/VL_PATRIM_LIQ"
canned["fund_restatement_diff"] = [
    dict(match={"p_fnet_id": 1298163}, rows=[
        leaf(1298163, 1293383, "07/2026", "2026-08-21 13:04:00", "2026-08-14 17:34:00", 7, INAD, "APLIC_ATIVO", "VL_CRED_EXISTE_INAD", "234716701,70", "255281411,73", 234716701.70, 255281411.73),
        leaf(1298163, 1293383, "07/2026", "2026-08-21 13:04:00", "2026-08-14 17:34:00", 7, PL, "PATRLIQ", "VL_PATRIM_LIQ", "549614285,94", "96794048,98", 549614285.94, 96794048.98)]),
    dict(match={"p_fnet_id": 1120221}, rows=[
        leaf(1120221, 1113801, "01/2026", "2026-02-24 16:13:00", "2026-02-13 13:32:00", 11, INAD, "APLIC_ATIVO", "VL_CRED_EXISTE_INAD", "187284652,71", "195818556,47", 187284652.71, 195818556.47),
        leaf(1120221, 1113801, "01/2026", "2026-02-24 16:13:00", "2026-02-13 13:32:00", 11, PL, "PATRLIQ", "VL_PATRIM_LIQ", "506043487,89", "514904640,02", 506043487.89, 514904640.02)]),
    dict(match={"p_fnet_id": 1086024}, rows=[
        leaf(1086024, 1085168, "12/2025", "2026-01-16 11:16:00", "2026-01-15 19:38:00", 1, INAD, "APLIC_ATIVO", "VL_CRED_EXISTE_INAD", "0,00", "187284652,71", 0.0, 187284652.71),
        leaf(1086024, 1085168, "12/2025", "2026-01-16 11:16:00", "2026-01-15 19:38:00", 1, PL, "PATRLIQ", "VL_PATRIM_LIQ", "0,00", "506043487,89", 0.0, 506043487.89)]),
]

# --- block 14: other CNPJs are synthetic strangers; MN I appears where the measurements say it would
canned["screen_zombie_growth"] = [dict(match={}, rows=[dict(cnpj="00000000000191", fund_name="FUNDO ESTRANHO A", period="2026-08-01", nav_mm=12.5, delinquency_pct=31.2, screen="zombie_growth", params={"p_min_delinq_pct": 5, "p_min_aum": 1000000})])]
canned["screen_captive_vehicles"] = [dict(match={}, rows=[dict(cnpj="00000000000272", fund_name="FUNDO ESTRANHO B", latest_period="2026-08-01", max_nav_mm=80.0, min_quotaholders=1, screen="captive_vehicles", params={"p_lookback_months": 3})])]
canned["screen_evergreen_aging"] = [dict(match={}, rows=[])]
canned["screen_delinquency_drivers"] = [dict(match={"p_driver": "value_up_rate_masked"}, rows=[]), dict(match={"p_driver": "consistent_worsening"}, rows=[
    dict(cnpj="32113885000121", fund_name="MN I FUNDO DE INVESTIMENTO EM DIREITOS CREDITORIOS", status="complete", window_from="2025-09-01", window_to="2026-08-01", n_months=12, months_missing=0,
         first_month="2025-09-01", last_month="2026-08-01", delinquency_start=0.0, delinquency_end=255281411.73, delta_brl=255281411.73, nav_start=506043487.89, nav_end=96794048.98,
         delta_nav=-409249438.91, rate_start=0.0, rate_end=263.7, delta_pp=263.7, stopped_reporting=False, driver="consistent_worsening", screen="delinquency_drivers", params={"p_months": 12, "p_driver": "consistent_worsening"})])]
canned["screen_restatements"] = [dict(match={}, rows=[
    dict(cnpj="32113885000121", tipo_fundo="FIDC", fund_name="MN I FUNDO DE INVESTIMENTO EM DIREITOS CREDITORIOS", window_from="2025-09-01", window_to="2026-08-01", documents=12,
         restatements=3, restatements_re=3, restatements_rc=0, restatement_pct=25.0, last_restated_at="2026-08-21 13:04:00", screen="restatements", params={"p_months": 12, "p_min_restatements": 3, "p_min_rate_pct": 20})])]
canned["screen_late_filers"] = [dict(match={}, rows=[])]
canned["screen_silent_filers"] = [dict(match={}, rows=[])]
canned["screen_dormant_funds"] = [
    dict(match={"p_dormancy": "empty_shell"}, rows=[dict(cnpj="00000000000353", fund_name="FUNDO ESTRANHO C", administrator="ADM X", window_from="2026-05-01", window_to="2026-07-01", months_observed=3, max_quotaholders=0, last_nav=1000.0, dormancy="empty_shell", screen="dormant_funds", params={"p_dormancy": "empty_shell"})]),
    dict(match={"p_min_nav": 1000000000}, rows=[dict(cnpj="00000000000434", fund_name="FUNDO ESTRANHO D", administrator="ADM Y", window_from="2026-05-01", window_to="2026-07-01", months_observed=3, max_quotaholders=5, last_nav=2.5e9, dormancy="parked", screen="dormant_funds", params={"p_min_nav": 1000000000})]),
]

# --- engine 1.9: direct credit by its registry code (api.portfolio_instruments), synthetic. One call for the demo's CRA and
# debênture, the codes as the statement prints them (the API strips the CRA-/CRI-/DEB- prefix). The CRA's single series
# matures on another date than the statement prints (vencimento_diverge); the debênture's funds' mark is below the
# statement's price (different dates). The ISIN's issuer code (ENEV) is one the XP master holds in block 6.
def inst(line_no, input_code, code, kind, **kw):
    base = dict(line_no=line_no, input_code=input_code, code=code, match_kind=kind, instrument_type=None, cnpj_securit=None,
                numero_serie=None, classe=None, data_vencimento=None, situacao=None, taxa_juros=None, classificacao_risco_atual=None,
                valor_total_integralizado=None, data_referencia=None, cd_isin=None, issuer_code=None, n_fundos=None,
                preco_marcacao_fundos=None, cda_period=None, reason=None)
    base.update(kw)
    return base


canned["portfolio_instruments"] = [dict(match={"p_codes": ["CRA-0260000X", "DEB-EXEM12"]}, rows=[
    inst(1, "CRA-0260000X", "0260000X", "securit_cetip", instrument_type="cra_mensal", cnpj_securit="90000000000500", numero_serie="1",
         classe="Sênior", data_vencimento="2032-04-15", situacao="Adimplente", taxa_juros="IPCA+ 8,7400% a.a", classificacao_risco_atual="brAA (sf)",
         valor_total_integralizado=250000000.0, data_referencia="2026-08-31", reason="exact CETIP code in cvm_securit_serie (synthetic)"),
    inst(2, "DEB-EXEM12", "EXEM12", "cda_ticker", instrument_type="debenture", cd_isin="BRENEVDBS0Z1", issuer_code="ENEV", n_fundos=14,
         preco_marcacao_fundos=53571.43, cda_period="2026-05-01", reason="cd_ativo in CDA block 4, funds' weighted mark (synthetic)"),
])]

# --- engine 1.9: managers and redemption terms (api.portfolio_fund_terms), synthetic: one row per fund CNPJ, in line order.
def terms(line_no, cnpj, gid, gname, src=None, asof=None, conv=None, pagto=None, tp=None, lock=None, reason=None):
    return dict(line_no=line_no, input_cnpj=cnpj, cnpj=cnpj, gestor_id=gid, gestor_name=gname, admin_cnpj="90000000000900",
                admin_name="ADMINISTRADORA EXEMPLO", terms_source=src, terms_dt_comptc=asof, qt_dia_conversao_cota=conv,
                qt_dia_pagto_resgate=pagto, tp_dia_pagto_resgate=tp, qt_dia_resgate_cotas=lock, reason=reason)


TERMS_CNPJS = ["08935128000159", "50088190000119", "51488342000133", "32113885000121", "42592315000115", "11728688000147"]
NO_TERMS = "no redemption terms in the Extrato or the lâmina: NULL is not filed, never zero (closed-end funds file none)"
canned["portfolio_fund_terms"] = [dict(match={"p_cnpjs": TERMS_CNPJS}, rows=[
    terms(1, TERMS_CNPJS[0], "90000000000101", "GESTORA EXEMPLO ALFA", "extrato", "2026-07-31", 30, 32, "DIAS ÚTEIS", 0),
    terms(2, TERMS_CNPJS[1], "90000000000202", "GESTORA EXEMPLO BETA", "extrato", "2026-06-30", 0, 1, "DIAS ÚTEIS", 0),
    terms(3, TERMS_CNPJS[2], "90000000000202", "GESTORA EXEMPLO BETA", "extrato", "2026-06-30", 0, 0, "DIAS ÚTEIS", 0),
    terms(4, TERMS_CNPJS[3], "90000000000303", "GESTORA EXEMPLO GAMA", reason=NO_TERMS),
    terms(5, TERMS_CNPJS[4], "90000000000404", "GESTORA EXEMPLO DELTA", "lamina", "2024-03-31", 0, 0, "DIAS CORRIDOS", None),
    terms(6, TERMS_CNPJS[5], "90000000000505", "GESTORA EXEMPLO EPSILON", reason=NO_TERMS),
])]

canned = {"_note": "Synthetic canned rows for FakeClient. Shapes follow the silo-mcp contract; values are modelled on production measurements of 2026-10-03 (CDA 2026-05) but "
                   "names marked FIF / EXEMPLO / ESTRANHO, aggregate 'linha agregada sintética' LFT rows, fee, sector and screen rows are invented. Never read as data."} | canned
json.dump(canned, open(sys.argv[1], "w"), ensure_ascii=False, indent=1)
print({k: len(v) for k, v in canned.items() if k != "_note"})
