"""FI debenture holdings (CDA block 6) field map.

Source CSV: cda_fi_BLC_6_{year}{month:02d}.csv inside the monthly ZIP, and
cda_fi_BLC_6_{year}.csv inside the yearly HIST archive. Both are members of the
archives `cda` already downloads, so this block costs no extra fetch.

WHY THIS BLOCK. Blocks 4 and 2 give the fund→equity and fund→fund edges. Block 6
is the fund→**corporate credit** edge: which company's debt a fund holds, at what
maturity, indexed to what, and at what spread. CPF_CNPJ_EMISSOR is a real CNPJ, so
it joins straight to the cia_* listed-company universe — the same shape as
cd_ativo joining block 4 to the quote tape, one asset class over.

COLUMN NAMES DRIFT, identically to blocks 4 and 2: the 2023+ monthly files use
CNPJ_FUNDO_CLASSE / TP_FUNDO_CLASSE, the yearly HIST archives (2005-2022) use
CNPJ_FUNDO / TP_FUNDO. Verified byte-identical otherwise between
cda_fi_BLC_6_2015.csv and cda_fi_BLC_6_202606.csv — 29 columns, same order.

UNIQUE-KEY AUDIT, measured on both eras of the real published files:

    key                                     2015 HIST (253,563)   202606 (3,279)
    cnpj+period                                  27,076 (89.3% lost)   624 (81.0%)
    + tp_fundo                                   27,076 (89.3%)        624 (81.0%)
    + tp_aplic + tp_ativo                        28,991 (88.6%)        810 (75.3%)
    + cpf_cnpj_emissor                          188,634 (25.6%)      1,812 (44.7%)
    + dt_venc                                   213,406 (15.8%)      2,982 ( 9.1%)
    + tp_negoc                                  213,441 (15.8%)      2,984 ( 9.0%)
    + row_hash          (shipped)               253,563 ( 0.0%)      3,279 ( 0.0%)

WHY row_hash IS NEEDED HERE AND NOT IN BLOCK 4. Block 4 has CD_ATIVO — one
published column that names the instrument. A debenture has no such column. What
remains after (issuer, maturity) is a second series of the same issuer maturing
the same day at a different coupon: the audit shows the residual groups separate
on PR_CUPOM_POSFX (16,910 groups in 2015), CD_INDEXADOR_POSFX (761) and
PR_TAXA_PREFX (432). Those are genuinely different securities holding different
money, so discarding them would repeat the exact failure blocks 4, 2 and FIP were
each fixed for.

The alternative — putting the four rate columns in the key — was measured and
also reaches 0% loss, but it makes four nullable NUMERICs load-bearing for
identity, and a key that ends in a coupon rate cannot serve a range scan. row_hash
goes LAST, as a tiebreaker after a natural key that still supports
(fund, period) and (issuer, period) lookups.

row_hash is safe here in the way that matters: full-row uniqueness equals row
count in both files (253,563 and 3,279), so no two source rows are byte-identical
and the digest never silently merges two real positions. Re-ingesting an
unchanged file is an exact no-op.
"""

TABLE = "cvm_fi_cda_debentures"
CONFLICT = (
    "cnpj", "period", "tp_fundo", "tp_aplic", "tp_ativo",
    "cpf_cnpj_emissor", "dt_venc", "tp_negoc", "row_hash",
)

FIELD_MAP = {
    "cnpj":                (["CNPJ_FUNDO_CLASSE", "CNPJ_FUNDO"], "cnpj"),
    "tp_fundo":            (["TP_FUNDO_CLASSE", "TP_FUNDO"],     "text"),
    # period is recomputed by the ingest module as first-of-month; DT_COMPTC is
    # listed so it is consumed rather than duplicated into raw.
    "period":              (["DT_COMPTC"],                       "date"),
    "denom_social":        (["DENOM_SOCIAL"],                    "text"),
    "tp_aplic":            (["TP_APLIC"],                        "text"),
    "tp_ativo":            (["TP_ATIVO"],                        "text"),
    "tp_negoc":            (["TP_NEGOC"],                        "text"),
    "emissor_ligado":      (["EMISSOR_LIGADO"],                  "text"),
    # The issuer. PF_PJ_EMISSOR says whether CPF_CNPJ_EMISSOR is a CPF or a
    # CNPJ, so it is kept as published text rather than validated as a CNPJ —
    # coercing a CPF through the 14-digit validator would drop the row.
    "pf_pj_emissor":       (["PF_PJ_EMISSOR"],                   "text"),
    "cpf_cnpj_emissor":    (["CPF_CNPJ_EMISSOR"],                "text"),
    "emissor":             (["EMISSOR"],                         "text"),
    "dt_venc":             (["DT_VENC"],                         "date"),
    # Rate structure: post-fixed (indexer + spread + coupon) or pre-fixed.
    "titulo_posfx":        (["TITULO_POSFX"],                    "text"),
    "cd_indexador_posfx":  (["CD_INDEXADOR_POSFX"],              "text"),
    "ds_indexador_posfx":  (["DS_INDEXADOR_POSFX"],              "text"),
    "pr_indexador_posfx":  (["PR_INDEXADOR_POSFX"],              "numeric"),
    "pr_cupom_posfx":      (["PR_CUPOM_POSFX"],                  "numeric"),
    "pr_taxa_prefx":       (["PR_TAXA_PREFX"],                   "numeric"),
    "titulo_cetip":        (["TITULO_CETIP"],                    "text"),
    "titulo_garantia":     (["TITULO_GARANTIA"],                 "text"),
    "cnpj_instituicao_financ_coobr": (["CNPJ_INSTITUICAO_FINANC_COOBR"], "text"),
    "qt_pos_final":        (["QT_POS_FINAL"],                    "numeric"),
    "vl_merc_pos_final":   (["VL_MERC_POS_FINAL"],               "numeric"),
    "vl_custo_pos_final":  (["VL_CUSTO_POS_FINAL"],              "numeric"),
    "qt_aquis_negoc":      (["QT_AQUIS_NEGOC"],                  "numeric"),
    "vl_aquis_negoc":      (["VL_AQUIS_NEGOC"],                  "numeric"),
    "qt_venda_negoc":      (["QT_VENDA_NEGOC"],                  "numeric"),
    "vl_venda_negoc":      (["VL_VENDA_NEGOC"],                  "numeric"),
}
