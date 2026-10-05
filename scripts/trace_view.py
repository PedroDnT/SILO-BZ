"""Read the diagnosis run traces (ADR 0003) as text.

The Worker writes one OTLP/JSON trace per run to the private R2 bucket
``silo-diagnosis-traces`` under ``traces/YYYY/MM/DD/<trace_id>.json`` (UTC date);
``src/portfolio/trace.py`` builds it. This prints one trace as a timeline (spans,
engine section statuses, agents with tokens and cost, Revisor removals), or several
as one row each. Times are shown in UTC-3 with UTC in parentheses.

    python scripts/trace_view.py list                      # keys of today and yesterday (UTC)
    python scripts/trace_view.py list --days 7
    python scripts/trace_view.py show traces/2026/10/06/<id>.json   # from R2
    python scripts/trace_view.py show trace.json           # a local file
    python scripts/trace_view.py show a.json b.json ...    # one row per trace
    python scripts/trace_view.py exposure PETR4 <trace key | engine.json>   # where an asset's exposure comes from

``list`` uses the R2 REST API with ``CLOUDFLARE_ACCOUNT_ID`` and ``CLOUDFLARE_API_TOKEN``
(Workers R2 Storage read), taken from the environment or, when unset, from the ``.env`` file at the repository root;
``show`` and ``exposure`` of a key that is not a local file run ``npx wrangler r2 object get`` in
``deploy/cloudflare/`` with the same credentials, as the deploy workflow does.
Traces hold no statement bytes and no free text, but they describe a real portfolio:
keep what you download out of the repository.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

BUCKET = "silo-diagnosis-traces"
REPO = Path(__file__).resolve().parent.parent
BRT = timezone(timedelta(hours=-3))
BAR = 32
STATUS = {0: "-", 1: "OK", 2: "ERROR"}


def _plain(value: dict[str, Any]) -> Any:
    """One OTLP/JSON AnyValue as a Python value (intValue is a string in OTLP/JSON)."""
    kind, v = next(iter(value.items()))
    if kind == "intValue":
        return int(v)
    if kind == "arrayValue":
        return [_plain(x) for x in v.get("values") or []]
    return v


def attrs(obj: dict[str, Any]) -> dict[str, Any]:
    return {kv["key"]: _plain(kv["value"]) for kv in obj.get("attributes") or []}


def spans_of(trace: dict[str, Any]) -> list[dict[str, Any]]:
    return [s for rs in trace.get("resourceSpans") or [] for ss in rs.get("scopeSpans") or [] for s in ss.get("spans") or []]


def when(ns: int) -> str:
    t = datetime.fromtimestamp(ns / 1e9, tz=timezone.utc)
    return f"{t.astimezone(BRT):%Y-%m-%d %H:%M:%S} UTC-3 ({t:%H:%M:%S} UTC)"


def _secs(ns: int) -> str:
    return f"{ns / 1e9:.1f}s"


def _usd(v: Any) -> str:
    return "-" if v is None else f"US$ {float(v):.4f}"


def render(trace: dict[str, Any]) -> str:
    spans = spans_of(trace)
    if not spans:
        return "trace with no spans"
    root = spans[0]
    ra = attrs(root)
    t0, t1 = int(root["startTimeUnixNano"]), int(root["endTimeUnixNano"])
    total = max(t1 - t0, 1)
    out = [
        f"Trace {root['traceId']} · {when(t0)} · HTTP {ra.get('app.http.status', '?')} "
        f"{STATUS[root['status']['code']]} · {_secs(t1 - t0)} · {_usd(ra.get('app.cost_usd'))}",
        f"schema {ra.get('app.engine.schema_version', '-')} · engine rev {ra.get('app.engine.rev', '-')} · "
        f"git {ra.get('app.git_sha', '-')} · {ra.get('app.files', 0)} file(s) {ra.get('app.formats', '-')}, "
        f"{ra.get('app.in_bytes', 0)} B",
    ]
    if "app.failed_stage" in ra:
        out.append(f"FAILED at stage {ra['app.failed_stage']}: {ra.get('error.type', 'unknown error type')}")
    for label, key in (("engine JSON", "app.engine_json"), ("PDF", "app.pdf")):
        sha = ra.get(f"{key}.sha256")
        if sha:
            ext = "json" if key == "app.engine_json" else "pdf"
            out.append(f"{label}: artifacts/{sha}.{ext} ({ra.get(f'{key}.bytes', '?')} B)")

    out += ["", "Timeline"]
    width = max(len(s["name"]) for s in spans) + 2
    for i, s in enumerate(spans):
        a, b = int(s["startTimeUnixNano"]) - t0, int(s["endTimeUnixNano"]) - t0
        lo, hi = round(a / total * BAR), max(round(b / total * BAR), round(a / total * BAR) + 1)
        lead = "" if i == 0 else ("└ " if i == len(spans) - 1 else "├ ")
        bar = " " * lo + "█" * (hi - lo) + " " * (BAR - hi)
        out.append(f"  {(lead + s['name']).ljust(width + 2)} {_secs(a):>7} |{bar}| {_secs(b - a):>7}  {STATUS[s['status']['code']]}")

    for s in spans:
        sa = attrs(s)
        if s["name"] == "engine.run":
            secs = sorted({k.split(".")[2] for k in sa if k.startswith("app.section.")})
            if secs:
                out += ["", "Sections (engine.run)"]
                for name in secs:
                    codes = ", ".join(sa.get(f"app.section.{name}.reason_codes") or [])
                    out.append(f"  {name:<22} {sa.get(f'app.section.{name}.status', '-'):<12} {codes}")
            ident = {k.removeprefix("app.identification."): v for k, v in sa.items() if k.startswith("app.identification.")}
            if ident:
                out.append("Identification: " + " · ".join(f"{k} {v}" for k, v in ident.items()))
            if "error.type" in sa:
                out.append(f"Engine error: {sa['error.type']}")

    agents = [s for s in spans if s["name"].startswith("invoke_agent ")]
    if agents:
        out += ["", "Agents"]
    for s in agents:
        sa = attrs(s)
        model = sa.get("gen_ai.request.model", "-")
        if sa.get("gen_ai.response.model") and sa["gen_ai.response.model"] != model:
            model += f" (answered by {sa['gen_ai.response.model']})"
        line = (f"  {sa.get('gen_ai.agent.name', s['name']):<8} {sa.get('gen_ai.provider.name', '-')} {model} · "
                f"{sa.get('app.llm.calls', 0)} call(s) · tokens in {sa.get('gen_ai.usage.input_tokens', '-')} "
                f"out {sa.get('gen_ai.usage.output_tokens', '-')} reasoning {sa.get('app.llm.reasoning_tokens', '-')} · "
                f"{_usd(sa.get('app.cost_usd'))}")
        if "app.narrative.status" in sa:
            line += f" · narrative {sa['app.narrative.status']}"
            if sa.get("app.narrative.reason_code"):
                line += f" ({sa['app.narrative.reason_code']})"
            line += f" · findings kept {sa.get('app.findings.kept', 0)}"
        if "app.findings.removed" in sa:
            line += f" · removed {sa['app.findings.removed']}"
        out.append(line)

    removed = [attrs(e) for s in agents for e in s.get("events") or [] if e.get("name") == "app.revisor.removed"]
    if removed:
        out += ["", "Revisor removals (rule · section · finding · whole/part · text sha256)"]
        for e in removed:
            out.append(f"  {e.get('app.revisor.rule', '-'):<28} {e.get('app.finding.section', '-'):<14} "
                       f"{e.get('app.finding.id', '-'):<8} {'whole' if e.get('app.finding.whole') else 'part':<6} "
                       f"{str(e.get('app.finding.text_sha256', ''))[:12]}")
    return "\n".join(out)


def row(trace: dict[str, Any]) -> str:
    spans = spans_of(trace)
    if not spans:
        return "(no spans)"
    root = spans[0]
    ra = attrs(root)
    t0, t1 = int(root["startTimeUnixNano"]), int(root["endTimeUnixNano"])
    removed = sum(attrs(s).get("app.findings.removed", 0) for s in spans if s["name"] == "invoke_agent revisor")
    tokens = sum((attrs(s).get("gen_ai.usage.input_tokens") or 0) + (attrs(s).get("gen_ai.usage.output_tokens") or 0)
                 for s in spans if s["name"].startswith("invoke_agent "))
    stage = ra.get("app.failed_stage") or "-"
    return (f"{when(t0)}  {root['traceId'][:12]}  {ra.get('app.http.status', '?'):>3}  {stage:<8} "
            f"{_secs(t1 - t0):>7}  {_usd(ra.get('app.cost_usd')):>12}  tokens {tokens:>7}  removed {removed:>2}  "
            f"schema {ra.get('app.engine.schema_version', '-')}")


CF_VARS = ("CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_API_TOKEN")


def read_dotenv(path: Path) -> dict[str, str]:
    """``KEY=VALUE`` lines of a .env file (an optional ``export``, optional quotes). Values are never printed."""
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.removeprefix("export ").partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        out[key.strip()] = value
    return out


def cloudflare_credentials(dotenv: Path | None = None) -> dict[str, str]:
    """The Cloudflare account id and token: the environment first, then the repository's .env."""
    file = read_dotenv(dotenv if dotenv is not None else REPO / ".env")
    return {k: os.environ.get(k) or file.get(k, "") for k in CF_VARS}


