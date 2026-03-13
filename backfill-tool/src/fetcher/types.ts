/**
 * Types for the Data Fetcher component
 */

import { BackfillError, ErrorCategory } from '../types/index.js';

/**
 * Authentication types supported by the fetcher
 */
export enum AuthType {
    None = 'NONE',
    ApiKey = 'API_KEY',
    OAuth = 'OAUTH'
}

/**
 * Configuration for API key authentication
 */
export interface ApiKeyAuthConfig {
    type: AuthType.ApiKey;
    headerName: string;
    apiKey: string;
}

/**
 * Configuration for OAuth authentication
 */
export interface OAuthConfig {
    type: AuthType.OAuth;
    tokenUrl: string;
    clientId: string;
    clientSecret: string;
    scope?: string;
    refreshBeforeExpiryMs?: number;
}

/**
 * Union type for authentication configurations
 */
export type AuthConfig = ApiKeyAuthConfig | OAuthConfig;

/**
 * Source configuration for external data sources
 */
export interface SourceConfig {
    url: string;
    auth?: AuthConfig;
    validateAvailability?: boolean;
    validateIntervalMs?: number;
}

/**
 * Result of a fetch operation
 */
export interface FetchResult {
    success: boolean;
    data?: Buffer;
    error?: BackfillError;
    sourceChecked?: boolean;
}

/**
 * Stream callback for processing large files
 */
export type StreamCallback = (chunk: Buffer) => Promise<void>;

/**
 * Options for streaming large files
 */
export interface StreamOptions {
    highWaterMark?: number;
    onChunk?: StreamCallback;
}

/**
 * OAuth token response from token endpoint
 */
interface OAuthTokenResponse {
    access_token: string;
    token_type: string;
    expires_in: number;
    refresh_token?: string;
}

/**
 * Cached OAuth token with expiry tracking
 */
interface CachedToken {
    token: string;
    expiresAt: number;
}