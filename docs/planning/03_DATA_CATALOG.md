# 03 — DATA CATALOG (Covered vs Missing + Real Shapes)

Source: CVM CKAN catalog (`https://dados.cvm.gov.br/api/3/action/package_list`, 54
datasets) cross-referenced against `src/fetchers/cvm_config.py`. All CVM CSVs are
**latin-1, `;`-delimited**, in **yearly zips** (except some single-CSV cadastres).

## Coverage summary: 16 / 54 datasets ingested

### ✅ Covered (Domain A)
- **FI:** `inf_diario`, `cda`, `perfil_mensal`
- **FII:** `inf_mensal` (geral/ativo_passivo/complemento), `inf_trimestral`, `inf_anual`, `dfin`
- **FIDC:** `inf_mensal` (tab_IV fund-level, tab_X tranches, tab_VI aging)
- **FIP:** `inf_trimestral`, `inf_quadrimestral`
- **FIAGRO:** `inf_mensal`
- **SECURIT:** `inf_mensal_cra/cri/ots`, `dfin_cra/cri`

### ⚠️ Configured but not stored
- `fi-doc-balancete` (URL in config, no table) → finish or delete (W0 decision).

### ❌ Missing — Domain A gaps
- `fi-cad` (fund cadastre — the proper source for `cvm_fund_registry`) — **W2, HIGH**
- `fi-doc-lamina`, `fi-doc-extrato`, `fi-doc-compl`, `fi-doc-entrega`, `fi-doc-eventual` — LOW

### ❌ Missing — Domain B (listed companies) — the new track
- Cadastre: `cia_aberta-cad`
- Financials: `cia_aberta-doc-itr` (quarterly), `cia_aberta-doc-dfp` (annual)
- Events: `cia_aberta-doc-ipe` (material facts)
- Reference: `cia_aberta-doc-fre`, `-fca`, `-cgvn`, `-vlmo`, `-eventos-recompra_acoes`

### ❌ Missing — other (lower priority / out of scope for now)
- Issuers: `emissores`, `cia_estrang-cad`, `cia_incent-cad`, `emissor_cepac-cad`
- Offerings: `oferta-distrib`, `distrpubl`, `coord_oferta-cad`, `crowdfunding-cad`
- Participants: `adm_cart-cad`, `adm_fii-cad`, `agente_auton-cad`, `agente_fiduc-cad`, `auditor-cad`, `consultor_vlmob-cad`, `intermed-cad`, `ato_declr-intermed`, `invnr-cad`
- Pension/insurance funds: `fie-doc-balancete`, `fie-doc-balanco`, `fie-medidas`
- Enforcement/misc: `processo-sancionador`, `arrecadacao-receita-publica`

---

## Domain B — real CSV shapes (verified from the portal)

### ITR & DFP — identical structure
Yearly zip `itr_cia_aberta_{year}.zip` / `dfp_cia_aberta_{year}.zip`, each containing
~19 member CSVs:
- Index: `itr_cia_aberta_{year}.csv` — cols: `CNPJ_CIA;DT_REFER;VERSAO;DENOM_CIA;CD_CVM;CATEG_DOC;ID_DOC;DT_RECEB;LINK_DOC`
- Statement members: `BPA`, `BPP`, `DRE`, `DFC_MD`, `DFC_MI`, `DMPL`, `DRA`, `DVA`, each in `_con` (consolidated) and `_ind` (individual) variants; plus `composicao_capital` and `parecer`.
- Statement CSV cols (long/account-line): `CNPJ_CIA;DT_REFER;VERSAO;DENOM_CIA;CD_CVM;GRUPO_DFP;MOEDA;ESCALA_MOEDA;ORDEM_EXERC;DT_INI_EXERC;DT_FIM_EXERC;CD_CONTA;DS_CONTA;VL_CONTA;ST_CONTA_FIXA`
- **Notes:** `VL_CONTA` uses **dot decimals**; `ESCALA_MOEDA` (`MIL` = thousands) must be normalized at ingest; `ORDEM_EXERC ∈ {ULTIMO, PENULTIMO}`; `CD_CONTA` is a standardized account taxonomy (e.g. `3.01` = revenue) → enables cross-company comparison; companies refile so `VERSAO` > 1 happens (upsert latest-wins).

### IPE — single CSV/year (material facts feed)
`ipe_cia_aberta_{year}.zip` → one CSV with cols:
`CNPJ_Companhia;Nome_Companhia;Codigo_CVM;Data_Referencia;Categoria;Tipo;Especie;Assunto;Data_Entrega;Tipo_Apresentacao;Protocolo_Entrega;Versao;Link_Download`
Cheap to ingest; high UI value (a live disclosures feed). Unique key ≈ `(Protocolo_Entrega, Versao)`.

### FRE / FCA / CGVN / VLMO
Multi-CSV yearly zips, thematic (governance, capital, risk, insider trades). Ingest
selectively in B2; structure mirrors the index+members pattern above.

## Proposed Domain B tables (see W5/W7; DDL sketch in `04`)
- `cia_company` (dim: cd_cvm, cnpj_cia, name, sector, segment, situation)
- `cia_filing` (index of submitted ITR/DFP docs)
- `cia_account` (tall financial-statement facts; partition by `dt_refer` year)
- `cia_event` (IPE material-facts feed)

## Cross-domain bridge
`cia_account.cnpj_cia` ↔ fund-portfolio CNPJs (FIDC originators, CRA debtors, FII
counterparties) → join a fund's exposure to the issuer's actual financials. This is the
platform's differentiating capability and should be a first-class analytical view (W9).
