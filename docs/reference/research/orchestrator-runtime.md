# Orchestrator runtime facts: hooks, worktrees, Workflow, `gh`

Research for issue #699 (part of map #695). It records facts a design
decision waits on. It makes no decision and changes nothing that runs.

Written on the throwaway branch `research/orchestrator-runtime`, not for
merge. Measured on 2026-10-07 between 00:00 and 00:20 UTC-3 (03:00 to 03:20
UTC) in a Claude Code cloud session: 4 CPUs, 15 GiB RAM, `/home/user/SILO-BZ`
at `origin/main` = `1020cca`.

## How to read this note

- Each fact names its source: a `file:line`, a command and its output, or a
  doc URL. Doc pages were fetched as Markdown with `curl` on the date above.
- "The hooks doc" is <https://code.claude.com/docs/en/hooks>. "The worktrees
  doc" is <https://code.claude.com/docs/en/worktrees>. "The sub-agents doc" is
  <https://code.claude.com/docs/en/sub-agents>.
- Nothing under `src/`, `serve/`, `tests/` or `scripts/` was edited. Hook
  behaviour was measured by piping a synthetic payload into each script.

## 1. The hooks under parallel worktrees

### What the settings declare

- `.claude/settings.json:66-75`: `PostToolUse` on `Write|Edit` runs
  `bash .claude/hooks/post-edit.sh` with `"timeout": 90`. The path is relative
  to the hook's working directory, not to `${CLAUDE_PROJECT_DIR}`.
- `.claude/settings.json:47-58`: `PreToolUse` on `Bash` with
  `"if": "Bash(git push *)"` runs
  `bash "${CLAUDE_PROJECT_DIR}/.claude/hooks/pre-push-docs.sh"`, timeout 30.
- The hooks doc, "Timeouts": a `command` hook that reaches its timeout is
  cancelled and its output is discarded, so "on most events a timed-out hook
  renders no decision".

### What post-edit.sh does

- `post-edit.sh:9-16`: it reads `tool_input.file_path`, strips a leading `./`,
  and exits unless the file ends in `.py` and exists.
- `post-edit.sh:24-25`: `PY=python3`, replaced by `.venv/bin/python` only when
  that file is executable in the current directory.
- `post-edit.sh:33-37`: the pytest branch is taken only when the path matches
  `src/*|serve/*|tests/*|scripts/*`, and only when `.venv/bin/pytest` exists.
  Otherwise it exits 0 with no message.
- `post-edit.sh:40`: the suite is `.venv/bin/pytest tests/ -q --tb=line`, the
  whole offline suite, not the edited file's tests.

### Finding: the pytest branch does not fire on a real edit

- The hooks doc, `PostToolUse` example input: `"file_path": "/path/to/file.txt"`.
  Claude Code sends the absolute path.
- A `case` pattern `src/*` does not match `/home/user/SILO-BZ/src/...`.
- Measured at the repo root:
  - `printf '{"tool_input":{"file_path":"/home/user/SILO-BZ/src/store/pg_client.py"}}' | bash .claude/hooks/post-edit.sh`
    → rc 0 in **0.044 s** (py_compile only).
  - `printf '{"tool_input":{"file_path":"src/store/pg_client.py"}}' | bash .claude/hooks/post-edit.sh`
    → rc 0 in **86.7 s** (py_compile + full suite).
- So today the hook runs `py_compile` on every edited `.py` and runs the suite
  only for a relative path, which Claude Code does not send. This is a
  discovery, reported here and not fixed (owner's rule: discovery is not
  prioritization).

### Finding: the suite and the timeout are the same size

- `time .venv/bin/python -m pytest tests/ -q -p no:cacheprovider` at the repo
  root: `3850 passed, 20 skipped, 1 warning in 85.29s`, wall-clock 87.1 s.
- The hook timeout is 90 s (`settings.json:73`). If the pytest branch did
  fire, the margin would be under 5 s on an idle machine, and a timed-out hook
  renders no decision (hooks doc, "Timeouts"). A failure would be silent.

### What a worktree has

- `.gitignore:19-20` lists `.venv/` and `venv/`. The worktrees doc, "Copy
  gitignored files into worktrees": a worktree "is a fresh checkout", only
  tracked files are checked out, and gitignored files are copied only when a
  `.worktreeinclude` file names them. The repo has no `.worktreeinclude`.
- Measured in `git worktree add /tmp/claude-0/wt-test -b wt-test origin/main`:
  `ls -d .venv` → "No such file or directory"; `which python3` →
  `/usr/bin/python3`, Python 3.13.16; `python3 -m pytest --version` →
  "No module named pytest".
