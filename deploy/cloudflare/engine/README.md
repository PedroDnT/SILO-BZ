# Engine image (map #510, slice E step 1)

The portfolio-diagnosis engine (`src/portfolio/`) and its report behind a small
HTTP server, `src/portfolio/server.py`, packed as a container image. Built and
smoke-tested in CI by `engine_image.yml`, and deployed as the Container of the
Worker in `deploy/cloudflare/` by `deploy_cloudflare.yml` (slice E step 2).

| Route | Answer |
| --- | --- |
| `GET /health` | `200 ok` |
| `POST /diagnose` | the statement as multipart field `file` or as the raw body: the spreadsheet template (`.xlsx`) or a BTG performance report (`.pdf`), at most 10 MB. Needs `Authorization: Bearer <DEMO_ACCESS_TOKEN>`. Returns `application/pdf` with `X-Silo-Narrative`, `X-Silo-Provider`, `X-Silo-Cost-Usd` and `X-Silo-Seconds` |

Errors are JSON `{"erro": "<mensagem em português>"}` with a fixed message per
status: 400 empty upload, 401 missing or wrong token, 413 over 10 MB, 415 neither
xlsx nor PDF, 422 statement unreadable or not reconciling, 502 the report writer
failed (for example no LLM key), 503 `DEMO_ACCESS_TOKEN` unset (every `/diagnose`
is refused), 503 with `Retry-After` and `X-Silo-Error: silo_unavailable` when SILO
did not answer while the lines were identified (a timeout, 5xx or network error
still failing after the engine's one retry; no PDF, retry later), 500 anything else. An error names the step that refused in
`X-Silo-Stage` (`auth`, `upload`, `read`, `engine`, `report`, `pdf`).

## Build and run locally

From the repository root (the build context must be the root; the whitelist in
`Dockerfile.dockerignore` sends only `src/portfolio/` and the requirements):

```bash
docker build -f deploy/cloudflare/engine/Dockerfile -t silo-engine .
docker run --rm -p 8080:8080 -e DEMO_ACCESS_TOKEN -e SILO_LLM_PROVIDER=fake silo-engine
curl localhost:8080/health
curl -H "Authorization: Bearer $DEMO_ACCESS_TOKEN" \
     --data-binary @docs/reference/portfolio/statement-template.xlsx \
     -o diagnostico.pdf localhost:8080/diagnose
```

Without Docker: `pip install -r requirements.txt -r requirements-report.txt`, then
`python -m src.portfolio.server` (Flask's server on `0.0.0.0:$PORT`). The image
runs `start.sh`: gunicorn, one worker with four threads and a 600 s timeout, as
user `engine` (uid 10001). `SSL_CERT_FILE` points at a private copy of certifi's
roots; with `SILO_TRUST_CF_CA=1` (set by the Worker when egress is allow-listed)
the Cloudflare egress CA is added to it as soon as the platform writes it.

## Environment (names only)

| Variable | Use |
| --- | --- |
| `DEMO_ACCESS_TOKEN` | the bearer token `/diagnose` requires; unset means 503 |
| `SILO_LLM_PROVIDER` | `anthropic` (default), `openai` or `fake` (no key, deterministic findings) |
| `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` | the chosen provider's key |
| `SILO_LLM_MODEL`, `SILO_LLM_EFFORT`, `SILO_LLM_FALLBACKS` | model overrides (`src/portfolio/report/llm.py`) |
| `SILO_LLM_EFFORT_REDATOR`, `SILO_LLM_EFFORT_REVISOR` | effort for one role; wins over `SILO_LLM_EFFORT` (unset by default) |
| `SILO_REPORT_SIGNATURE` | the report's signature line |
| `SILO_ENGINE_CLIENT` | `mcp` (default, the public read-only `silo-mcp`) or `postgrest`; there is no fake SILO client in the server, so canned rows never meet a real statement |
| `PORT` | listen port, default 8080 |
| `SILO_TRUST_CF_CA` | `1` trusts `/etc/cloudflare/certs/cloudflare-containers-ca.crt` (HTTPS egress interception on Cloudflare) |

The engine reads SILO with the public publishable key only; no database secret
is needed.

## Privacy

- The upload stays in memory. The xlsx reader and the PDF renderer use a private
  temporary directory deleted in a `finally` block; the PDF statement reader
  feeds `pdftotext` on stdin.
- Log lines carry status, stage, format, byte sizes, timings, narrative status,
  provider and cost. Never the file, its name, the holder, the CPF or the account,
  and never a traceback: exceptions are logged by type name only. The engine masks
  the holder before anything else sees the statement.
- Error answers are fixed messages; nothing of the request is echoed.
