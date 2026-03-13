/**
 * Parser - Converts raw data (CSV, JSON) into structured records
 */

import { DataRecord, CSVConfig } from '../types/index.js';

export class Parser {
    async parseCSV(buffer: Buffer, config: CSVConfig): Promise<DataRecord[]> {
        throw new Error('Not implemented');
    }

    async parseJSON(buffer: Buffer): Promise<DataRecord[]> {
        throw new Error('Not implemented');
    }

    async detectFormat(buffer: Buffer): Promise<'csv' | 'json'> {
        throw new Error('Not implemented');
    }
}