- Running post-edit.sh in that worktree with the relative path
  `src/store/pg_client.py`: rc 0 in 0.045 s. `PY` fell back to system
  `python3`, py_compile passed, and `[ -x .venv/bin/pytest ] || exit 0` skipped
  the suite silently (`post-edit.sh:37`).
- So in a worktree with no `.venv`, no subagent runs the suite from the hook,
  whatever the path shape. Each worktree does not "run its own suite"; it runs
  none.
- The repo venv is Python 3.13.16 (`.venv/bin/python --version`), not the
  3.12 that `AGENTS.md` names. `pytest` collected and passed under it.

### A shared venv works from a worktree

- `ln -s /home/user/SILO-BZ/.venv /tmp/claude-0/wt-a/.venv`, then in `wt-a`:
  `.venv/bin/python -c 'import sys; print(sys.prefix)'` →
  `/tmp/claude-0/wt-a/.venv`; `pytest --co -q` → `3870 tests collected`;
  `rootdir: /tmp/claude-0/wt-a`. `pytest.ini`'s `pythonpath = .` resolved to
  the worktree, so the worktree's own `src/` was imported, not the main
  checkout's.
- Two full suites at once in `wt-a` and `wt-b`, both on the symlinked venv,
  4 CPUs: wall-clock **92 s**; `wt-a` 81.5 s, `wt-b` 89.8 s, both
  `3850 passed, 20 skipped`. One suite alone took 85.3 s. Two in parallel cost
  about 8 % more wall-clock than one, on this machine, with nothing else running.
  N was not measured beyond 2.

### pre-push-docs.sh in a worktree

- `pre-push-docs.sh:28-33`: it `cd`s to the payload's `cwd`, compares
  `git rev-parse --path-format=absolute --git-common-dir` there with the same
  for `${CLAUDE_PROJECT_DIR:-.}`, and exits 0 if they differ.
- The hooks doc, "Worktrees are different": `${CLAUDE_PROJECT_DIR}` "stays
  put" at the project root; `cwd` in the input JSON "is the worktree root after
  Claude enters a worktree".
- Measured in `/tmp/claude-0/wt-test`: both `git-common-dir` values were
  `/home/user/SILO-BZ/.git`. The equality test passes, so the hook judges the
  push. `git symbolic-ref --short HEAD` → `wt-test`, the worktree's branch.
- Measured with one committed doc file in `wt-a` and payload
  `{"tool_input":{"command":"git push -u origin wt-a"},"cwd":"/tmp/claude-0/wt-a"}`,
  `CLAUDE_PROJECT_DIR=/home/user/SILO-BZ`: `permissionDecision: deny`, reason
  "No CHANGELOG row. `wt-a` changes 1 file(s) ... Create
  docs/planning/changelog.d/2026-10-07_wt-a.md ...". With a
  `No-changelog: probe` trailer amended onto the commit: empty output, rc 0,
  push allowed.
- `pre-push-docs.sh:155`: the once-per-branch README marker is
  `git rev-parse --git-path claude-docs-checked`. In a worktree that resolves
  to `/home/user/SILO-BZ/.git/worktrees/wt-a/claude-docs-checked` (measured).
  The marker is per worktree, so the README ask fires once per worktree, and it
  is deleted with the worktree.
- `pre-push-docs.sh:59`: the fragment name uses `date -u`, so a branch pushed
  after 21:00 UTC-3 is asked for the next day's date.

### Where a subagent's hooks run

