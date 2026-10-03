# Portfolio engine output (schema 1.0)

What `python -m src.portfolio.diagnose <statement> [--client mcp|postgrest|fake] [--out report.json]`
writes: one JSON document. The report writer (Redator and Revisor) builds on it, and
every number in a report must be a key of this document.

```
python -m src.portfolio.diagnose docs/reference/portfolio/statement-template.xlsx --client fake \
    --out tests/fixtures/portfolio/demo_engine_output.json
```

**The schema is stable and append-only within `schema_version` 1.0.** Keys are added, never
renamed, retyped or removed. A breaking change bumps `schema_version`. The fixture
`tests/fixtures/portfolio/demo_engine_output.json` is the engine run on the demo template with
the `FakeClient` and a fixed clock; `tests/test_portfolio_engine.py` regenerates it and compares
byte for byte, so a change to the engine that moves the fixture fails CI until the fixture is
regenerated in the same commit. The fake rows (`fake_silo_rows.json`) are synthetic (shaped on
production measurements of 2026-10-03): the values are not data.

## Conventions

| Convention  | Rule                                                                                                                                                                                                                               |
| ----------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Money       | BRL as a JSON number rounded to 2 decimals (`*_brl`).                                                                                                                                                                              |
| Percentages | A number of percent: `1.65` means 1,65 % (`pct_of_portfolio`, `rate_pct_per_year`, `pct_of_fund_value_with_known_fee`).                                                                                                            |
| Fractions   | `weight_in_line`, `explained_weight`, `unexplained_weight`, `similarity`, `quota_rel_diff`, `quota_on_date` ratios are fractions (0.25 = 25 %). Named `weight`, never `pct`.                                                       |
| Dates       | ISO `YYYY-MM-DD`; timestamps UTC `YYYY-MM-DDTHH:MM:SSZ` (show them in UTC-3 in the report).                                                                                                                                        |
| Null        | Not declared at source or not computed, never zero. A reason sits next to it.                                                                                                                                                      |
| Sections    | Every section starts with `status` (`complete`, `partial`, `unknown`, `not_applicable`), `reason` (Portuguese, why it is not complete) and `errors` (the verbatim error of each refused call: `call_id`, `tool`, `args`, `error`). |
| Sources     | Every number sits beside a `sources` list of `{tool, call_id, args, data_date}`; `call_id` is a row of `provenance`. `tool = "statement"` means the client's own statement (`args.line_no`).                                       |
| Text        | Engine strings are Portuguese and are the wording the report may quote.                                                                                                                                                            |
| Holder      | Never present. `statement.holder` holds the fixed tokens `[TITULAR]`, `[CPF]`, `[CONTA]`.                                                                                                                                          |

## Top level

`schema_version`, `generated_at_utc`, `engine` (`version`, `client`, `params`), `statement`,
`identification`, `fees`, `look_through`, `indexer`, `sector`, `restatements`, `risk_signals`,
`assumptions`, `section_status`, `provenance`.

- `engine.params`: `cda_month` (default: position month - 4), `fee_month` (default: position
  month - 1), `max_depth`, `restatement_months`, `max_diff_docs_per_fund`,
  `sector_lookthrough_top_tickers`. Fixed lags until a `coverage()`-driven default exists.
- `assumptions[]`: `{id, text}`, each a reading the engine could not verify (`fee_units`,
  `weight_in_root`, `position_date`, `valuation`, `direct_tesouro`, `economic_group`,
  `abnormal_movement`). The report should state the ones that touch what it says.
- `section_status`: `{section: {status, reason}}`, for a cover-page summary.
- `provenance[]`: every tool call in order: `call_id`, `tool`, `args`, `requested_at_utc`,
  `row_count` (null on error), `error` (verbatim, null on success). No retry, no trimming.

## `statement`

`holder`, `corretora`, `source_format`, `stated_total_brl`, `sum_of_lines_brl`,
`difference_brl`, `tolerance_brl`, `reconciled` (always true: a statement that does not
reconcile never reaches the engine), `n_lines`, `position_date` (latest of the lines),
`position_dates`, `notes[]`, `positions[]` (`line_no`, `source_row`, `linha_extrato`, `tipo`,
`codigo`, `quantidade`, `preco_unitario`, `valor_brl`, `pct_of_portfolio`, `data_posicao`,
`source`). The valuation of a line is the statement's.

## `identification`

`counts` (`identified`, `ambiguous`, `unknown`) and `lines[]`:

- `status`: `identified`, `ambiguous` (candidates and `reason`) or `unknown` (`reason`).
- `identity`: `kind` (`fund`, `ticker`, `tesouro`), `cnpj`, `name`, `entity_type`, `ticker`,
  `isin`, `asset_class`, `issuer_cnpj` (a share's issuer, from `company_financials`, because
  `lookup` returns `cnpj` null for tickers), `tesouro_title`, `tesouro_maturity`.
- `fund_match`: from `portfolio_resolve`: `candidates[]` (`rank`, `cnpj`, `name`,
  `matched_name`, `matched_period`, `entity_type`, `match_kind`, `similarity`, `quota_on_date`,
  `quota_rel_diff`, `ambiguous`, `reason`), `chosen`, `sources`.
