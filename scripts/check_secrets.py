"""Bounded secret guard for staged changes or a PR's additions; no secret output.

This is not a historical or general-purpose credential audit. It rejects private
dotenv files and database URLs containing passwords, without echoing file content,
Git errors, or caller-controlled filenames. Example/template dotenv files remain
subject to the content check. The local hook and CI call this same entry point.
"""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import PurePosixPath
from urllib.parse import unquote


DB_URL = re.compile(rb"postgres(?:ql)?://[^\s:@/]+:([^\s@]+)@", re.IGNORECASE)
EXAMPLES = {".env.example", ".env.template"}


def private_dotenv(path: str) -> bool:
    name = PurePosixPath(path).name
    return (name == ".env" or name.startswith(".env.")) and name not in EXAMPLES


def contains_password(text: bytes) -> bool:
    for match in DB_URL.finditer(text):
        password = unquote(match.group(1).decode("utf-8", errors="replace"))
        # Documentation placeholders are not credentials. Only bracketed labels
        # are exempt, never arbitrary strings such as "test" or "example".
        if not re.fullmatch(r"<[A-Za-z_ -]+>", password):
            return True
    return False


def git(*args: str) -> bytes:
    result = subprocess.run(["git", *args], capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError("git-input-unavailable")
    return result.stdout


def added_content(diff: bytes) -> bytes:
    additions: list[bytes] = []
    in_hunk = False
    for line in diff.splitlines():
        if line.startswith(b"diff --git "):
            in_hunk = False
        elif line.startswith(b"@@ "):
            in_hunk = True
        elif in_hunk and line.startswith(b"+"):
            additions.append(line[1:])
    return b"\n".join(additions)


def check(*, staged: bool, base: str | None = None, head: str = "HEAD") -> list[str]:
    if staged:
        selection = ["--cached"]
    else:
        if not base:
            raise RuntimeError("base-required")
        # Resolve caller refs before passing them to diff; errors never escape.
        base_sha = git("rev-parse", "--verify", f"{base}^{{commit}}").decode().strip()
        head_sha = git("rev-parse", "--verify", f"{head}^{{commit}}").decode().strip()
        ancestor = git("merge-base", base_sha, head_sha).decode().strip()
        selection = [ancestor, head_sha]
    names = git("diff", *selection, "--no-renames", "--name-only", "-z", "--diff-filter=ACMT", "--")
    paths = [p.decode("utf-8", errors="replace") for p in names.split(b"\0") if p]
    rules: list[str] = []
    if any(private_dotenv(path) for path in paths):
        rules.append("private-dotenv")
    diff = git("diff", *selection, "--no-color", "--no-renames", "--no-ext-diff", "--no-textconv",
               "--text", "--unified=0", "--output-indicator-new=+", "--output-indicator-old=-", "--")
    if contains_password(added_content(diff)):
        rules.append("embedded-db-credentials")
    return rules


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--staged", action="store_true")
    selection.add_argument("--base")
    parser.add_argument("--head", default="HEAD")
    args = parser.parse_args()
    try:
        rules = check(staged=args.staged, base=args.base, head=args.head)
    except (RuntimeError, OSError):
        print("secret guard: input unavailable; refusing unchecked changes")
        return 2
    if rules:
        print("secret guard: rejected (" + ", ".join(rules) + ")")
        return 1
    print("secret guard: passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
