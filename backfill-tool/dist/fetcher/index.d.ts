/**
 * Data Fetcher - Retrieves raw data from external sources
 */
import { FetchConfig } from '../types/index.js';
export declare class DataFetcher {
    private config;
    constructor(config: FetchConfig);
    fetchFromURL(url: string, headers?: Record<string, string>): Promise<Buffer>;
    fetchFromFile(path: string): Promise<Buffer>;
}
//# sourceMappingURL=index.d.ts.map