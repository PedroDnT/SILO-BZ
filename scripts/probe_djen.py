#!/usr/bin/env python3
"""Probe DJEN (CNJ's Diário de Justiça Eletrônico Nacional) for RJ editais (#843).

Read-only spike for epic #841: can SILO reach DJEN's public consult API from a
GitHub-hosted runner, and can it isolate recuperação judicial (RJ) items?

    python scripts/probe_djen.py reach
    python scripts/probe_djen.py sample --start 2026-09-01 --end 2026-09-30 --tribunals TJSP TJRJ
    python scripts/probe_djen.py proxies --rounds 3

`reach` sends one small query and prints the HTTP status, the item count and
the field names. `sample` pages through RJ-related items per tribunal over a
window and prints counts only: how many items, how many are of the RJ classes,
how many read like a deferimento do processamento or an art. 52 edital, and how
many name an administrador judicial. `proxies` asks whether a free public
Brazilian proxy can stand in for a paid one: it reads published BR proxy lists,
sends the `reach` query through each proxy with TLS verified end to end, and
prints how many answer HTTP 200 and how many keep answering over a few rounds.

It never prints party names, texts, CPFs or CNPJs: the log is public. Nothing is
stored. A failed request raises (exit 1), so a blocked runner is a red job with
the status code in the log, never an empty-looking result.

The endpoint and its parameters are documented by third parties, not by CNJ
(GET https://comunicaapi.pje.jus.br/api/v1/comunicacao). The probe therefore
prints the field names it actually received instead of assuming a schema.
"""

from __future__ import annotations

import argparse
import json
import concurrent.futures
import re
import subprocess
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from typing import Any, Iterable

BASE = "https://comunicaapi.pje.jus.br/api/v1/comunicacao"
USER_AGENT = "SILO-BZ DJEN probe (github.com/PedroDnT/SILO-BZ, issue 843)"
MIN_INTERVAL_S = 1.0  # at most one request per second
DEFAULT_TRIBUNALS = ("TJSP", "TJRJ", "TJMG", "TJRS", "TJPR", "TJSC")
SEARCH_TEXT = "recuperação judicial"
PAGE_SIZE = 100

# Published lists of free Brazilian proxies (scheme://ip:port, one per line).
FREE_PROXY_LISTS = (
    "https://api.proxyscrape.com/v4/free-proxy-list/get?request=display_proxies&country=br"
    "&protocol=http&proxy_format=protocolipport&format=text&timeout=10000",
    "https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/countries/BR/data.txt",
)
_PROXY_LINE = re.compile(r"^(https?|socks4a?|socks5h?)://[0-9A-Za-z.\-]+:\d{2,5}$")

# TPU classes (CNJ Tabelas Processuais Unificadas).
RJ_CLASS_CODES = {"129", "128"}  # 129 Recuperação Judicial, 128 Recuperação Extrajudicial

_last_request = 0.0


class ProbeError(RuntimeError):
    """A request DJEN did not answer with HTTP 200 and JSON."""


def _fold(text: str) -> str:
    """Lower case without accents, so 'Deferimento' and 'deferimento' match."""
    norm = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in norm if not unicodedata.combining(c)).lower()


def fetch(params: dict[str, Any], timeout: int = 60) -> dict[str, Any]:
    """One GET, rate limited. Raises ProbeError on any non-200 or non-JSON reply."""
    global _last_request
    wait = MIN_INTERVAL_S - (time.monotonic() - _last_request)
    if wait > 0:
        time.sleep(wait)
    url = f"{BASE}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    _last_request = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
            status = resp.status
    except urllib.error.HTTPError as e:
        snippet = e.read()[:200].decode("utf-8", "replace")
        raise ProbeError(f"HTTP {e.code} from DJEN: {snippet!r}") from e
    except urllib.error.URLError as e:
        raise ProbeError(f"DJEN unreachable: {e.reason!r}") from e
    if status != 200:
        raise ProbeError(f"HTTP {status} from DJEN")
    try:
        return json.loads(body)
    except ValueError as e:
        raise ProbeError(f"DJEN answered 200 but not JSON: {body[:200]!r}") from e


def items_of(payload: dict[str, Any]) -> list[dict[str, Any]]:
    items = payload.get("items")
    if items is None:
        raise ProbeError(f"no 'items' in the reply; keys: {sorted(payload)}")
    return items


def classify(item: dict[str, Any]) -> dict[str, bool]:
    """Booleans only. The text is read here and never printed."""
    text = _fold(str(item.get("texto") or ""))
    klass = str(item.get("codigoClasse") or item.get("codigo_classe") or "")
    klass_name = _fold(str(item.get("nomeClasse") or item.get("nome_classe") or ""))
    return {
        "rj_class": klass in RJ_CLASS_CODES or "recuperacao judicial" in klass_name
        or "recuperacao extrajudicial" in klass_name,
        "deferimento": bool(re.search(r"defer\w*\s+(o\s+)?processamento", text)),
        "edital_art52": "edital" in text and bool(re.search(r"art(igo|\.)?\s*52", text)),
        "names_aj": bool(re.search(r"administrador(a)?\s+judicial", text)),
        "has_process_number": bool(item.get("numero_processo") or item.get("numeroprocessocommascara")),
    }


