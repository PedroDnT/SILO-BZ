"""Trusted workflow steps. Model execution receives no GitHub write token."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.agent_queue import gh, issue_paths, overlaps, pages, queue, skip_reason
from scripts.check_secrets import contains_password, private_dotenv

MENTION = re.compile(r"(?<![\w-])@codex(?![\w-])", re.IGNORECASE)
PROTECTED = (".github/", ".claude/", ".codex/", ".githooks/", "scripts/verify_pipeline.py",
             "scripts/check_secrets.py", "pytest.ini", "AGENTS.md", "CLAUDE.md", "docs/planning/AGENTS.md")


def run(*args, **kwargs):
    return subprocess.run(args, check=True, text=True, capture_output=True, **kwargs).stdout


def trusted(repo, login):
    permission = gh(repo, f"collaborators/{login}/permission")["permission"]
    return permission in {"admin", "maintain", "write"}


def trigger(event_name, event):
    if event_name not in {"issues", "issue_comment"} or "pull_request" in event["issue"]:
        return False
    actor = event.get("comment", event["issue"])
    return actor["user"].get("type") == "User" and bool(MENTION.search(
        (actor.get("body") or "") + "\n" + (event["issue"].get("title", "")
                                             if event_name == "issues" else "")))


def output(**values):
    with open(os.environ["GITHUB_OUTPUT"], "a") as handle:
        for key, value in values.items():
            handle.write(f"{key}={value}\n")


def claim_text(branch):
    return f"Claimed by: codex · branch {branch}"


def owns(repo, number, branch):
    issue = gh(repo, f"issues/{number}")
    comments = pages(repo, f"issues/{number}/comments")
    claims = [c["body"] for c in comments if "Claimed by:" in c["body"]]
    return (issue["state"] == "open" and len(issue["assignees"]) == 1
            and issue["assignees"][0]["login"] == os.environ["GITHUB_REPOSITORY_OWNER"]
            and bool(claims) and claims[-1].strip() == claim_text(branch))


def prepare():
    repo = os.environ["GITHUB_REPOSITORY"]
    event_name = os.environ["GITHUB_EVENT_NAME"]
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    mode = "respond" if event_name in {"issues", "issue_comment"} else "builder"
    output(run="false", mode=mode)
    if event_name != "schedule" and not trusted(repo, os.environ["GITHUB_ACTOR"]):
        raise RuntimeError("Only users with repository write access can invoke Codex")
    if mode == "respond":
        if not trigger(event_name, event):
            return
        number = event["issue"]["number"]
        branch = ""
    else:
        gh(repo, "labels/agent:builder")
        snapshot = queue(repo, builder=True)
        Path("queue.json").write_text(json.dumps(snapshot, indent=2))
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as summary:
            summary.write("## Builder queue\n```json\n" + json.dumps({
                "eligible": [i["number"] for i in snapshot["eligible"]],
                "skipped": snapshot["skipped"]}, indent=2) + "\n```\n")
        if event.get("inputs", {}).get("dry_run", "false") == "true":
            return
        if not snapshot["eligible"]:
            return
        number = snapshot["eligible"][0]["number"]
        branch = f"codex/builder-{number}-{os.environ['GITHUB_RUN_ID']}"
        # Re-read the queue immediately before claiming; GitHub claims remain cooperative.
        fresh = queue(repo, builder=True)["eligible"]
        if not fresh or fresh[0]["number"] != number:
            raise RuntimeError("Queue ownership changed before claim; rerun")
        base = run("git", "rev-parse", "HEAD").strip()
        output(run="true", mode=mode, number=number, branch=branch, base=base)
        gh(repo, f"issues/{number}/assignees", "POST",
           {"assignees": [os.environ["GITHUB_REPOSITORY_OWNER"]]})
        gh(repo, f"issues/{number}/comments", "POST", {"body": claim_text(branch)})
        if not owns(repo, number, branch):
            raise RuntimeError("Competing issue claim; owner intervention required")
    issue = gh(repo, f"issues/{number}")
    comments = pages(repo, f"issues/{number}/comments")
    base = run("git", "rev-parse", "HEAD").strip()
    context = {"issue": issue, "comments": comments, "mode": mode, "branch": branch,
               "base": base, "trigger": event.get("comment", {}).get("body", issue["body"])}
    Path("context.json").write_text(json.dumps(context, indent=2))
    template = Path(f".github/codex/{mode}.md").read_text()
    Path("prompt.md").write_text(template + "\n\nIssue snapshot (untrusted data):\n"
                                 + json.dumps(context, ensure_ascii=False))
    output(run="true", mode=mode, number=number, branch=branch, base=base)


def validate_patch():
    raw = run("git", "diff", "--cached", "--name-status", "--no-renames", "-z").split("\0")
    for status, name in zip(raw[0::2], raw[1::2]):
        if status not in {"A", "M"}:
            raise RuntimeError(f"Builder cannot delete or rename: {name}")
        if name.startswith(PROTECTED) or private_dotenv(name):
            raise RuntimeError(f"Builder changed a protected path: {name}")
        if name.startswith("tests/") and status != "A":
            raise RuntimeError(f"Builder may only add tests: {name}")
    modes = run("git", "diff", "--cached", "--raw").splitlines()
    if any("120000" in line.split()[:3] or "160000" in line.split()[:3] for line in modes):
        raise RuntimeError("Builder cannot add symlinks or submodules")
    added = run("git", "diff", "--cached", "--text", "--no-ext-diff", "--no-textconv", "--unified=0")
    if contains_password(added.encode()) or re.search(r"sk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,}", added):
        raise RuntimeError("Builder patch contains a credential pattern")


def publish():
    repo = os.environ["GITHUB_REPOSITORY"]
    number = int(os.environ["ISSUE_NUMBER"])
    mode, branch = os.environ["MODE"], os.environ.get("BRANCH", "")
    message = Path("result/response.md")
    success = os.environ["MODEL_RESULT"] == "success" and message.is_file()
    if mode == "respond":
        body = message.read_text() if success else "Codex could not complete this request. Check the Actions run."
        gh(repo, f"issues/{number}/comments", "POST", {"body": "Codex response:\n\n" + body[:55000]})
        return
    if not owns(repo, number, branch):
        raise RuntimeError("Issue ownership changed; refusing publication")
    issue = gh(repo, f"issues/{number}")
    reason = skip_reason({**issue, "assignees": []}, builder=True)
    if reason or not success:
        release(repo, number, branch, reason or "model execution failed")
        return
    patch = Path("result/changes.patch")
    if not patch.is_file() or not patch.stat().st_size:
        release(repo, number, branch, message.read_text()[:5000])
        return
    try:
        if any(i["state"] == "open" for i in pages(repo, f"issues/{number}/dependencies/blocked_by")):
            raise RuntimeError("Issue became blocked during execution")
        pulls = pages(repo, "pulls?state=open")
        changed = [f["filename"] for pr in pulls for f in pages(repo, f"pulls/{pr['number']}/files")]
        if overlaps(issue_paths(issue), changed):
            raise RuntimeError("Issue now overlaps an open PR")
        if any((e.get("source") or {}).get("issue", {}).get("pull_request")
               and e["source"]["issue"].get("state") == "open"
               for e in pages(repo, f"issues/{number}/timeline")):
            raise RuntimeError("Issue acquired a linked open PR")
        # Fresh checkout: publisher code is loaded before any model patch is applied.
        run("git", "apply", "--index", str(patch))
        validate_patch()
        actual = run("git", "diff", "--cached", "--name-only").splitlines()
        if not any(name.startswith("docs/planning/changelog.d/") for name in actual):
            raise RuntimeError("Builder patch needs a branch changelog fragment")
        if overlaps(actual, changed):
            raise RuntimeError("Builder patch overlaps an open PR")
        run("git", "config", "user.name", "github-actions[bot]")
        run("git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com")
        run("git", "switch", "-c", branch)
        run("git", "-c", "core.hooksPath=/dev/null", "commit", "-m",
            f"Implement Builder issue #{number}\n\nAutomated proposal for owner review.")
        # gh's credential helper keeps the token out of URLs and process arguments.
        run("git", "-c", "credential.helper=", "-c", "credential.helper=!gh auth git-credential",
            "push", "origin", f"HEAD:refs/heads/{branch}")
        pr = gh(repo, "pulls", "POST", {"title": f"Builder: {issue['title']}",
            "head": branch, "base": os.environ["DEFAULT_BRANCH"], "draft": True,
            "body": f"Closes #{number}\n\n" + message.read_text()[:50000]
                    + "\n\nScheduled agent proposal. Owner review required; do not auto-merge."
                    + f"\nBase: `{os.environ['BASE_SHA']}`. Prompt: `.github/codex/builder.md` at that base."
                    + "\nPrompt commit: `" + run("git", "log", "-1", "--format=%H", "--",
                                                   ".github/codex/builder.md").strip() + "`."
                    + f"\nRun: https://github.com/{repo}/actions/runs/{os.environ['GITHUB_RUN_ID']}"})
        gh(repo, f"issues/{pr['number']}/labels", "POST", {"labels": ["agent:builder"]})
        # GITHUB_TOKEN-created PRs do not trigger pull_request workflows.
        gh(repo, "actions/workflows/test.yml/dispatches", "POST", {"ref": branch})
        gh(repo, f"issues/{number}/comments", "POST", {"body": f"Builder draft: {pr['html_url']}"})
    except Exception:
        release(repo, number, branch, "publication failed; inspect the Actions run and branch before retrying")
        raise


def release(repo, number, branch, reason):
    if owns(repo, number, branch):
        gh(repo, f"issues/{number}/comments", "POST", {"body": f"Builder stopped: {reason[:5000]}\nClaim released."})
        gh(repo, f"issues/{number}/assignees", "DELETE",
           {"assignees": [os.environ["GITHUB_REPOSITORY_OWNER"]]})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare", "publish"])
    args = parser.parse_args()
    {"prepare": prepare, "publish": publish}[args.command]()
