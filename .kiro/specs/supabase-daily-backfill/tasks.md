# Implementation Plan: Supabase Daily Data Backfill Tool

## Overview

This implementation plan covers the development of a data ingestion system that fetches financial data from CVM, BACEN, and B3 sources, validates and transforms it, and stores it in Supabase with append-only semantics. The system is built with TypeScript and follows a modular architecture with six core components: Data Fetcher, Parser, Validator, Transformer, Storage Manager, and Error Handler.

## Tasks

- [ ] 1. Set up project structure and core types
  - Create TypeScript project with tsconfig.json
  - Define core types and interfaces (Record, Schema, ValidationResult, BackfillError)
  - Set up directory structure (src/fetcher, src/parser, src/validator, src/transformer, src/storage, src/error-handler)
  - Install dependencies (Supabase client, CSV parser, HTTP client, logging library)
  - Configure environment variables for Supabase connection and API keys
  - _Requirements: 14.1, 14.2, 16.7, 19.1_

- [ ] 2. Implement Data Fetcher component
  - [ ] 2.1 Create DataFetcher class with HTTP and file I/O methods
    - Implement fetchFromURL method with configurable headers and timeout
    - Implement fetchFromFile method for local CSV files
    - Add support for streaming large files to avoid memory issues
    - _Requirements: 2.1, 2.2, 2.3, 2.7, 2.8_
  
  - [ ] 2.2 Add authentication support for external APIs
    - Support API key authentication in request headers
    - Support OAuth authentication flow
    - Validate source availability before fetching
    - _Requirements: 2.2, 15.5, 15.6, 15.7_
  
  - [ ] 2.3 Implement network error handling with retry logic
    - Add exponential backoff retry for network errors (max 3 attempts)
    - Handle connection timeouts (default 30 seconds)
    - Log errors and propagate to Error Handler
    - _Requirements: 2.5, 2.6, 2.9, 10.2, 11.1, 11.2_
  
  - [ ]* 2.4 Write unit tests for Data Fetcher
    - Test successful HTTP fetch with various response types
    - Test file reading from local filesystem
    - Test authentication header injection
    - Test timeout handling and retry logic
    - Test error propagation for unavailable sources
    - _Requirements: 2.1, 2.5, 2.6, 2.9_

- [ ] 3. Implement Parser component
  - [ ] 3.1 Create Parser class with CSV and JSON parsing methods
    - Implement parseCSV method with configurable delimiters
    - Implement parseJSON method for API responses
    - Add automatic format detection (CSV vs JSON)
    - Extract headers and map columns to field names
    - _Requirements: 3.1, 3.2, 3.5, 3.7_
  
  - [ ] 3.2 Add encoding support and error handling
    - Support multiple character encodings (UTF-8, Latin-1, ISO-8859-1)
    - Skip malformed CSV rows and log errors with context
    - Handle JSON parsing errors with line number and content
    - Return array of Record objects with all fields extracted
    - _Requirements: 3.3, 3.4, 3.6, 3.8_
  
  - [ ]* 3.3 Write unit tests for Parser
    - Test CSV parsing with different delimiters (comma, semicolon, tab)
    - Test JSON parsing with valid and invalid data
    - Test encoding detection and conversion
    - Test malformed row handling and error logging
    - Test header extraction and column mapping
    - _Requirements: 3.1, 3.2, 3.4, 3.6_

- [ ] 4. Implement Validator component
  - [ ] 4.1 Create Validator class with schema validation methods
    - Implement validateRecord method for single record validation
    - Implement validateBatch method for batch validation
    - Check required fields presence
    - Verify data types (string, number, date)
    - _Requirements: 4.1, 4.2, 17.1, 17.2_
  
  - [ ] 4.2 Add business rule validation
    - Validate CNPJ format for CVM records (14 digits, valid checksum)
    - Validate date ranges and formats
    - Validate numeric precision and ranges
    - Validate string length constraints
    - _Requirements: 4.3, 17.3, 17.4, 17.5, 17.6_
  
  - [ ] 4.3 Implement duplicate detection
    - Detect duplicates using service-specific unique keys
    - Flag duplicates for Transformer to handle as updates
    - Return validation report with pass/fail counts
    - _Requirements: 4.5, 4.6, 4.7_
  
  - [ ] 4.4 Add detailed error reporting
    - Log validation errors with specific field and rule violated
    - Include record data in failure report for manual review
    - Verify unique keys are non-null and properly formatted
    - _Requirements: 4.4, 4.8, 17.7, 17.8_
  
  - [ ]* 4.5 Write unit tests for Validator
    - Test required field validation
    - Test data type validation
    - Test CNPJ format validation with valid and invalid checksums
    - Test date and numeric validation
    - Test duplicate detection logic
    - Test error reporting with specific field violations
    - _Requirements: 4.1, 4.2, 4.3, 17.6_

