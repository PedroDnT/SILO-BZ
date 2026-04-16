# Requirements Document: Supabase Daily Data Backfill Tool

## Introduction

The Supabase Daily Data Backfill Tool is a data ingestion system that fetches financial data from external sources (URLs and CSV files) and stores it in Supabase across three isolated schemas (CVM, BACEN, B3). The system operates on an append-only model where data is never deleted, only inserted or updated. This MVP focuses on core functionality: fetching data, parsing CSV/JSON, validating, transforming, and storing with basic error handling.

## Glossary

- **Append-Only Model**: Data storage pattern where records are never deleted, only inserted or updated
- **Backfill Cycle**: Complete execution of the data ingestion process for all three services
- **BACEN**: Central Bank of Brazil; provides SGS time series and PTAX exchange rate data
- **B3**: Brazilian stock exchange; provides securities master data and pricing snapshots
- **CVM**: Brazilian Securities Commission; provides fund and credit market data
- **CSV**: Comma-separated values file format
- **Fetcher**: Component that retrieves raw data from external sources
- **Parser**: Component that converts raw data (CSV, JSON) into structured records
- **Payload**: JSONB field containing flexible, service-specific data attributes
- **Schema**: Database structure defining tables, columns, and constraints for a service
- **Storage Manager**: Component that handles database operations
- **Transformer**: Component that normalizes and prepares data for storage
- **Unique Key**: Service-specific combination of fields that uniquely identifies a record
- **Upsert**: Database operation that inserts new records or updates existing ones
- **Validator**: Component that ensures data conforms to schema and business rules

## Requirements

### Requirement 1: Daily Orchestration and Scheduling

**User Story:** As a system operator, I want the backfill tool to automatically execute daily at a configured time, so that financial data stays current without manual intervention.

#### Acceptance Criteria

1. THE Orchestrator SHALL schedule backfill runs at a configurable daily time
2. WHEN the scheduled time arrives, THE Orchestrator SHALL trigger backfill for all three services (CVM, BACEN, B3) in parallel
3. WHEN a backfill run completes, THE Orchestrator SHALL log the run metadata (start time, end time, status, records processed)
4. WHEN a backfill run fails, THE Orchestrator SHALL implement exponential backoff retry (1s, 2s, 4s, 8s) with maximum 3 attempts
5. WHEN a backfill run fails after all retries, THE Orchestrator SHALL alert the operations team with error details
6. WHEN an operator manually triggers a backfill, THE Orchestrator SHALL execute immediately regardless of schedule
7. WHEN a backfill run is in progress, THE Orchestrator SHALL prevent concurrent runs for the same service

### Requirement 2: Data Fetching from Multiple Sources

**User Story:** As a data engineer, I want the system to fetch data from diverse sources (HTTP endpoints, CSV files, APIs), so that I can ingest data from all three financial services.

#### Acceptance Criteria

1. THE Fetcher SHALL retrieve data from HTTP endpoints using GET requests with configurable headers
2. WHEN fetching from HTTP endpoints, THE Fetcher SHALL support authentication via API keys in request headers
3. THE Fetcher SHALL read CSV files from local filesystem paths
4. THE Fetcher SHALL read CSV files from S3 buckets using provided credentials
5. WHEN a network error occurs during fetch, THE Fetcher SHALL retry with exponential backoff (max 3 attempts)
6. WHEN a fetch operation exceeds the configured timeout (default 30 seconds), THE Fetcher SHALL abort and return an error
7. THE Fetcher SHALL stream large files instead of loading entire content into memory
8. WHEN a fetch completes successfully, THE Fetcher SHALL return the raw data as a Buffer
9. WHEN a data source is unavailable, THE Fetcher SHALL log the error and propagate it to the Error Handler

### Requirement 3: CSV and JSON Parsing

**User Story:** As a data processor, I want the system to parse CSV and JSON data with configurable formats, so that I can handle diverse data structures from different sources.

#### Acceptance Criteria

