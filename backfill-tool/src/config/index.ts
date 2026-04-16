/**
 * Configuration - Environment-based configuration management
 */

import { FetchConfig, StorageConfig, CSVConfig } from '../types/index.js';

export interface AppConfig {
    supabaseUrl: string;
    supabaseServiceRoleKey: string;
    fetch: FetchConfig;
    storage: StorageConfig;
    csv: CSVConfig;
    scheduleTime: string; // HH:MM UTC
    batchSize: number;
    freshnessThresholdHours: number;
    errorRateThreshold: number;
}

export function loadConfig(): AppConfig {
    return {
        supabaseUrl: process.env.SUPABASE_URL || '',
        supabaseServiceRoleKey: process.env.SUPABASE_SERVICE_ROLE_KEY || '',
        fetch: {
            timeout: parseInt(process.env.FETCH_TIMEOUT || '30000', 10),
            headers: {},
            maxRetries: parseInt(process.env.MAX_RETRIES || '3', 10),
            retryBackoff: [1000, 2000, 4000, 8000]
        },
        storage: {
            batchSize: parseInt(process.env.BATCH_SIZE || '1000', 10),
            maxRetries: parseInt(process.env.MAX_RETRIES || '3', 10)
        },
        csv: {
            delimiter: ',',
            encoding: 'utf-8',
            hasHeaders: true,
            skipMalformed: true
        },
        scheduleTime: process.env.SCHEDULE_TIME || '02:00',
        batchSize: parseInt(process.env.BATCH_SIZE || '1000', 10),
        freshnessThresholdHours: parseInt(process.env.FRESHNESS_THRESHOLD_HOURS || '48', 10),
        errorRateThreshold: parseFloat(process.env.ERROR_RATE_THRESHOLD || '0.05')
    };
}