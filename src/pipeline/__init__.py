"""Stage 4 — ORCHESTRATION. Wires fetch -> parse -> store for each source.
Entrypoints: run_backfill (one-shot, all years) and run_daily (cron-driven)."""

from .cvm_pipeline import CVMIngestor
from .bacen_pipeline import BacenIngestor

__all__ = ["CVMIngestor", "BacenIngestor"]
