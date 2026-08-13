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

// One table per dashboard page area. Absence of any of these means the pages
// that read it will render empty, so surface it before the build burns time.
const REQUIRED = [
  'cvm_fi_diario',
  'cvm_fidc_mensal',
  'cvm_fii_mensal',
  'cvm_securit_serie',
  'cvm_etf_registry',
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
await client.end();

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
