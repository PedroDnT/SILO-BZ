/**
 * Transformer - Normalizes and prepares data for storage
 */
import { DataRecord, CVMRecord, SGSObservation, PTAXRate, B3Security, B3PricingSnapshot } from '../types/index.js';
export declare class Transformer {
    transformToCVMRecord(record: DataRecord): CVMRecord;
    transformToBACENData(record: DataRecord): SGSObservation | PTAXRate;
    transformToB3Data(record: DataRecord): B3Security | B3PricingSnapshot;
}
//# sourceMappingURL=index.d.ts.map