- [ ] 5. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 6. Implement Transformer component
  - [ ] 6.1 Create Transformer class with service-specific transformation methods
    - Implement transformToCVMRecord method
    - Implement transformToBAC ENData method (SGS and PTAX)
    - Implement transformToB3Data method (Securities and Pricing)
    - Map parsed fields to database columns per service schema
    - _Requirements: 5.1, 5.9_
  
  - [ ] 6.2 Add data normalization logic
    - Normalize dates to ISO 8601 format (YYYY-MM-DD)
    - Normalize numeric values to appropriate precision
    - Normalize string values (trim whitespace, standardize case)
    - Generate JSONB payloads for flexible attributes
    - _Requirements: 5.2, 5.3, 5.4, 5.6_
  
  - [ ] 6.3 Implement insert vs update detection
    - Generate unique identifiers based on service-specific keys
    - Mark records as insert when unique key is new
    - Mark records as update when unique key exists
    - Validate transformed records conform to target schema
    - _Requirements: 5.5, 5.7, 5.8, 5.9_
  
  - [ ]* 6.4 Write unit tests for Transformer
    - Test CVM record transformation with CNPJ normalization
    - Test BACEN SGS and PTAX transformation
    - Test B3 securities and pricing transformation
    - Test date normalization to ISO 8601
    - Test numeric precision normalization
    - Test insert vs update detection logic
    - _Requirements: 5.1, 5.2, 5.3, 5.7, 5.8_

- [ ] 7. Implement Storage Manager component
  - [ ] 7.1 Create StorageManager class with Supabase connection
    - Initialize Supabase client with service role key
    - Set up connection pool for concurrent operations
    - Implement schema isolation (cvm, bacen, b3_calc)
    - Handle connection timeouts and automatic reconnection
    - _Requirements: 14.1, 14.2, 14.3, 14.7_
  
  - [ ] 7.2 Implement CVM data storage methods
    - Create insertCVMRecords method for batch insert
    - Enforce unique constraint on (entity, doc_type, cnpj_key, competence_date)
    - Normalize CNPJ to 14-digit format
    - Validate competence_date is valid
    - Process records in batches (minimum 1000 per transaction)
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7_
  
  - [ ] 7.3 Implement BACEN data storage methods
    - Create upsertBAC ENData method for SGS observations
    - Enforce unique constraint on (series_code, obs_date)
    - Create upsertBAC ENData method for PTAX rates
    - Enforce unique constraint on (currency_code, rate_datetime)
    - Process records in batches (minimum 1000 per transaction)
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 7.8_
  
  - [ ] 7.4 Implement B3 data storage methods
    - Create upsertB3Data method for securities
    - Enforce unique constraint on security_code
    - Create upsertB3Data method for pricing snapshots
    - Enforce unique constraint on (security_code, snapshot_date)
    - Process records in batches (minimum 1000 per transaction)
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8_
  
  - [ ] 7.5 Implement transaction management and error handling
    - Execute all write operations within transactions
    - Rollback transactions on failure and log errors
    - Support batch insert and upsert operations
    - Query last successful backfill date per service
    - _Requirements: 14.4, 14.5, 14.6, 14.8_
  
  - [ ] 7.6 Implement append-only semantics
    - Never physically delete records
    - Insert new rows for updates (time-series history)
    - Maintain unique constraints per service
    - Preserve all historical versions for audit trail
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6_
  
  - [ ]* 7.7 Write unit tests for Storage Manager
    - Test CVM record insertion with unique constraint enforcement
    - Test BACEN upsert logic for SGS and PTAX
    - Test B3 upsert logic for securities and pricing
    - Test transaction rollback on failure
    - Test append-only behavior (no deletes, insert for updates)
    - Test batch processing with 1000+ records
    - _Requirements: 6.2, 6.3, 7.2, 7.5, 8.2, 8.5, 9.1, 9.2_

