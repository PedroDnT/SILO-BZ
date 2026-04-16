/**
 * Core types and interfaces for the Supabase Daily Data Backfill Tool
 */
/**
 * Generic record structure representing parsed data from external sources
 */
export interface DataRecord {
    [key: string]: string | number | Date | null | undefined;
}
/**
 * Type alias for flexible JSON objects
 */
export type JsonObject = Record<string, unknown>;
/**
 * Schema definition for validating records
 */
export interface Schema {
    name: string;
    fields: FieldDefinition[];
    uniqueKeys: string[];
    businessRules?: BusinessRule[];
}
/**
 * Field definition within a schema
 */
export interface FieldDefinition {
    name: string;
    type: 'string' | 'number' | 'date' | 'boolean';
    required: boolean;
    maxLength?: number;
    minValue?: number;
    maxValue?: number;
    pattern?: RegExp;
}
/**
 * Business rule for custom validation logic
 */
export interface BusinessRule {
    name: string;
    validate: (record: DataRecord) => boolean;
    errorMessage: string;
}
/**
 * Result of validating a single record or batch
 */
export interface ValidationResult {
    valid: boolean;
    errors: ValidationError[];
    record?: DataRecord;
}
/**
 * Validation error details
 */
export interface ValidationError {
    field: string;
    rule: string;
    message: string;
    value?: any;
}
/**
 * Error categories for the backfill system
 */
export declare enum ErrorCategory {
    Network = "NETWORK",
    Parsing = "PARSING",
    Validation = "VALIDATION",
    Storage = "STORAGE",
    Critical = "CRITICAL"
}
/**
 * Structured error for backfill operations
 */
export interface BackfillError {
    category: ErrorCategory;
    message: string;
    context?: DataRecord;
    timestamp: Date;
    stackTrace?: string;
    retryable: boolean;
}
/**
 * CVM record structure for storage
 */
export interface CVMRecord {
    entity: string;
    doc_type: string;
    cnpj_key: string;
    competence_date: string;
    payload: JsonObject;
}
/**
 * BACEN SGS observation structure
 */
export interface SGSObservation {
    series_code: number;
    obs_date: string;
    value: number | null;
}
/**
 * BACEN PTAX exchange rate structure
 */
export interface PTAXRate {
    currency_code: string;
    rate_datetime: string;
    bid: number;
    ask: number;
}
/**
 * B3 security master data structure
 */
export interface B3Security {
    security_code: string;
    security_type: string;
    payload: JsonObject;
}
/**
 * B3 pricing snapshot structure
 */
export interface B3PricingSnapshot {
    security_code: string;
    snapshot_date: string;
    payload: JsonObject;
}
/**
 * CSV parsing configuration
 */
export interface CSVConfig {
    delimiter: ',' | ';' | '\t';
    encoding: 'utf-8' | 'latin1' | 'iso-8859-1';
    hasHeaders: boolean;
    skipMalformed: boolean;
}
/**
 * Fetch configuration
 */
export interface FetchConfig {
    timeout: number;
    headers?: Record<string, string>;
    maxRetries: number;
    retryBackoff: number[];
}
/**
 * Storage configuration
 */
export interface StorageConfig {
    batchSize: number;
    maxRetries: number;
}
/**
 * Result of an insert operation
 */
export interface InsertResult {
    success: boolean;
    recordsInserted: number;
    errors: BackfillError[];
}
/**
 * Result of an upsert operation
 */
export interface UpsertResult {
    success: boolean;
    recordsInserted: number;
    recordsUpdated: number;
    errors: BackfillError[];
}
/**
 * Service identifier
 */
export declare enum ServiceType {
    CVM = "CVM",
    BACEN = "BACEN",
    B3 = "B3"
}
/**
 * Backfill run metadata
 */
export interface BackfillRunMetadata {
    service: ServiceType;
    startTime: Date;
    endTime?: Date;
    status: 'running' | 'success' | 'failure';
    recordsProcessed: number;
    recordsSuccess: number;
    recordsFailure: number;
    errors: BackfillError[];
}
//# sourceMappingURL=index.d.ts.map