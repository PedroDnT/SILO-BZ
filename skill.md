---
name: silo
description: >
  Retrieve and verify Brazilian public financial data through the read-only
  SILO API or MCP v2. Use for prices, company filings, funds, credit, derivatives,
  macro, market positioning, events and research panels.
---

# SILO v2 for agents

## Connect and make the first call

1. Use the [v2 quickstart](https://octo-98895abd.mintlify.site/api-docs/v2/quickstart.md) or the [documentation index](https://octo-98895abd.mintlify.site/llms.txt). For tool use, connect via Streamable HTTP to `https://zcjbtpxuhdekpwcxmepn.supabase.co/functions/v1/silo-mcp-v2`, then call `tools/list`. The docs MCP at `https://octo-98895abd.mintlify.site/mcp` searches documentation.
2. If using REST, start at `https://zcjbtpxuhdekpwcxmepn.supabase.co/functions/v1/silo-api/v2`. The index lists available resources. `GET /<resource>?help=all`, relative to that base, lists parameters, defaults and supported kinds. For metric definitions and applicability, use `GET /coverage?kind=catalog` or `silo_coverage({"kind":"catalog"})`. Use the gateway's help and tool schemas for v2 request parameters and defaults.
3. Try `silo_search({"q":"petrobras"})` or `GET /search?q=petrobras` without a credential. Choose the identifier that matches the intended entity before fetching its data.

## Credentials

Anonymous access works without a key and has lower ceilings. For authenticated access, ask the user to sign in at [SILO sign-in](https://silo-bz-deloslabs.vercel.app/signin.html) and configure their Supabase Auth user access token as `Authorization: Bearer <access token>` in the REST or MCP client. Send it only to the SILO function URLs above. Keep it out of prompts, logs, URLs and committed configuration. An expired or invalid bearer is rejected on data calls. Ask for a fresh token if authentication fails, and check `meta.tier` to confirm the access level when a call succeeds. Pro access is granted separately.

The following **public publishable key** is retained for legacy v1 clients and compatibility checks. For v1 it goes in the `apikey` header. The v2 gateway does not need it.

```text
apikey: sb_publishable__yfFQsykAglrvc9GS6_PYw_B24ex437
```

## Answer a research question

1. **Resolve the entity.** Use `silo_search` for names and identifiers. Check the match and the resource's accepted identifier type. Preserve uncertainty if the input is ambiguous.
2. **Check coverage.** Use `silo_coverage` with the relevant dataset before claiming freshness, and compare the requested window with `data_through` and `complete_through`. Check metric applicability before interpreting a missing field. For point-in-time queries, check whether the resource supports `as_of`.
3. **Fetch and continue.** Select the resource and `kind`, inspect the applied parameters in `meta.request`, then follow all relevant pages within the task's scope. In REST follow `next_page_url`; in MCP extract its `cursor` and pass it alone to the same tool. A tier cap makes a result partial. For `over_limit`, narrow the request using the error guidance. For `429`, respect `Retry-After` when supplied. If a first result is empty, check the identifier, coverage, date window and related resource before concluding that the answer is unavailable.
4. **Calculate and cite.** Compute ratios, ranks and other derived results locally. State units, period and adjustments. Preserve nulls and gaps, and never invent an observation or an identifier match. Cite the request or tool arguments, the source and retrieval date, and available provenance such as `meta.endpoint`, `landed_at` or a source document link. If evidence is still incomplete, say what you checked and what prevents an answer.

For research conventions, see the [v2 researcher guide](https://octo-98895abd.mintlify.site/api-docs/v2/researchers.md). For existing PostgREST integrations, see the [v1 quickstart](https://octo-98895abd.mintlify.site/api-docs/quickstart.md).
