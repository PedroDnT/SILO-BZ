/**
 * Transformer - Normalizes and prepares data for storage
 */

import { DataRecord, CVMRecord, SGSObservation, PTAXRate, B3Security, B3PricingSnapshot } from '../types/index.js';

export class Transformer {
    transformToCVMRecord(record: DataRecord): CVMRecord {
        throw new Error('Not implemented');
    }

    transformToBACENData(record: DataRecord): SGSObservation | PTAXRate {
        throw new Error('Not implemented');
    }

    transformToB3Data(record: DataRecord): B3Security | B3PricingSnapshot {
        throw new Error('Not implemented');
    }
}