# Planning

## Live

| Doc                                        | Is                                                                                                     | Open                                                                             |
| ------------------------------------------ | ------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------- |
| [SERVING.md](SERVING.md)                   | The serving roadmap, step by step                                                                      | Step 8 (widen the panel) — everything else done or obsoleted                     |
| [INSTRUMENTS.md](INSTRUMENTS.md)           | How each B3 instrument class is ingested and served                                                    | Design reference, no queue                                                       |
| [SDK.md](SDK.md)                           | What `sdk/silo_client` is today and what is missing                                                    | pandas dependency, PyPI, wheel CI, async                                         |
| [OPEN_ITEMS.md](OPEN_ITEMS.md)             | **The** register of what is deliberately not done                                                      | Seventeen items, eight of them done; open are 3, 7, 8, 10, 11, 13, 14 (the §7 backlog), 15 (portfolio diagnosis) and 17 (audit protocol: B3 check, CVM phase 4, review candidates); read this before starting anything |
| [CHANGELOG.md](CHANGELOG.md)               | Append-only log, one row per merged branch; the newest 60 (older: `docs/archive/changelog/`)                                                             | —                                                                                |
| [COMPETITIVE_GAPS.md](COMPETITIVE_GAPS.md) | Who else does this, what they have that we don't, and what nobody has (2026-09-23)                     | Snapshot; its §7 backlog is sequenced in `OPEN_ITEMS.md` item 14                 |
| [AGENTS.md](AGENTS.md)                     | The governed agent loop (B7): principle, roster, lineage rules, and the registry                       | The manual Builder test passed (PR #291) and the prompts are written; nothing is scheduled (`OPEN_ITEMS.md` item 13) |
| [DOCUMENTS.md](DOCUMENTS.md)               | B4 design: field-by-field diffs between FNET versions of one structured informe, with a measured spike | §11 decided 2026-09-26; slice 1 (FIDC mensal, 2026) is built and served (migration 46, catalog v40); older years are `OPEN_ITEMS.md` item 14, row 2f |
| [RESEARCH_SEAM.md](RESEARCH_SEAM.md)       | Research seam spec: adjusted closes, research universe, index history and as-of fundamentals for external quant callers (map #371) | Approved 2026-09-29; build tickets under epic #410; the universe (#411), the price contract (`close_adj` default, field selection, cross-board coverage, refusals, SDK `prices()`), the total-return close (#418), the benchmark index (#412, #415), the as-of fundamentals (#414), the SDK research clients with the usage guide (#419) and the corrected IBOV11 description (catalog v49) are built. Open: more indices (#416); #412, #413, #415, #417 and #420 close after the production check (`scripts/verify_research_seam.py` passing) |
| [PORTFOLIO_DIAGNOSIS.md](PORTFOLIO_DIAGNOSIS.md) | Portfolio diagnosis design: look-through exposure, restatement warnings, min-variance and ERC benchmarks | Open decisions are `OPEN_ITEMS.md` item 15; tickets under #340 |

There is **one** list of open work, and it is `OPEN_ITEMS.md`. On 2026-09-18 two
were merged within minutes of each other, from different sessions, neither
pointing at the other — so anything provisional or missing goes in that file, and
nowhere else. A doc above may describe its own future shape; it does not carry a
queue.

## Archive

Finished work lives in [`../archive/`](../archive/), kept as the record of a
decision, not live state. Nothing there is a queue; do not work from it.
Dated snapshots (status runs, reviews, field tests) are not kept as files: they
are in git history.

## Where else to look

- `docs/architecture/` — the system in four pages: `SYSTEM.md`, `DATA_FLOW.md`,
  `OPERATIONS.md`, `DECISIONS.md`. Start there.
- `docs/reference/DATA_INVENTORY.md` — what is held, what is served, what is neither.
- `docs/reference/DATABASE_MAINTENANCE.md` — the ongoing upkeep runbook.
- `docs/reference/API.md` — the read contract.
