# Research agent reconciliation results

Checked 2026-09-26 against local `9b876b5` and the available `origin/main`
snapshot `6ccaf2b`. No merge, branch switch, production change, Actions run,
or paid model call was performed.

## Local completion evidence

- The adapter discovers all 54 callable surfaces in the newer-main contract:
  41 RPCs and 13 views. It no longer silently cuts the list at 41 entries.
- Published argument types, array item types, numeric limits, enums, and exact
  ISO dates are checked locally. Safe API status/code/message and server hints
  remain available to the agent; public result rows, counts, hashes, and timing
  remain auditable.
- Case-specific model input is still only the professional question. Reference
  identifiers, joins, dates, calculations, caveats, and scoring remain private
  to the evaluator. The newer-main label-based headline net-income semantics
  are distinguished from the historical baseline's code-only semantics.
- **17 focused offline tests passed**, and the current-main SDK/OpenAPI
  compatibility check discovered all 54 callable surfaces. Independent example
  arithmetic remains 56,508.93 × 0.124 = 7,007.10732 m² and 4.59 − 4.26 =
  +0.33 percentage points. These checks do not verify new live source rows.

## Evaluation gate

The [baseline grade](agent-evaluation-grade.md) remains 2 full passes out of
12, with no answerable case independently verified as a full pass. The
[immutable baseline record](../../research_examples/baseline-results.json)
is preserved separately from the latest-result file.

Cumulative observed estimated model spend is **US$0.604687**. A new 12-case
run reserves **US$18.72**, leaving its combined estimate below the **US$20**
total cap. A missing or inconsistent spend ledger fails closed.

No fresh passing same-API preflight report is available here. Issue #301's
new 12-case run and repeat flagship calculations therefore remain **unverified**.
Paid calls require a matching, read-only report no more than six hours old
with passing results for all three research RPCs. Production availability
must be checked anew; the historical `PGRST202` diagnosis is not evidence of
the current live release state.
