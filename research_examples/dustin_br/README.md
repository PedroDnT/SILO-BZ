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

Without a local `POSTGRES_URL`, dispatch **Research Build**
(`.github/workflows/research_build.yml`; empty `end` means today). It runs
`quality.py`, which writes the same `dustin_br.csv` plus `coverage_by_year.csv`
and `quality.md` to the run's artifact. The report is also the run's summary:
sessions, B3 sessions a source lacks, staleness-nulled cells, how often B3's
extrapolated tail leaves `di_10y` NULL, coverage by year, and the
no-look-ahead check re-run on the real inputs (a changed cell fails the run).
Every query runs with `default_transaction_read_only = on`.

## The rule

A value is on row `t` only if it was public by the end of B3 session `t`:

| Source                                  | Public                                                                                                        |
| --------------------------------------- | ------------------------------------------------------------------------------------------------------------- |
| DI curves (B3 `PRE`, `DOC`, `DPL`), DI1 | same evening                                                                                                  |
| USDBRL (PTAX), SELIC target, UST        | same day                                                                                                      |
| OFR FSI                                 | three weekdays after its date (OFR publishes two business days later); the first release where OFR revised it |
| Brent (EIA)                             | the day after the first Wednesday after it                                                                    |
| IPCA, IPCA 12m, IC-Br (monthly)         | the 15th of the next month (assumption)                                                                       |
| Focus 12-month IPCA                     | the Tuesday after the survey day's week                                                                       |

Each source keeps its own calendar. Momentum and realised volatility are
computed there, then joined to the B3 grid on the availability date. A value
older than its staleness limit (5 sessions for daily series, 10 for Brent and
Focus, 45 for monthly) is NULL, never carried. Every level column has a
`<name>__obs_date` companion that says which observation was used.
`tests/test_dustin_br_builder.py` checks the property directly: rows up to `T`
are identical whether or not anything published after `T` exists.

## Columns

| Column                                             | Meaning                                                                                                                                             |
| -------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| `di_1y` `di_2y` `di_3y` `di_5y` `di_10y`           | DI rate at 252/504/756/1260/2520 business days, % a.a., flat-forward on `PRE`; NULL past `di_anchor_du`                                             |
| `di_anchor_du`                                     | business days where B3's extrapolation of `PRE` begins (past the DI1 contracts); `di_10y` is often NULL early on                                    |
| `breakeven_1y` `breakeven_2y` `breakeven_5y`       | implied IPCA, (1 + `PRE`) / (1 + `DPL`) − 1, % a.a.: B3's definition. Carries a risk premium. OPTIONAL                                              |
| `di_2s5s`, `di_curvature`                          | `di_5y - di_2y`; `2·di_2y - di_1y - di_5y` (pp)                                                                                                     |
| `usdbrl`                                           | PTAX (SGS 1), BRL per USD                                                                                                                           |
| `ust_2y` `ust_5y` `ust_10y` `ust_30y`, `ust_2s10s` | Treasury par yields, %                                                                                                                              |
| `ofr_fsi`, `ofr_fsi_volatility`                    | OFR Financial Stress Index and its Volatility category, first release. **Replaces VIX**, which Cboe licenses                                        |
| `rates_vol_proxy`                                  | 21-day realised vol of UST 10Y changes, bp/yr. **A substitute for MOVE, not MOVE**                                                                  |
| `brazil_sovereign_risk_proxy`                      | B3 `DOC` 1Y minus UST 1Y, effective annual, bp. **Onshore dollar premium, not CDS**. OPTIONAL: follows EMBI+ in 1- to 3-month changes, not in level |
| `brent`                                            | EIA Brent spot FOB, USD/bbl                                                                                                                         |
| `commodity_index`                                  | BCB IC-Br (monthly, BRL)                                                                                                                            |
| `ipca`, `ipca_12m`, `selic`, `focus_ipca_12m`      | as published by BCB / IBGE                                                                                                                          |
| `*_mom_{5,21,63}d`                                 | change (rates) or log change (prices) over k observations                                                                                           |
| `*_rv_{21,63}d`                                    | realised vol of daily changes, annualised (√252)                                                                                                    |
| `corr_*_{21,63}d`                                  | correlation of daily changes on common observation dates (`corr_di2y_ofr_vol_*` against OFR's Volatility category)                                  |
| `di1_open_interest`, `di1_contracts`               | DI1 totals per session; **from 2018-01-02 only**; open interest is NULL on 2018-05-10 and 2025-09-11, where B3 omits it for held contracts          |

Known limits: the monthly publication rule is conservative, not a release
calendar; SILO keeps no Focus vintages; realised vol lags implied vol at
regime turns; the OFR FSI arrives two business days late and is a composite,
smoother than VIX; the sovereign proxy's level drifts for years with onshore
dollar conditions, so read it in changes. `DOC` is linear on 360 days (B3's
Manual de Curvas v21 §4.5), and the builder converts it that way.

## Stage 4: the regime model

`model.py` asks whether the matrix predicts the curve over the next 21
sessions: does the 2y DI fall (bull) or rise (bear), and does the 2s5s slope
widen (steepener) or narrow (flattener)? It scores three targets: the four-way
regime, the level alone and the slope alone. Each gets an L2 multinomial
logistic model on 24 CORE features, walk-forward from 2012 with a 21-session
purge, against two baselines on the same sessions: each class's share so far
(climatology), and each class's share after the class that just ended
(Markov). Research Build runs it after every build (`model_report.md`,
`model_predictions_<target>.csv`).

```bash
python -m research_examples.dustin_br.model --matrix out/dustin_br.csv --out-dir out
```

Results on run 36444747902's matrix (3,633 labelled sessions out of sample,
2012 to 2026), for the model with C chosen in each training window:

| Target | Log loss: model / climatology / Markov | Hit rate: model / climatology / Markov |
| ------ | -------------------------------------- | -------------------------------------- |
| Regime | 1.387 / 1.399 / 1.400                  | 29.0% / 20.2% / 26.1%                  |
| Level  | 0.706 / 0.703 / 0.698                  | 51.8% / 47.7% / 50.0%                  |
| Slope  | 0.701 / 0.697 / 0.700                  | 56.0% / 50.6% / 47.9%                  |

- **No edge in probability.** For every target the log-loss gain over each
  baseline has a 90% interval that spans zero (regime +0.012, -0.014 to
  +0.035, against climatology). A coin scores 1.386 on four classes and
  0.693 on two.
- **C set in advance overfits.** The first variant, C = 0.1, scores 1.855 on
  the regime, worse than both baselines (in sample 1.24): 4,600 labels that
  overlap 20 of 21 sessions hold about 220 independent outcomes. The variant
  above was added after that result; it picks C on each training window's
  last two years and never looks at a test year.
- **The level is a coin.** The 2y rate's direction is not called better than
  either baseline.
- **The slope is a lead, not a finding.** Its direction is called right 56.0%
  of the time, but not distinguishably better than climatology (+5.4, -0.4 to
  +10.6), and its probabilities are overconfident (74% predicted, 60%
  happened). It beats Markov by 8.0 points (+1.9 to +14.3) only because
  Markov is a coin for the slope: after a flattener the next 21 sessions
  flatten 50.9% of the time, after a steepener 51.2%. With 12 comparisons at
  a one-sided 5% level, about one "better" can appear by chance. The level
  and slope targets were fixed after the regime result and before either was
  scored.

Credit: the stress index is the Office of Financial Research's OFR Financial
Stress Index (OFR asks for credit when its work is reproduced).
