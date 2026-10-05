# Administration-fee peer comparison

Implementation of the narrow cost-comparison slice proposed in #614, informed by
#608. It contributes to #609; equivalent products remain an open decision.

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
vary. Performance fees, total expense, ETFs, FIDC, FII, FIP, returns, taxes and
replacement-product equivalence are outside this comparison.

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
The catalog is version 63, with regenerated OpenAPI and MCP contracts. A merge
alone does not deploy analytical SQL or the remote MCP. Until the RPC is available,
its refusal/error is shown as a gap and the existing fee section remains usable.
