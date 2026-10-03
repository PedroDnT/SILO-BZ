# Portfolio engine output (schema 1.0)

What `python -m src.portfolio.diagnose <statement> [--client mcp|postgrest|fake] [--out report.json]`
writes: one JSON document. The report writer (Redator and Revisor, `docs/reference/portfolio/report.md`)
builds on it, and every number in a report must be a key of this document.

```
python -m src.portfolio.diagnose docs/reference/portfolio/statement-template.xlsx --client fake \
    --out tests/fixtures/portfolio/demo_engine_output.json
```

The input is the spreadsheet template (`statement-template.md`) or, for the BTG performance report,
the PDF reader and consolidation (`statement-pdf.md`); both give the engine the same `Statement`.

**The schema is stable and append-only within `schema_version` 1.0.** Keys are added, never
renamed, retyped or removed. A breaking change bumps `schema_version`. The fixture
`tests/fixtures/portfolio/demo_engine_output.json` is the engine run on the demo template with
the `FakeClient` and a fixed clock; `tests/test_portfolio_engine.py` regenerates it and compares
byte for byte, so a change to the engine that moves the fixture fails CI until the fixture is
regenerated in the same commit. The canned rows (`fake_silo_rows.json`, built by
`tests/fixtures/portfolio/build_fake_silo_rows.py`) are synthetic, shaped on production
measurements of 2026-10-03 and on the merged `api.portfolio_*` contract: the values are not data.

## Conventions

| Convention         | Rule                                                                                                                                                                                                                                                                                                                    |
| ------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Money              | BRL as a JSON number rounded to 2 decimals; every key holding reais contains `_brl`.                                                                                                                                                                                                                                    |
| Percentages        | A number of percent: `1.65` means 1,65 %. Every key holding a percent contains `_pct` (`portfolio_pct`, `rate_pct_year`, `known_fee_fund_value_pct`).                                                                                                                                                                   |
| Fractions          | `weight_in_line`, `explained_weight`, `unexplained_weight`, `similarity`, `quota_rel_diff`, `quota_on_date` are ratios (0.25 = 25 %). Never named `pct`.                                                                                                                                                                |
| Dates              | ISO `YYYY-MM-DD`; timestamps UTC `YYYY-MM-DDTHH:MM:SSZ` (the report shows UTC-3 with UTC in parentheses).                                                                                                                                                                                                               |
| Null               | Not declared at source or not computed, never zero. A reason sits next to it. A disclosed 0 is `0.0`.                                                                                                                                                                                                                   |
| Sections           | Every section starts with `status` (`complete`, `partial`, `unknown`, `not_applicable`), `reason` (Portuguese, why it is not complete) and `errors` (the verbatim error of each refused call: `call_id`, `tool`, `args`, `error`). A refused call makes its section unknown (or the line, `partial`), never the report. |
| Sources            | Every number sits beside a `sources` list of `{tool, call_id, args, data_date}`; `call_id` is a row of `provenance`. `tool = "statement"` means the client's own statement (`args.line_no`).                                                                                                                            |
| Text               | Engine strings are Portuguese and are the wording the report may quote.                                                                                                                                                                                                                                                 |
| Holder and account | Never present: `statement.holder` holds the fixed tokens `[TITULAR]`, `[CPF]`, `[CONTA]`; accounts are ordinal tokens `C1..Cn` and holders `T1..Tn`.                                                                                                                                                                    |

## Top level

`schema_version`, `generated_at_utc`, `engine` (`version`, `client`, `params`), `statement`,
`identification`, `fees`, `look_through`, `indexer`, `sector`, `restatements`, `risk_signals`,
`assumptions`, `section_status`, `provenance`.

- `engine.params`: `cda_month` (default: position month - 4), `fee_month` (default: position
  month - 1), `max_depth` (default 4, 1 to 6), `restatement_months`, `max_diff_docs_per_fund`,
  `sector_lookthrough_top_tickers`. Fixed lags until a `coverage()`-driven default exists.
- `assumptions[]`: `{id, text}`, each a reading the engine could not verify (`fee_units`,
  `weight_in_root`, `position_date`, `valuation`, `direct_tesouro`, `economic_group`,
  `abnormal_movement`). The report states the ones that touch what it says.
- `section_status`: `{section: {status, reason}}`, for a cover-page summary.
- `provenance[]`: every tool call in order: `call_id`, `id` (`p<call_id>`), `tool`, `args`,
  `requested_at_utc`, `row_count` (null on error), `error` (verbatim, null on success). No retry,
  no trimming.

## `statement`

