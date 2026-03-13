/**
 * Unit tests for the Data Fetcher component
 */

import { describe, it, expect, vi, beforeEach, afterEach, Mock } from 'vitest';
import axios, { AxiosError, AxiosHeaders } from 'axios';
import * as fs from 'fs';
import { DataFetcher, createDataFetcher } from '../src/fetcher/index.js';
import { BackfillError, ErrorCategory, FetchConfig } from '../src/types/index.js';
import { AuthType, ApiKeyAuthConfig, OAuthConfig } from '../src/fetcher/types.js';

// Mock axios
vi.mock('axios');
// Mock fs
vi.mock('fs', () => ({
    promises: {
        access: vi.fn(),
        readFile: vi.fn()
    },
    constants: {
        F_OK: undefined
    },
    createReadStream: vi.fn()
}));

describe('DataFetcher', () => {
    let fetcher: DataFetcher;
    let mockAxios: Mock;
    let mockFs: typeof fs;

    beforeEach(() => {
        vi.clearAllMocks();
        fetcher = createDataFetcher({
            timeout: 5000,
            maxRetries: 2,
            retryBackoff: [100, 200]
        });
        mockAxios = vi.mocked(axios);
        mockFs = require('fs');
    });

    afterEach(() => {
        vi.resetAllMocks();
    });

    describe('fetchFromURL', () => {
        it('should successfully fetch data from URL', async () => {
            const mockData = 'test,data\n1,2';
            const mockResponse = {
                status: 200,
                statusText: 'OK',
                data: new TextEncoder().encode(mockData)
            };
            mockAxios.get.mockResolvedValueOnce(mockResponse);

            const result = await fetcher.fetchFromURL('https://example.com/data.csv');

            expect(result.success).toBe(true);
            expect(result.data).toBeDefined();
            expect(result.sourceChecked).toBe(true);
            expect(mockAxios.get).toHaveBeenCalledWith(
                'https://example.com/data.csv',
                expect.objectContaining({
                    timeout: 5000,
                    responseType: 'arraybuffer'
                })
            );
        });

        it('should include custom headers in request', async () => {
            const mockResponse = { status: 200, data: new ArrayBuffer(0) };
            mockAxios.get.mockResolvedValueOnce(mockResponse);

            await fetcher.fetchFromURL('https://example.com/data', {
                'X-Custom-Header': 'custom-value'
            });

            expect(mockAxios.get).toHaveBeenCalledWith(
                'https://example.com/data',
                expect.objectContaining({
                    headers: expect.objectContaining({
                        'X-Custom-Header': 'custom-value'
                    })
                })
            );
        });

        it('should retry on network error with exponential backoff', async () => {
            const mockError = new Error('Network error') as AxiosError;
            mockError.code = 'ECONNABORTED';
            mockAxios.get
                .mockRejectedValueOnce(mockError)
                .mockRejectedValueOnce(mockError)
                .mockResolvedValueOnce({ status: 200, data: new ArrayBuffer(0) });

            const result = await fetcher.fetchFromURL('https://example.com/data');

            expect(result.success).toBe(true);
            expect(mockAxios.get).toHaveBeenCalledTimes(3);
        });

        it('should not retry on 4xx errors', async () => {
            mockAxios.get.mockResolvedValue({ status: 404, statusText: 'Not Found' });

            const result = await fetcher.fetchFromURL('https://example.com/data');

            expect(result.success).toBe(false);
            expect(result.error?.category).toBe(ErrorCategory.Network);
            expect(result.error?.retryable).toBe(false);
            expect(mockAxios.get).toHaveBeenCalledTimes(1);
        });

        it('should retry on 5xx errors', async () => {
            mockAxios.get
                .mockResolvedValue({ status: 500, statusText: 'Internal Server Error' })
                .mockResolvedValue({ status: 200, data: new ArrayBuffer(0) });

            const result = await fetcher.fetchFromURL('https://example.com/data');

            expect(result.success).toBe(true);
            expect(mockAxios.get).toHaveBeenCalledTimes(2);
        });

        it('should handle connection timeout', async () => {
            const timeoutError = new Error('timeout of 5000ms exceeded') as AxiosError;
            timeoutError.code = 'ECONNABORTED';
            mockAxios.get.mockRejectedValue(timeoutError);

            const result = await fetcher.fetchFromURL('https://example.com/data');

            expect(result.success).toBe(false);
            expect(result.error?.category).toBe(ErrorCategory.Network);
            expect(result.error?.message).toContain('timeout');
            expect(result.error?.retryable).toBe(true);
        });

        it('should fail after max retries exhausted', async () => {
            const networkError = new Error('Network error') as AxiosError;
            networkError.code = 'ECONNABORTED';
            mockAxios.get.mockRejectedValue(networkError);

            const result = await fetcher.fetchFromURL('https://example.com/data');

            expect(result.success).toBe(false);
            expect(result.error?.retryable).toBe(true);
            expect(mockAxios.get).toHaveBeenCalledTimes(3); // maxRetries + 1 initial
        });
    });

    describe('API Key Authentication', () => {
        it('should include API key in headers', async () => {
            const mockResponse = { status: 200, data: new ArrayBuffer(0) };
            mockAxios.get.mockResolvedValue(mockResponse);

            const authConfig: ApiKeyAuthConfig = {
                type: AuthType.ApiKey,
                headerName: 'X-API-Key',
                apiKey: 'test-api-key-123'
            };

            await fetcher.fetchFromURL('https://example.com/data', {}, authConfig);

            expect(mockAxios.get).toHaveBeenCalledWith(
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

            mockAxios.post
                .mockResolvedValueOnce({ data: mockTokenResponse })
                .mockResolvedValueOnce(mockDataResponse);

            const authConfig: OAuthConfig = {
                type: AuthType.OAuth,
                tokenUrl: 'https://auth.example.com/token',
                clientId: 'client-id',
                clientSecret: 'client-secret'
            };

            await fetcher.fetchFromURL('https://example.com/data', {}, authConfig);

            // First call should be to token endpoint
            expect(mockAxios.post).toHaveBeenCalledWith(
                'https://auth.example.com/token',
                expect.any(String),
                expect.objectContaining({
                    headers: expect.objectContaining({
                        'Content-Type': 'application/x-www-form-urlencoded'
                    })
                })
            );

            // Second call should use the token
            expect(mockAxios.get).toHaveBeenCalledWith(
                'https://example.com/data',
                expect.objectContaining({
                    headers: expect.objectContaining({
                        'Authorization': 'Bearer oauth-token-123'
                    })
                })
            );
        });

        it('should cache OAuth tokens', async () => {
            const mockTokenResponse = {
                access_token: 'cached-token',
                token_type: 'Bearer',
                expires_in: 3600
            };
            const mockDataResponse = { status: 200, data: new ArrayBuffer(0) };

            mockAxios.post.mockResolvedValue({ data: mockTokenResponse });
            mockAxios.get.mockResolvedValue(mockDataResponse);

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
            expect(mockAxios.post).toHaveBeenCalledTimes(1);
            expect(mockAxios.get).toHaveBeenCalledTimes(2);
        });
    });

    describe('fetchFromFile', () => {
        it('should successfully read file from filesystem', async () => {
            const testData = 'test,csv\n1,2';
            const encoder = new TextEncoder();
            mockFs.promises.readFile.mockResolvedValue(encoder.encode(testData));
            mockFs.promises.access.mockResolvedValue(undefined);

            const result = await fetcher.fetchFromFile('/path/to/file.csv');

            expect(result.success).toBe(true);
            expect(result.data).toBeDefined();
            expect(mockFs.promises.readFile).toHaveBeenCalled();
        });

        it('should return error for non-existent file', async () => {
            mockFs.promises.access.mockRejectedValue(new Error('ENOENT'));

            const result = await fetcher.fetchFromFile('/nonexistent/file.csv');

            expect(result.success).toBe(false);
            expect(result.error?.category).toBe(ErrorCategory.Parsing);
            expect(result.error?.retryable).toBe(false);
        });

        it('should stream large files', async () => {
            const testData = 'large,csv\n1,2\n3,4\n5,6';
            const encoder = new TextEncoder();
            const chunks: Buffer[] = [];

            // Simulate streaming
            const mockStream = {
                on: (event: string, callback: (data: Buffer) => void) => {
                    if (event === 'data') {
                        chunks.forEach(chunk => callback(chunk));
                    }
                    if (event === 'end') {
                        callback(encoder.encode(testData));
                        setTimeout(() => (mockStream as any).emit('end'), 0);
                    }
                },
                emit: (event: string) => true,
                destroy: vi.fn()
            };

            mockFs.promises.access.mockResolvedValue(undefined);
            mockFs.createReadStream.mockReturnValue(mockStream as any);

            const chunksReceived: Buffer[] = [];
            const result = await fetcher.fetchFromFile('/path/to/large.csv', {
                stream: true,
                streamOptions: {
                    onChunk: async (chunk) => {
                        chunksReceived.push(chunk);
                    }
                }
            });

            expect(result.success).toBe(true);
        });
    });

    describe('Error Handling', () => {
        it('should propagate errors to error handler', async () => {
            const mockErrorHandler = {
                logError: vi.fn()
            };
            fetcher.setErrorHandler(mockErrorHandler as any);

            mockAxios.get.mockRejectedValue(new Error('Network failure'));

            await fetcher.fetchFromURL('https://example.com/data');

            expect(mockErrorHandler.logError).toHaveBeenCalled();
        });

        it('should handle unknown error types', async () => {
            mockAxios.get.mockRejectedValue('string error');

            const result = await fetcher.fetchFromURL('https://example.com/data');

            expect(result.success).toBe(false);
            expect(result.error?.category).toBe(ErrorCategory.Critical);
        });
    });

    describe('Source Availability', () => {
        it('should validate source availability before fetching', async () => {
            mockAxios.head.mockResolvedValue({ status: 200 });
            mockAxios.get.mockResolvedValue({ status: 200, data: new ArrayBuffer(0) });

            const result = await fetcher.fetchFromURL('https://example.com/data');

            expect(mockAxios.head).toHaveBeenCalledBefore(mockAxios.get);
            expect(result.sourceChecked).toBe(true);
        });

        it('should skip fetch if source unavailable', async () => {
            mockAxios.head.mockResolvedValue({ status: 503 });

            const result = await fetcher.fetchFromURL('https://example.com/data');

            expect(result.success).toBe(false);
            expect(result.error?.category).toBe(ErrorCategory.Network);
            expect(mockAxios.get).not.toHaveBeenCalled();
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

            mockAxios.post.mockResolvedValue({ data: mockTokenResponse });
            mockAxios.get.mockResolvedValue(mockDataResponse);

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
            expect(mockAxios.post).toHaveBeenCalledTimes(2);
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