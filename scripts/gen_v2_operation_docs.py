"""Generate operation playgrounds and SDK contract from the shared operation definitions.

Run after gen_openapi_v2.py. --check checks every generated artifact and navigation.
The gateway reads the same definitions. Published documentation URLs stay stable.
"""
from __future__ import annotations

import argparse
import copy
import json
import re
from pathlib import Path

from scripts.gen_openapi_v2 import ROOT, build, load_registry, load_error_codes

def artifacts():
    registry = load_registry()
    base = build(registry, load_error_codes())
    definitions = json.loads((ROOT / "supabase/functions/silo-api/operations.json").read_text())
    files, groups, links = {}, [], []
    all_paths = {}
    for definition in definitions:
        name, kind = definition["resource"], definition["kind"]
        method, path = definition["method"].lower(), definition["path"]
        title, detail = definition["title"], definition["description"]
        slug = f"api-docs/v2/operations/{name}/{kind}"
        spec_path = f"api-docs/v2/specs/{name}-{kind}.json"
        spec = copy.deepcopy(base)
        op = spec["paths"][f"/{name}"][method]
        spec["paths"] = {path: {method: op}}
        op.update(operationId=f"v2_{name}_{kind}", summary=title, description=detail)
        op["x-mint"] = {"href": f"/{slug}"}
        op["parameters"] = [
            {"name": p["name"], "in": "query", "required": p["required"],
             "description": p["description"], "schema": p["schema"],
             **({"example": p["example"]} if "example" in p else {})}
            for p in definition["parameters"]
        ] + [{"name": "details", "in": "query", "required": False,
              "description": "Include request diagnostics.", "schema": {"type": "boolean", "default": False}}]
        if definition["body"]:
            old = op["requestBody"]["content"]["application/json"]["schema"]["properties"]
            props = {b["name"]: {**old[b["target"]], "description": b["description"]} for b in definition["body"]}
            required = ["names"] if kind == "resolve" else [b["name"] for b in definition["body"] if b["target"] == "id"]
            op["requestBody"]["content"]["application/json"] = {"schema": {"type": "object", "properties": props, "required": required, "additionalProperties": False}}
        meta = spec["components"]["schemas"]["Envelope"]["properties"]["meta"]
        meta["required"] = ["tier"]
        for key in ["resource", "kind", "request", "endpoint", "id_known"]:
            meta.get("properties", {}).pop(key, None)
        files[spec_path] = json.dumps(spec, indent=2, ensure_ascii=False) + "\n"
        all_paths[path] = {method: op}
        files[f"{slug}.mdx"] = f'''---
title: {json.dumps(title)}
description: {json.dumps(detail)}
keywords: [{json.dumps(name)}, {json.dumps(kind)}, "API", "MCP"]
openapi: "{spec_path} {method.upper()} {path}"
---

{detail}

[Python DataFrames](/api-docs/v2/python) · [Pagination and errors](/api-docs/v2/responses) · [Agent setup](/api-docs/v2/mcp)
'''
        if path == "/macro/series":
            choices = next(p["choices"] for p in definition["parameters"] if p["name"] == "series")
            page = files[f"{slug}.mdx"]
            page = re.sub(r'openapi: [^\n]+\n', "", page)
            page = page.replace(detail + "\n\n", "`GET /macro/series`\n\n", 1)
            page += '\nimport { SeriesQuery } from "/snippets/series-query.jsx";\n\n'
            page += '<SeriesQuery choices={' + json.dumps(choices, ensure_ascii=False) + '} />\n'
            page += '\n[Request and response schema](/api-docs/v2/specs/macro-series.json)\n\n<Accordion title="Series codes and units">\n\n'
            page += "\n".join(f"- `{c['value']}`: {c['label']}." for c in choices)
            page += '\n\n</Accordion>\n'
            files[f"{slug}.mdx"] = page
        group = next((g for g in groups if g["group"] == definition["group"]), None)
        if group is None:
            group = {"group": definition["group"], "expanded": False, "pages": []}
            groups.append(group)
        group["pages"].append(slug)
        links.append(f"- [{title}](/{slug}): `{method.upper()} {path}`.")
    combined = copy.deepcopy(spec)
    combined["paths"] = all_paths
    files["api-docs/v2/operations-openapi.json"] = json.dumps(combined, indent=2, ensure_ascii=False) + "\n"
    files["sdk/silo_client/operations.json"] = json.dumps(definitions, indent=2, ensure_ascii=False) + "\n"
    files["api-docs/v2/endpoints.mdx"] = '''---
title: "Explore the API"
description: "Find a task, open its preconfigured playground, and query Brazilian financial data."
keywords: ["endpoints", "API", "playground", "data"]
icon: "compass"
---

**Deployed preview.** Browse 74 operations across 14 REST resources. Each operation
has a dedicated route with task-specific inputs.
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
    start, end = "<!-- BEGIN V2 OPERATIONS -->", "<!-- END V2 OPERATIONS -->"
    entries = [link.replace("](/", "](https://octo-98895abd.mintlify.site/").replace("): `", ".md): `") for link in links]
    block = start + "\n## v2 operations\n\n" + "\n".join(entries) + "\n" + end
    index = (ROOT / "llms.txt").read_text()
    if start in index:
        index = index[:index.index(start)] + block + index[index.index(end) + len(end):]
    else:
        index = index.replace("## Existing v1 integrations", block + "\n\n## Existing v1 integrations")
    files["llms.txt"] = index
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
