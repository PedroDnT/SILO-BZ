# docs/

Five places, one question each. A doc that answers a different question than the
folder it is in is in the wrong folder.

| Where                                                              | Answers                      | Holds                                                                                           |
| ------------------------------------------------------------------ | ---------------------------- | ----------------------------------------------------------------------------------------------- |
| root `AGENTS.md`, `CLAUDE.md`, `CONTEXT.md`, `docs/agents/`, `docs/adr/` | How do I work here?          | Rules, vocabulary, per-dataset notes, decisions                                                 |
| [`architecture/`](architecture/)                                   | How does it work?            | `SYSTEM.md`, `DATA_FLOW.md`, `OPERATIONS.md`, `DECISIONS.md`                                    |
| [`reference/`](reference/)                                         | What is true about the data? | `API.md`, `DATABASE_MAINTENANCE.md`, `DATA_INVENTORY.md`, `DATA_MODELING.md`, `CIA_DATA_MAP.md`, `research/` (measured findings), `security/` (role and RLS SQL) |
| [`planning/`](planning/)                                           | What is open?                | Live work only: `OPEN_ITEMS.md`, the roadmap docs, `CHANGELOG.md`                               |
| [`archive/`](archive/)                                             | What did we decide, and why? | Finished research kept because a live doc cites it                                              |

Two rules keep it this way:

- **A dated snapshot is not a file.** Status runs, reviews and field tests go in
  the PR or the issue, and in git history after that. Do not add them to `planning/`.
- **Published product docs are elsewhere.** `api-docs/` is the Mintlify site,
  `skill.md` and `sdk/` are what API callers read. They are not agent or planning docs.