1. THE Parser SHALL parse CSV files with configurable delimiters (comma, semicolon, tab)
2. WHEN parsing CSV files, THE Parser SHALL extract headers and map columns to field names
3. THE Parser SHALL handle multiple character encodings (UTF-8, Latin-1, ISO-8859-1)
4. WHEN a CSV file contains malformed rows, THE Parser SHALL log the error and skip the row
5. THE Parser SHALL parse JSON responses from APIs into structured records
6. WHEN JSON parsing fails, THE Parser SHALL log the error with context (line number, content)
7. THE Parser SHALL detect data format (CSV or JSON) automatically from file content
8. WHEN parsing completes, THE Parser SHALL return an array of Record objects with all fields extracted

### Requirement 4: Data Validation Against Schema and Business Rules

**User Story:** As a data quality manager, I want the system to validate all data against schema and business rules before storage, so that only correct data enters the database.

#### Acceptance Criteria

1. THE Validator SHALL check that all required fields are present in each record
2. THE Validator SHALL verify that field values match expected data types (string, number, date)
3. THE Validator SHALL enforce business rules specific to each service (e.g., CNPJ format for CVM, date ranges)
4. WHEN a record fails validation, THE Validator SHALL log the error with the specific field and rule violated
5. THE Validator SHALL detect duplicate records by comparing against existing data using service-specific unique keys
6. WHEN duplicates are detected, THE Validator SHALL flag them for the Transformer to handle as updates
7. THE Validator SHALL validate entire batches of records and return a report with pass/fail counts
8. WHEN validation fails for a record, THE Validator SHALL include the record in the failure report for manual review

### Requirement 5: Data Transformation and Normalization

**User Story:** As a database architect, I want the system to normalize and transform data into the correct format for each service, so that data is consistently stored and queryable.

#### Acceptance Criteria

1. THE Transformer SHALL map parsed fields to database columns according to service-specific schemas
2. THE Transformer SHALL normalize dates to ISO 8601 format (YYYY-MM-DD)
3. THE Transformer SHALL normalize numeric values to appropriate precision (e.g., currency to 2 decimals)
4. THE Transformer SHALL normalize string values (trim whitespace, standardize case where appropriate)
5. THE Transformer SHALL generate or extract unique identifiers for each record based on service-specific keys
6. THE Transformer SHALL prepare JSONB payloads containing flexible, service-specific attributes
7. WHEN a record matches an existing unique key, THE Transformer SHALL mark it as an update operation
8. WHEN a record has a new unique key, THE Transformer SHALL mark it as an insert operation
9. THE Transformer SHALL validate that transformed records conform to the target schema before returning

### Requirement 6: CVM Service Data Storage

**User Story:** As a CVM data consumer, I want the system to store fund and credit market data with proper unique constraints, so that I can query current and historical records.

#### Acceptance Criteria

1. THE Storage Manager SHALL insert CVM records into the `cvm.records` table with fields: entity, doc_type, cnpj_key, competence_date, payload
2. WHEN a CVM record with the same (entity, doc_type, cnpj_key, competence_date) key exists, THE Storage Manager SHALL insert a new row with updated payload (append-only)
3. THE Storage Manager SHALL enforce a unique constraint on (entity, doc_type, cnpj_key, competence_date) to prevent exact duplicates
4. WHEN inserting CVM records, THE Storage Manager SHALL normalize CNPJ to 14-digit format
5. WHEN inserting CVM records, THE Storage Manager SHALL validate competence_date is a valid date
6. THE Storage Manager SHALL process CVM records in batches (minimum 1000 records per transaction)
7. WHEN a CVM batch insert fails, THE Storage Manager SHALL rollback the transaction and log the error

### Requirement 7: BACEN Service Data Storage

**User Story:** As a BACEN data consumer, I want the system to store SGS time series and PTAX exchange rates with proper unique constraints, so that I can query economic indicators and exchange rates.

#### Acceptance Criteria

