# CVM Pipeline — Asset Map, Ingestion Spec & Validation Protocol

## Objective

Track Brazilian capital markets industry metrics — AUM, flows, delinquency, tranche performance, emissions — across all regulated fund types with enough regularity and fidelity to answer accountability questions: Is industry AUM growing? Where is delinquency rising? Are senior tranches performing as promised? Which securitization series are in distress?

All raw data comes from CVM's open portal (`dados.cvm.gov.br`). The pipeline fetches, normalises, and persists it to Supabase for SQL analysis.

---

## 1. Asset Map

| Entity | What it represents | Industry size | Frequency | CVM portal path |
|---|---|---|---|---|
| **FI** | All regulated investment funds (open-ended) | ~R$8tn AUM | Daily + Monthly | `/FI/DOC/` |
| **FIDC** | Receivables funds — tranche structure (sênior/mezanino/subordinada) | ~R$700bn AUM | Monthly | `/FIDC/DOC/` |
| **FIAGRO** | Agribusiness chain funds (from 2025-05) | ~R$50bn+ | Monthly | `/FIAGRO/DOC/` |
| **FIP** | Private equity / venture funds | ~R$900bn AUM | Quarterly/4-monthly | `/FIP/DOC/` |
| **FII** | Real estate investment trusts (listed) | ~R$400bn AUM | Monthly | `/FII/DOC/` |
| **SECURIT** | CRA / CRI / OTS securitization vehicles — multi-series | ~R$4tn outstanding | Monthly | `/SECURIT/DOC/` |

BACEN macro series (SELIC, IPCA, CDI, PTAX, Focus) are in the schema but no ingestor exists yet.

---

## 2. Entity Specifications

### 2.1 FI — Fundos de Investimento

**Available doc types:**

| doc_type | File pattern | Rows/period | Key content |
|---|---|---|---|
| `inf_diario` | `inf_diario_fi_{YYYYMM}.zip` → `inf_diario_fi_{YYYYMM}.csv` | ~400k | Daily NAV, quota price, flows, quotaholders |
| `cda` | `cda_fi_{YYYYMM}.zip` → `cda_fi_BLC_1_{YYYYMM}.csv` | ~50k deduped | Portfolio by asset class |
| `perfil_mensal` | `perfil_mensal_fi_{YYYYMM}.csv` | ~10k | Investor concentration |
| `balancete` | `balancete_fi_{YYYYMM}.zip` → `balancete_fi_{YYYYMM}.csv` | ~30k | Monthly balance sheet |

**Critical field mapping (`inf_diario`):**

| DB column | Raw CSV column |
|---|---|
| `cnpj` | `CNPJ_FUNDO_CLASSE` (normalize to 14 digits) |
| `dt_comptc` | `DT_COMPTC` |
| `vl_patrim_liq` | `VL_PATRIM_LIQ` |
| `captc_dia` | `CAPTC_DIA` |
| `resg_dia` | `RESG_DIA` |
| `vl_quota` | `VL_QUOTA` |
| `nr_cotst` | `NR_COTST` |

**Upsert key:** `(cnpj, dt_comptc)`

---

### 2.2 FIDC — Fundos de Investimento em Direitos Creditórios

**ZIP structure — 17 CSVs (confirmed from real data):**

Each monthly ZIP (`inf_mensal_fidc_{YYYYMM}.zip`) contains:

