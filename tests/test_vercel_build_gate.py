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

import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import textwrap
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
    ["dashboard/page.md", "dashboard/sources/supabase/x.sql",
     "dashboard/static/signin.html", "vercel.json",
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


def test_a_merge_commit_diffs_the_whole_pull_request(repo: Path):
    """Why HEAD^ is the right base here, pinned so nobody "fixes" it again.

    main advances only by merge commits. HEAD^ on a merge is the FIRST parent —
    main before the PR — so the diff is the entire pull request, not its tip
    commit. Two earlier attempts to replace this with VERCEL_GIT_PREVIOUS_SHA
    were dead code: the SHA is absent from Vercel's shallow clone and fetching
    it is refused on the build runner.
    """
    trunk = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo,
        capture_output=True, text=True,
    ).stdout.strip()
    _git(repo, "checkout", "-q", "-b", "feature")
    _commit(repo, "dashboard/page.md", "a dashboard change\n")
    _commit(repo, "README.md", "an unrelated commit on top of it\n")
    _git(repo, "checkout", "-q", trunk)
    _git(repo, "merge", "-q", "--no-ff", "-m", "Merge pull request #1", "feature")

    head_parents = subprocess.run(
        ["git", "log", "-1", "--format=%p"], cwd=repo, capture_output=True, text=True,
    ).stdout.split()
    assert len(head_parents) == 2, "precondition: this must be a merge commit"

    result = _gate(repo)
    assert result.returncode == BUILD, (
        "the PR touched dashboard/, so the merge must rebuild even though its "
        f"tip commit only changed README.\n{result.stdout}"
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


@pytest.mark.parametrize("path", ["README.md", "docs/API.md", "tests/test_x.py"])
def test_production_always_builds_even_with_nothing_to_diff(repo: Path, path: str):
    """The deploy hook could never refresh the site, and this is the fix.

    A hook fires on a commit that did not change — that is the point of it — so
    every path-diff rule skipped it. Measured 2026-08-29 01:40 UTC: the hook
    returned 201, created deployment dpl_DosS5xPKtYoroMGREr6XyaV4yYPq on
    main@9664535, the gate found no dashboard change, and the deployment went
    straight to CANCELED. The site had never once been refreshed by it.

    Keying on VERCEL_ENV rather than on what triggered the build is what lets
    it through: a hook on the production branch produces a production
    deployment. Publishing a stale site to save 20 minutes is the wrong trade.
    """
    _commit(repo, path, "a commit that touches nothing the site uses\n")
    assert _gate(repo).returncode == SKIP, (
        "precondition: without VERCEL_ENV this is exactly the skip that "
        "cancelled the hook deployment"
    )
    result = _gate(repo, VERCEL_ENV="production")
    assert result.returncode == BUILD, (
        f"production is the published site and must never be skipped.\n{result.stdout}"
    )


def test_previews_stay_path_filtered(repo: Path):
    """Previews are not the published site, so the old economics still hold.

    This is also where the 2026-08-26 damage came from: four CONCURRENT preview
    builds, three for commits that never touched dashboard/, whose scans of
    cvm_fi_perfil blocked the schema apply until the server killed it.
    """
    _commit(repo, "README.md", "docs only\n")
    assert _gate(repo, VERCEL_ENV="preview").returncode == SKIP

    _commit(repo, "dashboard/page.md", "a real change\n")
    assert _gate(repo, VERCEL_ENV="preview").returncode == BUILD


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


def test_every_fi_doc_type_is_dispatchable_and_repairable():
    """A doc type wired into backfill but absent from the dropdown is unreachable.

    `_want_fi_doc` honours any doc type, so a new FI dataset lands correctly on
    the daily run and is picked up by `fi_doc_type: all`. But `all` re-fetches
    inf_diario, perfil_mensal and balancete (24 GB) for every year, so the only
    affordable way to fill one dataset's history is to select it — and a fixed
    `type: choice` list silently makes that impossible. CDA blocks 4 and 2
    shipped that way.

    Two more places hardcode the same list and would raise rather than degrade:
    the coverage gate's `counts` dict (KeyError, outside its try/except) and
    gaps.FI_MONTHLY_TABLES (ValueError from missing_fi_months, which is what
    --repair-gaps runs on). All three are asserted together because a doc type
    present in one and missing from another is still a broken dispatch.
    """
    from src.pipeline.gaps import FI_MONTHLY_TABLES

    pipeline = (ROOT / "src/pipeline/cvm_pipeline.py").read_text()
    wired = set(re.findall(r'_want_fi_doc\("([a-z_]+)"\)', pipeline))
    assert wired, "no FI doc-type filter call sites found — did _want_fi_doc get renamed?"

    wf = yaml.safe_load((ROOT / ".github/workflows/backfill.yml").read_text())
    options = set(wf[True]["workflow_dispatch"]["inputs"]["fi_doc_type"]["options"])

    assert wired <= options, (
        f"{sorted(wired - options)} are ingested by backfill but cannot be selected in "
        "backfill.yml — the only way to fill their history would be a full FI re-ingest"
    )
    assert wired <= set(FI_MONTHLY_TABLES), (
        f"{sorted(wired - set(FI_MONTHLY_TABLES))} are missing from gaps.FI_MONTHLY_TABLES, "
        "so --repair-gaps raises ValueError for a doc type the dropdown offers"
    )


def _gate_decision(doc_type: str, year: int, repair: bool = False, **coverage) -> str:
    """Run backfill.yml's coverage-gate decision block, without a database.

    The block lives inside a heredoc, so nothing else in CI executes it — a
    KeyError there surfaces only when an operator dispatches the workflow and
    the job dies before fetching anything. Lifting it out and exec'ing it is
    the only way to hold its behaviour from an offline test.
    """
    text = (ROOT / ".github/workflows/backfill.yml").read_text()
    start = text.index("          skip = False\n")
    block = textwrap.dedent(text[start:text.index("          if skip:", start)])
    block = (
        block.replace("${{ inputs.fi_doc_type }}", doc_type)
        .replace("${{ inputs.fi_repair_gaps }}", "true" if repair else "false")
        .replace("${{ inputs.fi_months }}", "")
    )
    ns = dict(
        year=year, diario_months=12, perfil_months=12, balancete_months=3,
        cda_months=0, cda_acoes_months=0, cda_cotas_months=0, diario_rows=0,
    )
    ns.update(coverage)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        exec(block, ns)  # noqa: S102 — the point is to run the shipped block
    return out.getvalue().strip()


def test_the_coverage_gate_decides_every_dispatchable_doc_type():
    """`counts[doc]` sits outside the gate's try/except — a miss kills the job.

    Failing closed is the wrong default here: the gate exists to skip work
    already done, so a doc type it does not recognise must run the year rather
    than abort the dispatch.
    """
    wf = yaml.safe_load((ROOT / ".github/workflows/backfill.yml").read_text())
    for doc in wf[True]["workflow_dispatch"]["inputs"]["fi_doc_type"]["options"]:
        if doc == "all":
            continue
        assert _gate_decision(doc, 2024).startswith(("RUN", "SKIP"))

    assert _gate_decision("a_doc_type_added_later", 2024).startswith("RUN")


def test_the_gate_skips_years_the_holdings_blocks_cannot_reach():
    """cvm_pipeline schedules cda_acoes/cda_cotas only from 2023.

    Before that, the FI CDA history comes from the yearly HIST archive, and
    `hist_cda` reads BLC_1 only (src/fetchers/cvm_config.py). So an earlier year
    would spin up a job, download nothing and report success — which reads as
    "2019 holdings are empty upstream" rather than "we never wired it".
    """
    for year in (2019, 2022):
        assert _gate_decision("cda_acoes", year).startswith("SKIP")
    assert _gate_decision("cda_acoes", 2023).startswith("RUN")
    # `cda` itself does have a pre-2023 path, so it must not be caught by this.
    assert _gate_decision("cda", 2019).startswith("RUN")

    # Repair mode too: --repair-gaps on 2019 would report all twelve months as
    # gaps (the table is empty) and then schedule none of them, because the
    # backfill loop gates the block on year >= 2023. The check has to sit ahead
    # of the repair branch, not inside the coverage one.
    assert _gate_decision("cda_acoes", 2019, repair=True).startswith("SKIP")
    assert _gate_decision("cda_acoes", 2024, repair=True).startswith("RUN")
    assert _gate_decision("balancete", 2019, repair=True).startswith("RUN")


def test_b3_backfill_accepts_an_exact_year_range():
    text = (ROOT / ".github/workflows/daily_ingest.yml").read_text()

    assert "end_year:" in text
    assert "--b3-start-year ${{ inputs.start_year }}" in text
    assert "--end-year ${{ inputs.end_year }}" in text