1. THE Storage Manager SHALL insert SGS observations into `bacen.sgs_observations` table with fields: series_code, obs_date, value
2. WHEN an SGS observation with the same (series_code, obs_date) key exists, THE Storage Manager SHALL upsert to update the value
3. THE Storage Manager SHALL enforce a unique constraint on (series_code, obs_date) to prevent duplicates
4. THE Storage Manager SHALL insert PTAX rates into `bacen.ptax_rates` table with fields: currency_code, rate_datetime, bid, ask
5. WHEN a PTAX rate with the same (currency_code, rate_datetime) key exists, THE Storage Manager SHALL upsert to update bid and ask values
6. THE Storage Manager SHALL enforce a unique constraint on (currency_code, rate_datetime) to prevent duplicates
7. THE Storage Manager SHALL process BACEN records in batches (minimum 1000 records per transaction)
8. WHEN a BACEN batch upsert fails, THE Storage Manager SHALL rollback the transaction and log the error

### Requirement 8: B3 Service Data Storage

**User Story:** As a B3 data consumer, I want the system to store securities master data and pricing snapshots with proper unique constraints, so that I can query security information and historical pricing.

#### Acceptance Criteria

1. THE Storage Manager SHALL insert B3 securities into `b3_calc.securities` table with fields: security_code, security_type, payload
2. WHEN a B3 security with the same security_code exists, THE Storage Manager SHALL insert a new row with updated payload (append-only)
3. THE Storage Manager SHALL enforce a unique constraint on security_code to prevent duplicate securities
4. THE Storage Manager SHALL insert B3 pricing snapshots into `b3_calc.pricing_snapshots` table with fields: security_code, snapshot_date, payload
5. WHEN a B3 pricing snapshot with the same (security_code, snapshot_date) key exists, THE Storage Manager SHALL upsert to update the payload
6. THE Storage Manager SHALL enforce a unique constraint on (security_code, snapshot_date) to prevent duplicate snapshots
7. THE Storage Manager SHALL process B3 records in batches (minimum 1000 records per transaction)
8. WHEN a B3 batch upsert fails, THE Storage Manager SHALL rollback the transaction and log the error

### Requirement 9: Append-Only Data Model

**User Story:** As a compliance officer, I want the system to maintain a complete audit trail of all data changes, so that I can verify data integrity and meet regulatory requirements.

#### Acceptance Criteria

1. THE Storage Manager SHALL never physically delete records from any service schema
2. WHEN a record is updated, THE Storage Manager SHALL insert a new row with the updated values (creating a time-series history)
3. THE Storage Manager SHALL maintain unique constraints per service to prevent exact duplicate keys
4. WHEN querying historical data, THE system SHALL return all versions of a record ordered by insertion time
5. IF a record must be marked as inactive, THE Storage Manager SHALL add an inactive flag rather than deleting
6. THE Storage Manager SHALL preserve all historical versions for audit trail and compliance purposes

### Requirement 10: Error Handling and Categorization

**User Story:** As a system administrator, I want the system to categorize and handle different error types appropriately, so that I can respond to failures effectively.

#### Acceptance Criteria

1. THE Error Handler SHALL categorize errors into: Network, Parsing, Validation, Storage, and Critical
2. WHEN a Network error occurs (connection timeout, DNS failure, HTTP 4xx/5xx), THE Error Handler SHALL retry with exponential backoff (max 3 attempts)
3. WHEN a Parsing error occurs (malformed CSV/JSON, encoding issues), THE Error Handler SHALL log the error and skip the record
4. WHEN a Validation error occurs (missing fields, invalid format, business rule violation), THE Error Handler SHALL log the error and flag the record for manual review
5. WHEN a Storage error occurs (constraint violation, transaction failure), THE Error Handler SHALL rollback the transaction and retry the entire batch (max 3 attempts)
6. WHEN a Critical error occurs (database connection loss, service unavailability), THE Error Handler SHALL halt the backfill and alert the operations team immediately
7. THE Error Handler SHALL log all errors with context (record data, error type, error message, timestamp)

### Requirement 11: Retry Logic and Circuit Breaker

**User Story:** As a reliability engineer, I want the system to implement intelligent retry logic and circuit breaker patterns, so that transient failures don't cause permanent backfill failures.

#### Acceptance Criteria

