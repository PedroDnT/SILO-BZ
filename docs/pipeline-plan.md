# CVM Pipeline — Master Plan

**Objective:** Regular accountability and analysis of Brazilian capital markets — AUM, flows, delinquency, tranche performance, emissions — sourced from CVM's open data portal and persisted to Supabase for SQL analysis.

---

## Control surfaces

The same `CVMIngestor` is driven through three surfaces — they share the audit log
(`cvm_ingest_log`) and idempotent upsert keys, so they can be mixed safely.

| Surface | Use case | Trigger |
|---|---|---|
| `python -m src.pipeline.run_daily` | Production cron — current + previous month for monthlies, current year for yearlies | `.github/workflows/daily_ingest.yml` @ 06:00 UTC |
| `python -m src.pipeline.run_backfill --start-year 2019` | Historical bulk fills | Manual, long-running |
| `flask --app app run` + `POST /api/ingest` | Interactive partial fills, retry of failed slices, progress polling, error classification | Operator from localhost — see `README.md` "Flask control plane" |

The Flask layer is the right surface for finishing the FIDC tranche / SECURIT serie
backfills (`docs/PLAN.md` Phase 3): you can fire one `(year, month)` slice, inspect
warnings / classified errors, then either retry that slice or POST `/api/ingest/range`
to chain the rest.

---

## Part 1 — What Data Exists and What It Contains

### 1.1 FI — Fundos de Investimento (~R$8tn AUM)

One fund can appear as many rows per day (one per quota class). All financial metrics are fund-level.

| doc_type | File | Frequency | Primary use |
|---|---|---|---|
| `inf_diario` | `inf_diario_fi_{YYYYMM}.zip` | Daily (monthly ZIP) | NAV, flows, quota price |
| `cda` | `cda_fi_{YYYYMM}.zip` → `cda_fi_BLC_1_*` | Monthly | Portfolio composition by asset class |
| `perfil_mensal` | `perfil_mensal_fi_{YYYYMM}.csv` | Monthly | Investor concentration |
| `balancete` | `balancete_fi_{YYYYMM}.zip` | Monthly | Balance sheet |

**Key columns (inf_diario):** `CNPJ_FUNDO_CLASSE`, `DT_COMPTC`, `VL_PATRIM_LIQ`, `VL_QUOTA`, `CAPTC_DIA`, `RESG_DIA`, `NR_COTST`

**DB table:** `cvm_fi_diario` — upsert key `(cnpj, dt_comptc)`, partitioned by year

**Analysis available today:**
- Industry AUM trend (daily/monthly)
- Net flow = `SUM(captc_dia) - SUM(resg_dia)`
- Individual fund NAV track over time
- Quota price performance

---

### 1.2 FIDC — Fundos de Investimento em Direitos Creditórios (~R$700bn AUM)

Each monthly ZIP contains **17 CSVs**. The pipeline currently reads only `tab_IV`. All 17 tabs are documented below with official field descriptions from CVM's data dictionary.

| CSV (tab) | Granularity | What it contains |
|---|---|---|
| **tab_I** | Fund | Full balance sheet: receivables with/without risk by category, delinquency, cedente concentration (top 9), derivatives, other assets |
| **tab_II** | Fund | Portfolio by sector: industrial, commercial (retail/wholesale/leasing), services (education/entertainment/utilities), agronegócio, financial (consumer credit, consignado, corporate, vehicles, real estate), factoring, judicial, brand rights |
| **tab_III** | Fund | Liabilities: payables (short-term/long-term), derivative positions |
| **tab_IV** | Fund | **NAV** (`TAB_IV_A_VL_PL`) + 3-month average PL (`TAB_IV_B_VL_PL_MEDIO`) |
| **tab_V** | Fund | Credits WITH risk acquisition — maturity aging (30/60/90/120/150/180/360/720/1080/1080+ days) + delinquency by aging + early payoff by aging |
| **tab_VI** | Fund | Credits WITHOUT risk acquisition — same aging structure (recourse structures where cedente retains risk) |
| **tab_VII** | Fund | Monthly acquisitions (qty+value, with/without risk, current/overdue/non-performing), alienations (to cedente, service providers, third parties), substitutions, repurchases |
| **tab_IX** | Fund | Derivative pricing: min/avg/max buy/sell for each asset class |
| **tab_X** | Fund | Credit risk rating distribution (AA→H), tax debt |
| **tab_X_1** | **Series** | Quotaholders count per tranche/series (`TAB_X_CLASSE_SERIE`) |
| **tab_X_1_1** | Fund | Quotaholder breakdown: sênior and subordinada counts by investor type (PF, PJ, bank, distributor, foreign, pension fund, insurer, etc.) |
| **tab_X_2** | **Series** | Quota quantity (`TAB_X_QT_COTA`) and quota price (`TAB_X_VL_COTA`) per tranche |
| **tab_X_3** | **Series** | Monthly return % (`TAB_X_VL_RENTAB_MES`) per tranche |
| **tab_X_4** | **Series** | Flows per tranche: captações/resgates/resgates solicitados + qty and value |
| **tab_X_5** | Fund | Portfolio liquidity buckets (0/30/60/90/180/360/360+ days) |
| **tab_X_6** | **Series** | Expected (`TAB_X_PR_DESEMP_ESPERADO`) vs actual (`TAB_X_PR_DESEMP_REAL`) performance % per tranche |
| **tab_X_7** | Fund | Collateral: guarantee value and % over portfolio |

