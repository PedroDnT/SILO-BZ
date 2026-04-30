"""Stage 2 — PARSE. Bytes/DataFrames/JSON → typed row dicts plus quality
validation. Most CVM CSV parsing lives in src/fetchers/cvm_fetcher.py
(extraction is tightly coupled to the ZIP/URL conventions); BACEN parsing
lives in src/fetchers/bacen_fetcher.py (DataFrame normalization). This
package only owns shared, source-agnostic validation."""

from .validation import DataValidator, ValidationError, ValidationWarning, validator

__all__ = ["DataValidator", "ValidationError", "ValidationWarning", "validator"]
