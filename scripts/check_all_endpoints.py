#!/usr/bin/env python3
"""
CVM Live Endpoint Checker
=========================
Run this from your terminal (outside VS Code sandbox) to fetch real data
from all 7 CVM endpoints and display parsed results.

Usage:
    cd /path/to/repo
    CVM_DNS_NAMESERVERS="1.1.1.1,8.8.8.8,9.9.9.9" .venv/bin/python check_all_endpoints.py

Optional flags:
    --rows N        Number of sample rows to display per endpoint (default: 3)
    --cols N        Max columns to display per row (default: 10)
    --page-size N   Records per page to fetch (default: 10)
    --entity NAME   Only run endpoints for this entity (fidc/fip/fiagro/securit)
"""

import asyncio
import json
import sys
import time
import argparse
import socket
from typing import Optional

# ---------------------------------------------------------------------------
# CLI args
# ---------------------------------------------------------------------------

parser = argparse.ArgumentParser(description="CVM live endpoint checker")
parser.add_argument("--rows",      type=int, default=3,  help="Sample rows to show per endpoint")
parser.add_argument("--cols",      type=int, default=10, help="Max columns per row")
parser.add_argument("--page-size", type=int, default=10, help="Page size for each request")
parser.add_argument("--entity",    type=str, default=None, help="Filter to one entity")
args = parser.parse_args()

# ---------------------------------------------------------------------------
# Colour helpers (ANSI, graceful fallback if terminal doesn't support them)
# ---------------------------------------------------------------------------

def _c(code: str, text: str) -> str:
    if sys.stdout.isatty():
        return f"\033[{code}m{text}\033[0m"
    return text

GREEN  = lambda t: _c("32;1", t)
RED    = lambda t: _c("31;1", t)
YELLOW = lambda t: _c("33;1", t)
CYAN   = lambda t: _c("36;1", t)
BOLD   = lambda t: _c("1",    t)
DIM    = lambda t: _c("2",    t)

# ---------------------------------------------------------------------------
# Endpoint matrix
# ---------------------------------------------------------------------------

ALL_ENDPOINTS = [
    # (entity,   doc_type,           year,  month)
    ("fidc",    "mensal",            2025,  2),
    ("fip",     "inf_quadrimestral", 2024,  None),
    ("fip",     "inf_trimestral",    2022,  None),
    ("fiagro",  "mensal",            2025,  12),
    ("securit", "cra_mensal",        2024,  None),
    ("securit", "cri_mensal",        2024,  None),
    ("securit", "ots_mensal",        2024,  None),
]

ENDPOINTS = [
    ep for ep in ALL_ENDPOINTS
    if args.entity is None or ep[0] == args.entity.lower()
]

# ---------------------------------------------------------------------------
# Network pre-check
# ---------------------------------------------------------------------------

def check_network() -> bool:
    try:
        socket.setdefaulttimeout(5)
        socket.getaddrinfo("dados.cvm.gov.br", 443)
        return True
    except OSError:
        return False

# ---------------------------------------------------------------------------
# Pretty printers
# ---------------------------------------------------------------------------

SEP = "─" * 70

def print_header(entity: str, doc_type: str, year: int, month: Optional[int]) -> None:
    period = f"{year}-{month:02d}" if month else str(year)
    print(f"\n{SEP}")
    print(BOLD(f"  {entity.upper()} / {doc_type}   [{period}]"))
    print(SEP)


def print_columns(cols: list) -> None:
    print(CYAN(f"  COLUMNS ({len(cols)}):"))
    line = ""
    for col in cols:
        candidate = line + ("  " if line else "") + col
        if len(candidate) > 78:
            print(f"    {line}")
            line = col
        else:
            line = candidate
    if line:
        print(f"    {line}")


def print_row(idx: int, row: dict, max_cols: int) -> None:
    items = [(k, v) for k, v in row.items() if v not in (None, "")]
    shown = items[:max_cols]
    print(DIM(f"  ── row {idx} ──────────────────────────────"))
    for k, v in shown:
        print(f"    {YELLOW(k)}: {v}")
    hidden = len(items) - len(shown)
    if hidden > 0:
        print(DIM(f"    ... +{hidden} more non-null fields"))


