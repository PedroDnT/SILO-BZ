# Local migration ledger: gpt-5-mini retirement

Application: SILO-BZ, base 4e40dac2, issue #1092, 2026-11-11 (Brasília).
Assessment followed by local implementation, explicitly requested by the owner.
Single approved stage: defaults, pricing/budget accounting, baseline isolation,
offline tests and reviewable diff. No other migration stages authorized.
Existing direct OpenAI Responses integration and Agents SDK are retained.
Credentials: existing route retained; no key inspected, changed or used. Access unknown.
Owner restrictions override broader migration guidance: no provider/architecture
changes, prompt tuning, budget increases, gpt-5.1 migration, workflow edits,
production actions, paid calls or PR. On 2026-11-11 the owner explicitly approved
commit and publication of this branch only; the earlier no-push restriction is superseded.

## Evidence

- https://developers.openai.com/api/docs/deprecations: 2026-12-11 shutdown;
  gpt-5.6-terra replacement. gpt-5.1's separate deadline is out of scope.
- https://developers.openai.com/api/docs/models/gpt-5.6-terra:
  Responses, structured outputs, function calling, low reasoning supported;
  maximum input 922,000; only alias listed, no dated snapshot to invent.
- https://developers.openai.com/api/docs/pricing: Standard input/output/cache-write/
  cache-read = 2/12/2.5/0.2 per million; above 272,000 input = 4/18/5/0.4.
- https://developers.openai.com/api/docs/guides/prompt-caching:
  default 30m writes billed at 1.25x input, not an additive surcharge.
- https://openai.github.io/openai-agents-python/models/: Responses model adapter.
- Installed and tested repository pins: openai 3.28.0, openai-agents 0.24.0.
  SDK source accepts the string model and sends settings via Responses; real
  SDK request serialization/parsing exercised over httpx2.MockTransport.

## Guidance applicability review

| Guidance heading | Applicability/support | Decision and evidence |
| --- | --- | --- |
| Model selection | Yes / documented | Replace judge and shared evaluation model; retain extractor/report gpt-5.1. Live access and quality unknown. |
| Instruction file naming | No change needed | AGENTS.md and CLAUDE.md untouched. |
| Migrate Chat Completions to Responses | Already present | Both routes already use Responses. No endpoint migration. |
| Streaming | No new need | Buffered judge and bounded evaluator preserved. |
| WebSocket mode | No new need | Existing HTTP retained; transport redesign outside owner scope. |
| Zero Data Retention | Unknown contractual requirement | Preserve judge store=False; do not infer ZDR or change evaluation storage policy. |
| Data residency | Unknown project setting | No project/endpoint changes; price basis is non-regional Standard. |
| Processing tiers | Yes / Standard documented | Preserve existing tier; no Fast, Flex, Batch or Reserved change authorized. |
| Prompt cache keys | No change needed | No new key introduced. |
| Extended retention for older models | Not applicable | Migrated model is 5.6; older routes unchanged. |
| Explicit cache breakpoints | Deferred by narrow scope | No cache strategy change; default implicit 30m accounted for. |
| Cache diagnostics | Not needed for offline migration | No recent response IDs or live calls. |
| State management | Already present | Judge is stateless; existing SDK owns evaluator replay. |
| Instruction persistence | Already present | Existing system instructions passed on each judge call; evaluator Runner unchanged. |
| Encrypted reasoning items | Existing SDK concern | No custom state/replay change. |
| Reasoning effort | Yes / low supported | Judge remains low; evaluator retains existing explicit settings and API defaults. |
| Reasoning preservation | Outside narrow scope | No reasoning-context policy added. |
| Reasoning summaries and preambles | Not applicable | No new user-visible summaries. |
| Verbosity | Already present | Evaluator low retained; judge uses strict boolean schema. |
| Maximum output tokens | Yes / supported | Judge 3,000 and evaluator 2,000 retained; reasoning billed as output. |
| Assistant message phases | Already present | Provider consumes final messages; SDK owns evaluator replay. |
| Context compaction | Not authorized | No smaller context/compaction protocol introduced to make budget fit. |
| Structured outputs | Yes / documented and offline tested | Judgement Pydantic schema sent through real SDK parse. |
| Tools / tool choice | Yes / documented | Same evaluator tools, no new hosted tools or approval changes. |
| Tool search and additional tools | Not needed | Fixed small tool sets preserved. |
| Parallel tool calls | Already controlled | Evaluator parallel_tool_calls=False retained. |
| Programmatic tool calling | Not applicable | No code-execution tool added. |
| Model-aligned tool interfaces | Not applicable | No tool redesign. |

## Workflows and checks

Investigator: new default, pricing and cache-write reserve. Existing same-model
refusal retained. Tests cover real SDK structured request, cached input/write/
reasoning cost, missing usage, both caps, env override and missing key.
Evaluator v1: new model/prices/max-input reserve, per-request accounting,
new model-named output files, model recorded in new spend entries; unknown
failure costs retain full reserve and stop, matching v2's existing behavior.
Evaluator v2: inherits model/prices and records them; separate outputs, truthful
comparison text, historical model printed from stored record.
Historical JSON/Markdown/grades and cumulative spend are unchanged.

Budget consequence: full-context 12-turn reserve is US$69.69 per case and
US$836.28 for 12 cases, plus US$2.164687 previously recorded. Both entrypoints
refuse before credentials or network under the unchanged US$20 cap. No new
budget approval inferred. A future bounded-context protocol is owner work.
The report cap is US$1 and the Investigator share US$0.30, unchanged. Existing
prompt-character estimation is not a tokenizer-enforced monetary guarantee.

Deployment evidence: deploy/cloudflare/wrangler.jsonc has SILO_INVESTIGATOR=on;
this is repository configuration only, not proof of deployed production state.
No historical 403 for GPT-6 is treated as evidence about Terra access.

## Validation

Initial focused suite: 130 passed. Additional real Agents SDK transport and v1
failure-persistence tests: test_research_agent_eval.py, 25 passed.
Final full suite: 5268 passed, 35 skipped in 142.26s. No migration test skipped.
Final diff check and isolated-index application check passed. Exported review report
and verification.txt preserve exact commands, exclusions and offline budget refusal.
No live model quality/access validation performed. No paid calls.

## Remaining gates

Owner reviews local diff. Before release, separately approve credential access
verification and a bounded-cost quality smoke/evaluation protocol. No paid
operation, PR or production release is authorized by this preparation task.

## Evaluator follow-up (2026-11-12, Brasília)

The owner's 2026-11-11 23:24 decision moved the research evaluators (only) to
`gpt-6.1-terra` with an enforced 70,000-token input cap per request; see
`research_examples/README.md`. The Investigator judge keeps `gpt-5.6-terra`.
The budget consequence above no longer holds for the evaluators: the reserve
is US$1.4625 per case and US$17.55 for 12 cases.
