# Brief and declared client constraints

## Brief (#607)

The report opens with a short brief: portfolio value and identification coverage,
checked GPT summary, disclosed fixed administration fee (not all costs), three
risk rows, return coverage and three position returns, and material limitations.
No portfolio return is manufactured. Missing data is labelled not assessed.
The existing complete report remains in an expandable appendix. The brief reuses
Redator/Revisor findings: no extra model call or budget.

The upload page requests HTML. PDF is available on explicit request through the
browser print/save dialog over the same report; opening the appendix includes it.
The existing `/diagnose` PDF response remains the default for API/CLI callers and
existing smoke checks. HTML requests skip WeasyPrint and do not store a PDF artifact;
the masked engine and run trace still follow ADR 0003. Trace PDF download is unavailable
for these HTML-only runs. No second paid diagnosis is needed to print.

## Declared constraints (#614)

Choose client constraints next, after the brief. Cost comparison already exists;
economic groups need a verified mapping; new brokers need parser samples; batch and
history would extend the stateless MVP; CDB/CDCA remain roadmap. Real narrative and
live rollout remain validation gates, not assumed complete by this branch.

Optional multipart `client_constraints` is a JSON object with only:

| Field | Meaning |
| --- | --- |
| profile | conservador / moderado / arrojado, as declared |
| horizon_date | ISO investment horizon, not before the statement date |
| liquidity_date | ISO liquidity need date, not before the statement date |
| liquidity_brl | finite nonnegative amount; requires liquidity_date |

No names, IDs, free text or inferred profile. Invalid values return 400 before engine
calls. `client_fit` is an additive engine field; the report adapter copies it.
This is a factual constraints check, not a formal suitability approval.

- Horizon: identify direct-credit statement maturities after the declared date;
  keep missing maturities explicit. This does not assess early-sale prices.
- Liquidity: compare required amount with statement cash only. Funds, equities,
  ETFs and Tesouro sales/redemptions are not presumed. A shortfall is not proof
  of illiquidity; it is an amount not proven in cash. Reconfirm balances and needs.
- Profile: recorded, assessment remains not assessed. Objectives, experience,
  risk capacity and product-level suitability are missing; no arbitrary profile
  allocation limits are invented.

No SQL/catalog/migration, portfolio database, recommendations or forecast added.
Live validation and deploy remain separate from offline verification.
