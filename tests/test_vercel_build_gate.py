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


def _gate(repo: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", "scripts/vercel_should_build.sh"],
        cwd=repo, capture_output=True, text=True,
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
