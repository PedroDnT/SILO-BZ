"""The pre-push docs check: every merge carries its own planning and README update.

`docs/planning/CHANGELOG.md` is "one row per merged branch", and until
2026-09-26 that was a convention only. Four of the thirty PRs merged before
this file (#292, #302, #303, #304) carried no row, and README.md changed in five
of the thirty while the facts it states kept moving. PRs here auto-merge on
green, so the last moment to put the docs in is before the push that publishes
the branch. That is where `.claude/hooks/pre-push-docs.sh` sits: a PreToolUse
hook on `git push` in `.claude/settings.json`.

Its contract, pinned below:

* no CHANGELOG row on the branch -> the push is denied, every time, until the
  row lands or a commit carries a `No-changelog: <reason>` trailer;
* a row main had at the merge base missing from HEAD, word for word -> the
  push is denied, every time, until the row is back or a commit carries a
  `Changelog-removes: <reason>` trailer. On 2026-09-26 GitHub's update of
  #322's branch from main dropped #324's and #325's rows, and the PR merged
  green. `.github/workflows/test.yml` runs the same comparison on pull
  requests, for the merges this hook never sees;
* README.md untouched -> the push is denied ONCE per branch with a staleness
  checklist (README, planning index, OPEN_ITEMS); the next push goes through,
  so the check costs one round trip, never a loop;
* anything it cannot judge (not a push, a branch delete, `main`, nothing
  changed, another repository) passes. The hook guards docs; it must never be
  what blocks an unrelated command. A skip it did not expect is shown to the
  user, not swallowed.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / ".claude/hooks/pre-push-docs.sh"
SETTINGS = ROOT / ".claude/settings.json"
WORKFLOW = ROOT / ".github/workflows/test.yml"

pytestmark = pytest.mark.skipif(
    not all(shutil.which(tool) for tool in ("bash", "git", "jq")),
    reason="needs bash, git and jq",
)

BRANCH = "claude/some-feature"
HEADER = "| Date | Branch | Change |\n| --- | --- | --- |\n"
ROW = HEADER + f"| 2026-09-26 | {BRANCH} | **A change.** Why it matters. |\n"
# Two rows another branch lands on main first, as #324 and #325 did.
THEIRS = ["| 2026-09-26 | claude/other | **Catalog v40: a new endpoint.** Why. |",
          "| 2026-09-26 | claude/other | **Slice 1 is built.** Why. |"]
RESTORED = ROW + "".join(f"{row}\n" for row in THEIRS)
README = {"README.md": "# SILO\nA new fact.\n"}  # keeps the README check out of the way
# A git hook running this suite would leak GIT_DIR / GIT_INDEX_FILE into the
# scratch repositories below.
ENV = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com",
         "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null", *args],
        cwd=repo, env=ENV, check=True, capture_output=True, text=True,
    ).stdout


def commit(repo: Path, files: dict[str, str], message: str = "change") -> None:
    for name, text in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)


def make_repo(path: Path) -> Path:
    """A clone whose origin/main is its first commit, on a fresh branch."""
    git(path, "init", "-q", "-b", "main")
    commit(path, {
        "README.md": "# SILO\n",
        "docs/planning/CHANGELOG.md": HEADER,
        "docs/planning/README.md": "# Planning\n",
        "docs/planning/AGENTS.md": "# Agents\n",
        "src/app.py": "x = 1\n",
    }, "initial")
    git(path, "update-ref", "refs/remotes/origin/main", "HEAD")
    git(path, "checkout", "-q", "-b", BRANCH)
    return path


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    return make_repo(tmp_path)


def run_hook(repo: Path, command: str = f"git push -u origin {BRANCH}",
             project: Path | None = None, hook: Path = HOOK) -> dict | None:
    """Run the hook as Claude Code does. None means the push goes through."""
    payload = {"hook_event_name": "PreToolUse", "tool_name": "Bash",
               "tool_input": {"command": command}, "cwd": str(repo)}
    env = {**ENV, "CLAUDE_PROJECT_DIR": str(project or repo)}
    out = subprocess.run(["bash", str(hook)], input=json.dumps(payload), env=env,
                         check=True, capture_output=True, text=True)
    return json.loads(out.stdout) if out.stdout.strip() else None


def advance_main(repo: Path, changelog: str) -> None:
    """Another branch merges first: main gains rows this branch does not have."""
    git(repo, "checkout", "-q", "main")
    commit(repo, {"docs/planning/CHANGELOG.md": changelog}, "another branch merges")
    git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    git(repo, "checkout", "-q", BRANCH)


def merge_main_keeping_our_changelog(repo: Path) -> None:
    """#322's shape: the branch has its row, main gains two, and the merge of
    main into the branch keeps the branch's side of the CHANGELOG conflict."""
    commit(repo, {"src/app.py": "x = 2\n", "docs/planning/CHANGELOG.md": ROW, **README})
    advance_main(repo, HEADER + "".join(f"{row}\n" for row in THEIRS))
    git(repo, "merge", "-q", "--no-edit", "-X", "ours", "main")


