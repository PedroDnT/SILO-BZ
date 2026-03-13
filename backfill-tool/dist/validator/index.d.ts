/**
 * Validator - Ensures data conforms to schema and business rules
 */
import { DataRecord, Schema, ValidationResult } from '../types/index.js';
export declare class Validator {
    validateRecord(record: DataRecord, schema: Schema): ValidationResult;
    validateBatch(records: DataRecord[], schema: Schema): ValidationResult[];
}
//# sourceMappingURL=index.d.ts.map