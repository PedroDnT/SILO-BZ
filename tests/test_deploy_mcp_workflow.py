"""Pins deploy_mcp.yml, the workflow that redeploys the live remote MCP.

It deploys to production, so the rules that keep it safe are asserted here
rather than trusted to review:

* manual dispatch only — an MCP tool calls an api.* function that is live only
  after the analytical layer is applied, so a deploy on every merge would
  publish tools whose SQL is not there yet;
* functions only — never ``supabase config push`` / ``db push``, which would
  overwrite the production project's settings with the CLI's defaults
  (supabase/config.toml says why);
* ``--no-verify-jwt`` and the right project, matching config.toml and CLAUDE.md;
* the token comes from a secret, never from the file;
* the deploy is proven by asking the live endpoint for its tool list.
"""
from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/deploy_mcp.yml"
PROJECT_REF = "zcjbtpxuhdekpwcxmepn"


def _spec() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _runs() -> str:
    steps = _spec()["jobs"]["deploy"]["steps"]
    return "\n".join(s.get("run", "") for s in steps)


def test_dispatch_only():
    triggers = _spec().get(True) or _spec().get("on")  # PyYAML reads `on:` as True
    assert set(triggers) == {"workflow_dispatch"}, (
        "deploy_mcp.yml must stay manual: tools go live before their SQL otherwise"
    )


def test_deploys_the_function_only_never_pushes_config():
    text = WORKFLOW.read_text(encoding="utf-8")
    runs = _runs()
    assert f"supabase functions deploy silo-mcp --project-ref \"$PROJECT_REF\" --no-verify-jwt" in runs
    assert _spec()["jobs"]["deploy"]["env"]["PROJECT_REF"] == PROJECT_REF
    for forbidden in ("config push", "db push", "db reset"):
        assert f"supabase {forbidden}" not in runs, f"`supabase {forbidden}` must never run here"
    assert "SUPABASE_ACCESS_TOKEN: ${{ secrets.SUPABASE_ACCESS_TOKEN }}" in text


def test_the_live_endpoint_is_checked_after_the_deploy():
    names = [s.get("name", "") for s in _spec()["jobs"]["deploy"]["steps"]]
    deploy = names.index("Deploy silo-mcp")
    smoke = next(i for i, n in enumerate(names) if n.startswith("Live tools/list"))
    assert smoke > deploy
    runs = _runs()
    assert "tools/list" in runs and "tools.ts" in runs
