# Cloudflare: the portfolio-diagnosis demo (map #510, slice E)

A Worker named `silo-demo-health` (the name of the first safe deploy, #519, kept
so the address and the Container application carry over) and the engine
Container, at `https://silo-demo-health.<account subdomain>.workers.dev`.

| Path             | Answer                                                                                                                                                                                                                                   |
| ---------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `GET /`          | the upload page (Portuguese): access code, statement files (one per account), downloads `diagnostico.pdf`                                                                                                                                                   |
| `GET /health`    | `200 ok` from the Worker itself, public, no Container                                                                                                                                                                                    |
| `POST /diagnose` | the statement (template `.xlsx` or BTG `.pdf`, extrato or performance report; raw body, or one multipart `file` part per account, consolidated; at most 10 MB in all). Token as `x-demo-token` or `Authorization: Bearer`; `401` without it, `503` if the secret is unset, `413` over 10 MB. Returns the engine's answer, plus `x-silo-trace-key`, the R2 key the Worker writes the run's trace to (the upload page links to `/traces#<key>`; the upload page has the same opt-in "Lembrar neste aparelho") |
| `GET /traces`    | the owner's trace page (Portuguese), a static shell with no data: asks for the access code (kept only in that browser's `localStorage`, and only when "Lembrar neste aparelho" is ticked; "Esquecer" clears it; then the runs list on load), lists the stored runs of the last 3, 7 (default), 14 or 30 days (at most 100), opens one run from its own link `/traces#traces/YYYY/MM/DD/<trace_id>.json` (the link holds no token), shows the run's report in HTML (a sandboxed frame, printable), the agents' timeline (each span's start, duration, model, tokens and cost, and what the Revisor removed), what the investigator did and found (its facts with quote, tier, source and document), where an asset's exposure comes from (an arrow diagram, one box per statement line, plus the text) and downloads a run's stored PDF when it has one. Works on a phone |
| `GET /api/traces`, `/api/traces/exposure`, `/api/traces/report`, `/api/traces/agents`, `/api/traces/investigation`, `/api/traces/pdf` | what that page calls; same token as `/diagnose`, `GET` only. Read the private bucket through the `TRACES` binding, only through keys of the two strict shapes `traces/YYYY/MM/DD/<32 hex>.json` and `artifacts/<64 hex>.json`, `.html` or `.pdf`; `no-store`; nothing logged. `report` answers the stored HTML under a policy with no script and no request (`sandbox`) |
| anything else    | `404`                                                                                                                                                                                                                                    |

Each upload gets its own Durable Object, so its own Container instance and disk;
the Worker stops the instance as soon as it has the answer (`sleepAfter` 60 s
covers a client that went away). The Worker forwards the upload with
`Authorization: Bearer` and passes back only the content type, the
attachment name and the engine's `X-Silo-*` headers (narrative status,
provider, cost in US$, seconds, failing stage). Every answer carries
`X-Silo-Origin: worker` or `engine`.

The trace page is the owner's way to read what a run stored without a terminal (the engine JSON and the
PDF hold portfolio data, with holder, CPF and account masked, so they never go through GitHub: the repository is
public). `src/exposure.ts` holds the pure functions; `tests/test_worker_exposure.py` checks that its text is
the same as `scripts/trace_view.py exposure`.

Files: `wrangler.jsonc` (Container `standard-1`, `max_instances` 3, image
`engine/Dockerfile` built from the repository root, LLM defaults as `vars`,
invocation logs off, preview URLs off), `src/index.ts` (routes, token check,
upload page, egress), `engine/` (the image, see its README). `container/` is the
health-only image of the first deploy, no longer referenced.

## Run traces in R2 (ADR 0003)

The uploaded statement is never stored: its bytes are only forwarded to the
Container. What is stored, in the private R2 bucket `silo-diagnosis-traces`
(binding `TRACES`; only this Worker writes it, no public access, no lifecycle
rule), is one trace per run that passed the token check, to improve the agents
later. It holds portfolio data, so treat the bucket as sensitive:

| Key                                  | What                                                                                       |
| ------------------------------------ | ------------------------------------------------------------------------------------------ |
| `traces/YYYY/MM/DD/<trace_id>.json`  | OTLP/JSON trace (`src/portfolio/trace.py`); the date is the write's UTC date               |
| `artifacts/<sha256>.json`            | the engine JSON, holder, CPF and account already masked by the readers (`[TITULAR]` ...)   |
| `artifacts/<sha256>.html`            | the report's HTML, masked like the PDF (every run that reached the report; from 2026-10-06) |
| `artifacts/<sha256>.pdf`             | the PDF that was returned (200 runs that asked for PDF only)                               |
| `feedback/<trace_id>.json`           | reserved for human labels on a run, written by hand later; no code writes it yet           |

The trace's root span names the artifacts by `app.engine_json.sha256`, `app.html.sha256` and
`app.pdf.sha256`. Spans: `invoke_workflow diagnosis` (status, failing stage,
files, formats, bytes, engine revision), `engine.run` (section statuses and
reason codes, identification counts), `invoke_agent redator` / `invoke_agent
revisor` (GenAI semantic conventions, pinned in `GENAI_SEMCONV`: provider,
model, token usage, cost; each Revisor removal is an `app.revisor.removed` event
with a fixed rule code, the section and the SHA-256 of the removed text, never
the text). An error is span status ERROR with `exception.type` only.

