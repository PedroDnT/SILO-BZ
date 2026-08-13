"""FI monthly investor profile (PERFIL_MENSAL) field map.

Source CSV: perfil_mensal_fi_{year}{month:02d}.csv (latin-1, ';'-delimited).
Target table: cvm_fi_perfil.

The source ships 107 fields (106 pre-CVM-175). This map lifts the ones that
answer the questions the /fi dashboard asks — who owns the fund (16 investor
types, by headcount AND by share of PL), how concentrated it is, and how fast
it could be liquidated — into typed columns. Everything still unmapped
(the FPR/VaR scenario block, the emissor identity block, assembly votes) falls
through to residual `raw`.

Header stability, verified against the real files rather than assumed:
perfil_mensal_fi_202012.csv (106 fields) and perfil_mensal_fi_202512.csv (107)
differ only in the key — CNPJ_FUNDO became CNPJ_FUNDO_CLASSE and TP_FUNDO_CLASSE
was added. Every other column below is spelled identically in both, so only the
key needs a legacy fallback. Ordering convention (see fii_geral.py): current
CVM-175 header first, legacy name last.

NR_COTST_* is a headcount (INT); PR_PL_COTST_* is that type's share of PL —
they are NOT interchangeable, which is exactly why both families are lifted.
"""

TABLE = "cvm_fi_perfil"
CONFLICT = ("cnpj", "period")

