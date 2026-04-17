"""
Supabase ingestion layer for CVM + BACEN historical data.

Entry points:
  python -m src.ingestor.run_backfill   — full historical download
  python -m src.ingestor.run_daily      — yesterday's incremental update
"""
