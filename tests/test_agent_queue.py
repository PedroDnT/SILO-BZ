"""Queue selection and trusted publication guards, without network/model calls."""

import importlib.util
import json
from pathlib import Path
import subprocess

import pytest

from scripts import agent_queue

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("codex_runner", ROOT / ".github/codex/runner.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def issue(number=1, **changes):
    return {"number": number, "title": "Add an API endpoint", "created_at": "2026-01-01T00:00:00Z",
            "state": "open", "body": "Implement src/store/analytical/99_api_test.sql",
            "labels": [{"name": "ready-for-agent"}], "assignees": [], **changes}


@pytest.mark.parametrize("label", sorted(agent_queue.BLOCKING_LABELS))
def test_conflicting_labels_are_never_selected(label):
    row = issue(labels=[{"name": "ready-for-agent"}, {"name": label}])
    assert agent_queue.skip_reason(row)


@pytest.mark.parametrize("changes,options", [
    ({"labels": []}, {}), ({"assignees": [{"login": "PedroDnT"}]}, {}),
    ({"body": "no paths"}, {}), ({}, {"blocked": True}), ({}, {"linked_pr": True}),
    ({}, {"changed": ["src/store/analytical/99_api_test.sql"]}),
    ({"title": "Refactor code", "body": "src/fetchers/cvm_config.py"}, {"builder": True}),
])
def test_queue_skips_ineligible_issues(changes, options):
    assert agent_queue.skip_reason(issue(**changes), **options)


def test_queue_selects_oldest_and_checks_blockers_and_linked_prs(monkeypatch):
    rows = [issue(4, created_at="2026-02-01"), issue(3), issue(2), issue(1)]
    def fake_pages(repo, endpoint):
        if endpoint.startswith("issues?"):
            return rows
        if endpoint == "issues/1/dependencies/blocked_by":
            return [{"number": 9, "state": "open"}]
        if endpoint == "issues/2/timeline":
            return [{"source": {"issue": {"state": "open", "pull_request": {"url": "pr"}}}}]
        return []
    monkeypatch.setattr(agent_queue, "pages", fake_pages)
    result = agent_queue.queue("owner/repo", builder=True)
    assert [i["number"] for i in result["eligible"]] == [3, 4]
    assert [i["number"] for i in result["skipped"]] == [1, 2]
    assert result["skipped"][0]["reason"] == "blocked by an open issue #9"


@pytest.mark.parametrize("body,states,eligible", [
    ("Blocked by: #7", {7: "open"}, False),
    ("Blocked by: #7", {7: "closed"}, True),
    ("Part of #7", {7: "open"}, True),
    ("**Blocked by:** #7 (docs) and the deploy (#8).", {7: "closed", 8: "open"}, False),
])
def test_body_blocked_by_line_blocks_while_a_named_issue_is_open(monkeypatch, body, states, eligible):
    rows = [issue(1, body=body + "\nImplement src/store/analytical/99_api_test.sql")]
    fetched = []
    def fake_gh(repo, endpoint, method="GET", data=None):
        fetched.append(endpoint)
        return {"number": int(endpoint.rsplit("/", 1)[1]),
                "state": states[int(endpoint.rsplit("/", 1)[1])]}
    monkeypatch.setattr(agent_queue, "pages", lambda repo, endpoint:
                        rows if endpoint.startswith("issues?") else [])
    monkeypatch.setattr(agent_queue, "gh", fake_gh)
    result = agent_queue.queue("o/r")
    assert bool(result["eligible"]) is eligible
    if not eligible:
        assert result["skipped"] == [{"number": 1, "reason": "blocked by an open issue #"
                                      + str(max(n for n, s in states.items() if s == "open"))}]
    # Only the `Blocked by:` line is fetched; `Part of #n` never is.
    assert fetched == ([f"issues/{n}" for n in sorted(states)] if "Blocked by" in body else [])


def test_directory_and_glob_overlap():
    assert agent_queue.overlaps(["src/fetchers/"], ["src/fetchers/cvm_config.py"])
    assert agent_queue.overlaps(["src/parsers/field_maps/*.py"], ["src/parsers/field_maps/fi.py"])
    assert not agent_queue.overlaps(["src/fetchers/cvm_config.py"], ["tests/test_fetcher.py"])


def test_root_files_count_as_paths_but_domains_do_not(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "README.md").write_text("readme\n")
    assert agent_queue.issue_paths(issue(body="Edit README.md; see example.com")) == ["README.md"]


def test_priority_precedes_age_and_conflicting_priorities_are_skipped(monkeypatch):
    rows = [issue(1), issue(2, created_at="2026-03-01", labels=[{"name": "ready-for-agent"},
                                                                  {"name": "P0-critical"}])]
    monkeypatch.setattr(agent_queue, "pages", lambda repo, endpoint:
                        rows if endpoint.startswith("issues?") else [])
    assert [i["number"] for i in agent_queue.queue("o/r")["eligible"]] == [2, 1]
    assert agent_queue.skip_reason(issue(labels=[{"name": "ready-for-agent"},
                                               {"name": "P0-critical"}, {"name": "P1-next"}]))


@pytest.mark.parametrize("pulls", [
    [{"labels": [{"name": "agent:builder"}]}],
    [{"labels": [{"name": "agent:scout"}]}] * 3,
])
def test_builder_respects_review_and_global_pr_budgets(monkeypatch, pulls):
    monkeypatch.setattr(agent_queue, "pages", lambda repo, endpoint: pulls)
    assert not agent_queue.queue("o/r", builder=True)["eligible"]


def test_github_pagination_does_not_drop_the_second_page(monkeypatch):
    monkeypatch.setattr(agent_queue, "gh", lambda repo, endpoint:
                        list(range(100)) if endpoint.endswith("&page=1") else [100])
    assert len(agent_queue.pages("o/r", "issues?state=open")) == 101


@pytest.mark.parametrize("body,kind,pull,expected", [
    ("@codex explain this", "User", False, True),
    ("ordinary answer", "User", False, False),
    ("@codex explain this", "Bot", False, False),
    ("@codex review", "User", True, False),
    ("test@codex-more", "User", False, False),
    ("ping @codex-more", "User", False, False),
])
def test_only_issue_mentions_by_humans_trigger(body, kind, pull, expected):
    event = {"issue": {"number": 1}, "comment": {"body": body, "user": {"type": kind}}}
    if pull:
        event["issue"]["pull_request"] = {}
    assert runner.trigger("issue_comment", event) is expected


def test_permission_is_checked_live(monkeypatch):
    monkeypatch.setattr(runner, "gh", lambda *args: {"permission": "read"})
    assert not runner.trusted("o/r", "someone")
    monkeypatch.setattr(runner, "gh", lambda *args: {"permission": "write"})
    assert runner.trusted("o/r", "someone")


def test_dry_run_never_assigns_or_invokes_model(tmp_path, monkeypatch):
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"inputs": {"dry_run": "true"}}))
    for key, value in {"GITHUB_REPOSITORY": "o/r", "GITHUB_EVENT_NAME": "workflow_dispatch",
                       "GITHUB_EVENT_PATH": str(event), "GITHUB_ACTOR": "owner",
                       "GITHUB_OUTPUT": str(tmp_path / "outputs"),
                       "GITHUB_STEP_SUMMARY": str(tmp_path / "summary")}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(runner, "trusted", lambda *args: True)
    monkeypatch.setattr(runner, "queue", lambda *args, **kwargs: {"eligible": [issue()], "skipped": []})
    def fake_gh(repo, endpoint, method="GET", data=None):
        assert endpoint == "labels/agent:builder" and method == "GET"
        return {"name": "agent:builder"}
    monkeypatch.setattr(runner, "gh", fake_gh)
    runner.prepare()
    assert "run=false" in (tmp_path / "outputs").read_text()
    assert not (tmp_path / "prompt.md").exists()


