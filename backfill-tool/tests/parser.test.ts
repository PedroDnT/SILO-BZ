/**
 * Parser Unit Tests
 * Tests for CSV and JSON parsing functionality
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { Parser } from '../src/parser/index.js';
import { BackfillError, ErrorCategory } from '../src/types/index.js';

describe('Parser', () => {
    let parser: Parser;
    let mockErrorHandler: vi.Mock;

    beforeEach(() => {
        mockErrorHandler = vi.fn();
        parser = new Parser(mockErrorHandler);
    });

    // =========================================================================
    // CSV Parsing Tests
    // =========================================================================

    describe('parseCSV', () => {
        it('should parse CSV with comma delimiter', async () => {
            const csvBuffer = Buffer.from(`name,age,city
John,30,New York
Jane,25,Los Angeles`);

            const result = await parser.parseCSV(csvBuffer, {
                delimiter: ',',
                encoding: 'utf-8',
                hasHeaders: true,
                skipMalformed: true
            });

            expect(result).toHaveLength(2);
            expect(result[0]).toEqual({ name: 'John', age: '30', city: 'New York' });
            expect(result[1]).toEqual({ name: 'Jane', age: '25', city: 'Los Angeles' });
        });

        it('should parse CSV with semicolon delimiter', async () => {
            const csvBuffer = Buffer.from(`name;age;city
John;30;New York
Jane;25;Los Angeles`);

            const result = await parser.parseCSV(csvBuffer, {
                delimiter: ';',
                encoding: 'utf-8',
                hasHeaders: true,
                skipMalformed: true
            });

            expect(result).toHaveLength(2);
            expect(result[0]).toEqual({ name: 'John', age: '30', city: 'New York' });
        });

        it('should parse CSV with tab delimiter', async () => {
            const csvBuffer = Buffer.from(`name\tage\tcity
John\t30\tNew York
Jane\t25\tLos Angeles`);

            const result = await parser.parseCSV(csvBuffer, {
                delimiter: '\t',
                encoding: 'utf-8',
                hasHeaders: true,
                skipMalformed: true
            });

            expect(result).toHaveLength(2);
            expect(result[0]).toEqual({ name: 'John', age: '30', city: 'New York' });
        });

        it('should handle CSV without headers', async () => {
            const csvBuffer = Buffer.from(`John,30,New York
Jane,25,Los Angeles`);

            const result = await parser.parseCSV(csvBuffer, {
                delimiter: ',',
                encoding: 'utf-8',
                hasHeaders: false,
                skipMalformed: true
            });

            expect(result).toHaveLength(2);
            expect(result[0]).toEqual(['John', '30', 'New York']);
        });

        it('should skip malformed CSV rows when skipMalformed is true', async () => {
            const csvBuffer = Buffer.from(`name,age,city
John,30,New York
invalid row
Jane,25,Los Angeles`);

            const result = await parser.parseCSV(csvBuffer, {
                delimiter: ',',
                encoding: 'utf-8',
                hasHeaders: true,
                skipMalformed: true
            });

            expect(result).toHaveLength(2);
            expect(mockErrorHandler).toHaveBeenCalledTimes(1);

            const errorArg = mockErrorHandler.mock.calls[0][0] as BackfillError;
            expect(errorArg.category).toBe(ErrorCategory.Parsing);
        });

        it('should handle empty CSV', async () => {
            const csvBuffer = Buffer.from('');

            const result = await parser.parseCSV(csvBuffer, {
                delimiter: ',',
                encoding: 'utf-8',
                hasHeaders: true,
                skipMalformed: true
            });

            expect(result).toHaveLength(0);
        });

        it('should handle CSV with empty lines', async () => {
            const csvBuffer = Buffer.from(`name,age

John,30

Jane,25`);

            const result = await parser.parseCSV(csvBuffer, {
                delimiter: ',',
                encoding: 'utf-8',
                hasHeaders: true,
                skipMalformed: true
            });

            expect(result).toHaveLength(2);
        });

        it('should trim whitespace from CSV values', async () => {
            const csvBuffer = Buffer.from(`name,age,city
  John  , 30 ,  New York  `);

            const result = await parser.parseCSV(csvBuffer, {
                delimiter: ',',
                encoding: 'utf-8',
                hasHeaders: true,
                skipMalformed: true
            });

            expect(result[0]).toEqual({ name: 'John', age: '30', city: 'New York' });
        });
    });

    // =========================================================================
    // JSON Parsing Tests
    // =========================================================================

    describe('parseJSON', () => {
        it('should parse JSON array', async () => {
            const jsonBuffer = Buffer.from(`[
                { "name": "John", "age": 30 },
                { "name": "Jane", "age": 25 }
            ]`);

            const result = await parser.parseJSON(jsonBuffer);

            expect(result).toHaveLength(2);
            expect(result[0]).toEqual({ name: 'John', age: 30 });
            expect(result[1]).toEqual({ name: 'Jane', age: 25 });
        });

        it('should parse JSON object with data wrapper', async () => {
            const jsonBuffer = Buffer.from(`{
                "data": [
                    { "name": "John", "age": 30 },
                    { "name": "Jane", "age": 25 }
                ]
            }`);

            const result = await parser.parseJSON(jsonBuffer);

            expect(result).toHaveLength(2);
            expect(result[0]).toEqual({ name: 'John', age: 30 });
        });

        it('should parse JSON object with results wrapper', async () => {
            const jsonBuffer = Buffer.from(`{
                "results": [
                    { "name": "John", "age": 30 }
                ]
            }`);

            const result = await parser.parseJSON(jsonBuffer);

            expect(result).toHaveLength(1);
            expect(result[0]).toEqual({ name: 'John', age: 30 });
        });

        it('should parse JSON object with records wrapper', async () => {
            const jsonBuffer = Buffer.from(`{
                "records": [
                    { "name": "John", "age": 30 }
                ]
            }`);

            const result = await parser.parseJSON(jsonBuffer);

            expect(result).toHaveLength(1);
            expect(result[0]).toEqual({ name: 'John', age: 30 });
        });

        it('should parse single JSON object as array', async () => {
            const jsonBuffer = Buffer.from(`{ "name": "John", "age": 30 }`);

            const result = await parser.parseJSON(jsonBuffer);

            expect(result).toHaveLength(1);
            expect(result[0]).toEqual({ name: 'John', age: 30 });
        });

        it('should call error handler on invalid JSON', async () => {
            const jsonBuffer = Buffer.from(`{ invalid json }`);

            await expect(parser.parseJSON(jsonBuffer)).rejects.toThrow();
            expect(mockErrorHandler).toHaveBeenCalledTimes(1);

            const errorArg = mockErrorHandler.mock.calls[0][0] as BackfillError;
            expect(errorArg.category).toBe(ErrorCategory.Parsing);
            expect(errorArg.context).toBeDefined();
        });

        it('should handle empty JSON array', async () => {
            const jsonBuffer = Buffer.from(`[]`);

            const result = await parser.parseJSON(jsonBuffer);

            expect(result).toHaveLength(0);
        });
    });

    // =========================================================================
    // Format Detection Tests
    // =========================================================================

    describe('detectFormat', () => {
        it('should detect JSON array format', async () => {
            const buffer = Buffer.from(`[{"name": "John"}]`);
            const result = await parser.detectFormat(buffer);
            expect(result).toBe('json');
        });

        it('should detect JSON object format', async () => {
            const buffer = Buffer.from(`{"name": "John"}`);
            const result = await parser.detectFormat(buffer);
            expect(result).toBe('json');
        });

        it('should detect CSV with comma delimiter', async () => {
            const buffer = Buffer.from(`name,age,city\nJohn,30,NYC`);
            const result = await parser.detectFormat(buffer);
            expect(result).toBe('csv');
        });

        it('should detect CSV with semicolon delimiter', async () => {
            const buffer = Buffer.from(`name;age;city\nJohn;30;NYC`);
            const result = await parser.detectFormat(buffer);
            expect(result).toBe('csv');
        });

        it('should detect CSV with tab delimiter', async () => {
            const buffer = Buffer.from(`name\tage\tcity\nJohn\t30\tNYC`);
            const result = await parser.detectFormat(buffer);
            expect(result).toBe('csv');
        });

        it('should default to CSV for plain text', async () => {
            const buffer = Buffer.from(`plain text without delimiters`);
            const result = await parser.detectFormat(buffer);
            expect(result).toBe('csv');
        });

        it('should detect UTF-8 BOM and handle correctly', async () => {
            const bom = Buffer.from([0xEF, 0xBB, 0xBF]);
            const content = Buffer.from(`name,age\nJohn,30`);
            const buffer = Buffer.concat([bom, content]);

            const result = await parser.detectFormat(buffer);
            expect(result).toBe('csv');
        });
    });

    // =========================================================================
    // Auto-parse Tests
    // =========================================================================

    describe('parse (auto-detect)', () => {
        it('should auto-detect and parse JSON', async () => {
            const buffer = Buffer.from(`[{"name": "John"}]`);
            const result = await parser.parse(buffer);
            expect(result).toHaveLength(1);
            expect(result[0]).toEqual({ name: 'John' });
        });

        it('should auto-detect and parse CSV', async () => {
            const buffer = Buffer.from(`name,age\nJohn,30`);
            const result = await parser.parse(buffer);
            expect(result).toHaveLength(1);
            expect(result[0]).toEqual({ name: 'John', age: '30' });
        });

        it('should use provided CSV config when CSV detected', async () => {
            const buffer = Buffer.from(`name;age\nJohn;30`);
            const result = await parser.parse(buffer, {
                delimiter: ';',
                encoding: 'utf-8',
                hasHeaders: true,
                skipMalformed: true
            });
            expect(result).toHaveLength(1);
            expect(result[0]).toEqual({ name: 'John', age: '30' });
        });
    });

    // =========================================================================
    // Column Mapping Tests
    // =========================================================================

    describe('parseCSVWithMapping', () => {
        it('should map CSV columns to field names', async () => {
            const csvBuffer = Buffer.from(`John,30,New York`);

            const result = await parser.parseCSVWithMapping(
                csvBuffer,
                {
                    delimiter: ',',
                    encoding: 'utf-8',
                    hasHeaders: false,
                    skipMalformed: true
                },
                { 0: 'name', 1: 'age', 2: 'city' }
            );

            expect(result).toHaveLength(1);
            expect(result[0]).toEqual({ name: 'John', age: '30', city: 'New York' });
        });

        it('should handle partial column mapping', async () => {
            const csvBuffer = Buffer.from(`John,30,New York,Male`);

            const result = await parser.parseCSVWithMapping(
                csvBuffer,
                {
                    delimiter: ',',
                    encoding: 'utf-8',
                    hasHeaders: false,
                    skipMalformed: true
                },
                { 0: 'name', 1: 'age' }
            );

            expect(result).toHaveLength(1);
            expect(result[0]).toEqual({ name: 'John', age: '30' });
        });

        it('should skip malformed rows with column mapping', async () => {
            const csvBuffer = Buffer.from(`John,30
invalid
Jane,25,LA`);

            const result = await parser.parseCSVWithMapping(
                csvBuffer,
                {
                    delimiter: ',',
                    encoding: 'utf-8',
                    hasHeaders: false,
                    skipMalformed: true
                },
                { 0: 'name', 1: 'age', 2: 'city' }
            );

            expect(result).toHaveLength(2);
            expect(mockErrorHandler).toHaveBeenCalledTimes(1);
        });
    });

    // =========================================================================
    // Encoding Tests
    // =========================================================================

    describe('Encoding Support', () => {
        it('should handle UTF-8 encoding', async () => {
            const csvBuffer = Buffer.from(`name,city
João,São Paulo
München,Germany`, 'utf-8');

            const result = await parser.parseCSV(csvBuffer, {
                delimiter: ',',
                encoding: 'utf-8',
                hasHeaders: true,
                skipMalformed: true
            });

            expect(result[0].name).toBe('João');
            expect(result[0].city).toBe('São Paulo');
        });

        it('should handle Latin-1 encoding', async () => {
            // Create buffer with Latin-1 encoded content
            const name = 'João'; // João in Latin-1
            const csvBuffer = Buffer.from(`name\n${name}`, 'latin1');

            const result = await parser.parseCSV(csvBuffer, {
                delimiter: ',',
                encoding: 'latin1',
                hasHeaders: true,
                skipMalformed: true
            });

            expect(result[0].name).toBeTruthy();
        });

        it('should handle ISO-8859-1 encoding', async () => {
            const name = 'Café'; // Café in ISO-8859-1
            const csvBuffer = Buffer.from(`name\n${name}`, 'iso-8859-1');

            const result = await parser.parseCSV(csvBuffer, {
                delimiter: ',',
                encoding: 'iso-8859-1',
                hasHeaders: true,
                skipMalformed: true
            });

            expect(result[0].name).toBeTruthy();
        });
    });

    // =========================================================================
    // Error Handling Tests
    // =========================================================================

    describe('Error Handling', () => {
        it('should include context in error handler calls', async () => {
            const csvBuffer = Buffer.from(`name,age
valid,row
invalid;row;with;many;columns`);

            await parser.parseCSV(csvBuffer, {
                delimiter: ',',
                encoding: 'utf-8',
                hasHeaders: true,
                skipMalformed: true
            });

            expect(mockErrorHandler).toHaveBeenCalled();
            const errorArg = mockErrorHandler.mock.calls[0][0] as BackfillError;
            expect(errorArg.context).toBeDefined();
            expect(errorArg.context.rowNumber).toBeDefined();
        });

        it('should use custom error handler when provided', async () => {
            const customHandler = vi.fn();
            const customParser = new Parser(customHandler);

            const csvBuffer = Buffer.from(`name,age
valid,row
invalid`);

            await customParser.parseCSV(csvBuffer, {
                delimiter: ',',
                encoding: 'utf-8',
                hasHeaders: true,
                skipMalformed: true
            });

            expect(customHandler).toHaveBeenCalled();
        });

        it('should use default error handler when none provided', async () => {
            const defaultParser = new Parser();
            const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => { });

            const csvBuffer = Buffer.from(`name,age
valid,row
invalid`);

            await defaultParser.parseCSV(csvBuffer, {
                delimiter: ',',
                encoding: 'utf-8',
                hasHeaders: true,
                skipMalformed: true
            });

            expect(consoleSpy).toHaveBeenCalled();
            consoleSpy.mockRestore();
        });
    });
});