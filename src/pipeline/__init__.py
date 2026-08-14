"""Stage 4 — ORCHESTRATION. Wires fetch -> parse -> store for each source.
Entrypoints: run_backfill (one-shot, all years) and run_daily (cron-driven)."""

from .cvm_pipeline import CVMIngestor
from .bacen_pipeline import BacenIngestor
from .b3_pipeline import B3Ingestor

__all__ = ["CVMIngestor", "BacenIngestor", "B3Ingestor"]
