"""Rewrite no-op ADD COLUMN IF NOT EXISTS so daily schema apply does not lock.

PostgreSQL takes AccessExclusiveLock for `ALTER TABLE ... ADD COLUMN IF NOT
EXISTS` *before* it checks whether the column exists. Daily ingest re-applies
schema.sql + every migration, so that lock is acquired on tables whose columns
have been present for months. A concurrent SELECT (AccessShareLock) — a
Vercel Evidence build scanning cvm_fii_mensal / cvm_fi_perfil — then blocks
the DDL, and the queued exclusive lock blocks every reader behind it.

Confirmed on SILO-BZ:

- 2026-08-26 22:41 UTC (run 33019539699): migration 14's ADD COLUMN on
  cvm_fi_perfil hung 4m20s; the server killed the connection.
- 2026-08-27 02:45 UTC (run 33034222521): schema.sql:268 ADD COLUMN on
  cvm_fii_mensal hit lock_timeout=15s three times. The same statement in the
  22:23 run logged `column "nr_cotst" ... already exists, skipping` — it was
  a no-op. Ingest never started.

This rewriter wraps *top-level* ADD COLUMN IF NOT EXISTS in a pg_attribute
probe (AccessShareLock, compatible with SELECT). The original ALTER runs only
when at least one named column is missing. Statements inside DO $$ blocks are
left alone — those are already catalog-guarded (see migrations/03_precision.sql).

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


def guard_add_column_sql(sql: str) -> str:
    """Wrap top-level ADD COLUMN IF NOT EXISTS; leave everything else intact."""
    parts: list[str] = []
    for chunk in split_sql_statements(sql):
        wrapped = wrap_add_column_statement(chunk)
        if wrapped is None:
            parts.append(chunk)
            continue
        # Keep any leading whitespace/comments that preceded the ALTER.
        body = _statement_body(chunk)
        lead_len = chunk.find(body) if body else 0
        lead = chunk[:lead_len] if lead_len > 0 else ""
        parts.append(lead + wrapped)
    return "".join(parts)


def iter_wrappable(sql: str) -> Iterable[str]:
    for chunk in split_sql_statements(sql):
        if wrap_add_column_statement(chunk) is not None:
            yield _statement_body(chunk)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Wrap no-op ADD COLUMN IF NOT EXISTS in a catalog probe.",
    )
    parser.add_argument("path", help="SQL file to rewrite (stdout)")
    args = parser.parse_args(argv)
    with open(args.path, encoding="utf-8") as fh:
        sys.stdout.write(guard_add_column_sql(fh.read()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
