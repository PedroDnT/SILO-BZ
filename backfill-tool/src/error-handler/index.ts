/**
 * Error Handler - Captures and handles errors with retry logic
 */

import { BackfillError, ErrorCategory } from '../types/index.js';

export class ErrorHandler {
    logError(error: BackfillError): void {
        throw new Error('Not implemented');
    }

    async retryWithBackoff<T>(fn: () => Promise<T>, maxRetries: number): Promise<T> {
        throw new Error('Not implemented');
    }

    categorizeError(error: Error): ErrorCategory {
        throw new Error('Not implemented');
    }
}