`holder`, `corretora`, `source_format` (`xlsx`, `csv`, `pdf`, `mixed`), `stated_total_brl`,
`sum_of_lines_brl`, `difference_brl`, `tolerance_brl`, `reconciled` (always true: a statement
that does not reconcile never reaches the engine), `n_lines`, `position_date` (latest of the
lines), `position_dates`, `notes[]` (which sum checks ran, date gaps, multi-titular), `positions[]`,
`consolidated`, `accounts[]`.

- `positions[]`: `line_no`, `source_row`, `linha_extrato`, `tipo` (the template's types, plus
  `caixa` for a current-account line), `codigo`, `quantidade`, `preco_unitario`, `preco_implicito`
  (true when the unit price is value / quantity), `valor_brl`, `portfolio_pct`, `data_posicao`,
  and what the statement itself prints, all null for a spreadsheet that has not got them:
  `vencimento`, `taxa_texto` (the rate exactly as printed), `estrategia_corretora` and
  `classe_corretora` (the broker's own labels), `conta_ref`, `contas[]` (the per-account lines of
  a consolidated position: `conta_ref`, `titular_ref`, `valor_brl`, ...), `source`. The valuation
  of a line is always the statement's.
- `consolidated` / `accounts[]`: true when several statements were consolidated; `accounts[]` is
  the per-account view (`conta_ref`, `titular_ref`, `n_lines`, `stated_total_brl`,
  `sum_of_lines_brl`, `position_date`, `source_format`, `positions[]`). `positions[]` above is the
  consolidated view: the same asset in several accounts is one line with its `contas`.

## `identification`

`counts` (`identified`, `ambiguous`, `unknown`) and `lines[]`:

- `status`: `identified`, `ambiguous` (candidates and `reason`) or `unknown` (`reason`).
- `identity`: `kind` (`fund`, `ticker`, `tesouro`, `caixa`), `cnpj`, `name`, `entity_type`,
  `ticker`, `isin`, `asset_class`, `issuer_cnpj` (a share's issuer, from `company_financials`,
  because `lookup` returns `cnpj` null for tickers), `tesouro_title`, `tesouro_maturity`.
- `fund_match`: from `portfolio_resolve`: `candidates[]` (`rank`, `cnpj`, `name`,
  `matched_name`, `matched_period`, `entity_type`, `match_kind`, `similarity`, `quota_on_date`,
  `quota_rel_diff`, `ambiguous`, `reason`), `chosen`, `quota_basis` (printed or implied by the
  statement), `sources`.
- `ticker_match`: `lookup` row, `reference_quote` (close and date: reference only, never the
  position's value; its date can be after the position date), `issuer`. A ticker the statement
  types as `outro` is told share or fund quota by `lookup.asset_class`, never by the engine.
- `statement_facts`: `vencimento`, `taxa_texto`, `estrategia_corretora`, `classe_corretora`,
  `conta_ref`, `preco_implicito`: what the statement printed for the line.
- `valuation`: `{value_brl, basis: "statement", note, sources}`. A Tesouro line has no price
  series in SILO: the statement's value is the value.
- `findings[]`: `{kind: "renamed" | "cnpj_conflict", text, ...}`.
- A CRI, CRA, CDB, LCI, LCA or debenture held directly is `unknown` (SILO has no registry or
  price for them) with the statement's registry code in the reason; its printed rate and maturity
  still feed the indexer block.

## `fees`

`month`, `estimate_label` (`estimativa, não divulgada`), `not_found_label`
(`taxa divulgada não encontrada`), `stale_after_months` (24), `lines[]`, `underlying[]`, `totals`.
The rules (owner, 2026-10-03):

1. **Headline = the disclosed administration fee as filed**, % a year: the lâmina
   (`cvm_fi_lamina`, newest reference month), then cad_fi (`cvm_fund_registry.taxa_adm`), then
   none: `fee_status = "taxa divulgada não encontrada"` (about 84 % of funds). The estimate is
   never substituted. `fee_status` is `divulgada`, `faixa divulgada` or the not-found label.
2. **The estimate is a separate field**, `estimate`, always labelled `estimativa, não divulgada`
   with its `method`, beside the disclosed fee or alone, never averaged, never the fee.
   `estimate.available` is false when the tool gave none (a fiscal-year reset month, no balancete).
3. **`expense_ratio`** (PR_PL_DESPESA, the declared total expense ratio) is a separate field with
   its period, never added. `portfolio_fees` does not return it yet: `declared_pct` is null and
   the note says so.
4. The lâmina date and age are always output (`disclosed.as_of`, `age_months`); `stale` and
   `stale_label = "defasada"` when older than 24 months. For cad_fi `as_of` is the day SILO read
   the row (the field `as_of_meaning` says which).
5. A disclosed 0 is `rate_pct_year = 0.0`, with a finding `Divulgado 0, balancete registra
despesa.` (level `atenção`) when the estimate is above 0,05 % a.a. With no single value but a
   min and max, `headline.kind = "faixa"` and the range is output as filed. Another `atenção`
   finding when the estimate differs from a fixed disclosed fee by more than max(0,25 p.p. a.a.;
   25 % of the disclosed value).
6. **`disclosed.perf_as_filed` is the source's text, verbatim, never parsed**, and never R$ (a
   share of the excess return, not of the NAV).