def test_competing_claim_blocks_publication(monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY_OWNER", "PedroDnT")
    monkeypatch.setattr(runner, "gh", lambda *args: issue(assignees=[{"login": "PedroDnT"}]))
    monkeypatch.setattr(runner, "pages", lambda *args: [
        {"body": "Claimed by: codex · branch codex/ours"},
        {"body": "Claimed by: claude · branch claude/theirs"}])
    assert not runner.owns("o/r", 1, "codex/ours")


@pytest.mark.parametrize("status,path,mode", [
    ("M", ".github/workflows/test.yml", "100644"),
    ("M", "tests/test_existing.py", "100644"),
    ("D", "src/important.py", "100644"),
    ("A", ".env.local", "100644"),
    ("A", "src/link.py", "120000"),
    ("A", "src/submodule", "160000"),
])
def test_publisher_rejects_protected_paths_deletions_links_and_existing_tests(monkeypatch, status, path, mode):
    def fake_run(*args):
        if "--name-status" in args:
            return f"{status}\0{path}\0"
        if "--raw" in args:
            return f":000000 {mode} 000000 abcdef A\t{path}\n"
        return ""
    monkeypatch.setattr(runner, "run", fake_run)
    with pytest.raises(RuntimeError):
        runner.validate_patch()


def test_publisher_accepts_additive_test_and_implementation(monkeypatch):
    monkeypatch.setattr(runner, "run", lambda *args:
                        "A\0tests/test_new.py\0M\0src/new.py\0" if "--name-status" in args else "")
    runner.validate_patch()


def test_publisher_rejects_secret_pattern_without_printing_it(monkeypatch):
    monkeypatch.setattr(runner, "run", lambda *args:
                        "M\0src/new.py\0" if "--name-status" in args else
                        "" if "--raw" in args else "+postgres://user:" + "fake-password" + "@example/db")
    with pytest.raises(RuntimeError, match="credential pattern"):
        runner.validate_patch()


def test_real_git_patch_validation(tmp_path, monkeypatch):
    def git(*args):
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)
    git("init")
    git("-c", "user.name=test", "-c", "user.email=test@example.com", "commit", "--allow-empty", "-m", "base")
    (tmp_path / "src").mkdir()
    (tmp_path / "src/new.py").write_text("VALUE = 1\n")
    git("add", "src/new.py")
    monkeypatch.chdir(tmp_path)
    runner.validate_patch()