| CSV | Granularity | Key content | Pipeline status |
|---|---|---|---|
| `tab_I` | Fund | Full asset breakdown: credits with/without risk, delinquency, cedentes (top 9), derivatives | **Not ingested** |
| `tab_II` | Fund | Portfolio by sector: industrial, commercial, agronegócio, financial, real estate, etc. | **Not ingested** |
| `tab_III` | Fund | Liabilities breakdown | Not useful for NAV |
| `tab_IV` | Fund | **NAV** (`TAB_IV_A_VL_PL`) and average PL (`TAB_IV_B_VL_PL_MEDIO`) | **Ingested → `cvm_fidc_mensal`** |
| `tab_V` | Fund | Credits with risk: maturity aging buckets (30/60/.../1080+ days) | **Not ingested** |
| `tab_VI` | Fund | Credits without risk: same aging + delinquency by bucket | **Not ingested** |
| `tab_VII` | Fund | Count and value of receivables (current, overdue, non-performing) by cedente/prestador/terceiro | **Not ingested** |
| `tab_IX` | Fund | Derivative pricing (min/avg/max buy/sell per asset class) | Not priority |
| `tab_X` | Fund | Credit risk rating distribution (AA, A, B, … H) + tax debt | **Not ingested** |
| `tab_X_1` | **Series** | Quotaholders per tranche/series (`TAB_X_CLASSE_SERIE`) | **Not ingested** |
| `tab_X_1_1` | Fund | Quotaholder breakdown by investor type for sênior and subordinada | **Not ingested** |
| `tab_X_2` | **Series** | Quota price (`TAB_X_VL_COTA`) and quantity per tranche | **Not ingested** |
| `tab_X_3` | **Series** | Monthly return % (`TAB_X_VL_RENTAB_MES`) per tranche | **Not ingested** |
| `tab_X_4` | **Series** | Cash flows (captações, resgates, resgates solicitados) per tranche | **Not ingested** |
| `tab_X_5` | Fund | Liquidity buckets (0/30/60/90/180/360/360+ days) | **Not ingested** |
| `tab_X_6` | **Series** | Expected vs actual performance % per tranche | **Not ingested** |
| `tab_X_7` | Fund | Guarantee / collateral value and % over portfolio | **Not ingested** |

**The `TAB_X_CLASSE_SERIE` identifier (tranche key):**

Values observed in real data:
- `"Subclasse Sênior Série 1"` / `"Subclasse Senior Série 2"`
- `"Subclasse Subordinada Subordinada 1"`
- `"Subclasse Subordinada Mezanino 1"`
- `"Subclasse Subordinada Junior"` (no series number)

**Current ingestion — `cvm_fidc_mensal`:**

| DB column | Raw CSV column (tab_IV) |
|---|---|
| `cnpj` | `CNPJ_FUNDO_CLASSE` |
| `period` | `DT_COMPTC` |
| `vl_patrim_liq` | `TAB_IV_A_VL_PL` → fallback `VL_PATRIM_LIQ` |
| `vl_total` | `VL_TOTAL` or `VL_CARTEIRA_TOTAL` |
| `vl_inadimpl` | Any column containing `inadimpl` |

**Upsert key:** `(cnpj, period)` — fund-level, one row per fund per month.

**Missing — tranche-level tables (to be designed):**

`cvm_fidc_tranche` — one row per fund per series per month:
- Source: `tab_X_2` (quota price/qty) + `tab_X_3` (return) + `tab_X_6` (expected vs actual)
- Key columns: `cnpj`, `period`, `classe_serie` (e.g., "Subclasse Sênior Série 1"), `vl_cota`, `qt_cota`, `vl_rentab_mes`, `pr_desemp_esperado`, `pr_desemp_real`
- Upsert key: `(cnpj, period, classe_serie)`

`cvm_fidc_tranche_flows` — one row per fund per series per operation type per month:
- Source: `tab_X_4`
- Key columns: `cnpj`, `period`, `classe_serie`, `tp_oper` (captações/resgates/etc.), `vl_total`, `qt_cota`

`cvm_fidc_aging` — delinquency aging buckets per fund per month:
- Source: `tab_VI` (credits at risk by days overdue)
- Key columns: `cnpj`, `period`, `vl_inad_30`, `vl_inad_60`, `vl_inad_90`, ..., `vl_inad_maior_1080`

---

### 2.3 FIAGRO — Fundos de Investimento nas Cadeias Produtivas Agroindustriais

Available from **2025-05** only. ZIP mirrors FIDC monthly structure. Use uppercase column names (`VL_PATRIM_LIQ` directly, no tab disambiguation needed).

---

### 2.4 FIP — Fundos de Investimento em Participações

| doc_type | Years | File pattern |
|---|---|---|
| `inf_trimestral` | 2010–2023 | `inf_trimestral_fip_{year}.csv` |
| `inf_quadrimestral` | 2024+ | `inf_quadrimestral_fip_{year}.csv` |

Flat yearly CSVs. Key column: `VL_PATRIM_LIQ`. No tranche structure.

