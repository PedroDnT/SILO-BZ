"""FII INF_TRIMESTRAL — IMOVEL member field map (the property register).

Source CSV: inf_trimestral_fii_imovel_{year}.csv, inside
            inf_trimestral_fii_{year}.zip (latin-1, ';'-delimited, 19 fields).
Target table: cvm_fii_imovel  (NOT cvm_fii_periodic — different grain).

GRAIN
-----
Many properties per fund per quarter: 20,227 rows for 2025 against 1,3xx funds
and 5 reference dates. cvm_fii_periodic is keyed (cnpj, doc_type, period_year,
data_referencia) — one row per fund per period — so this member cannot live
there without collapsing a fund's entire portfolio into a single row.

WHY THE KEY CARRIES row_hash
----------------------------
CVM publishes no property identifier, and the file legitimately repeats
identical descriptive rows: fund 04.141.645/0001-03 reports five separate 460 m2
units in "ED. CONTINENTAL SQUARE FARIA LIMA" for 2025-03-31, indistinguishable
on every descriptive field. Measured on the real 2025 member:

    (cnpj, data_referencia, nome_imovel)                      -> 302 collisions
    (cnpj, data_referencia, versao, classe, nome, endereco)   -> 187 collisions
    + area + numero_unidades                                  -> 135 collisions
    full source row                                           ->   0 collisions

So any descriptive key silently drops ~260 real rows per year to upsert dedup.
row_hash is a sha256 over the row's own source fields — no invented value, no
guess — and it makes re-ingesting an unchanged file an exact no-op while never
mapping one property onto another's row. `versao` is carried as a column: CVM
bumps it when a fund refiles a quarter, so analytics should read the max versao
per (cnpj, data_referencia).

row_hash is computed in src/pipeline/ingest_fii.py (it needs the whole raw row,
which a per-column FIELD_MAP cannot see), not here.
"""

TABLE = "cvm_fii_imovel"
CONFLICT = ("cnpj", "data_referencia", "row_hash")

FIELD_MAP = {
    "cnpj":            (["CNPJ_Fundo_Classe", "CNPJ_FUNDO_CLASSE", "CNPJ_Fundo"], "cnpj"),
    "data_referencia": (["Data_Referencia", "DT_COMPTC"], "date"),
    "versao":          (["Versao"],                        "int"),

    # Identity of the property as the fund describes it
    "classe":          (["Classe"],                        "text"),
    "nome_imovel":     (["Nome_Imovel"],                   "text"),
    "endereco":        (["Endereco"],                      "text"),
    "area":            (["Area"],                          "numeric"),
    "numero_unidades": (["Numero_Unidades"],               "int"),
    "outras_caracteristicas": (["Outras_Caracteristicas_Relevantes"], "text"),

    # Performance of the property in the quarter
    "pr_vacancia":       (["Percentual_Vacancia"],       "pct"),
    "pr_inadimplencia":  (["Percentual_Inadimplencia"],  "pct"),
    "pr_receitas_fii":   (["Percentual_Receitas_FII"],   "pct"),
    "pr_locado":         (["Percentual_Locado"],         "pct"),
    "pr_vendido":        (["Percentual_Vendido"],        "pct"),

    # Development pipeline (only filled for properties under construction)
    "pr_conclusao_obras_realizado": (["Percentual_Conclusao_Obras_Realizado"], "pct"),
    "pr_conclusao_obras_previsto":  (["Percentual_Conclusao_Obras_Previsto"],  "pct"),
    "custo_construcao_realizado":   (["Custo_Construcao_Realizado"],           "numeric"),
    "custo_construcao_previsto":    (["Custo_Construcao_Previsto"],            "numeric"),

    "pr_imovel_total_investido": (["Percentual_Imovel_Total_Investido"], "pct"),
}