def list_keys(days: int, now: datetime | None = None) -> list[dict[str, Any]]:
    creds = cloudflare_credentials()
    account, token = creds["CLOUDFLARE_ACCOUNT_ID"], creds["CLOUDFLARE_API_TOKEN"]
    if not account or not token:
        sys.exit("list needs CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN, in the environment or in the .env file "
                 "at the repository root")
    now = now or datetime.now(timezone.utc)
    api = f"https://api.cloudflare.com/client/v4/accounts/{account}/r2/buckets/{BUCKET}/objects"
    objs: list[dict[str, Any]] = []
    for d in range(days):
        day = (now - timedelta(days=d)).strftime("%Y/%m/%d")
        req = urllib.request.Request(f"{api}?prefix=traces/{day}/&per_page=1000",
                                     headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req, timeout=60) as r:
            objs += parse_listing(json.load(r))
    return objs


def parse_listing(d: dict[str, Any]) -> list[dict[str, Any]]:
    if not d.get("success"):
        raise SystemExit(f"R2 list failed: {[e.get('code') for e in d.get('errors') or []]} "
                         "(token needs Workers R2 Storage read)")
    return list(d.get("result") or [])


def r2_get(key: str) -> bytes:
    env = {**os.environ, **{k: v for k, v in cloudflare_credentials().items() if v}}
    r = subprocess.run(["npx", "wrangler", "r2", "object", "get", f"{BUCKET}/{key}", "--remote", "--pipe"],
                       cwd=REPO / "deploy" / "cloudflare", capture_output=True, stdin=subprocess.DEVNULL, env=env)
    if r.returncode != 0:
        raise SystemExit(f"could not read {key} from R2: {r.stderr.decode(errors='replace').strip()[-400:]}")
    return r.stdout


