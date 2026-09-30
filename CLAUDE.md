# CLAUDE.md

@AGENTS.md

## Claude Code

Everything above this heading is imported from `AGENTS.md`, the source of truth
for every agent in this repository. Add or change a rule there, never here. This
file exists because Claude Code loads `CLAUDE.md` when both files are present, and
it holds only what is specific to Claude Code.

The hooks in `.claude/settings.json`:

- **PostToolUse on Write and Edit** (`.claude/hooks/post-edit.sh`) runs
  `py_compile` on every edited `.py` file, and the offline pytest suite when the
  file is under `src/`, `serve/`, `tests/`, or `scripts/`. Failures surface; they
  are not swallowed.
- **PreToolUse on `git push`** (`.claude/hooks/pre-push-docs.sh`) enforces the
  "Every branch carries its own docs" rule of `AGENTS.md`. It holds a push until
  the branch adds its `docs/planning/CHANGELOG.md` row (or a
  `No-changelog: <reason>` commit trailer), holds it while any row main had at the
  merge base is missing or reworded (or a `Changelog-removes: <reason>` trailer),
  and once per branch, unless it edits `README.md`, asks for a README /
  planning-index / `OPEN_ITEMS.md` staleness check before publishing.
- **PreToolUse on Bash** (`.claude/hooks/npm-cwd-guard.sh`) refuses
  `npm install|i|ci` aimed at `$HOME` or at a directory with no `package.json`
  (`-g` is allowed).

Project skills are in `.claude/skills/` and the scheduled agents' prompts in
`.claude/agents/`.
