/**
 * Data Fetcher - Retrieves raw data from external sources
 */

import { FetchConfig } from '../types/index.js';

export class DataFetcher {
    private config: FetchConfig;

    constructor(config: FetchConfig) {
        this.config = config;
    }

    async fetchFromURL(url: string, headers?: Record<string, string>): Promise<Buffer> {
        throw new Error('Not implemented');
    }

    async fetchFromFile(path: string): Promise<Buffer> {
        throw new Error('Not implemented');
    }
}