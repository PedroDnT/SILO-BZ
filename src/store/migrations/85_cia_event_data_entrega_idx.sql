-- api.coverage() reads the company_events dates as index probes (#1100).
-- Its company_events arm takes MAX(data_entrega), bounded and not, from
-- cia_event. No index led on data_entrega, so each call read every row of the
-- table (an index-only scan of ~500k entries on idx_cia_event_categoria, 3 s
-- cold, anon's statement timeout). With this index each MAX is one backward
-- probe. cia_event is created by migration 04, not schema.sql, so the index
-- lives here; schema.sql carries the same statement behind a to_regclass guard.
CREATE INDEX IF NOT EXISTS idx_cia_event_data_entrega
    ON cia_event (data_entrega);
