/**
 * Orchestrator - Coordinates backfill operations
 */

import { ServiceType, BackfillRunMetadata } from '../types/index.js';

export class Orchestrator {
    async runDailyBackfill(): Promise<void> {
        throw new Error('Not implemented');
    }

    async runServiceBackfill(service: ServiceType): Promise<BackfillRunMetadata> {
        throw new Error('Not implemented');
    }

    async runManualBackfill(services: ServiceType[]): Promise<BackfillRunMetadata[]> {
        throw new Error('Not implemented');
    }
}