7. **A master's fee is never added to a feeder's.** Each fund keeps its own. `underlying[]` lists
   the funds a statement fund holds (every path), each with its own fee record and
   `label = "não somada"`, `added_to_totals = false`.

A line: `line_no`, `cnpj`, `fund_name`, `position_value_brl`, `fee_status`, `reason`,
`fund_nav_brl`, `disclosed` (`source`, `as_of`, `age_months`, `stale`, `n_classes`, `note`,
`adm_rate_pct_year`, `adm_min_pct_year`, `adm_max_pct_year`, `adm_info_text`, `perf_as_filed`,
`perf_info_text`), `headline` (`kind` `fixa` | `faixa`, `rate_pct_year` or the range, `per_year_brl`
= position value x rate), `estimate` (`adm_pct_year`, `adm_per_year_brl`, `perf_pct_year`,
`perf_per_year_brl`, `fiscal_reset_suspect`, `month`), `expense_ratio`, `findings[]`.
`totals`: `adm_disclosed_fixed_per_year_brl`, the range low and high, `estimate_adm_per_year_brl`
and `estimate_perf_per_year_brl` (kept apart), and the fund value with a fixed fee, a range, none.
Assumption: the rates are read as percent a year (`fee_units`).

## `look_through`

`cda_month`, `max_depth`, `lines[]`, `shared_exposure`. From `portfolio_lookthrough`, one call per
fund: `depth` 0 is the fund's own holdings, a row is a leaf unless its `asset_kind` is `fund_quota`
(looked through; its holdings are the rows below).

- `lines[]`: `status` (`complete`, `partial`, `no_holdings`, `unknown`), `exposures[]` (`via`
  path, `depth`, `block`, `asset_kind`, `asset_key`, `asset_name`, `isin`, `issuer_cnpj`,
  `issuer_code`, `tp_aplic`, `tp_titpub`, `indexer_code`, `taxa_texto`, `maturity`,
  `weight_in_line`, `exposure_brl` = position value x `weight_in_root`, `not_opened_fund`,
  `period`, `sources`), `fund_nodes[]` (the funds on the way, with `expanded` and
  `not_expanded_reason`), `explained_weight` and `unexplained_weight` (what no ingested CDA block
  explains: cash, derivatives, blocks 3, 5, 7, 8; negative when liabilities and derivatives sum
  above the fund value; never filled), `rows_without_weight` (a NAV on the path unknown),
  `n_cycle_rows_skipped`. `no_cda_filing` is `no_holdings` (FIDC and FII file no CDA).
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
`value_brl`, `portfolio_pct`). `items[]` lists every classified exposure with its rule and
sources. Neither is ever inferred from a name (`never_inferred_from_name`).

- `indexer`: `rules_version`, `rules_sha256`, `rules_file` (`src/portfolio/rules/indexer_rules.csv`),
  `classes[]` (`indexer_class`, `value_brl`, `portfolio_pct`, `n_items`), `by_position[]`. The
  class comes from a published field: CDA block 1 `tp_aplic` / `tp_titpub`, block 6
  `cd_indexador_posfx`, block 4 `tp_aplic`, a direct Tesouro title, or what the statement prints:
  the `taxa_texto` of a direct credit line, read by the table's `statement_taxa` regexes only
  (`IPCA + x`, `x% do CDI`, `CDI + x`, `x% a.a.`...), and the `Conta corrente` line as `caixa
(conta corrente)`. A rate text with no rule is `sem classificação`.
- `sector`: `sectors[]` (`sector`, `taxonomy`, ...). Taxonomy `CVM (cia_company.setor)` for
  listed shares (B3's `short_interest.sector` only as a labelled fallback), `CVM (cvm_fidc_setor)`
  for FIDC (tab II lettered codes, parents only). FII `segmento_atuacao` and ETF `segment` have no
  tool in the public contract: `sem classificação` with that reason. `lookthrough_ticker_limit`:
  shares inside funds are resolved for the largest N tickers only, the rest says so.

## `restatements`

`window`, `assessment` (the thresholds are parked by the owner), `lines[]` for FIDC and FII
positions: `restatements[]` (`fnet_id`, `previous_fnet_id`, `reference`, `versao`, `modalidade`,
`delivered_at`, `previous_delivered_at`, `lag_days`, `n_fields_changed`, `diff_status`,
`assessment`, `leaves[]`, `n_leaves`, `leaves_complete`). Every leaf (`leaf`, `field_path`,
`old_value`, `new_value`, `old_num`, `new_num`, `delta`, both FNET ids, both dates, `source_url`)
says `reapresentado, não avaliado`: the engine makes no materiality judgement.

## `risk_signals`

`screens[]` (each tool call with `status` and `n_rows`; `screen_overdue_securit` and
`screen_dormant_trend` are `not_applicable`: no fund CNPJ), `dormant_coverage_note`,
`abnormal_movement` (parked), `lines[]` (`signals[]` with the screen's own row and `screen` /
`params`, `unknown_screens`). A signal is not a verdict, and no signal is not a health
certificate. `screen_dormant_funds` is called twice, pinned (`p_dormancy = empty_shell`;
`p_min_nav = 1000000000`): a parked fund below R$1bn is not covered.

## Mapping to the report's provisional fixture (slice D)

The report was built against `report_provisional_engine_output.json`, written before this schema.
The paths differ; this table is the follow-up to update `src/portfolio/report/values.py`, the
Redator's placeholders and that fixture together. Units already agree (`_brl` reais, `_pct`
percent).