1. THE Error Handler SHALL implement exponential backoff for transient errors: 1s, 2s, 4s, 8s
2. THE Error Handler SHALL limit retries to maximum 3 attempts per operation
3. WHEN an operation fails 3 times, THE Error Handler SHALL log the failure and propagate the error
4. THE Error Handler SHALL implement a circuit breaker that disables a service after 5 consecutive failures
5. WHEN a circuit breaker is triggered, THE Error Handler SHALL alert the operations team
6. WHEN an operator manually triggers a retry, THE Error Handler SHALL reset the circuit breaker and attempt the operation again
7. THE Error Handler SHALL track retry attempts and log them for debugging purposes

### Requirement 12: Logging and Audit Trail

**User Story:** As an auditor, I want the system to maintain a comprehensive audit trail of all operations, so that I can verify what data was processed and when.

#### Acceptance Criteria

1. THE Logger SHALL record every backfill run with: start time, end time, status (success/failure), records processed per service
2. THE Logger SHALL record per-record processing: fetch timestamp, parse timestamp, validate timestamp, store timestamp
3. THE Logger SHALL record all errors with: error type, error message, affected record (if applicable), timestamp
4. THE Logger SHALL record all retry attempts with: operation, attempt number, timestamp, result
5. THE Logger SHALL record data freshness: last successful backfill time per service
6. THE Logger SHALL store all logs in a structured format (JSON) for easy querying
7. WHEN a backfill completes, THE Logger SHALL generate a summary report with: total records processed, success count, failure count, error breakdown

### Requirement 13: Monitoring and Alerting

**User Story:** As an operations manager, I want the system to track key metrics and alert on anomalies, so that I can proactively respond to issues.

#### Acceptance Criteria

1. THE system SHALL track backfill duration per service (time from start to completion)
2. THE system SHALL track records processed count per service (fetched, validated, stored)
3. THE system SHALL track error rate per service (percentage of records that failed)
4. THE system SHALL track data freshness per service (time since last successful backfill)
5. THE system SHALL track external API response times for each data source
6. WHEN backfill fails after all retries, THE system SHALL alert the operations team with error details
7. WHEN data freshness exceeds threshold (e.g., 48 hours without update), THE system SHALL alert the operations team
8. WHEN error rate exceeds threshold (e.g., >5% of records), THE system SHALL alert the operations team
9. WHEN API response time degrades significantly, THE system SHALL alert the operations team
10. THE system SHALL expose metrics in a format compatible with monitoring systems (Prometheus, CloudWatch, etc.)

### Requirement 14: Supabase Integration

**User Story:** As a backend engineer, I want the system to securely connect to Supabase and manage database operations, so that data is reliably stored in the correct schemas.

#### Acceptance Criteria

1. THE Storage Manager SHALL authenticate to Supabase using a service role key
2. THE Storage Manager SHALL maintain a connection pool to manage concurrent database connections
3. THE Storage Manager SHALL isolate writes to service-specific schemas (cvm, bacen, b3_calc)
4. THE Storage Manager SHALL execute all write operations within transactions to ensure consistency
5. WHEN a transaction fails, THE Storage Manager SHALL rollback all changes and log the error
6. THE Storage Manager SHALL support batch insert and upsert operations for performance
7. THE Storage Manager SHALL handle connection timeouts and reconnect automatically
8. THE Storage Manager SHALL query the last successful backfill date per service to support incremental backfill

### Requirement 15: External Data Source Integration

**User Story:** As a data engineer, I want the system to integrate with CVM, BACEN, and B3 data sources, so that I can ingest data from all three financial services.

#### Acceptance Criteria

1. THE Fetcher SHALL support HTTP GET requests to CVM CSV endpoints
2. THE Fetcher SHALL support HTTP GET requests to BACEN SGS API endpoints
3. THE Fetcher SHALL support HTTP GET requests to BACEN PTAX API endpoints
4. THE Fetcher SHALL support HTTP GET requests to B3 CSV endpoints
5. THE Fetcher SHALL support authentication via API keys in request headers for services that require it
6. THE Fetcher SHALL support OAuth authentication for services that require it
7. THE Fetcher SHALL validate source availability before attempting to fetch data
8. WHEN a data source is unavailable, THE Fetcher SHALL log the error and skip that service for the current cycle