**`TAB_X_CLASSE_SERIE` values (the tranche key):**
- `"Subclasse Sênior Série 1"`, `"Subclasse Sênior Série 2"`, …
- `"Subclasse Subordinada Mezanino 1"`
- `"Subclasse Subordinada Subordinada 1"`
- `"Subclasse Subordinada Junior"`

**Currently ingested → `cvm_fidc_mensal`:** tab_IV only — NAV, 3-month avg PL, total, delinquency (generic), quotaholders. Upsert key `(cnpj, period)`.

**Missing (high priority):**
- Per-tranche performance, return, flows — tabs X_2, X_3, X_4, X_6
- Delinquency aging buckets — tab_VI
- Sector portfolio breakdown — tab_II
- Monthly acquisition/alienation activity — tab_VII

---

### 1.3 FIAGRO — Agribusiness Funds

Available from **2025-05** only. ZIP mirrors FIDC but uses uppercase column names (`VL_PATRIM_LIQ` directly, no tab disambiguation). Same DB structure as FIDC.

---

### 1.4 FIP — Private Equity / Venture (~R$900bn AUM)

Flat yearly CSVs. No tranche structure. Key column: `VL_PATRIM_LIQ`.

| doc_type | Years | Pattern |
|---|---|---|
| `inf_trimestral` | 2010–2023 | `inf_trimestral_fip_{year}.csv` |
| `inf_quadrimestral` | 2024+ | `inf_quadrimestral_fip_{year}.csv` |

**Currently ingested → `cvm_fip_periodic`:** NAV only. Upsert key `(cnpj, doc_type, period_year)`.

---

### 1.5 FII — Real Estate Investment Trusts (~R$400bn AUM)

One yearly ZIP, three CSVs with different content:

| CSV | Key content |
|---|---|
| `geral` | Registration: mandate, manager, ISIN, market listing, admin info |
| `ativo_passivo` | Balance sheet: real estate by type (renda/venda/construção), CRI/LCI holdings, `Rendimentos_Distribuir`, total passivo |
| `complemento` | **NAV** (`Patrimonio_Liquido`), quotaholders by type (PF/PJ/bank/foreign/pension/insurer/other FII/clubs), `Valor_Ativo`, `Cotas_Emitidas`, `Valor_Patrimonial_Cotas`, **`Percentual_Rentabilidade_Efetiva_Mes`**, **`Percentual_Rentabilidade_Patrimonial_Mes`**, **`Percentual_Dividend_Yield_Mes`**, `Percentual_Amortizacao_Cotas_Mes` |

**Currently ingested → `cvm_fii_mensal`:** `complemento` → NAV only; `geral` and `ativo_passivo` → row inserted but no financial fields extracted. Upsert key `(cnpj, period, doc_subtype)`.

**Missing from complemento:** dividend yield, effective return, patrimony return, amortization %, quotaholder breakdown, cotas emitidas, valor ativo

**Missing from ativo_passivo:** real estate breakdown, CRI/LCI holdings, `Rendimentos_Distribuir`

---

### 1.6 SECURIT — Securitizadoras: CRA / CRI / OTS (~R$4tn outstanding)

Each yearly ZIP contains **8 CSVs**. The pipeline reads only one (by accident via first-alphabetical fallback).

