# Cloudflare: the portfolio-diagnosis demo (map #510, slice E)

A Worker named `silo-demo-health` (the name of the first safe deploy, #519, kept
so the address and the Container application carry over) and the engine
Container, at `https://silo-demo-health.<account subdomain>.workers.dev`.

| Path             | Answer                                                                                                                                                                                                                                   |
| ---------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `GET /`          | the upload page (Portuguese): access code, statement files (one per account), downloads `diagnostico.pdf`                                                                                                                                                   |
| `GET /health`    | `200 ok` from the Worker itself, public, no Container                                                                                                                                                                                    |
| `POST /diagnose` | the statement (template `.xlsx` or BTG `.pdf`, extrato or performance report; raw body, or one multipart `file` part per account, consolidated; at most 10 MB in all). Token as `x-demo-token` or `Authorization: Bearer`; `401` without it, `503` if the secret is unset, `413` over 10 MB. Returns the engine's answer |
| anything else    | `404`                                                                                                                                                                                                                                    |

Each upload gets its own Durable Object, so its own Container instance and disk;
the Worker stops the instance as soon as it has the answer (`sleepAfter` 60 s
covers a client that went away). The Worker forwards the upload with
`Authorization: Bearer` and passes back only the content type, the
attachment name and the engine's `X-Silo-*` headers (narrative status,
provider, cost in US$, seconds, failing stage). Every answer carries
`X-Silo-Origin: worker` or `engine`.

Files: `wrangler.jsonc` (Container `standard-1`, `max_instances` 3, image
`engine/Dockerfile` built from the repository root, LLM defaults as `vars`,
invocation logs off, preview URLs off), `src/index.ts` (routes, token check,
upload page, egress), `engine/` (the image, see its README). `container/` is the
health-only image of the first deploy, no longer referenced.

## Secrets and egress

`DEMO_ACCESS_TOKEN` and `OPENAI_API_KEY` are Worker secrets, copied from the
repository secrets by the deploy, and handed to the Container as environment
variables at start with `SILO_LLM_PROVIDER=openai`, `SILO_LLM_MODEL=gpt-5.1`,
`SILO_LLM_EFFORT=medium`. The US$1.00 cost cap per report is in the engine
(`COST_CAP_USD`, `src/portfolio/report/llm.py`).

Egress (`EGRESS` var): `allowlist` (default) starts the Container with internet
off and lets out only `zcjbtpxuhdekpwcxmepn.supabase.co` (silo-mcp) and
`api.openai.com`, through `@cloudflare/containers`' `allowedHosts` with
`interceptHttps`. HTTPS is then terminated by the platform's proxy, whose CA the
image trusts at start (`engine/start.sh`). `open` turns the internet on instead.

## Deploy

Dispatch **Deploy Cloudflare demo** (`.github/workflows/deploy_cloudflare.yml`).
It refuses unless `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`,
`DEMO_ACCESS_TOKEN` and `OPENAI_API_KEY` exist, deploys with an immediate
Container rollout, and then checks the live address, printing status codes,
sizes, timings and the cost header only: `/health` 200, `/` the page, `/diagnose`
401 without a token and with wrong ones, an unknown path 404, then two real
reports from the synthetic template (200, `application/pdf`, `%PDF-`, provider
`openai`, narrative `complete`), the second one with a marker in the holder name
and the file name while `wrangler tail` listens; the marker must not appear.
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
