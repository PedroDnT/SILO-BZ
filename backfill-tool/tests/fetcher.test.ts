/**
 * Unit tests for the Data Fetcher component
 */

import { describe, it, expect, vi, beforeEach, afterEach, SpyInstance } from 'vitest';
import axios from 'axios';
import * as fs from 'fs';
import { DataFetcher, createDataFetcher } from '../src/fetcher/index.js';
import { BackfillError, ErrorCategory, FetchConfig } from '../src/types/index.js';
import { AuthType, ApiKeyAuthConfig, OAuthConfig } from '../src/fetcher/types.js';

// Spy on axios and fs modules
let axiosGetSpy: SpyInstance;
let axiosPostSpy: SpyInstance;
let axiosHeadSpy: SpyInstance;
let fsPromisesAccessSpy: SpyInstance;
let fsPromisesReadFileSpy: SpyInstance;

describe('DataFetcher', () => {
    let fetcher: DataFetcher;

    beforeEach(() => {
        vi.clearAllMocks();
        fetcher = createDataFetcher({
            timeout: 5000,
            maxRetries: 2,
            retryBackoff: [100, 200]
        });

        // Setup spies
        axiosGetSpy = vi.spyOn(axios, 'get').mockReset();
        axiosPostSpy = vi.spyOn(axios, 'post').mockReset();
        axiosHeadSpy = vi.spyOn(axios, 'head').mockReset();
        fsPromisesAccessSpy = vi.spyOn(fs.promises, 'access').mockReset();
        fsPromisesReadFileSpy = vi.spyOn(fs.promises, 'readFile').mockReset();
    });

    afterEach(() => {
        vi.restoreAllMocks();
    });

    describe('fetchFromURL', () => {
        it('should successfully fetch data from URL', async () => {
            const mockData = 'test,data\n1,2';
            const mockResponse = {
                status: 200,
                statusText: 'OK',
                data: new TextEncoder().encode(mockData)
            };
            axiosHeadSpy.mockResolvedValueOnce({ status: 200 });
            axiosGetSpy.mockResolvedValueOnce(mockResponse);

            const result = await fetcher.fetchFromURL('https://example.com/data.csv');

            expect(result.success).toBe(true);
            expect(result.data).toBeDefined();
            expect(result.sourceChecked).toBe(true);
            expect(axiosGetSpy).toHaveBeenCalledWith(
                'https://example.com/data.csv',
                expect.objectContaining({
                    timeout: 5000,
                    responseType: 'arraybuffer'
                })
            );
        });

        it('should include custom headers in request', async () => {
            const mockResponse = { status: 200, data: new ArrayBuffer(0) };
            axiosHeadSpy.mockResolvedValueOnce({ status: 200 });
            axiosGetSpy.mockResolvedValueOnce(mockResponse);

            await fetcher.fetchFromURL('https://example.com/data', {
                'X-Custom-Header': 'custom-value'
            });

            expect(axiosGetSpy).toHaveBeenCalledWith(
                'https://example.com/data',
                expect.objectContaining({
                    headers: expect.objectContaining({
                        'X-Custom-Header': 'custom-value'
                    })
                })
            );
        });

        it('should retry on network error with exponential backoff', async () => {
            const networkError = new Error('Network error');
            (networkError as any).code = 'ECONNABORTED';

            axiosHeadSpy.mockResolvedValue({ status: 200 });
            axiosGetSpy
                .mockRejectedValueOnce(networkError)
                .mockRejectedValueOnce(networkError)
                .mockResolvedValueOnce({ status: 200, data: new ArrayBuffer(0) });

            const result = await fetcher.fetchFromURL('https://example.com/data');

            expect(result.success).toBe(true);
            expect(axiosGetSpy).toHaveBeenCalledTimes(3);
        });

        it('should not retry on 4xx errors (availability check fails)', async () => {
            // When HEAD returns 4xx, availability check fails and GET is never called
            axiosHeadSpy.mockResolvedValue({ status: 404 });

            const result = await fetcher.fetchFromURL('https://example.com/data');

            expect(result.success).toBe(false);
            expect(result.error?.category).toBe(ErrorCategory.Network);
            expect(result.error?.retryable).toBe(false);
            // GET is never called because availability check failed
            expect(axiosGetSpy).not.toHaveBeenCalled();
        });

        it('should retry on 5xx errors', async () => {
            axiosHeadSpy.mockResolvedValue({ status: 200 });
            // First call returns 500, second call returns success
            axiosGetSpy
                .mockResolvedValueOnce({ status: 500, statusText: 'Internal Server Error' })
                .mockResolvedValueOnce({ status: 200, data: new ArrayBuffer(0) });

            const result = await fetcher.fetchFromURL('https://example.com/data');

            expect(result.success).toBe(true);
            expect(axiosGetSpy).toHaveBeenCalledTimes(2);
        });

        it('should handle connection timeout', async () => {
            const timeoutError = new Error('timeout of 5000ms exceeded');
            (timeoutError as any).code = 'ECONNABORTED';
            axiosHeadSpy.mockResolvedValue({ status: 200 });
            axiosGetSpy.mockRejectedValue(timeoutError);

            const result = await fetcher.fetchFromURL('https://example.com/data');

            expect(result.success).toBe(false);
            expect(result.error?.category).toBe(ErrorCategory.Network);
            expect(result.error?.message).toContain('timeout');
            expect(result.error?.retryable).toBe(true);
        });

        it('should fail after max retries exhausted', async () => {
            const networkError = new Error('Network error');
            (networkError as any).code = 'ECONNABORTED';
            axiosHeadSpy.mockResolvedValue({ status: 200 });
            axiosGetSpy.mockRejectedValue(networkError);

            const result = await fetcher.fetchFromURL('https://example.com/data');

            expect(result.success).toBe(false);
            expect(result.error?.retryable).toBe(true);
            expect(axiosGetSpy).toHaveBeenCalledTimes(3); // maxRetries + 1 initial
        });
    });

    describe('API Key Authentication', () => {
        it('should include API key in headers', async () => {
            const mockResponse = { status: 200, data: new ArrayBuffer(0) };
            axiosHeadSpy.mockResolvedValue({ status: 200 });
            axiosGetSpy.mockResolvedValue(mockResponse);

            const authConfig: ApiKeyAuthConfig = {
                type: AuthType.ApiKey,
                headerName: 'X-API-Key',
                apiKey: 'test-api-key-123'
            };

            await fetcher.fetchFromURL('https://example.com/data', {}, authConfig);

            expect(axiosGetSpy).toHaveBeenCalledWith(
                'https://example.com/data',
                expect.objectContaining({
                    headers: expect.objectContaining({
                        'X-API-Key': 'test-api-key-123'
                    })
                })
            );
        });
    });

    describe('OAuth Authentication', () => {
        it('should obtain and use OAuth token', async () => {
            const mockTokenResponse = {
                access_token: 'oauth-token-123',
                token_type: 'Bearer',
                expires_in: 3600
            };
            const mockDataResponse = { status: 200, data: new ArrayBuffer(0) };

            axiosHeadSpy.mockResolvedValue({ status: 200 });
            axiosPostSpy.mockResolvedValueOnce({ data: mockTokenResponse });
            axiosGetSpy.mockResolvedValueOnce(mockDataResponse);

            const authConfig: OAuthConfig = {
                type: AuthType.OAuth,
                tokenUrl: 'https://auth.example.com/token',
                clientId: 'client-id',
                clientSecret: 'client-secret'
            };

            await fetcher.fetchFromURL('https://example.com/data', {}, authConfig);

            // Verify POST was called to get token
            expect(axiosPostSpy).toHaveBeenCalled();
            expect(axiosPostSpy.mock.calls[0][0]).toBe('https://auth.example.com/token');

            // Verify GET was called with Bearer token
            expect(axiosGetSpy).toHaveBeenCalled();
            const getCallHeaders = axiosGetSpy.mock.calls[0][1].headers;
            expect(getCallHeaders['Authorization']).toBe('Bearer oauth-token-123');
        });

        it('should cache OAuth tokens', async () => {
            const mockTokenResponse = {
                access_token: 'cached-token',
                token_type: 'Bearer',
                expires_in: 3600
            };
            const mockDataResponse = { status: 200, data: new ArrayBuffer(0) };

            axiosHeadSpy.mockResolvedValue({ status: 200 });
            axiosPostSpy.mockResolvedValue({ data: mockTokenResponse });
            axiosGetSpy.mockResolvedValue(mockDataResponse);

            const authConfig: OAuthConfig = {
                type: AuthType.OAuth,
                tokenUrl: 'https://auth.example.com/token',
                clientId: 'client-id',
                clientSecret: 'client-secret'
            };

            // Make two requests with same config
            await fetcher.fetchFromURL('https://example.com/data1', {}, authConfig);
            await fetcher.fetchFromURL('https://example.com/data2', {}, authConfig);

            // Token endpoint should only be called once
            expect(axiosPostSpy).toHaveBeenCalledTimes(1);
            expect(axiosGetSpy).toHaveBeenCalledTimes(2);
        });
    });

    describe('fetchFromFile', () => {
        it('should successfully read file from filesystem', async () => {
            const testData = 'test,csv\n1,2';
            const encoder = new TextEncoder();
            fsPromisesAccessSpy.mockResolvedValue(undefined);
            fsPromisesReadFileSpy.mockResolvedValue(encoder.encode(testData));

            const result = await fetcher.fetchFromFile('/path/to/file.csv');

            expect(result.success).toBe(true);
            expect(result.data).toBeDefined();
            expect(fsPromisesReadFileSpy).toHaveBeenCalled();
        });

        it('should return error for non-existent file', async () => {
            fsPromisesAccessSpy.mockRejectedValue(new Error('ENOENT'));

            const result = await fetcher.fetchFromFile('/nonexistent/file.csv');

            expect(result.success).toBe(false);
            expect(result.error?.category).toBe(ErrorCategory.Parsing);
            expect(result.error?.retryable).toBe(false);
        });
    });

    describe('Error Handling', () => {
        it('should propagate errors to error handler', async () => {
            const mockErrorHandler = {
                logError: vi.fn()
            };
            fetcher.setErrorHandler(mockErrorHandler as any);

            axiosHeadSpy.mockResolvedValue({ status: 200 });
            axiosGetSpy.mockRejectedValue(new Error('Network failure'));

            await fetcher.fetchFromURL('https://example.com/data');

            expect(mockErrorHandler.logError).toHaveBeenCalled();
        });

        it('should handle unknown error types', async () => {
            axiosHeadSpy.mockResolvedValue({ status: 200 });
            axiosGetSpy.mockRejectedValue('string error');

            const result = await fetcher.fetchFromURL('https://example.com/data');

            expect(result.success).toBe(false);
            expect(result.error?.category).toBe(ErrorCategory.Critical);
        });
    });

    describe('Source Availability', () => {
        it('should skip fetch if source unavailable', async () => {
            axiosHeadSpy.mockResolvedValue({ status: 503 });

            const result = await fetcher.fetchFromURL('https://example.com/data');

            expect(result.success).toBe(false);
            expect(result.error?.category).toBe(ErrorCategory.Network);
            expect(axiosGetSpy).not.toHaveBeenCalled();
        });
    });

    describe('Configuration', () => {
        it('should use default configuration', () => {
            const defaultFetcher = new DataFetcher();
            expect(defaultFetcher).toBeDefined();
        });

        it('should merge custom configuration with defaults', () => {
            const customFetcher = createDataFetcher({
                timeout: 60000,
                maxRetries: 5
            });
            expect(customFetcher).toBeDefined();
        });
    });

    describe('Token Cache', () => {
        it('should clear OAuth token cache', async () => {
            const mockTokenResponse = {
                access_token: 'token',
                token_type: 'Bearer',
                expires_in: 3600
            };
            const mockDataResponse = { status: 200, data: new ArrayBuffer(0) };

            axiosHeadSpy.mockResolvedValue({ status: 200 });
            axiosPostSpy.mockResolvedValue({ data: mockTokenResponse });
            axiosGetSpy.mockResolvedValue(mockDataResponse);

            const authConfig: OAuthConfig = {
                type: AuthType.OAuth,
                tokenUrl: 'https://auth.example.com/token',
                clientId: 'client-id',
                clientSecret: 'client-secret'
            };

            await fetcher.fetchFromURL('https://example.com/data', {}, authConfig);
            fetcher.clearTokenCache();

            // Next request should get a new token
            await fetcher.fetchFromURL('https://example.com/data2', {}, authConfig);
            expect(axiosPostSpy).toHaveBeenCalledTimes(2);
        });
    });
});

describe('DataFetcher Factory', () => {
    it('should create DataFetcher with default config', () => {
        const fetcher = createDataFetcher();
        expect(fetcher).toBeInstanceOf(DataFetcher);
    });

    it('should create DataFetcher with custom config', () => {
        const fetcher = createDataFetcher({
            timeout: 60000,
            maxRetries: 5,
            retryBackoff: [1000, 2000, 4000, 8000]
        });
        expect(fetcher).toBeInstanceOf(DataFetcher);
    });
});