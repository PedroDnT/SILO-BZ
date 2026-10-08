# Portfolio engine output (schema 2.1)

What `python -m src.portfolio.diagnose <statement> [--client mcp|postgrest|fake] [--out report.json]`
writes: one JSON document. The report writer (Redator and Revisor, `src/portfolio/report/`)
builds on it, and every number in a report must be a key of this document.

```
python -m src.portfolio.diagnose docs/reference/portfolio/statement-template.xlsx --client fake \
    --out tests/fixtures/portfolio/demo_engine_output.json
```

The input is the spreadsheet template (`statement-template.md`) or, for the BTG performance report,
the PDF reader and consolidation (`statement-pdf.md`); both give the engine the same `Statement`.

**The schema is stable and append-only within a major version.** A minor bump (1.0 to 1.1) only adds keys (see "Changes since 1.0") Keys are added, never
renamed, retyped or removed. A breaking change bumps the major `schema_version` (1.15 to 2.0). The fixture
`tests/fixtures/portfolio/demo_engine_output.json` is the engine run on the demo template with
the `FakeClient` and a fixed clock; `tests/test_portfolio_engine.py` regenerates it and compares
byte for byte, so a change to the engine that moves the fixture fails CI until the fixture is
regenerated in the same commit. The canned rows (`fake_silo_rows.json`, built by
`tests/fixtures/portfolio/build_fake_silo_rows.py`) are synthetic, shaped on production
measurements of 2026-10-03 and on the merged `api.portfolio_*` contract: the values are not data.

## Changes since 1.0

