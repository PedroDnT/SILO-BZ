# Engine image (map #510, slice E step 1)

The portfolio-diagnosis engine (`src/portfolio/`) and its report behind a small
HTTP server, `src/portfolio/server.py`, packed as a container image. Built and
smoke-tested in CI by `engine_image.yml`. **Not deployed:** the Worker in
`deploy/cloudflare/` still runs the health-only Container.

| Route | Answer |
| --- | --- |
| `GET /health` | `200 ok` |
| `POST /diagnose` | the statement as multipart field `file` or as the raw body: the spreadsheet template (`.xlsx`) or a BTG performance report (`.pdf`), at most 10 MB. Needs `Authorization: Bearer <DEMO_ACCESS_TOKEN>`. Returns `application/pdf` |

Errors are JSON `{"erro": "<mensagem em português>"}` with a fixed message per
status: 400 empty upload, 401 missing or wrong token, 413 over 10 MB, 415 neither
xlsx nor PDF, 422 statement unreadable or not reconciling, 502 the report writer
failed (for example no LLM key), 503 `DEMO_ACCESS_TOKEN` unset (every `/diagnose`
is refused), 500 anything else.

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
runs gunicorn, one worker with four threads and a 600 s timeout, as user
`engine` (uid 10001).

## Environment (names only)

| Variable | Use |
| --- | --- |
| `DEMO_ACCESS_TOKEN` | the bearer token `/diagnose` requires; unset means 503 |
| `SILO_LLM_PROVIDER` | `anthropic` (default), `openai` or `fake` (no key, deterministic findings) |
| `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` | the chosen provider's key |
| `SILO_LLM_MODEL`, `SILO_LLM_EFFORT`, `SILO_LLM_FALLBACKS` | model overrides (`src/portfolio/report/llm.py`) |
| `SILO_REPORT_SIGNATURE` | the report's signature line |
| `SILO_ENGINE_CLIENT` | `mcp` (default, the public read-only `silo-mcp`) or `postgrest`; there is no fake SILO client in the server, so canned rows never meet a real statement |
| `PORT` | listen port, default 8080 |

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

## Next (step 2, not in this image's PR)

Point `wrangler.jsonc`'s Container at this Dockerfile with the repository root as
build context, instance type `standard-1`, route the Worker's upload to
`/diagnose`, pass `DEMO_ACCESS_TOKEN` and the LLM key as Worker secrets at
container start, and set the egress allow-list decided on #519.
