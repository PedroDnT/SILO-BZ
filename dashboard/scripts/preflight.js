#!/usr/bin/env node
/**
 * Fail fast, and legibly, when the dashboard is pointed at a database that
 * cannot satisfy its source queries.
 *
 * Without this, a wrong/empty database produces the least useful failure the
 * stack can emit. @evidence-dev/postgres discards the real Postgres error:
 *
 *     const lengthQuery = await connection.query(...).catch(() => undefined);
 *     const rowCount = lengthQuery.rows[0].rows;   // TypeError on undefined
 *
 * so every source reports `Cannot read properties of undefined (reading
 * 'rows')` — identical whether the table is missing, the column is misspelled,
 * or permission was denied — and the build then hangs until the pooler drops it
 * ("Connection terminated unexpectedly", ~5 minutes later). That is exactly the
 * signature we spent a deploy cycle decoding; this check turns it into one line.
 *
 * Runs before `evidence sources` and connects with the same
 * EVIDENCE_SOURCE__supabase__* variables Evidence itself uses, so it verifies
 * the credentials that actually matter rather than a copy of them.
 */
import pg from 'pg';

const env = (name) => process.env[`EVIDENCE_SOURCE__supabase__${name}`];

// One table per dashboard page area. These are existence checks, not row
// counts — the point is to catch a connection pointed at the wrong database,
// not to police coverage.
const REQUIRED = [
  'cvm_fi_diario',
  'cvm_fi_perfil',
  'cvm_fi_cda',
  'cvm_fidc_mensal',
  'cvm_fidc_aging',
  'cvm_fidc_tranche',
  'cvm_fii_mensal',
  'cvm_securit_serie',
  'cvm_securit_fluxo',
  'cvm_etf_registry',
  'bacen_sgs',
  'cvm_ingest_log',
];

// Objects a source query reads that only exist once a migration has been
// applied. These are a SEPARATE check because they fail for a different reason
// and have a different fix.
//
// A dashboard deploy and a schema migration are independent events: Vercel
// builds on push, while migrations are applied by the ingest workflow. Merge a
// PR that adds both a migration and a query against it, and the deploy can win
// the race — the source queries then fail with five identical
// "Cannot read properties of undefined (reading 'rows')" lines and the build
// dies on a 0-byte parquet, which says nothing about the actual cause.
//
// Checking them here turns that into one line naming the migration to apply.
// The build still fails, and should: a dashboard querying columns that do not
// exist is not deployable. The point is that the failure is legible.
//
// `source` is the file that creates the object and `fix` the command that
// applies it. Two different commands land here: migrations go in with
// apply_schema.py, analytical views with apply_analytical.sh, and naming the
// wrong one sends whoever reads this log down the wrong path.
const REQUIRED_AFTER_MIGRATION = [
  {
    relation: 'cvm_fii_imovel', column: null,
    source: 'src/store/migrations/15_fii_trimestral_members.sql',
    fix: 'python scripts/apply_schema.py',
  },
  {
    relation: 'cvm_fi_perfil', column: 'nr_cotst_pf_varejo',
    source: 'src/store/migrations/14_fi_perfil_columns.sql',
    fix: 'python scripts/apply_schema.py',
  },
  {
    relation: 'bacen_expectativas', column: 'horizon',
    source: 'src/store/migrations/16_bacen_expectativas_horizon.sql',
    fix: 'python scripts/apply_schema.py',
  },
  // The B3 lending / investor-flow group. /short and /flows read these, and
  // they arrive in two stages — landing tables from the migration, the views
  // the pages actually query from the analytical layer — so both are checked.
  {
    relation: 'b3_lending_open_position', column: null,
    source: 'src/store/migrations/39_b3_lending_flow.sql',
    fix: 'python scripts/apply_schema.py',
  },
  {
    relation: 'fact_short_interest_daily', column: null,
    source: 'src/store/analytical/20_short_interest.sql',
    fix: 'bash scripts/apply_analytical.sh',
  },
  {
    relation: 'fact_investor_flow_daily', column: null,
    source: 'src/store/analytical/20_short_interest.sql',
    fix: 'bash scripts/apply_analytical.sh',
  },
];

const missingVars = ['host', 'database', 'user', 'password'].filter((v) => !env(v));
if (missingVars.length) {
  console.error(
    `\n[preflight] Missing required env vars: ${missingVars
      .map((v) => `EVIDENCE_SOURCE__supabase__${v}`)
      .join(', ')}\n` +
      `[preflight] Set them on the Vercel project (all environments). See dashboard/README.md.\n`
  );
  process.exit(1);
}

const client = new pg.Client({
  host: env('host'),
  port: Number(env('port') || 5432),
  database: env('database'),
  user: env('user'),
  password: env('password'),
  ssl: { rejectUnauthorized: false },
  // Don't inherit the 5-minute hang this check exists to prevent.
  connectionTimeoutMillis: 15_000,
  query_timeout: 15_000,
});

try {
  await client.connect();
} catch (err) {
  console.error(
    `\n[preflight] Cannot connect to ${env('host')}:${env('port') || 5432}/${env('database')}\n` +
      `[preflight] ${err.message}\n`
  );
  process.exit(1);
}

const { rows } = await client.query(
  `SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename = ANY($1)`,
  [REQUIRED]
);

// Migration-dependent objects, checked before the base-table verdict so the
// more specific diagnosis wins when both are wrong.
const pending = [];
for (const item of REQUIRED_AFTER_MIGRATION) {
  const { rows: hit } = item.column
    ? await client.query(
        `SELECT 1 FROM information_schema.columns
          WHERE table_schema = 'public' AND table_name = $1 AND column_name = $2`,
        [item.relation, item.column]
      )
    : await client.query(`SELECT 1 WHERE to_regclass($1) IS NOT NULL`, [item.relation]);
  if (hit.length === 0) pending.push(item);
}

await client.end();

if (pending.length) {
  console.error(
    `\n[preflight] Connected to ${env('host')}/${env('database')} fine, but ` +
      `${pending.length} object(s) a source query needs are not there yet:\n` +
      pending
        .map((p) => `             - ${p.relation}${p.column ? '.' + p.column : ''}` +
                    `   (added by ${p.source})`)
        .join('\n') +
      `\n\n[preflight] The schema has not been applied to this database. A deploy` +
      `\n[preflight] and a migration are independent events and the deploy won the` +
      `\n[preflight] race. Run, then redeploy:\n` +
      [...new Set(pending.map((p) => p.fix))]
        .map((f) => `[preflight]     ${f}`)
        .join('\n') +
      `\n[preflight] The Daily CVM Ingest workflow does both.\n`
  );
  process.exit(1);
}

const found = new Set(rows.map((r) => r.tablename));
const missing = REQUIRED.filter((t) => !found.has(t));

if (missing.length) {
  console.error(
    `\n[preflight] Connected to ${env('host')}/${env('database')} as ${env('user')}, ` +
      `but ${missing.length} of ${REQUIRED.length} expected tables are missing:\n` +
      missing.map((t) => `             - ${t}`).join('\n') +
      `\n\n[preflight] This database is not the ingestion target. Most likely the` +
      `\n[preflight] EVIDENCE_SOURCE__supabase__host points at a Supabase preview-branch` +
      `\n[preflight] database (empty by design) instead of the project that POSTGRES_URL` +
      `\n[preflight] writes to. Compare the two hosts and re-deploy.\n`
  );
  process.exit(1);
}

console.log(`[preflight] ${env('host')}/${env('database')}: all ${REQUIRED.length} expected tables present.`);
