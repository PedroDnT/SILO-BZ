/**
 * Data Fetcher Component
 * 
 * Responsible for fetching raw data from external sources (HTTP endpoints, CSV files)
 * with support for authentication, retry logic, and streaming for large files.
 */

import * as fs from 'fs';
import * as path from 'path';
import axios, { AxiosError, AxiosResponse, InternalAxiosRequestConfig } from 'axios';
import { createReadStream } from 'fs';
import { Readable } from 'stream';
import { BackfillError, ErrorCategory, FetchConfig } from '../types/index.js';
import {
    AuthType,
    AuthConfig,
    ApiKeyAuthConfig,
    OAuthConfig,
    SourceConfig,
    FetchResult,
    StreamOptions,
    OAuthTokenResponse,
    CachedToken
} from './types.js';

/**
 * Default fetch configuration
 */
const DEFAULT_CONFIG: FetchConfig = {
    timeout: 30000, // 30 seconds
    maxRetries: 3,
    retryBackoff: [1000, 2000, 4000] // 1s, 2s, 4s
};

/**
 * Data Fetcher class for retrieving data from external sources
 */
export class DataFetcher {
    private config: FetchConfig;
    private oauthCache: Map<string, CachedToken> = new Map();
    private errorHandler: ErrorHandler | null = null;

    constructor(config?: Partial<FetchConfig>) {
        this.config = { ...DEFAULT_CONFIG, ...config };
    }

    /**
     * Set the error handler for error propagation
     */
    setErrorHandler(handler: ErrorHandler): void {
        this.errorHandler = handler;
    }

    /**
     * Fetch data from a URL with optional authentication and retry logic
     */
    async fetchFromURL(
        url: string,
        headers?: Record<string, string>,
        authConfig?: AuthConfig
    ): Promise<FetchResult> {
        const startTime = Date.now();

        // Build request configuration
        const requestHeaders = await this.buildHeaders(headers, authConfig);

        return this.executeWithRetry(async (attempt) => {
            // Validate source availability if configured
            if (attempt === 0) {
                const availabilityResult = await this.validateSourceAvailability(url, requestHeaders);
                if (!availabilityResult.success) {
                    return availabilityResult;
                }
            }

            const response = await this.makeRequest(url, requestHeaders);

            return {
                success: true,
                data: Buffer.from(response.data as ArrayBuffer),
                sourceChecked: attempt === 0
            };
        }, `fetchFromURL(${url})`);
    }

    /**
     * Fetch data from a local file with optional streaming
     */
    async fetchFromFile(filePath: string, options?: { stream?: boolean; streamOptions?: StreamOptions }): Promise<FetchResult> {
        return this.executeWithRetry(async () => {
            // Validate file exists and is readable
            if (!await this.fileExists(filePath)) {
                const error: BackfillError = {
                    category: ErrorCategory.Parsing,
                    message: `File not found or not accessible: ${filePath}`,
                    timestamp: new Date(),
                    retryable: false
                };
                this.logError(error);
                return { success: false, error };
            }

            // Stream large files if requested
            if (options?.stream) {
                return this.streamFile(filePath, options.streamOptions);
            }

            // Read entire file into memory
            return this.readFile(filePath);
        }, `fetchFromFile(${filePath})`);
    }

    /**
     * Fetch from a configured source
     */
    async fetchFromSource(source: SourceConfig): Promise<FetchResult> {
        const headers: Record<string, string> = {};

        return this.fetchFromURL(source.url, headers, source.auth);
    }

    /**
     * Make HTTP request with proper error handling
     */
    private async makeRequest(
        url: string,
        headers: Record<string, string>
    ): Promise<AxiosResponse> {
        try {
            const response = await axios.get(url, {
                headers,
                timeout: this.config.timeout,
                responseType: 'arraybuffer',
                validateStatus: (status) => status < 500 // Don't throw on 4xx
            });

            if (response.status >= 400) {
                const error: BackfillError = {
                    category: ErrorCategory.Network,
                    message: `HTTP ${response.status}: ${response.statusText}`,
                    timestamp: new Date(),
                    retryable: response.status >= 500
                };
                throw error;
            }

            return response;
        } catch (error) {
            if (axios.isAxiosError(error)) {
                const axiosError = error as AxiosError;

                if (axiosError.code === 'ECONNABORTED' || axiosError.message.includes('timeout')) {
                    const backfillError: BackfillError = {
                        category: ErrorCategory.Network,
                        message: `Connection timeout after ${this.config.timeout}ms`,
                        timestamp: new Date(),
                        retryable: true
                    };
                    throw backfillError;
                }

                const backfillError: BackfillError = {
                    category: ErrorCategory.Network,
                    message: axiosError.message || 'Network error',
                    timestamp: new Date(),
                    retryable: axiosError.response?.status ? (axiosError.response.status >= 500) : true
                };
                throw backfillError;
            }

            throw error;
        }
    }