| CSV | Granularity | Key content |
|---|---|---|
| `ativo_passivo` | Certificate | Total assets (`Ativo`), credits (current/overdue/non-performing), cash, derivatives, `Valor_Atualizado_Emissao`, `Reducao_Valor_Emissao` |
| **`classe`** | **Series** | Per series: `Classe` (Sênior/Subordinada), `Numero_Serie`, `Codigo_CETIP`, `Codigo_ISIN`, `Data_Vencimento`, `Situacao` (Adimplente/etc), `Valor_Total_Integralizado`, `Taxa_Juros`, `Quantidade_Certificados`, `Valor_Certificados`, `Rendimentos`, `Amortizacoes`, `Rentabilidade`, `Classificacao_Risco_Atual`, `Indice_Subordinacao_Minimo` |
| **`fluxo_caixa`** | Certificate | Monthly cash flows: `Recebimentos_Direitos_Creditorios`, `Pagamentos_Classe_Senior` (principal + juros), `Pagamentos_Classe_Subordinada_Mezanino` (principal + juros), `Pagamentos_Classe_Subordinada_Junior` (principal + juros), `Variacao_Liquida_Caixa` |
| `geral` | Certificate | Emissora, trustee, custodian, collateral type, `Numero_Emissao`, `Quantidade_Series`, revolving flag, `Patrimonio_Liquido_Emissao`, `Desempenho_Emissao` |
| `cedente_devedor` | Certificate | Cedente/devedor concentration: CNPJ + % share per counterparty |
| `direitos_creditorios` | Certificate | Credits receivable by type (production/commercialization/etc), delinquency (`Parcelas_Atraso`), concentration % |
| `desembolso` | Certificate | Disbursements by maturity bucket (30/60/90/120/150/180/360/360+ days) — investor payments schedule |
| `derivativos` | Certificate | Derivative positions by type (term/futures/options/swap) |

**Bug:** `csv_name_pattern = "inf_mensal_cra_{year}.csv"` never matches any file. Fallback picks `ativo_passivo` alphabetically — works now, breaks silently if CVM renames files.

**Currently ingested → `cvm_securit_mensal`:** `ativo_passivo` only — `Valor_Atualizado_Emissao`, `Ativo`, `Data_Referencia`. Upsert key `(instrument_type, period_year, cnpj_securit, dt_emissao, dt_vencto, vl_emissao)`.

**Missing:** per-series status, credit rating, yield (`classe`); tranche-level cash flows (`fluxo_caixa`); cedente concentration; disbursement schedule

---

## Part 2 — Accountability Rules

SQL checks the pipeline must support. Each maps to a schedulable query.

### 2.1 FI — Industry Flow Health (monthly)
```sql
SELECT DATE_TRUNC('month', dt_comptc) AS month,
       SUM(vl_patrim_liq) / 1e12 AS pl_tn,
       (SUM(captc_dia) - SUM(resg_dia)) / 1e9 AS net_flow_bn
FROM cvm_fi_diario
GROUP BY 1 ORDER BY 1 DESC LIMIT 12;
-- Flag: net_flow_bn < -50 for 3+ consecutive months = industry stress
```

### 2.2 FIDC — Industry Delinquency Trend
```sql
SELECT period,
       COUNT(DISTINCT cnpj) AS funds,
       ROUND(SUM(vl_inadimpl) / NULLIF(SUM(vl_patrim_liq), 0) * 100, 2) AS delinquency_pct
FROM cvm_fidc_mensal
GROUP BY period ORDER BY period DESC LIMIT 24;
-- Flag: delinquency_pct > 15% = elevated credit stress
```

### 2.3 FIDC — Tranche Underperformance *(requires tab_X_6)*
```sql
SELECT cnpj, period, classe_serie,
       pr_desemp_esperado, pr_desemp_real,
       pr_desemp_real - pr_desemp_esperado AS gap_pct
FROM cvm_fidc_tranche
WHERE pr_desemp_real < pr_desemp_esperado
  AND period >= CURRENT_DATE - INTERVAL '3 months'
ORDER BY gap_pct ASC LIMIT 20;
-- Flag: negative gap on senior tranche for 2+ months = structural underperformance
```

### 2.4 FIDC — Delinquency Aging (long-tail concentration) *(requires tab_VI)*
```sql
SELECT cnpj, period,
       (vl_inad_720 + vl_inad_1080 + vl_inad_maior_1080) AS long_tail,
       vl_total_inad,
       ROUND(100.0 * (vl_inad_720 + vl_inad_1080 + vl_inad_maior_1080)
             / NULLIF(vl_total_inad, 0), 1) AS pct_long_tail
FROM cvm_fidc_aging
WHERE period = (SELECT MAX(period) FROM cvm_fidc_aging)
  AND vl_total_inad > 1e6
ORDER BY pct_long_tail DESC LIMIT 20;
-- Flag: pct_long_tail > 50% = receivables likely unrecoverable
```

### 2.5 FIDC — Portfolio Sector Concentration *(requires tab_II)*
```sql
SELECT cnpj, period,
       ROUND(100.0 * TAB_II_F_VL_FINANC / NULLIF(TAB_II_VL_CARTEIRA, 0), 1) AS pct_financ,
       ROUND(100.0 * TAB_II_E_VL_AGRONEG / NULLIF(TAB_II_VL_CARTEIRA, 0), 1) AS pct_agro
FROM cvm_fidc_portfolio
WHERE period = (SELECT MAX(period) FROM cvm_fidc_portfolio)
ORDER BY pct_financ DESC;
```