def denied(result: dict | None) -> str:
    assert result is not None, "expected the push to be held"
    decision = result["hookSpecificOutput"]
    assert decision["permissionDecision"] == "deny"
    return decision["permissionDecisionReason"]


def test_a_branch_without_a_changelog_row_is_held_until_it_has_one(repo):
    commit(repo, {"src/app.py": "x = 2\n"})
    first = denied(run_hook(repo))
    assert "No CHANGELOG row" in first and f"| {BRANCH} |" in first
    # Required, not merely suggested: the next push is held again.
    assert "No CHANGELOG row" in denied(run_hook(repo))
    commit(repo, {"docs/planning/CHANGELOG.md": ROW})
    assert run_hook(repo) is None


def test_the_readme_check_is_asked_once_per_branch(repo):
    commit(repo, {"src/app.py": "x = 2\n", "docs/planning/CHANGELOG.md": ROW})
    reason = denied(run_hook(repo))
    assert "No CHANGELOG row" not in reason
    for doc in ("README.md", "docs/planning/README.md", "docs/planning/OPEN_ITEMS.md"):
        assert doc in reason
    assert run_hook(repo) is None


def test_a_branch_that_updates_the_readme_is_not_asked(repo):
    commit(repo, {"src/app.py": "x = 2\n", "docs/planning/CHANGELOG.md": ROW,
                  "README.md": "# SILO\nA new fact.\n"})
    assert run_hook(repo) is None


def test_a_no_changelog_trailer_stands_in_for_the_row(repo):
    commit(repo, {"docs/planning/COMPETITIVE_GAPS.md": "gaps\n"},
           "Update the landscape\n\nNo-changelog: the Scout edits COMPETITIVE_GAPS.md only")
    assert "No CHANGELOG row" not in denied(run_hook(repo))
    assert run_hook(repo) is None


def test_a_merge_that_drops_rows_main_had_is_held_until_they_are_back(repo):
    merge_main_keeping_our_changelog(repo)
    reason = denied(run_hook(repo))
    assert "CHANGELOG rows dropped" in reason and "no longer has 2 row(s)" in reason
    assert all(row in reason for row in THEIRS)
    assert f"| {BRANCH} |" not in reason  # its own row is not the missing one
    # Required, not merely suggested: the next push is held again.
    assert "CHANGELOG rows dropped" in denied(run_hook(repo))
    commit(repo, {"docs/planning/CHANGELOG.md": RESTORED})
    assert run_hook(repo) is None


def test_the_dropped_rows_are_named_briefly(repo):
    long_rows = [f"| 2026-09-2{i} | claude/b{i} | **Row {i}.** {'why ' * 60}|"
                 for i in range(9, 2, -1)]
    advance_main(repo, HEADER + "".join(f"{row}\n" for row in long_rows))
    git(repo, "merge", "-q", "--ff-only", "main")
    commit(repo, {"docs/planning/CHANGELOG.md": ROW, **README})
    reason = denied(run_hook(repo))
    assert "no longer has 7 row(s)" in reason and "…and 2 more" in reason
    named = [line for line in reason.splitlines() if line.startswith("| 20")]
    assert named == [row[:160] + "…" for row in long_rows[:5]]


