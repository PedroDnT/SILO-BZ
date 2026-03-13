/**
 * Logger - Structured logging for backfill operations
 */

import { BackfillRunMetadata, BackfillError } from '../types/index.js';

export class Logger {
    info(message: string, meta?: Record<string, unknown>): void {
        throw new Error('Not implemented');
    }

    error(message: string, meta?: Record<string, unknown>): void {
        throw new Error('Not implemented');
    }

    warn(message: string, meta?: Record<string, unknown>): void {
        throw new Error('Not implemented');
    }

    debug(message: string, meta?: Record<string, unknown>): void {
        throw new Error('Not implemented');
    }

    logBackfillRun(metadata: BackfillRunMetadata): void {
        throw new Error('Not implemented');
    }

    logError(error: BackfillError): void {
        throw new Error('Not implemented');
    }
}