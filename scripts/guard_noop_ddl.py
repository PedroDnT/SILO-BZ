"""Rewrite no-op / long-held DDL so daily schema apply does not lock.

PostgreSQL traps show up when daily ingest re-applies schema.sql + every
migration against a live warehouse:

1. `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` takes AccessExclusiveLock
   *before* it checks whether the column exists. A concurrent SELECT
   (AccessShareLock) — a Vercel Evidence build scanning cvm_fii_mensal /
   cvm_fi_perfil — then blocks the DDL, and the queued exclusive lock
   blocks every reader behind it.

   Confirmed on SILO-BZ:

   - 2026-08-26 22:41 UTC (run 33019539699): migration 14's ADD COLUMN on
     cvm_fi_perfil hung 4m20s; the server killed the connection.
   - 2026-08-27 02:45 UTC (run 33034222521): schema.sql:268 ADD COLUMN on
     cvm_fii_mensal hit lock_timeout=15s three times. The same statement in
     the 22:23 run logged `column "nr_cotst" ... already exists, skipping`
     — it was a no-op. Ingest never started.

   Top-level ADD COLUMN IF NOT EXISTS is wrapped in a pg_attribute probe
   (AccessShareLock, compatible with SELECT). The original ALTER runs only
   when at least one named column is missing.

2. `CREATE MATERIALIZED VIEW IF NOT EXISTS ... AS SELECT` (implicit WITH
   DATA) inserts the composite type into pg_type and holds that insert
   uncommitted for the whole population scan. A concurrent schema apply
   does not see the uncommitted relation, tries to CREATE the same name,
   and waits on pg_type_typname_nsp_index until lock_timeout.

   Confirmed on SILO-BZ:

   - 2026-08-28 14:36 UTC (Daily CVM Ingest #184 / run 33180429771):
     CREATE MATERIALIZED VIEW mv_b3_isin_subtype failed three times with
     `canceling statement due to lock timeout` / `while inserting index
     tuple ... in relation "pg_type_typname_nsp_index"`. PR #105's ADD
     COLUMN guard had already rewritten the earlier ALTERs (the log is
     DO / CREATE INDEX up to that line). Ingest never started.

   Top-level CREATE MATERIALIZED VIEW IF NOT EXISTS that does not already
   say WITH NO DATA / WITH DATA is rewritten to WITH NO DATA so the type
   commit is instantaneous. Population is a later REFRESH (schema.sql
   refresh-if-empty, or pg_cron CONCURRENTLY), a separate statement that
   does not insert into pg_type.

3. Adjacent DROP INDEX / CREATE UNIQUE INDEX pairs rebuild an already-correct
   index every day. Run 37579395989 (2026-10-07) failed at the DROP of
   uq_fi_cda_acoes before ingestion. For simple btree column keys with NULLS
   NOT DISTINCT, probe the catalog and retain valid matching indexes. Missing
   or different indexes still execute the original DDL. An absent constraint's
   DROP CONSTRAINT IF EXISTS is also catalog-guarded to avoid a no-op lock.

Statements inside DO $$ blocks are left alone — those are already
catalog-guarded (see migrations/03_precision.sql, 06_etf.sql).

Stdlib only: the GitHub composite action must run this on runners that have
not always run setup-python (backfill's apply-schema job).
"""
from __future__ import annotations

import argparse
import re
import sys
from typing import Iterable

GUARD_TAG = "silo_guard_add"

