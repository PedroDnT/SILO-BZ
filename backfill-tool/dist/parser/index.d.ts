/**
 * Parser - Converts raw data (CSV, JSON) into structured records
 */
import { DataRecord, CSVConfig } from '../types/index.js';
export declare class Parser {
    parseCSV(buffer: Buffer, config: CSVConfig): Promise<DataRecord[]>;
    parseJSON(buffer: Buffer): Promise<DataRecord[]>;
    detectFormat(buffer: Buffer): Promise<'csv' | 'json'>;
}
//# sourceMappingURL=index.d.ts.map