**Upsert key:** `(cnpj, doc_type, period_year)`

---

### 2.5 FII — Fundos de Investimento Imobiliário

**ZIP structure — 3 CSVs per yearly ZIP:**

| CSV | Key content | Pipeline status |
|---|---|---|
| `inf_mensal_fii_geral_{year}.csv` | Fund registration, mandate, manager info | Ingested but no financial fields mapped |
| `inf_mensal_fii_ativo_passivo_{year}.csv` | Full balance sheet: real estate assets by type, CRI/LCI holdings, rendimentos a distribuir, passivo | **Ingested but no financial fields mapped** |
| `inf_mensal_fii_complemento_{year}.csv` | **NAV**, quotaholders by type, dividend yield, monthly return, amortization | **Ingested → `cvm_fii_mensal`** |

**Full column inventory — `complemento` (relevant fields not yet ingested):**

| Column | Meaning |
|---|---|
| `Patrimonio_Liquido` | NAV ✓ currently mapped |
| `Total_Numero_Cotistas` | Total quotaholders |
| `Numero_Cotistas_Pessoa_Fisica` | Retail investors |
| `Valor_Ativo` | Total assets |
| `Cotas_Emitidas` | Shares outstanding |
| `Valor_Patrimonial_Cotas` | Book value per share |
| `Percentual_Rentabilidade_Efetiva_Mes` | Effective monthly return % |
| `Percentual_Rentabilidade_Patrimonial_Mes` | Patrimony-based monthly return % |
| `Percentual_Dividend_Yield_Mes` | Monthly dividend yield % |
| `Percentual_Amortizacao_Cotas_Mes` | Monthly amortization % |

**Full column inventory — `ativo_passivo` (not ingested):**

| Column | Meaning |
|---|---|
| `Imoveis_Renda_Acabados` | Completed income-generating real estate |
| `CRI` / `LCI` / `LCI_LCA` | Fixed income holdings |
| `FII` | Exposure to other FIIs |
| `Rendimentos_Distribuir` | Accrued income to distribute |
| `Total_Passivo` | Total liabilities |

**Current ingestion — `cvm_fii_mensal`:**

| DB column | Source CSV | Raw column |
|---|---|---|
| `cnpj` | `complemento` | `CNPJ_Fundo_Classe` |
| `period` | `complemento` | `Data_Referencia` → first 7 chars + `-01` |
| `doc_subtype` | derived | `"geral"` / `"ativo_passivo"` / `"complemento"` |
| `vl_patrim_liq` | `complemento` | `Patrimonio_Liquido` |

**Upsert key:** `(cnpj, period, doc_subtype)`

**Missing — fields to add to `cvm_fii_mensal` for `complemento` rows:**

`nr_cotst`, `vl_ativo`, `cotas_emitidas`, `vl_patrimonial_cotas`, `pct_rentab_efetiva_mes`, `pct_rentab_patrimonial_mes`, `pct_dividend_yield_mes`, `pct_amortizacao_mes`

---

### 2.6 SECURIT — Securitizadoras (CRA / CRI / OTS)

**ZIP structure — 8 CSVs per yearly ZIP (confirmed from real data):**

| CSV | Granularity | Key content | Pipeline status |
|---|---|---|---|
| `inf_mensal_cra_ativo_passivo_{year}.csv` | Certificate | Total assets, credits by aging, cash, derivatives, **`Valor_Atualizado_Emissao`** | **Ingested (fallback — first alphabetical CSV)** |
| `inf_mensal_cra_classe_{year}.csv` | **Series** | Per-series: Classe, Numero_Serie, CETIP code, ISIN, maturity, status, Valor_Total_Integralizado, interest rate, yield, credit rating | **Not ingested** |
| `inf_mensal_cra_fluxo_caixa_{year}.csv` | Certificate | Cash flows split by tranche: Senior principal+interest, Mezanino principal+interest, Junior principal+interest | **Not ingested** |
| `inf_mensal_cra_geral_{year}.csv` | Certificate | Issuer, trustee, custodian, collateral type, number of series, revolving flag | **Not ingested** |
| `inf_mensal_cra_cedente_devedor_{year}.csv` | Certificate | Cedente/devedor concentration (CNPJ, % share) | **Not ingested** |
| `inf_mensal_cra_direitos_creditorios_{year}.csv` | Certificate | Credits receivable, delinquency, concentration | **Not ingested** |
| `inf_mensal_cra_derivativos_{year}.csv` | Certificate | Derivative positions | Not priority |
| `inf_mensal_cra_desembolso_{year}.csv` | Certificate | Disbursement schedule by bucket (30/60/90/… days) | **Not ingested** |