- `ticker_match`: `lookup` row, `reference_quote` (close and date: reference only, never the
  position's value; its date can be after the position date), `issuer`.
- `valuation`: `{value_brl, basis: "statement", note, sources}`. A Tesouro line has no price
  series in SILO: the statement's value is the value.
- `findings[]`: `{kind: "renamed" | "cnpj_conflict", text, ...}`. `renamed` carries the old
  name that matched, its period and the current name.

## `fees`

`month`, `estimate_label` (`estimativa a partir do balancete`), `lines[]`, `totals`.

- A line: `fee_status` (`divulgada`, `estimativa a partir do balancete`, `taxa desconhecida`),
  `reason`, `fund_nav_brl`, `fiscal_reset_suspect`, `adm`, `perf`, `total_per_year_brl`.
- `adm`: `basis`, `rate_pct_per_year`, `per_year_brl` (= position value x rate), and
  `disclosed_source` / `disclosed_as_of` when disclosed. A balancete estimate carries `label`
  and is never shown as the disclosed fee; with `fiscal_reset_suspect` it is dropped
  (`basis = taxa desconhecida`, no number).
- `perf.disclosed`: `rate_as_filed` and `meaning`: a share of the EXCESS return over the
  regulation's benchmark, so `per_year_brl` is always null (position x rate would be wrong).
  `perf.estimate`: balancete estimate, labelled, the only R$ figure for performance.
- `totals`: `adm_disclosed_per_year_brl`, `adm_estimated_per_year_brl`,
  `perf_estimated_per_year_brl`, `total_per_year_brl`, fund value with a known and with an
  unknown fee. The total covers only funds with a known fee; the disclosed and estimated parts
  stay separate.

## `look_through`

`cda_month`, `max_depth`, `lines[]`, `shared_exposure`.

- `lines[]` (one per fund, one tool call each): `status` (`complete`, `no_holdings`, `unknown`),
  `exposures[]` (leaves: `via` path, `depth`, `block`, `asset_kind`, `asset_key`, `asset_name`,
  `isin`, `issuer_cnpj`, `issuer_code`, `tp_aplic`, `tp_titpub`, `indexer_code`, `maturity`,
  `weight_in_line`, `exposure_brl` = position value x `weight_in_root`, `period`, `sources`),
  `fund_nodes[]` (intermediate funds), `explained_weight` and `unexplained_weight` (what no
  ingested CDA block explains: cash, derivatives, blocks 3, 5, 7, 8; negative when liabilities
  and derivatives sum above the fund value; never filled), `n_cycle_rows_skipped`.
  A fund quota with no children is a leaf `fundo_sem_look_through`.
- `shared_exposure`: `economic_group_assessed` (always false) and `note`, `groups[]` with
  `kind` (`mesmo_ativo`: same asset key or ISIN; `mesmo_emissor_raiz_cnpj`: same 8-digit CNPJ
  root; `mesmo_codigo_emissor_b3`: same ISIN characters 3 to 6; `mesmo_fundo_investido`: the
  same fund held by two lines), `label`, `line_nos`, `lines[]` (`exposure_brl` per line,
  `direct`), `total_exposure_brl`. Totals of different kinds describe the same positions: do not
  add them.

## `indexer` and `sector`

Both put the whole portfolio in classes: the classes sum to `portfolio_value_brl`
(`sum_check_brl` is the rounding difference) and `sem classificação` is always the last entry,
even at zero. It also holds the unexplained part of funds, lines the engine could not identify
or open, and values with no rule, each named in `unclassified_breakdown[]` (`reason`,
`value_brl`, `pct_of_portfolio`). `items[]` lists every classified exposure with its rule and
sources. Neither is ever inferred from a name (`never_inferred_from_name`).

- `indexer`: `rules_version`, `rules_sha256`, `rules_file`
  (`src/portfolio/rules/indexer_rules.csv`), `classes[]` (`indexer_class`, `value_brl`,
  `pct_of_portfolio`, `n_items`), `by_position[]`.
- `sector`: `sectors[]` (`sector`, `taxonomy`, ...). Taxonomy `CVM (cia_company.setor)` for
  listed shares (B3's `short_interest.sector` only as a labelled fallback),
  `CVM (cvm_fidc_setor)` for FIDC (tab II lettered codes, parents only). FII
  `segmento_atuacao` and ETF `segment` have no tool in the public contract: `sem classificação`
  with that reason. `lookthrough_ticker_limit`: shares inside funds are resolved for the
  largest N tickers only, the rest says so.

## `restatements`

`window`, `assessment` (the thresholds are parked by the owner), `lines[]` for FIDC and FII
positions: `restatements[]` (`fnet_id`, `previous_fnet_id`, `reference`, `versao`,
`modalidade`, `delivered_at`, `previous_delivered_at`, `lag_days`, `n_fields_changed`,
`diff_status`, `assessment`, `leaves[]`, `n_leaves`, `leaves_complete`). Every leaf (`leaf`,
`field_path`, `old_value`, `new_value`, `old_num`, `new_num`, `delta`, both FNET ids, both
dates, `source_url`) says `reapresentado, não avaliado`: the engine makes no materiality
judgement.

## `risk_signals`

`screens[]` (each tool call with `status` and `n_rows`; `screen_overdue_securit` and
`screen_dormant_trend` are `not_applicable`: no fund CNPJ), `dormant_coverage_note`,
`abnormal_movement` (parked), `lines[]` (`signals[]` with the screen's own row and
`screen` / `params`, `unknown_screens`). A signal is not a verdict, and no signal is not a
health certificate. `screen_dormant_funds` is called twice, pinned
(`p_dormancy = empty_shell`; `p_min_nav = 1000000000`): a parked fund below R$1bn is not covered.

## Tools the engine calls

`portfolio_resolve`, `portfolio_fees`, `portfolio_lookthrough` (from `demo/api-portfolio`: the
argument and column names here are the agreed contract, recorded with canned rows only and not
yet run against the live function), and the existing `lookup`, `quote_latest`,
`company_financials`, `short_interest`, `fidc_portfolio`, `fund_restatements`,
`fund_restatement_diff` and the `screen_*` tools. Default client: the public read-only MCP
`silo-mcp`; fallback `PostgrestClient`. Neither was exercised over a network from the build
sandbox.
