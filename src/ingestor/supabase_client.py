"""
Supabase client wrapper for bulk upsert operations.

Requires environment variables:
  SUPABASE_URL         — https://<project>.supabase.co
  SUPABASE_SERVICE_KEY — service_role key (bypasses RLS)

Falls back to direct asyncpg connection when SUPABASE_DB_URL is set,
which is faster for large batch inserts via COPY.
"""

import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_CHUNK_SIZE = 500  # Supabase REST upsert batch limit (safe limit)


def get_supabase_client():
    """Return an initialised supabase-py Client."""
    try:
        from supabase import create_client, Client  # type: ignore
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
    client,
    table: str,
    rows: List[Dict[str, Any]],
    conflict_columns: Optional[str] = None,
) -> int:
    """
    Upsert rows into a Supabase table in chunks.

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
