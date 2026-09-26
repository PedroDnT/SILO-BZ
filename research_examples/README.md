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
research-agent catalog-discovery benchmarks. See `docs/research/benchmark-specifications.md`.

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

Each live case updates `docs/research/agent-evaluation-results.md` and
`research_examples/eval-results.json`. The Markdown file is the readable
results summary. The JSON file preserves tool order, usage, errors, and
answers for review. New runs also preserve bounded public response rows for
independent numeric review. `research_examples/eval-spend.json` tracks the
cumulative model-cost estimate across runs, and
`docs/research/agent-evaluation-grade.md` records the independent baseline
grading. Discovery checks are automatic; substantive accuracy still requires
comparison with source rows and private references. Run paid cases only after
the separate live API preflight passes for the required research RPCs.
`research_examples/baseline-results.json` preserves the graded baseline;
future latest-result updates do not change that evidence. The spend ledger
must exist, reconcile with its entries, and stay within the US$20 total cap.