### 2.6 SECURIT — Distressed Series *(requires classe CSV)*
```sql
SELECT cnpj_securit, codigo_identificacao, classe, numero_serie,
       data_vencimento, situacao, valor_total_integralizado, rentabilidade,
       classificacao_risco_atual
FROM cvm_securit_serie
WHERE data_referencia = (SELECT MAX(data_referencia) FROM cvm_securit_serie)
  AND situacao != 'Adimplente'
  AND data_vencimento > CURRENT_DATE
ORDER BY valor_total_integralizado DESC;
-- Flag: any live series not "Adimplente"
```

### 2.7 SECURIT — Cash Burn (senior paid from reserves) *(requires fluxo_caixa)*
```sql
SELECT cnpj_securit, codigo_identificacao, data_referencia,
       recebimentos_direitos_creditorios,
       pagamentos_classe_senior,
       pagamentos_classe_senior - recebimentos_direitos_creditorios AS cash_burn
FROM cvm_securit_fluxo
WHERE data_referencia >= CURRENT_DATE - INTERVAL '3 months'
  AND pagamentos_classe_senior > recebimentos_direitos_creditorios * 1.1
ORDER BY cash_burn DESC LIMIT 20;
-- Flag: senior paid > 110% of new receivables = reserve drawdown
```

### 2.8 SECURIT — Subordination Breach *(requires classe CSV)*
```sql
SELECT cnpj_securit, codigo_identificacao, classe, numero_serie,
       indice_subordinacao_minimo,
       -- subordination ratio = subordinada value / total issuance
       -- requires joining ativo_passivo for total Ativo
       classificacao_risco_atual
FROM cvm_securit_serie
WHERE data_referencia = (SELECT MAX(data_referencia) FROM cvm_securit_serie)
  AND classe ILIKE '%senior%'
  AND indice_subordinacao_minimo IS NOT NULL;
```

### 2.9 FII — Dividend Yield Outliers
```sql
WITH stats AS (
    SELECT period,
           PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY pct_dividend_yield_mes) AS p50,
           STDDEV(pct_dividend_yield_mes) AS sigma
    FROM cvm_fii_mensal
    WHERE doc_subtype = 'complemento' AND pct_dividend_yield_mes IS NOT NULL
      AND period = (SELECT MAX(period) FROM cvm_fii_mensal WHERE doc_subtype = 'complemento')
    GROUP BY period
)
SELECT f.cnpj, f.pct_dividend_yield_mes,
       ROUND((f.pct_dividend_yield_mes - s.p50) / NULLIF(s.sigma, 0), 2) AS z_score
FROM cvm_fii_mensal f JOIN stats s USING (period)
WHERE f.doc_subtype = 'complemento'
  AND ABS((f.pct_dividend_yield_mes - s.p50) / NULLIF(s.sigma, 0)) > 2
ORDER BY z_score;
-- Flag: z < -2 (suspiciously low) or z > 2 (suspiciously high)
```

### 2.10 FII — Income vs NAV Ratio *(requires ativo_passivo)*
```sql
SELECT f.cnpj, f.period,
       ap.rendimentos_distribuir,
       c.vl_patrim_liq,
       ROUND(100.0 * ap.rendimentos_distribuir / NULLIF(c.vl_patrim_liq, 0), 2) AS income_yield_pct
FROM cvm_fii_mensal ap
JOIN cvm_fii_mensal c USING (cnpj, period)
WHERE ap.doc_subtype = 'ativo_passivo'
  AND c.doc_subtype = 'complemento'
  AND c.period = (SELECT MAX(period) FROM cvm_fii_mensal WHERE doc_subtype = 'complemento')
ORDER BY income_yield_pct DESC;
```

---

## Part 3 — Execution Plan (Run Non-Stop to Completion)

### Phase 0 — Bug Fixes (1 hour, no schema changes)

**0.1** Fix SECURIT `csv_name_pattern` in `src/fetchers/cvm_config.py`:
```python
# cra_mensal, cri_mensal, ots_mensal — change from generic to explicit:
"csv_name_pattern": "inf_mensal_cra_ativo_passivo_{year}.csv"
"csv_name_pattern": "inf_mensal_cri_ativo_passivo_{year}.csv"
"csv_name_pattern": "inf_mensal_ots_ativo_passivo_{year}.csv"
```