def test_model_job_has_no_github_write_token_or_publication_rights():
    yaml = pytest.importorskip("yaml")
    workflow = yaml.safe_load((ROOT / ".github/workflows/codex.yml").read_text())
    model = workflow["jobs"]["model"]
    assert model["permissions"] == {"contents": "read"}
    assert "GH_TOKEN" not in json.dumps(model)
    checkout = model["steps"][0]
    assert checkout["with"]["persist-credentials"] is False
    assert "CODEX_BUILDER_ENABLED == 'true'" in workflow["jobs"]["prepare"]["if"]
    assert workflow["concurrency"]["cancel-in-progress"] is False
    assert "actions/workflows/test.yml/dispatches" in (ROOT / ".github/codex/runner.py").read_text()


def test_prepare_assigns_before_claim_comment(tmp_path, monkeypatch):
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"inputs": {"dry_run": "false"}}))
    template = tmp_path / ".github/codex"
    template.mkdir(parents=True)
    (template / "builder.md").write_text("trusted prompt")
    for key, value in {"GITHUB_REPOSITORY": "o/r", "GITHUB_REPOSITORY_OWNER": "owner",
                       "GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_EVENT_PATH": str(event),
                       "GITHUB_ACTOR": "owner", "GITHUB_RUN_ID": "123",
                       "GITHUB_OUTPUT": str(tmp_path / "outputs"),
                       "GITHUB_STEP_SUMMARY": str(tmp_path / "summary")}.items():
        monkeypatch.setenv(key, value)
    calls = []
    def fake_gh(repo, endpoint, method="GET", data=None):
        calls.append((endpoint, method, data))
        return issue() if endpoint == "issues/1" else {}
    monkeypatch.setattr(runner, "trusted", lambda *args: True)
    monkeypatch.setattr(runner, "queue", lambda *args, **kwargs: {"eligible": [issue()], "skipped": []})
    monkeypatch.setattr(runner, "owns", lambda *args: True)
    monkeypatch.setattr(runner, "gh", fake_gh)
    monkeypatch.setattr(runner, "pages", lambda *args: [])
    monkeypatch.setattr(runner, "run", lambda *args: "base-sha\n")
    monkeypatch.chdir(tmp_path)
    runner.prepare()
    writes = [(endpoint, data) for endpoint, method, data in calls if method == "POST"]
    assert writes == [("issues/1/assignees", {"assignees": ["owner"]}),
                      ("issues/1/comments", {"body": "Claimed by: codex · branch codex/builder-1-123"})]
    assert "run=true" in (tmp_path / "outputs").read_text()
    assert json.loads((tmp_path / "context.json").read_text())["branch"] == "codex/builder-1-123"


