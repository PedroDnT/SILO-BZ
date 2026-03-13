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
    scheduleTime: string;
    batchSize: number;
    freshnessThresholdHours: number;
    errorRateThreshold: number;
}
export declare function loadConfig(): AppConfig;
//# sourceMappingURL=index.d.ts.map