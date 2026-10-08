# Source-backed input collection and replay

This completes the **local adapter** from retained sources to seven input
components. It does not activate production ingestion, certify PIT/financial
conventions, accept a protocol or manufacture elapsed development history.
Use it after the separately approved credit canary; do not confuse a prepared
query or synthetic rehearsal with a real archived signal.

## FCA evidence already available at the source

The existing FCA dataset ZIP includes three relevant members: the document
index, `geral`, and `valor_mobiliario`. The warehouse still contains only the
securities projection and cannot establish zero-equity filings by itself.
`fca_sources.py` reuses the existing field map and validators locally, without
adding a warehouse dataset, mapping table or changing the FCA ingestor.

On 08/10/2026, the public 2026 ZIP was fetched through the existing CVMFetcher
into ignored local evidence. It has **361,734 bytes**, 1,003 document-index rows,
676 general rows and 964 securities rows. SHA-256:
`21d4bb18fb6923cf2253c2a1d76496ef71366287fbde5ca725d76f303a2069b8`.
All 26 reviewed full CNPJs have their selected latest indexed document in `geral`;
the adapter derives 32 equity/unit rows. None of those 26 selected documents has
zero equities in this copy. There are general filings without securities elsewhere
in the source; synthetic tests cover zero-equity selection explicitly.

For each exact scoped CNPJ, select the latest `(reference date, version)` from
the full index before joining content. Require the exact indexed document ID in
`geral`, reject ambiguous equal ranks, unindexed securities and malformed keys.
Only then count all published equity/unit rows in that filing. A newer indexed
document missing content is an error, never an empty filing or an older fallback.
An absent issuer requires retained earlier-year evidence or a blocker; no CNPJ
root, parent stock, guarantor or name substitution is permitted.

`complete=true` means the selected filing's published export has been reconciled
inside these retained bytes. It remains a **CVM source-completeness attestation**,
not independent assurance that CVM omitted nothing. `DT_RECEB` is a filing receipt
date; all projected rows use the actual ZIP observation receipt as `fetched_at`.
No January/July knowledge is inferred from a ZIP retrieved in October.

## Operator path

Retain the full ZIP and an actual receipt with `source_url`, `sha256`,
`read_started_at`, `read_finished_at`, `source_observed_at`. The source URL must
match the official FCA yearly URL. Never type an earlier observation timestamp.
Use the existing CVMFetcher for acquisition; cached bytes need their original
observation evidence, not a fresh timestamp asserted as a fresh remote response.
The locally retained copy above is sufficient for adapter preparation, not a
certificate of source freshness for every subsequent signal.

Build the identity component from already collected evidence:

```bash
.venv/bin/python -m research_examples.debenture_equity.fca_sources \
  --zip .context/fca-source-inspection-2026-10-08/source.zip \
  --receipt .context/fca-source-inspection-2026-10-08/receipt.json \
  --year 2026 --links research_examples/debenture_equity/reviewed_links.json \
  --signal-date 2026-10-08 --output .context/fca-identity-2026-10-08.json
```

The CLI accepts one source year; the `derive_identity` interface accepts one
retained vintage per explicitly supplied year. It embeds exact ZIP bytes/base64,
hash and receipt alongside selected index/general records and the projection.
Prospective replay reparses those raw bytes and compares the entire derived
identity/census, so changing a ticker and recomputing the row-count hash is refused.

Print the bounded warehouse **SELECT**, then execute it via Supabase MCP:

```bash
.venv/bin/python -m research_examples.debenture_equity.collector query \
  --identity .context/fca-identity-2026-10-08.json \
  --signal-date 2026-10-08 --equity-from 2026-01-02 \
  --cutoff 2026-10-09T10:00:00-03:00
```

The SELECT chooses the latest complete credit capture ending at the signal date,
retains its **entire** raw response, full fact census and audit, and exports all
selected-bond facts across that capture. Numeric credit values are text to preserve
Decimal precision. Per-ticker equity and IBOV responses are capped by the existing
API; sector inputs use the exact signal date. No FCA warehouse timestamps are
used to authenticate source vintages. No source writes or schema calls occur.

The query ran read-only on 08/10 for syntax/current coverage: **5,790 equity rows,
192 IBOV rows, 43 sector rows, zero credit captures for 08/10**. These are preliminary
counts, not a complete or archived observation. The absent credit capture blocks
collection; the pending production canary is still required. Do not reuse this
pre-canary response as though it included later ingested credit.

Retain the returned `components` object, without MCP wrappers. Split its four
component values into separate exact JSON files and attach their actual query/read
receipts. Supply the FCA component above and a separately verified cash-calendar
component covering equity warmup, the signal and its next scheduled cash session.
COTAHIST supplies past-session evidence; the annual B3 calendar establishes the
scheduled next session. Keep the evidence used to resolve exceptional closures.

The collection request is the existing snapshot request shape, with six source
components (all `snapshots.COMPONENTS` except `frozen_model_and_feature_manifest`):

```json
{
  "signal_date": "2026-10-08",
  "cutoff_at": "2026-10-09T10:00:00-03:00",
  "protocol_sha256": "<externally pinned protocol fingerprint>",
  "links_sha256": "<externally pinned links fingerprint>",
  "components": {
    "<each of the six source component names>": {
      "path": "<retained component file>",
      "sha256": "<SHA256 of exact file bytes>",
      "source_observed_at": "<actual source observation>",
      "read_started_at": "<actual read start>",
      "read_finished_at": "<actual read finish>"
    }
  }
}
```

Then, before the real next-session cutoff:

```bash
.venv/bin/python -m research_examples.debenture_equity.collector seal \
  --request .context/cutoff-request-2026-10-08.json \
  --protocol research_examples/debenture_equity/prospective_protocol_v3.json \
  --destination .context/cutoff-input-2026-10-08 --max-bytes 100000000
```

The explicit protocol file must match the externally pinned hash. V3 here is a
candidate used for technical rehearsal, not protocol acceptance/activation;
existing V2/defaults remain unchanged. Request/link acceptance must precede
outcomes before an archive becomes an accepted research observation.

The collector verifies six hashes/receipt times, requires retained FCA raw source
evidence and a nonempty complete credit capture, computes the frozen features,
writes the seventh component exclusively, calls the existing deadline-bound
archive helper, and replays the sealed archive against the external protocol.
Partial source/feature/archive files are never overwritten. The 100 MB component
budget excludes originals, feature staging, manifest/receipt overhead and durable
retention costs. Receipt metadata and source completeness remain attestations.

The synthetic end-to-end test seals/replays one eligible signal and rejects
source-byte tampering. The real FCA adapter and read-only SELECT have been checked
separately, but **no real seven-component cutoff archive or production canary has
been completed**. Return conventions, dated issuer changes, calendar/close-time
acceptance, externally accepted inventory/root, production approval and future
history remain. `strict_pit_certified` stays false.

The reviewed bond links currently end on 06/10. A rehearsal for 08/10 may
produce an empty feature panel until dated identity coverage is reviewed; such
a panel does not establish an eligible prospective development observation.
