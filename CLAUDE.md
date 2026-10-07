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
  file is under `src/`, `serve/`, `tests/`, or `scripts/`. Failures surface; they
  are not swallowed.
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
- **PreToolUse on Bash** (`.claude/hooks/npm-cwd-guard.sh`) refuses
  `npm install|i|ci` aimed at `$HOME` or at a directory with no `package.json`
  (`-g` is allowed).

Project skills are in `.claude/skills/` and the scheduled agents' prompts in
`.claude/agents/`. Root `skills-lock.json` pins the vendored skills that the
`skills` CLI installs into the gitignored `.agents/`; they are local, not
project skills, and no symlink to them is tracked (#681).