- [ ] 8. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 9. Implement Error Handler component
  - [ ] 9.1 Create ErrorHandler class with error categorization
    - Categorize errors into: Network, Parsing, Validation, Storage, Critical
    - Implement logError method with context (record, type, message, timestamp)
    - Track retry attempts and log them for debugging
    - _Requirements: 10.1, 10.7, 11.7_
  
  - [ ] 9.2 Implement retry logic with exponential backoff
    - Create retryWithBackoff method with exponential backoff (1s, 2s, 4s, 8s)
    - Limit retries to maximum 3 attempts per operation
    - Log failure after 3 attempts and propagate error
    - _Requirements: 10.2, 11.1, 11.2, 11.3_
  
  - [ ] 9.3 Implement error-specific handling strategies
    - Network errors: Retry with exponential backoff
    - Parsing errors: Log and skip record
    - Validation errors: Log and flag for manual review
    - Storage errors: Rollback transaction and retry batch
    - Critical errors: Halt backfill and alert operations team
    - _Requirements: 10.2, 10.3, 10.4, 10.5, 10.6_
  
  - [ ] 9.4 Implement circuit breaker pattern
    - Disable service after 5 consecutive failures
    - Alert operations team when circuit breaker triggers
    - Support manual retry to reset circuit breaker
    - _Requirements: 11.4, 11.5, 11.6_
  
  - [ ]* 9.5 Write unit tests for Error Handler
    - Test error categorization for all error types
    - Test exponential backoff retry logic
    - Test max retry limit enforcement
    - Test circuit breaker triggering after 5 failures
    - Test circuit breaker reset on manual retry
    - Test error logging with context
    - _Requirements: 10.1, 10.2, 11.1, 11.2, 11.4_

- [ ] 10. Implement Logging and Monitoring
  - [ ] 10.1 Create Logger class with structured logging
    - Implement structured JSON logging
    - Include trace IDs for operation correlation
    - Support log levels (DEBUG, INFO, WARN, ERROR)
    - Include stack traces for exceptions
    - _Requirements: 12.6, 20.1, 20.2, 20.3, 20.4_
  
  - [ ] 10.2 Add backfill run logging
    - Log backfill run metadata (start time, end time, status, records processed)
    - Log per-record processing timestamps (fetch, parse, validate, store)
    - Log all errors with error type, message, affected record, timestamp
    - Log all retry attempts with operation, attempt number, result
    - _Requirements: 12.1, 12.2, 12.3, 12.4_
  
  - [ ] 10.3 Add data freshness tracking
    - Track last successful backfill time per service
    - Generate summary report on backfill completion
    - Include total records processed, success count, failure count, error breakdown
    - _Requirements: 12.5, 12.7_
  
  - [ ] 10.4 Implement metrics tracking
    - Track backfill duration per service
    - Track records processed count per service
    - Track error rate per service (percentage of failed records)
    - Track data freshness per service
    - Track external API response times
    - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.5_
  
  - [ ] 10.5 Add alerting logic
    - Alert on backfill failure after all retries
    - Alert when data freshness exceeds threshold (48 hours)
    - Alert when error rate exceeds threshold (5%)
    - Alert when API response time degrades significantly
    - _Requirements: 13.6, 13.7, 13.8, 13.9_
  
  - [ ] 10.6 Expose metrics for monitoring systems
    - Expose metrics in Prometheus format
    - Provide API endpoint to query backfill status and metrics
    - Support verbose logging mode for debugging
    - _Requirements: 13.10, 20.6, 20.7, 20.8_
  
  - [ ]* 10.7 Write unit tests for Logger and Monitoring
    - Test structured JSON log output
    - Test trace ID correlation across operations
    - Test log level filtering
    - Test metrics tracking and calculation
    - Test alerting threshold logic
    - _Requirements: 12.6, 13.3, 13.7, 13.8_

- [ ] 11. Implement Orchestrator component
  - [ ] 11.1 Create Orchestrator class for scheduling and coordination
    - Schedule backfill runs at configurable daily time
    - Trigger backfill for all three services (CVM, BACEN, B3) in parallel
    - Log run metadata on completion
    - Support manual trigger for immediate execution
    - _Requirements: 1.1, 1.2, 1.3, 1.6_
  
  - [ ] 11.2 Add retry and failure handling
    - Implement exponential backoff retry for failed runs (max 3 attempts)
    - Alert operations team on failure after all retries
    - Prevent concurrent runs for the same service
    - _Requirements: 1.4, 1.5, 1.7_
  
  - [ ] 11.3 Integrate all components into pipeline
    - Wire Fetcher → Parser → Validator → Transformer → Storage Manager
    - Pass errors to Error Handler for categorization and retry
    - Log all operations through Logger
    - Track metrics through Monitoring
    - _Requirements: 2.9, 10.7, 12.1, 13.1_
  
  - [ ]* 11.4 Write integration tests for Orchestrator
    - Test daily scheduling trigger
    - Test parallel execution of three services
    - Test manual trigger execution
    - Test concurrent run prevention
    - Test retry logic on failure
    - Test end-to-end pipeline flow
    - _Requirements: 1.1, 1.2, 1.6, 1.7_