def summarise(items: Iterable[dict[str, Any]]) -> Counter:
    totals: Counter = Counter()
    for item in items:
        totals["items"] += 1
        flags = classify(item)
        for key, value in flags.items():
            totals[key] += int(value)
        totals["rj_class_and_names_aj"] += int(flags["rj_class"] and flags["names_aj"])
    return totals


def cmd_reach(_: argparse.Namespace) -> int:
    payload = fetch({"siglaTribunal": "TJSP", "pagina": 1, "itensPorPagina": 5,
                     "texto": SEARCH_TEXT})
    items = items_of(payload)
    print("reachable: yes (HTTP 200, JSON)")
    print(f"top-level keys: {sorted(payload)}")
    print(f"count: {payload.get('count')}")
    fields = sorted({k for it in items for k in it})
    print(f"item fields ({len(fields)}): {fields}")
    return 0


def cmd_sample(args: argparse.Namespace) -> int:
    print(f"window {args.start} .. {args.end}, text {SEARCH_TEXT!r}, max {args.max_pages} pages per tribunal")
    for tribunal in args.tribunals:
        totals: Counter = Counter()
        reported = None
        for page in range(1, args.max_pages + 1):
            payload = fetch({
                "siglaTribunal": tribunal,
                "dataDisponibilizacaoInicio": args.start,
                "dataDisponibilizacaoFim": args.end,
                "texto": SEARCH_TEXT,
                "pagina": page,
                "itensPorPagina": PAGE_SIZE,
            })
            if reported is None:
                reported = payload.get("count")
            items = items_of(payload)
            totals += summarise(items)
            if len(items) < PAGE_SIZE:
                break
        capped = "" if totals["items"] >= (reported or 0) else f" (read {totals['items']} of {reported})"
        print(f"{tribunal}: reported={reported}{capped} " + " ".join(
            f"{k}={totals[k]}" for k in ("items", "rj_class", "deferimento", "edital_art52",
                                          "names_aj", "rj_class_and_names_aj", "has_process_number")))
    return 0


def parse_proxy_list(text: str) -> list[str]:
    """scheme://host:port lines, deduplicated in order; anything else is skipped."""
    seen: dict[str, None] = {}
    for line in text.splitlines():
        line = line.strip()
        if _PROXY_LINE.match(line):
            seen.setdefault(line, None)
    return list(seen)


def try_proxy(proxy: str, timeout: int = 15) -> str:
    """HTTP status of the reach query through one proxy ("000" when it never answered).

    curl, not urllib, because it speaks SOCKS too. TLS is verified as usual, so a
    proxy that tampers with the connection fails instead of feeding fake data.
    """
    url = f"{BASE}?{urllib.parse.urlencode({'siglaTribunal': 'TJSP', 'pagina': 1, 'itensPorPagina': 5, 'texto': SEARCH_TEXT})}"
    r = subprocess.run(["curl", "-s", "-m", str(timeout), "--proxy", proxy, "-A", USER_AGENT,
                        "-o", "/dev/null", "-w", "%{http_code}", url], capture_output=True, text=True)
    return r.stdout.strip() or "000"


def cmd_proxies(args: argparse.Namespace) -> int:
    proxies: list[str] = []
    for src in args.lists:
        req = urllib.request.Request(src, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=30) as resp:
            found = parse_proxy_list(resp.read().decode("utf-8", "replace"))
        print(f"list {urllib.parse.urlsplit(src).netloc}: {len(found)} proxies")
        proxies += [p for p in found if p not in proxies]
    alive = proxies
    for rnd in range(1, args.rounds + 1):
        with concurrent.futures.ThreadPoolExecutor(args.workers) as ex:
            codes = dict(zip(alive, ex.map(try_proxy, alive)))
        print(f"round {rnd}: tried {len(alive)}, status counts {dict(Counter(codes.values()))}")
        alive = [p for p, c in codes.items() if c == "200"]
        if not alive:
            break
        if rnd < args.rounds:
            time.sleep(args.pause)
    print(f"answered HTTP 200 in all {args.rounds} rounds: {len(alive)} of {len(proxies)}")
    for p in alive:
        print(f"  ok {p}")
    return 0 if alive else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("reach", help="one small query: status, count, field names")
    sample = sub.add_parser("sample", help="counts of RJ items per tribunal over a window")
    sample.add_argument("--start", required=True, help="first day, YYYY-MM-DD")
    sample.add_argument("--end", required=True, help="last day, YYYY-MM-DD")
    sample.add_argument("--tribunals", nargs="+", default=list(DEFAULT_TRIBUNALS))
    sample.add_argument("--max-pages", type=int, default=20)
    prox = sub.add_parser("proxies", help="can a free public BR proxy reach DJEN, and does it keep working?")
    prox.add_argument("--lists", nargs="+", default=list(FREE_PROXY_LISTS))
    prox.add_argument("--rounds", type=int, default=3)
    prox.add_argument("--pause", type=float, default=60.0, help="seconds between rounds")
    prox.add_argument("--workers", type=int, default=40)
    args = parser.parse_args(argv)
    try:
        return {"reach": cmd_reach, "sample": cmd_sample, "proxies": cmd_proxies}[args.cmd](args)
    except ProbeError as e:
        print(f"reachable: no ({e})", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
