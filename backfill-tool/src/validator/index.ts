/**
 * Validator - Ensures data conforms to schema and business rules
 */

import { DataRecord, Schema, ValidationResult } from '../types/index.js';

export class Validator {
    validateRecord(record: DataRecord, schema: Schema): ValidationResult {
        throw new Error('Not implemented');
    }

    validateBatch(records: DataRecord[], schema: Schema): ValidationResult[] {
        throw new Error('Not implemented');
    }
}