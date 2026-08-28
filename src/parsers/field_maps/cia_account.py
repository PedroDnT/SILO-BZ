"""CIA_ABERTA ITR/DFP financial-statement line-item field map (W7).

Source CSVs: the scoped statement members inside the ITR/DFP yearly ZIPs, e.g.
             dfp_cia_aberta_DRE_con_2024.csv, itr_cia_aberta_BPA_ind_2024.csv
             (latin-1, ; delimited). Enumerated by CIAFetcher.fetch_zip_members().
Target:      cia_account  (UNIQUE NULLS NOT DISTINCT on the 8-column natural key)

Header (verified live 2026-05-29 against dfp_cia_aberta_2023.zip):
    CNPJ_CIA;DT_REFER;VERSAO;DENOM_CIA;CD_CVM;GRUPO_DFP;MOEDA;ESCALA_MOEDA;
    ORDEM_EXERC;DT_INI_EXERC;DT_FIM_EXERC;CD_CONTA;DS_CONTA;VL_CONTA;ST_CONTA_FIXA

    Balance-sheet members (BPA/BPP) are point-in-time and omit DT_INI_EXERC; the
    map tolerates the missing column (apply_map yields None for absent candidates).

Notes
-----
* ``grupo`` (BPA/BPP/DRE/DFC_MD/DFC_MI/DMPL/DRA/DVA), ``escopo`` (con/ind) and
  ``doc_type`` (itr/dfp) are NOT read from the CSV — they are injected by
  ``ingest_cia_account`` from the CIAMember filename / call argument. The map only
  covers columns that physically live in the statement CSV.
* ``CD_CVM`` is zero-padded to 6 digits in ITR/DFP (e.g. "001023"). The ``cd_cvm``
  coerce strips leading zeros to the canonical code ("1023") so cia_account joins
  cia_company / cia_event (which store the unpadded code from CAD / IPE).
* ``VL_CONTA`` is expressed in ``ESCALA_MOEDA`` units (MIL observed). It is mapped
  here as a raw ``numeric`` (pre-scale); ``ingest_cia_account`` multiplies it to
  absolute reais. ``escala_moeda`` is kept as the original string for audit.
* ``GRUPO_DFP`` (a long description), ``MOEDA``, ``DENOM_CIA`` fall through to the
  ``raw`` JSONB residual (denormalised / not modelled as typed columns).
* ``COLUNA_DF`` exists ONLY in the DMPL members (statement of changes in equity):
  the same cd_conta line repeats once per equity-component column. It is part of
  a DMPL row's natural key — without it those rows collapse ~85% under last-wins
  upsert dedup. It is NULL for every other statement type; with the constraint's
  NULLS NOT DISTINCT, those NULLs collapse so non-DMPL uniqueness is unchanged.
  Added to cia_account + uq_cia_account by migration 05_cia_account_coluna_df.sql.
* ``DT_INI_EXERC`` is likewise part of the key, for the same reason one step
  further on: an ITR income statement reports each cd_conta for BOTH the quarter
  and the year-to-date period under one DT_REFER, and only DT_INI_EXERC tells
  them apart. It is NULL for the point-in-time balance sheet (BPA/BPP), which is
  why those members were never affected. Added to uq_cia_account by migration
  29_cia_account_dt_ini_exerc.sql.
* The natural key is
  (cd_cvm, doc_type, grupo, escopo, dt_refer, ordem_exerc, coluna_df,
   dt_ini_exerc, cd_conta, versao);
  the PK on cia_account is a surrogate BIGSERIAL and the UNIQUE constraint enforces
  idempotency.
"""

TABLE = "cia_account"
CONFLICT = (
    "cd_cvm",
    "doc_type",
    "grupo",
    "escopo",
    "dt_refer",
    "ordem_exerc",
    "coluna_df",
    # An ITR income statement reports the SAME cd_conta twice under one filing —
    # once for the quarter, once year-to-date — and DT_INI_EXERC is the only
    # thing that separates them. Without it here, last-wins kept whichever row
    # the CSV listed last and threw the other away: 40% of DRE_con rows in
    # itr_cia_aberta_2025.zip (62,788 of 157,164), which is every cumulative
    # period in every quarterly income statement. Same failure as coluna_df /
    # DMPL (migration 05); key widened by migration 29.
    "dt_ini_exerc",
    "cd_conta",
    "versao",
)

FIELD_MAP = {
    "cnpj_cia":      (["CNPJ_CIA"],        "cnpj"),
    "cd_cvm":        (["CD_CVM"],          "cd_cvm"),
    "dt_refer":      (["DT_REFER"],        "date"),
    "versao":        (["VERSAO"],          "int"),
    "ordem_exerc":   (["ORDEM_EXERC"],     "text"),
    "dt_ini_exerc":  (["DT_INI_EXERC"],    "date"),
    "dt_fim_exerc":  (["DT_FIM_EXERC"],    "date"),
    "coluna_df":     (["COLUNA_DF"],       "text"),
    "cd_conta":      (["CD_CONTA"],        "text"),
    "ds_conta":      (["DS_CONTA"],        "text"),
    "vl_conta":      (["VL_CONTA"],        "numeric"),
    "escala_moeda":  (["ESCALA_MOEDA"],    "text"),
    "st_conta_fixa": (["ST_CONTA_FIXA"],   "text"),
}