**0.2** Add missing FII complemento fields to `ingest_fii_mensal` in `src/pipeline/cvm_pipeline.py`:
```python
# Add to complemento record:
"nr_cotst":                _find_field(row, "Total_Numero_Cotistas"),
"vl_ativo":                _find_field(row, "Valor_Ativo"),
"cotas_emitidas":          _find_field(row, "Cotas_Emitidas"),
"vl_patrimonial_cotas":    _find_field(row, "Valor_Patrimonial_Cotas"),
"pct_rentab_efetiva_mes":  _find_field(row, "Percentual_Rentabilidade_Efetiva_Mes"),
"pct_rentab_patrimonial":  _find_field(row, "Percentual_Rentabilidade_Patrimonial_Mes"),
"pct_dividend_yield_mes":  _find_field(row, "Percentual_Dividend_Yield_Mes"),
"pct_amortizacao_mes":     _find_field(row, "Percentual_Amortizacao_Cotas_Mes"),
```

**0.3** Add `rendimentos_distribuir` from FII `ativo_passivo` rows:
```python
"rendimentos_distribuir": _find_field(row, "Rendimentos_Distribuir"),
```

**0.4** Add columns to `src/store/schema.sql` for `cvm_fii_mensal`:
```sql
ALTER TABLE cvm_fii_mensal
  ADD COLUMN IF NOT EXISTS nr_cotst              INT,
  ADD COLUMN IF NOT EXISTS vl_ativo              NUMERIC(20,6),
  ADD COLUMN IF NOT EXISTS cotas_emitidas        NUMERIC(20,6),
  ADD COLUMN IF NOT EXISTS vl_patrimonial_cotas  NUMERIC(20,6),
  ADD COLUMN IF NOT EXISTS pct_rentab_efetiva_mes     NUMERIC(10,6),
  ADD COLUMN IF NOT EXISTS pct_rentab_patrimonial     NUMERIC(10,6),
  ADD COLUMN IF NOT EXISTS pct_dividend_yield_mes     NUMERIC(10,6),
  ADD COLUMN IF NOT EXISTS pct_amortizacao_mes        NUMERIC(10,6),
  ADD COLUMN IF NOT EXISTS rendimentos_distribuir     NUMERIC(20,6);
```

**0.5** Add test for FII ativo_passivo field extraction to `tests/test_cvm_fetch_parse.py`.

**Validation:** Run `python scripts/run_analysis_local.py` — all Q2 checks still pass.

---

### Phase 1 — FIDC Tranche Tables (half-day)

**1.1** Add three new tables to `src/store/schema.sql`:

```sql
-- Tranche-level quota price, return, and performance per series per month
CREATE TABLE IF NOT EXISTS cvm_fidc_tranche (
    id             BIGSERIAL    PRIMARY KEY,
    cnpj           TEXT         NOT NULL,
    period         DATE         NOT NULL,
    classe_serie   TEXT         NOT NULL,   -- e.g. "Subclasse Sênior Série 1"
    qt_cota        NUMERIC(20,8),
    vl_cota        NUMERIC(20,8),
    vl_rentab_mes  NUMERIC(10,6),           -- monthly return %
    pr_desemp_esperado NUMERIC(10,6),       -- expected performance %
    pr_desemp_real     NUMERIC(10,6),       -- actual performance %
    raw            JSONB,
    fetched_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_fidc_tranche UNIQUE (cnpj, period, classe_serie)
);
CREATE INDEX IF NOT EXISTS idx_fidc_tranche_cnpj   ON cvm_fidc_tranche (cnpj);
CREATE INDEX IF NOT EXISTS idx_fidc_tranche_period ON cvm_fidc_tranche (period DESC);

-- Tranche-level flows: captações / resgates per series per month
CREATE TABLE IF NOT EXISTS cvm_fidc_tranche_flows (
    id             BIGSERIAL    PRIMARY KEY,
    cnpj           TEXT         NOT NULL,
    period         DATE         NOT NULL,
    classe_serie   TEXT         NOT NULL,
    tp_oper        TEXT         NOT NULL,   -- "Captações no Mês" / "Resgates no Mês" / "Resgates Solicitados"
    vl_total       NUMERIC(20,6),
    qt_cota        NUMERIC(20,8),
    fetched_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_fidc_tranche_flows UNIQUE (cnpj, period, classe_serie, tp_oper)
);
CREATE INDEX IF NOT EXISTS idx_fidc_tranche_flows_cnpj   ON cvm_fidc_tranche_flows (cnpj);
CREATE INDEX IF NOT EXISTS idx_fidc_tranche_flows_period ON cvm_fidc_tranche_flows (period DESC);

-- Delinquency aging buckets per fund per month (tab_VI)
CREATE TABLE IF NOT EXISTS cvm_fidc_aging (
    id              BIGSERIAL    PRIMARY KEY,
    cnpj            TEXT         NOT NULL,
    period          DATE         NOT NULL,
    -- Credits without risk: maturity aging
    vl_prazo_30     NUMERIC(20,6),
    vl_prazo_60     NUMERIC(20,6),
    vl_prazo_90     NUMERIC(20,6),
    vl_prazo_120    NUMERIC(20,6),
    vl_prazo_150    NUMERIC(20,6),
    vl_prazo_180    NUMERIC(20,6),
    vl_prazo_360    NUMERIC(20,6),
    vl_prazo_720    NUMERIC(20,6),
    vl_prazo_1080   NUMERIC(20,6),
    vl_prazo_maior_1080 NUMERIC(20,6),
    -- Delinquency buckets (days past due)
    vl_inad_30      NUMERIC(20,6),   -- 1-30 dpd
    vl_inad_60      NUMERIC(20,6),
    vl_inad_90      NUMERIC(20,6),
    vl_inad_120     NUMERIC(20,6),
    vl_inad_150     NUMERIC(20,6),
    vl_inad_180     NUMERIC(20,6),
    vl_inad_360     NUMERIC(20,6),
    vl_inad_720     NUMERIC(20,6),
    vl_inad_1080    NUMERIC(20,6),
    vl_inad_maior_1080 NUMERIC(20,6),   -- 1080+ dpd
    vl_total_inad   NUMERIC(20,6),   -- sum for convenience
    fetched_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_fidc_aging UNIQUE (cnpj, period)
);
CREATE INDEX IF NOT EXISTS idx_fidc_aging_cnpj   ON cvm_fidc_aging (cnpj);
CREATE INDEX IF NOT EXISTS idx_fidc_aging_period ON cvm_fidc_aging (period DESC);
```

