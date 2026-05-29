-- =============================================================================
-- Migration 02 — BACEN tables (SGS, PTAX, Expectativas)
-- Idempotent: all statements use IF NOT EXISTS guards.
-- Apply after schema.sql which creates the base tables.
-- =============================================================================

-- No structural changes to BACEN tables currently required.
-- This file exists as a placeholder so W2/W3/W4 agents can append their own
-- BACEN-related migrations here without editing the shared schema.sql.

-- Future: if BACEN series need wider precision or new columns, add here:
-- ALTER TABLE bacen_sgs ALTER COLUMN value TYPE NUMERIC(28,8);