    /**
     * Build request headers with authentication
     */
    private async buildHeaders(
        customHeaders?: Record<string, string>,
        authConfig?: AuthConfig
    ): Promise<Record<string, string>> {
        const headers: Record<string, string> = {
            'Accept': 'text/csv, application/json, */*',
            ...customHeaders
        };

        if (!authConfig) {
            return headers;
        }

        switch (authConfig.type) {
            case AuthType.ApiKey:
                headers[authConfig.headerName] = authConfig.apiKey;
                break;

            case AuthType.OAuth:
                const token = await this.getOAuthToken(authConfig);
                headers['Authorization'] = `Bearer ${token}`;
                break;
        }

        return headers;
    }

    /**
     * Get OAuth token (with caching)
     */
    private async getOAuthToken(config: OAuthConfig): Promise<string> {
        const cacheKey = `${config.tokenUrl}:${config.clientId}`;
        const cached = this.oauthCache.get(cacheKey);

        // Return cached token if still valid
        if (cached && cached.expiresAt > Date.now()) {
            return cached.token;
        }

        // Request new token
        const response = await axios.post<OAuthTokenResponse>(
            config.tokenUrl,
            new URLSearchParams({
                grant_type: 'client_credentials',
                client_id: config.clientId,
                client_secret: config.clientSecret,
                scope: config.scope || ''
            }),
            {
                headers: { 'Content-Type': 'application/x-www-form-urlencoded' }
            }
        );

        const { access_token, expires_in } = response.data;
        const expiresAt = Date.now() + (expires_in * 1000) - 60000; // Refresh 1 min early

        this.oauthCache.set(cacheKey, { token: access_token, expiresAt });
        return access_token;
    }

    /**
     * Validate that a data source is available
     */
    private async validateSourceAvailability(
        url: string,
        headers: Record<string, string>
    ): Promise<FetchResult> {
        try {
            const response = await axios.head(url, {
                headers,
                timeout: Math.min(this.config.timeout, 10000) // Shorter timeout for availability check
            });

            if (response.status >= 400) {
                const error: BackfillError = {
                    category: ErrorCategory.Network,
                    message: `Source unavailable: HTTP ${response.status}`,
                    timestamp: new Date(),
                    retryable: response.status >= 500
                };
                this.logError(error);
                return { success: false, error, sourceChecked: true };
            }

            return { success: true, sourceChecked: true };
        } catch (error) {
            const backfillError: BackfillError = {
                category: ErrorCategory.Network,
                message: `Source availability check failed: ${error instanceof Error ? error.message : 'Unknown error'}`,
                timestamp: new Date(),
                retryable: true
            };
            this.logError(backfillError);
            return { success: false, error: backfillError, sourceChecked: true };
        }
    }

    /**
     * Execute a function with exponential backoff retry
     */
    private async executeWithRetry<T>(
        fn: (attempt: number) => Promise<FetchResult | T>,
        operationName: string
    ): Promise<FetchResult> {
        let lastError: BackfillError | undefined;

        for (let attempt = 0; attempt <= this.config.maxRetries; attempt++) {
            try {
                const result = await fn(attempt);
                return result as FetchResult;
            } catch (error) {
                lastError = this.normalizeError(error);

                // Don't retry if error is not retryable
                if (!lastError.retryable) {
                    this.logError(lastError);
                    return { success: false, error: lastError };
                }

                // Don't wait after last attempt
                if (attempt < this.config.maxRetries) {
                    const waitTime = this.config.retryBackoff[attempt] || 1000;
                    await this.sleep(waitTime);
                }
            }
        }

        // All retries exhausted
        if (lastError) {
            this.logError(lastError);
            return { success: false, error: lastError };
        }

        return { success: false, error: { category: ErrorCategory.Critical, message: 'Unknown error', timestamp: new Date(), retryable: false } };
    }