### Requirement 16: Configuration Management

**User Story:** As a system administrator, I want the system to support configuration for scheduling, timeouts, and retry parameters, so that I can tune the system for different environments.

#### Acceptance Criteria

1. THE system SHALL support configurable daily backfill time (e.g., 02:00 UTC)
2. THE system SHALL support configurable fetch timeout (default 30 seconds)
3. THE system SHALL support configurable retry parameters (max attempts, backoff multiplier)
4. THE system SHALL support configurable batch size for database operations (default 1000 records)
5. THE system SHALL support configurable data freshness threshold for alerting (default 48 hours)
6. THE system SHALL support configurable error rate threshold for alerting (default 5%)
7. THE system SHALL load configuration from environment variables or configuration files
8. WHEN configuration changes, THE system SHALL apply them without requiring a restart (where applicable)

### Requirement 17: Data Integrity and Validation

**User Story:** As a data quality engineer, I want the system to validate data integrity throughout the pipeline, so that only correct data reaches the database.

#### Acceptance Criteria

1. THE Validator SHALL verify that parsed records contain all required fields for the service
2. THE Validator SHALL verify that field values match expected data types
3. THE Validator SHALL verify that date fields are valid dates in expected format
4. THE Validator SHALL verify that numeric fields are valid numbers with appropriate precision
5. THE Validator SHALL verify that string fields do not exceed maximum length constraints
6. THE Validator SHALL verify CNPJ format for CVM records (14 digits, valid checksum)
7. THE Validator SHALL verify that unique keys are non-null and properly formatted
8. WHEN validation fails, THE Validator SHALL include the specific field and rule violated in the error message

### Requirement 18: Performance and Scalability

**User Story:** As a performance engineer, I want the system to process large volumes of data efficiently, so that daily backfills complete within acceptable time windows.

#### Acceptance Criteria

1. THE system SHALL process records in batches (minimum 1000 records per transaction) for efficiency
2. THE system SHALL fetch data from multiple services in parallel to reduce total execution time
3. THE system SHALL use connection pooling to reuse database connections
4. THE system SHALL stream large CSV files instead of loading entire content into memory
5. THE system SHALL leverage existing database indexes on unique key fields for fast lookups
6. THE system SHALL use bulk insert/upsert operations instead of individual record operations
7. THE system SHALL cache validation rules and column mappings to avoid repeated parsing
8. WHEN processing large datasets, THE system SHALL monitor memory usage and avoid out-of-memory errors

### Requirement 19: Security and Secrets Management

**User Story:** As a security engineer, I want the system to securely manage API keys and credentials, so that sensitive data is protected.

#### Acceptance Criteria

1. THE system SHALL store API keys in environment variables or a secrets manager (not in code)
2. THE system SHALL use HTTPS for all external API calls
3. THE system SHALL support API key rotation without code changes
4. THE system SHALL not log API keys or sensitive credentials
5. THE system SHALL use Supabase service role key for backend operations (not public key)
6. THE system SHALL support OAuth authentication for services that require it
7. THE system SHALL validate SSL certificates for all HTTPS connections
8. THE system SHALL encrypt sensitive data at rest in the database (handled by Supabase)

### Requirement 20: Operational Monitoring and Debugging

**User Story:** As a system operator, I want the system to provide detailed logs and metrics for debugging, so that I can quickly identify and resolve issues.

#### Acceptance Criteria

1. THE Logger SHALL provide structured logs in JSON format for easy parsing
2. THE Logger SHALL include trace IDs in logs to correlate related operations
3. THE Logger SHALL log at appropriate levels (DEBUG, INFO, WARN, ERROR) based on severity
4. THE Logger SHALL include stack traces for exceptions
5. THE Logger SHALL provide a way to query logs by service, date range, or error type
6. THE system SHALL expose metrics in a format compatible with monitoring systems
7. THE system SHALL provide a dashboard or API endpoint to query backfill status and metrics
8. WHEN debugging is needed, THE system SHALL support verbose logging mode for detailed operation traces

