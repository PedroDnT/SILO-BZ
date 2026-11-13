"""Generate task-specific playgrounds from the v2 registry; no new API routes.

Run after gen_openapi_v2.py. --check checks every generated artifact and navigation.
Each projection keeps the actual HTTP path and pins kind in its request schema.
Separate specs are necessary because OpenAPI cannot describe two GET /prices
operations and Mintlify cannot apply different overlays to the same source.
"""
from __future__ import annotations

import argparse
import copy
import json
import re
from pathlib import Path

from scripts.gen_openapi_v2 import ROOT, build, load_registry, load_error_codes

GROUPS = {
    "search": "Find identifiers", "prices": "Stock prices",
    "statements": "Financial statements", "funds": "Funds and holdings",
    "fidc": "Receivables funds", "derivatives": "Options and futures",
    "curves": "Interest rate curves", "macro": "Macroeconomics",
    "positioning": "Market positioning", "events": "Filings and events",
    "screens": "Research screens", "panel": "Cross-asset data",
    "portfolio": "Portfolio analysis", "coverage": "Data coverage",
}
TITLES = {
    "prices/history": "Historical stock prices", "prices/latest": "Latest closing price",
    "prices/session": "Market session", "prices/index": "Index history",
    "prices/forward": "Forward prices", "statements/all": "As-filed line items",
    "statements/income": "Income statements", "statements/balance": "Balance sheets",
    "statements/cashflow": "Cash flow statements", "statements/headline": "Headline financials",
    "statements/versions": "Filing version history", "search/any": "Resolve an identifier",
    "search/company": "Find companies", "search/fund": "Find funds",
    "search/universe": "Listed universe", "macro/series": "Economic series",
    "macro/inflation": "Inflation history", "macro/inflation_items": "Inflation components",
    "macro/fx": "Exchange rates", "macro/expectations": "Forecast revisions",
    "coverage/freshness": "Dataset freshness", "coverage/metrics": "Metric coverage",
    "coverage/catalog": "Data dictionary", "panel/panel": "Cross-asset panel",
    "funds/profile": "Fund profiles", "funds/nav": "NAV and flows",
    "funds/holdings": "Equity holdings", "funds/debentures": "Debenture holdings",
    "funds/properties": "Property holdings", "fidc/portfolio": "Receivables portfolio",
    "fidc/tranches": "Tranche performance", "fidc/aging": "Receivables aging",
    "fidc/cedentes": "Originator concentration", "fidc/sacados": "Debtor concentration",
    "derivatives/chain": "Option chain", "derivatives/history": "Option price history",
    "derivatives/exercises": "Option exercises", "derivatives/termo": "Termo contracts",
    "derivatives/futures": "Futures history", "derivatives/futures_curve": "Futures curve",
    "derivatives/di_settlement": "DI settlement rates",
    "curves/snapshot": "Latest yield curve", "curves/history": "Yield curve history",
    "curves/vertices": "Published curve vertices", "events/company": "Company filings",
    "events/fund": "Fund documents", "events/restatements": "Restated filings",
    "events/restatement_diff": "Restatement changes", "events/judicial_recovery": "Judicial recovery filings",
    "screens/list": "Available screens", "portfolio/resolve": "Resolve portfolio entries",
    "portfolio/fees": "Disclosed and estimated fees", "portfolio/fee_peers": "Fee peer comparison",
    "portfolio/lookthrough": "Portfolio look-through", "portfolio/movement": "Monthly return comparison",
    "portfolio/instruments": "Resolve credit instruments", "portfolio/fund_terms": "Fund redemption terms",
    "portfolio/equivalents": "ETF equivalents", "portfolio/debenture_returns": "Debenture fund marks",
}


