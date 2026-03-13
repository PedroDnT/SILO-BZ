/**
 * Storage Manager - Handles database operations with Supabase
 */

import { CVMRecord, SGSObservation, PTAXRate, B3Security, B3PricingSnapshot, InsertResult, UpsertResult } from '../types/index.js';

export class StorageManager {
    async insertCVMRecords(records: CVMRecord[]): Promise<InsertResult> {
        throw new Error('Not implemented');
    }

    async upsertBACENData(records: (SGSObservation | PTAXRate)[]): Promise<UpsertResult> {
        throw new Error('Not implemented');
    }

    async upsertB3Data(records: (B3Security | B3PricingSnapshot)[]): Promise<UpsertResult> {
        throw new Error('Not implemented');
    }
}