1.14 (#607/#614): additive `client_fit`, with validated declared constraints and factual cash/maturity checks; no suitability approval. See [contract](brief-client-fit.md).
1.15 (map #510, owner 2026-10-06): additive `returns.contribution`, the retroactive contribution per position and window (see `returns`, below); no portfolio total.
2.0 (2026-10-07): keys removed, none added. The return, tax and market-equivalent blocks stop writing reader text the report derives from their codes and figures (`src/portfolio/report/labels.py`, added by `adapt` at the same view paths, so the report and the Redator's placeholders are unchanged): `returns.lines[].basis_label` and `status_label`, every return window's `status_label` and `gross_label`; `tax.lines[].fee.third_party_label`, `tax.lines[].tax.status_label`, `instrument_label`, `rate_text` and `candidates[].rate_today_text`, `tax.lines[].pension.regime_label`, `base_text` and `irrevocable_text`; `equivalents.pl_label` and `fee_label`, `equivalents.lines[].etf.pl_label`, `fee_label` and `basis_label`, and every window's `etf_band_label` / `fund_band_label`. The report reads a 1.x document as before (its labels are replaced by the same text).

2.1 (#766, owner 2026-10-08; catalog v71): keys added, none renamed, retyped or removed. Direct credit gets a return.
A CRA or CRI identified in the CVM register has `basis` `curva_securitizadora` (method A, `portfolio_credit_returns`,
one call for every such line); a debênture's code is `retorno_debenture_metodo_pendente` (method B waits for the owner's
threshold); a CDB, LCI, LCA or a CDCA the statement prints has `retorno_contratado_anexo` and a `contracted` block
(method C). Every `returns.lines[]` gains `credit_code` and `contracted` (null when not bank credit); a curve line also
gains `series`, its `month_ends[]` gain `data_referencia`, `paid_per_unit`, `factor`, `month_flag` and `taxa_juros`,
and its windows `month_flags`. `returns` gains `pct_of_cdi_credit_note` and `contracted_note`; `coverage.{12m,6m}`
gains `contracted_value_brl`, `contracted_coverage_portfolio_value_pct` and `n_contracted`; every contribution window
gains `excluded_lines`. `statement.positions[]` gains `data_inicial` (the BTG detail table's 'Data inicial'). New reason
codes in `common.REASON_TEXT`: `retorno_debenture_metodo_pendente`, `serie_ambigua`, `valor_invalido`, `quantidade_mudou`,
`pu_repetido`, `queda_sem_evento_arquivado`, `pagamento_acima_do_pu`, `taxa_credito_sem_taxa_adm`, `credito_nao_cdi`,
`taxa_nao_informada`, `retorno_contratado_anexo`, `contratado_taxa_ilegivel`, `contratado_sem_data_inicial`,
`contratado_papel_mais_novo`, `contratado_vence_na_janela`, `contratado_ipca_indisponivel`, `metodo_fora_do_total`.
The new calls (`portfolio_credit_returns`, and `inflation` when a contracted rate is on IPCA) come after the CDI call
of the return block, so the call ids of later blocks move.

1.13 (#609 owner's resolution and #606 addendum Q36, 2026-10-05; catalog v68). Keys were added, none renamed, retyped
or removed. A new top-level section `equivalents` (below), placed after `tax` and before `investigation` (1.12), with its `section_status` entry and the
assumptions `pct_of_cdi` and `market_equivalent`. Every `returns.lines[]` gains `benchmark` and every return window
gains `cdi_like`, `pct_of_cdi` and `pct_of_cdi_reason_code`; `returns` gains `pct_of_cdi_note`; every `fees.lines[]`
gains `benchmark_as_filed` (`portfolio_fees` v68's `benchmark_extrato`, `benchmark_lamina`, `benchmark_lamina_n`, null
for a row that predates them). New reason codes in `common.REASON_TEXT`: `referencia_nao_informada`,
`referencia_nao_cdi`, `referencia_diverge`, `referencia_nao_servida`, `pct_cdi_so_fundos`, `cdi_nao_positivo`,
`equivalente_fora_escopo`, `equivalente_sem_comparacao`, `equivalente_sem_classe`, `equivalente_sem_par`,
`equivalente_sem_etf`, `equivalente_sem_pl`, `equivalente_sem_linha`, `equivalente_sem_retorno`, `equivalente_sem_taxa`,
`distribuicao_classe_nao_avaliada`. The equivalents block calls `portfolio_equivalents`, `class_return_distribution`
and the ETF's series after every other block but the investigator, so no earlier call id moves. The report shows it in "Equivalente de
mercado" and prints "% do CDI" only where the engine wrote it (`redator-revisor.md`).

1.12 (owner's resolution of #605, 2026-10-05). Keys were added, none renamed, retyped or removed: a new top-level
section `investigation` (below), placed after `tax`, with its `section_status` entry and the assumption
`investigation`. New reason codes in `common.REASON_TEXT`: `investigador_desligado`, `investigador_falhou`,
`sem_gatilho_investigador`, `investigacao_parcial`, `limite_buscas`, `busca_web_indisponivel`, `nivel_b_desligado`.
The block runs last; its SILO calls (`company_events`, RAD only) come after every earlier call id. Off by default
(the CLI and the demo fixture); the report does not show it yet.

1.11 (owner's resolution of #613, 2026-10-05; rules from `docs/reference/research/tax-rules-by-instrument.md` (#611)
and `pension-plan-data.md` (#612)). Keys were added, none renamed, retyped or removed: a new top-level section `tax`
(below), placed after `returns`, with its `section_status` entry and the assumption `tax`; `statement.positions[]`
gains `data_aplicacao` (the spreadsheet's new optional column, null when not printed). New reason codes in
`common.REASON_TEXT`: `imposto_sem_regra`, `imposto_linhas_sem_regra`, `data_aplicacao_nao_informada`,
`aliquota_depende_de_condicao`, `mais_de_uma_regra`, `ganho_12m_indisponivel`, `aplicacao_dentro_da_janela`,
`ganho_12m_nao_positivo`, `previdencia_sem_estimativa`, `isento_sem_imposto`. The block makes no tool call, so no
call id moves. The report shows it in "Taxa e imposto por posição" (`redator-revisor.md`). Also in 1.11 (catalog v66, #609): each
`fees.comparison.lines[]` row gains `n_fund_peers`, `n_etf_peers`, `n_etf_excluded`, `etf_peer_tickers`,
`etf_peer_fee_oldest`, `etf_peer_fee_newest` and `etf_peer_fee_source`, copied as `portfolio_fee_peers` serves them
(null when the row was not served), and `fees.comparison.basis` says ETFs on an index mapped to the class enter as peers
and in the statistics with the third-party site's fee, counted apart in `n_etf_peers`. The equivalente de mercado (#609: an ETF of the same objective with its
12- and 6-month return against the class distribution) came in 1.13.

1.10 (owner's resolution of #610, 2026-10-05; inputs `docs/reference/research/portfolio-return-coverage.md`
(#606) and `quota-net-of-fees.md` (#631)). Keys were added, none renamed, retyped or removed: a new top-level
section `returns` (below), placed after `risks`, with its `section_status` entry and the assumption `returns`.
New reason codes in `common.REASON_TEXT`: `linhas_sem_retorno`, `cdi_indisponivel`, `retorno_tesouro_sem_serie`,
`retorno_credito_sem_serie`, `retorno_caixa`, `retorno_fidc_sem_classe`, `retorno_fip_sem_serie`,
`retorno_sem_ticker`, `retorno_sem_regra`, `retorno_linha_nao_identificada`, `etf_rf_sem_api`,
`serie_incompleta`, `retorno_total_nulo`, `sem_taxa_utilizavel`, `taxa_nao_aplicavel`. The block runs after
every other one, so the call ids of the earlier sections do not move. The report shows it in "Retorno por posição".

Additive extension of 1.9 (2026-10-05, catalog v63): `fees.comparison` is an independently
statused peer comparison, with `as_of`, `basis`, per-position `lines` and statement/API
`sources`. Comparable lines carry their filed class, fund-of-funds flag, document
scope, own fee/date, p25/median/p75, percentile, difference in percentage points,
peer/exclusion counts and peer document dates. Non-comparable lines retain null
statistics and a fixed reason. Section totals report compared/not-compared counts,
fund value, compared value and coverage by fund and portfolio value. The report
view adapts lines into `fees.comparison.by_line`. See
[fee-peer-comparison.md](fee-peer-comparison.md) for eligibility and limitations.

1.9 (owner's brief of 2026-10-05: identify the CRA, CRI and debentures held directly; manager concentration and
liquidity, both "não avaliado" in 1.8; catalog v62 serves `portfolio_instruments` and `portfolio_fund_terms`). Keys
were added, none renamed, retyped or removed. **Identification:** a CRA, CRI or debenture line with a code is
looked up in `portfolio_instruments` (one batched call, the `_resolve` chunk and retry path) and gains
`credit_match` (below); a fund line gains `fund_terms` (below); `identity.issuer_code` for a debenture found in the
CDA. `FIP` is a fund type (statement, BTG extrato, identification, report). **New section `liquidity`** (below),
after `allocation` and in `section_status`. `concentration.manager` is computed (below) and
`concentration.fund_liquidity` points at `liquidity`. **Risks:** rows `credito_situacao`, `credito_vencimento_diverge`,
`credito_preco_marcacao`, `concentracao_gestor`, and `liquidez` is evaluated (table below). `look_through.lines[].
max_depth_used`: a fund of funds whose look-through passes the API's one-page cap (22023) is asked again one level
shallower, down to 1, and the section gains `profundidade_reduzida`. **Signals:** `screen_delinquency_drivers` refuses
with its defaults (above 1000 rows on 2026-10-05), so it is called once per worsening driver
(`screen_delinquency_drivers[consistent_worsening]`, `[value_up_rate_masked]`). Assumptions `credit_registry` and
`fund_terms`. `REASON_TEXT` codes `credito_sem_registro`, `credito_sem_codigo`, `vencimento_diverge`,
`serie_sem_vencimento`, `situacao_fora_adimplente`, `codigo_nao_conferido`, `sem_cra_cri`, `cra_cri_sem_registro`,
`sem_debenture`, `sem_marcacao_fundos`, `gestor_nao_informado`, `sem_gestor`, `prazo_nao_informado`,
`liquidez_sem_identificacao`, `profundidade_reduzida`. **Changed values** (from the first real-statement review,
2026-10-05): a `renamed` finding is written only when the name led the identification (`match_kind` other than
`cnpj`), since CVM 175 renamed almost every fund; `concentracao_fundo` sums the lines of one fund (same CNPJ, else
same code) held in several accounts; the `indexador` row carries `check_label` when more than 25% of the portfolio has
no indexer (`INDEXER_UNCLASSIFIED_CHECK_PCT`). `look_through.shared_exposure.groups[]` of kind
`mesmo_fundo_investido` gain `direct_line_nos` and `lines[].direct`: a fund or ETF held directly joins the group when
another line holds the same CNPJ underneath (never two direct lines alone).

1.8 (owner's brief of 2026-10-04: charts, a clear fee total and the main risks). Keys were added, none renamed,
retyped or removed. **New section `allocation`** and **new section `risks`** (below), placed after `concentration`
and in `section_status`. `fees.summary` (below), and `fees.totals.adm_disclosed_range_low_portfolio_pct` /
`adm_disclosed_range_high_portfolio_pct`. `concentration.maturity_ladder.by_year[]` (`year` as a string, so it never
prints as a number; `value_brl`, `portfolio_pct`, `n_lines`, `line_nos`): the ladder's lines by calendar year of
maturity. Assumption id `risks`. `REASON_TEXT` codes `sem_emissor_impresso`, `riscos_nao_avaliados`,
`sem_carteira_dos_fundos`, `sem_taxa_em_reais`.

1.7 (owner, 2026-10-04: a real 41-line statement came out with half its value unidentified after one timeout).
Keys were added, none renamed, retyped or removed. **Identification:** `portfolio_resolve` is split (the lines with a
CNPJ on the statement in one call, the others in chunks of 3); a transient failure (timeout 57014, 5xx, 408/429,
network) is retried once with the chunk halved, and a failure costs only its own lines. A line with a CNPJ on the
statement that resolve does not return (error or no candidate) is identified by it: `fund_match.chosen.match_kind =
"cnpj_extrato"`, `reason` "CNPJ do extrato; nome não conferido.", `identity.name` null, and every later block runs for
it. An `ETF` line whose `codigo` is a ticker skips the name path (the ETF probe matches the bare ticker). A line without
a CNPJ that still fails for an infrastructure reason raises `SiloUnavailable`: no document (the server answers 503).
New: `lines[].reason_code`, `identification.unknown_groups[]` (`reason_code`, `line_nos`, `n_lines`, `value_brl`,
`portfolio_pct`), `cnpj_extrato_line_nos`, `same_identity_line_groups[]` (`kind`, `key`, `line_nos`: lines printed
apart that identify as one fund or ticker). **Every section** gains `reason_codes[]` (also in `section_status`), codes
whose fixed Portuguese text is `src/portfolio/common.py` `REASON_TEXT`; the report prints that text, never `reason`.
`errors[]` entries gain `transient`. `movement.lines[].reason_code` and `fees.lines[].reason_code` (failure lines).
**Statement:** the spreadsheet reads the optional columns `vencimento` and `taxa` (`taxa_texto`); lines of one
statement with the same identity (same CNPJ; same code and maturity; a codeless fund with the same name, type and
printed quota) are merged into one position with its source lines in `contas` (`conta_ref` null), before
identification: `statement.n_lines_read`, `n_positions_merged`, and a note. **Indexer:** four more `statement_taxa`
rules (`CDI`, `CDI+x`, `x% CDI`, `IPCA+x`), rules version `2026-10-04.1`. **New section `concentration`** (below).

1.6 (catalog v57, owner's decision of 2026-10-03: the report shows each ETF's cotistas and PL). Keys were added,
none renamed, retyped or removed. CVM has no 2026 daily report row (no cotistas, no PL) for any of the 178 active
registry ETFs, so every fee line's `etf_site` gains `nr_cotistas` (an int), `pl_brl` (R$, as stored), `facts_label`
(`etfsbrasil.com.br, site de terceiro`) and `facts_note`, from the same snapshot as the fee (`as_of`); `fees.
etf_facts_label`. They are descriptive (rule 12): never summed, never a fee base, never `fund_nav_brl`.

1.5 (catalog v56, owner's decisions of 2026-10-03: "a taxa sim" for the newer lâmina, and "ETFs também têm taxa").
Keys were added, none renamed, retyped or removed; one value changed meaning. **Changed:** a `lamina_newer` line
(`headline.kind = "lamina_mais_recente"`) is now a cost: `per_year_brl` is the position value x the lâmina's rate,
`counted_as_cost` is true, it is summed in `totals.adm_disclosed_fixed_per_year_brl` and counted in
`fund_value_with_fixed_fee_brl` (so `fund_value_with_lamina_newer_fee_brl` is now a subset of it and no longer part
of `fund_value_without_disclosed_fee_brl`), and it is compared with the balancete estimate
(`estimativa_difere_da_divulgada`). It stays `needs_manual_check` with the new `headline.sources_differ_label`
(`fontes divergem`); the Extrato value beside it is never summed. `extrato_lamina_beside` and `extrato_to_check` are
unchanged. **New, ETFs:** `identification.lines[].etf_match` and `identity.etf_cnpj` (a ticker line typed `ETF`, or
`outro` and not a share, mapped to the ETF's CNPJ by `portfolio_resolve` `match_kind = "etf_ticker"`; the line stays a
ticker for the other blocks); `headline.kind` can be `etf_site` (rule 12); every fee line has `etf_site`; `fees.
sources_differ_label`, `etf_site_label`; `totals.adm_etf_site_per_year_brl`, `adm_etf_site_portfolio_pct`,
`adm_fee_per_year_brl`, `adm_fee_portfolio_pct`, `fund_value_with_etf_site_fee_brl`,
`fund_value_with_etf_site_fee_to_check_brl`, `known_fee_incl_etf_site_fund_value_pct`. A ticker's four-character root
may now hold digits (B5P211, 5PRE11, TD3511, B3SA3), in the engine and in the PDF reader.

1.4 (catalog v55, issue #552: the Extrato and the lâmina disagree). Keys were added, none renamed, retyped or
removed. New on every fee line (`lines[]` and `underlying[]`): `fee_resolution` (the tool's rule: `extrato`,
`extrato_lamina_beside`, `extrato_to_check`, `lamina_newer`, `lamina`, `cad_fi`), `lamina_beside`,
`extrato_beside` and `scale_flag` (rule 11 below), `disclosed.fee_resolution`; `headline.kind` can be
`lamina_mais_recente`; three findings (`lamina_ao_lado_do_extrato`, `lamina_mais_recente_que_extrato`,
`possivel_erro_de_escala_no_extrato`); `fees.lamina_beside_label`, `extrato_beside_label`, `lamina_newer_label`,
`scale_flag_label`, `check_label`; `totals.fund_value_with_lamina_newer_fee_brl`. Fixed:
`totals.fund_value_with_implausible_fee_brl` read a top-level key the line never had, so it stayed 0; it now
holds the lines above 5 % a.a. `needs_manual_check` is also true for `lamina_newer`.

1.3 (catalog v54, _movimento incomum_, owner's decisions of 2026-10-03). Keys were added, none renamed, retyped or
removed. New: the top-level section `movement` (below), `engine.params.movement_month`, `section_status.movement`, a
`movement_class` assumption, `--movement-month` on the CLI. Reworded, same keys: the `abnormal_movement` assumption and
`risk_signals.abnormal_movement` (a string) no longer say the rule is parked: they say it is the `movement` section.
The movement rule is not a materiality threshold for restatements, which stay parked.

1.2 (wording, owner on #515): a filed fee of 0 or above 5 % a.a. may be correct, so the engine never calls it wrong.
Labels changed: `0 informado; a conferir` and `valor informado acima de 5% a.a.; a conferir` (a negative value:
`valor informado negativo; a conferir`, `fees.negative_label`). Numeric handling is unchanged: neither value is a
cost, summed or compared, the balancete estimate stays beside it, `filed_zero` and `implausible_filed` keep their
meaning, and the filed value is shown (`headline.filed_pct_year` for a 0, `disclosed.adm_filed_raw` otherwise). New:
`fees.lines[].needs_manual_check` (true for either case, false otherwise) and `disclosed.needs_manual_check`.
The labels, the finding texts and the `reason` no longer say "descartado", "implausível" or "erro de escala"; the
`kind` of the finding (`valor_implausivel_descartado`), the key `disclosed.rejected` and `implausible_*` are kept
(append-only) and now mean "above the usual range, to be checked".

1.1 (catalog v52, the CVM Extrato as the first fee source). Keys were added, none renamed or removed;
two values changed meaning, as the owner decided on #515, and a consumer that read them must read the new rule:

- `fees.lines[].headline` can be `kind = "zero_informado"`: a filed 0 is no longer `rate_pct_year = 0.0`; it
  has `rate_pct_year = null`, `filed_pct_year = 0.0` and is never counted as a cost or summed. The tool's 0
  is still visible as `disclosed.adm_rate_pct_year = 0.0` with `disclosed.filed_zero = true`.
- `fees.totals.fund_value_without_disclosed_fee_brl` now also holds the lines with a filed 0 or an implausible
  value (new keys split them out).
- `fees.lines[].disclosed.source` can be `cvm_fi_extrato`; the provenance wording follows `disclosed.origin`.
- `fees.lines[].reason` is now always the engine's Portuguese; the tool's English note stays in `disclosed.note`.
- New: `fees.source_order`, `stale_after_months_by_origin`, `zero_label`, `implausible_label`;
  `disclosed.*` (origin, age_days, filed_zero, implausible_filed, adm_filed_raw, scope_label, class_note,
  terms_as_filed, rejected, ...); `expense_ratio` filled; `fees.totals.*_portfolio_pct`;
  `look_through.top_exposures`, `exposures[].portfolio_pct`, `groups[].total_exposure_portfolio_pct`;
  `identification.lines[].fund_match.tiebroken_by_quota`; `restatements...tipo_documento`, `reference_date`.

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
`identification`, `fees`, `look_through`, `indexer`, `sector`, `restatements`, `risk_signals`, `movement`,
`concentration` (1.7), `allocation` and `risks` (1.8), `returns` (1.10), `tax` (1.11), `equivalents` (1.13), `investigation` (1.12), `assumptions`, `section_status`, `provenance`.

- `engine.params`: `cda_month` (default: position month - 4), `fee_month` (default: position
  month - 1), `movement_month` (default: the position month when the position date is a month-end, else the
  month before, because a month that is not over cannot be judged), `max_depth` (default 4, 1 to 6),
  `restatement_months`, `max_diff_docs_per_fund`, `sector_lookthrough_top_tickers`. Fixed lags until a
  `coverage()`-driven default exists.
- `assumptions[]`: `{id, text}`, each a reading the engine could not verify (`fee_units`,
  `weight_in_root`, `position_date`, `valuation`, `direct_tesouro`, `economic_group`,
  `abnormal_movement`, `movement_class`, `risks` (1.8), `returns` (1.10), `tax` (1.11), `investigation` (1.12),
  `pct_of_cdi` and `market_equivalent` (1.13)). The report states the ones that touch what it says.
- `section_status`: `{section: {status, reason, reason_codes}}`, for a cover-page summary. The sections, their order
  and their names in the report's view are declared once in `src/portfolio/sections.py`.
- `provenance[]`: every tool call in order: `call_id`, `id` (`p<call_id>`), `tool`, `args`,
  `requested_at_utc`, `row_count` (null on error), `error` (verbatim, null on success). No trimming;
  the only retry is identification's (1.7), and the retried call is its own row. The report's view keeps
  neither `args` nor `error`: they stay in this document.

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
  a consolidated position: `conta_ref`, `titular_ref`, `valor_brl`, ...), `source`, `data_aplicacao` (1.11: the
  application date as printed; null when not printed, and a merged position keeps it only when every line agrees). The valuation
  of a line is always the statement's. Added within 1.8 for the BTG extrato read by OCR
  (`statement_ocr`, its labels drawn as outlines): `fonte_texto` (`"ocr"` when the name, code,
  emissor and rate were read by OCR; the numbers still come from the PDF's text layer; null
  otherwise), `codigo_conferido` (the code matched its shape, or the CNPJ its check digits; null
  outside OCR or with no code), `taxa_conferida` (the rate text matched its pattern; null outside
  OCR or with no rate) and `ajustes_ocr[]` (what the deterministic normalisation changed, as
  `"código: CRAO260025T lido como CRA0260025T pelo formato CRA"`; empty otherwise). A report can
  say "lido por OCR" and "a conferir" from these.
- `consolidated` / `accounts[]`: true when several statements were consolidated; `accounts[]` is
  the per-account view (`conta_ref`, `titular_ref`, `n_lines`, `stated_total_brl`,
  `sum_of_lines_brl`, `position_date`, `source_format`, `positions[]`). `positions[]` above is the
  consolidated view: the same asset in several accounts is one line with its `contas`.

## `identification`

`counts` (`identified`, `ambiguous`, `unknown`), `unknown_groups[]`, `cnpj_extrato_line_nos`,
`same_identity_line_groups[]` (1.7) and `lines[]`:

- `status`: `identified`, `ambiguous` (candidates and `reason`) or `unknown` (`reason`). `reason_code` (1.7):
  null for an identified line, `cnpj_extrato` for one identified by the statement's CNPJ only, else one of
  `consulta_falhou`, `sem_candidato`, `ambiguo`, `credito_sem_fonte`, `bancario_sem_fonte`, `outro_sem_ticker`,
  `acao_sem_ticker`, `ticker_nao_encontrado`, `tesouro_sem_vencimento`, `sem_identificacao`.
- `identity`: `kind` (`fund`, `ticker`, `tesouro`, `caixa`), `cnpj`, `name`, `entity_type`,
  `ticker`, `isin`, `asset_class`, `issuer_cnpj` (a share's issuer, from `company_financials`,
  because `lookup` returns `cnpj` null for tickers), `tesouro_title`, `tesouro_maturity`.
- `fund_match`: from `portfolio_resolve`: `candidates[]` (`rank`, `cnpj`, `name`,
  `matched_name`, `matched_period`, `entity_type`, `match_kind`, `similarity`, `quota_on_date`,
  `quota_rel_diff`, `ambiguous`, `reason`), `chosen`, `quota_basis` (printed or implied by the
  statement), `sources`.
- `etf_match` (1.5): for a ticker line typed `ETF`, or `outro` and not a share, with no fund CNPJ, and for a line
  typed `ETF` named by its bare ticker (matched in the first call, it never becomes a fund: an ETF files no CDA):
  the ETF's CNPJ from `portfolio_resolve` (`match_kind = "etf_ticker"`, SILO's curated ETF registry), its `name`,
  `reason`, `sources`; null otherwise. Used by the fee block only (`identity.etf_cnpj`); the line stays a ticker. A fixed
  income ETF that `lookup` does not find (it is not in COTAHIST) is identified this way.
- `ticker_match`: `lookup` row, `reference_quote` (close and date: reference only, never the
  position's value; its date can be after the position date), `issuer`. A ticker the statement
  types as `outro` is told share or fund quota by `lookup.asset_class`, never by the engine.
- `statement_facts`: `vencimento`, `taxa_texto`, `estrategia_corretora`, `classe_corretora`,
  `conta_ref`, `preco_implicito`: what the statement printed for the line.
- `valuation`: `{value_brl, basis: "statement", note, sources}`. A Tesouro line has no price
  series in SILO: the statement's value is the value.
- `findings[]`: `{kind: "renamed" | "cnpj_conflict", text, ...}`.
- A CDB, LCI or LCA held directly is `unknown` (SILO has no registry or price for them) with the statement's
  registry code in the reason; its printed rate and maturity still feed the indexer block. A CRA, CRI or debenture
  is looked up by its code (1.9):
- `credit_match` (1.9): `matched`, `reason_code`, `reason`, `input_code`, `code`, `match_kind` (`securit_cetip` |
  `cda_ticker` | null). For a CRA or CRI the series columns of `cvm_securit_serie` as filed (`instrument_type`,
  `cnpj_securit`, `numero_serie`, `classe`, `data_vencimento`, `situacao`, `taxa_juros`, `classificacao_risco_atual`,
  `valor_total_integralizado_brl`, `data_referencia`, and since catalog v67 `cd_isin`, the series' `codigo_isin` as
  filed, also served as `identity.isin`; its `issuer_code` stays null and the direct exposure carries neither, because a
  CRA or CRI ISIN names the securitizer), `n_series` and `series[]` when the code has several; the
  series chosen is the one whose maturity equals the statement's, else the only one, else the lowest number
  (`serie_sem_vencimento`). For a debenture `cd_isin`, `issuer_code` (ISIN characters 3-6), `n_fundos`,
  `preco_marcacao_fundos_brl` and `cda_period`, and `price_gap_pct` / `price_gap_abs_pct` / `price_gap_label` (the
  statement's price against the funds' mark, other dates: information, never a price verdict). `statement`
  (`issuer_as_printed`, `vencimento`, `taxa_texto`, `preco_brl`, `preco_implicito`, `data_posicao`): the issuer stays
  the one printed. `flags[]` (`code`, `text`, and the two maturities for `vencimento_diverge`): `vencimento_diverge`,
  `situacao_fora_adimplente`, `codigo_nao_conferido` (an OCR code sent as read, never fuzzy-matched). `sources`.
- `fund_terms` (1.9), on a fund line: `answered`, `gestor_id`, `gestor_name`, `admin_cnpj`, `admin_name`,
  `terms_source` (`extrato` | `lamina` | null), `terms_dt_comptc`, `qt_dia_conversao_cota`, `qt_dia_pagto_resgate`,
  `tp_dia_pagto_resgate`, `qt_dia_resgate_cotas`, `tool_note`, `sources`: as filed; null is "not filed", never 0.

## `fees`

`month`, `estimate_label` (`estimativa, não divulgada`), `not_found_label` (`taxa divulgada não encontrada`),
`zero_label` (`0 informado; a conferir`), `implausible_label` (`valor implausível
descartado`), `source_order` (`extrato`, `lamina`, `cad_fi`), `stale_after_months` (24, the lâmina's),
`stale_after_months_by_origin` (`extrato` 36, `lamina` 24, `cad_fi` null), `lines[]`, `underlying[]`, `totals`.
From `portfolio_fees` (catalog v52), one source per fund. The rules (owner, #515, 2026-10-03):

1. **Headline = the disclosed administration fee as filed**, % a year, from ONE source in this order: the CVM
   Extrato (`disclosed.origin = "extrato"`), the lâmina (`"lamina"`), cad_fi (`"cad_fi"`), else none:
   `fee_status = "taxa divulgada não encontrada"`. The estimate is never substituted. The provenance sentence
   follows `disclosed.origin` (an Extrato fee is not a cad_fi fee); `disclosed.as_of_meaning` says what the date
   means for that origin (the Extrato's `DT_COMPTC`, the lâmina's reference month, or, for cad_fi, the day SILO
   read the row, with no age claimed). `fee_status` is `divulgada`, `faixa divulgada`, `valor 0 informado
(provavelmente não preenchido)`, `valor informado acima de 5% a.a.; a conferir` or the not-found label.
2. **A filed 0 is not used as a fee, and not called wrong.** `headline.kind = "zero_informado"`, no rate, no R$, `counted_as_cost = false`,
   never summed; with the attention finding below when the estimate is above 0,05 % a.a.
3. **A value above 5 % a.a. (or below 0) is to be checked, not called wrong.** `headline` is null,
   `disclosed.implausible_filed = true`, the value as filed is in `disclosed.adm_filed_raw` and
   `disclosed.rejected.raw_value`: a plain number (named without `_pct`, so nothing prints it as a rate).
4. **Age.** The filing date and age are always output (`disclosed.as_of`, `age_months`, `age_days`). `stale`
   and `stale_label = "defasada"` when older than 36 months for the Extrato (age does not predict error there)
   and 24 for the lâmina (`disclosed.stale_after_months`).
5. **The estimate is a separate field**, `estimate`, always labelled `estimativa, não divulgada` with its
   `method`, beside the disclosed fee or alone, never averaged, never the fee. `estimate.available` is false
   when the tool gave none (a fiscal-year reset month, no balancete).
6. **Findings** (`findings[]`, level `atenção` unless stated): `divulgado_zero_balancete_registra_despesa`
   ("Divulgado 0, balancete registra despesa."); `estimativa_difere_da_divulgada` when the estimate differs
   from a fixed disclosed fee by more than max(0,25 p.p. a.a.; 25 % of it), worded "Estimativa e divulgada
   divergem", not that either is wrong; `lamina_defasada` / `taxa_defasada` and `valor_implausivel_descartado`
   at level `informação`.
7. **Terms as filed.** `disclosed.perf_as_filed` is the performance fee as text, verbatim, never parsed, never
   R$. For an Extrato fee `disclosed.terms_as_filed` carries `tp_fundo_classe`, `classe_anbima`, `performance`
   (`exists`, `taxa_perfm_as_filed`, `param_as_filed`, `calc_as_filed`, `info_as_filed`), `entry` and `exit`
   (`exists`, `pct_as_filed`, `real_brl_as_filed`) and `custody_max_as_filed`: shown as filed, no reading.
8. **Class scope.** An Extrato row of a CVM 175 class is `disclosed.scope_label = "taxa da classe"` (an ICVM 555
   fund: `taxa do fundo`); no subclass fee is assumed.
9. **`expense_ratio`** (the lâmina's declared total expense ratio, PR_PL_DESPESA) is its own field: `declared_pct`
   (% of average NAV), `period` (`from`, `to`), `as_of`, `source`, `note`; null with a note when none. Never added
   to a fee, whatever the fee's source.
10. **A master's fee is never added to a feeder's.** `underlying[]` lists the funds a statement fund holds (every
    path), each with its own fee record and `label = "não somada"`, `added_to_totals = false`.
11. **The Extrato and the lâmina disagree** (catalog v55, #552). When the Extrato filed 0 or above 5 % a.a. and the
    lâmina is older, has no single fee, or none in (0, 5] (`fee_resolution = "extrato_lamina_beside"`), the Extrato
    stays the headline as filed and `lamina_beside` carries the lâmina's own fee (`lamina_pct_year`, or the min and
    max), its `as_of`, `age_months`, `stale` (24 months), `label` `lâmina informa` and `check_label` `a conferir`.
    When the lâmina's single fee is in (0, 5] and NEWER than the Extrato (`lamina_newer`), the lâmina is the headline
    (`headline.kind = "lamina_mais_recente"`, its rate and date, `fee_status` `lâmina mais recente que o Extrato; a
conferir`) and `extrato_beside` carries the Extrato's value as filed (`filed_value`, a plain number) with its
    `as_of`. Since 1.5 (owner, 2026-10-03) the newer lâmina's fee is a disclosed fee like any other: `per_year_brl` is
    set, `counted_as_cost` is true, it is summed and compared with the estimate; the line keeps `needs_manual_check`
    and `headline.sources_differ_label` (`fontes divergem`), and the Extrato value beside it is never summed. In
    `extrato_lamina_beside` `needs_manual_check` is true and neither value is a cost, summed or compared. Nothing is
    rescaled. `scale_flag` (`label` `possível erro de escala no
Extrato`, `factor` 10 or 100, `extrato_lamina_ratio`) is present when the tool's `extrato_scale_factor` is set:
    a flag only. With no lâmina fee (`extrato_to_check`) nothing is shown beside.
12. **ETFs** (1.5, catalog v56). CVM's Extrato, lâmina and cad*fi hold no fee for any of the 178 active ETFs in
    `cvm_etf_registry` (measured 2026-10-03). When no CVM source discloses anything for the CNPJ, the headline is the
    tool's `etf_site*\*`: the "Taxa de administração total" etfsbrasil.com.br prints, a third-party site
(`headline.kind = "etf_site"`, `origin` `etf_site`, `origin_label` `site etfsbrasil.com.br (terceiros)`, `ticker`,
`as_of`the snapshot date,`fee_status`and`basis` `taxa informada pelo site etfsbrasil.com.br (fonte de
    terceiros, não é documento da CVM)`; `disclosed`stays null). A value in (0, 5] is a cost, summed apart in`totals.adm_etf_site_per_year_brl`and, with the disclosed fees, in`adm_fee_per_year_brl`; a 0, a negative or a
value above 5 is `filed_pct_year`with`check_label` (`0 informado; a conferir`, ...), `needs_manual_check`, never
summed (`fund_value_with_etf_site_fee_to_check_brl`). `etf_site`on every line carries the site's value, date,
source and the tool's note; a CVM source, when one exists, always comes first. Since 1.6 it also carries the
site's`nr_cotistas`and`pl_brl` of the same snapshot (`portfolio_fees` `etf_site_nr_cotistas`, `etf_site_pl`),
    whatever the fee's state: descriptive facts, in no total and no fee computation; null when the site printed none.

A line: `line_no`, `cnpj`, `fund_name`, `position_value_brl`, `fee_status`, `reason`, `fund_nav_brl`, `disclosed`,
`headline` (`kind` `fixa` | `faixa` | `zero_informado` | `lamina_mais_recente` | `etf_site`, `rate_pct_year` or the range, `per_year_brl` = position
value x rate, `origin`, `scope_label`, `as_of`, `age_months`, `stale`), `estimate` (`adm_pct_year`,
`adm_per_year_brl`, `perf_pct_year`, `perf_per_year_brl`, `fiscal_reset_suspect`, `month`), `expense_ratio`,
`findings[]`. `totals`: `adm_disclosed_fixed_per_year_brl` and `adm_disclosed_fixed_portfolio_pct`, the range low
and high, `estimate_adm_per_year_brl` and `estimate_adm_portfolio_pct` (kept apart), `fund_value_with_fixed_fee_brl`,
`fund_value_with_fee_range_brl`, `fund_value_with_filed_zero_brl`, `fund_value_with_implausible_fee_brl`,
`fund_value_with_lamina_newer_fee_brl` (a subset of the fixed since 1.5), `fund_value_without_disclosed_fee_brl` (every
line with no usable fee: none, a filed 0, above 5, or an ETF site value to check), and since 1.5 the ETF keys of rule 12
(`adm_etf_site_per_year_brl`, `adm_etf_site_portfolio_pct`, `adm_fee_per_year_brl`, `adm_fee_portfolio_pct`,
`fund_value_with_etf_site_fee_brl`, `fund_value_with_etf_site_fee_to_check_brl`, `known_fee_incl_etf_site_fund_value_pct`). Assumption: the rates are percent a year (`fee_units`; CVM's XML
specification says so for the Extrato).

`summary` (1.8), "Quanto a carteira paga em taxas": the totals above, their coverage and what is left out. `title`,
`basis`, `n_fund_lines`, `fund_value_brl`, `fund_value_portfolio_pct`; `adm_disclosed_fixed_per_year_brl` and
`adm_disclosed_fixed_portfolio_pct` (null when no line has a fixed fee, so a 0 never reads as "no cost"); the range
low and high in R$ and as `_portfolio_pct` (null without a range line); `adm_etf_site_per_year_brl`,
`adm_etf_site_portfolio_pct` and `etf_site_label` (the third-party ETF fee, its own sum, never "divulgada"; the
summary carries no total that adds it to the disclosed fees); `coverage_fixed_fund_value_pct`,
`coverage_range_fund_value_pct`, `coverage_etf_site_fund_value_pct`, `coverage_without_fee_fund_value_pct` (shares
of the fund value, not fee rates); `estimate_adm_per_year_brl`, `estimate_adm_portfolio_pct` and `estimate_label`
(apart, never added to a disclosed fee); `not_included[]` (`id`, `text`, `line_nos`, `value_brl`): `performance`
(variable, shown per fund as filed, never summed), `carregamento_pgbl` (not public), `spread_credito_direto` (the
direct-credit lines and their value), `sem_taxa` (lines with no usable fee and their value), and
`fundos_investidos` when `underlying` is not empty (Res. CVM 175, art. 98).

## `look_through`

`cda_month`, `max_depth`, `lines[]`, `shared_exposure`. From `portfolio_lookthrough`, one call per
fund: `depth` 0 is the fund's own holdings, a row is a leaf unless its `asset_kind` is `fund_quota`
(looked through; its holdings are the rows below).

- `lines[]`: `status` (`complete`, `partial`, `no_holdings`, `unknown`), `exposures[]` (`via`
  path, `depth`, `block`, `asset_kind`, `asset_key`, `asset_name`, `isin`, `issuer_cnpj`,
  `issuer_code`, `tp_aplic`, `tp_titpub`, `indexer_code`, `taxa_texto`, `maturity`,
  `weight_in_line`, `exposure_brl` = position value x `weight_in_root`, `portfolio_pct`, `not_opened_fund`,
  `period`, `sources`), `fund_nodes[]` (the funds on the way, with `expanded` and
  `not_expanded_reason`), `explained_weight` and `unexplained_weight` (what no ingested CDA block
  explains: cash, derivatives, blocks 3, 5, 7, 8; negative when liabilities and derivatives sum
  above the fund value; never filled), `rows_without_weight` (a NAV on the path unknown),
  `n_cycle_rows_skipped`. `no_cda_filing` is `no_holdings` (FIDC and FII file no CDA).
- `shared_exposure`: `economic_group_assessed` (always false) and `note`, `groups[]` with
  `kind` (`mesmo_ativo`: same asset key or ISIN; `mesmo_emissor_raiz_cnpj`: same 8-digit CNPJ
  root; `mesmo_codigo_emissor_b3`: same ISIN characters 3 to 6; `mesmo_fundo_investido`: the
  same fund held by two lines), `label`, `line_nos`, `lines[]` (`exposure_brl` per line,
  `direct`), `total_exposure_brl`, `total_exposure_portfolio_pct`. Totals of different kinds describe the same positions: do not
  add them. The Treasury is not an issuer group (its ISIN code and repo collateral are left out of `mesmo_codigo_emissor_b3`).

* `top_exposures[]`: the same asset summed across lines (direct included), funds not opened and the current account
  left out: `asset_key`, `asset_name`, `isin`, `exposure_brl`, `portfolio_pct`, `line_nos`, `sources`.

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
`abnormal_movement` (a pointer to `movement`), `lines[]` (`signals[]` with the screen's own row and `screen` /
`params`, `unknown_screens`). A signal is not a verdict, and no signal is not a health
certificate. `screen_dormant_funds` is called twice, pinned (`p_dormancy = empty_shell`;
`p_min_nav = 1000000000`): a parked fund below R$1bn is not covered.

## `movement`

_Movimento incomum_ (`src/portfolio/movement.py`, one `portfolio_movement` call per 200 funds, for ONE month). The SQL owns
the statistics (`31_api_portfolio.sql`, `docs/reference/API.md`); the engine recomputes none of it, applies the owner's
rules about where a level may appear, and checks the served level against the served `z`.

- **Definition** (`definition`): the fund's monthly **quota return**, month-end `vl_quota` over the previous month's
  (`fact_fund_monthly`, the one stable subclass; no NAV change), against the same return over every FI fund of its
  **ANBIMA class as filed in the CVM Extrato** (its newest filing, `class_note`). The class mean and sample sd are taken on
  values **winsorized** at the class's 1st and 99th percentile of the month; the fund's own value is not winsorized.
  `z = (own - mean) / sd`.
- **Levels** (`levels_note`, `thresholds`): `atencao` when `|z|` is strictly above 2 (**table only**), `forte` when strictly
  above 3 (**text**, and `investigator_trigger` true for the later Investigator), `normal` otherwise (exactly 2 is normal,
  exactly 3 is `atencao`), `nao_avaliado` when the fund could not be judged. Measured on production 2026-10-03, among
  the evaluated fund-months: `atencao` or `forte` 5.2% to 5.7%, `forte` 2.4% to 2.9% (six months, 2025-12 to 2026-09).
- `status`, `reason`, `errors`; `month`, `note` (not a forecast, verdict or recommendation), `counts`
  (`funds`, `normal`, `atencao`, `forte`, `nao_avaliado`), `investigator_trigger_line_nos`.
- `lines[]`, one per fund line with a CNPJ: `line_no`, `cnpj`, `fund_name`, `month`, `class` / `subclass` (the filed label
  split at its first `' - '`, display only), `class_as_filed` (the peer group), `class_as_of`, `n_peers` (funds of the class
  with a return that month, the fund included), `min_peers` (30), `own_value_pct`, `class_mean_pct`, `class_sd_pct`,
  `class_p01_pct`, `class_p99_pct`, `z` (4 decimals), `level`, `level_label` (`normal`, `atenção`, `forte`, `não avaliado`),
  `investigator_trigger`, `in_table` (atencao or forte), `in_text` (forte only), `reason` (Portuguese: what was compared, or
  why the fund is `nao_avaliado`), `sources`.
- **Not evaluated, never skipped**: fewer than 30 peers, a class with sd 0, no class (fund outside the Extrato, which covers
  about 84% of the active FI funds, or no `classe_anbima`), no return (no quota in both months, a quota-subclass change), an
  ETF, FIDC, FII, FIP or FIAGRO, a month that is not complete, a CNPJ the function did not return, a refused call (the
  section is `unknown`, with the verbatim error). There is no fallback to a wider class. A level the served `z` contradicts
  (beyond the 4-decimal rounding) becomes `nao_avaliado` and says so. Lines that are not funds with a CNPJ (shares, Tesouro,
  cash, unidentified) are in `not_applicable_lines[]` with a reason.

## `concentration`

1.7. Sums of statement values only (`source = "statement"`); the section is `partial` with `reason_codes`
`gestor_sem_api` and `liquidez_sem_api` until SILO serves those.

- `issuer`: direct credit (`CRA`, `CRI`, `debênture`, `CDB`, `LCI`, `LCA`, and an `outro` line whose name prints
  `CDCA`) grouped by the issuer **as printed**: the line's name without the instrument type and the registry code,
  accent-free upper text. `label` "emissor como impresso no extrato; grupo econômico não avaliado", `basis`,
  `direct_credit_value_brl`, `direct_credit_portfolio_pct`, `groups[]` (`issuer_as_printed`, `line_nos`, `tipos`,
  `value_brl`, `portfolio_pct`, `direct_credit_pct`), `not_printed_line_nos`. Never an economic group.
- `maturity_ladder`: lines with a printed maturity (`vencimento`, or a Tesouro maturity in `codigo`) by time to
  maturity from the position date: `buckets[]` (`vencido ou vence na data`, `até 1 ano`, `de 1 a 2 anos`, `de 2 a 5
anos`, `de 5 a 10 anos`, `acima de 10 anos`: `value_brl`, `portfolio_pct`, `n_lines`, `line_nos`), `no_maturity`,
  `sum_check_brl` (0 within a cent).
- `fgc`: CDB, LCI and LCA summed per issuer as printed, `above_limit` above `limit_brl` (250000.0), `excess_brl`;
  `label` "a conferir: limite por CPF e instituição; o extrato consolidado pode ter mais de um titular", `rule`
  (Regulamento do FGC, Anexo II da Resolução CMN nº 4.222/2013, art. 2º: CDB, RDB, LC, LCI, LCA, LCD covered; LF,
  CRA, CRI, debêntures and fund quotas not), `scope_note`, `n_above_limit`.
- `manager` (1.9): the fund lines with a CNPJ summed by the filed `gestor_id` of `portfolio_fund_terms`, never by
  name: `label`, `basis`, `status`, `reason_code`, `fund_value_brl`, `fund_value_portfolio_pct`, `groups[]`
  (`gestor_id`, `gestor_name`, `names_as_filed`, `line_nos`, `n_lines`, `value_brl`, `portfolio_pct`,
  `fund_value_pct`, `sources`), largest first, `without_gestor_line_nos` / `without_gestor_value_brl` (no gestor
  filed: `partial`, `gestor_nao_informado`), `unanswered_line_nos` (the call failed for them). A PGBL / VGBL wrapper
  counts under its fund's manager. Before 1.9: `{status: "unknown", reason_code: "gestor_sem_api"}`.
- `fund_liquidity` (1.9): `{status, reason_code, reason, section: "liquidity"}`, a pointer to the `liquidity`
  section.

## `allocation`

1.8. The portfolio by asset class, from the type the statement prints for each line (`tipo`); an `outro` ticker
takes the class SILO's `lookup` gave it (`ação`, `cota de fundo listada`), never one read from the name; direct credit
is `crédito privado direto` (the `concentration.issuer` rule). `source = "statement"`, `basis`, `portfolio_value_brl`,
`classes[]` (`asset_class`, `value_brl`, `portfolio_pct`, `n_lines`, `line_nos`), largest first, with `sem
classificação` always last, even at zero; `sum_check_brl` (0 within a cent).

## `liquidity`

1.9. How fast each line can turn into cash, by the redemption terms as filed (`portfolio_fund_terms`: CVM Extrato,
else lâmina) and the statement's type. `title`, `source`, `basis`, `days_note` (business and calendar days are never
converted: a D+N in calendar days sits in the bucket of its N), `note` (no sale price, discount or market depth),
`thresholds_days` (`d5` 5, `d30` 30), `portfolio_value_brl`, `buckets[]` (`bucket_id`, `bucket`, `value_brl`,
`portfolio_pct`, `n_lines`, `line_nos`, `lines[]` with the filed terms and `sources`), in this order: `d0_d5` (D+0
a D+5), `d6_d30`, `acima_d30` (payment days as filed), `lockup` (`qt_dia_resgate_cotas` above 0 wins over the
payment days), `fundo_sem_prazo` (a fund with no terms filed: closed-end FIDC, FII, FIP, or not filed;
`prazo_nao_informado`), `credito_direto` (no liquidity before maturity), `titulos_publicos`, `bolsa` (ETF and
shares), `caixa`, `sem_classificacao` (unidentified, or the terms call failed: never `fundo_sem_prazo`).
`above_d30_parts` / `above_d30_total_brl` / `above_d30_total_pct`: `acima_d30` + `lockup` + `fundo_sem_prazo` +
`credito_direto`. `evaluated` (false when the terms call failed for every fund: `status` `unknown`, the risk row
`nao_avaliado`), `unanswered_line_nos`, `sum_check_brl` (0 within a cent).

## `risks`

1.8, "Principais riscos". Built last, from the other sections: every value is a field of another section
(`source_path`) or a sum of statement values, every severity comes from the fixed thresholds in
`src/portfolio/risks.py` (`THRESHOLDS`, also in the section and printed in the report's methodology), every
explanation is a fixed text. `title`, `note` (no forecast, no recommendation), `severity_rule`, `thresholds`,
`counts` (`atencao`, `moderado`, `baixo`, `nao_avaliado`, `nao_se_aplica`), `rows[]`. A row: `id`, `risk`, `status`
(`avaliado` | `nao_avaliado` | `nao_se_aplica`, with `status_label`), `unit` (`pct` | `count`) and the value in
`value_pct` or `value_count`, `subject`, `source_path`, `severity` (`atencao` | `moderado` | `baixo`, strictly above
the threshold) and `severity_label`, `thresholds`, `explanation`, `reason_code` and `reason` (the fixed text, for a
row not evaluated or not applicable), `line_nos`, `sources`, `text_allowed`, and where it applies
`value_brl_detail` (+ `_label`), `check_label`, `parts`, `assessment`, `table_only`. No row is ever dropped.

| `id`                         | Value                                                                                                                                                    | atenção above | moderado above |
| ---------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------- | -------------- |
| `concentracao_emissor`       | largest direct-credit issuer as printed, % of the portfolio                                                                                              | 10%           | 5%             |
| `concentracao_fundo`         | largest fund position, % of the portfolio                                                                                                                | 25%           | 15%            |
| `credito_privado`            | direct credit, % of the portfolio                                                                                                                        | 30%           | 15%            |
| `credito_sem_fgc`            | direct credit the FGC does not cover (CRI, CRA, debêntures, CDCA, and CDB/LCI/LCA above R$ 250 mil per printed issuer), % of the portfolio, "a conferir" | 20%           | 10%            |
| `fgc_acima_limite`           | printed issuers above R$ 250 mil, a count                                                                                                                | 0             | —              |
| `vencimentos`                | the year with most value maturing, % of the portfolio                                                                                                    | 40%           | 20%            |
| `indexador`                  | largest indexer group (inflação, pré-fixado, pós-fixado, renda variável, câmbio), % of the portfolio, every group in `parts`; a fact, no forecast        | 80%           | 60%            |
| `reapresentacoes`            | restatements of the portfolio's FIDC and FII in the window, a count                                                                                      | —             | 0              |
| `movimento_anormal`          | funds at the strong level, a count; atenção with one, moderado with only attention-level funds                                                           | 0             | —              |
| `liquidez`                   | `liquidity.above_d30_total_pct` (beyond D+30, lock-up, funds without terms, direct credit), % of the portfolio (1.9; `nao_avaliado` before)              | 50%           | 30%            |
| `concentracao_gestor`        | largest manager by filed `gestor_id`, % of the portfolio (1.9)                                                                                           | 40%           | 25%            |
| `credito_situacao`           | CRA/CRI whose registry `situacao` is not `Adimplente`, a count (1.9)                                                                                     | 0             | —              |
| `credito_vencimento_diverge` | CRA/CRI whose statement maturity differs from the registry's, a count, "a conferir" (1.9)                                                                | —             | 0              |
| `credito_preco_marcacao`     | largest gap between a debenture's statement price and the funds' CDA mark, % (1.9; information, never a price verdict)                                   | —             | 5%             |

Rows are ordered evaluated first (atenção, moderado, baixo), then not evaluated, then not applicable. The movement
row keeps the owner's rule that the attention level is a table row: its count of such funds is under `table_only`,
and `text_allowed` is false when only that count sets the severity. The section is `partial`
(`riscos_nao_avaliados`) while any row is not evaluated.

## `returns`

1.10, return per position (`src/portfolio/returns.py`). A fact per asset over a past period: no threshold, no
portfolio total, no mean, median or ranking, no recommendation (`note`). Keys: `position_date`, `end_month` (the
position month when the position date is the month's last calendar day, else the month before, as `movement`),
`windows[]` (`id` `12m` | `6m`, `months`, `base_month`, `end_month`, `annualized` false, `fee_share_of_annual`
1 | 0.5, `volatility_note`, `note`), `definition`, `gross_note`, `sharpe_drag_note`, `drawdown_note`,
`performance_note`, `cdi` (`series`, `sgs_code`, `unit`, `convention`, `n_rates`, `first_date`, `last_date`,
`status`, `reason_code`, `sources`), `lines[]`, `n_lines`, `n_evaluated`, `n_not_evaluated`, `coverage`
(`{12m, 6m}`: `evaluated_value_brl`, `coverage_portfolio_value_pct`, `n_evaluated`; a share of the statement's
value, not a return).

A line (every statement line, in order): `line_no`, `linha_extrato`, `tipo`, `cnpj` (funds), `ticker` (tickers),
`name`, `valor_brl`, `basis`, `without_distributions`, `status` (`avaliado` | `nao_avaliado`), `reason_code` and `reason` (a line not evaluated), `fee`, `performance_fee_filed`, `notes[]`,
`month_ends[]` (`month`, `date` (null for a fund: `fund_nav` serves the month, not the quota's day), `value`,
`null_reason`), `windows` (`{12m, 6m}`), `sources` (the statement line and the series call).

| `basis`                     | Series                                                                              | Rule                                                                                                                            |
| --------------------------- | ----------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| `cota_fundo`                | `fund_nav(p_cnpj, p_from, p_entity_type 'fi')`, `quota` per month                   | `fundo` of family `fi`. No `p_to`: the series ends at the family's latest complete period, so a month not served is missing.    |
| `close_total_return`        | `quote_history(..., p_fields [close_total_return, close_total_return_null_reason])` | `ação` (or `outro` of class equity). A null is `retorno_total_nulo` with its reason, never the price return.                    |
| `close_sem_proventos`       | `quote_history(..., p_fields [close])`                                              | `FII` with a ticker; `ETF` that `lookup` found on the cash tape. "Sem proventos": an ETF that distributes is understated.       |
| `last_price_etf_renda_fixa` | `trade_consolidated_history(p_ticker, p_from, p_to)`, `last_price`                  | `ETF` known only from the ETF registry (not on COTAHIST). Tool unknown or refused: `etf_rf_sem_api`. `ref_price` is never read. |
| `curva_securitizadora`      | `portfolio_credit_returns(p_codes, p_end_month, p_series, p_classes)`, `factor`     | 2.1. `CRA` / `CRI` matched in the CVM register (`credit.match_kind` `securit_cetip`). A window's value is 1 at its base month times each month's factor; a month with a `month_flag` makes the window `nao_avaliado` with that flag as its code (`mes_ausente` is `serie_incompleta`). Not a market price; out of the contribution sum. |
| null                        | none                                                                                | Tesouro, CDB, LCI, LCA, debênture, CRA or CRI not matched, FIDC (tranche unknown), FIP, cash, unidentified line: a fixed code.   |

The month-end value of a ticker is its last session in the month on or before the position date (`date` says
which). A window needs all its month-ends (13 for `12m`, 7 for `6m`), else `serie_incompleta` with
`missing_months`.

`fee` is the fee block's own headline, never fetched again: `status` (`ok` | `nao_avaliado` | `nao_se_aplica`),
`reason_code` (`sem_taxa_utilizavel` for no headline, a range, a filed 0 or above 5, or an ETF site fee not
counted as a cost; `taxa_nao_aplicavel` for a share), `rate_pct_year`, `kind`, `fee_status`, `origin`, `as_of`,
`sources`. Usable kinds: `fixa`, `lamina_mais_recente`, and `etf_site` with `counted_as_cost`. A fund whose
disclosed fee has a performance part (`performance_fee_filed`) keeps the administration fee only and carries the
note "o retorno líquido já desconta a performance provisionada; a taxa por ponto mostrada considera só a
administração".

A window: `status`, `reason_code`, `reason`, `base_month`, `end_month`, `base_date`, `end_date`,
`base_value`, `end_value`, `n_observations`, `net_return_pct` (the period's return; 6 months is not annualized),
`cdi_pct`, `cdi_base_date`, `cdi_end_date`, `cdi_n_rates`, `cdi_reason_code`, `net_minus_cdi_pp`,
`volatility_annual_pct` (sample standard deviation of the monthly returns × √12) and `volatility_note`
("12 observações; estimativa ruidosa" | "6 observações; muito ruidosa"), `max_drawdown_pct` (≤ 0, on month-end
values), `max_drawdown_peak_month`, `max_drawdown_trough_month`, `max_drawdown_note` ("em fechamentos mensais;
quedas dentro do mês não aparecem"), `fee_status`, `fee_reason_code`, `fee_pct_period` (the annual fee, half of it
for `6m`), `gross_return_est_pct` (net + `fee_pct_period`, an estimate), `fee_per_point`
(`fee_pct_period` ÷ gross, a ratio; null when the gross is exactly 0), `fee_per_point_excluded_from_aggregates`
(true when the gross is ≤ 0: a negative value is shown as computed and never enters a mean, median or ranking),
`fee_per_point_note`, `sharpe_drag` (annual fee ÷ annualized volatility, both windows: the Sharpe the fee takes; null with a "não aplicável" note when the annualized volatility is below 1% a.a., a cash-like fund, owner 2026-10-05)
and `sharpe_drag_note`, `notes`, `sources`; where it applies, `missing_months` and `null_reasons`.

The CDI is `macro_series('CDI', base month, position date)`, compounded by B3's DI-factor convention: daily factors
`1 + rate/100` truncated at 16 decimals, multiplied over the rates dated from the base date inclusive to the end
date exclusive, the product rounded to 8. A ticker's dates are its sessions; a fund's are the last business day
of the base and end months in the CDI's own calendar.

**Retroactive contribution** (1.15, owner 2026-10-06; `returns.contribution`). A statement gives positions at one date
and no flows, so the contribution is back-cast, never a measured attribution. Keys: `label` ("contribuição retroativa"),
`note`, `windows` (`{12m, 6m}`). A window: `status` (`avaliado` | `nao_avaliado` with `reason_code` `linhas_sem_retorno`),
`covered_return_pct`, `coverage_portfolio_value_pct` (the same share as `coverage`), `start_value_brl`, `end_value_brl`,
`n_lines`, `lines[]` (`line_no`, `linha_extrato`, `valor_brl`, `net_return_pct`, `start_value_brl`, `start_weight_pct`,
`contribution_pp`). For each evaluated line: start value = current value ÷ (1 + r), r the window's `net_return_pct`;
weight = its start value ÷ the sum of the start values of the evaluated lines; contribution = weight × r. The
contributions add up to `covered_return_pct`, the return of the evaluated lines taken together (sum of end values ÷ sum
of start values − 1). It assumes no purchase or redemption in the window. The only total is that of the evaluated part,
always next to its coverage; there is no portfolio return, mean or ranking, and lines stay in statement order.

"% do CDI" (1.13, #606 addendum Q36). A line's `benchmark` is the filed benchmark the fee block read
(`fees.lines[i].benchmark_as_filed`): `extrato` (the Extrato's `PARAM_TAXA_PERFM`, the performance fee's index and the
Extrato's only benchmark column), `lamina` (`INDICE_REFER`, one value when every class filed the same one),
`lamina_n`, their dates, `cdi_like`, `reason_code`, `matched`, `rule_version` (of `src/portfolio/rules/benchmark_cdi.yaml`),
`sources`; both as filed, never normalized in the output. `src/portfolio/benchmark.py` matches them exactly, after
trimming, collapsing whitespace and upper-casing, against the rule file's `accepted` list (`CDI`, `DI1 - DI DE UM DIA`,
`CDI252`, `CDI 100%`, `DI-CETIP`, `CDI DIARIO`, `(CDI252+0%)`); every other spelling is not CDI-like. A window's
`pct_of_cdi` is `net_return_pct ÷ cdi_pct × 100` (4 decimals) only when `cdi_like` and the window's CDI is above zero;
otherwise null with `pct_of_cdi_reason_code`: `pct_cdi_so_fundos` (not a fund), `referencia_nao_servida` (no fee row
carried the benchmark), `referencia_nao_informada`, `referencia_nao_cdi`, `referencia_diverge` (the two documents, or the
lâmina's classes, disagree, or some classes filed one and some none), `cdi_indisponivel` or `cdi_nao_positivo`. `net_minus_cdi_pp` is kept in every case.

**Direct credit** (2.1, #766). A curve line's `fee` is `nao_se_aplica` with `taxa_credito_sem_taxa_adm`. Its
`benchmark` is the rate the statement prints (`taxa_texto`), never the register's free-text `taxa_juros`: `cdi_like`
when it contains CDI, else `pct_of_cdi_reason_code` `credito_nao_cdi` (IPCA or prefixado) or `taxa_nao_informada`, with
`pct_of_cdi_credit_note` as the report's one footnote. The contribution lists the curve line in `excluded_lines`
(`metodo_fora_do_total`) and covers only the lines it sums.

`contracted` (method C, a CDB, LCI, LCA or CDCA; `src/portfolio/contracted.py`): `label` ("retorno contratado"), `basis`,
`taxa_texto` (as printed), `rate` (`indexer` `pct_cdi` | `cdi_spread` | `ipca_spread` | `prefixado`, and `value`; null
when the text matches none of the four shapes or the OCR did not check it), `data_inicial` and `data_inicial_source`
(`data_inicial` from the BTG detail table, else the spreadsheet's `data_aplicacao`), `vencimento`, `status`,
`reason_code`, `notes`, `windows` (`{12m, 6m}`), `sources`. A window: `status`, `reason_code`, `base_month`,
`end_month`, `base_date`, `end_date` (the CDI calendar's month-ends), `n_business_days` (CDI rates from base inclusive
to end exclusive), `accrual_pct`, `index_pct` (the CDI or IPCA of the window), `rate_factor_pct`, `cdi_pct`,
`net_minus_cdi_pp`, `pct_of_cdi` (only for a rate on the CDI), `pct_of_cdi_reason_code`, `approximation` (IPCA only),
`sources`. % do CDI p: product of `1 + cdi/100 x p/100`, each truncated at 16 places, rounded to 8; CDI + s: the DI
factor times `(1 + s/100)^(du/252)`; prefixado x: `(1 + x/100)^(du/252)`; IPCA + s: the product of the window's IPCA
months times `(1 + s/100)^(du/252)`, labelled an approximation. Not computed when the paper starts after the base date,
matures before the end date, has no initial date or no legible rate. It is never a measured return: the line stays
`nao_avaliado`, and it is counted only in `coverage.contracted_*`, shown only in the annex.

## `tax`

1.11, fee paid and tax per position (`src/portfolio/tax.py`, issue #613). Rules: one YAML per instrument type in
`src/portfolio/rules/tax/` (`cdb`, `lci`, `lca`, `cri`, `cra`, `debenture`, `debenture_incentivized`, `fii`, `shares`,
`etf_equity`, `etf_fixed_income`, `fund_long`, `fund_short`, `fund_equity`, `pension_regressive`,
`pension_progressive`) plus `iof.yaml` and `person.yaml`, schema `silo.tax_rule/0.1` (section 5 of the #611 note).
Every rate, article, URL and quote is the note's; Tesouro Direto, FIDC and FIP have no file (`not_covered`). Keys:
`status`, `reason`, `errors`, `reason_codes`, `position_date`, `note`, `labels` (`estimate` "estimativa", `check`
"a conferir", `info` "informativo; não é recomendação", `exempt` "isento", `date_missing`, `regime`), `rules_note`,
`rules_files[]` (`file`, `instrument`, `version`, `valid_from`, `valid_to`, `in_force`, `sha256`, `not_verified`),
`not_covered[]`, `lines[]`, `person`, `n_lines`, `n_with_rule`, `n_without_rule`, `n_tax_estimated`, `n_fee_estimated`.
No portfolio total of tax.

A line (every statement line, in order): `line_no`, `linha_extrato`, `tipo`, `valor_brl`, `fee`, `holding`
(`data_aplicacao`, `days_held`, `text`, `sources`), `tax`, `pension` (PGBL/VGBL lines only), `optimization[]`, `iof`,
`a_conferir[]` (`id`, `text`, `label` "a conferir", `decides_rate`, `rules_file`: every `engine_cannot_observe` item
of the line's rule files, plus `data_aplicacao` when the rate depends on a date not printed), `sources`.

- `fee`: the fee block's headline, never fetched again. `status` `estimada` (`per_year_brl`, `rate_pct_year`: a fixed
  disclosed fee, a newer lâmina's, or an ETF site fee counted as a cost, with `third_party`),
  `faixa` (`per_year_min_brl`, `per_year_max_brl`, `rate_min_pct_year`, `rate_max_pct_year`), `sem_taxa` (no usable
  fee: `fee_status` carries the fee block's label) or `nao_se_aplica` (no fee line: shares, credit, Tesouro); `label`
  "estimativa", `basis`, `kind`, `notes` (nothing added for a fund of funds, Art. 98; no performance-fee estimate),
  `loading` (pension lines: `nao_informado`, the statement prints no loading fee), `sources`.
- `tax`: `status` `aliquota_hoje` (one rule, one rate, no hidden condition), `condicional` (one rule whose rate a
  condition the statement cannot show decides: `outcomes`), `faixa` (`bracket.text` is "alíquota entre X% e Y%
  conforme o prazo; data de aplicação não informada, a conferir", or the ETF repricing-term bracket), `candidatos`
  (more than one rule file applies: `candidates[]`, `bracket`), `isento`, `previdencia` or `sem_regra`;
  `selection_reason`, `instrument`, `rules_file`, `candidates[]` (`instrument`, `label`,
  `rules_file`, `event`, `base`, `exempt`, `table`, `unit`, `rates_pct`, `rate_today_pct`,
  `article`, `rule_source`), `rate_today_pct` (0 when `isento`), `exempt`, `article`, `rule_source` (`rules_file`,
  `source_id`, `act`, `article`, `url`, `quote`), `bracket`, `outcomes`, `other_events[]`, `come_cotas[]` (a mark:
  `applies` true, false or null, `text`, `article`), `estimate`, `reason_code`, `reason`.
- `tax.estimate`: `label` "estimativa", `tax_brl` = rate today x `gain_12m_brl`, `gain_12m_brl` = value x r / (1 + r)
  with r the return block's 12-month `net_return_pct`, `net_return_12m_pct`, `rate_pct`, `basis`, `reason_code`,
  `reason`, `sources`. A figure only for `aliquota_hoje` with `data_aplicacao` printed and on or before the window's
  base date, and a positive gain; otherwise null with the code. A date is never assumed.
- `pension`: `plan` (`PGBL` | `VGBL` | null, from the statement's table heading), `regime` (always null),
  `base` (PGBL on the whole redemption, VGBL on the income only), `regressive`
  (`table` of `over_years`/`up_to_years`/`rate_pct`, `rate_today_pct` only with a printed start date, `text`),
  `progressive` (`advance_rate_pct` 15, `text` "15% antecipado; ajuste anual pela tabela progressiva, depende da renda
  total; não estimado"), `irrevocable` ("irretratável"), and their `rule_source`s.
- `optimization[]`, each `label` "informativo; não é recomendação": `proxima_faixa` (`date`, `days`, `from_pct`,
  `to_pct`, "em N dias a alíquota cai de X% para Y%", only with the date), `equivalencia_bruta` (exempt lines:
  `brackets[]` of `cdb_rate_pct`, `factor` = 1 / (1 - alíquota), `equivalent_pct` for "N% do CDI" or "N% a.a." only;
  one bracket when application date and maturity give the term, else the four) and `come_cotas`. No imperative verb.
- `iof`: null unless the application date shows fewer than 30 days held: `days_held`, `rate_pct` (0 for the art. 32
  §2º zero-rate operations, else null), `text` ("IOF regressivo nos primeiros 30 dias; a conferir": the note does not
  quote the Anexo's table), `article`, `rule_source`.

`person`: `flags[]` (`dividends`, `jcp`: `line_nos` of share lines, `rate_pct`, `text`, `article`, `computed` false),
`minimum_tax` (`text` "depende da renda total anual; fora do escopo", `excluded_income[]`, `computed` false),
`a_conferir[]`, `rules_file`. No figure.

## `equivalents`

1.13, the market equivalent per fund line (`src/portfolio/market_equivalent.py`, #609). For a `fundo` line whose ANBIMA
class and FUNDO_COTAS (as the fee comparison read them from the Extrato) are mapped in the reviewed YAML
(`src/portfolio/rules/equivalents/class_index.yaml`, approved pairs only, read in reverse), the equivalent is the
largest active ETF by third-party PL across every index mapped to the class (`portfolio_equivalents`, catalog v68). The
served pairs decide (the SQL reads only approved ones); `class_indices_rules` holds the YAML's approved indices as this
engine read them and `pairs_match_rules` is false while the database serves another version of the list (a deploy
lag, never a failure). The class is read only from a comparison row the fee block accepted, and the flagged ETF must
be the largest by PL, else `resposta_inconsistente`. Keys: `status`, `reason`, `errors`, `reason_codes`, `label` ("equivalente de mercado; não é
recomendação"), `as_of` (the run's UTC date, as the fee comparison), `end_month` and `windows[]` (the return block's),
`choice_note`, `class_note`, `band_note`, `lines[]`, `n_fund_lines`, `n_found`, `n_without`,
`found_value_brl`, `coverage_portfolio_value_pct`. No ranking, no "melhor", no instruction.

A line (every `fundo` line): `line_no`, `linha_extrato`, `fund_name`, `cnpj`, `valor_brl`, `classe_anbima`,
`fundo_cotas`, `class_indices`, `class_indices_rules`, `pairs_match_rules`, `n_etfs`, `status` (`encontrado` |
`sem_equivalente`), `reason_code` and `reason` (`equivalente_fora_escopo`, `equivalente_sem_comparacao`, `equivalente_sem_classe`, `equivalente_sem_par`, `equivalente_sem_etf`, `equivalente_sem_pl`,
`equivalente_sem_linha`, `consulta_falhou`, `resposta_inconsistente`), `label`, `etf`, `windows[]`,
`fund_return_status`, `sources`.

- `etf`: `ticker`, `cnpj`, `name`, `underlying_index`, `segment`, `pl_brl` and `pl_as_of` (etfsbrasil,
  third party), `fee_pct_year` and `fee_as_of` (the same source as the fee comparison's ETF peers;
  `fee_reason_code` `equivalente_sem_taxa` when the site printed none), `in_fee_peers`, `snapshot_source`, `basis`
  (`close_sem_proventos` from `quote_history` `close`, or `last_price_etf_renda_fixa` from `trade_consolidated_history`
  for a `fixed_income_br` ETF; never `ref_price` or `close_adj`), `without_distributions` (true),
  `note`, `pl_rank`, `sources`.
- `windows[i]` (`12m`, `6m`, the return block's dates): `etf_net_return_pct` (or `etf_reason_code`
  `equivalente_sem_retorno` with `etf_series_reason_code`, e.g. `serie_incompleta`, `etf_rf_sem_api`),
  `fund_net_return_pct` (the return block's, or `fund_reason_code`), the class distribution
  (`class_return_distribution` for the class and FUNDO_COTAS at the return block's end month: `class_p25_pct`,
  `class_median_pct`, `class_p75_pct`, `class_n_funds`, or `class_reason_code` `distribuicao_classe_nao_avaliada`),
  `etf_minus_median_pp`, `fund_minus_median_pp`, and the position in the distribution, `etf_band` / `fund_band`
  (`abaixo_p25`, `p25_mediana`, `mediana_p75`, `acima_p75`) with `band_note` (a position in the
  class's distribution, not a ranking; `class_return_distribution` serves quartiles, not an exact percentile rank).

## `investigation`

Engine 1.12 (owner's resolution of #605, 2026-10-05; sources from `docs/reference/research/credit-issue-documents.md`,
#604). Built by `src/portfolio/investigator/`, placed after `equivalents` (1.13), in `section_status`. It runs only when the engine
is given an investigator: the server builds one with `SILO_INVESTIGATOR=on` (the Worker's var, `on` in the deployed
demo since 2026-10-06, owner's Q49, which replaced the supervised live run of #605 Q37), the CLI never does,
so the demo fixture carries the section off (`status` `not_applicable`, reason code `investigador_desligado`). A
failure of the investigator is `status` `unknown` (`investigador_falhou`), never a failed report.

**Triggers** (Q33): a CRA, CRI or debenture line not identified (`credito_nao_identificado`) or with
`vencimento_diverge` (`credito_vencimento_diverge`); every FIP (`fip`); every line in
`movement.investigator_trigger_line_nos` (`movimento_forte`; this is how an FII is read, only on a trigger).

**Sources, in order.** A CRA or CRI: Fundos.NET certificados (`listarFundos?term=<ISIN>&paraCerts=true`, then the
certificate's list with `paginaCertificados=true`; categories Termo (17) and Aditamento (19) first: the original
termo and the newest aditamentos, at most 3 documents; else offer (16) and rating (36) documents). Fundos.NET
matches the ISIN, not the CETIP code: the ISIN is `portfolio_instruments`' `cd_isin` (catalog v67, as filed) when it
has the shape of an ISIN, else the statement's code when that is one; a filed `00000` or `NÃO TEM` is never sent, and
without an ISIN the trigger says so in `notes`. A debenture:
RAD escrituras through `company_events` (category "Escrituras e aditamentos de debêntures") when SILO knows the
issuer's CNPJ. A FIP: the newest periodic report on Fundos.NET that reads (structured monthly informe and CDA
skipped). A fund with a `forte` movement: fato relevante, comunicado or relatório gerencial delivered in the
movement month or the two after. When those give no accepted fact: Exa Agent (`EXA_API_KEY`), official domains
first (`cvm.gov.br`, `b3.com.br`, `bmfbovespa.com.br`, `debentures.com.br` and the issuer's, securitizadora's or
manager's site), then the open web; each cited URL is read again through Exa `/contents` and checked like any
document; a page that does not name the asset (its code or ISIN, a debenture's issuer CNPJ, a fund's CNPJ or CVM
name) is discarded (`documento_sem_identificador`), since a quote can be verbatim in a page about another asset.
An item with no such identifier gets no web search. Without the key the section says so (`web_search.available` false, `busca_web_indisponivel`).

**Budget**: `limits.searches_per_trigger` 5 and `limits.searches_per_report` 20, plus a wall clock of 180 s. A
counted search is an FNET certificate lookup, an FNET listing page, a `company_events` call or an Exa Agent run;
downloads and `/contents` reads are not. `searches_used`, `searches_by_kind`. The wall clock is checked before
every search, download, extraction and judge call. A failure of one item (network, an unexpected answer) is a
note on that item; the others keep their facts. An item with no public identifier gets no web search.

**Cost** (owner, #605 Q37): ONE US$1.00 cap per report (`llm.COST_CAP_USD`) covers the report's LLM, the
investigator's LLM and Exa together, on one `CostMeter` the server creates per report. The investigator runs first,
inside the engine, and may book at most US$0.30 of it (`extract.INVESTIGATOR_SHARE_USD`, through `ShareMeter`);
at least US$0.70 stays for the Redator and the Revisor (a complete report cost US$0.31, deploy run 37226627623). Each
LLM call is checked at its worst case before it is made (the extractor and the judge run at low reasoning effort with
8,000 and 3,000 output tokens, the excerpt is at most 40,000 characters); an Exa Agent run at its list price (`low`
US$0.025) and a `/contents` read at US$0.001, then booked at the reported `costDollars`. When the share is spent the
investigator stops: that item and every later one carry "limite de custo do investigador atingido (US$0,30 do teto de
US$1,00 do relatório); a conferir", and the report goes on. `costs`: `usd`, `llm_usd`, `exa_usd`, `share_cap_usd`,
`report_cap_usd`, `note`. The spend is in `X-Silo-Cost-Usd` and in the trace (`invoke_agent investigator` and
`invoke_agent investigator_judge` spans, `app.cost_usd`, `app.exa.calls`, `app.exa.cost_usd`).

**Coordinator** (owner's addendum to #605): the extractor also reads `coordenador`, the Coordenador Líder the issue's
own documents name. A coordinator fact alone does not count as "found", so the web fallback still runs; the domains
of the APPROVED entries it matches in `src/portfolio/rules/investigator/coordinators.yaml` (by CNPJ or printed name,
never from the asset's name; entries are `proposta` until the owner sets `aprovada`) are listed first among the
official domains, and a page on them is labelled `web_coordenador`. `triggers[].coordinator`: `value`, `fact_id`,
`domains`, `list_status` ("aprovada", "proposta, aguarda revisão do dono", "sem entrada na lista revisada"), or null.

**Tiers** (Q31): `A` "verificado na fonte" (the quote, normalized for spaces, accents, case, line breaks and
hyphenation, is in the document text, and the value is in the quote); `B` "conferido por modelo; a conferir" (a
passage resembling the quote is located, and a judge model different from the extractor confirms it supports the
fact); `C` "descartado", counted in `discarded` (`count`, `text` "N fatos descartados", `by_reason{code: {count,
text}}`). In every tier every number of the value, and for B of the quote, must be a number of the document's
passage: enforced in `tiers.assess`, never asked of a model. `models`: `extractor`, `judge`, `tier_b_enabled`
(false when no judge is set or both name the same model), `note`.

- `triggers[]`: `trigger_id`, `line_no`, `kind`, `kind_label`, `tipo`, `identifiers` (public only: code, ISIN,
  securitizadora or issuer CNPJ, fund CNPJ and CVM name), `sources_tried[]`, `notes[]`, `searches_used`,
  `limit_reached`, `message` (never blank: "N fato(s) com citação (nível A: a; nível B: b)", "não encontrado em:
  Fundos.NET, RAD, sites oficiais, busca aberta" listing what was tried, "limite de 20 buscas atingido; a conferir",
  "limite de 5 buscas deste item atingido; a conferir", "tempo do investigador esgotado; a conferir", the cost
  limit message above), `fact_ids[]`, `coordinator`.
- `facts[]`: `fact_id`, `trigger_id`, `line_no`, `field` (`emissor_cnpj`, `lastro`, `devedor`, `garantias`,
  `indexador`, `vencimento`, `rating`, `coordenador`; `empresa_investida`, `participacao_pct`; `evento`), `field_label`, `subject`
  (the series or investee, as the document names it), `value` (as quoted), `quote`, `passage` and `passage_ratio`
  (tier B only), `url`, `document_id` (`fnet:<id>`, `rad:<protocol>`, `web:<sha256 of the URL, 32 hex>`),
  `document_title`, `document_date` (as the source prints it), `read_at_utc`, `read_date`, `source_type` (`fnet`,
  `rad`, `web_cvm`, `web_b3`, `web_snd`, `web_coordenador`, `web_dominio_nao_verificado`, `web_busca_aberta`, labelled from the URL's
  domain by code), `source_type_label`, `tier`, `tier_label`, `fnet_id`, `rad_protocol`, `cross_check`.
- `cross_check` (credit facts with a `credit_match`; else null): `silo_field`, `silo_value`, `agrees` (true or false
  only for a date or a CNPJ of the same series; null for free text or another series), `note`; for `vencimento` also
  `silo_serie`, `document_value_iso`, `statement_vencimento`. A divergence is shown, neither value is changed.
  `counts.divergences` counts `agrees` false.
- `documents_consulted[]`: `document_id`, `source_type`, `url`, `title`, `document_date`, `read_at_utc`, `fnet_id`,
  `rad_protocol`, `status` ("lido" or "não lido"), `error_code`, `cache` (`hit` or `miss`), `sha256` of the text,
  `n_chars`, `trigger_ids[]`.
- `counts` (`triggers`, `facts`, `tier_a`, `tier_b`, `discarded`, `divergences`, `documents_read`,
  `documents_not_read`), `messages[]` (one line per trigger), `web_search`, `tiers`, `note`, `enabled`.

**Cache** (Q35): a document is kept under `docs/<fnet|rad|web>/<id>/<sha256 of the text>.txt`. In the deployed
demo the engine hands new entries to the Worker with the run's trace (`GET /trace/<id>`, key `documents`) and the
Worker writes them to the private R2 bucket of ADR 0003 after checking the hash; there is no read path from R2 into
the engine yet, so each report reads its documents again. The listing is re-queried in every report.

**Privacy**: nothing from the statement but public asset identifiers leaves the engine (no holder, CPF, account,
quantity, value, price or the line's own text), in a URL, a request body or a prompt
(`tests/test_portfolio_investigator.py::test_nothing_from_the_statement_leaves_the_engine`). The report does not
show the section yet.

## The report's view (mapping)

`src/portfolio/report/adapt.py` is this table as code: `python -m src.portfolio.report.build engine.json` maps an
engine document (schema 1.x or 2.x) to the view the Redator, the Revisor and the renderer read, and it computes no
figure (every percent it uses is an engine field). Since 2.0 it adds the return, tax and equivalent blocks'
`*_label`, `rate_text` and pension texts from `src/portfolio/report/labels.py`. The provisional fixture
`tests/fixtures/portfolio/report_provisional_engine_output.json` is the view's original hand-written shape and
still renders. The view's `sections` and `gaps` ("O que não foi possível avaliar") are built by
`src/portfolio/sections.py`. The view holds no holder, account or statement-file identifier. Units agree (`_brl` reais,
`_pct` percent, plain numbers such as `adm_filed_raw` and `age_months` print without a unit).

| Report view                                                                                                                                                                                                                                                                                                                      | Engine (this schema)                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `generated_at`, `valuation_date`, `illustrative`                                                                                                                                                                                                                                                                                 | `generated_at_utc`, `statement.position_date`, `engine.client == "fake"`                                                                                                                                                                                                                                                                                                                                                                                                                |
| `portfolio.total_brl`, `n_lines`, `n_identified` / `n_ambiguous` / `n_unknown`                                                                                                                                                                                                                                                   | `statement.sum_of_lines_brl`, `n_lines`, `identification.counts.*`                                                                                                                                                                                                                                                                                                                                                                                                                      |
| `lines[i]` (`line_id` L<line_no>, `instrument`, `value_brl`, `weight_pct`)                                                                                                                                                                                                                                                       | `statement.positions[i]` (`linha_extrato`, `valor_brl`, `portfolio_pct`) joined to `identification.lines[i]`                                                                                                                                                                                                                                                                                                                                                                            |
| `lines[i].identification` (`status`, `method`, `renamed_from`, `renamed_at`, `candidates`)                                                                                                                                                                                                                                       | `status` (an `identified` line the quota separated is `ambiguous`, from `fund_match.tiebroken_by_quota`), `fund_match.chosen.match_kind`, the `renamed` finding, `fund_match.candidates`                                                                                                                                                                                                                                                                                                |
| `fees.total_disclosed_brl_year`, `total_disclosed_pct_year`                                                                                                                                                                                                                                                                      | `fees.totals.adm_disclosed_fixed_per_year_brl`, `adm_disclosed_fixed_portfolio_pct` (null without a fixed fee)                                                                                                                                                                                                                                                                                                                                                                          |
| `fees.total_estimated_brl_year`, `weighted_estimated_pct_year`                                                                                                                                                                                                                                                                   | `fees.totals.estimate_adm_per_year_brl`, `estimate_adm_portfolio_pct`                                                                                                                                                                                                                                                                                                                                                                                                                   |
| `fees.by_line[i]` `disclosed_pct_year`, `disclosed_brl_year`, `disclosed_origin(_label)`, `disclosed_as_of`, `disclosed_age_months`, `disclosed_stale(_label)`, `disclosed_scope_label`                                                                                                                                          | `fees.lines[i].headline` and `.disclosed` (`rate_pct_year`, `per_year_brl`, `origin`, `origin_label`, `as_of`, `age_months`, `stale`, `stale_label`, `scope_label`)                                                                                                                                                                                                                                                                                                                     |
| `fees.by_line[i]` `fee_status`, `label`, `reason`, `filed_zero_label`, `implausible_label`, `implausible_raw`                                                                                                                                                                                                                    | `fee_status`, `reason`, `disclosed.filed_zero_label`, `implausible_label`, `adm_filed_raw`                                                                                                                                                                                                                                                                                                                                                                                              |
| `fees.by_line[i]` `estimated_pct_year`, `estimated_brl_year`, `estimate_label`, `month`                                                                                                                                                                                                                                          | `fees.lines[i].estimate` (`adm_pct_year`, `adm_per_year_brl`, `label`, `month`)                                                                                                                                                                                                                                                                                                                                                                                                         |
| `fees.by_line[i]` `expense_ratio_pct`, `expense_ratio_period_from/to`, `perf_as_filed`, `terms_as_filed`, `findings`                                                                                                                                                                                                             | `expense_ratio`, `disclosed.perf_as_filed`, `disclosed.terms_as_filed`, `findings`                                                                                                                                                                                                                                                                                                                                                                                                      |
| `fees.by_line[i]` `fee_resolution`, `lamina_newer_label`, `lamina_beside_*` (`label`, `check_label`, `pct_year`, `min_pct_year`, `max_pct_year`, `as_of`, `age_months`, `stale_label`), `extrato_beside_label`, `extrato_beside_value`, `extrato_beside_as_of`, `scale_flag_label`, `scale_factor`, `extrato_lamina_ratio` (1.4) | `fee_resolution`, `headline.basis` for `lamina_mais_recente`, `lamina_beside`, `extrato_beside` (`filed_value`, `as_of`), `scale_flag` (`label`, `factor`, `extrato_lamina_ratio`); `disclosed_pct_year` also holds a `lamina_mais_recente` rate, and since 1.5 its `disclosed_brl_year` too                                                                                                                                                                                            |
| `fees.by_line[i]` `sources_differ_label`, `etf_ticker`, `etf_site_label`, `etf_site_check_label`, `etf_site_raw`; `disclosed_pct_year`, `disclosed_brl_year`, `disclosed_origin(_label)`, `disclosed_as_of` also for an ETF (1.5)                                                                                                | `headline.sources_differ_label`; for `headline.kind = "etf_site"`: `ticker`, `basis`, `check_label`, `filed_pct_year`, and `rate_pct_year`, `per_year_brl`, `origin`, `origin_label`, `as_of`                                                                                                                                                                                                                                                                                           |
| `fees.total_etf_site_brl_year`, `total_etf_site_pct_year`, `total_fee_brl_year`, `total_fee_pct_year` (1.5)                                                                                                                                                                                                                      | `fees.totals.adm_etf_site_per_year_brl`, `adm_etf_site_portfolio_pct`, `adm_fee_per_year_brl`, `adm_fee_portfolio_pct` (null without a summed ETF fee; the last two also need a fixed disclosed fee)                                                                                                                                                                                                                                                                                    |
| `fees.by_line[i]` `etf_site_nr_cotistas`, `etf_site_pl_brl`, `etf_site_as_of`, `etf_facts_label` (1.6)                                                                                                                                                                                                                           | `fees.lines[i].etf_site` `nr_cotistas`, `pl_brl`, `as_of`, `facts_label` (the last two null when neither value is present); rendered as "Cotistas: N; PL: R$ X (etfsbrasil.com.br, site de terceiro, coleta de <data>)"                                                                                                                                                                                                                                                                 |
| `data_dates.ETFSBRASIL` (1.5)                                                                                                                                                                                                                                                                                                    | the newest `headline.as_of` of an `etf_site` fee line, and since 1.6 the `etf_site.as_of` of a line with cotistas or PL: the site is listed as its own source, never as CVM                                                                                                                                                                                                                                                                                                             |
| `fees.underlying[i]`                                                                                                                                                                                                                                                                                                             | `fees.underlying[i]` (`parent_line_id` = its `line_no`, `label_not_added` = `label`)                                                                                                                                                                                                                                                                                                                                                                                                    |
| `lookthrough.shared_exposure[i]` (`key`, `level`, `total_brl`, `total_pct`, `legs`)                                                                                                                                                                                                                                              | the 12 largest `look_through.shared_exposure.groups[i]` (`label`, `kind`, `total_exposure_brl`, `total_exposure_portfolio_pct`, `lines`)                                                                                                                                                                                                                                                                                                                                                |
| `lookthrough.top_underlying[i]`                                                                                                                                                                                                                                                                                                  | `look_through.top_exposures[i]`                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| `indexer.buckets[i]`, `sector.buckets[i]` (`weight_pct`)                                                                                                                                                                                                                                                                         | `indexer.classes[i]`, `sector.sectors[i]` (`portfolio_pct`)                                                                                                                                                                                                                                                                                                                                                                                                                             |
| `restatements.items[i]`                                                                                                                                                                                                                                                                                                          | `restatements.lines[i].restatements[j]`; the delinquency leaf is `leaves[leaf = VL_CRED_EXISTE_INAD]` (`old_num`, `new_num`, `delta`)                                                                                                                                                                                                                                                                                                                                                   |
| `risk_screens` (`screens_run`, `hits`, `not_run`)                                                                                                                                                                                                                                                                                | `risk_signals.screens` (complete count, unknown with reason), `risk_signals.lines[i].signals`                                                                                                                                                                                                                                                                                                                                                                                           |
| `sections.<name>`                                                                                                                                                                                                                                                                                                                | `section_status.<name>` (`lookthrough` is `look_through`, `risk_screens` is `risk_signals`, `abnormal_movement` is `movement` from 1.3); `material_restatement`, `economic_group` from the engine's own notes                                                                                                                                                                                                                                                                           |
| `movement` (`status`, `month`, `definition`, `class_note`, `levels_note`, `note`, `min_peers`, `thresholds`, `counts`, `n_not_fund_lines`)                                                                                                                                                                                       | `movement.*` of the same names (`min_peers` from `thresholds`, `n_not_fund_lines` the length of `not_applicable_lines`); absent from the view for an engine document before 1.3                                                                                                                                                                                                                                                                                                         |
| `movement.by_line[i]` (`line_id`, `fund_name`, `class`, `subclass`, `class_as_filed`, `n_peers`, `own_value_pct`, `class_mean_pct`, `class_sd_pct`, `z`, `level`, `level_label`, `investigator_trigger`, `reason`, `provenance`)                                                                                                 | `movement.lines[i]`, copied                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| `movement.table[i]`, `movement.strong[i]`, `movement.not_evaluated[i]`                                                                                                                                                                                                                                                           | the same lines filtered: atencao or forte (the table, the only place `atencao` is shown), forte (the only fund-level path the text may cite), nao_avaliado (with `reason`)                                                                                                                                                                                                                                                                                                              |
| `provenance[i]` (`id`, `endpoint`, `source`, `data_date`, `failed`)                                                                                                                                                                                                                                                              | `provenance[i]` (`id` = `p<call_id>`, `tool`, `error` is not null); `source` from the tool, `data_date` from the `sources` that cite the call. Since 1.7 the view carries neither `args` nor `error`                                                                                                                                                                                                                                                                                    |
| `lines[i]` `identification.reason`, `reason_code`, `method = "cnpj_extrato"`; `vencimento`, `taxa_texto`, `n_source_lines` (1.7)                                                                                                                                                                                                 | the fixed text of `identification.lines[i].reason_code` (`REASON_TEXT`, never the engine's `reason`), null for an identified line; the statement's facts; the length of `contas`                                                                                                                                                                                                                                                                                                        |
| `sections.<name>.reason`, `reason_codes`; `risk_screens.not_run[i].reason`; `movement.reason`; a failed fee or movement line's `reason` (1.7)                                                                                                                                                                                    | the fixed texts of the codes; a screen that did not run has one fixed text                                                                                                                                                                                                                                                                                                                                                                                                              |
| `lookthrough.shared_exposure[i].same_position` (1.7)                                                                                                                                                                                                                                                                             | true when every leg is a line of one `identification.same_identity_line_groups` entry: one position, never a finding                                                                                                                                                                                                                                                                                                                                                                    |
| `concentration` (`issuer`, `maturity_ladder`, `fgc`, `manager`, `fund_liquidity`) (1.7)                                                                                                                                                                                                                                          | `concentration.*`, copied, line numbers as `L<n>`                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| `gaps[i]` (`title`, `text`, `line_ids`, `value_brl`, `weight_pct`) (1.7)                                                                                                                                                                                                                                                         | "O que não foi possível avaliar", one line per gap, fixed texts only: `identification.unknown_groups` (grouped by reason, with value), `cnpj_extrato_line_nos`, fee lines without a usable fee grouped by `fee_status`, screens that did not run, funds without a movement verdict, the other sections' `reason_codes`, and the view's own fixed notes                                                                                                                                  |
| `fees.summary` (1.8)                                                                                                                                                                                                                                                                                                             | `fees.summary`, copied; `not_included[i].line_ids` as `L<n>`; `coverage_fixed_portfolio_pct`, `coverage_range_portfolio_pct` (#765): `totals.fund_value_with_fixed_fee_brl` or `..._fee_range_brl` over `statement.sum_of_lines_brl`, one division in `adapt.py`, nothing summed |
| `allocation` (`status`, `basis`, `buckets[i]` `asset_class`, `value_brl`, `weight_pct`, `line_ids`) (1.8)                                                                                                                                                                                                                        | `allocation.classes[i]` (`portfolio_pct`)                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| `concentration.maturity_ladder.by_year[i]` (`year`, `value_brl`, `weight_pct`, `line_ids`) (1.8)                                                                                                                                                                                                                                 | `concentration.maturity_ladder.by_year[i]`                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| `risks` (`status`, `title`, `note`, `severity_rule`, `thresholds`, `counts`, `rows[i]`) (1.8)                                                                                                                                                                                                                                    | `risks.*`; a row without `sources`, `line_nos` (as `line_ids`) and with `reason` only when not evaluated; `provenance` from its `sources`                                                                                                                                                                                                                                                                                                                                               |
| `lookthrough.tree[i]` (`line_id`, `name`, `value_brl`, `weight_pct`, `n_exposures`, `children[j]` `name`, `value_brl`, `weight_pct`) (1.8)                                                                                                                                                                                       | the five largest funds of `look_through.lines` with an opened portfolio and, under each, its three largest positive `exposures` (`exposure_brl`, `portfolio_pct`): the diagram's selection, never a new figure                                                                                                                                                                                                                                                                          |
| `gaps[i]` from the charts and risks (1.8)                                                                                                                                                                                                                                                                                        | every risk row `nao_avaliado` and every chart not drawn (`sem_vencimento`, `sem_credito_direto`, `sem_carteira_dos_fundos`, `sem_taxa_em_reais`), fixed texts                                                                                                                                                                                                                                                                                                                           |
| `credit` (1.9) (`label`, `price_note`, `rate_note`, `lines[i]`: `line_id`, `tipo`, codes, `status_label`, issuer as printed, both maturities and rates, `situacao`, rating, ISIN, `issuer_code`, funds' mark and gap)                                                                                                            | `identification.lines[i].credit_match` of every CRA, CRI and debenture line                                                                                                                                                                                                                                                                                                                                                                                                             |
| `liquidity` (1.9) (`buckets[i]` with `weight_pct`, `line_ids`)                                                                                                                                                                                                                                                                   | `liquidity`, copied, line numbers as `L<n>`                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| `concentration.manager` (1.9) (`groups[i]`, `fund_value_weight_pct`)                                                                                                                                                                                                                                                             | `concentration.manager`                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| `lines[i].badges[]` (1.9) (`code`, `label`: `ocr`, `codigo_nao_conferido`, `taxa_nao_conferida`, `vencimento_diverge`)                                                                                                                                                                                                           | the statement's `fonte_texto`, `codigo_conferido`, `taxa_conferida` and `credit_match.flags`                                                                                                                                                                                                                                                                                                                                                                                            |
| `returns` (1.10) (`windows[i]`, `coverage[i]` with `id`, `cdi`, `lines[i]`: `line_id`, `basis_label`, `fee`, `windows[j]`)                                                                                                                                                                                                       | `returns.*`, copied; `windows` and `coverage` become lists in the engine's window order (`12m`, `6m`), because a placeholder key must start with a letter; every `reason` is the fixed text of its code (`cdi_reason`, `fee_reason` for the window's other codes); no total, mean or ranking is added, and "% do CDI" is shown only where the engine wrote `pct_of_cdi` (1.12), with `pct_of_cdi_reason` beside a fund that has none; `lines[i].benchmark` copied with its fixed reason |
| `tax` (1.11) (`labels`, `rules_files`, `not_covered`, `person`, `lines[i]`: `line_id`, `fee`, `holding`, `tax`, `pension`, `optimization`, `iof`, `a_conferir`)                                                                                                                                                                  | `tax.*`, copied without `rule_source`, `sources` and the `date_missing` template; `tax.act` from `rule_source.act`; every `reason` the fixed text of its code; `person.flags[i].line_ids` as `L<n>`                                                                                                                                                                                                                                                                                     |
| `gaps[i]` from returns and tax (1.10, 1.11)                                                                                                                                                                                                                                                                                      | the lines with no return (`returns.lines[i].reason_code`) and the `sem_regra` tax lines, grouped by code, with their line ids and no value                                                                                                                                                                                                                                                                                                                                              |
| `fees.comparison.by_line[i]` `n_fund_peers`, `n_etf_peers`, `n_etf_excluded`, `etf_peer_*` (1.11)                                                                                                                                                                                                                                | the same keys of `fees.comparison.lines[i]`                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| `equivalents` (1.13) (`label`, notes, `lines[i]`: `line_id`, `etf`, `windows[j]`)                                                                                                                                                                                                                                                | `equivalents.*`, copied without `sources`; every reason the fixed text of its code (the SQL's own reason never reaches the view); lines with no equivalent and windows not compared are `gaps[i]`, grouped by code; `api.portfolio_equivalents` is credited to `ETFSBRASIL` and dated by the ETF's PL and fee snapshots, never by the run date                                                                                                                                          |
| `data_dates`                                                                                                                                                                                                                                                                                                                     | the newest `data_date` per source name                                                                                                                                                                                                                                                                                                                                                                                                                                                  |

## Tools the engine calls

`portfolio_credit_returns` (2.1, catalog v71; live once the analytical SQL and the MCP are deployed) and
`inflation` (2.1, IPCA, only for a contracted rate on IPCA), `portfolio_equivalents` and `class_return_distribution` (1.13, catalog v68 and v66; live once the analytical SQL
and the MCP are deployed), `fund_nav`, `quote_history`, `macro_series` and `trade_consolidated_history` (1.10, the return block; the last
is catalog v65, merged in #632 and live once the analytical SQL and the MCP are deployed; until then its unknown-tool answer is the expected `etf_rf_sem_api`), `portfolio_instruments` and `portfolio_fund_terms` (catalog v62), `portfolio_movement` (catalog v54), `portfolio_resolve` (`etf_ticker` since catalog v56), `portfolio_fees` (catalog v52: the 21 columns of v51, then 25 appended; 10 more in v55, 5 in v56, 2 in v57, 3 in v68), `portfolio_lookthrough` (merged; the canned
rows follow their documented columns and have not been run against the live functions), and the
existing `lookup`, `quote_latest`, `company_financials`, `short_interest`, `fidc_portfolio`,
`fund_restatements`, `fund_restatement_diff` and the `screen_*` tools. Default client: the public
read-only MCP `silo-mcp`; fallback `PostgrestClient`. Neither was exercised over a network from the
build sandbox.

## Brief and client constraints

See [brief-client-fit.md](brief-client-fit.md). The additive `client_fit` field records declared constraints and deterministic maturity/cash checks; it never approves suitability. The brief reuses checked findings, and HTML delivery skips PDF generation until the browser print/save request.
