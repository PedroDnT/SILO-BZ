/**
 * Orchestrator - Coordinates backfill operations
 */
import { ServiceType, BackfillRunMetadata } from '../types/index.js';
export declare class Orchestrator {
    runDailyBackfill(): Promise<void>;
    runServiceBackfill(service: ServiceType): Promise<BackfillRunMetadata>;
    runManualBackfill(services: ServiceType[]): Promise<BackfillRunMetadata[]>;
}
//# sourceMappingURL=index.d.ts.map