def test_a_branch_behind_main_is_not_blamed_for_rows_it_never_had(repo):
    """The comparison is with the merge base, not origin/main's tip. Every merge
    adds a row to main, so comparing with the tip would hold nearly every push
    and send the branch off to merge main, the very step that drops rows."""
    commit(repo, {"src/app.py": "x = 2\n", "docs/planning/CHANGELOG.md": ROW, **README})
    advance_main(repo, HEADER + "".join(f"{row}\n" for row in THEIRS))
    assert run_hook(repo) is None


def test_a_changelog_removes_trailer_lets_a_deliberate_removal_through(repo):
    """#318 removed a stale duplicate row on purpose. A trailer says so."""
    advance_main(repo, HEADER + "".join(f"{row}\n" for row in THEIRS))
    git(repo, "merge", "-q", "--ff-only", "main")
    commit(repo, {"docs/planning/CHANGELOG.md": ROW + f"{THEIRS[0]}\n", **README})
    assert THEIRS[1] in denied(run_hook(repo))
    commit(repo, {"src/app.py": "x = 2\n"},
           "Say why the row goes\n\nChangelog-removes: a stale duplicate of a later row")
    assert run_hook(repo) is None


COMPARISON = 'dropped=$(grep -vxFf <(rows HEAD) <(rows "$base"))'


def test_the_dropped_row_test_fails_without_the_comparison(repo, tmp_path_factory):
    """Mutation check: with the comparison disabled, the merge that drops rows
    goes through. The deny pinned above comes from the comparison, not from
    anything else the hook checks."""
    source = HOOK.read_text(encoding="utf-8")
    assert source.count(COMPARISON) == 1, "the comparison changed; update COMPARISON"
    mutant = tmp_path_factory.mktemp("mutant") / "pre-push-docs.sh"
    mutant.write_text(source.replace(COMPARISON, 'dropped=""'), encoding="utf-8")
    merge_main_keeping_our_changelog(repo)
    assert run_hook(repo, hook=mutant) is None
    assert "CHANGELOG rows dropped" in denied(run_hook(repo))


CI_STEP = "No CHANGELOG row dropped against the base branch"


def ci_step() -> dict:
    yaml = pytest.importorskip("yaml")
    spec = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return next(step for step in spec["jobs"]["pytest"]["steps"]
                if step.get("name") == CI_STEP)


def run_ci_step(repo: Path, runner: Path) -> subprocess.CompletedProcess:
    """Run the test.yml step where actions/checkout leaves a pull request:
    detached on GitHub's merge of the branch into main, one commit deep."""
    git(repo, "checkout", "-q", "-b", "pull-merge", "main")
    git(repo, "merge", "-q", "--no-ff", "--no-edit", BRANCH)
    git(repo, "update-ref", "refs/pull/1/merge", "HEAD")
    git(repo, "checkout", "-q", BRANCH)
    git(runner, "init", "-q")
    git(runner, "remote", "add", "origin", repo.as_uri())
    git(runner, "fetch", "-q", "--no-tags", "--depth=1", "origin",
        "+refs/pull/1/merge:refs/remotes/pull/1/merge")
    git(runner, "checkout", "-q", "--detach", "refs/remotes/pull/1/merge")
    return subprocess.run(["bash", "-e", "-c", ci_step()["run"]], cwd=runner,
                          env={**ENV, "BASE_REF": "main"}, capture_output=True, text=True)


def test_ci_runs_the_comparison_on_pull_requests():
    """A PR's pytest job, so it gates whatever already gates that job."""
    step = ci_step()
    assert step["if"] == "github.event_name == 'pull_request'"
    assert step["env"] == {"BASE_REF": "${{ github.base_ref }}"}


def test_ci_fails_a_pull_request_that_drops_rows_main_had(repo, tmp_path_factory):
    merge_main_keeping_our_changelog(repo)
    result = run_ci_step(repo, tmp_path_factory.mktemp("runner"))
    assert result.returncode == 1, result.stdout + result.stderr
    assert "::error file=docs/planning/CHANGELOG.md::2 CHANGELOG row(s)" in result.stdout
    assert all(row in result.stdout for row in THEIRS)


