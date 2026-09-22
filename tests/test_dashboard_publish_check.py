"""The publish check: a build that is not on the public host is not published.

Between 2026-09-18 and 2026-09-22 the dashboard built correctly every night and
published nothing. Four production deployments went READY while both vercel.app
project domains stayed bound to dpl_54vMGARv4w1DAhyx… (6646c0c, PR #275). The
inflation feature shipped into that gap: live on the branch alias, invisible on
the public URL, reported as done on the strength of build-log row counts and a
READY state. CLAUDE.md's rule — row counts in a build log and pixels on the
public URL are different observations — is what these tests enforce.

The script's contract is the ordinary one (0 published, 1 not), unlike
vercel_should_build.sh whose exit codes Vercel inverts. Getting it backwards
here turns the alarm into silence, so it is pinned.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/promote_dashboard.sh"
WORKFLOW = ROOT / ".github/workflows/publish_check.yml"

yaml = pytest.importorskip("yaml")
pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")

PUBLIC = "public.example"
BRANCH = "branch.example"

# A curl standing in for the network. It answers the two manifest URLs and the
# two Vercel endpoints, records every call, and — like the real promote —
# changes what the public host serves only AFTER the promote succeeds.
SHIM = r'''#!/usr/bin/env python3
import os, sys, pathlib
argv = sys.argv[1:]
url = [a for a in argv if a.startswith("http")][-1]
state = pathlib.Path(os.environ["SHIM_STATE"])
log = pathlib.Path(os.environ["SHIM_LOG"])
out = None
if "-o" in argv:
    out = argv[argv.index("-o") + 1]
log.open("a").write(url + "\n")

promoted = (state / "promoted").exists()
branch_manifest = os.environ["BRANCH_MANIFEST"]
public_manifest = branch_manifest if (promoted and os.environ.get("PROMOTE_WORKS") == "1") \
    else os.environ["PUBLIC_MANIFEST"]

body, code = "", "200"
if "/promote/" in url:
    (state / "promoted").touch()
    code = os.environ.get("PROMOTE_CODE", "201")
elif "/v6/deployments" in url:
    body = os.environ.get("DEPLOYMENTS_JSON", '{"deployments":[{"uid":"dpl_NEW"}]}')
elif url.startswith(f"https://{os.environ['PUBLIC_HOST']}/"):
    body = public_manifest
elif url.startswith(f"https://{os.environ['BRANCH_HOST']}/"):
    body = branch_manifest

if out:
    pathlib.Path(out).write_text(body)
    if "-w" in argv:
        sys.stdout.write(code)
else:
    sys.stdout.write(body)
'''


@pytest.fixture
def run(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "curl").write_text(SHIM)
    (bin_dir / "curl").chmod(0o755)
    state = tmp_path / "state"
    state.mkdir()
    log = tmp_path / "calls.log"
    log.touch()

    def _run(*, token=None, public="OLD", branch="NEW", promote_works=True, **extra):
        env = {
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "SHIM_STATE": str(state),
            "SHIM_LOG": str(log),
            "PUBLIC_HOST": PUBLIC,
            "BRANCH_HOST": BRANCH,
            "PUBLIC_MANIFEST": public,
            "BRANCH_MANIFEST": branch,
            "PROMOTE_WORKS": "1" if promote_works else "0",
            "VERIFY_TRIES": "2",
            "VERIFY_DELAY": "0",
            **{k: str(v) for k, v in extra.items()},
        }
        env.pop("VERCEL_TOKEN", None)
        if token:
            env["VERCEL_TOKEN"] = token
        p = subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True)
        return p, log.read_text()

    return _run


def test_no_token_and_already_published_is_success(run):
    """The token only buys the fix. Without one the check still runs, because
    'we could not promote' and 'the site is stale' are different facts."""
    p, calls = run(token=None, public="SAME", branch="SAME")
    assert p.returncode == 0, p.stdout + p.stderr
    assert "VERCEL_TOKEN unset" in p.stdout
    assert "/promote/" not in calls


def test_no_token_and_stale_site_fails_loudly(run):
    p, _ = run(token=None, public="OLD", branch="NEW")
    assert p.returncode == 1
    assert "BEHIND" in p.stdout
    assert "OPEN_ITEMS.md item 8" in p.stdout


def test_a_stale_site_is_promoted_and_then_verified(run):
    """The promote's status code is not the evidence; the public host is."""
    p, calls = run(token="tok", public="OLD", branch="NEW")
    assert p.returncode == 0, p.stdout + p.stderr
    assert "/v10/projects/prj_1zWxdkrKrs12Ss9TMPaepuaYgDpa/promote/dpl_NEW" in calls
    assert "Published" in p.stdout


def test_a_201_that_does_not_move_the_site_still_fails(run):
    """The exact failure this script exists for: the API says yes and the
    public URL disagrees. 2026-09-18 through 2026-09-22 looked like success
    from every angle except the one that mattered."""
    p, _ = run(token="tok", public="OLD", branch="NEW", promote_works=False)
    assert p.returncode == 1
    assert "::error::" in p.stdout
    assert "still does not match" in p.stdout


def test_an_unreadable_deployment_list_does_not_report_success(run):
    p, _ = run(token="tok", public="OLD", branch="NEW", DEPLOYMENTS_JSON='{"deployments":[]}')
    assert p.returncode == 1


def test_an_empty_public_response_is_never_equal(run):
    """Two failed fetches both digest to the hash of nothing. Treating that as
    a match would report a dead site as published."""
    p, _ = run(token=None, public="", branch="")
    assert p.returncode == 1


def test_the_workflow_runs_the_script_and_passes_the_token():
    wf = yaml.safe_load(WORKFLOW.read_text())
    steps = wf["jobs"]["publish-check"]["steps"]
    run_step = next(s for s in steps if "run" in s)
    assert "scripts/promote_dashboard.sh" in run_step["run"]
    assert "VERCEL_TOKEN" in run_step["env"]["VERCEL_TOKEN"]
    # After the 06:00 ingest and its 17-45 min build, never before.
    assert wf[True]["schedule"][0]["cron"] == "0 8 * * *"
