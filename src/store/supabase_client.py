"""
Supabase client wrapper for bulk upsert operations.

Requires environment variables:
  SUPABASE_URL         — https://<project>.supabase.co
  SUPABASE_SERVICE_KEY — service_role key (bypasses RLS)
"""

import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_CHUNK_SIZE = 500  # Supabase REST upsert batch limit (safe limit)


def get_supabase_client() -> Any:
    """Return an initialised supabase-py Client."""
    try:
        from supabase import create_client  # type: ignore
    except ImportError as exc:
        raise ImportError(
            "supabase package is required. Run: pip install supabase"
        ) from exc

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_KEY")
    if not url or not key:
        raise EnvironmentError(
            "SUPABASE_URL and SUPABASE_SERVICE_KEY must be set"
        )
    return create_client(url, key)


def upsert_rows(
    client: Any,
    table: str,
    rows: List[Dict[str, Any]],
    conflict_columns: Optional[str] = None,
) -> int:
    """
    Upsert rows into a Supabase table in chunks.

    When `conflict_columns` is set, rows with duplicate conflict-key tuples are
    deduplicated (last write wins) before chunking. PostgREST otherwise raises
    21000 "ON CONFLICT DO UPDATE command cannot affect row a second time" when
    duplicates land in the same chunk — common for CVM tab_X_4-style files where
    a (cnpj, period, classe_serie, tp_oper) tuple appears multiple times.

    Args:
        client:           supabase-py Client
        table:            table name
        rows:             list of dicts to upsert
        conflict_columns: comma-separated column names for ON CONFLICT
                          (Supabase uses the unique constraint name or column list)

    Returns:
        Total number of rows processed.
    """
    if not rows:
        return 0

    if conflict_columns:
        keys = [c.strip() for c in conflict_columns.split(",") if c.strip()]
        seen: Dict[tuple, int] = {}
        deduped: List[Dict[str, Any]] = []
        for row in rows:
            key = tuple(row.get(k) for k in keys)
            if key in seen:
                deduped[seen[key]] = row  # last write wins
            else:
                seen[key] = len(deduped)
                deduped.append(row)
        if len(deduped) < len(rows):
            logger.info(
                "upsert dedup: table=%s conflict=%s collapsed %d -> %d rows",
                table, conflict_columns, len(rows), len(deduped),
            )
        rows = deduped

    total = 0
    for i in range(0, len(rows), _CHUNK_SIZE):
        chunk = rows[i : i + _CHUNK_SIZE]
        try:
            kwargs: Dict[str, Any] = {"returning": "minimal"}
            if conflict_columns:
                kwargs["on_conflict"] = conflict_columns
            client.table(table).upsert(chunk, **kwargs).execute()
            total += len(chunk)
        except Exception as exc:
            logger.error(
                "Upsert failed for table=%s chunk_start=%d: %s",
                table, i, exc
            )
            raise
    return total