**Important:** The current `csv_name_pattern = "inf_mensal_cra_{year}.csv"` does NOT match any file in the ZIP. The fetcher falls back to the **first alphabetical CSV** (`ativo_passivo`). This works coincidentally because `ativo_passivo` has the fields we need (`Valor_Atualizado_Emissao`, `Ativo`, `Data_Referencia`). If CVM renames or reorders ZIPs, the fallback will break silently.

**Fix required:** Set `csv_name_pattern` to `"inf_mensal_cra_ativo_passivo_{year}.csv"` to be explicit.

**Current `cvm_securit_mensal` field mapping (from `ativo_passivo`):**

| DB column | Raw CSV column | Source |
|---|---|---|
| `cnpj_securit` | `CNPJ_Emissora` | `ativo_passivo` |
| `dt_emissao` | `Data_Referencia` → fallback `DT_EMISSAO` | `ativo_passivo` |
| `vl_emissao` | `Valor_Atualizado_Emissao` → fallback `VL_EMISSAO` | `ativo_passivo` |
| `vl_total` | `Ativo` → fallback `VL_TOTAL` | `ativo_passivo` |

**Missing — series-level table (to be designed):**

`cvm_securit_serie` — one row per certificate series per month:
- Source: `inf_mensal_cra_classe_{year}.csv` (and CRI/OTS equivalents)
- Key columns: `cnpj_securit`, `codigo_identificacao` (`Codigo_Identificacao_Certificado`), `data_referencia`, `classe` (Sênior/Subordinada), `numero_serie`, `codigo_cetip`, `codigo_isin`, `data_vencimento`, `situacao`, `valor_total_integralizado`, `taxa_juros`, `rentabilidade`, `classificacao_risco_atual`
- Upsert key: `(cnpj_securit, codigo_identificacao, data_referencia, numero_serie)`

`cvm_securit_fluxo` — monthly cash flow by tranche per certificate:
- Source: `inf_mensal_cra_fluxo_caixa_{year}.csv`
- Key columns: `cnpj_securit`, `codigo_identificacao`, `data_referencia`, `recebimentos_direitos_creditorios`, `pagamentos_classe_senior`, `pagamentos_senior_principal`, `pagamentos_senior_juros`, `pagamentos_mezanino`, `pagamentos_junior`, `variacao_liquida_caixa`

---

## 3. Accountability Rules

These are the specific checks the pipeline should support after full ingestion. Each maps to a SQL query.

### 3.1 FIDC Tranche Performance vs Target

**Rule:** A senior tranche should deliver its promised return. If `pr_desemp_real < pr_desemp_esperado` for 2+ consecutive months, flag the fund.

```sql
-- Underperforming senior tranches (last 3 months)
SELECT cnpj, period, classe_serie,
       pr_desemp_esperado, pr_desemp_real,
       pr_desemp_real - pr_desemp_esperado AS gap
FROM cvm_fidc_tranche
WHERE classe_serie ILIKE '%senior%'
  AND pr_desemp_real < pr_desemp_esperado
  AND period >= CURRENT_DATE - INTERVAL '3 months'
ORDER BY gap ASC
LIMIT 20;
```

### 3.2 FIDC Delinquency Aging Concentration

**Rule:** If > 30% of the delinquent portfolio is in the 360+ day bucket, the receivables are likely unrecoverable.

```sql
-- Funds with heavy long-tail delinquency
SELECT cnpj, period,
       vl_inad_maior_1080 + vl_inad_1080 AS vl_long_tail,
       vl_total_inad,
       ROUND(100.0 * (vl_inad_maior_1080 + vl_inad_1080) / NULLIF(vl_total_inad, 0), 1) AS pct_long_tail
FROM cvm_fidc_aging
WHERE period = (SELECT MAX(period) FROM cvm_fidc_aging)
  AND vl_total_inad > 0
ORDER BY pct_long_tail DESC
LIMIT 20;
```

