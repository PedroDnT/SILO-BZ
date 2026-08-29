#!/usr/bin/env python3
"""Preflight: can this runner reach dados.cvm.gov.br at all?

WHY THIS EXISTS
A backfill dispatch is up to 300 minutes of work whose every download goes to
one host. When CVM refuses this runner's IP, that whole dispatch is doomed
before it starts, and finding out costs the full grind. Measured on 2026-08-29:
the 06:00 ingest spent ~40 minutes proving the same refusal across twenty
slices, and the 07:35 health check then reported the pipeline red for it.

This asks the question once, in about a second, so the answer arrives before
the work does rather than after.

WHAT IT CHECKS, AND WHAT IT DELIBERATELY DOES NOT
It issues a ranged GET for the first bytes of a file that has existed for years
and is not part of any current publication window, so a green result means "the
host answered us", not "today's file is ready". A 404 for a not-yet-published
month is normal and is NOT what this is looking for: ANY HTTP response proves
the host is answering this IP, which is the only question here. Only a
connect-level failure — DNS, TCP, TLS — counts as unreachable, matching the
CVMHostUnreachable breaker in src/fetchers/cvm_fetcher.py.

EXIT CODES
    0  reachable — the host answered
    1  unreachable — connect-level failure after every attempt

It never fails the caller for a slow response alone; the timeout is generous
because a loaded CVM is still a working CVM.
"""
from __future__ import annotations

import argparse
import sys
import time
import urllib.error
import urllib.request

# Stable and old on purpose: this file is years past any publication window, so
# its absence would be news in itself rather than the routine "not published
# yet" 404 the daily window sees.
DEFAULT_URL = (
    "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/ITR/DADOS/itr_cia_aberta_2019.zip"
)


def probe(url: str, timeout: float, attempts: int) -> int:
    last: str = ""
    for attempt in range(1, attempts + 1):
        started = time.monotonic()
        req = urllib.request.Request(url, method="GET")
        # One kilobyte is enough to prove the host answers; pulling the whole
        # archive to test reachability would be its own kind of rude.
        req.add_header("Range", "bytes=0-1023")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                elapsed = time.monotonic() - started
                print(f"CVM reachable: HTTP {resp.status} in {elapsed:.2f}s ({url})")
                return 0
        except urllib.error.HTTPError as exc:
            # The host answered, which is the whole question. Even a 404 or a
            # 403 on this one path means the network route is open.
            elapsed = time.monotonic() - started
            print(f"CVM reachable: HTTP {exc.code} in {elapsed:.2f}s ({url})")
            return 0
        except Exception as exc:  # URLError, socket.timeout, ssl errors
            last = f"{type(exc).__name__}: {exc}"
            print(f"attempt {attempt}/{attempts} failed: {last}", file=sys.stderr)
            if attempt < attempts:
                time.sleep(2 * attempt)

    print(
        "CVM UNREACHABLE from this runner — connect-level failure, not a missing "
        f"file. Last error: {last}\n"
        "Every download in this dispatch goes to this host, so the run would "
        "spend its whole timeout proving the same refusal. Re-dispatch to draw a "
        "fresh runner IP; CVM being up from elsewhere does not mean it is up "
        "from here.",
        file=sys.stderr,
    )
    return 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--url", default=DEFAULT_URL)
    ap.add_argument("--timeout", type=float, default=30.0)
    ap.add_argument("--attempts", type=int, default=3)
    args = ap.parse_args()
    return probe(args.url, args.timeout, args.attempts)


if __name__ == "__main__":
    sys.exit(main())
