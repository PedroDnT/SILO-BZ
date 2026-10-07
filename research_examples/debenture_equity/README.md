# Debenture → issuer → equity: bounded readiness audit

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
