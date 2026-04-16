/**
 * Error Handler - Captures and handles errors with retry logic
 */
import { BackfillError, ErrorCategory } from '../types/index.js';
export declare class ErrorHandler {
    logError(error: BackfillError): void;
    retryWithBackoff<T>(fn: () => Promise<T>, maxRetries: number): Promise<T>;
    categorizeError(error: Error): ErrorCategory;
}
//# sourceMappingURL=index.d.ts.map