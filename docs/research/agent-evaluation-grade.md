# Research agent baseline: independent grading

Run: 2026-09-25 01:20 UTC, `gpt-5-mini`. This grades the saved 12-case
[process record](agent-evaluation-results.md) against evaluator-only
[`eval_reference.json`](../../research_examples/eval_reference.json) and
[`baseline-review.json`](../../research_examples/baseline-review.json).
Only the professional question was passed as case-specific model input.

## Result

- **2 of 12 full rubric passes:** L1 and L3 correctly explain why the causal
  or individual-skill claims cannot be made. L2 reaches the right causal limit
  but supports it with unrelated FIDC evidence and an inconsistent fund lookup.
- **0 of 9 answerable cases verified as full passes.** Q2 gives a plausible
  qualitative account-chart answer, but the baseline log kept tool metadata,
  not response rows, so its numeric claims cannot be checked independently.
  Other cases failed on API availability, tool arguments, turn exhaustion, or
  unanswered calculations. “Completed” in the process record means text was
  returned; it does not mean the answer passed.
- Catalog and tool discovery preceded data calls in **12/12** cases. Explicit
  `/coverage` was attempted in **4/12**. The five-call bound stopped further
  substantive calls; the recorded count can be six because it includes a
  rejected sixth attempt.
- The full run logged **1,509,190 input** and **32,145 output** tokens;
  its model-cost estimate is **US$0.441587**. Three earlier smoke attempts
  add about **US$0.1631**, giving **US$0.604687** observed estimated spend
  against the US$20 cap. These are model-price estimates, not a reconciled
  billing statement.

| Case | Independent classification | Full pass | Finding |
| --- | --- | --- | --- |
| Q1 | Tool contract failure | No | Cash-flow rows were not obtained; income alone cannot establish coverage. |
| Q2 | Unverified | No | Qualitative chart distinction is plausible; returned numeric rows were not preserved. |
| Q3 | Tool contract failure | No | Repeated invalid calls; no version comparison. Question wording was clarified afterward. |
| Q4 | API unavailable | No | `fii_property_history` failed in production; no filed area/fraction verified. |
| Q5 | Tool contract failure | No | Invalid lookups prevented the property disclosure comparison. |
| Q6 | Turn exhaustion | No | No completed answer or disclosure denominator. |
| Q7 | Tool contract failure | No | No matched Focus vintages or revision calculation. |
| Q8 | API unavailable | No | `focus_expectations` failed in production; no verified dated gap. |
| Q9 | Unverified | No | The original regime/horizon ambiguity led to clarification instead of analysis. |
| L1 | Successful limitation | Yes | Causal claim rejected with confounding and design limits. |
| L2 | Rubric failure | No | Correct causal limit, but unrelated FIDC evidence weakens the answer. |
| L3 | Successful limitation | Yes | Aggregate medians cannot rank individuals or identify a policy effect. |

## Evidence boundaries and next gate

Direct production probes documented in the [implementation plan](../../tasks/plan.md)
returned PostgREST `PGRST202` for the new FII property and Focus RPCs; the
branch contract names those RPCs.
The agent log itself recorded `SiloError` without safe API codes. The revised
adapter now derives callable arguments from published OpenAPI, validates them
locally, returns redacted status/code/message, and will retain bounded public
response rows for independent numeric review. These changes passed offline
checks and have **not** been rerun against the live API.

Reference arithmetic was checked independently: 56,508.93 m² × 0.124 =
7,007.10732 m² for the documented Via Parque example; 4.59% − 4.26% =
+0.33 percentage points for the documented Focus/realized IPCA example.
Those examples are not substitutes for verified live rows at the question's
exact filing version or survey date. No flagship case has yet passed twice.

The next paid run is gated on the separate deterministic live preflight for
all required research RPCs. Until it passes, FII/Focus-dependent cases remain API-blocked and
the 12-case benchmark remains **unverified as a product-value claim**. The
runner's spend ledger now counts the baseline and smoke estimates before
reserving any additional calls. No production migration, schema-cache refresh,
or deployment was performed here.