| Report (provisional)                                                | Engine (this schema)                                                                                                                  |
| ------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| `generated_at`, `valuation_date`                                    | `generated_at_utc`, `statement.position_date`                                                                                         |
| `portfolio.total_brl`, `n_lines`                                    | `statement.sum_of_lines_brl`, `statement.n_lines`                                                                                     |
| `portfolio.n_identified` / `n_ambiguous` / `n_unknown`              | `identification.counts.identified` / `ambiguous` / `unknown`                                                                          |
| `lines[i].value_brl`, `weight_pct`                                  | `statement.positions[i].valor_brl`, `portfolio_pct`                                                                                   |
| `lines[i].identification.status`, `candidates`                      | `identification.lines[i].status`, `fund_match.candidates`                                                                             |
| `lines[i].identification.renamed_from`                              | `identification.lines[i].findings[kind = renamed].matched_name`                                                                       |
| `fees.by_line[i].disclosed_pct_year`                                | `fees.lines[i].headline.rate_pct_year`                                                                                                |
| `fees.by_line[i].estimated_pct_year`, `estimated_brl_year`, `label` | `fees.lines[i].estimate.adm_pct_year`, `adm_per_year_brl`, `label`                                                                    |
| `fees.total_estimated_brl_year`, `total_disclosed_brl_year`         | `fees.totals.estimate_adm_per_year_brl`, `adm_disclosed_fixed_per_year_brl`                                                           |
| `lookthrough.shared_exposure[i]` (`key`, `total_brl`, `legs`)       | `look_through.shared_exposure.groups[i]` (`label`, `total_exposure_brl`, `lines`)                                                     |
| `lookthrough.top_underlying`                                        | not output: take `look_through.lines[i].exposures` sorted by `exposure_brl`                                                           |
| `indexer.buckets[i]` (`indexer`, `weight_pct`)                      | `indexer.classes[i]` (`indexer_class`, `portfolio_pct`)                                                                               |
| `sector.buckets[i]` (`sector`, `weight_pct`)                        | `sector.sectors[i]` (`sector`, `portfolio_pct`)                                                                                       |
| `restatements.items[i]`                                             | `restatements.lines[i].restatements[j]`; the delinquency leaf is `leaves[leaf = VL_CRED_EXISTE_INAD]` (`old_num`, `new_num`, `delta`) |
| `risk_screens` (`hits`, `not_run`)                                  | `risk_signals.lines[i].signals`, `risk_signals.screens[status = unknown]`                                                             |
| `sections.<name>`                                                   | `section_status.<name>` (`look_through`, `risk_signals` for `lookthrough`, `risk_screens`)                                            |
| `provenance[i].id` (`p1`)                                           | `provenance[i].id` (`p<call_id>`); `sources[].call_id` is the number                                                                  |
| `data_dates`                                                        | per source: `sources[].data_date`                                                                                                     |

## Tools the engine calls

`portfolio_resolve`, `portfolio_fees`, `portfolio_lookthrough` (merged, catalog v51; the canned
rows follow their documented columns and have not been run against the live functions), and the
existing `lookup`, `quote_latest`, `company_financials`, `short_interest`, `fidc_portfolio`,
`fund_restatements`, `fund_restatement_diff` and the `screen_*` tools. Default client: the public
read-only MCP `silo-mcp`; fallback `PostgrestClient`. Neither was exercised over a network from the
build sandbox.
