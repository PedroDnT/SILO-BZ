# Reproducible research demonstrations

Run each example from the repository root with `python
research_examples/<script>.py`. They calculate small source-backed examples
offline and print their inputs, result and limits.

These are evaluator-side reference demonstrations. A deployed agent prompt
must state only the professional research question; it must discover data via
the SILO catalog and choose its own tools. Keep expected sources, joins and
reference answers in evaluator-private case specifications, not runtime prompts
or tool hints.

The examples use a project-documented CIA census and published FII/BCB/IBGE
observations, rather than claiming a newly fetched full history. Therefore
their arithmetic can be reproduced, but they do not pass archive-ingestion or
research-agent catalog-discovery benchmarks.

## Live agent evaluation

Install the evaluator dependencies with `.venv/bin/python -m pip install -r
research_examples/requirements-eval.txt` in an environment with pip, or use
`uv pip install --python .venv/bin/python -r research_examples/requirements-eval.txt`.
The evaluator reads `OPENAI_API_KEY` from the environment or the ignored root
`.env`. It uses the published read-only demo SILO access with `--public-demo`.

Run `.venv/bin/python research_examples/agent_eval.py --public-demo` first to
validate the 12-case budget without paid model calls. Add `--run` and
`--preflight-report <path>` to execute the cases after the live read-only
contract check passes. The report must be a JSON object with a UTC
`checked_at` (within six hours), the exact `base_url`, `read_only: true`,
`status: "passed"`, and `endpoints` mapping each of
`financial_statement_history`, `fii_property_history`, and
`focus_expectations` to `{"status":"passed"}`. `--case-id L1` selects one case
for a smoke run. The model sees
only each case's professional question; expected dispositions and review
notes remain in `research_examples/eval_cases.json`.

Each live case updates `docs/reference/research/agent-evaluation-results.md` and
`research_examples/eval-results.json`. The Markdown file is the readable
results summary. The JSON file preserves tool order, usage, errors, and
answers for review. New runs also preserve bounded public response rows for
independent numeric review. `research_examples/eval-spend.json` tracks the
cumulative model-cost estimate across runs, and
`docs/reference/research/agent-evaluation-grade.md` records the independent baseline
grading. Discovery checks are automatic; substantive accuracy still requires
comparison with source rows and private references. Run paid cases only after
the separate live API preflight passes for the required research RPCs.
`research_examples/baseline-results.json` preserves the graded baseline;
future latest-result updates do not change that evidence. The spend ledger
must exist, reconcile with its entries, and stay within the US$20 total cap.

### MCP v2 comparison

The original runner remains the default. Use the same entry point with
`--transport mcp-v2` to expose the live server's 14 native tool schemas:

```bash
python research_examples/agent_eval.py --transport mcp-v2
python research_examples/agent_eval.py --transport mcp-v2 --preflight
```

The first command is offline. The second checks the live catalog and one row
from each of the three required research paths, with no model requests.
`--run` repeats those checks before making paid requests; a failed or empty
probe stops the run. A v1 preflight report cannot authorize a v2 run.
Anonymous access is the default; `SILO_USER_JWT` selects the caller's own
signed-in access. No credential is saved in evaluation artifacts.

V2 keeps the same model, questions, turn limit, five-data-call limit and
cumulative US$20 spend ledger. Data results retain the 100-row/80-KB caps;
catalog discovery permits 160 KB because the live catalog exceeds 80 KB.
Calls are spaced for anonymous rate limits. The agent receives only the
professional question and the public MCP tools, never the evaluator probes
or baseline grading. A model error or missing usage stops the run and retains
the whole-case cost reserve in the shared ledger until billing is reconciled.

Paid runs save `research_examples/eval-v2-results.json` and
`docs/reference/research/agent-evaluation-v2-results.md`. They preserve the
tool schemas, bounded public rows, errors, usage, and a per-case comparison
against the saved v1 baseline. V2 rubric scores remain ungraded until an
independent review; technical completion is not a pass. The original v1
results and its graded 2/12 baseline are preserved.

## Debenture/equity readiness

[Bounded existing-data audit](debenture_equity/README.md): render a single-capture
read-only SELECT for Supabase MCP, then generate a table offline from the returned
JSON. Commercial/legal names remain candidates; this does not run a backtest.