**1.2** Add `ingest_fidc_tranche` and `ingest_fidc_aging` methods to `CVMIngestor` in `src/pipeline/cvm_pipeline.py`.

Fetcher strategy: for a given `(year, month)`, fetch the FIDC ZIP once, then extract multiple CSVs. The current `CVMFetcher.fetch()` API only returns one CSV. Options:
- **Option A (minimal change):** Add new doc_types `fidc_tab_X_2`, `fidc_tab_X_3`, `fidc_tab_X_4`, `fidc_tab_X_6`, `fidc_tab_VI` to `DatasetConfig.FIDC_DATASETS` — each targeting a different CSV inside the same ZIP. The ZIP is small (~2MB) so re-downloading is acceptable. Implement in `ingest_fidc_mensal` with separate passes.
- **Option B (cleaner):** Extend `CVMFetcher.fetch()` to accept a list of `csv_name_pattern` values and return one concatenated result per CSV. Avoids re-downloading the same ZIP.

Recommend **Option A** for minimal code risk. Add config entries:

```python
FIDC_DATASETS = {
    "mensal":       {"csv_name_pattern": "inf_mensal_fidc_tab_IV_{year}{month:02d}.csv", ...},
    "mensal_tab_VI": {"csv_name_pattern": "inf_mensal_fidc_tab_VI_{year}{month:02d}.csv",
                      "url_pattern": same as mensal, ...},
    "mensal_tab_X2": {"csv_name_pattern": "inf_mensal_fidc_tab_X_2_{year}{month:02d}.csv", ...},
    "mensal_tab_X3": {"csv_name_pattern": "inf_mensal_fidc_tab_X_3_{year}{month:02d}.csv", ...},
    "mensal_tab_X4": {"csv_name_pattern": "inf_mensal_fidc_tab_X_4_{year}{month:02d}.csv", ...},
    "mensal_tab_X6": {"csv_name_pattern": "inf_mensal_fidc_tab_X_6_{year}{month:02d}.csv", ...},
}
```

**1.3** Add tranche and aging ingestion to the `backfill()` orchestration.

**1.4** Update `scripts/seed_local_db.py` to seed new tables.

**1.5** Add tests in `tests/test_cvm_fetch_parse.py` for tranche and aging ingestion.

**Validation:**
```sql
-- After seeding 2025-03:
SELECT COUNT(*) FROM cvm_fidc_tranche;          -- expect > 2000 rows
SELECT COUNT(*) FROM cvm_fidc_tranche_flows;    -- expect > 6000 rows
SELECT COUNT(*) FROM cvm_fidc_aging;            -- expect > 1000 rows
SELECT COUNT(DISTINCT classe_serie) FROM cvm_fidc_tranche WHERE cnpj = '05754060000113';
-- expect 2 (Sênior Série 1 + Subordinada Subordinada 1)
```

---

### Phase 2 — SECURIT Series + Cash Flow Tables (half-day)

**2.1** Add two new tables to `src/store/schema.sql`:

