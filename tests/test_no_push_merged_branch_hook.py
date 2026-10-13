"""The merged-branch push check: which branch a `git push` command pushes.

`.claude/hooks/no-push-merged-branch.sh` refuses a push of a branch whose PR is
already merged, because GitHub deleted that branch and the push recreates it.
Until #904 it took the branch from the session directory (the payload `cwd`)
and matched the words `git push` anywhere in a command. On 2026-10-13 that
blocked every orchestrate subagent: their `cwd` was the primary checkout, on
`main`, which matched the merged PR #44. It also let `git -C <worktree> push`
through unchecked, and blocked a heredoc that only mentioned the words.

The contract pinned here: the branch comes from an explicit refspec, else the
current branch of the directory the push runs in (`cd <dir> &&`, `git -C
<dir>`), and only then the payload `cwd`. Only a real push command counts.
`gh` is a stub on PATH, so the suite is offline.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / ".claude/hooks/no-push-merged-branch.sh"

pytestmark = pytest.mark.skipif(
    not all(shutil.which(tool) for tool in ("bash", "git", "jq", "awk")),
    reason="needs bash, git, jq and awk",
)

ENV = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
MERGED = "main:44 claude/done:12"  # branch:PR the stub reports as merged

GH_STUB = """#!/usr/bin/env bash
# Answers the hook's REST query from $MERGED and logs the branch it was asked.
for a in "$@"; do
  case "$a" in *head=*) b=${a#*head=\\{owner\\}:} ;; esac
done
echo "$b" >>"$GH_LOG"
for m in $MERGED; do
  [ "${m%:*}" = "$b" ] && echo "${m##*:}"
done
exit 0
"""


def git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com",
         "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null", *args],
        cwd=repo, env=ENV, check=True, capture_output=True, text=True,
    )


@pytest.fixture
def env(tmp_path: Path) -> dict:
    """A primary checkout on `main` and a worktree on an unmerged branch."""
    primary = tmp_path / "primary"
    primary.mkdir()
    git(primary, "init", "-q", "-b", "main")
    git(primary, "commit", "-q", "--allow-empty", "-m", "init")
    git(primary, "branch", "claude/done")
    worktree = tmp_path / "wt"
    git(primary, "worktree", "add", "-q", "-b", "orchestrator/904-fix", str(worktree))
    bindir = tmp_path / "bin"
    bindir.mkdir()
    stub = bindir / "gh"
    stub.write_text(GH_STUB)
    stub.chmod(0o755)
    return {"primary": primary, "worktree": worktree, "bin": bindir,
            "log": tmp_path / "gh.log"}


def run(env: dict, command: str, cwd: Path | None = None) -> tuple[int, str, list[str]]:
    payload = {"tool_input": {"command": command}, "cwd": str(cwd or env["primary"])}
    env["log"].unlink(missing_ok=True)
    proc = subprocess.run(
        ["bash", str(HOOK)], input=json.dumps(payload), capture_output=True, text=True,
        env={**ENV, "PATH": f"{env['bin']}{os.pathsep}{ENV['PATH']}",
             "MERGED": MERGED, "GH_LOG": str(env["log"])},
    )
    asked = env["log"].read_text().split() if env["log"].exists() else []
    return proc.returncode, proc.stderr, asked


def test_plain_push_checks_the_cwd_branch(env):
    code, err, asked = run(env, "git push")
    assert (code, asked) == (2, ["main"])
    assert "PR #44" in err
    assert run(env, "git push", cwd=env["worktree"])[0] == 0


def test_an_explicit_refspec_names_the_branch(env):
    code, _, asked = run(env, "git push -u origin orchestrator/904-fix")
    assert (code, asked) == (0, ["orchestrator/904-fix"])
    code, err, _ = run(env, "git push -u origin claude/done", cwd=env["worktree"])
    assert code == 2 and "claude/done" in err


def test_a_src_dst_refspec_checks_the_remote_branch(env):
    code, _, asked = run(env, "git push origin HEAD:refs/heads/claude/done",
                         cwd=env["worktree"])
    assert (code, asked) == (2, ["claude/done"])
    code, _, asked = run(env, "git push origin HEAD", cwd=env["worktree"])
    assert (code, asked) == (0, ["orchestrator/904-fix"])


def test_git_dash_c_uses_that_directory(env):
    """The #904 case: session on `main`, the push from a worktree goes through."""
    code, _, asked = run(env, f"git -C {env['worktree']} push -u origin HEAD")
    assert (code, asked) == (0, ["orchestrator/904-fix"])
    code, _, asked = run(env, f"git -C {env['worktree']} push", cwd=env["worktree"].parent)
    assert (code, asked) == (0, ["orchestrator/904-fix"])


def test_a_leading_cd_uses_that_directory(env):
    code, _, asked = run(env, f"cd {env['worktree']} && git push -u origin HEAD")
    assert (code, asked) == (0, ["orchestrator/904-fix"])
    code, _, asked = run(env, "cd ../primary && git push", cwd=env["worktree"])
    assert (code, asked) == (2, ["main"])


def test_a_heredoc_that_mentions_the_words_is_not_a_push(env):
    command = ("gh issue create --title t --body-file - <<'EOF'\n"
               "git push\ncd x && git push -u origin main\nEOF\n")
    assert run(env, command) == (0, "", [])


def test_quoted_text_and_comments_are_not_a_push(env):
    assert run(env, 'echo "run git push; git push origin main"') == (0, "", [])
    assert run(env, "echo ok # then git push") == (0, "", [])


def test_a_push_after_a_heredoc_is_still_checked(env):
    command = "cat >f <<EOF\ntext\nEOF\ngit push origin claude/done"
    code, _, asked = run(env, command)
    assert (code, asked) == (2, ["claude/done"])


def test_a_branch_delete_is_allowed(env):
    for command in ("git push origin --delete claude/done",
                    "git push -d origin claude/done",
                    "git push origin :claude/done"):
        assert run(env, command)[0] == 0, command


def test_a_directory_it_cannot_enter_fails_open(env):
    assert run(env, "cd /no/such/dir && git push") == (0, "", [])
    assert run(env, 'git -C "$WT" push origin HEAD') == (0, "", [])


def test_a_refspec_is_checked_even_from_a_directory_it_cannot_enter(env):
    code, _, asked = run(env, 'cd "$WT" && git push -u origin claude/done')
    assert (code, asked) == (2, ["claude/done"])
    code, _, asked = run(env, f"cd /no/such && cd {env['worktree']} && git push")
    assert (code, asked) == (0, ["orchestrator/904-fix"])


def test_a_quoted_newline_does_not_split_a_segment(env):
    code, _, asked = run(env, "git commit -m 'a\ngit push origin claude/done'")
    assert (code, asked) == (0, [])


def test_no_gh_fails_open(env, tmp_path):
    # PATH with git, jq and awk but no gh.
    bindir = tmp_path / "nogh"
    bindir.mkdir()
    for tool in ("git", "jq", "awk", "cat"):
        (bindir / tool).symlink_to(shutil.which(tool))
    payload = {"tool_input": {"command": "git push"}, "cwd": str(env["primary"])}
    proc = subprocess.run(["/bin/bash", str(HOOK)], input=json.dumps(payload),
                          capture_output=True, text=True, env={**ENV, "PATH": str(bindir)})
    assert proc.returncode == 0
