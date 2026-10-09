# CLAUDE.md

@AGENTS.md

@docs/agents/dataset-notes.md

## Claude Code

Everything above this heading is imported: `AGENTS.md`, the source of truth for
every agent in this repository, and `docs/agents/dataset-notes.md`, the
per-dataset detail. Add or change a rule in `AGENTS.md`, never here. This file
exists because Claude Code loads `CLAUDE.md` when both files are present, and it
holds only what is specific to Claude Code.

The hooks in `.claude/settings.json`:

- **PostToolUse on Write and Edit** (`.claude/hooks/post-edit.sh`) runs
  `py_compile` on every edited `.py` file, and the offline pytest suite when the
  file is under `src/`, `serve/`, `tests/`, or `scripts/` (timeout 300 s; the suite
  takes about 85 s). Claude Code sends absolute paths; the hook makes them relative
  to the checkout first, since 2026-10-06 (#708; before that the suite never ran).
  Failures surface; they are not swallowed.
- **PreToolUse on `git push`** (`.claude/hooks/pre-push-docs.sh`) enforces the
  "Every branch carries its own docs" rule of `AGENTS.md`. It holds a push until
  the branch adds its changelog row as a fragment, `docs/planning/changelog.d/<date>_<branch>.md`
  (or a `No-changelog: <reason>` commit trailer), holds it while any row main had at the
  merge base, in a fragment, `CHANGELOG.md` or its archive `docs/archive/changelog/`, is missing or reworded (or a `Changelog-removes: <reason>` trailer),
  and once per branch, unless it edits `README.md`, asks for a README /
  planning-index / `OPEN_ITEMS.md` staleness check before publishing. It also
  holds a push that changes files one of the four `docs/architecture/` pages
  describes (the map is in the script) until that page is edited, or a
  `No-architecture-change: <reason>` trailer says it is still right, and holds an
  edited page over its size cap (4 KiB, `DECISIONS.md` 5 KiB).
- **PreToolUse on `git push`** (`.claude/hooks/no-push-merged-branch.sh`) refuses a push
  from a branch whose PR is already merged (rule 6 of "Working beside other agents"),
  because GitHub deleted that branch and a push recreates it. `--delete` is allowed; it
  does nothing when `gh` is missing or offline.
- **PreToolUse on Bash** (`.claude/hooks/npm-cwd-guard.sh`) refuses
  `npm install|i|ci` aimed at `$HOME` or at a directory with no `package.json`
  (`-g` is allowed).
- **SessionStart** (`.claude/hooks/session-start.sh`) fetches `origin/main` and
  prints its last 5 commits and the open PRs (REST), so a session sees parallel
  work before it starts. It never blocks; a failed step prints `(unavailable)`.

Project skills are in `.claude/skills/` and the scheduled agents' prompts in
`.claude/agents/`. Root `skills-lock.json` pins the vendored skills that the
`skills` CLI installs into the gitignored `.agents/`; they are local, not
project skills, and no symlink to them is tracked (#681).