```sql
-- Series-level data per CRA/CRI certificate (from classe CSV)
CREATE TABLE IF NOT EXISTS cvm_securit_serie (
    id                          BIGSERIAL    PRIMARY KEY,
    instrument_type             TEXT         NOT NULL,  -- cra_mensal | cri_mensal | ots_mensal
    cnpj_securit                TEXT,
    codigo_identificacao        TEXT         NOT NULL,
    data_referencia             DATE         NOT NULL,
    classe                      TEXT,                   -- Sênior | Subordinada
    numero_serie                INT,
    tipo_oferta                 TEXT,
    codigo_cetip                TEXT,
    codigo_isin                 TEXT,
    data_vencimento             DATE,
    situacao                    TEXT,                   -- Adimplente | Inadimplente | Liquidado | ...
    valor_total_integralizado   NUMERIC(20,6),
    taxa_juros                  TEXT,                   -- e.g. "98% DI", "5.59% a.a. + IPCA"
    pagamento_periodicidade     TEXT,
    quantidade_certificados     NUMERIC(20,0),
    valor_certificados          NUMERIC(20,6),
    rendimentos                 NUMERIC(20,6),
    amortizacoes                NUMERIC(20,6),
    rentabilidade               NUMERIC(20,8),
    classificacao_risco_atual   TEXT,                   -- AAAsf(bra) | PIFsf(bra) | etc
    indice_subordinacao_minimo  NUMERIC(10,6),
    fetched_at                  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_securit_serie UNIQUE NULLS NOT DISTINCT
        (instrument_type, cnpj_securit, codigo_identificacao, data_referencia, numero_serie)
);
CREATE INDEX IF NOT EXISTS idx_securit_serie_cnpj      ON cvm_securit_serie (cnpj_securit);
CREATE INDEX IF NOT EXISTS idx_securit_serie_isin      ON cvm_securit_serie (codigo_isin);
CREATE INDEX IF NOT EXISTS idx_securit_serie_situacao  ON cvm_securit_serie (situacao, data_referencia DESC);

-- Monthly cash flows by tranche per certificate (from fluxo_caixa CSV)
CREATE TABLE IF NOT EXISTS cvm_securit_fluxo (
    id                                  BIGSERIAL    PRIMARY KEY,
    instrument_type                     TEXT         NOT NULL,
    cnpj_securit                        TEXT,
    codigo_identificacao                TEXT         NOT NULL,
    data_referencia                     DATE         NOT NULL,
    recebimentos_direitos_creditorios   NUMERIC(20,6),
    pagamentos_despesas                 NUMERIC(20,6),
    pagamentos_classe_senior            NUMERIC(20,6),
    pagamentos_senior_principal         NUMERIC(20,6),
    pagamentos_senior_juros             NUMERIC(20,6),
    pagamentos_mezanino                 NUMERIC(20,6),
    pagamentos_mezanino_principal       NUMERIC(20,6),
    pagamentos_mezanino_juros           NUMERIC(20,6),
    pagamentos_junior                   NUMERIC(20,6),
    pagamentos_junior_principal         NUMERIC(20,6),
    pagamentos_junior_juros             NUMERIC(20,6),
    variacao_liquida_caixa              NUMERIC(20,6),
    fetched_at                          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_securit_fluxo UNIQUE NULLS NOT DISTINCT
        (instrument_type, cnpj_securit, codigo_identificacao, data_referencia)
);
CREATE INDEX IF NOT EXISTS idx_securit_fluxo_cnpj   ON cvm_securit_fluxo (cnpj_securit);
CREATE INDEX IF NOT EXISTS idx_securit_fluxo_date   ON cvm_securit_fluxo (data_referencia DESC);
```

**2.2** Add doc_type entries to `DatasetConfig.SECURIT_DATASETS`:
```python
"cra_classe":     {"url_pattern": same as cra_mensal, "csv_name_pattern": "inf_mensal_cra_classe_{year}.csv"},
"cra_fluxo":      {"url_pattern": same as cra_mensal, "csv_name_pattern": "inf_mensal_cra_fluxo_caixa_{year}.csv"},
# repeat for cri_classe, cri_fluxo, ots_classe, ots_fluxo
```

**2.3** Add `ingest_securit_serie` and `ingest_securit_fluxo` methods to `CVMIngestor`.

**2.4** Update `backfill()` to include new SECURIT doc types.

**Validation:**
```sql
SELECT COUNT(*), COUNT(DISTINCT situacao) FROM cvm_securit_serie WHERE data_referencia = '2024-12-01';
SELECT situacao, COUNT(*) FROM cvm_securit_serie
WHERE data_referencia = '2024-12-01' GROUP BY 1;
-- Expect: "Adimplente" as dominant, with some "Liquidado" and ideally few others
```

---

### Phase 3 — Supabase Backfill

Run after phases 0–2 are deployed. Order matters — largest tables last.

