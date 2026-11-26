"""The gate-file list (scripts/gate_files.py) and the workflow that runs it.

A pull request that changes a gate file is merged by the owner, never by
auto-merge (#1208). The workflow test pins what keeps `pull_request_target`
safe: the script comes from the default branch and the token can only read.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from scripts.gate_files import GATE_DIRS, GATE_FILES, gate_paths, is_gate_path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/gate_files.yml"


def test_the_gate_list_is_the_one_the_issue_names():
    assert set(GATE_DIRS) == {".github/", ".claude/"}
    assert set(GATE_FILES) == {
        "CLAUDE.md",
        "AGENTS.md",
        "docs/planning/AGENTS.md",
        "scripts/verify_pipeline.py",
    }


@pytest.mark.parametrize(
    "path",
    [
        "CLAUDE.md",
        "AGENTS.md",
        "docs/planning/AGENTS.md",
        "scripts/verify_pipeline.py",
        ".github/dependabot.yml",
        ".github/workflows/test.yml",
        ".claude/settings.json",
        ".claude/skills/orchestrate/SKILL.md",
        ".claude/hooks/pre-push-docs.sh",
    ],
)
def test_gate_paths_match(path):
    assert is_gate_path(path)


@pytest.mark.parametrize(
    "path",
    [
        "AGENTS.md.bak",
        "CLAUDE.md.orig",
        "docs/planning/AGENTS_NOTES.md",
        "docs/planning/AGENTS.md.bak",
        "docs/AGENTS.md",
        "dashboard/AGENTS.md",
        "docs/agents/CLAUDE.md",
        "scripts/verify_pipeline.py.bak",
        "scripts/verify_pipeline_helpers.py",
        "tests/scripts/verify_pipeline.py",
        ".githubx/workflows/test.yml",
        ".claude.json",
        ".github",
        "docs/.github/workflows/test.yml",
        "README.md",
        "src/pipeline/run_daily.py",
        "scripts/gate_files.py",
    ],
)
def test_other_paths_do_not_match(path):
    assert not is_gate_path(path)


def test_gate_paths_keeps_order_and_drops_repeats_and_blanks():
    changed = [
        "README.md",
        ".github/workflows/test.yml\n",
        "",
        "AGENTS.md",
        "src/store/schema.sql",
        ".github/workflows/test.yml",
    ]
    assert gate_paths(changed) == [".github/workflows/test.yml", "AGENTS.md"]
    assert gate_paths(["README.md", "tests/test_gate_files.py"]) == []


def test_cli_prints_matches_from_stdin_and_from_arguments():
    script = str(ROOT / "scripts/gate_files.py")
    from_stdin = subprocess.run(
        [sys.executable, script],
        input="README.md\n.claude/settings.json\nCLAUDE.md\n",
        capture_output=True,
        text=True,
        check=True,
    )
    assert from_stdin.stdout == ".claude/settings.json\nCLAUDE.md\n"
    from_args = subprocess.run(
        [sys.executable, script, "README.md", "scripts/verify_pipeline.py"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert from_args.stdout == "scripts/verify_pipeline.py\n"
    nothing = subprocess.run(
        [sys.executable, script], input="README.md\n", capture_output=True, text=True, check=True
    )
    assert nothing.stdout == ""


def test_workflow_runs_from_main_with_a_read_only_token():
    text = WORKFLOW.read_text()
    workflow = yaml.safe_load(text)
    # PyYAML reads the bare key `on` as the boolean True.
    triggers = workflow[True]
    assert list(triggers) == ["pull_request_target"]
    assert set(triggers["pull_request_target"]["types"]) == {
        "opened",
        "synchronize",
        "reopened",
        "auto_merge_enabled",
        "auto_merge_disabled",
    }
    assert workflow["permissions"] == {"contents": "read", "pull-requests": "read"}

    (job,) = workflow["jobs"].values()
    # The owner adds this exact name to the required checks of the main ruleset.
    assert job["name"] == "gate files (no auto-merge)"
    assert "permissions" not in job
    # Not a job-level `if`: a required check must report for every pull request.
    assert "if" not in job

    checkouts = [s for s in job["steps"] if s.get("uses", "").startswith("actions/checkout@")]
    assert len(checkouts) == 1
    assert checkouts[0]["with"]["ref"] == "${{ github.event.repository.default_branch }}"
    for step in job["steps"]:
        if "uses" in step:
            sha = step["uses"].split("@")[1]
            assert len(sha) == 40 and all(c in "0123456789abcdef" for c in sha)

    # The PR's code is never fetched or run, and no PR field reaches the script
    # except through env.
    assert "pull_request.head" not in text
    assert "refs/pull" not in text
    for step in job["steps"]:
        assert "${{" not in step.get("run", "")
    run = job["steps"][-1]["run"]
    assert "set -euo pipefail" in run
    assert "scripts/gate_files.py" in run
    assert "pulls/$PR_NUMBER/files" in run
