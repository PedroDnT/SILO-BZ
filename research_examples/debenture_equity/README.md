# Debenture → issuer → equity: audit and offline experiment

This is the first executable gate of the [experiment plan](../../docs/reference/research/debenture-equity-experiment.md).
It reads existing data only. There is no ingest, database connection, migration,
API, daily enablement, paid service, or automatic mapping acceptance here.

From the repository root:

```sh
.venv/bin/python research_examples/debenture_equity/audit.py \
  --capture-id f7d46926-0349-4d54-a198-ffbad8045065
```

Execute the printed **SELECT** with the Supabase MCP for project
`zcjbtpxuhdekpwcxmepn`. Save the returned `audit` JSON object, without the MCP
wrapper, to an ignored local path. Then:

```sh
.venv/bin/python research_examples/debenture_equity/audit.py \
  --input .context/debenture-equity-audit.json
```

Redirect stdout to an ignored Markdown file if desired. Never commit the full
candidate export or raw market data. The SQL is bounded to a single capture and
its requested date window for COTAHIST and the instrument registry. Company/FCA
aliases use stored vintages to find candidates, **not** to infer historic knowledge.
The query can return many candidates; preserve the complete JSON without tool
output truncation. It returns no raw CSV or sensitive contact metadata.

The report reconciles counts and checks payload hash, complete status, drops,
source consistency and requested/known-session delivery. It distinguishes
registered equities from positive raw cash closes. A quoted equity is not proof
of adjusted-return coverage, current listing status, issuer identity or PIT.
The result is deliberately capped at PARTIALLY READY for this first gate, even
if every bond has a unique name candidate. Definitive dated mappings and the
later experiment gates are outside this audit's certification scope.

Names are normalized by uppercasing, translating the listed Portuguese accents,
and removing non-alphanumeric characters. No fuzzy matching, ISIN-prefix join,
CNPJ-root collapse, parent substitution, or guessed ticker is performed.
Legal names, FCA `Nome_Empresarial`, company `DENOM_COMERC`, COTAHIST short names
and registry institution names all retain their source in each candidate.
One bond can have zero, one or several candidates. An issuer need not have equity.

## Bounded existing-data export and recovery proposal

The reviewed sample now contains 26 documentary **original-issuer** links in
`reviewed_links.json`. Their retrospective validity assumes no intervening transfer;
they do not certify original-date knowledge or the full candidate universe.
`protocol.json` freezes the method and chronological splits. This three-month
pilot cannot meet its confirmatory date/issuer floors even after recovery.

Print a read-only export using existing total-return API functions and stored credit.
This example selects the initial six-link subset; pass every reviewed bond and its
FCA equity candidates to reproduce the full sample documented in the plan:

```sh
.venv/bin/python -m research_examples.debenture_equity.prepare \
  --bonds ALPA13 ALUP18 ANIM18 ASAI18 BSA318 BRKMA6 \
  --tickers ALPA3 ALPA4 ALUP11 ANIM3 ASAI3 B3SA3 BRKM3 BRKM5 BRKM6
```

Execute the printed SELECT through Supabase MCP. Save only its `bundle` object
locally, without truncation. Credit capture censuses validate both all stored groups
and the selected export scope. Never commit the bundle or raw source data.

The export includes FCA negotiation/listing start and end dates. The runner uses
the latest reference/version per full CNPJ and ticker as of each signal date,
then retains all listing rows in that filing and respects both recorded intervals
(inclusive endpoints). Segment changes may legitimately close one row and open
another within the same filing. An older open record cannot
override a newer closure. Missing interval dates and tickers removed entirely from
a later filing remain unproven: this bounded export is not a full FCA snapshot
absence audit, and reference dates do not prove publication-time availability.
Older local bundles must be exported again to include these date fields.

```sh
.venv/bin/python -m research_examples.debenture_equity.prepare \
  --plan-bundle .context/debenture-equity-bundle.json
```

This prints nonoverlapping missing-session slices, an explicitly conditional storage
scenario and the optimistic date ceiling after label purges. It never executes
ingest or authorizes production access. The [plan](../../docs/reference/research/debenture-equity-experiment.md)
records the concrete proposed recovery and its approval/stop conditions.

## Offline experiment

```sh
.venv/bin/python -m research_examples.debenture_equity.experiment \
  --bundle .context/debenture-equity-bundle.json \
  --links research_examples/debenture_equity/reviewed_links.json \
  --out-dir .context/debenture-equity-strict
```

Default `strict_pit` refuses an end-to-end historical claim from current equity/index
revisions. Add `--mode retrospective` for the explicitly retrospective pilot. Output
is local `result.json` plus `issuer_panel.csv`; no database/network access occurs.
The result includes protocol, bundle and identity fingerprints and exclusion counts.
One issuer/date/horizon is one outcome; absent trades are never imputed as zero.
PU changes and rates remain excluded. Missing history, sample floors or sector
robustness prevent a favorable overall research verdict. No tradability is certified.

Sector robustness reads existing `b3_index_portfolio` classifications for the exact
ticker/signal date, observed by that date's end in Brasília and before export.
There is no historical fill or inference from today's company sector. Conflicting
index labels refuse evaluation. Categories come only from purged training rows;
unknown validation/test sectors are excluded and counted. The same sector controls
enter both models; placebos shuffle whole credit vectors within date and sector.
The original and delayed studies must both pass sector robustness as well as the
uncontrolled checks before an incremental-evidence verdict. Missing history or fewer
than two training sectors gives an inconclusive result, with coverage reported.

Focused checks:

```sh
.venv/bin/python -m pytest tests/test_debenture_equity_audit.py tests/test_debenture_equity_experiment.py -q
```

## Unactivated prospective design

[prospective-design.md](prospective-design.md) and
[prospective_protocol.json](prospective_protocol.json) preserve the longer calendar
candidate, information/label cutoff rules, immutable inputs, development-only
power grid and completion audit. These are design artifacts, not an implemented
collector, an input accepted by the pilot CLI, production approval or evidence of
strict PIT. The original `protocol.json` and its results stay unchanged.