FIELD_MAP = {
    # ---- natural key -------------------------------------------------------
    "cnpj":          (["CNPJ_FUNDO_CLASSE", "CNPJ_FUNDO"],  "cnpj"),
    "period":        (["DT_COMPTC", "DT_REF"],               "date"),
    "tp_fundo":      (["TP_FUNDO_CLASSE", "TP_FUNDO"],       "text"),

    # ---- risk / portfolio profile -----------------------------------------
    "mod_var":                          (["MOD_VAR"],                          "text"),
    "vedac_taxa_perfm":                 (["VEDAC_TAXA_PERFM"],                 "text"),
    "pr_var_carteira":                  (["PR_VAR_CARTEIRA"],                  "pct"),
    "prazo_carteira_titulo":            (["PRAZO_CARTEIRA_TITULO"],            "numeric"),
    "pr_variacao_diaria_cota":          (["PR_VARIACAO_DIARIA_COTA"],          "pct"),
    "pr_variacao_diaria_cota_estresse": (["PR_VARIACAO_DIARIA_COTA_ESTRESSE"], "pct"),
    "pr_ativo_cred_priv":               (["PR_ATIVO_CRED_PRIV"],               "pct"),

    # ---- investor headcount by type (16 buckets) ---------------------------
    "nr_cotst_pf_pb":                (["NR_COTST_PF_PB"],                "int"),
    "nr_cotst_pf_varejo":            (["NR_COTST_PF_VAREJO"],            "int"),
    "nr_cotst_pj_nao_financ_pb":     (["NR_COTST_PJ_NAO_FINANC_PB"],     "int"),
    "nr_cotst_pj_nao_financ_varejo": (["NR_COTST_PJ_NAO_FINANC_VAREJO"], "int"),
    "nr_cotst_banco":                (["NR_COTST_BANCO"],                "int"),
    "nr_cotst_corretora_distrib":    (["NR_COTST_CORRETORA_DISTRIB"],    "int"),
    "nr_cotst_pj_financ":            (["NR_COTST_PJ_FINANC"],            "int"),
    "nr_cotst_invnr":                (["NR_COTST_INVNR"],                "int"),
    "nr_cotst_eapc":                 (["NR_COTST_EAPC"],                 "int"),
    "nr_cotst_efpc":                 (["NR_COTST_EFPC"],                 "int"),
    "nr_cotst_rpps":                 (["NR_COTST_RPPS"],                 "int"),
    "nr_cotst_segur":                (["NR_COTST_SEGUR"],                "int"),
    "nr_cotst_capitaliz":            (["NR_COTST_CAPITALIZ"],            "int"),
    "nr_cotst_fi_clube":             (["NR_COTST_FI_CLUBE"],             "int"),
    "nr_cotst_distrib":              (["NR_COTST_DISTRIB"],              "int"),
    "nr_cotst_outro":                (["NR_COTST_OUTRO"],                "int"),

    # ---- share of PL by investor type (the same 16 buckets, in money) ------
    "pr_pl_cotst_pf_pb":                (["PR_PL_COTST_PF_PB"],                "pct"),
    "pr_pl_cotst_pf_varejo":            (["PR_PL_COTST_PF_VAREJO"],            "pct"),
    "pr_pl_cotst_pj_nao_financ_pb":     (["PR_PL_COTST_PJ_NAO_FINANC_PB"],     "pct"),
    "pr_pl_cotst_pj_nao_financ_varejo": (["PR_PL_COTST_PJ_NAO_FINANC_VAREJO"], "pct"),
    "pr_pl_cotst_banco":                (["PR_PL_COTST_BANCO"],                "pct"),
    "pr_pl_cotst_corretora_distrib":    (["PR_PL_COTST_CORRETORA_DISTRIB"],    "pct"),
    "pr_pl_cotst_pj_financ":            (["PR_PL_COTST_PJ_FINANC"],            "pct"),
    "pr_pl_cotst_invnr":                (["PR_PL_COTST_INVNR"],                "pct"),
    "pr_pl_cotst_eapc":                 (["PR_PL_COTST_EAPC"],                 "pct"),
    "pr_pl_cotst_efpc":                 (["PR_PL_COTST_EFPC"],                 "pct"),
    "pr_pl_cotst_rpps":                 (["PR_PL_COTST_RPPS"],                 "pct"),
    "pr_pl_cotst_segur":                (["PR_PL_COTST_SEGUR"],                "pct"),
    "pr_pl_cotst_capitaliz":            (["PR_PL_COTST_CAPITALIZ"],            "pct"),
    "pr_pl_cotst_fi_clube":             (["PR_PL_COTST_FI_CLUBE"],             "pct"),
    "pr_pl_cotst_distrib":              (["PR_PL_COTST_DISTRIB"],              "pct"),
    "pr_pl_cotst_outro":                (["PR_PL_COTST_OUTRO"],                "pct"),

    # ---- concentration -----------------------------------------------------
    "pr_comitente_1":            (["PR_COMITENTE_1"],            "pct"),
    "pr_comitente_2":            (["PR_COMITENTE_2"],            "pct"),
    "pr_comitente_3":            (["PR_COMITENTE_3"],            "pct"),
    "comitente_ligado_1":        (["COMITENTE_LIGADO_1"],        "bool"),
    "comitente_ligado_2":        (["COMITENTE_LIGADO_2"],        "bool"),
    "comitente_ligado_3":        (["COMITENTE_LIGADO_3"],        "bool"),
    "pr_ativo_emissor_ligado":   (["PR_ATIVO_EMISSOR_LIGADO"],   "pct"),
    "pr_patrim_liq_maior_cotst": (["PR_PATRIM_LIQ_MAIOR_COTST"], "pct"),

    # ---- liquidity ---------------------------------------------------------
    # These four ARE in the header of every vintage checked (2020-12, 2025-12)
    # but CVM ships them 100% empty in both — 0 of 12,272 and 0 of 24,979 rows.
    # They are mapped so that if CVM ever starts populating them the values land
    # in a typed column instead of raw. Nothing is synthesised to fill them: a
    # column the source leaves blank stays NULL.
    "nr_dia_cinqu_perc":          (["NR_DIA_CINQU_PERC"],          "numeric"),
    "nr_dia_cem_perc":            (["NR_DIA_CEM_PERC"],            "numeric"),
    "st_liqdez":                  (["ST_LIQDEZ"],                  "text"),
    "pr_patrim_liq_convtd_caixa": (["PR_PATRIM_LIQ_CONVTD_CAIXA"], "pct"),
}