def test_real_patch_is_published_only_as_a_draft_and_ci_is_dispatched(tmp_path, monkeypatch):
    source, publisher = tmp_path / "source", tmp_path / "publisher"
    source.mkdir()
    def git(directory, *args):
        return subprocess.run(["git", *args], cwd=directory, check=True,
                              text=True, capture_output=True).stdout
    git(source, "init")
    # Include the prompt to verify its exact commit is recorded in provenance.
    prompt = source / ".github/codex/builder.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_text("trusted builder prompt\n")
    git(source, "add", ".github/codex/builder.md")
    git(source, "-c", "user.name=test", "-c", "user.email=test@example.com", "commit", "-m", "base")
    base = git(source, "rev-parse", "HEAD").strip()
    git(tmp_path, "clone", str(source), str(publisher))
    for name, text in {"src/store/analytical/99_api_test.sql": "SELECT 1;\n",
                       "docs/planning/changelog.d/test.md": "test change\n"}.items():
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    git(source, "add", "src/store/analytical/99_api_test.sql", "docs/planning/changelog.d/test.md")
    patch = git(source, "diff", "--cached", "--binary")
    result = publisher / "result"
    result.mkdir()
    (result / "response.md").write_text("Tests passed in the model job.\n")
    (result / "changes.patch").write_text(patch)
    for key, value in {"GITHUB_REPOSITORY": "o/r", "ISSUE_NUMBER": "1", "MODE": "builder",
                       "BRANCH": "codex/builder-1-123", "MODEL_RESULT": "success",
                       "DEFAULT_BRANCH": "main", "BASE_SHA": base, "GITHUB_RUN_ID": "123"}.items():
        monkeypatch.setenv(key, value)
    writes, pushes = [], []
    def fake_gh(repo, endpoint, method="GET", data=None):
        if method == "POST":
            writes.append((endpoint, data))
        if endpoint == "pulls":
            return {"number": 42, "html_url": "https://example.com/pr/42"}
        return issue()
    real_run = runner.run
    def fake_run(*args):
        if "push" in args:
            pushes.append(args)
            return ""
        return real_run(*args)
    monkeypatch.setattr(runner, "run", fake_run)
    monkeypatch.setattr(runner, "gh", fake_gh)
    monkeypatch.setattr(runner, "owns", lambda *args: True)
    monkeypatch.setattr(runner, "pages", lambda *args: [])
    monkeypatch.chdir(publisher)
    runner.publish()
    assert len(pushes) == 1
    pr = next(data for endpoint, data in writes if endpoint == "pulls")
    assert pr["draft"] is True and pr["head"] == "codex/builder-1-123"
    assert base in pr["body"] and "actions/runs/123" in pr["body"]
    assert ("issues/42/labels", {"labels": ["agent:builder"]}) in writes
    assert ("actions/workflows/test.yml/dispatches", {"ref": "codex/builder-1-123"}) in writes
    assert (publisher / "src/store/analytical/99_api_test.sql").read_text() == "SELECT 1;\n"


def test_model_failure_releases_its_claim(tmp_path, monkeypatch):
    for key, value in {"GITHUB_REPOSITORY": "o/r", "ISSUE_NUMBER": "1", "MODE": "builder",
                       "BRANCH": "codex/builder-1-123", "MODEL_RESULT": "failure"}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(runner, "owns", lambda *args: True)
    monkeypatch.setattr(runner, "gh", lambda *args: issue())
    released = []
    monkeypatch.setattr(runner, "release", lambda *args: released.append(args))
    runner.publish()
    assert released == [("o/r", 1, "codex/builder-1-123", "model execution failed")]