def load(ref: str) -> dict[str, Any]:
    p = Path(ref)
    return json.loads(p.read_text() if p.is_file() else r2_get(ref))


def engine_doc(ref: str) -> dict[str, Any]:
    """The engine JSON: a local engine file as is, or the artifact a trace (local file or R2 key) names."""
    doc = load(ref)
    if "look_through" in doc:
        return doc
    spans = spans_of(doc)
    sha = attrs(spans[0]).get("app.engine_json.sha256") if spans else None
    if not sha:
        raise SystemExit("this trace names no engine JSON artifact (a run that failed before the engine ended has none)")
    return json.loads(r2_get(f"artifacts/{sha}.json"))


def _brl(v: Any) -> str:
    return "R$ " + f"{float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _pct(v: Any) -> str:
    return f"{float(v):.2f}".replace(".", ",") + "%"


def exposure_text(doc: dict[str, Any], ticker: str) -> str:
    """Where the exposure to one asset comes from: each statement line that holds it, directly or through a fund."""
    lt = doc.get("look_through") or {}
    groups = [g for g in (lt.get("shared_exposure") or {}).get("groups") or []
              if g.get("kind") == "mesmo_ativo" and ticker.upper() in str(g.get("label", "")).upper()]
    if not groups:
        return (f"{ticker}: no asset held through more than one statement line matches in this engine output "
                f"(look-through status: {lt.get('status')}, CDA month: {lt.get('cda_month')}).")
    position_date = (doc.get("statement") or {}).get("position_date")
    by_line = {li.get("line_no"): li for li in lt.get("lines") or []}
    out = []
    for g in groups:
        out.append(f"{g['label']}: {_brl(g['total_exposure_brl'])} = {_pct(g['total_exposure_portfolio_pct'])} da carteira")
        for ln in g.get("lines") or []:
            if ln.get("direct"):
                out.append(f"  direta       {ln['linha_extrato']} (linha {ln['line_no']}): {_brl(ln['exposure_brl'])}")
                continue
            ex = next((e for e in (by_line.get(ln["line_no"]) or {}).get("exposures") or []
                       if str(e.get("asset_key", "")).upper() == ticker.upper()), None)
            detail = ""
            if ex:
                bits = []
                if ex.get("weight_in_line") is not None:
                    bits.append(f"{_pct(float(ex['weight_in_line']) * 100)} do valor do fundo")
                if ex.get("period"):
                    bits.append(f"CDA de {str(ex['period'])[:7]}")
                if ex.get("depth"):
                    bits.append(f"nível {ex['depth']}")
                detail = "; " + "; ".join(bits) if bits else ""
            out.append(f"  via fundo    {ln['linha_extrato']} (linha {ln['line_no']}): {_brl(ln['exposure_brl'])}{detail}")
    out += ["",
            f"Extrato de {position_date or '?'}; CDA do look-through: {lt.get('cda_month')}. A parte via fundo é a carteira "
            "do fundo naquele mês, não na data do extrato; fundo sem CDA do mês não é aberto (o total é um piso).",
            (lt.get("shared_exposure") or {}).get("note") or ""]
    return "\n".join(x for x in out if x is not None)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    ls = sub.add_parser("list", help="trace keys in R2, newest day first")
    ls.add_argument("--days", type=int, default=2, help="UTC days back, today included (default 2)")
    sh = sub.add_parser("show", help="one trace in detail, or several as one row each")
    sh.add_argument("refs", nargs="+", help="local file or R2 key (traces/YYYY/MM/DD/<id>.json)")
    ex = sub.add_parser("exposure", help="where the exposure to one asset comes from (direct and through funds)")
    ex.add_argument("ticker", help="e.g. PETR4")
    ex.add_argument("ref", help="engine.json, a local trace file, or an R2 trace key (traces/YYYY/MM/DD/<id>.json)")
    args = ap.parse_args(argv)
    if args.cmd == "exposure":
        print(exposure_text(engine_doc(args.ref), args.ticker))
        return 0
    if args.cmd == "list":
        for o in list_keys(args.days):
            print(f"{o.get('key')}  {o.get('size', '?')} B  {o.get('last_modified', '')}")
        return 0
    traces = [load(r) for r in args.refs]
    print(render(traces[0]) if len(traces) == 1 else "\n".join(row(t) for t in traces))
    return 0


if __name__ == "__main__":
    sys.exit(main())
