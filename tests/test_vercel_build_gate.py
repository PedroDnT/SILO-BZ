"""The Vercel build gate: skip builds a commit cannot change, refresh on a hook.

A dashboard build fires ~90 queries at production Supabase and takes 25-45
minutes. Vercel builds every commit, so a tests-only commit paid that price for
a byte-identical site. On 2026-08-26 four builds overlapped: shared source
queries slowed 5x, two hit BUILD_EXCEEDED_MAXIMUM_TIME, and their concurrent
scans of cvm_fi_perfil blocked the schema apply's ALTER TABLE until the server
killed it — so migration 14 and everything after it never ran. Three of those
four builds were for commits that never touched dashboard/.

Vercel's ignoreCommand contract is inverted: exit 0 SKIPS, exit 1 BUILDS.
Getting that backwards silently stops publishing the site, so it is pinned here.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/vercel_should_build.sh"
VERCEL_JSON = ROOT / "vercel.json"

SKIP, BUILD = 0, 1

yaml = pytest.importorskip("yaml")
pytestmark = pytest.mark.skipif(
    shutil.which("git") is None or shutil.which("bash") is None,
    reason="needs git and bash",
)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A throwaway repo with the real gate script installed."""
    r = tmp_path / "repo"
    (r / "scripts").mkdir(parents=True)
    (r / "dashboard").mkdir()
    _git(r.parent, "init", "-q", str(r))
    _git(r, "config", "user.email", "t@t")
    _git(r, "config", "user.name", "t")
    shutil.copy(SCRIPT, r / "scripts/vercel_should_build.sh")
    (r / "vercel.json").write_text("{}\n")
    (r / "dashboard/page.md").write_text("v1\n")
    (r / "README.md").write_text("v1\n")
    _git(r, "add", "-A")
    _git(r, "commit", "-qm", "base")
    return r


def _gate(repo: Path, **env: str) -> subprocess.CompletedProcess:
    """Run the gate. Keyword args become environment variables, so a test can
    supply the VERCEL_* values Vercel injects into the Ignored Build Step."""
    return subprocess.run(
        ["bash", "scripts/vercel_should_build.sh"],
        cwd=repo, capture_output=True, text=True,
        env={**os.environ, **env} if env else None,
    )


def _commit(repo: Path, rel: str, body: str) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.name == SCRIPT.name:
        # Never clobber the gate itself — the test would then execute garbage.
        # Appending a comment is a real content change to the same path.
        path.write_text(path.read_text() + f"\n# {body.strip()}\n")
    else:
        path.write_text(body)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", f"touch {rel}")


@pytest.mark.parametrize(
    "path",
    ["dashboard/page.md", "dashboard/sources/supabase/x.sql", "vercel.json",
     "scripts/vercel_should_build.sh"],
)
def test_builds_when_a_watched_path_changes(repo: Path, path: str):
    _commit(repo, path, "changed\n")
    result = _gate(repo)
    assert result.returncode == BUILD, (
        f"{path} affects the published site; exit {result.returncode} would SKIP "
        f"it.\n{result.stdout}"
    )


@pytest.mark.parametrize(
    "path",
    ["README.md", "tests/test_x.py", "src/pipeline/x.py",
     ".github/workflows/x.yml", "docs/API.md", "api-docs/quickstart.mdx"],
)
def test_skips_when_nothing_the_site_uses_changed(repo: Path, path: str):
    _commit(repo, path, "changed\n")
    result = _gate(repo)
    assert result.returncode == SKIP, (
        f"{path} cannot change the built site, so rebuilding costs ~30min of "
        f"Supabase queries for an identical result.\n{result.stdout}"
    )


def test_a_mixed_commit_builds(repo: Path):
    """Touching dashboard/ AND unrelated files must still build."""
    (repo / "dashboard/page.md").write_text("v2\n")
    (repo / "README.md").write_text("v2\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "mixed")
    assert _gate(repo).returncode == BUILD


def test_fails_open_without_a_parent_commit(tmp_path: Path):
    """Vercel shallow-clones. No HEAD^ means build — never silently skip."""
    r = tmp_path / "shallow"
    (r / "scripts").mkdir(parents=True)
    _git(tmp_path, "init", "-q", str(r))
    _git(r, "config", "user.email", "t@t")
    _git(r, "config", "user.name", "t")
    shutil.copy(SCRIPT, r / "scripts/vercel_should_build.sh")
    _git(r, "add", "-A")
    _git(r, "commit", "-qm", "only commit")
    result = _gate(r)
    assert result.returncode == BUILD, (
        "with no parent to diff against the gate must fail OPEN; a wrong skip "
        "silently ships a stale site"
    )


def test_builds_when_the_dashboard_changed_since_the_last_deployment(repo: Path):
    """The bug this diff base exists to fix.

    Land a dashboard change, then push an unrelated commit on top. Diffing
    HEAD^..HEAD asks "did the LAST commit touch the dashboard", sees nothing,
    and skips — so the dashboard change never reaches the site even though the
    deployed build predates it. VERCEL_GIT_PREVIOUS_SHA asks the question we
    actually mean: has anything changed since what is currently deployed.
    """
    deployed = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True,
    ).stdout.strip()
    _commit(repo, "dashboard/page.md", "a real dashboard change\n")
    _commit(repo, "README.md", "an unrelated commit on top\n")

    assert _gate(repo).returncode == SKIP, (
        "precondition: with no previous SHA the HEAD^ fallback skips — this is "
        "the shape of the bug, kept here so the regression is visible"
    )
    result = _gate(repo, VERCEL_GIT_PREVIOUS_SHA=deployed)
    assert result.returncode == BUILD, (
        "the dashboard changed since the deployed commit, so the site is stale "
        f"and must rebuild.\n{result.stdout}"
    )


