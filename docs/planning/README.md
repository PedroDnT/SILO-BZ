# Planning

## Live

| Doc                                        | Is                                                                                                     | Open                                                                             |
| ------------------------------------------ | ------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------- |
| [SERVING.md](SERVING.md)                   | The serving roadmap, step by step                                                                      | Step 8 (widen the panel) — everything else done or obsoleted                     |
| [INSTRUMENTS.md](INSTRUMENTS.md)           | How each B3 instrument class is ingested and served                                                    | Design reference, no queue                                                       |
| [SDK.md](SDK.md)                           | What `sdk/silo_client` is today and what is missing                                                    | pandas dependency, PyPI, wheel CI, async                                         |
| [OPEN_ITEMS.md](OPEN_ITEMS.md)             | **The** register of what is deliberately not done                                                      | Fourteen items (14 sequences the §7 backlog); read this before starting anything |
| [CHANGELOG.md](CHANGELOG.md)               | Append-only log, one row per merged branch                                                             | —                                                                                |
| [COMPETITIVE_GAPS.md](COMPETITIVE_GAPS.md) | Who else does this, what they have that we don't, and what nobody has (2026-09-23)                     | Snapshot; its §7 backlog is sequenced in `OPEN_ITEMS.md` item 14                 |
| [AGENTS.md](AGENTS.md)                     | The governed agent loop (B7): principle, roster, lineage rules, and the registry                       | Nothing scheduled; the smallest test (one manual Builder run) is pending         |
| [DOCUMENTS.md](DOCUMENTS.md)               | B4 design: field-by-field diffs between FNET versions of one structured informe, with a measured spike | Awaiting Pedro's eight decisions (§11); nothing built                            |

There is **one** list of open work, and it is `OPEN_ITEMS.md`. On 2026-09-18 two
were merged within minutes of each other, from different sessions, neither
pointing at the other — so anything provisional or missing goes in that file, and
nowhere else. A doc above may describe its own future shape; it does not carry a
queue.

## Archive

Finished work, kept as the record of a decision — not live state. Nothing here
is a queue; do not work from it.

| Doc                                                                                  | Was                                                                          |
| ------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------- |
| [archive/competitive_research_2026-09-23/](archive/competitive_research_2026-09-23/) | The six research tracks behind `COMPETITIVE_GAPS.md`, with every source URL  |
| [archive/DASHBOARD_REVIEW_2026-09-15.md](archive/DASHBOARD_REVIEW_2026-09-15.md)     | Page-by-page review of the live site                                         |
| [archive/SHIP_DASHBOARD_2026-09-14.md](archive/SHIP_DASHBOARD_2026-09-14.md)         | What "shipped" meant for `dashboard/`, and the four things that did not hold |
| [archive/API_FIELD_TEST_2026-08-28.md](archive/API_FIELD_TEST_2026-08-28.md)         | A fresh agent given the docs and no source, to find the friction             |
| [archive/STATUS_2026-08-28.md](archive/STATUS_2026-08-28.md)                         | Overnight run snapshot                                                       |
| [archive/STATUS_2026-08-28_day.md](archive/STATUS_2026-08-28_day.md)                 | Day session snapshot                                                         |
| [archive/RELEASE_v1.1.md](archive/RELEASE_v1.1.md)                                   | Annotation for the v1.1 tag, which could not be pushed                       |

## Where else to look

- `docs/DATA_INVENTORY.md` — what is held, what is served, what is neither.
- `docs/DATABASE_MAINTENANCE.md` — the ongoing upkeep runbook.
- `docs/API.md` — the read contract.