_ALTER_ADD = re.compile(
    r"^ALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?(?P<table>[\w.]+)\s+"
    r"(?P<body>ADD\s+COLUMN\s+IF\s+NOT\s+EXISTS\b.+)$",
    re.IGNORECASE | re.DOTALL,
)
_ADD_COL_NAME = re.compile(
    r"ADD\s+COLUMN\s+IF\s+NOT\s+EXISTS\s+(?P<col>[\w]+)",
    re.IGNORECASE,
)
_MIXED_ALTER = re.compile(
    r"\b(?:ALTER\s+COLUMN|DROP\s+COLUMN|ADD\s+CONSTRAINT|DROP\s+CONSTRAINT|"
    r"RENAME\s+|SET\s+SCHEMA|OWNER\s+TO)\b",
    re.IGNORECASE,
)
_LEADING_NOISE = re.compile(
    r"^(?:\s|--[^\n]*\n|/\*.*?\*/)*",
    re.DOTALL,
)
_CREATE_MV = re.compile(
    r"^CREATE\s+MATERIALIZED\s+VIEW\s+IF\s+NOT\s+EXISTS\s+"
    r"(?P<name>[\w.]+)\s+AS\s+(?P<query>.+)$",
    re.IGNORECASE | re.DOTALL,
)
_WITH_NO_DATA_TAIL = re.compile(r"\bWITH\s+NO\s+DATA\s*$", re.IGNORECASE)
_WITH_DATA_TAIL = re.compile(r"\bWITH\s+DATA\s*$", re.IGNORECASE)
_DROP_INDEX = re.compile(r"^DROP INDEX IF EXISTS ([\w.]+);$", re.I)
_DROP_CONSTRAINT = re.compile(
    r"^ALTER TABLE ([\w.]+) DROP CONSTRAINT IF EXISTS ([\w]+);$", re.I,
)
_REBUILD_INDEX = re.compile(
    r"^CREATE UNIQUE INDEX IF NOT EXISTS ([\w.]+)\s+ON ([\w.]+)\s*"
    r"\(([a-z_][a-z_0-9]*(?:\s*,\s*[a-z_][a-z_0-9]*)*)\)\s+NULLS NOT DISTINCT;$",
    re.I,
)


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def split_sql_statements(sql: str) -> list[str]:
    """Split on top-level semicolons; keep inner `;` inside quotes / $-quotes.

    Each returned chunk includes its trailing semicolon when one terminated it.
    A final chunk without a semicolon is included if it has non-whitespace.
    """
    chunks: list[str] = []
    buf: list[str] = []
    i = 0
    n = len(sql)
    while i < n:
        ch = sql[i]
        nxt = sql[i + 1] if i + 1 < n else ""

        if ch == "-" and nxt == "-":
            end = sql.find("\n", i)
            if end < 0:
                buf.append(sql[i:])
                break
            buf.append(sql[i : end + 1])
            i = end + 1
            continue
        if ch == "/" and nxt == "*":
            end = sql.find("*/", i + 2)
            if end < 0:
                buf.append(sql[i:])
                break
            buf.append(sql[i : end + 2])
            i = end + 2
            continue
        if ch == "'":
            buf.append(ch)
            i += 1
            while i < n:
                buf.append(sql[i])
                if sql[i] == "'":
                    if i + 1 < n and sql[i + 1] == "'":
                        buf.append("'")
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            continue
        if ch == '"':
            buf.append(ch)
            i += 1
            while i < n:
                buf.append(sql[i])
                if sql[i] == '"':
                    i += 1
                    break
                i += 1
            continue
        if ch == "$":
            tag, consumed = _dollar_tag(sql, i)
            if tag is not None:
                buf.append(sql[i : i + consumed])
                i += consumed
                closer = "$" + tag + "$"
                end = sql.find(closer, i)
                if end < 0:
                    buf.append(sql[i:])
                    break
                buf.append(sql[i : end + len(closer)])
                i = end + len(closer)
                continue
        if ch == ";":
            buf.append(ch)
            chunks.append("".join(buf))
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    rest = "".join(buf)
    if rest:
        chunks.append(rest)
    return chunks


def _dollar_tag(sql: str, i: int) -> tuple[str | None, int]:
    """Return (tag, length of $tag$) at sql[i], or (None, 0) if not a $-quote."""
    if sql[i] != "$":
        return None, 0
    j = i + 1
    while j < len(sql) and (sql[j].isalnum() or sql[j] == "_"):
        j += 1
    if j < len(sql) and sql[j] == "$":
        return sql[i + 1 : j], j - i + 1
    return None, 0