def test_tries_to_fetch_a_previous_sha_that_is_not_in_the_clone(repo: Path):
    """Without this fetch the whole previous-SHA branch is DEAD CODE.

    Vercel shallow-clones, and the previous SHA is essentially never in the
    checkout: on deployment 5t9vBkhFVbezBGagY2KBE6ZciYov the variable was set
    to 1dac794 and `git cat-file -e` still missed, so the gate quietly stayed
    on HEAD^ — the exact bug it was meant to fix, shipped inert. The fetch is
    what makes the fix real, so its attempt is pinned here.
    """
    _commit(repo, "dashboard/page.md", "changed\n")
    result = _gate(repo, VERCEL_GIT_PREVIOUS_SHA="0" * 40)
    assert "fetched previous SHA" in result.stdout, (
        "the gate must TRY to fetch a previous SHA it does not have; without "
        f"that it can never use one.\n{result.stdout}"
    )


def test_falls_back_to_head_parent_when_the_previous_sha_is_unfetchable(repo: Path):
    """The fetch can still fail — no network, no origin, a garbage SHA.

    Resolving it blindly would make `git diff` fail and — depending on how that
    error were handled — could skip. The gate must notice and fall back. This
    throwaway repo has no `origin`, so the fetch genuinely cannot succeed.
    """
    _commit(repo, "dashboard/page.md", "changed\n")
    result = _gate(repo, VERCEL_GIT_PREVIOUS_SHA="0" * 40)
    assert result.returncode == BUILD, result.stdout
    assert "HEAD^" in result.stdout, (
        f"expected the fallback to be named in the log:\n{result.stdout}"
    )


def test_the_decision_log_names_the_vercel_variables(repo: Path):
    """A deploy hook fires on an unchanged commit, so every path-diff rule
    skips it — measured on 2026-08-29, when the hook returned 201 and the
    deployment went straight to CANCELED. Vercel documents no deploy-hook flag,
    so the log is the evidence for writing that rule later. Losing it would
    mean guessing.
    """
    _commit(repo, "README.md", "docs only\n")
    out = _gate(repo).stdout
    for var in ("VERCEL_GIT_COMMIT_SHA", "VERCEL_GIT_PREVIOUS_SHA",
                "VERCEL_GIT_COMMIT_REF", "VERCEL_ENV"):
        assert var in out, f"{var} missing from the decision log:\n{out}"


def test_vercel_json_wires_the_gate():
    cfg = json.loads(VERCEL_JSON.read_text())
    assert "ignoreCommand" in cfg, "the gate does nothing unless vercel.json calls it"
    assert "vercel_should_build.sh" in cfg["ignoreCommand"]
    # The build itself must still be the real one.
    assert "npm run sources" in cfg["buildCommand"]


def test_daily_ingest_dashboard_rebuild_is_dispatch_only_opt_in():
    """A fill or scheduled ingest must not start a competing dashboard build."""
    text = (ROOT / ".github/workflows/daily_ingest.yml").read_text()
    wf = yaml.safe_load(text)
    steps = wf["jobs"]["ingest"]["steps"]
    hook = [s for s in steps if "deploy hook" in s.get("name", "").lower()]
    assert hook, f"no deploy-hook step in: {[s.get('name') for s in steps]}"
    step = hook[0]
    condition = step.get("if", "")
    assert "github.event_name == 'workflow_dispatch'" in condition
    assert "rebuild_dashboard == 'true'" in condition
    assert "rebuild_dashboard:" in text
    assert "default: false" in text
    assert step.get("continue-on-error") is True, (
        "a failed redeploy must not fail an ingest whose data already landed"
    )
    body = step["run"]
    assert "VERCEL_DEPLOY_HOOK_URL" in body
    assert "skipping dashboard rebuild" in body, "must self-skip when unset"
    # It has to run after the analytical layer, or it publishes stale aggregates.
    names = [s.get("name", "") for s in steps]
    assert names.index(step["name"]) > names.index("Build / refresh analytical layer")


def test_backfill_is_sliceable_serial_and_never_rebuilds_dashboard():
    text = (ROOT / ".github/workflows/backfill.yml").read_text()
    wf = yaml.safe_load(text)
    jobs = wf["jobs"]

    assert "VERCEL_DEPLOY_HOOK_URL" not in text
    assert jobs["backfill-fi"]["strategy"]["max-parallel"] == 1
    assert jobs["backfill-other"]["strategy"]["max-parallel"] == 1
    assert "--start-year ${{ inputs.start_year }}" in text
    assert "--end-year ${{ inputs.end_year }}" in text
    assert "inputs.entity" in jobs["backfill-fi"]["if"]
    assert "fi_doc_type:" in text
    assert '--doc-type "${{ inputs.fi_doc_type }}"' in text
    assert "Print ingest_log + coverage snapshot" in text
    assert "started_at < NOW() - INTERVAL '24 hours'" in text
    assert "Marked stale by backfill coverage inspection after 24 hours" in text


def test_b3_backfill_accepts_an_exact_year_range():
    text = (ROOT / ".github/workflows/daily_ingest.yml").read_text()

    assert "end_year:" in text
    assert "--b3-start-year ${{ inputs.start_year }}" in text
    assert "--end-year ${{ inputs.end_year }}" in text
