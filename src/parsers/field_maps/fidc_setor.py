"""FIDC receivables portfolio by sector field map (tab_II).

Source CSV: tab_II inside the monthly FIDC ZIP (2025+) and inside the yearly
HIST ZIP (2013-2024). The 33 value columns are the same from 2013-01 (every
HIST archive opened); only the fund key is CNPJ_FUNDO through 2019 and
CNPJ_FUNDO_CLASSE after, which the candidate list covers.
Target table: cvm_fidc_setor.

TAB_II_VL_CARTEIRA is the receivables portfolio total. It is also the only
same-ZIP, same-grain source for cvm_fidc_mensal.vl_total in the 2025+ era
(tab_IV ships six columns and the total is not one of them), so
ingest_fidc_mensal merges it in the way it merges tab_VI's delinquency total.

Column names keep CVM's letter code (A, C1, F3, ...) because the tab is a
hierarchy: C is commercial, C1/C2/C3 its members; dropping the code would leave
`vl_comerc` twice. Wide, like cvm_fidc_aging, because the CSV is one row per
(fund, month) and stays that way.
"""

TABLE = "cvm_fidc_setor"
# Unique-key audit (real inf_mensal_fidc_tab_II_202607.csv): no ID_SUBCLASSE;
# 4,382 rows, zero duplicates on (CNPJ_FUNDO_CLASSE, DT_COMPTC).
CONFLICT = ("cnpj", "period")

FIELD_MAP = {
    "cnpj":   (["CNPJ_FUNDO_CLASSE", "CNPJ_FUNDO"], "cnpj"),
    "period": (["DT_COMPTC"],                        "date"),
    "vl_carteira":              (["TAB_II_VL_CARTEIRA"],              "numeric"),
    "vl_a_indust":              (["TAB_II_A_VL_INDUST"],              "numeric"),
    "vl_b_imobil":              (["TAB_II_B_VL_IMOBIL"],              "numeric"),
    "vl_c_comerc":              (["TAB_II_C_VL_COMERC"],              "numeric"),
    "vl_c1_comerc":             (["TAB_II_C1_VL_COMERC"],             "numeric"),
    "vl_c2_varejo":             (["TAB_II_C2_VL_VAREJO"],             "numeric"),
    "vl_c3_arrend":             (["TAB_II_C3_VL_ARREND"],             "numeric"),
    "vl_d_serv":                (["TAB_II_D_VL_SERV"],                "numeric"),
    "vl_d1_serv":               (["TAB_II_D1_VL_SERV"],               "numeric"),
    "vl_d2_serv_publico":       (["TAB_II_D2_VL_SERV_PUBLICO"],       "numeric"),
    "vl_d3_serv_educ":          (["TAB_II_D3_VL_SERV_EDUC"],          "numeric"),
    "vl_d4_entret":             (["TAB_II_D4_VL_ENTRET"],             "numeric"),
    "vl_e_agroneg":             (["TAB_II_E_VL_AGRONEG"],             "numeric"),
    "vl_f_financ":              (["TAB_II_F_VL_FINANC"],              "numeric"),
    "vl_f1_cred_pessoa":        (["TAB_II_F1_VL_CRED_PESSOA"],        "numeric"),
    "vl_f2_cred_pessoa_consig": (["TAB_II_F2_VL_CRED_PESSOA_CONSIG"], "numeric"),
    "vl_f3_cred_corp":          (["TAB_II_F3_VL_CRED_CORP"],          "numeric"),
    "vl_f4_midmarket":          (["TAB_II_F4_VL_MIDMARKET"],          "numeric"),
    "vl_f5_veiculo":            (["TAB_II_F5_VL_VEICULO"],            "numeric"),
    "vl_f6_imobil_empresa":     (["TAB_II_F6_VL_IMOBIL_EMPRESA"],     "numeric"),
    "vl_f7_imobil_resid":       (["TAB_II_F7_VL_IMOBIL_RESID"],       "numeric"),
    "vl_f8_outro":              (["TAB_II_F8_VL_OUTRO"],              "numeric"),
    "vl_g_credito":             (["TAB_II_G_VL_CREDITO"],             "numeric"),
    "vl_h_factor":              (["TAB_II_H_VL_FACTOR"],              "numeric"),
    "vl_h1_pessoa":             (["TAB_II_H1_VL_PESSOA"],             "numeric"),
    "vl_h2_corp":               (["TAB_II_H2_VL_CORP"],               "numeric"),
    "vl_i_setor_publico":       (["TAB_II_I_VL_SETOR_PUBLICO"],       "numeric"),
    "vl_i1_precat":             (["TAB_II_I1_VL_PRECAT"],             "numeric"),
    "vl_i2_tribut":             (["TAB_II_I2_VL_TRIBUT"],             "numeric"),
    "vl_i3_royalties":          (["TAB_II_I3_VL_ROYALTIES"],          "numeric"),
    "vl_i4_outro":              (["TAB_II_I4_VL_OUTRO"],              "numeric"),
    "vl_j_judicial":            (["TAB_II_J_VL_JUDICIAL"],            "numeric"),
    "vl_k_marca":               (["TAB_II_K_VL_MARCA"],               "numeric"),
}