Transport: the Container cannot reach R2 (egress allow-list), and a trace with
the engine JSON is too large for a response header. So the engine keeps the
run's bundle in memory (the trace, the engine JSON and the HTML) and names it in `X-Silo-Trace-Id` (never passed to the
client); after answering, the Worker, inside `ctx.waitUntil`, calls `GET
/trace/<id>` on the same instance with the bearer token (answered once, then
forgotten), writes the objects, and only then stops the instance. The PDF is
written from the body the Worker already holds, under its own SHA-256 and only
when it matches the trace's. A Worker-side 503 (no instance) has no trace.

Read them with `scripts/trace_view.py` (from the repository root): `list` prints the keys of the
last days through the R2 REST API (`CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN`, from the environment or the
repository's `.env`), `show <key or file>`
prints one run as a timeline with its sections, agents, tokens, cost and Revisor removals, and `show`
with several prints one row per run. `exposure PETR4 <trace key>` fetches that run's engine JSON and prints where the
asset's exposure comes from (direct, and through each fund with its CDA month); `exposure PETR4 engine.json` does the
same for a local engine file. Keep downloaded traces out of the repository.

`feedback/<trace_id>.json` convention: one JSON object per labelled run,
`{"trace_id", "labeled_at" (ISO date), "labeler", "verdict" ("good" | "bad" |
"mixed"), "findings": [{"finding_id", "label", "note"}], "note"}`. Labels refer
to findings by id; they never copy portfolio data.

## Secrets and egress

`DEMO_ACCESS_TOKEN` and `OPENAI_API_KEY` are Worker secrets, copied from the
repository secrets by the deploy, and handed to the Container as environment
variables at start with `SILO_LLM_PROVIDER=openai`, `SILO_LLM_MODEL=gpt-5.1`,
`SILO_LLM_EFFORT=medium`. The US$1.00 cost cap per report is in the engine
(`COST_CAP_USD`, `src/portfolio/report/llm.py`). `EXA_API_KEY` (engine 1.12,
#605) is copied the same way; with `SILO_INVESTIGATOR=on` (a var) the engine's
investigator reads Fundos.NET, RAD and, as its fallback, Exa, and the public
documents it read go to R2 with the trace as `docs/<source>/<id>/<sha256>.txt`.
The var is `off` (owner, #605 Q37): the owner turns it on after one supervised
live run. Its spend is inside the same US$1.00 cap (at most US$0.30 of it) and in
`X-Silo-Cost-Usd`.

Egress (`EGRESS` var): `allowlist` (default) starts the Container with internet
off and lets out only `zcjbtpxuhdekpwcxmepn.supabase.co` (silo-mcp),
`api.openai.com` and the investigator's sources `fnet.bmfbovespa.com.br`,
`www.rad.cvm.gov.br` and `api.exa.ai`, through `@cloudflare/containers`' `allowedHosts` with
`interceptHttps`. HTTPS is then terminated by the platform's proxy, whose CA the
image trusts at start (`engine/start.sh`). `open` turns the internet on instead.

## Deploy

Dispatch **Deploy Cloudflare demo** (`.github/workflows/deploy_cloudflare.yml`).
It refuses unless `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`,
`DEMO_ACCESS_TOKEN`, `OPENAI_API_KEY` and `EXA_API_KEY` exist, deploys with an immediate
Container rollout, and then checks the live address, printing status codes,
sizes, timings and the cost header only: `/health` 200, `/` the page, `/diagnose`
401 without a token and with wrong ones, an unknown path 404, then two real
reports from the synthetic template (200, `application/pdf`, `%PDF-`, provider
`openai`, narrative `complete`), the second one with a marker in the holder name
and the file name while `wrangler tail` listens; the marker must not appear.
It then finds that run's trace in R2 (listed through the R2 REST API, matched by
size and format) and fails if the marker or the upload's bytes are in the trace
or the engine JSON, if the holder is not `[TITULAR]`, or if any object is stored
under the upload's own SHA-256. Before deploying it creates the bucket when
missing (the API token needs Workers R2 Storage: Edit).
A merge deploys nothing.

Offline check: `npm ci && npx wrangler deploy --dry-run --containers-rollout=none`
in this directory (a full dry run builds the image and needs Docker).

## Status (2026-10-04)

Deployed; `/health`, the page, the 401s and the 404 pass, and the engine reaches
silo-mcp and api.openai.com through the allow-list. The report was blocked by
OpenAI's 403 `model_not_found` for `gpt-6-luna` on the key in `OPENAI_API_KEY`
(every gpt-6 model is refused for that key), so the owner switched the model to
`gpt-5.1` on 2026-10-04 (`docs/planning/OPEN_ITEMS.md` item 15). Run 37226627623
produced a complete report, but the marked second one came back with narrative
`unknown`, so the run failed before the privacy probe. The response now carries
`X-Silo-Narrative-Reason` (an error class name or `revisor_removed_all`, never
the message) and `X-Silo-Llm-Calls` (`role:out=N:reasoning=N` per call), and the
smoke runs the privacy probe before failing on the marked report.
Run 37230811125 read those headers: `LLMOutputError`, `redator:out=16000:reasoning=11091`,
so gpt-5.1's reasoning used most of the 16,000-token output limit and the reply was
cut. The OpenAI provider's limit is 32,000 since (owner's choice, 2026-10-04).

## Not covered

- Workers Logs (persisted) cannot be searched from the workflow; the tail probe
  covers the live stream only.
- No custom domain, no rate limit beyond the token, `max_instances` and the
  provider's spend limit.

The upload UI requests HTML, shows the brief and optional declared client constraints, and uses the browser print/save dialog only on request. API PDF callers remain supported; HTML-only traces have no PDF artifact. See `docs/reference/portfolio/brief-client-fit.md`.
