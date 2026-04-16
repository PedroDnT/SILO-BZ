/**
 * Configuration - Environment-based configuration management
 */
export function loadConfig() {
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
//# sourceMappingURL=index.js.map