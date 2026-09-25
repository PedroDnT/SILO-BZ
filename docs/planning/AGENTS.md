# Agents

The design of SILO's governed agent loop, backlog item B7 in
[COMPETITIVE_GAPS.md](COMPETITIVE_GAPS.md) §7. Approved by Pedro on
2026-09-24. The §5 test passed on 2026-09-24 and the three prompt files exist;
**nothing is scheduled yet**: see §6.

The contrast this is written against is Liqi (COMPETITIVE_GAPS §4.5), whose
agent count reads 13 to 20+ depending on the source, and whose CEO, as Pedro
heard it, does not know which agents are running. Every rule below exists so
that SILO can always answer three questions from the repo alone: which agents
exist, what each one is allowed to do, and which prompt produced a given
change.

## 1. Principle: agents propose, gates decide

- **An agent never writes to `main` or to the database.** Each run produces
  at most one draft PR or one issue, and nothing else. A run with nothing to
  do, or with its budget full (§3d), is a no-op and says so in its session.
- **The existing gates apply unchanged.** An agent PR goes through the same
  four as any other:

  | Gate                                        | Checks                                                   |
  | ------------------------------------------- | -------------------------------------------------------- |
  | Offline pytest suite (`test.yml`, pre-push) | code and contracts, no network, no DB                    |
  | `scripts/verify_pipeline.py`                | the live warehouse after a change lands                  |
  | `.claude/skills/iliquid_nightly` checklist  | the integrity rules and the serving contract, in review  |
  | Pedro's merge                               | everything else, including whether the item was worth it |

  If an agent change makes a gate fail, the change is wrong, not the gate
  (`CLAUDE.md`). No agent may edit a gate: `tests/` may gain tests but not
  lose or loosen them, and `scripts/verify_pipeline.py`, `.github/workflows/`,
  `.claude/` and `CLAUDE.md` are out of bounds.

- **Scope stays with Pedro.** The Builder works only on issues Pedro labelled
  `agent-ok`. The Scout and the Sentinel have a fixed scope written in their
  prompt files, which change only through a PR Pedro merges (§3b).

## 2. Roster

Three to start.

| Agent        | Cadence                                         | Reads                                                                                                                                         | Output                                                                                                                                                                      | Permissions                                                                         |
| ------------ | ----------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------- |
| **Scout**    | weekly                                          | Tomé (`agentetome.com/api/stats`, `/como-funciona`), CNN Money, the competitor list in COMPETITIVE_GAPS §2                                    | one draft PR updating COMPETITIVE_GAPS §2 (landscape) and §3 (matrix); every new Y cell carries a URL, unknown stays `?`                                                    | web read; edits `docs/planning/COMPETITIVE_GAPS.md` only                            |
| **Builder**  | weekly, one item per run                        | open GitHub issues labelled `agent-ok`, oldest first                                                                                          | one draft PR: a dataset through the `CLAUDE.md` "Adding a dataset" six steps, or one new `api.*` endpoint in the `19_api_contract.sql` pattern, with code and offline tests | repo read and write on its own branch; no schema apply, no deploy, no DB credential |
| **Sentinel** | daily, after the 06:00 UTC ingest and its gates | `api.coverage()`, `cvm_ingest_log`, and source drift: new FNET document types or categories, changed CVM CSV headers against our `FIELD_MAP`s | one issue, never code                                                                                                                                                       | read-only                                                                           |

**Later:** a question-queue agent, once the API or an MCP (B2) logs the calls
it could not answer. That log is the queue; until it exists there is nothing
for this agent to read.

### What the Sentinel adds to the existing watchers

Three workflows already watch the system. All three watch **our** side:

| Workflow            | Schedule  | Watches                                                                                                                                                                                                                                                                                                 |
| ------------------- | --------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `health.yml`        | 07:30 UTC | DB Health: unhealed ingest errors and stuck slices in the daily window, that ingest ran at all, completeness drift per monthly family, `api.catalog()` / `api.coverage()` answering, `fact_fund_monthly` freshness, BACEN SGS freshness, disk; then the anonymous API surface and closed landing tables |
| `watchdog.yml`      | 08:00 UTC | stale daily slices in `cvm_ingest_log`; re-runs `run_daily` when found                                                                                                                                                                                                                                  |
| `publish_check.yml` | 08:00 UTC | that the public dashboard host serves the newest production build (`scripts/promote_dashboard.sh`, OPEN_ITEMS item 8)                                                                                                                                                                                   |