def _statement_body(chunk: str) -> str:
    """Strip leading comments/whitespace so we can classify the statement."""
    return _LEADING_NOISE.sub("", chunk).strip()


def wrap_add_column_statement(stmt: str) -> str | None:
    """Return a catalog-guarded DO block, or None if stmt is not wrappable."""
    body = _statement_body(stmt)
    ended_with_semi = body.endswith(";")
    core = body[:-1].strip() if ended_with_semi else body
    match = _ALTER_ADD.match(core)
    if not match:
        return None
    if _MIXED_ALTER.search(match.group("body")):
        return None
    table = match.group("table")
    cols = [m.group("col") for m in _ADD_COL_NAME.finditer(match.group("body"))]
    if not cols:
        return None
    values = ", ".join(f"({_sql_literal(c)})" for c in cols)
    original = core  # ALTER ... without trailing semicolon
    return (
        f"DO ${GUARD_TAG}$\n"
        f"BEGIN\n"
        f"  -- Skip AccessExclusiveLock when every named column already exists.\n"
        f"  -- pg_attribute probe is AccessShareLock (compatible with SELECT).\n"
        f"  IF EXISTS (\n"
        f"    SELECT 1\n"
        f"    FROM (VALUES {values}) AS wanted(col)\n"
        f"    WHERE NOT EXISTS (\n"
        f"      SELECT 1 FROM pg_attribute\n"
        f"      WHERE attrelid = to_regclass({_sql_literal(table)})\n"
        f"        AND attname = wanted.col\n"
        f"        AND attnum > 0\n"
        f"        AND NOT attisdropped\n"
        f"    )\n"
        f"  ) THEN\n"
        f"    {original};\n"
        f"  END IF;\n"
        f"END\n"
        f"${GUARD_TAG}$;\n"
    )


def _keep_lead(chunk: str, rewritten: str) -> str:
    """Preserve leading whitespace/comments that preceded the statement body."""
    body = _statement_body(chunk)
    lead_len = chunk.find(body) if body else 0
    lead = chunk[:lead_len] if lead_len > 0 else ""
    return lead + rewritten


def guard_add_column_sql(sql: str) -> str:
    """Wrap top-level ADD COLUMN IF NOT EXISTS; leave everything else intact."""
    parts: list[str] = []
    for chunk in split_sql_statements(sql):
        wrapped = wrap_add_column_statement(chunk)
        if wrapped is None:
            parts.append(chunk)
            continue
        parts.append(_keep_lead(chunk, wrapped))
    return "".join(parts)


def wrap_matview_statement(stmt: str) -> str | None:
    """Return CREATE ... WITH NO DATA, or None if stmt is not a top-level MV."""
    body = _statement_body(stmt)
    ended_with_semi = body.endswith(";")
    core = body[:-1].strip() if ended_with_semi else body
    match = _CREATE_MV.match(core)
    if not match:
        return None
    query = match.group("query").rstrip()
    if _WITH_NO_DATA_TAIL.search(query):
        return None
    if _WITH_DATA_TAIL.search(query):
        new_core = _WITH_DATA_TAIL.sub("WITH NO DATA", core)
        return new_core + ";\n"
    return core + "\nWITH NO DATA;\n"


def guard_matview_sql(sql: str) -> str:
    """Force top-level CREATE MATERIALIZED VIEW IF NOT EXISTS to WITH NO DATA."""
    parts: list[str] = []
    for chunk in split_sql_statements(sql):
        wrapped = wrap_matview_statement(chunk)
        if wrapped is None:
            parts.append(chunk)
            continue
        parts.append(_keep_lead(chunk, wrapped))
    return "".join(parts)


