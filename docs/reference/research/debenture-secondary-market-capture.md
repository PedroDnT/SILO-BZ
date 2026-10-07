# Debenture secondary-market capture: first implementation

This is the B3 observation seam of #662, under [ADR 0004](../../adr/0004-debenture-market-data-sources.md).
It implements capture, validation, retrieval vintages and operator entrypoints.
It is **not deployed and not a research-ready bond→equity dataset**. Two real
one-day exports passed the parser; daily capture remains opt-in. #628 remains a research issue;
this implementation follows the owner's subsequent request to begin building.

## Sources and evidence

The [B3 classifications catalog](https://arquivos.b3.com.br/bdi/table/classifications?lang=pt-br),
read on 2026-10-06 (UTC-3), identifies `ConsolidatedRecords` as Negociação
consolidada, formerly Registros consolidados, with `limitDate = M-18`. It links
dates before 2025-12-11 to [HistoricoRF](https://drp.b3.com.br/Web/HistoricoRF),
described as definitive negotiations by **asset type**. The instrument-level
depth of that legacy history remains unverified; M-18 alone is not proof that
eighteen months of individual-bond observations can be exported.

B3's [Negociação Consolidada glossary, 15/12/2025](https://www.b3.com.br/data/files/E0/10/B2/EB/8E2AB9109B5E99B9AC094EA8/Glossario_Negociacao_Consolidada_balcao.pdf)
defines DEB coverage, grouping by instrument code, settlement date and trade
classification, and the fields below. It says the file is published at the
day's close. Its reference PU may be B3 mark-to-market, while the last PU is
instrument-wide and independent of the row's grouping. Consolidated registrations
can differ from the trade-by-trade file; never add the two as disjoint volumes.

The existing `B3BdiFetcher.fetch_table` is reused, including retry/HTML rejection
and its typed empty response. A public one-day export for 2026-10-05 timed out
after 45 seconds and again after 120 seconds on 2026-10-06 (UTC-3).
On 2026-10-07 (UTC-3), two real exports succeeded through the existing fetcher:

| Session | All source rows | DEB groups | Distinct DEB codes | Dropped rows | Decoded UTF-8 bytes |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2026-10-06 | 167,668 | 1,467 | 775 | 0 | 20,690,933 |
| 2025-12-11 | 3,283 | 1,349 | 821 | 0 | 563,275 |

Both exports delivered only their requested session and passed the unchanged
parser. The actual header places `Código IF` before `Instrumento financeiro` and
uses sentence case; a regression test applies that exact header to synthetic
values. The recent file contains `-`, `EXTRAGRUPO` and `INTRAGRUPO`; all DEB groups
have ISIN and the eight non-oscillation metrics, while 370 lack oscillation.
Its 1,467 groups produce 13,203 long facts. These are source observations, not
validated issuer/equity links or a count of listed companies.

Decoded-payload SHA-256: recent `51c863fe610712779ef8283fd2715a9550c6e4c4e802d640a838e81350066184`;
older `ba1c24a57165b7107b0957db7db1d2e9cdaea9d3908e952cb6ac4ae3086973ad`.
The full exports remain in ignored local `.context/`, with no production writes
or committed market rows. The CSV fixture in `tests/fixtures/b3_credit/` remains
synthetic. Two successful dates verify those dates only: continuity, legacy
depth, revision frequency and original publication times remain unverified.

## Stored contract

| Object | Grain | Meaning |
| --- | --- | --- |
| `b3_credit_capture` | One retrieval, keyed by its ingest-log `capture_id`/`run_id` | Requested dates, response arrival time `observed_at`, decoded CSV, UTF-8 payload hash, source URL, session census and `captured`/`incomplete`/`complete` status |
| `fact_credit_market` | Capture × original instrument code × trade date × settlement date × classification × metric | Long DEB observations, with optional original ISIN/issuer name and a complete source-row hash |

Metrics: `quantity` (units), `trade_count` (trades), `volume_brl` (BRL),
`min_price`, `avg_price`, `max_price`, `last_price`, `reference_price` (BRL/unit),
and `oscillation_pct` (percent). A blank source value remains NULL. Prices must
be positive when present; quantities/counts/volume non-negative; count integral.
Every position passes `DataValidator`; invalid rows are dropped and counted.
Both tables remain private, with RLS enabled and client grants revoked.
Migration 74 and `schema.sql` carry the same definition. There is no new API
endpoint, catalog entry or raw-data redistribution.

The parser discovers columns by labels and supports reordered/quoted CSV fields.
Identical duplicate rows collapse; conflicting rows sharing a natural grouping
raise. It retains every classification, including `-`; it never converts missing
classification into extragroup. Unknown headers refuse rather than guessing.

Group-specific quantity/count/volume can be summed across disjoint source groups.
`last_price` and `reference_price` repeat across groups and must **not** be summed
or repeatedly weighted as independent quotes. An average of averages also needs
compatible source weights. No yield, coupon, issuer CNPJ, obligor, outstanding,
bond total return or equity mapping is inferred here.

## Completeness, revisions and point-in-time

The bounded COTAHIST cash-session calendar is compared with dates delivered for
**all source instruments before filtering DEB**. A session with other instruments
and zero DEB rows is a delivered day with no debenture observations. A missing
date or typed empty export for known sessions is unresolved availability, not
proof of zero trades. This is a cross-market calendar check, not an independent
OTC calendar or proof that every trade of a delivered day was published.

Each ingest has one audit identity. After a response arrives, its raw CSV is
saved with status `captured` before parsing. Valid facts land through `pg_client`
in bounded statements. Only after all writes succeed, every expected date is
delivered and no rows were dropped is the capture marked `complete`. Missing
sessions or dropped rows leave `incomplete` and fail the slice, retaining valid
facts and the raw evidence. Parse/DB failure leaves an ineligible `captured`
snapshot and a red audit. Successfully acknowledged batches are counted in the
audit even if a later batch fails.

Replaying rows within the same capture is idempotent. A later HTTP retrieval is
a new vintage, including when the values are unchanged. This intentionally
preserves both revision history and a return from version A to B to A. Storage
therefore grows with each retrieval; raw CSV and historical snapshots currently
have no pruning policy. The recent one-day raw export alone is about 20.7 MB;
weekly overlapping captures can repeat that payload. Measure representative
multi-day payloads and a storage budget before bootstrap or daily enablement.

`observed_at` is SILO's response-arrival time, not B3's original publication
timestamp. A newly downloaded historical file cannot be used as information
known at its original trade date in a strict PIT backtest. The captures support
retrieval-time as-of reads going forward; a retrospective observation-date study
must separately declare its publication-lag and revision assumptions.

For a read at cutoff `:as_of`, select the **whole latest complete capture per
source and trade date before joining facts**. Selecting latest per bond would
resurrect a row removed by a later correction. Example for bounded dates:

```sql
WITH chosen AS (
    SELECT DISTINCT ON (c.source, d.trade_date)
           c.capture_id, c.source, d.trade_date
    FROM public.b3_credit_capture c
    CROSS JOIN LATERAL (
        SELECT value::date AS trade_date
        FROM jsonb_array_elements_text(c.delivered_dates)
    ) d
    WHERE c.status = 'complete'
      AND c.observed_at <= :as_of
      AND c.requested_from <= :to_date AND c.requested_to >= :from_date
      AND d.trade_date BETWEEN :from_date AND :to_date
    ORDER BY c.source, d.trade_date, c.observed_at DESC, c.capture_id DESC
)
SELECT f.*, c.trade_date AS observed_session
FROM chosen c
JOIN public.fact_credit_market f
  ON f.capture_id = c.capture_id AND f.trade_date = c.trade_date
WHERE f.instrument_code = :code
ORDER BY f.trade_date, f.settlement_date, f.trade_classification, f.metric;
```

No eligible capture means unknown at that cutoff. A complete capture with no
DEB rows means no DEB observations in that export. This query does not forward-fill
either state. It keeps the last complete capture if a newer retrieval failed;
callers must inspect the capture/audit history for freshness and failed updates.

## Operator entrypoints

Verify one completed session without DB credentials or writes:

```bash
python -m src.pipeline.b3_credit_pipeline --start 2026-10-05 --end 2026-10-05 --dry-run
```

This reports source/debenture/drop counts, delivered dates and the payload hash;
it does not reconcile a DB calendar and is not a completeness certificate.
For a single persisted range, omit `--dry-run` after migration rollout is approved.
The single-range entrypoint accepts at most 31 calendar days and refuses today's
or future sessions. Dates are computed in America/Sao_Paulo; timestamps are stored
with a time zone as usual.

Historical capture runs alone, with explicit boundaries, in seven-day slices:

```bash
python -m src.pipeline.run_backfill --b3-credit-start 2025-12-11 --b3-credit-end 2026-10-05
```

This is an operator example, not a verified available range. It stops at the
first incomplete slice. Bounded requests replace #662's provisional single
eighteen-month request: a one-day export already timed out, so a large request
would be unmeasured in duration and storage. Earlier/absent sessions are never
silently relabeled as covered.

`B3_CREDIT_ENABLED=1 python -m src.pipeline.run_b3_events` opts the daily B3 step
into the trailing seven completed calendar days, before the corporate-event
sweep. The same code path is used by watchdog recovery. The switch is off by
default pending coverage/storage checks and approved rollout; no production
environment or workflow dispatch was changed. A credit
failure stays red while other B3 sources still run.

Local verification uses offline parser/pipeline/orchestration tests and
`tests/sql/b3_credit_behaviour.sql` (in the existing ephemeral-Postgres CI job).
The SQL test exercises capture replay, A→B→A changes, row removals, knowledge-time
cutoffs, incomplete-capture constraints and private table privileges. An optional
real-`pg_client` test accepts only a loopback database ending in `_test`:

```bash
SILO_TEST_CREDIT_DATABASE_URL=postgresql://silo_test@127.0.0.1:55441/silo_credit_test \
  python -m pytest tests/test_b3_credit.py::test_real_pg_client_writes_capture_dates_facts_and_single_audit -q
```

The test database must already contain migration 74. This is disposable
verification state, never a local warehouse source of truth.

The active acceptance items and later capabilities are tracked once, in
[OPEN_ITEMS item 18](../../planning/OPEN_ITEMS.md#18-debenture-secondary-market-capture-662).