None of them notices that a **source** changed: a new column in a CVM CSV that
our field map ignores, a new FNET document category, a member added to the
FIDC ZIP. Those land as green runs that silently hold less than the source
publishes. The Sentinel watches for exactly that, which is the other half of
the `CLAUDE.md` rule "do not confuse OUR health with the SOURCE's". It does not
duplicate the three above: a red `health.yml` is already the alarm, and the
Sentinel does not file an issue for it.

`cvm_ingest_log` is closed to anon, and `health.yml` verifies that on every
run. So the Sentinel needs a read-only credential with
`default_transaction_read_only = on`, the same posture as `health.yml`. Which
credential, and whether it is a new Postgres role, is Pedro's call (§6).

### Sentinel credential

[`docs/security/sentinel_readonly_role.sql`](../security/sentinel_readonly_role.sql)
is the proposed answer, for Pedro to run by hand with psql: a LOGIN role
`silo_sentinel` whose password comes from a psql variable
(`-v sentinel_password=…`), never a literal in the file. It holds CONNECT,
USAGE on `public` and `api`, SELECT on `cvm_ingest_log` and `fnet_document`,
EXECUTE on `api.coverage()` and `api.metric_coverage()`, and a 30s
`statement_timeout`; nothing else. It does not set
`default_transaction_read_only` (the grants are the boundary); the script's
header carries the one-line `ALTER ROLE` if the posture above is wanted too.
The connection string goes in the Sentinel routine's environment secret, never
in the repo.

## 3. Lineage

The rules that keep "which agents are running" answerable.

### a. This file is the registry

An agent that is not in this table does not run. Adding a row, changing a
schedule or a permission, and retiring an agent are all PRs to this file.

| Name     | Prompt file                  | Schedule (UTC, proposed) | Routine id | Permissions                               | Output     | Kill switch         |
| -------- | ---------------------------- | ------------------------ | ---------- | ----------------------------------------- | ---------- | ------------------- |
| Scout    | `.claude/agents/scout.md`    | Mondays 10:00            | TBD        | web read; COMPETITIVE_GAPS.md only        | 1 draft PR | disable the routine |
| Builder  | `.claude/agents/builder.md`  | Wednesdays 10:00         | TBD        | own branch; no schema apply, deploy or DB | 1 draft PR | disable the routine |
| Sentinel | `.claude/agents/sentinel.md` | daily 09:00              | TBD        | read-only                                 | 1 issue    | disable the routine |

All three prompt files exist (written 2026-09-25). A routine id is filled in
by the owner's session when that routine is created, one at a time, after
the labels exist; until a row has one, that agent does not run.

The Sentinel's 09:00 sits after the 06:00 ingest, 07:30 DB Health and the
08:00 watchdog and publish check, so it reads a day whose own-side state has
settled.

### b. Prompts are versioned files

Each agent's prompt lives at `.claude/agents/<name>.md` and is the whole of
its instructions. The routine only points at the file. An agent changes its
own behaviour only by a PR to its prompt, which Pedro merges like any other.
There is no learning at runtime and no memory outside the repo, in line with
the COMPETITIVE_GAPS §4.5 "Avoid" list: what SILO does must stay a function of
the git commit.

### c. Every output carries its provenance

Every agent PR and issue:

- carries the label `agent:<name>` (`agent:scout`, `agent:builder`,
  `agent:sentinel`);
- states in its body the prompt file and the git SHA of the last commit that
  touched it (`git log -1 --format=%H -- .claude/agents/<name>.md`), plus a
  link to the session that produced it.

So any agent change can be traced to the exact prompt that caused it, and a
prompt change can be measured by the outputs before and after its SHA.

### d. Budgets

| Rule                                      | Effect                                                                                                                                 |
| ----------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| At most **3 open agent PRs**, all agents  | a run that finds 3 open `agent:*` PRs is a no-op                                                                                       |
| **One item per run**                      | the Builder takes one `agent-ok` issue; the Scout one update; the Sentinel one issue, or a comment on its open one for the same source |
| **A red CI is fixed or the PR is closed** | never bypassed: no skipped tests, no `--no-verify`, no weakened assertion                                                              |

### e. Retirement

Scored per agent over its last 4 runs that produced output:

| Metric             | Measured as                                                                           |
| ------------------ | ------------------------------------------------------------------------------------- |
| Merge rate         | merged PRs / PRs opened. For the Sentinel: issues closed as acted on / issues opened  |
| Human-edited lines | lines changed on the branch after the agent's last commit, taken from the merged diff |
| CI-red rate        | PRs whose first CI run was red / PRs opened                                           |

**Merge rate below 50% over 4 runs pauses the agent**: its routine is
disabled and its registry row says why. It comes back only through a PR to its
prompt. The other two metrics are recorded, not gated, until there is enough
history to set a bar that means something.