```bash
# 1. FIDC (includes new tranche tables)
python -m src.pipeline.cvm_pipeline backfill --entity fidc --start 2019

# 2. FII (complemento now includes yield/return columns)
python -m src.pipeline.cvm_pipeline backfill --entity fii --start 2019

# 3. SECURIT (includes new serie + fluxo tables)
python -m src.pipeline.cvm_pipeline backfill --entity securit --start 2021

# 4. FIP (unchanged, idempotent to re-run)
python -m src.pipeline.cvm_pipeline backfill --entity fip --start 2010

# 5. FI inf_diario (largest — run as separate overnight job)
python -m src.pipeline.cvm_pipeline backfill --entity fi --start 2019

# SECURIT duplicate audit post-backfill:
# The upsert key now includes populated dt_emissao/vl_emissao (was null before).
# Run verify_pipeline.py and check row counts vs expected before and after.
```

**Post-backfill verification:**
```bash
python scripts/verify_pipeline.py
# Check: all null rates < 5%, business metrics in expected ranges
```

---

### Phase 4 — BACEN Macro Integration

Add `src/pipeline/bacen_pipeline.py` to ingest:

| Series | Code | Why needed |
|---|---|---|
| SELIC overnight | 11 | Benchmark for all fixed income; yield-adjusted FI/FIDC returns |
| CDI rate | 12 | Most FIDC sênior targets CDI + spread |
| IPCA | 433 | FII dividends and CRA/CRI often IPCA-linked |
| IGP-M | 189 | Some FII rent escalation |
| USD/BRL PTAX | via `/olinda/servico/PTAX` | FIP with foreign exposure |
| Focus median IPCA | via `/expectativas/mercado` | Forward yield curve |

All land in existing `bacen_sgs`, `bacen_ptax`, `bacen_expectativas` tables (already in schema.sql).

---

### Phase 5 — Schema Maintenance

- **Jan 2027:** Add `cvm_fi_diario_2027` partition to `schema.sql` and apply to Supabase.
- **2025-05:** Add FIAGRO to seed and backfill once CVM publishes first data.
- **Annually:** Verify FIP doc_type (`inf_quadrimestral` continues past 2024).

---

## Part 4 — Pre-Run Validation (Gate Before Every Backfill)

### Step 1 — Smoke seed one period
```bash
python scripts/seed_local_db.py --skip-fi
```

### Step 2 — Field null-rate check (must all pass before proceeding)
```bash
python scripts/run_analysis_local.py
```

| Check | Threshold |
|---|---|
| FIDC `vl_patrim_liq` (tab_IV) | < 1% null |
| FIDC tranche `vl_rentab_mes` | < 1% null |
| FIDC aging `vl_inad_30` | < 5% null |
| FII `vl_patrim_liq` (complemento) | < 1% null |
| FII `pct_dividend_yield_mes` | < 5% null |
| SECURIT `vl_emissao` (ativo_passivo) | < 5% null |
| SECURIT serie `situacao` | < 1% null |

### Step 3 — Business plausibility

| Entity | Metric | Expected range |
|---|---|---|
| FI (latest month) | Industry PL | R$7–10tn |
| FIDC (latest month) | Industry PL | R$600–800bn |
| FIDC (latest month) | Delinquency rate | 5–20% |
| FII complemento | Industry PL | R$300–500bn |
| FIP (2024) | Industry PL | R$700bn–1.1tn |
| SECURIT CRA (2024) | Total assets | R$1.2–2tn |
| SECURIT CRI (2024) | Total assets | R$2–3tn |
| SECURIT senior series | `situacao = Adimplente` rate | > 90% |

---

## Part 5 — Known Data Limitations

| Limitation | Impact |
|---|---|
| FIDC tab_V (credits WITH risk aging) vs tab_VI (WITHOUT risk) — pipeline plan uses tab_VI | Some FIDCs structure as pass-through (sem risco); for recourse FIDCs, tab_V is the right aging table. Consider ingesting both and labeling. |
| SECURIT `Taxa_Juros` is free text ("98% DI", "IPCA + 5%") | Cannot filter by index programmatically without parsing. Needs NLP or regex normalization. |
| FII `ativo_passivo` has no CNPJ field — uses `CNPJ_Fundo_Classe` like geral | Already handled by `_find_cnpj_field`. |
| CVM data has a 1–3 week lag | Accountability queries reflect prior month. Not suitable for real-time monitoring. |
| FIDC tabs X_2/X_3/X_4/X_6 use `CNPJ_FUNDO` (without `_CLASSE`) | Some newer multi-class FIDCs report at class level. Join to fund-level data via CNPJ prefix or `CNPJ_FUNDO_CLASSE` from tab_I. |
| ANBIMA cross-check URLs have changed (404) | Independent validation of industry totals must use CVM data only until ANBIMA updates its open data links. |
| `cvm_securit_mensal` upsert key changes post-fix | Re-ingesting 2019–2024 CRA/CRI/OTS after Phase 0 may insert duplicates. Solution: truncate + re-insert for each `(instrument_type, period_year)` pair before backfill. |
