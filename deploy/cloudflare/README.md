# Cloudflare: first safe deploy (issue #519)

A Worker named `silo-demo-health` and one health-only Container, deployed to
`https://silo-demo-health.<account subdomain>.workers.dev`. It exists to prove the
Cloudflare path of the portfolio-diagnosis demo (map #510) before any engine,
upload or LLM key goes near it: the API token can deploy a Worker and push a
Container image, the GitHub runner has Docker, the Container starts, and the
access token gate refuses without the token.

| Path                    | Answer                                                                                                                                                                                                                               |
| ----------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `GET /health`           | `200 ok` from the Worker itself, public, no Container                                                                                                                                                                                |
| `GET /container/health` | needs header `x-demo-token: <DEMO_ACCESS_TOKEN>`; `401` without it or with a wrong one, `503` if the secret is unset; with it, the Worker starts (or reuses) the Container and returns `200` when the Container's own `/health` does |
| anything else           | `404`                                                                                                                                                                                                                                |

Files: `wrangler.jsonc` (Worker, Container `lite`, `max_instances` 1,
Durable Object class `HealthContainer` with SQLite storage, `workers_dev` on,
preview URLs off, invocation logs off), `src/index.ts` (routes and token check,
`sleepAfter` 60 s, internet off for the Container), `container/Dockerfile`
(busybox httpd serving one file).

## Deploy

Dispatch **Deploy Cloudflare health** (`.github/workflows/deploy_cloudflare.yml`)
from the Actions tab. It refuses unless the repository secrets
`CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID` and `DEMO_ACCESS_TOKEN` exist,
runs `wrangler deploy` with the pinned wrangler of `package-lock.json`, copies
`DEMO_ACCESS_TOKEN` into the Worker as a secret, and then checks the live
address, printing status codes only: `/health` 200, `/container/health` 401
without the token and with a wrong one, an unknown path 404, and
`/container/health` 200 with the token (retried for up to about 7 minutes of
cold start). A merge deploys nothing.

To check the Worker and bundle offline: `npm ci && npx wrangler deploy --dry-run
--containers-rollout=none` in this directory (a full dry run needs Docker).

## Deliberately absent

- The portfolio engine, the upload page and any upload route.
- `ANTHROPIC_API_KEY` or any other LLM key: not in the workflow, not in the
  Worker, not in the Container.
- Durable Object storage use, KV, R2, D1, and logging of any request content.
- Egress: the Container runs with internet off; the egress allow-list decided
  on #519 belongs to the engine's deploy.