def guard_index_rebuild_sql(sql: str) -> str:
    """Skip adjacent simple UNIQUE index rebuilds only when the catalog matches.

    Narrow grammar: ordinary unquoted column keys, default btree semantics,
    NULLS NOT DISTINCT. Expressions, partial indexes and other DDL stay intact.
    A missing, invalid or different index still executes the original pair.
    """
    chunks = split_sql_statements(sql)
    out = []
    i = 0
    while i < len(chunks):
        drop = _DROP_INDEX.fullmatch(_statement_body(chunks[i]))
        create = (_REBUILD_INDEX.fullmatch(_statement_body(chunks[i + 1]))
                  if drop and i + 1 < len(chunks) else None)
        if not create or drop.group(1) != create.group(1):
            out.append(chunks[i])
            i += 1
            continue
        name, table, keys = create.groups()
        cols = [c.strip().lower() for c in keys.split(",")]
        values = ", ".join(_sql_literal(c) for c in cols)
        pair = _statement_body(chunks[i]) + "\n" + chunks[i + 1].strip()
        guard = f"""DO $silo_guard_index$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_index x
    JOIN pg_class idx ON idx.oid = x.indexrelid
    JOIN pg_am am ON am.oid = idx.relam
    WHERE x.indexrelid = to_regclass({_sql_literal(name)})
      AND x.indrelid = to_regclass({_sql_literal(table)})
      AND x.indisunique AND x.indisvalid AND x.indisready AND x.indimmediate
      AND x.indnullsnotdistinct
      AND am.amname = 'btree' AND x.indpred IS NULL AND x.indexprs IS NULL
      AND x.indnkeyatts = {len(cols)} AND x.indnatts = {len(cols)}
      AND ARRAY(SELECT pg_get_indexdef(x.indexrelid, n, true)
                FROM generate_series(1, x.indnatts) n) = ARRAY[{values}]
      AND NOT EXISTS (SELECT 1 FROM unnest(x.indoption) opt WHERE opt <> 0)
      AND NOT EXISTS (
        SELECT 1 FROM unnest(x.indclass) op
        JOIN pg_opclass oc ON oc.oid = op WHERE NOT oc.opcdefault
      )
      AND NOT EXISTS (
        SELECT 1 FROM unnest(x.indkey::smallint[], x.indcollation::oid[]) k(attnum, coll)
        JOIN pg_attribute a ON a.attrelid = x.indrelid AND a.attnum = k.attnum
        WHERE k.coll <> a.attcollation
      )
  ) THEN
    {pair}
  END IF;
END
$silo_guard_index$;
"""
        out.append(_keep_lead(chunks[i], guard))
        i += 2
    return "".join(out)


def guard_drop_constraint_sql(sql: str) -> str:
    """An absent constraint must not acquire an exclusive table lock either."""
    out = []
    for chunk in split_sql_statements(sql):
        body = _statement_body(chunk)
        match = _DROP_CONSTRAINT.fullmatch(body)
        if not match:
            out.append(chunk)
            continue
        table, name = match.groups()
        guarded = f"""DO $silo_guard_constraint$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_constraint
             WHERE conrelid = to_regclass({_sql_literal(table)})
               AND conname = {_sql_literal(name.lower())}) THEN
    {body}
  END IF;
END
$silo_guard_constraint$;
"""
        out.append(_keep_lead(chunk, guarded))
    return "".join(out)


def guard_noop_ddl(sql: str) -> str:
    """Apply catalog guards and defer initial materialized-view population."""
    return guard_index_rebuild_sql(guard_drop_constraint_sql(
        guard_matview_sql(guard_add_column_sql(sql))))


def iter_wrappable(sql: str) -> Iterable[str]:
    for chunk in split_sql_statements(sql):
        if wrap_add_column_statement(chunk) is not None:
            yield _statement_body(chunk)


def iter_wrappable_matview(sql: str) -> Iterable[str]:
    for chunk in split_sql_statements(sql):
        if wrap_matview_statement(chunk) is not None:
            yield _statement_body(chunk)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Rewrite no-op ADD COLUMN IF NOT EXISTS and CREATE MATERIALIZED "
            "VIEW IF NOT EXISTS, absent constraint drops and matching index rebuilds."
        ),
    )
    parser.add_argument("path", help="SQL file to rewrite (stdout)")
    args = parser.parse_args(argv)
    with open(args.path, encoding="utf-8") as fh:
        sys.stdout.write(guard_noop_ddl(fh.read()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
