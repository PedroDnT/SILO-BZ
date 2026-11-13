"""The post-edit hook: py_compile every edited .py, the offline suite when src/,
serve/, tests/ or scripts/ change (`.claude/hooks/post-edit.sh`, a PostToolUse
hook on Write|Edit in `.claude/settings.json`).

Found 2026-10-06 (#708): Claude Code sends the edited file as an absolute
path, and the hook matched `src/*|serve/*|tests/*|scripts/*` against it
relative, so the pytest branch never ran, in any session, since the hook was
written. The 90 s hook timeout was also under the suite's 85 s. Pinned here:

* an absolute path under the checkout is made relative and then classified;
* a relative path is classified as before;
* a .py outside the four directories compiles only;
* a path outside the checkout is ignored;
* the hook's timeout in settings.json leaves the suite room to finish;
* every hook command in settings.json runs its script through
  `${CLAUDE_PROJECT_DIR}`, so a session that has `cd`-ed elsewhere (say
  `dashboard/`) still finds it (#1110: the post-edit hook was relative and
  exited 127 there).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / ".claude/hooks/post-edit.sh"
SETTINGS = ROOT / ".claude/settings.json"

pytestmark = pytest.mark.skipif(
    not all(shutil.which(tool) for tool in ("bash", "git", "jq")),
    reason="needs bash, git and jq",
)

# The suite was 85 s on 2026-10-06 (3850 tests); the hook must not time out on it.
SUITE_SECONDS_MEASURED = 85


def _run(file_path: str) -> str:
    payload = json.dumps({"tool_input": {"file_path": file_path}})
    env = {**os.environ, "POST_EDIT_DRY_RUN": "1"}
    out = subprocess.run(
        ["bash", str(HOOK)], input=payload, text=True, capture_output=True,
        cwd=ROOT, env=env, check=False,
    )
    assert out.returncode == 0, out.stderr
    return out.stdout.strip()


def test_absolute_path_under_src_runs_pytest():
    assert _run(str(ROOT / "src/store/pg_client.py")) == "pytest src/store/pg_client.py"


def test_relative_path_under_src_runs_pytest():
    assert _run("src/store/pg_client.py") == "pytest src/store/pg_client.py"


def test_absolute_path_under_tests_runs_pytest():
    assert _run(str(ROOT / "tests/conftest.py")) == "pytest tests/conftest.py"


def test_py_outside_the_four_dirs_compiles_only(tmp_path):
    other = ROOT / "sdk/silo_client/__init__.py"
    assert other.is_file()
    assert _run(str(other)) == "compile-only sdk/silo_client/__init__.py"


def test_path_outside_the_checkout_is_ignored(tmp_path):
    outside = tmp_path / "x.py"
    outside.write_text("x = 1\n")
    assert _run(str(outside)) == ""


def test_hook_timeout_leaves_the_suite_room():
    settings = json.loads(SETTINGS.read_text())
    hooks = [
        h
        for group in settings["hooks"]["PostToolUse"]
        for h in group["hooks"]
        if "post-edit.sh" in h.get("command", "")
    ]
    assert len(hooks) == 1
    assert hooks[0]["timeout"] >= 2 * SUITE_SECONDS_MEASURED


def _hook_commands(settings: dict) -> list[str]:
    return [
        h["command"]
        for groups in settings["hooks"].values()
        for group in groups
        for h in group["hooks"]
        if h.get("type") == "command"
    ]


def test_every_hook_command_is_anchored_on_the_project_dir():
    commands = _hook_commands(json.loads(SETTINGS.read_text()))
    assert commands
    for command in commands:
        assert command.startswith('bash "${CLAUDE_PROJECT_DIR}/.claude/hooks/'), command
        script = command.split("${CLAUDE_PROJECT_DIR}/", 1)[1].rstrip('"')
        assert (ROOT / script).is_file(), command


def test_post_edit_hook_runs_from_another_directory(tmp_path):
    """The settings.json command itself, run from outside the checkout root."""
    (command,) = [c for c in _hook_commands(json.loads(SETTINGS.read_text())) if "post-edit.sh" in c]
    payload = json.dumps({"tool_input": {"file_path": str(ROOT / "src/store/pg_client.py")}})
    env = {**os.environ, "POST_EDIT_DRY_RUN": "1", "CLAUDE_PROJECT_DIR": str(ROOT)}
    out = subprocess.run(
        ["bash", "-c", command], input=payload, text=True, capture_output=True,
        cwd=ROOT / "dashboard", env=env, check=False,
    )
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "pytest src/store/pg_client.py"
