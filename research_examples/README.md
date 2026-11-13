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

The current model is `gpt-6.1-terra` (prices checked 2026-11-12); the saved
`gpt-5-mini` runs remain historical. Run
`.venv/bin/python research_examples/agent_eval.py --public-demo` first to
check the 12-case budget without network or model calls.

Every model request is capped at 70,000 input tokens (owner's choice,
2026-11-11). The Agents SDK's `RunConfig(call_model_input_filter=...)` hook
runs `InputCapFilter` immediately before each request. It estimates the
instructions, the conversation and the tool schemas with tiktoken's
`o200k_base` (installed by `requirements-eval.txt`), or with characters / 2
when tiktoken is absent, and adds 10%. A request over the cap is never sent:
the case stops as `context_cap_reached` with no answer, its observed usage is
charged, and the run moves to the next case. Nothing is trimmed. Because the
cap holds, the reserve is 1.25 × 12 turns × one capped request: US$1.4625 per
case, US$17.55 for all 12, which fits the cumulative US$20 cap on top of the
US$2.164687 already in the ledger. This is a configuration bound, not a
measured model cost. Do not raise the cap or clear the spend ledger.
Credential access to the model remains unverified.

To execute, add `--run` and
`--preflight-report <path>` to execute the cases after the live read-only
contract check passes. The report must be a JSON object with a UTC
`checked_at` (within six hours), the exact `base_url`, `read_only: true`,
`status: "passed"`, and `endpoints` mapping each of
`financial_statement_history`, `fii_property_history`, and
`focus_expectations` to `{"status":"passed"}`. `--case-id L1` selects one case
for a smoke run. The model sees
only each case's professional question; expected dispositions and review
notes remain in `research_examples/eval_cases.json`.

Each new live case updates `docs/reference/research/agent-evaluation-gpt-6.1-terra-results.md` and
`research_examples/eval-gpt-6.1-terra-results.json`. The Markdown file is the readable
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
The runner records the model and price basis; it sums costs per request so the
272,000-token long-context threshold is not applied to aggregate usage across
turns. All input is conservatively charged at the default 30-minute cache-write
rate; no cache-read discount is assumed. A model error or missing usage stops
the run and retains the full-case reserve until billing is reconciled.

### MCP v2 comparison

The original runner remains the default. Use the same entry point with
`--transport mcp-v2` to expose the live server's 14 native tool schemas:

```bash
python research_examples/agent_eval.py --transport mcp-v2
python research_examples/agent_eval.py --transport mcp-v2 --preflight
```

The first command is offline and checks the budget gate above. The second
checks the live catalog and one row
from each of the three required research paths, with no model requests.
`--run` repeats those checks before making paid requests; a failed or empty
probe stops the run. A v1 preflight report cannot authorize a v2 run.
Anonymous access is the default; `SILO_USER_JWT` selects the caller's own
signed-in access. No credential is saved in evaluation artifacts.

V2 shares the current runner's model, questions, turn limit, five-data-call limit and
cumulative US$20 spend ledger, and the same 70,000-token input cap, which
counts the 14 MCP tool schemas (about 18,000 estimated tokens with the
instructions). Data results retain the 100-row/80-KB caps; catalog discovery
permits 140 KB because the live catalog (about 129 KB) exceeds 80 KB. The
catalog plus the tool schemas leave little room under the cap, so a v2 case
may stop as `context_cap_reached` after its catalog read; that is recorded,
not worked around.
Calls are spaced for anonymous rate limits. The agent receives only the
professional question and the public MCP tools, never the evaluator probes
or baseline grading. A model error or missing usage stops the run and retains
the whole-case cost reserve in the shared ledger until billing is reconciled.

New paid runs save `research_examples/eval-v2-gpt-6.1-terra-results.json` and
`docs/reference/research/agent-evaluation-v2-gpt-6.1-terra-results.md`. They preserve the
tool schemas, bounded public rows, errors, usage, and a per-case comparison
against the saved v1 baseline. V2 rubric scores remain ungraded until an
independent review; technical completion is not a pass. The original v1
results and its graded 2/12 baseline are preserved, as are the 2026-11-06 MCP v2
artifacts in `eval-v2-results.json` and `agent-evaluation-v2-results.md`.
The new model differs from both historical baselines: score changes cannot be
attributed to the v1/v2 transport alone.

## Debenture/equity readiness

[Bounded existing-data audit](debenture_equity/README.md): render a single-capture
read-only SELECT for Supabase MCP, then generate a table offline from the returned
JSON. Commercial/legal names remain candidates; this does not run a backtest.

### Pro comparison at 120,000 input tokens

Use the existing 12 cases with `gpt-5-mini` for comparison with the historical v1
and previous Pro runs. Pass the reconciled cumulative ledger as an absolute path.
Provide `SILO_INTEGRATION_KEY` in the process environment from a local secret
store. The preflight requires `meta.tier: pro` on every data probe.

```bash
python -m research_examples.mcp_v2_eval --pro --budget-usd 10 --spend-ledger "$SILO_EVAL_LEDGER" --preflight
python -m research_examples.mcp_v2_eval --pro --budget-usd 10 --spend-ledger "$SILO_EVAL_LEDGER" --run
```

The Pro profile counts model input before each request, keeps the 12-turn and
2,000-output-token limits, and reserves US$0.51 per case. Run one evaluator per
ledger. An interrupted charge keeps its reserve. If the ledger and result file
disagree after an interruption, reconcile them before retrying. Completed
attempts are skipped on resume. The Pro profile writes its own result and review
files. Grade the answers against the saved rubric and both earlier 2/12 runs.