### 3.3 FIDC Industry Delinquency Trend

**Rule:** Track month-over-month change in industry-wide delinquency ratio.

```sql
SELECT period,
       ROUND(SUM(vl_inadimpl) / NULLIF(SUM(vl_patrim_liq), 0) * 100, 2) AS delinquency_pct
FROM cvm_fidc_mensal
GROUP BY period
ORDER BY period DESC
LIMIT 24;
```

### 3.4 SECURIT — Distressed Series

**Rule:** A CRA/CRI series is distressed if `Situacao != 'Adimplente'` or `Rentabilidade = 0` for a live series.

```sql
-- Non-performing securitization series
SELECT cnpj_securit, codigo_identificacao, numero_serie, classe,
       data_vencimento, situacao, valor_total_integralizado, rentabilidade
FROM cvm_securit_serie
WHERE data_referencia = (SELECT MAX(data_referencia) FROM cvm_securit_serie)
  AND situacao != 'Adimplente'
  AND data_vencimento > CURRENT_DATE
ORDER BY valor_total_integralizado DESC;
```

### 3.5 SECURIT — Tranche Cash Flow vs Receivables

**Rule:** If `pagamentos_classe_senior > recebimentos_direitos_creditorios`, the senior tranche is being paid out of reserves, not new receivables — a structural risk signal.

```sql
-- Certificates paying senior from reserves (cash burn)
SELECT cnpj_securit, codigo_identificacao, data_referencia,
       recebimentos_direitos_creditorios,
       pagamentos_classe_senior,
       pagamentos_classe_senior - recebimentos_direitos_creditorios AS cash_burn
FROM cvm_securit_fluxo
WHERE data_referencia >= CURRENT_DATE - INTERVAL '6 months'
  AND pagamentos_classe_senior > recebimentos_direitos_creditorios
ORDER BY cash_burn DESC
LIMIT 20;
```

### 3.6 FII — Dividend Yield vs Industry Average

**Rule:** Flag FIIs with dividend yield more than 2 standard deviations below the industry median.

```sql
WITH monthly_yield AS (
    SELECT period,
           PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY pct_dividend_yield_mes) AS median_yield,
           STDDEV(pct_dividend_yield_mes) AS std_yield
    FROM cvm_fii_mensal
    WHERE doc_subtype = 'complemento'
      AND pct_dividend_yield_mes IS NOT NULL
      AND period = (SELECT MAX(period) FROM cvm_fii_mensal WHERE doc_subtype = 'complemento')
    GROUP BY period
)
SELECT f.cnpj, f.period, f.pct_dividend_yield_mes,
       m.median_yield,
       ROUND((f.pct_dividend_yield_mes - m.median_yield) / NULLIF(m.std_yield, 0), 2) AS z_score
FROM cvm_fii_mensal f
JOIN monthly_yield m ON f.period = m.period
WHERE f.doc_subtype = 'complemento'
  AND (f.pct_dividend_yield_mes - m.median_yield) / NULLIF(m.std_yield, 0) < -2
ORDER BY z_score ASC;
```

### 3.7 FI — Industry Net Flow (Monthly Health Check)

```sql
SELECT DATE_TRUNC('month', dt_comptc) AS month,
       COUNT(DISTINCT cnpj) AS active_funds,
       SUM(captc_dia) / 1e9 AS inflow_bn,
       SUM(resg_dia) / 1e9 AS redemption_bn,
       (SUM(captc_dia) - SUM(resg_dia)) / 1e9 AS net_flow_bn
FROM cvm_fi_diario
GROUP BY 1 ORDER BY 1 DESC LIMIT 12;
```

---

## 4. Pre-Run Validation Protocol

Run these checks on a **single recent period** before triggering a historical backfill.

### Step 1 — Smoke seed

```bash
python scripts/seed_local_db.py --skip-fi
# Seeds: FIDC 2025-03, FII 2024, FIP 2024, SECURIT CRA/CRI 2024
```

### Step 2 — Field population (Q2 gate)

```bash
python scripts/run_analysis_local.py
```