@pytest.mark.parametrize("fix", ["restore the rows", "Changelog-removes trailer"])
def test_ci_passes_once_the_rows_are_back_or_the_removal_is_declared(
        repo, tmp_path_factory, fix):
    merge_main_keeping_our_changelog(repo)
    if fix == "restore the rows":
        commit(repo, {"docs/planning/CHANGELOG.md": RESTORED})
    else:
        commit(repo, {"src/app.py": "x = 3\n"},
               "Drop two rows\n\nChangelog-removes: superseded by a later row")
    result = run_ci_step(repo, tmp_path_factory.mktemp("runner"))
    assert result.returncode == 0, result.stdout + result.stderr


def test_an_edited_planning_doc_points_at_its_index_row(repo):
    commit(repo, {"docs/planning/AGENTS.md": "# Agents\nchanged\n",
                  "docs/planning/CHANGELOG.md": ROW})
    assert "This branch edits AGENTS.md" in denied(run_hook(repo))


def test_a_push_inside_a_compound_command_is_checked(repo):
    commit(repo, {"src/app.py": "x = 2\n"})
    reason = denied(run_hook(repo, f"pytest -q && git push -u origin {BRANCH}"))
    assert "No CHANGELOG row" in reason


@pytest.mark.parametrize("command", [
    "git status",
    "git log --grep push",
    f"git push origin --delete {BRANCH}",
    f"git push origin :{BRANCH}",
    "git push --tags",
])
def test_commands_that_publish_no_branch_content_pass(repo, command):
    commit(repo, {"src/app.py": "x = 2\n"})
    assert run_hook(repo, command) is None


def test_main_and_an_unchanged_branch_pass(repo):
    assert run_hook(repo) is None
    git(repo, "checkout", "-q", "main")
    commit(repo, {"src/app.py": "x = 2\n"})
    assert run_hook(repo, "git push origin main") is None


def test_a_push_in_another_repository_passes(repo, tmp_path_factory):
    other = make_repo(tmp_path_factory.mktemp("other"))
    commit(other, {"src/app.py": "x = 2\n"})
    assert run_hook(other, project=repo) is None


def test_a_skip_it_did_not_expect_is_shown_not_swallowed(repo):
    commit(repo, {"src/app.py": "x = 2\n"})
    git(repo, "update-ref", "-d", "refs/remotes/origin/main")
    result = run_hook(repo)
    assert result == {"systemMessage": "docs check skipped: no origin/main in this clone"}


def test_the_hook_is_wired_to_git_push():
    settings = json.loads(SETTINGS.read_text(encoding="utf-8"))
    handlers = [handler for group in settings["hooks"]["PreToolUse"]
                if group["matcher"] == "Bash" for handler in group["hooks"]]
    wired = [h for h in handlers if "pre-push-docs.sh" in h["command"]]
    assert len(wired) == 1 and wired[0]["if"] == "Bash(git push *)"


def test_the_prettier_hook_leaves_the_changelog_alone(tmp_path):
    """Prettier pads every row of a markdown table to the widest cell: 228
    changed lines on this changelog, the churn test_changelog_integrity.py
    refuses to normalise. The hook above sends every branch to that file."""
    settings = json.loads(SETTINGS.read_text(encoding="utf-8"))
    command = next(handler["command"] for group in settings["hooks"]["PostToolUse"]
                   for handler in group["hooks"] if "prettier" in handler["command"])
    calls = tmp_path / "calls"
    fake = tmp_path / "bin" / "prettier"
    fake.parent.mkdir()
    fake.write_text(f'#!/usr/bin/env bash\necho "$@" >> "{calls}"\n', encoding="utf-8")
    fake.chmod(0o755)
    env = {**ENV, "PATH": f"{fake.parent}{os.pathsep}{ENV['PATH']}"}
    for path in ("/repo/docs/planning/CHANGELOG.md", "/repo/README.md"):
        subprocess.run(["bash", "-c", command], env=env, check=True, text=True,
                       input=json.dumps({"tool_input": {"file_path": path}}))
    formatted = calls.read_text(encoding="utf-8").splitlines()
    assert len(formatted) == 1 and formatted[0].endswith("/repo/README.md")
