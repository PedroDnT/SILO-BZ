# Administration-fee peer comparison

Implementation of the narrow cost-comparison slice proposed in #614, informed by
#608. It contributes to #609, whose owner resolution (2026-10-05) adds ETF peers
and the class return distribution (catalog v66, section "ETF peers" below).

`api.portfolio_fee_peers(p_cnpjs TEXT[], p_as_of DATE DEFAULT CURRENT_DATE)`
returns one row for each distinct normalized CNPJ (1–200 inputs), with a dated
administration fee, peer statistics or an explicit non-comparison reason. It
refuses above the API's 1,000-row cap. The public read grants follow the other
portfolio endpoints; landing tables stay private.

## Peer definition

The source is `public.vw_fi_extrato_latest`. Peers share exactly the filed ANBIMA
class, `FUNDO_COTAS` (`S` or `N`) and document scope (`FI` or `CLASSES-FIF`).
Unknown class, fund-of-funds flag or scope is not widened to a larger group.
Activity requires a non-null FI quota in `fact_fund_monthly` in the reference
month containing `p_as_of` or either of the two preceding months.

Usable fees are positive and at most 5% per year. Their document dates must be
no later than `p_as_of` and no older than 36 months. Zero is excluded, not
interpreted as free. `n_excluded` counts unusable fees in the same active group.
At least 30 usable funds are needed, including the target when eligible.
There is no fallback to class alone. The output includes p25, median, p75,
percentile using midrank ties, target minus median in percentage points, peer
counts, exclusion counts and oldest/newest document dates.

This is the latest-document snapshot available when queried, **not a historical
universe or backtest**. `p_as_of` dates the activity window and document filters;
it does not restore older versions of a latest document. Peers' fee dates can
vary. Performance fees, total expense, FIDC, FII, FIP, taxes and any replacement
recommendation are outside this comparison.

## ETF peers (catalog v66, #609)

ETFs enter the peer group because an ETF can replace a fund. CVM files no ANBIMA
class for an ETF (173 of the 178 active ETFs are in `cvm_registro_classe` with the
class empty), so an ETF reaches a class only through
`src/portfolio/rules/equivalents/class_index.yaml`, a short list of
(class, index) pairs as filed, each `status: proposta` until the owner approves it.
The index is never inferred from a fund's name. `scripts/gen_class_index_sql.py`
writes the pairs into `31_api_portfolio.sql` as the internal view
`public.portfolio_class_index` (a VALUES list, so the pairs go live with the same
analytics-only apply as the function, and no migration carries data);
`tests/test_portfolio_equivalents.py` fails when the two disagree and checks every
spelling against a fixture of filed values.

Read in reverse, an active ETF whose `underlying_index` is mapped to class C is a
peer in every FUNDO_COTAS and scope cell of C, once per CNPJ. Its fee is
`etf_market_snapshot.taxa_adm_pct` (etfsbrasil, the newest snapshot dated no later
than `p_as_of`), a third-party value and never a CVM-disclosed one, held to the same
`0 < fee <= 5` and 36-month rules. `n_peers` is `n_fund_peers + n_etf_peers`, and the
30 minimum and the statistics are over both; `n_etf_excluded`, `etf_peer_tickers`,
the ETF snapshot dates and `etf_peer_fee_source` say which ETFs entered and that
their fee is third-party. Measured 2026-10-05: the mapped equity classes have fewer
than 30 usable fund fees in every cell, and the Selic ETFs (six CNPJs) take some
`RENDA FIXA BAIXA DURAÇÃO - SOBERANO` cells over 30 (26 and 28 usable fund fees in
the N cells); `n_fund_peers` shows when ETFs made the difference.

`api.class_return_distribution(p_classe_anbima, p_fundo_cotas, p_month)` gives the
p25, median and p75 of the class's net fund quota returns over 12 and 6 months, at
least 30 funds or `nao_avaliado`: what the equivalent ETF's return is set against.

## Market equivalent (catalog v67, engine 1.12)

`api.portfolio_equivalents(p_classes TEXT[], p_as_of DATE)` reads the same pairs,
only those with `status: aprovada`, and returns, per class, every active ETF (one
row per CNPJ, the fee-peer universe) on an index mapped to the class, with its
third-party PL and fee (etfsbrasil, `etf_market_snapshot`, each dated), and flags
the largest by PL across all of the class's indices (`is_equivalent`, ties by
ticker). A class with no approved pair, no active ETF or no PL comes back as
`sem_par`, `sem_etf` or `sem_pl`. Measured 2026-10-05: `RENDA FIXA SIMPLES` and
`RENDA FIXA BAIXA DURAÇÃO - SOBERANO` give BLFT11 (R$ 13.82 bn), the small-cap
class SMAL11, the dividend class DIVO11, the sustainability class ISUS11.

The engine (`src/portfolio/market_equivalent.py`, section `equivalents`) takes the
class and FUNDO_COTAS each fund line's fee comparison read from the Extrato,
checks that the SQL's indices are the YAML's approved ones, and sets the ETF and
the fund beside `class_return_distribution` over the return block's 12- and
6-month windows: the class's p25, median and p75, the difference to the median in
p.p., and the quartile band each return falls in (a position in the class's
distribution, not a ranking; the function serves quartiles, not an exact
percentile rank). The ETF's return is the return block's own series: the cash
tape's raw `close` ("sem proventos", understated for an ETF that distributes) or,
for a `fixed_income_br` ETF, `trade_consolidated_history`'s `last_price`; never
`ref_price` or `close_adj`. The ETF's fee is the same third-party value the fee
peers use, with its date and label, and `in_fee_peers` says whether it was a peer.
Everything is labelled "equivalente de mercado; não é recomendação"; a fund with
no class, no pair, no ETF, no PL, or an ETF with no return carries a fixed reason
code (`common.REASON_TEXT`), never a blank.

## Engine and report

The engine stores the independent section at `fees.comparison`, batches up to
200 CNPJs and preserves statement/API provenance. A comparison is accepted only
when the displayed fee headline is the same fixed Extrato fee and document date,
without a stale flag. A newer lâmina or another fee source is explicitly not
compared rather than silently comparing a different number.

Every fund position remains in the coverage denominator, including unidentified
positions and excluded fund types. The output reports compared/not-compared line
counts, compared value, total fund value and coverage by both fund and portfolio
value. The report shows each eligible fund's group, own fee/date, median,
interquartile range, difference in percentage points, percentile, counts and
peer document dates. Other funds show their non-comparison reason. No savings
in reais or recommendation to switch is derived. The narrative receives the
same deterministic values and the same limitations.

The synthetic demo rows test output shape, not measured production coverage.
The 63.6% class-plus-FUNDO_COTAS coverage measured in #608 does not carry over
unchanged: document-scope splitting and date exclusions must be measured live.
Cold performance and production coverage remain to validate after rollout.

## Validation and rollout

Python tests cover fee-source parity, range validation, missing/refused rows,
coverage, batches and report/narrative integration. `tests/sql/portfolio_behaviour.sql`
checks cohort separation, minimum count, exclusions, tie percentiles,
normalization, input refusal and anon privileges with synthetic rows.

Apply analytical SQL before deploying `silo-mcp`; then redeploy the Python engine.
The catalog is version 67 (`portfolio_equivalents` and the filed benchmark on
`portfolio_fees`), with regenerated OpenAPI and MCP contracts. A merge
alone does not deploy analytical SQL or the remote MCP. Until the RPC is available,
its refusal/error is shown as a gap and the existing fee section remains usable.