    /**
     * Normalize various error types to BackfillError
     */
    private normalizeError(error: unknown): BackfillError {
        if (this.isBackfillError(error)) {
            return error;
        }

        if (error instanceof Error) {
            return {
                category: ErrorCategory.Network,
                message: error.message,
                timestamp: new Date(),
                stackTrace: error.stack,
                retryable: true
            };
        }

        return {
            category: ErrorCategory.Critical,
            message: String(error),
            timestamp: new Date(),
            retryable: false
        };
    }

    /**
     * Check if an error is already a BackfillError
     */
    private isBackfillError(error: unknown): error is BackfillError {
        return (
            typeof error === 'object' &&
            error !== null &&
            'category' in error &&
            'message' in error &&
            'timestamp' in error
        );
    }

    /**
     * Check if a file exists
     */
    private async fileExists(filePath: string): Promise<boolean> {
        try {
            await fs.promises.access(filePath, fs.constants.F_OK);
            return true;
        } catch {
            return false;
        }
    }

    /**
     * Read entire file into buffer
     */
    private async readFile(filePath: string): Promise<FetchResult> {
        try {
            const absolutePath = path.resolve(filePath);
            const buffer = await fs.promises.readFile(absolutePath);
            return { success: true, data: buffer };
        } catch (error) {
            const backfillError: BackfillError = {
                category: ErrorCategory.Parsing,
                message: `Failed to read file: ${error instanceof Error ? error.message : 'Unknown error'}`,
                timestamp: new Date(),
                retryable: false
            };
            this.logError(backfillError);
            return { success: false, error: backfillError };
        }
    }

    /**
     * Stream a large file and process in chunks
     */
    private async streamFile(filePath: string, options?: StreamOptions): Promise<FetchResult> {
        return new Promise((resolve) => {
            const absolutePath = path.resolve(filePath);
            const highWaterMark = options?.highWaterMark || 16384; // 16KB chunks
            const chunks: Buffer[] = [];

            const stream = createReadStream(absolutePath, { highWaterMark });

            stream.on('data', async (chunk: Buffer) => {
                chunks.push(chunk);

                if (options?.onChunk) {
                    try {
                        await options.onChunk(chunk);
                    } catch (error) {
                        stream.destroy();
                        const backfillError: BackfillError = {
                            category: ErrorCategory.Parsing,
                            message: `Error processing chunk: ${error instanceof Error ? error.message : 'Unknown error'}`,
                            timestamp: new Date(),
                            retryable: false
                        };
                        this.logError(backfillError);
                        resolve({ success: false, error: backfillError });
                    }
                }
            });

            stream.on('end', () => {
                const buffer = Buffer.concat(chunks);
                resolve({ success: true, data: buffer });
            });

            stream.on('error', (error) => {
                const backfillError: BackfillError = {
                    category: ErrorCategory.Parsing,
                    message: `Error streaming file: ${error.message}`,
                    timestamp: new Date(),
                    retryable: false
                };
                this.logError(backfillError);
                resolve({ success: false, error: backfillError });
            });
        });
    }

    /**
     * Log error to error handler
     */
    private logError(error: BackfillError): void {
        if (this.errorHandler) {
            this.errorHandler.logError(error);
        }
        // Console logging for development
        console.error(`[DataFetcher] ${error.category}: ${error.message}`);
    }

    /**
     * Sleep utility for retry delays
     */
    private sleep(ms: number): Promise<void> {
        return new Promise(resolve => setTimeout(resolve, ms));
    }

    /**
     * Clear OAuth token cache
     */
    clearTokenCache(): void {
        this.oauthCache.clear();
    }
}

/**
 * Interface for error handling (to avoid circular dependency)
 */
export interface ErrorHandler {
    logError(error: BackfillError): void;
}

/**
 * Factory function for creating a DataFetcher with default config
 */
export function createDataFetcher(config?: Partial<FetchConfig>): DataFetcher {
    return new DataFetcher(config);
}