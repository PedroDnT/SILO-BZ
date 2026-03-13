/**
 * Storage Manager - Handles database operations with Supabase
 */
import { CVMRecord, SGSObservation, PTAXRate, B3Security, B3PricingSnapshot, InsertResult, UpsertResult } from '../types/index.js';
export declare class StorageManager {
    insertCVMRecords(records: CVMRecord[]): Promise<InsertResult>;
    upsertBACENData(records: (SGSObservation | PTAXRate)[]): Promise<UpsertResult>;
    upsertB3Data(records: (B3Security | B3PricingSnapshot)[]): Promise<UpsertResult>;
}
//# sourceMappingURL=index.d.ts.map