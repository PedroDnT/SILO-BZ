/**
 * Logger - Structured logging for backfill operations
 */
import { BackfillRunMetadata, BackfillError } from '../types/index.js';
export declare class Logger {
    info(message: string, meta?: Record<string, unknown>): void;
    error(message: string, meta?: Record<string, unknown>): void;
    warn(message: string, meta?: Record<string, unknown>): void;
    debug(message: string, meta?: Record<string, unknown>): void;
    logBackfillRun(metadata: BackfillRunMetadata): void;
    logError(error: BackfillError): void;
}
//# sourceMappingURL=index.d.ts.map