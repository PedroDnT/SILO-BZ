# Planning

## Live

| Doc                              | Is                                                  | Open                                                         |
| -------------------------------- | --------------------------------------------------- | ------------------------------------------------------------ |
| [SERVING.md](SERVING.md)         | The serving roadmap, step by step                   | Step 8 (widen the panel) — everything else done or obsoleted |
| [INSTRUMENTS.md](INSTRUMENTS.md) | How each B3 instrument class is ingested and served | Design reference, no queue                                   |
| [SDK.md](SDK.md)                 | What `sdk/silo_client` is today and what is missing | pandas dependency, PyPI, wheel CI, async                     |
| [CHANGELOG.md](CHANGELOG.md)     | Append-only log, one row per merged branch          | —                                                            |

## Known gaps, not in any queue

Things that are missing or provisional rather than broken, recorded so a reader
does not have to rediscover them. Verified 2026-09-18 unless the row says
otherwise.

| Gap | Why it matters | State |
| --- | --- | --- |
| The docs site is on Mintlify's generated subdomain, `octo-98895abd.mintlify.site` | It works, but a hex-string hostname reads as provisional. A custom domain needs a DNS record and a Mintlify plan. | Not started, needs an account change |
| `silo-bz.vercel.app` is a hand-bound alias frozen on the 2026-09-17 build | It answers **200 with a stale page**, which is worse than a 404 for anyone holding the old link. The live host is `silo-bz-deloslabs.vercel.app`, which follows production by itself. Re-assigning the old alias has been tried five times and does not hold; it is deliberately left alone. | Known, not fixed |
| `coverage().landed_at` reads a day stale for the B3 lending group | The not-published-yet path logs the slice `skipped` (`src/pipeline/b3_pipeline.py`), and `landed_at` counts only `ok` rows — so on any day B3 has not yet published the newest session, which is most days at 06:00 UTC, the field reports our pipeline as stale although it ran and upserted. That is the OUR-health-vs-SOURCE-health confusion `CLAUDE.md` warns about, landing in the field documented as "when ingest last SUCCEEDED". Fix would be to log `ok` when rows landed and only the newest session is missing, keeping `skipped` for the zero-row case — it touches the DB Health gate, so it is not a drive-by. | Diagnosed, unfixed |
| Supabase storage near the plan allowance | Ingest stops when it fills. | Reported 81% of 135 GB on 2026-09-17; **not re-measured since** |
| `sdk/silo_client` is not published | `pip install silo-client` does not resolve; callers vendor the directory. | See [SDK.md](SDK.md) |

## Archive

Finished work, kept as the record of a decision — not live state. Nothing here
is a queue; do not work from it.

| Doc                                                                              | Was                                                                          |
| -------------------------------------------------------------------------------- | ---------------------------------------------------------------------------- |
| [archive/DASHBOARD_REVIEW_2026-09-15.md](archive/DASHBOARD_REVIEW_2026-09-15.md) | Page-by-page review of the live site                                         |
| [archive/SHIP_DASHBOARD_2026-09-14.md](archive/SHIP_DASHBOARD_2026-09-14.md)     | What "shipped" meant for `dashboard/`, and the four things that did not hold |
| [archive/API_FIELD_TEST_2026-08-28.md](archive/API_FIELD_TEST_2026-08-28.md)     | A fresh agent given the docs and no source, to find the friction             |
| [archive/STATUS_2026-08-28.md](archive/STATUS_2026-08-28.md)                     | Overnight run snapshot                                                       |
| [archive/STATUS_2026-08-28_day.md](archive/STATUS_2026-08-28_day.md)             | Day session snapshot                                                         |
| [archive/RELEASE_v1.1.md](archive/RELEASE_v1.1.md)                               | Annotation for the v1.1 tag, which could not be pushed                       |

## Where else to look

- `docs/DATA_INVENTORY.md` — what is held, what is served, what is neither.
- `docs/DATABASE_MAINTENANCE.md` — the ongoing upkeep runbook.
- `docs/API.md` — the read contract.