Expected after current fixes:

| Field | Target null rate |
|---|---|
| `FIDC vl_patrim_liq` (tab_IV) | < 1% |
| `FII complemento vl_patrim_liq` | < 1% |
| `SECURIT vl_emissao` (Valor_Atualizado_Emissao) | < 5% |
| `SECURIT vl_total` (Ativo) | < 5% |
| `SECURIT dt_emissao` (Data_Referencia) | < 1% |

### Step 3 — Business plausibility

| Entity | Expected range |
|---|---|
| FI industry PL (latest month) | R$7–10tn |
| FIDC industry PL | R$600–800bn |
| FII (complemento) PL | R$300–500bn |
| FIP 2024 PL | R$700bn–1.1tn |
| SECURIT CRA total assets | R$1.2–2tn |
| SECURIT CRI total assets | R$2–3tn |

---

## 5. Ingestion Sequence

1. **FIDC, FIP, FIAGRO, FII, SECURIT** — run concurrently, low volume
2. **FI inf_diario** — run last, separately (~15 min/year; 400k rows/month)
3. **FI cda, perfil_mensal** — optional, after inf_diario

Concurrency limits in `backfill()`: 6 FI tasks at a time, 10 others.

---

## 6. Schema Gaps & Expansion Plan

### Immediate fixes (before next backfill)

| Fix | File | Change |
|---|---|---|
| SECURIT csv_name_pattern | `src/fetchers/cvm_config.py` | Change `"inf_mensal_cra_{year}.csv"` → `"inf_mensal_cra_ativo_passivo_{year}.csv"` (same for CRI, OTS) |
| FII complemento extra columns | `src/pipeline/cvm_pipeline.py` | Add `nr_cotst`, `vl_ativo`, `cotas_emitidas`, `pct_rentab_efetiva_mes`, `pct_dividend_yield_mes` to `ingest_fii_mensal` |
| FII schema | `src/store/schema.sql` | Add columns to `cvm_fii_mensal` for the new fields |

### New tables to design (next sprint)

| Table | Source CSV(s) | Granularity | Priority |
|---|---|---|---|
| `cvm_fidc_tranche` | `tab_X_2`, `tab_X_3`, `tab_X_6` | Fund × series × month | **High** — enables accountability rules 3.1 |
| `cvm_fidc_tranche_flows` | `tab_X_4` | Fund × series × op_type × month | High |
| `cvm_fidc_aging` | `tab_VI` | Fund × month | Medium — enables rule 3.2 |
| `cvm_fidc_portfolio` | `tab_II` | Fund × sector × month | Medium |
| `cvm_securit_serie` | `classe` CSV | Certificate × series × month | **High** — enables rule 3.4 |
| `cvm_securit_fluxo` | `fluxo_caixa` CSV | Certificate × month | **High** — enables rule 3.5 |

---

## 7. Known Gaps

| Gap | Impact | Next step |
|---|---|---|
| FIDC/FII Supabase data pre-fix: `vl_patrim_liq = NULL` | All historical FIDC + FII PL analytics broken | Backfill: `backfill(entity_filter="fidc")`, `backfill(entity_filter="fii")` |
| SECURIT `csv_name_pattern` uses first-alphabetical fallback | Silent breakage if CVM renames files | Fix config to use explicit `ativo_passivo` pattern |
| SECURIT `classe` and `fluxo_caixa` not ingested | Cannot track series status or tranche cash flow | Design + implement `cvm_securit_serie` + `cvm_securit_fluxo` |
| FIDC tranche tabs (X_2, X_3, X_4, X_6) not ingested | Cannot track per-tranche performance, yield, or expected vs actual | Design + implement `cvm_fidc_tranche` |
| FII complemento missing yield/return columns | Cannot track fund income distribution | Add columns to schema + ingestor |
| BACEN ingestor not implemented | Cannot compute yield-adjusted returns or macro correlation | Add `src/pipeline/bacen_pipeline.py` |
| `cvm_fi_diario` partition: add 2027 in Jan 2027 | Performance degrades past `future` partition | Add to schema.sql before Jan 2027 |
| FIAGRO no data before 2025-05 | Expected gap | Add to seed/backfill when CVM publishes |