- The sub-agents doc, "Working directory": "A subagent with `isolation:
worktree` runs its Bash and PowerShell commands inside its worktree."
- The hooks doc: the hook's `cwd` follows Claude. `bash .claude/hooks/post-edit.sh`
  (`settings.json:72`) is a relative path, so it runs the worktree's copy of the
  script in the worktree, where `.venv` is absent (see above). The pre-push hook
  uses `${CLAUDE_PROJECT_DIR}` and runs the main checkout's copy.
- The worktrees doc, "Isolate subagents with worktrees": a subagent in a
  worktree under `.claude/worktrees/` "doesn't load the `CLAUDE.md` file or
  `.claude/rules/` directory at the worktree's root"; it takes instruction
  files from the main conversation.

## 2. Disk

| Item                                      | Measured                      |
| ----------------------------------------- | ----------------------------- |
| `du -sh .venv`                            | 534M                          |
| `du -sh --exclude=.venv --exclude=.git .` | 30M                           |
| `du -sh .git`                             | 5.9M                          |
| `df -h /home/user`                        | `/dev/vda 252G 11G 29G 26% /` |
| `nproc`                                   | 4                             |
| `free -h`                                 | 15Gi total, 14Gi free         |

- A checkout without `.venv` is 30 MB. A worktree with its own venv is about
  564 MB. The session reports 29 GB available, so N own-venv worktrees cost
  about 0.56 GB × N; a venv shared by symlink costs about 0.03 GB × N.
- `git worktree add /tmp/claude-0/wt-test -b wt-test origin/main` → rc 0,
  "Preparing worktree (new branch 'wt-test')", HEAD at `1020cca`.
  `git worktree remove /tmp/claude-0/wt-test` → rc 0. `git branch -D wt-test`
  → "Deleted branch wt-test". Both worked. Adding two worktrees took 0.25 s
  (`time`).
- A worktree with a commit needs `git worktree remove --force` (measured on
  `wt-a`; the worktrees doc, "Clean up", says the same for uncommitted or
  untracked files).
- The worktrees doc: Claude Code creates its own worktrees under
  `.claude/worktrees/<name>/` on branch `worktree-<name>`, holds a
  `git worktree lock` while the agent runs, removes an unchanged subagent
  worktree at once, and sweeps changed ones after `cleanupPeriodDays`.
  Non-interactive `-p` runs leave worktrees and locks in place. The repo's
  `.gitignore:38-39` already ignores `.claude/worktrees/`; there is no
  `.worktreeinclude` file.

## 3. The Workflow tool against Agent fan-out with `isolation: "worktree"`

Facts from the `workflow-authoring` skill text as loaded in this session. The
Workflow tool itself was not in this subagent's tool list; the skill says it
"does not itself authorize running one" and that use is opt-in per the tool
description.

What Workflow adds:

- **A script with deterministic control flow.** Plain JavaScript (no
  TypeScript, no filesystem or Node API, no `Date.now()`, `Math.random()` or
  argless `new Date()`), run in an async context. Loops, conditionals and
  fan-out are code, not model turns.
- **Phases.** `export const meta = {name, description, phases: [...]}` as a
  pure literal; `phase('Title')` groups later `agent()` calls in the progress
  display; `opts.phase` pins an agent to a group inside `pipeline()`.
- **`pipeline(items, stage1, stage2, ...)`.** Each item runs through all stages
  with no barrier. Wall-clock is the slowest single-item chain. A stage that
  throws drops its item to `null`. The skill says this is the default.
- **`parallel(thunks)`.** A barrier: awaits all; a failed thunk resolves to
  `null`; never rejects.
- **Typed results.** `agent(prompt, {schema})` forces a `StructuredOutput`
  call and returns the validated object; the model retries on mismatch.
  Without a schema the final text is returned as a string. `null` if the user
  skips the agent or it dies on a terminal API error.
- **Resume.** Every run persists its script and returns a `runId`;
  `Workflow({scriptPath, resumeFromRunId})` replays the longest unchanged
  prefix of `agent()` calls from cache and runs the rest live. The journal is
  `<transcriptDir>/journal.jsonl`.
- **`args`, `budget`, `workflow()`.** `args` is passed verbatim (arrays as
  JSON, not strings). `budget.total/spent()/remaining()` is the "+500k"
  ceiling and is hard: `agent()` throws once spent. `workflow(name|{scriptPath},
args)` nests one level only.
- **`agent()` options.** `label`, `phase`, `schema`, `model` (omit by
  default), `effort`, `agentType`, `isolation: 'worktree'`.

Its constraints, from the same text:

- `isolation: 'worktree'` is "EXPENSIVE (~200-500ms setup + disk per agent),
  use ONLY when agents mutate files in parallel"; the worktree is auto-removed
  if unchanged. (Measured here: 0.25 s for two `git worktree add`, 30 MB each.)
- Concurrent `agent()` calls are capped at `min(16, available CPUs - 2)` per
  workflow. On this 4-CPU machine that is **2** at a time; extra calls queue.
- Lifetime cap of 1000 agents per workflow; at most 4096 items per
  `parallel()`/`pipeline()` call.
- Subagents get the same `CLAUDE.md` files as the main session (except
  built-in types such as Explore and Plan).
- Workflow agents reach MCP tools through `ToolSearch`; interactively
  authenticated servers may be absent in headless runs.
- The skill text has no "under 10 agents" size guideline. It says "Scale to
  what the user asked for" and gives the caps above. The number in #699 is not
  in the skill text; if it exists, it is in the Workflow tool description,
  which this session did not load.

What plain `Agent` fan-out has, from the sub-agents doc: `isolation: worktree`
in frontmatter or on the call; the subagent runs its Bash in the worktree,
branched from the default branch; the worktree is cleaned up if unchanged. The
doc names no pipeline, no resume, no typed return and no shared budget.

## 4. `gh` from this environment

- `gh api "repos/PedroDnT/SILO-BZ/pulls?state=open&per_page=1" -q '.[0].number'`
  → `694` (REST, works).
- `gh pr list -R PedroDnT/SILO-BZ --limit 1` →
  `HTTP 403: GitHub GraphQL is not available from Claude Code sessions; use the REST API (gh api repos/{owner}/{repo}/...). For review threads, auto-merge, and draft/ready-for-review use the CCR routes on api.github.com: GET /repos/{owner}/{repo}/pulls/{n}/ccr/review_threads, POST /repos/{owner}/{repo}/pulls/{n}/ccr/comments/{comment_id}/resolve (or /unresolve), PUT or DELETE /repos/{owner}/{repo}/pulls/{n}/ccr/auto_merge, POST /repos/{owner}/{repo}/pulls/{n}/ccr/ready_for_review, POST /repos/{owner}/{repo}/pulls/{n}/ccr/convert_to_draft. (https://api.github.com/graphql)`
- `gh api user -q .login` → `PedroDnT`. `gh auth status` says the `GH_TOKEN`
  "is invalid", yet REST calls succeed; the proxy, not the token, authenticates.
- `gh api repos/PedroDnT/SILO-BZ/pulls/694/ccr/auto_merge` (GET, read-only
  probe) → HTTP 404 "No such CCR pull-request route", with the same route list.
  The route exists for `PUT` and `DELETE` only, as the 403 text says.
- `gh api repos/PedroDnT/SILO-BZ/issues/699 -q .body` worked (REST issue read).
- Not tested, by instruction: creating a PR, enabling auto-merge, commenting
  on an issue. All three are REST or CCR `POST`/`PUT` routes per the text
  above. `gh pr create` and `gh pr merge` are in `settings.json:21-22` as
  allowed commands; `gh pr create` uses REST for the create itself.

## Measured

| Measure                                               | Value                        |
| ----------------------------------------------------- | ---------------------------- |
| Full offline suite, repo root, alone                  | 85.3 s (87.1 wall)           |
| Same suite, two at once in two worktrees, shared venv | 92 s wall; 81.5 s and 89.8 s |
| post-edit.sh, absolute `.py` path under `src/`        | 0.044 s, no pytest           |
| post-edit.sh, relative `src/...` path, repo root      | 86.7 s, pytest ran           |
| post-edit.sh, relative path, worktree without `.venv` | 0.045 s, no pytest           |
| PostToolUse hook timeout                              | 90 s                         |
| `.venv`                                               | 534 MB, Python 3.13.16       |
| Checkout without `.venv` and `.git`                   | 30 MB                        |
| `.git`                                                | 5.9 MB                       |
| Disk available                                        | 29 GB of 252 GB              |
| CPUs / RAM                                            | 4 / 15 GiB                   |
| Two `git worktree add`                                | 0.25 s                       |
| Workflow concurrency cap here (`min(16, CPUs-2)`)     | 2                            |
| REST `gh api` open PR number                          | 694                          |
| GraphQL `gh pr list`                                  | HTTP 403                     |

## What this means for the design

- A subagent in a worktree does not run the suite from the post-edit hook:
  the worktree has no `.venv`, and the hook skips silently. If the design wants
  tests per worktree, it must run them itself or give the worktree a venv (a
  symlink to the root `.venv` worked here; a `.worktreeinclude` cannot copy a
  534 MB venv cheaply).
- The post-edit pytest branch also does not fire in the main checkout, because
  Claude Code sends absolute paths. Any plan that counts on "the hook runs the
  suite on every edit" counts on something that is not happening. Report to
  the owner; do not fix inside #699.
- The suite is 85 s and the hook timeout is 90 s. A hook-run suite is one slow
  disk away from a silent timeout. Two suites at once cost 92 s on 4 CPUs, so
  N parallel suites scale about linearly in CPU, and the Workflow cap of 2
  agents at a time on this machine bounds N anyway.
- pre-push-docs.sh works in a worktree: same common dir, branch read from the
  worktree, `No-changelog:` trailer honoured. Its once-per-branch marker is per
  worktree, so each worktree gets the README ask once.
- Disk is not the limit: 30 MB per worktree, 29 GB free. A venv per worktree
  (0.56 GB each) is affordable but slow to build; a shared venv is 0 MB.
- `gh` is REST-only here. PR creation, auto-merge (`PUT .../ccr/auto_merge`)
  and issue comments are REST or CCR write routes; none was exercised in this
  research.
