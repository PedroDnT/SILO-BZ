"""Read the cooperative issue queue; never apply triage or priority labels."""

from __future__ import annotations

import argparse
import fnmatch
import json
from pathlib import Path
import re
import subprocess

BLOCKING_LABELS = {"needs-triage", "needs-info", "ready-for-human", "wontfix", "epic", "P3-parked"}
PRIORITY = {"P0-critical": 0, "P1-next": 1, "P2-later": 2}
PATH = re.compile(r"(?<![\w/])(?:[\w.-]+/)+[\w.*-]+(?:\.[\w*-]+)?")


def gh(repo, endpoint, method="GET", data=None):
    args = ["gh", "api", f"repos/{repo}/{endpoint}", "-X", method]
    if data is not None:
        args += ["--input", "-"]
    result = subprocess.run(args, input=json.dumps(data) if data is not None else None,
                            text=True, capture_output=True, check=True)
    return json.loads(result.stdout) if result.stdout.strip() else None


def pages(repo, endpoint):
    result = []
    for page in range(1, 1001):
        separator = "&" if "?" in endpoint else "?"
        batch = gh(repo, f"{endpoint}{separator}per_page=100&page={page}")
        result.extend(batch)
        if len(batch) < 100:
            return result
    raise RuntimeError("GitHub pagination exceeded 1000 pages")


def issue_paths(issue):
    body = issue.get("body") or ""
    paths = {match.rstrip(".") for match in PATH.findall(body)}
    # Root files have no slash; accept existing ones without mistaking domains for paths.
    paths.update(name for name in (match.rstrip(".") for match in
                                  re.findall(r"(?<![\w/])[\w-]+\.[\w.-]+", body))
                 if Path(name).is_file())
    return sorted(paths)


def overlaps(planned, changed):
    return any(fnmatch.fnmatchcase(other, path) or other.startswith(path.rstrip("/") + "/")
               or path.startswith(other.rstrip("/") + "/")
               for path in planned for other in changed)


def skip_reason(issue, *, blocked=False, linked_pr=False, changed=(), builder=False):
    labels = {label["name"] for label in issue.get("labels", [])}
    if "ready-for-agent" not in labels:
        return "not ready-for-agent"
    if labels & BLOCKING_LABELS:
        return "conflicting triage label or epic"
    if len(labels & PRIORITY.keys()) > 1:
        return "multiple priority labels"
    if issue.get("assignees"):
        return "assigned"
    if blocked:
        return "blocked by an open issue"
    if linked_pr:
        return "already referenced by an open PR"
    paths = issue_paths(issue)
    if not paths:
        return "no repository paths in issue body"
    if overlaps(paths, changed):
        return "files overlap an open PR"
    if builder:
        text = issue.get("title", "") + "\n" + (issue.get("body") or "")
        if not re.search(r"\b(dataset|endpoint)\b", text, re.IGNORECASE) or not any(
                p.startswith(("src/fetchers/", "src/parsers/field_maps/", "src/store/analytical/"))
                for p in paths):
            return "outside Builder dataset/API scope"
    return None


def queue(repo, *, builder=False):
    pulls = pages(repo, "pulls?state=open")
    if builder:
        agent_prs = [pr for pr in pulls if any(label["name"].startswith("agent:")
                                             for label in pr.get("labels", []))]
        if len(agent_prs) >= 3 or any(any(label["name"] == "agent:builder"
                                        for label in pr.get("labels", [])) for pr in pulls):
            return {"eligible": [], "skipped": [{"number": None,
                    "reason": "agent PR budget full or an existing Builder PR needs review/repair"}]}
    changed = [f["filename"] for pr in pulls
               for f in pages(repo, f"pulls/{pr['number']}/files")]
    issues = pages(repo, "issues?state=open&labels=ready-for-agent&sort=created&direction=asc")
    eligible, skipped = [], []
    def order(row):
        priority = min((PRIORITY.get(label["name"], 3) for label in row.get("labels", [])), default=3)
        return priority, row["created_at"], row["number"]
    for issue in sorted(issues, key=order):
        if "pull_request" in issue:
            continue
        reason = skip_reason(issue, changed=changed, builder=builder)
        if reason is None:
            blocked = any(i["state"] == "open" for i in pages(
                repo, f"issues/{issue['number']}/dependencies/blocked_by"))
            timeline = pages(repo, f"issues/{issue['number']}/timeline")
            linked = any((event.get("source") or {}).get("issue", {}).get("pull_request")
                         and event["source"]["issue"].get("state") == "open"
                         for event in timeline)
            reason = skip_reason(issue, blocked=blocked, linked_pr=linked,
                                 changed=changed, builder=builder)
        if reason:
            skipped.append({"number": issue["number"], "reason": reason})
        else:
            eligible.append(issue)
    return {"eligible": eligible, "skipped": skipped}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default="PedroDnT/SILO-BZ")
    parser.add_argument("--builder", action="store_true")
    args = parser.parse_args()
    print(json.dumps(queue(args.repo, builder=args.builder), indent=2))


if __name__ == "__main__":
    main()
