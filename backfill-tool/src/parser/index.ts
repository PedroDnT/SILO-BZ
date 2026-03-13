/**
 * Parser - Converts raw data (CSV, JSON) into structured records
 * 
 * Supports:
 * - CSV parsing with configurable delimiters (comma, semicolon, tab)
 * - JSON parsing for API responses
 * - Automatic format detection (CSV vs JSON)
 * - Multiple character encodings (UTF-8, Latin-1, ISO-8859-1)
 * - Error handling with context for malformed rows
 */

import { parse } from 'csv-parse';
import {
    DataRecord,
    CSVConfig,
    BackfillError,
    ErrorCategory
} from '../types/index.js';

// ============================================================================
// Encoding Utilities
// ============================================================================

type Encoding = 'utf-8' | 'latin1' | 'iso-8859-1';

/**
 * Convert Buffer to string with specified encoding
 */
function decodeBuffer(buffer: Buffer, encoding: Encoding): string {
    switch (encoding) {
        case 'utf-8':
            return buffer.toString('utf-8');
        case 'latin1':
        case 'iso-8859-1':
            return buffer.toString('latin1');
        default:
            return buffer.toString('utf-8');
    }
}

/**
 * Detect encoding from Buffer using BOM and byte patterns
 */
function detectEncoding(buffer: Buffer): Encoding {
    // Check for UTF-8 BOM
    if (buffer.length >= 3 &&
        buffer[0] === 0xEF &&
        buffer[1] === 0xBB &&
        buffer[2] === 0xBF) {
        return 'utf-8';
    }

    // Check for UTF-16 BE BOM
    if (buffer.length >= 2 && buffer[0] === 0xFE && buffer[1] === 0xFF) {
        return 'utf-8'; // UTF-16 BE, fall back to UTF-8
    }

    // Check for UTF-16 LE BOM
    if (buffer.length >= 2 && buffer[0] === 0xFF && buffer[1] === 0xFE) {
        return 'utf-8'; // UTF-16 LE, fall back to UTF-8
    }

    // Check for high-byte characters (likely Latin-1 or ISO-8859-1)
    for (let i = 0; i < Math.min(buffer.length, 100); i++) {
        if (buffer[i] > 127) {
            // High-byte character found, likely not pure ASCII/UTF-8
            return 'latin1';
        }
    }

    return 'utf-8';
}

// ============================================================================
// Parser Implementation
// ============================================================================

export class Parser {
    private errorHandler: (error: BackfillError) => void;

    constructor(errorHandler?: (error: BackfillError) => void) {
        this.errorHandler = errorHandler || this.defaultErrorHandler;
    }

    /**
     * Default error handler that logs to console
     */
    private defaultErrorHandler(error: BackfillError): void {
        console.error(`[Parser Error] ${error.category}: ${error.message}`, {
            context: error.context,
            timestamp: error.timestamp
        });
    }

    /**
     * Parse CSV data from buffer with configurable delimiters
     * 
     * @param buffer - Raw CSV data as Buffer
     * @param config - CSV parsing configuration
     * @returns Promise<Array<DataRecord>> - Parsed records
     */
    async parseCSV(buffer: Buffer, config: CSVConfig): Promise<DataRecord[]> {
        const records: DataRecord[] = [];
        const content = decodeBuffer(buffer, config.encoding);

        return new Promise((resolve, reject) => {
            const parser = parse({
                delimiter: config.delimiter,
                columns: config.hasHeaders,
                skip_empty_lines: true,
                trim: true,
                relax_column_count: true
            });

            let rowNumber = 0;

            parser.on('readable', () => {
                let record;
                while ((record = parser.read()) !== null) {
                    rowNumber++;
                    records.push(record as DataRecord);
                }
            });

            parser.on('error', (error) => {
                if (config.skipMalformed) {
                    const parseError: BackfillError = {
                        category: ErrorCategory.Parsing,
                        message: `CSV parsing error at row ${rowNumber}: ${error.message}`,
                        context: { rowNumber, error: error.message },
                        timestamp: new Date(),
                        retryable: false
                    };
                    this.errorHandler(parseError);
                } else {
                    reject(error);
                }
            });

            parser.on('end', () => {
                resolve(records);
            });

            parser.write(content);
            parser.end();
        });
    }

