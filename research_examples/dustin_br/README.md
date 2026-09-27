# DUSTIN-BR research dataset

One point-in-time row per B3 session for a Brazilian rates-regime model inspired
by HSBC's DUSTIN framework. This builds **features only**: no model, no target.
Sources, coverage and every availability rule:
[`docs/research/dustin_br_data_sources.md`](../../docs/research/dustin_br_data_sources.md).

```bash
# reads with POSTGRES_URL through src.store.pg_client, read only
python -m research_examples.dustin_br.build_dataset --start 2008-01-02 --end 2026-09-25 --out dustin_br.csv
```

It needs the backfills first (`market_backfill.yml`, and the SGS load for IC-Br).
With no `b3_reference_rate` rows it exits 1 and says so. A column with no value
in the window is named at the end of the run, not silently dropped.

## The rule

A value is on row `t` only if it was public by the end of B3 session `t`:

| Source                                | Public                                     |
| ------------------------------------- | ------------------------------------------ |
| DI curves (B3 `PRE`, `DOC`), DI1      | same evening                               |
| USDBRL (PTAX), SELIC target, UST, VIX | same day                                   |
| Brent (EIA)                           | the day after the first Wednesday after it |
| IPCA, IPCA 12m, IC-Br (monthly)       | the 15th of the next month (assumption)    |
| Focus 12-month IPCA                   | the Tuesday after the survey day's week    |

Each source keeps its own calendar. Momentum and realised volatility are
computed there, then joined to the B3 grid on the availability date. A value
older than its staleness limit (5 sessions for daily series, 10 for Brent and
Focus, 45 for monthly) is NULL, never carried. Every level column has a
`<name>__obs_date` companion that says which observation was used.
`tests/test_dustin_br_builder.py` checks the property directly: rows up to `T`
are identical whether or not anything published after `T` exists.

## Columns

| Column                                             | Meaning                                                                             |
| -------------------------------------------------- | ----------------------------------------------------------------------------------- |
| `di_1y` `di_2y` `di_3y` `di_5y` `di_10y`           | DI rate at 252/504/756/1260/2520 business days, % a.a., flat-forward on `PRE`       |
| `di_2s5s`, `di_curvature`                          | `di_5y - di_2y`; `2·di_2y - di_1y - di_5y` (pp)                                     |
| `usdbrl`                                           | PTAX (SGS 1), BRL per USD                                                           |
| `ust_2y` `ust_5y` `ust_10y` `ust_30y`, `ust_2s10s` | Treasury par yields, %                                                              |
| `vix`                                              | Cboe close                                                                          |
| `rates_vol_proxy`                                  | 21-day realised vol of UST 10Y changes, bp/yr. **A substitute for MOVE, not MOVE**  |
| `brazil_sovereign_risk_proxy`                      | B3 `DOC` 1Y minus UST 1Y, effective annual, bp. **Onshore dollar premium, not CDS** |
| `brent`                                            | EIA Brent spot FOB, USD/bbl                                                         |
| `commodity_index`                                  | BCB IC-Br (monthly, BRL)                                                            |
| `ipca`, `ipca_12m`, `selic`, `focus_ipca_12m`      | as published by BCB / IBGE                                                          |
| `*_mom_{5,21,63}d`                                 | change (rates) or log change (prices) over k observations                           |
| `*_rv_{21,63}d`                                    | realised vol of daily changes, annualised (√252)                                    |
| `corr_*_{21,63}d`                                  | correlation of daily changes on common observation dates                            |
| `di1_open_interest`, `di1_contracts`               | DI1 totals per session; **from 2018-01-02 only**                                    |

Known limits: the `DOC` convention (linear, 360-day) is an assumption to verify
before modelling; the monthly publication rule is conservative, not a release
calendar; SILO keeps no Focus vintages; realised vol lags implied vol at regime
turns.
