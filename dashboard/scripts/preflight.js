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
const REQUIRED_AFTER_MIGRATION = [
  { relation: 'cvm_fii_imovel', column: null, migration: '15_fii_trimestral_members.sql' },
  { relation: 'cvm_fi_perfil', column: 'nr_cotst_pf_varejo', migration: '14_fi_perfil_columns.sql' },
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
                    `   (added by src/store/migrations/${p.migration})`)
        .join('\n') +
      `\n\n[preflight] The schema migration has not been applied to this database.` +
      `\n[preflight] A deploy and a migration are independent events and the deploy` +
      `\n[preflight] won the race. Apply the schema, then redeploy:` +
      `\n[preflight]     python scripts/apply_schema.py` +
      `\n[preflight] or run the Daily CVM Ingest workflow, which bootstraps it.\n`
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
