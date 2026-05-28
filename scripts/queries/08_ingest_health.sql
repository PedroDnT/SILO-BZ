-- Pipeline operational health: ingest log + data coverage alerts
-- Paste into psql $POSTGRES_URL -f scripts/queries/08_ingest_health.sql

-- Last 7 days of ingest runs — any errors?
SELECT * FROM ingest_log_summary(CURRENT_DATE - 7, CURRENT_DATE)
ORDER BY entity, doc_type;

-- Last 30 days ranked by error count
SELECT * FROM ingest_log_summary(CURRENT_DATE - 30, CURRENT_DATE)
ORDER BY n_error DESC, entity;

-- Coverage gaps: entities with no new data in 35+ days
SELECT * FROM data_coverage(NULL, CURRENT_DATE - 90, CURRENT_DATE)
WHERE months_since_last_report > 1
ORDER BY months_since_last_report DESC, entity_type;

-- Raw recent errors (last 20)
SELECT entity, doc_type, status, rows_upserted, error_msg,
       started_at AT TIME ZONE 'UTC' AS started_utc
FROM cvm_ingest_log
WHERE status = 'error'
ORDER BY started_at DESC
LIMIT 20;
