"""Exercise the real hook/CI detector against isolated Git indexes and commits."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
GUARD = ROOT / "scripts/check_secrets.py"
ENV = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
PASSWORD = "synthetic-private-password-829"


def git(repo, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid",
                           "-c", "commit.gpgsign=false", *args], cwd=repo,
                          env=ENV, capture_output=True, check=True).stdout


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-q")
    git(tmp_path, "-c", "core.hooksPath=/dev/null", "commit", "--allow-empty", "-qm", "base")
    return tmp_path


def stage(repo, name, text):
    p = repo / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    git(repo, "add", "-f", "--", name)


def run(repo, *args):
    index = git(repo, "ls-files", "--stage", "-z")
    status = git(repo, "status", "--porcelain", "-z")
    result = subprocess.run([sys.executable, str(GUARD), *args], cwd=repo,
                            env=ENV, capture_output=True, text=True)
    assert git(repo, "ls-files", "--stage", "-z") == index
    assert git(repo, "status", "--porcelain", "-z") == status
    assert PASSWORD not in result.stdout + result.stderr
    return result


@pytest.mark.parametrize("name", [".env", ".env.local", "nested/.env.production", "nested/.env.secrets"])
def test_force_added_private_dotenv_is_rejected(repo, name):
    stage(repo, name, "")
    result = run(repo, "--staged")
    assert result.returncode == 1 and "private-dotenv" in result.stdout


@pytest.mark.parametrize("name", [".env.example", "nested/.env.template"])
def test_only_documented_templates_are_allowed(repo, name):
    stage(repo, name, "POSTGRES_URL=\n")
    assert run(repo, "--staged").returncode == 0


@pytest.mark.parametrize("scheme", ["postgres", "postgresql", "POSTGRESQL"])
@pytest.mark.parametrize("password", [PASSWORD, "synthetic%2Dprivate%2Dpassword%2D829"])
def test_both_url_schemes_and_encoded_passwords_are_rejected_without_echo(repo, scheme, password):
    stage(repo, "package-lock.json", f'{scheme}://user:{password}@example.invalid/db\n')
    result = run(repo, "--staged")
    assert result.returncode == 1 and "embedded-db-credentials" in result.stdout
    assert password not in result.stdout + result.stderr


def test_hook_files_are_not_exempt_and_working_tree_cannot_hide_a_staged_secret(repo):
    scheme = "postgres"
    stage(repo, ".githooks/hidden", f'{scheme}://user:{PASSWORD}@example.invalid/db\n')
    (repo / ".githooks/hidden").write_text("now harmless\n")
    assert run(repo, "--staged").returncode == 1


def test_clean_staged_blob_is_not_rejected_for_unstaged_content(repo):
    stage(repo, "a.txt", "safe\n")
    scheme = "postgresql"
    (repo / "a.txt").write_text(f'{scheme}://user:{PASSWORD}@example.invalid/db\n')
    assert run(repo, "--staged").returncode == 0


def test_ci_detects_committed_secret_after_bypassing_hook(repo):
    base = git(repo, "rev-parse", "HEAD").decode().strip()
    scheme = "postgresql"
    stage(repo, "a.txt", f'{scheme}://user:{PASSWORD}@example.invalid/db\n')
    git(repo, "-c", "core.hooksPath=/dev/null", "commit", "-qm", "bypass")
    assert run(repo, "--staged").returncode == 0
    assert run(repo, "--base", base, "--head", "HEAD").returncode == 1


def test_ci_ignores_unchanged_base_credentials(repo):
    scheme = "postgres"
    stage(repo, "legacy.txt", f'{scheme}://user:{PASSWORD}@example.invalid/db\n')
    git(repo, "-c", "core.hooksPath=/dev/null", "commit", "-qm", "historical fixture")
    base = git(repo, "rev-parse", "HEAD").decode().strip()
    stage(repo, "new.txt", "harmless\n")
    git(repo, "-c", "core.hooksPath=/dev/null", "commit", "-qm", "safe")
    assert run(repo, "--base", base).returncode == 0


def test_invalid_ref_git_error_does_not_echo_caller_data(repo):
    result = run(repo, "--base", PASSWORD)
    assert result.returncode == 2 and "input unavailable" in result.stdout


def test_documentation_placeholder_is_allowed_but_template_secret_is_not(repo):
    scheme = "postgresql"
    stage(repo, ".env.example", f'{scheme}://user:<password>@example.invalid/db\n')
    assert run(repo, "--staged").returncode == 0
    stage(repo, ".env.example", f'{scheme}://user:{PASSWORD}@example.invalid/db\n')
    assert run(repo, "--staged").returncode == 1


def test_real_hook_rejects_commit_without_echoing_matching_source(repo):
    (repo / "scripts").mkdir()
    shutil.copy(GUARD, repo / "scripts/check_secrets.py")
    hook = repo / ".git/hooks/pre-commit"
    shutil.copy(ROOT / ".githooks/pre-commit", hook)
    hook.chmod(0o755)
    scheme = "postgres"
    stage(repo, "a.txt", f'{scheme}://user:{PASSWORD}@example.invalid/db\n')
    before = git(repo, "rev-parse", "HEAD")
    result = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid",
                             "commit", "-m", "reject"], cwd=repo, env=ENV, capture_output=True, text=True)
    assert result.returncode != 0
    assert PASSWORD not in result.stdout + result.stderr
    assert git(repo, "rev-parse", "HEAD") == before


def test_ignore_rules_cover_nested_variants_and_keep_examples(repo):
    shutil.copy(ROOT / ".gitignore", repo / ".gitignore")
    stage(repo, "nested/.env.example", "")
    for name in [".env.local", "nested/.env.production"]:
        assert git(repo, "check-ignore", name).strip().decode() == name
    result = subprocess.run(["git", "check-ignore", "--no-index", "nested/.env.example"], cwd=repo, env=ENV)
    assert result.returncode == 1


def test_pr_ci_calls_the_same_guard_on_the_pr_range():
    workflow = yaml.safe_load((ROOT / ".github/workflows/test.yml").read_text())
    step = next(s for s in workflow["jobs"]["pytest"]["steps"] if s.get("name") == "Reject secrets in PR additions")
    assert step["if"] == "github.event_name == 'pull_request'"
    assert '--base "refs/remotes/origin/$BASE_REF"' in step["run"]
    assert '--head "$HEAD_SHA"' in step["run"]
    assert "scripts/check_secrets.py" in step["run"]
