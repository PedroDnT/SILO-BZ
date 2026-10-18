"""Keep every CVM source file version the run downloaded, in R2 (#982).

Most CVM tables are upserted in place, so a correction CVM publishes replaces
the old value and nothing records when the new one appeared. The files
themselves are the record: this script stores each file in the fetcher's cache
(`cache/<md5(url)>.cache`, its URL and fetch time in the matching `.meta`) under

    <prefix>/<url path>/<sha256>

An object that already exists is not uploaded again, so the bucket grows only
when CVM changes a file, and an object's upload time is when SILO first saw that
version. Object metadata carries the source URL and the fetch time.

Uploads go through the AWS CLI (preinstalled on GitHub's runners) against R2's
S3 endpoint; credentials come from AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY.
Any failure exits 1 after the other files were tried.

    python scripts/archive_raw_sources.py --bucket silo-raw-sources \\
        --endpoint https://<account_id>.r2.cloudflarestorage.com

Runs in daily_ingest as the ingest job's last step, only when the repository
variable RAW_ARCHIVE_ENABLED is 1.
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import subprocess
import sys
from typing import Callable, List, Optional, Sequence
from urllib.parse import urlparse

Runner = Callable[[Sequence[str]], subprocess.CompletedProcess]


def _run(cmd: Sequence[str]) -> subprocess.CompletedProcess:
    return subprocess.run(list(cmd), capture_output=True, text=True)


def sha256_of(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def object_key(prefix: str, url: str, sha: str) -> str:
    """`<prefix>/<url path>/<sha256>`: one object per distinct content of a URL."""
    path = urlparse(url).path.strip("/")
    if not path:
        raise ValueError(f"no path in source URL {url!r}")
    return f"{prefix.strip('/')}/{path}/{sha}"


def _exists(run: Runner, aws: List[str], bucket: str, key: str) -> bool:
    out = run(aws + ["s3api", "head-object", "--bucket", bucket, "--key", key])
    if out.returncode == 0:
        return True
    if "Not Found" in out.stderr or "404" in out.stderr:
        return False
    raise RuntimeError(f"head-object {key}: {out.stderr.strip() or out.returncode}")


def archive(
    cache_dir: str, bucket: str, endpoint: str, prefix: str = "raw/cvm",
    run: Runner = _run,
) -> dict:
    """Upload each cached file not yet in the bucket. Returns the counts and errors."""
    aws = ["aws", "--endpoint-url", endpoint]
    counts = {"uploaded": 0, "already_held": 0, "errors": []}
    metas = sorted(glob.glob(os.path.join(cache_dir, "*.meta")))
    for meta_path in metas:
        data_path = meta_path[: -len(".meta")] + ".cache"
        try:
            with open(meta_path, encoding="utf-8") as f:
                meta = json.load(f)
            sha = sha256_of(data_path)
            key = object_key(prefix, meta["url"], sha)
            if _exists(run, aws, bucket, key):
                counts["already_held"] += 1
                continue
            out = run(aws + [
                "s3api", "put-object", "--bucket", bucket, "--key", key,
                "--body", data_path,
                "--metadata", f"source-url={meta['url']},fetched-at={meta['timestamp']},sha256={sha}",
            ])
            if out.returncode != 0:
                raise RuntimeError(f"put-object {key}: {out.stderr.strip() or out.returncode}")
            counts["uploaded"] += 1
            print(f"archived {key}")
        except Exception as exc:  # recorded and reported; the run still exits 1
            counts["errors"].append(f"{os.path.basename(meta_path)}: {exc}")
    return counts


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--cache-dir", default="cache")
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--prefix", default="raw/cvm")
    args = parser.parse_args(argv)

    counts = archive(args.cache_dir, args.bucket, args.endpoint, args.prefix)
    print(f"raw archive: {counts['uploaded']} new version(s), {counts['already_held']} already held, "
          f"{len(counts['errors'])} error(s)")
    for err in counts["errors"]:
        print(f"ERROR {err}", file=sys.stderr)
    return 1 if counts["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