- [ ] 12. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 13. Implement Configuration Management
  - [ ] 13.1 Create Config class for environment-based configuration
    - Load configuration from environment variables
    - Support configurable daily backfill time (default 02:00 UTC)
    - Support configurable fetch timeout (default 30 seconds)
    - Support configurable retry parameters (max attempts, backoff multiplier)
    - _Requirements: 16.1, 16.2, 16.3, 16.7_
  
  - [ ] 13.2 Add operational configuration
    - Support configurable batch size (default 1000 records)
    - Support configurable data freshness threshold (default 48 hours)
    - Support configurable error rate threshold (default 5%)
    - Apply configuration changes without restart where applicable
    - _Requirements: 16.4, 16.5, 16.6, 16.8_
  
  - [ ]* 13.3 Write unit tests for Configuration
    - Test environment variable loading
    - Test default value fallback
    - Test configuration validation
    - Test dynamic configuration updates
    - _Requirements: 16.7, 16.8_

- [ ] 14. Implement External Data Source Integration
  - [ ] 14.1 Create service-specific fetcher configurations
    - Configure CVM CSV endpoint URLs and authentication
    - Configure BACEN SGS API endpoint and parameters
    - Configure BACEN PTAX API endpoint and parameters
    - Configure B3 CSV endpoint URLs and authentication
    - _Requirements: 15.1, 15.2, 15.3, 15.4_
  
  - [ ] 14.2 Add authentication support for each service
    - Support API key authentication for CVM (if required)
    - Support public API access for BACEN (no auth)
    - Support API key or OAuth for B3 (if required)
    - Validate source availability before fetching
    - _Requirements: 15.5, 15.6, 15.7, 15.8_
  
  - [ ]* 14.3 Write integration tests for external sources
    - Test CVM CSV endpoint fetch with authentication
    - Test BACEN SGS API fetch and JSON parsing
    - Test BACEN PTAX API fetch and JSON parsing
    - Test B3 CSV endpoint fetch with authentication
    - Test error handling for unavailable sources
    - _Requirements: 15.1, 15.2, 15.3, 15.4, 15.8_

- [ ] 15. Implement Security and Secrets Management
  - [ ] 15.1 Set up secrets management
    - Store API keys in environment variables
    - Support API key rotation without code changes
    - Use Supabase service role key (not public key)
    - _Requirements: 19.1, 19.3, 19.5_
  
  - [ ] 15.2 Add security best practices
    - Use HTTPS for all external API calls
    - Validate SSL certificates for HTTPS connections
    - Never log API keys or sensitive credentials
    - Support OAuth authentication where required
    - _Requirements: 19.2, 19.4, 19.6, 19.7_
  
  - [ ]* 15.3 Write security tests
    - Test that API keys are not logged
    - Test HTTPS enforcement for external calls
    - Test SSL certificate validation
    - Test environment variable loading for secrets
    - _Requirements: 19.2, 19.4, 19.7_

- [ ] 16. Implement Performance Optimizations
  - [ ] 16.1 Add batch processing optimizations
    - Process records in batches (minimum 1000 per transaction)
    - Use bulk insert/upsert operations
    - Leverage database indexes on unique key fields
    - _Requirements: 18.1, 18.5, 18.6_
  
  - [ ] 16.2 Add parallel processing and streaming
    - Fetch data from multiple services in parallel
    - Stream large CSV files to avoid memory issues
    - Use connection pooling for database operations
    - Cache validation rules and column mappings
    - _Requirements: 18.2, 18.3, 18.4, 18.7_
  
  - [ ] 16.3 Add memory management
    - Monitor memory usage during large dataset processing
    - Implement backpressure to avoid out-of-memory errors
    - Release resources after batch processing
    - _Requirements: 18.8_
  
  - [ ]* 16.4 Write performance tests
    - Test batch processing with 10,000+ records
    - Test parallel service execution
    - Test memory usage with large CSV files
    - Test connection pool efficiency
    - _Requirements: 18.1, 18.2, 18.4, 18.8_

- [ ] 17. Final integration and wiring
  - [ ] 17.1 Wire all components together in main entry point
    - Initialize all components with configuration
    - Set up dependency injection for testability
    - Create main backfill execution function
    - Add graceful shutdown handling
    - _Requirements: 1.1, 1.2, 14.1, 16.7_
  
  - [ ] 17.2 Add CLI interface for manual execution
    - Support command-line arguments for service selection
    - Support dry-run mode for testing
    - Support verbose logging flag
    - Display progress and summary on completion
    - _Requirements: 1.6, 20.8_
  
  - [ ]* 17.3 Write end-to-end integration tests
    - Test complete backfill cycle for CVM service
    - Test complete backfill cycle for BACEN service
    - Test complete backfill cycle for B3 service
    - Test error handling and recovery across pipeline
    - Test append-only semantics with duplicate data
    - Test parallel execution of all three services
    - _Requirements: 1.2, 9.1, 9.2, 18.2_

- [ ] 18. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- The implementation uses TypeScript as specified in the design document
- All components follow the interfaces defined in the design document
- Focus on core functionality first, then add monitoring and optimization