def print_quality(dq: dict) -> None:
    if not dq:
        return
    print(CYAN("  DATA QUALITY:"))
    print("    " + json.dumps(dq, ensure_ascii=False).replace(", ", ",\n    "))

# ---------------------------------------------------------------------------
# Single endpoint runner
# ---------------------------------------------------------------------------

async def run_endpoint(svc, entity: str, doc_type: str, year: int, month: Optional[int]) -> dict:
    """Fetch one endpoint and return a result dict."""
    t0 = time.perf_counter()
    try:
        response = await svc.get_data(
            entity=entity,
            doc_type=doc_type,
            year=year,
            month=month,
            page=1,
            page_size=args.page_size,
        )
        elapsed = time.perf_counter() - t0
        return {"ok": True, "response": response, "elapsed": elapsed}
    except Exception as exc:
        elapsed = time.perf_counter() - t0
        return {"ok": False, "error": str(exc), "elapsed": elapsed}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main():
    # Lazy import so errors surface clearly
    from src.cvm_api.services import CVMCreditDataService

    print(BOLD("\nCVM Live Endpoint Checker"))
    print(f"Endpoints to test: {len(ENDPOINTS)}")
    print(f"Page size        : {args.page_size}")
    print(f"Sample rows      : {args.rows}")

    if not check_network():
        print(RED("\n✗ Cannot resolve dados.cvm.gov.br — check your network / DNS."))
        print("  Tip: set CVM_DNS_NAMESERVERS=1.1.1.1,8.8.8.8,9.9.9.9 in env")
        sys.exit(1)

    print(GREEN("  Network OK — dados.cvm.gov.br is reachable\n"))

    svc = CVMCreditDataService()
    summary = []

    for entity, doc_type, year, month in ENDPOINTS:
        print_header(entity, doc_type, year, month)
        result = await run_endpoint(svc, entity, doc_type, year, month)

        if not result["ok"]:
            print(RED(f"  ✗ FAILED ({result['elapsed']:.2f}s)"))
            print(f"  {result['error']}")
            summary.append((entity, doc_type, False, result["elapsed"], result["error"]))
            continue

        resp = result["response"]
        total     = resp.pagination.total_items
        pages     = resp.pagination.total_pages
        proc_time = resp.metadata.get("processing_time_seconds", result["elapsed"])
        source    = resp.metadata.get("source_url", "")

        print(GREEN(f"  ✓ OK  ({proc_time:.2f}s fetch+parse)"))
        print(f"  SOURCE URL   : {source}")
        print(f"  TOTAL RECORDS: {total:,}")
        print(f"  TOTAL PAGES  : {pages:,}  (page_size={args.page_size})")

        if resp.data:
            cols = list(resp.data[0].keys())
            print_columns(cols)
            print(CYAN(f"\n  SAMPLE ROWS (first {min(args.rows, len(resp.data))} of {total:,}):"))
            for i, row in enumerate(resp.data[:args.rows], 1):
                print_row(i, row, args.cols)

        print_quality(resp.metadata.get("data_quality", {}))
        summary.append((entity, doc_type, True, proc_time, None))

    # -----------------------------------------------------------------------
    # Summary table
    # -----------------------------------------------------------------------
    print(f"\n{SEP}")
    print(BOLD("  SUMMARY"))
    print(SEP)
    ok_count  = sum(1 for s in summary if s[2])
    err_count = len(summary) - ok_count

    for entity, doc_type, ok, elapsed, err in summary:
        status = GREEN("✓ OK   ") if ok else RED("✗ ERROR")
        label  = f"{entity}/{doc_type}"
        print(f"  {status}  {label:<35s}  {elapsed:.2f}s  {err or ''}")

    print(SEP)
    colour = GREEN if err_count == 0 else RED
    print(colour(f"  {ok_count}/{len(summary)} endpoints passed"))
    print(SEP + "\n")


if __name__ == "__main__":
    asyncio.run(main())
