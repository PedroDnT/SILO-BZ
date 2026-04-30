"""Stage 3 — STORE. Supabase client + chunked upserts + audit log helpers.
Schema lives in store/schema.sql (apply with psql)."""

from .supabase_client import get_supabase_client, upsert_rows

__all__ = ["get_supabase_client", "upsert_rows"]