    /**
     * Parse JSON data from buffer
     * 
     * @param buffer - Raw JSON data as Buffer
     * @returns Promise<Array<DataRecord>> - Parsed records
     */
    async parseJSON(buffer: Buffer): Promise<DataRecord[]> {
        const content = buffer.toString('utf-8');
        const records: DataRecord[] = [];
        let lineNumber = 0;

        try {
            const parsed = JSON.parse(content);

            // Handle different JSON structures
            if (Array.isArray(parsed)) {
                // Direct array of records
                return parsed as DataRecord[];
            } else if (parsed.data && Array.isArray(parsed.data)) {
                // API response with data wrapper
                return parsed.data as DataRecord[];
            } else if (parsed.results && Array.isArray(parsed.results)) {
                // API response with results wrapper
                return parsed.results as DataRecord[];
            } else if (parsed.records && Array.isArray(parsed.records)) {
                // API response with records wrapper
                return parsed.records as DataRecord[];
            } else if (typeof parsed === 'object' && parsed !== null) {
                // Single object, wrap in array
                return [parsed as DataRecord];
            } else {
                throw new Error('JSON content is not an array or valid object');
            }
        } catch (error) {
            const parseError: BackfillError = {
                category: ErrorCategory.Parsing,
                message: `JSON parsing error at line ${lineNumber}: ${(error as Error).message}`,
                context: {
                    lineNumber,
                    content: content.substring(0, 200) // First 200 chars for context
                },
                timestamp: new Date(),
                stackTrace: (error as Error).stack,
                retryable: false
            };
            this.errorHandler(parseError);
            throw error;
        }
    }

    /**
     * Detect data format (CSV or JSON) from buffer content
     * 
     * @param buffer - Raw data as Buffer
     * @returns Promise<'csv' | 'json'> - Detected format
     */
    async detectFormat(buffer: Buffer): Promise<'csv' | 'json'> {
        const content = decodeBuffer(buffer, detectEncoding(buffer));
        const trimmed = content.trim();

        // Check for JSON indicators
        if (trimmed.startsWith('{') || trimmed.startsWith('[')) {
            try {
                // Verify it's valid JSON by attempting parse
                JSON.parse(trimmed);
                return 'json';
            } catch {
                // Not valid JSON, likely CSV
                return 'csv';
            }
        }

        // Check for common CSV patterns
        // CSV typically has multiple lines with delimiters
        const lines = trimmed.split(/\r?\n/).filter(line => line.trim());
        if (lines.length > 0) {
            const firstLine = lines[0];
            const csvDelimiters = [',', ';', '\t'];

            for (const delimiter of csvDelimiters) {
                if (firstLine.includes(delimiter)) {
                    return 'csv';
                }
            }
        }

        // Default to CSV if no clear JSON structure
        return 'csv';
    }

    /**
     * Parse data with automatic format detection
     * 
     * @param buffer - Raw data as Buffer
     * @param csvConfig - Optional CSV configuration (used if CSV detected)
     * @returns Promise<Array<DataRecord>> - Parsed records
     */
    async parse(buffer: Buffer, csvConfig?: CSVConfig): Promise<DataRecord[]> {
        const format = await this.detectFormat(buffer);

        if (format === 'json') {
            return this.parseJSON(buffer);
        } else {
            // Use default CSV config if not provided
            const config = csvConfig || {
                delimiter: ',' as const,
                encoding: 'utf-8' as const,
                hasHeaders: true,
                skipMalformed: true
            };
            return this.parseCSV(buffer, config);
        }
    }

    /**
     * Parse CSV with custom column mapping
     * Maps CSV columns to specific field names
     * 
     * @param buffer - Raw CSV data as Buffer
     * @param config - CSV parsing configuration
     * @param columnMapping - Map of column index to field name
     * @returns Promise<Array<DataRecord>> - Parsed records with mapped fields
     */
    async parseCSVWithMapping(
        buffer: Buffer,
        config: CSVConfig,
        columnMapping: Record<number, string>
    ): Promise<DataRecord[]> {
        const records: DataRecord[] = [];
        const content = decodeBuffer(buffer, config.encoding);

        return new Promise((resolve, reject) => {
            const parser = parse({
                delimiter: config.delimiter,
                columns: false, // Use index-based mapping
                skip_empty_lines: true,
                trim: true,
                relax_column_count: true
            });

            let rowNumber = 0;

            parser.on('readable', () => {
                let record;
                while ((record = parser.read()) !== null) {
                    rowNumber++;

                    // Apply column mapping
                    const mappedRecord: DataRecord = {};
                    Object.entries(columnMapping).forEach(([index, fieldName]) => {
                        const idx = parseInt(index, 10);
                        if (record[idx] !== undefined) {
                            mappedRecord[fieldName] = record[idx];
                        }
                    });

                    records.push(mappedRecord);
                }
            });

            parser.on('error', (error) => {
                if (config.skipMalformed) {
                    const parseError: BackfillError = {
                        category: ErrorCategory.Parsing,
                        message: `CSV parsing error at row ${rowNumber}: ${error.message}`,
                        context: { rowNumber, error: error.message },
                        timestamp: new Date(),
                        retryable: false
                    };
                    this.errorHandler(parseError);
                } else {
                    reject(error);
                }
            });

            parser.on('end', () => {
                resolve(records);
            });

            parser.write(content);
            parser.end();
        });
    }
}