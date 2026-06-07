# ETF separation, performance analytics, and dashboard — notes & data gaps

This documents the analytical + dashboard work that evaluates **ETFs separately**
from funds and adds **per-asset-class performance** (horizontal/vertical), plus the
live-data gaps found while building it. Nothing here fabricates data — gaps are
recorded as gaps.

## What was added

- **ETF carve-out** — `src/store/analytical/01_dim_fund.sql` and
  `04_fact_fund_monthly.sql` now exclude ETF CNPJs (`NOT EXISTS … cvm_etf_registry`)
  from the fund universe, so ETFs aren't double-counted inside the FI buckets.
  `dim_fund_category` and everything downstream inherit the carve-out.
- **`16_etf_analysis.sql`** — ETF-only RPCs over `etf_daily` + `anbima_etf_class_monthly`:
  `etf_performance_series`, `etf_performance_ranking`, `etf_class_performance`.
- **`17_performance_analysis.sql`** — fund RPCs over `fact_fund_monthly` ⋈
  `dim_fund_category`: `fund_performance_series` (horizontal) and
  `fund_performance_ranking` (vertical, ranked within asset class). Return basis is
  per class and is returned as a column — FI `quota_return`, FII `dividend_yield`
  (compounded), FIDC/FIAGRO/FIP `pl_growth` (growth, not a clean return).
- **Dashboard** — `dashboard/pages/performance.md` (fund performance),
  `dashboard/pages/etf.md` (ETF universe), and nav links from `index.md`.

## Applying to prod

These are part of the analytical layer, applied **after** data exists:

```bash
POSTGRES_URL=… bash scripts/apply_analytical.sh   # idempotent; CREATE OR REPLACE
```

(or let the daily CI run it). The functions were validated read-only against live
data — the FII compounded-yield ranking and the ETF ranking logic both return
correct results — but the objects are **not yet created on prod** (apply pending).

## Live-data gaps found (2026-06)

| Gap | Detail | Unblocks |
| --- | --- | --- |
| **`etf_daily` is empty** | The 187 registry ETFs' fund-level CNPJs have **zero** overlap with 2026 `cvm_fi_diario` (CVM-175 keys the daily file on share-**class** CNPJs). So ETF price/NAV/return/AUM/flow series can't come from CVM today. | Fix registry↔class-CNPJ linkage, or wire an external ETF price feed (etfsbrasil.com / FMP), or ingest ANBIMA ETF class series. |
| **ETF registry quant fields sparse** | `vl_patrim_liq` populated for only 8/187; `taxa_adm` 0/187. Identity (provider/segment/index) is complete for ~all. | cad_fi enrichment refresh / external feed. |
| **`anbima_etf_class_monthly` empty** | Table exists; the ANBIMA ETF ingest hasn't run on this DB. | Run the ANBIMA ETF pipeline. |
| **Fund history is 2026-only** | FI daily, FII (Q1), FIP present; FIDC/FIAGRO and `cvm_fund_registry` are empty. With the registry empty, FI funds fall into the coarse `Other FI` class. | Historical backfill + registry ingest (migration 11 already applied). |

The ETF page is therefore built on the **real registry universe** (provider /
segment / index / status), with price/return/AUM sections explicitly marked
pending a price feed.