## 4. Runtime

- **Agents run as Claude Code Routines**: scheduled cloud sessions, a fresh
  session per fire, so no run inherits another's context. The prompt each
  routine sends is one line pointing at `.claude/agents/<name>.md`.
- **GitHub Actions stays ingest and its gates.** No agent runs in Actions, and
  no agent holds `POSTGRES_URL`.
- **Kill switch: disable the routine.** One action, immediate, and it leaves
  the routine and its run history in place for the retirement score.

## 5. Smallest test before scheduling anything

One **manual** Builder run, on FIDC informe `tab_X_7` (collateral coverage of
the receivables, value and %; listed as unread in
[`docs/DATA_INVENTORY.md`](../DATA_INVENTORY.md) §2).

Why this item: it is a real gap, it is small, and it exercises the whole
six-step recipe (config, field map, `schema.sql` plus a migration, the ingest
method, the wiring, an offline test with a CSV fixture) in a family whose
patterns already exist (`cvm_fidc_tranche`, migration 38).

Setup: write `.claude/agents/builder.md`, open one issue for `tab_X_7`, label
it `agent-ok`, start one Builder session by hand.

Measure:

- **Human-edited lines** before the PR is mergeable, against the lines the
  agent wrote.
- **First-pass CI**: green or red on the first run, and how many fix rounds.
- Whether the PR read the member's real header before writing a field map, as
  `OPEN_ITEMS.md` item 1 asks of any new endpoint: measure first.

**Reject if** the rework is about the same as writing it by hand. Then the
loop is not worth scheduling, and B7 closes with the numbers recorded here.

### Result: PASS (2026-09-24)

The run became [PR #291](https://github.com/PedroDnT/SILO-BZ/pull/291),
merged by Pedro on 2026-09-24 (merge commit `dc07115`).

| Measure                    | Result                                                                                                                                                    |
| -------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Agent output               | 1 commit (`20a13af`), 22 files, +663 / -13: migration 45 (`cvm_fidc_garantia`, key `(cnpj, period)`), field map, config, ingest, wiring, 20 offline tests |
| Human-edited lines         | **0** after the agent's last commit (the merge is byte-identical to `20a13af` on every file the PR touched)                                               |
| First-pass CI              | **green** on the first run (pytest offline, SQL compile); 0 fix rounds                                                                                    |
| Read the real header first | yes: all 82 published months (188,476 rows) and CVM's dictionary; found the `CNPJ_FUNDO` → `CNPJ_FUNDO_CLASSE` switch after 2020-10                       |

Where the agent deviated from this section's wording, each deviation was
stated in the PR body:

- The table is `cvm_fidc_garantia`, not a `fidc_tab_x7` name, and the value is
  not called "coverage": the denominator of the filed percentage is
  undocumented (value ÷ % matched the tab II portfolio for only 6 of 28 filers
  in 2026-08), so the docs say "as filed".
- Validation is stricter than the minimum: CNPJ check digits, not just 14
  digits (4 rows dropped in the whole history, all for negative values).
- It left the `ANALYZE` list in `.github/workflows/daily_ingest.yml` and
  `scripts/verify_pipeline.py` untouched because they are gate files (§1),
  and the `api-docs/data-inventory.mdx` mirror untouched as out of scope.

The rework was nil against 663 written lines, so the reject condition does
not hold and the prompts were written (§6).

## 6. Status (2026-09-25)

| Piece                              | State                                                                                                                                                       |
| ---------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| This design                        | approved by Pedro                                                                                                                                           |
| Smallest test (§5)                 | **passed** 2026-09-24: PR #291, 0 human-edited lines, green first CI                                                                                        |
| Prompt files `.claude/agents/*.md` | **written** 2026-09-25: `scout.md`, `builder.md`, `sentinel.md`                                                                                             |
| Labels `agent-ok`, `agent:<name>`  | not created; the owner creates them (each prompt no-ops while its label is missing)                                                                         |
| Routines                           | none; every routine id above is TBD, filled by the owner's session after merge                                                                              |
| Sentinel's read-only DB credential | script ready (`docs/security/sentinel_readonly_role.sql`), run by the owner by hand; until `SENTINEL_DATABASE_URL` is set, the Sentinel runs in public mode |

Order from here: create the labels, then schedule the routines one at a
time (Builder first, since it is the one tested; then Sentinel; then Scout),
filling in the registry row as each one is created. Each routine's prompt is
one line: "Read `.claude/agents/<name>.md` in full and follow it exactly."