def artifacts():
    registry = load_registry()
    base = build(registry, load_error_codes())
    files = {}
    groups = []
    links = []
    for resource in registry["resources"]:
        name = resource["name"]
        method = resource.get("method", "GET").lower()
        pages = []
        for kind, plan in resource["kinds"].items():
            key = f"{name}/{kind}"
            title = TITLES.get(key, kind.replace("_", " ").capitalize())
            slug = f"api-docs/v2/operations/{key}"
            spec_path = f"api-docs/v2/specs/{name}-{kind}.json"
            spec = copy.deepcopy(base)
            op = spec["paths"][f"/{name}"][method]
            spec["paths"] = {f"/{name}": {method: op}}
            op["operationId"] = f"v2_{name}_{kind}"
            op["summary"] = title
            op["x-mint"] = {"href": f"/{slug}"}
            detail = re.sub(r"api\.[a-z_]+(?:\(\))?:?", "", plan["doc"]).strip()
            detail = re.sub(r"\b(B3|BACEN|BCB|IBGE|CVM|ANBIMA|FNET|SGS)\b", "source", detail)
            op["description"] = (
                f"Deployed preview. {resource['summary']}\n\n"
                f"{detail}\n\n"
                f"This playground selects `{kind}` on `{method.upper()} /{name}`. "
                f"See the [full resource reference](/api-docs/v2/reference/{name}) for all variants."
            )
            used = {"kind", "cursor", "limit"} | set(plan.get("args", {})) | set(plan.get("uses", []))
            used |= {f["parameter"] for f in plan.get("filters", [])}
            if plan.get("view_by"):
                used.add(plan["view_by"]["parameter"])
            if plan.get("when_empty"):
                used.add(plan["when_empty"]["parameter"])
                used |= set(plan["when_empty"]["plan"].get("args", {}))
            op["parameters"] = [p for p in op["parameters"] if p["name"] in used]
            required = plan.get("require_one_of", [])
            for param in op["parameters"]:
                param.pop("example", None)
                if param["name"] == "kind":
                    param.update(required=True, example=kind, description=f"Selects {title.lower()}.")
                    param["schema"] = {"type": "string", "enum": [kind], "default": kind}
                elif param["name"] in required and len(required) == 1:
                    param["required"] = True
                # A resource example can name a ticker where another kind needs a
                # fund, index or document id. Never reuse that example blindly.
            if (name == "prices" and kind in {"history", "latest"}) or name == "statements":
                next(p for p in op["parameters"] if p["name"] == "id")["example"] = "PETR4"
            if name == "search" and kind in {"any", "company"}:
                next(p for p in op["parameters"] if p["name"] == "q")["example"] = "PETR4"
            if name == "portfolio" and kind != "resolve":
                media = op["requestBody"]["content"]["application/json"]
                media.pop("example", None)
                media["schema"]["required"] = ["id"]
            if name == "portfolio" and kind == "resolve":
                op["requestBody"]["content"]["application/json"]["schema"]["required"] = ["names"]
            files[spec_path] = json.dumps(spec, indent=2, ensure_ascii=False) + "\n"
            requirement = ""
            if required:
                requirement = "Supply " + " or ".join(f"`{p}`" for p in required) + ". "
            description = f"Query {title.lower()} through SILO REST and MCP v2."
            files[f"{slug}.mdx"] = f'''---
title: {json.dumps(title)}
description: {json.dumps(description)}
keywords: [{json.dumps(name)}, {json.dumps(kind)}, "API", "MCP"]
openapi: "{spec_path} {method.upper()} /{name}"
---

**Deployed preview.** {detail[0].upper() + detail[1:]}

{requirement}Open **Try it**, review the inputs, and select **Send** to query the deployed API.
The `kind` field is preset to `{kind}`. This is a view of the existing `/{name}` resource, not a new route.

<Note>
  Anonymous calls need no credential except on screens and portfolio, which require signed-in access.
  With a Pro credential, verify `meta.tier` is `pro` in the actual response.
</Note>

## Before you query

Resolve identifiers with [search](/api-docs/v2/reference/search), then check
[coverage](/api-docs/v2/reference/coverage). Dates and identifiers must match the
selected operation; expand the parameter descriptions below for its accepted values.

## Use from an agent

Call `silo_{name}` over [MCP v2](/api-docs/v2/mcp){f' with `kind: "{kind}"`' if name != 'panel' else ''}.
Main arguments stay at the top level; advanced REST parameters go inside `options`.
Use the same identifier and date window as the REST request.

## Read the result

Inspect `data`, `meta.request`, `meta.tier`, and `next_page_url`.
Follow every page before treating a result as complete. `meta.tier_cap_reached`
means partial data; a missing next page does not override it. Empty results and
`null` are not zero. An error is not a data result.

See [pagination and errors](/api-docs/v2/responses) for a complete reading checklist.
'''
            pages.append(slug)
            links.append(f"- [{title}](/{slug}): `{method.upper()} /{name}`" + (f" with `kind={kind}`." if name != "panel" else "."))
        groups.append({"group": GROUPS[name], "expanded": False, "pages": pages})
    files["api-docs/v2/endpoints.mdx"] = '''---
title: "Explore the API"
description: "Find a task, open its preconfigured playground, and query Brazilian financial data."
keywords: ["endpoints", "API", "playground", "data"]
icon: "compass"
---

**Deployed preview.** Browse 74 operations across 14 REST resources. Each operation
has a dedicated page and a playground with its `kind` already selected.
These pages expose the existing API; they do not add data coverage.

<Columns cols={2}>
  <Card title="Historical prices" icon="chart-line" href="/api-docs/v2/operations/prices/history">Query a ticker and a date window.</Card>
  <Card title="Income statements" icon="file-invoice" href="/api-docs/v2/operations/statements/income">Read filed periods for a company.</Card>
  <Card title="Fund holdings" icon="briefcase" href="/api-docs/v2/operations/funds/holdings">Find what a fund holds or who holds a ticker.</Card>
  <Card title="Inflation" icon="chart-column" href="/api-docs/v2/operations/macro/inflation">Read inflation history and components.</Card>
</Columns>

Use the search button to find an operation by name. Open **Try it**, check its
parameters, and select **Send**. Switch between cURL, Python, and JavaScript in the
code panel. Read [authentication](/api-docs/v2/authentication) before adding a key.

## All operations

''' + "\n".join(links) + "\n"
    return files, groups


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    files, groups = artifacts()
    docs_path = ROOT / "docs.json"
    docs = json.loads(docs_path.read_text())
    nav = docs["navigation"]["tabs"][0]["groups"]
    operation_group = {"group": "Browse operations", "pages": groups}
    existing = next((g for g in nav if g["group"] == "Browse operations"), None)
    if args.check:
        stale = [path for path, text in files.items() if not (ROOT / path).exists() or (ROOT / path).read_text() != text]
        if existing != operation_group:
            stale.append("docs.json operation navigation")
        if stale:
            raise SystemExit("Stale generated operation docs: " + ", ".join(stale))
    else:
        for path, text in files.items():
            target = ROOT / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)
        if existing:
            nav[nav.index(existing)] = operation_group
        else:
            nav.insert(len(nav) - 1, operation_group)
        docs_path.write_text(json.dumps(docs, indent=2) + "\n")
    print(f"Checked {len(files)} generated files" if args.check else f"Wrote {len(files)} generated files")


if __name__ == "__main__":
    main()
