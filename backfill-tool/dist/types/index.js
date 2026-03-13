/**
 * Core types and interfaces for the Supabase Daily Data Backfill Tool
 */
// ============================================================================
// Error Handling Types
// ============================================================================
/**
 * Error categories for the backfill system
 */
export var ErrorCategory;
(function (ErrorCategory) {
    ErrorCategory["Network"] = "NETWORK";
    ErrorCategory["Parsing"] = "PARSING";
    ErrorCategory["Validation"] = "VALIDATION";
    ErrorCategory["Storage"] = "STORAGE";
    ErrorCategory["Critical"] = "CRITICAL";
})(ErrorCategory || (ErrorCategory = {}));
/**
 * Service identifier
 */
export var ServiceType;
(function (ServiceType) {
    ServiceType["CVM"] = "CVM";
    ServiceType["BACEN"] = "BACEN";
    ServiceType["B3"] = "B3";
})(ServiceType || (ServiceType = {}));
//# sourceMappingURL=index.js.map