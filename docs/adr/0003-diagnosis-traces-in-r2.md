# 0003. Diagnosis traces, with portfolio data, are kept in a private R2 bucket

Date: 2026-10-05. Status: accepted (owner decision). Amends [ADR 0001](0001-stateless-portfolio-analysis.md)
for the diagnosis demo on Cloudflare (`deploy/cloudflare/`).

## Decision

Every portfolio diagnosis writes a trace of its run to the private Cloudflare R2
bucket `silo-diagnosis-traces`, to improve the agents (Redator, Revisor) later:

- an OTLP/JSON trace following the OpenTelemetry GenAI semantic conventions
  (pinned in `src/portfolio/trace.py`, `GENAI_SEMCONV`), and, as separate objects
  named by SHA-256, the engine JSON and the PDF. The trace **does** contain
  portfolio data; the owner accepted that it is sensitive.
- Holder, CPF and account are masked in all of it: the statement readers replace
  them with fixed tokens before the engine runs (`src/portfolio/mask.py`).
- The **original uploaded statement is never stored**, in R2 or anywhere else.
- No application-level encryption (R2 encrypts at rest). No retention lock and no
  lifecycle rule until there is a paying client.
- The bucket is private; only the Worker writes it, through its binding.
- Supabase stays without portfolios: ADR 0001's consequences for the warehouse
  are unchanged.

## Why

Improving the narrative agents needs real runs to look at: what the engine
found, what the Redator wrote, what the Revisor removed and why. Masked engine
JSON and the PDF carry that; the uploaded file adds nothing the engine JSON does
not, and it is the one object that holds the unmasked holder.

## When to revisit

- When a paying client arrives: retention period, deletion on request, and
  whether to encrypt at the application level.
- If the product becomes advisory: CVM Resolução 19/2021 requires working papers
  to be kept for at least five years, which would turn "no retention lock" into a
  minimum retention.
- LGPD: storage of personal data must end when its purpose ends (art. 16), and
  the controller must protect it with security measures (art. 46). Masking keeps
  the direct identifiers out, but a portfolio can still identify a person; the
  purpose (agent improvement) and its end date should be written down with the
  retention decision above.

## Consequences

- `deploy/cloudflare/wrangler.jsonc` binds `TRACES`; the deploy workflow creates
  the bucket and checks, with a marked synthetic statement, that the marker and
  the upload's bytes are not stored.
- The engine keeps one run's bundle in memory until the Worker reads it once
  (`GET /trace/<id>`, bearer token); the upload page tells the user what is kept.
- Human labels on a run go to `feedback/<trace_id>.json` (convention in
  `deploy/cloudflare/README.md`).
