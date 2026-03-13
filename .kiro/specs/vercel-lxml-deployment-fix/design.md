# Vercel lxml Deployment Fix Design

## Overview

This bugfix addresses a Vercel deployment failure caused by missing package metadata for lxml version 6.0.2. The lxml package is a transitive dependency (installed via pandas) that has incomplete dist-info metadata, specifically missing the INSTALLER file. Vercel's Python build process validates package metadata and fails with an ENOENT error when it cannot find this file.

The fix strategy involves explicitly pinning lxml to a stable version (5.3.0) that has complete metadata and is known to work reliably in Vercel's serverless environment. This approach ensures successful deployment while maintaining full pandas functionality and all existing API behavior.

## Glossary

- **Bug_Condition (C)**: The condition that triggers the deployment failure - when lxml 6.0.2 is installed as a transitive dependency with incomplete metadata
- **Property (P)**: The desired behavior - successful Vercel deployment with all package metadata files present and valid
- **Preservation**: All existing API functionality (CVM, BACEN, B3), pandas data processing capabilities, and XML/HTML parsing must remain unchanged
- **lxml**: A Python library for processing XML and HTML, used internally by pandas for certain data parsing operations
- **dist-info**: Python package metadata directory containing installation and package information
- **INSTALLER**: A metadata file that records which tool installed the package (pip, conda, etc.)
- **Transitive Dependency**: A dependency that is not directly specified in requirements.txt but is required by another package (pandas requires lxml)

## Bug Details

### Fault Condition

The bug manifests when Vercel's Python build process attempts to validate installed packages and encounters lxml version 6.0.2 with incomplete metadata. The build system expects all installed packages to have complete dist-info directories, but lxml-6.0.2.dist-info is missing the INSTALLER file, causing the build to fail before any application code can run.

**Formal Specification:**
```
FUNCTION isBugCondition(deployment)
  INPUT: deployment of type VercelBuildContext
  OUTPUT: boolean
  
  RETURN deployment.pythonVersion == "3.12"
         AND "lxml" IN deployment.installedPackages
         AND deployment.installedPackages["lxml"].version == "6.0.2"
         AND NOT fileExists(deployment.sitePackages + "/lxml-6.0.2.dist-info/INSTALLER")
         AND deployment.buildPhase == "package_validation"
END FUNCTION
```

### Examples

- **Deployment with pandas 2.2.0**: Installs lxml 6.0.2 as transitive dependency → Build fails with "ENOENT: no such file or directory, lstat '/vercel/path0/.vercel/python/.venv/lib/python3.12/site-packages/lxml-6.0.2.dist-info/INSTALLER'"

- **Deployment with pandas 2.1.3**: Installs lxml 6.0.2 as transitive dependency → Build fails with same ENOENT error during package validation phase

- **Deployment with explicit lxml==5.3.0**: Installs lxml 5.3.0 with complete metadata → Build succeeds, all metadata files present, deployment completes successfully

- **Edge case - No pandas dependency**: If pandas were removed, lxml would not be installed → Build would succeed but pandas functionality would be broken (not applicable to this project)

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**
- All three FastAPI applications (CVM, BACEN, B3) must continue to build and deploy successfully to their respective routes
- Pandas data processing functionality must remain fully operational, including CSV/Excel parsing
- XML/HTML parsing capabilities (if used by the application) must continue to work correctly
- All existing API endpoints must return the same responses with identical data formats
- Database connectivity and SQLAlchemy operations must remain unchanged
- Rate limiting, caching, and logging functionality must continue to work as before

**Scope:**
All application functionality that does not involve the Vercel build process should be completely unaffected by this fix. This includes:
- Runtime behavior of all API endpoints
- Data processing and transformation logic
- Database queries and operations
- HTTP client requests to external services
- Authentication and rate limiting
- Error handling and logging

## Hypothesized Root Cause

Based on the bug description and error analysis, the most likely issues are:

1. **Incomplete Package Distribution**: lxml 6.0.2 was published with incomplete metadata files in its wheel distribution. The INSTALLER file, which should be created during installation, is either missing from the wheel or not being created properly during Vercel's build process.

2. **Vercel Build Environment Incompatibility**: Vercel's Python build environment (using Python 3.12 and specific pip/setuptools versions) may have stricter metadata validation than typical environments, causing it to fail when encountering packages with incomplete dist-info directories.

3. **Transitive Dependency Version Resolution**: When pandas is installed without explicit lxml pinning, pip's dependency resolver selects lxml 6.0.2 (the latest version), which happens to have this metadata issue. Earlier versions like 5.3.0 do not have this problem.

4. **Build Process Timing**: The error occurs during Vercel's package validation phase, after installation but before the application starts. This suggests Vercel performs additional metadata checks that standard pip installations may skip.

## Correctness Properties

Property 1: Fault Condition - Successful Deployment with Complete Metadata

_For any_ Vercel deployment where lxml is required as a transitive dependency, the fixed requirements configuration SHALL install a version of lxml with complete and valid package metadata (including the INSTALLER file), allowing the build process to complete successfully without ENOENT errors.

**Validates: Requirements 2.1, 2.2, 2.3**

Property 2: Preservation - API Functionality and Data Processing

_For any_ API request or data processing operation that worked before the fix, the deployed application SHALL produce exactly the same behavior after the fix, preserving all pandas functionality, XML/HTML parsing capabilities, and API endpoint responses.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6**

## Fix Implementation

### Changes Required

Assuming our root cause analysis is correct (lxml 6.0.2 has incomplete metadata):

**Files to Modify**:
1. `requirements.txt` (root level)
2. `requirements-vercel.txt` (Vercel-specific)
3. `src/cvm_api/requirements.txt`
4. `src/bacen_api/requirements.txt`
5. `src/b3_calc_api/requirements.txt`

**Specific Changes**:

1. **Add Explicit lxml Version Pin**: Add `lxml==5.3.0` to all requirements files
   - This version is known to have complete metadata and work reliably in Vercel
   - It's compatible with pandas 2.1.3 and 2.2.0
   - It provides all XML/HTML parsing functionality needed by pandas

2. **Position in Requirements Files**: Place lxml pin before pandas in dependency order
   - This ensures pip installs the pinned version before resolving pandas dependencies
   - Prevents pip from upgrading to lxml 6.0.2 during pandas installation

3. **Verify Pandas Compatibility**: Ensure pandas versions in requirements files are compatible with lxml 5.3.0
   - pandas 2.1.3 (currently in requirements-vercel.txt) - compatible
   - pandas 2.2.0 (currently in requirements.txt) - compatible
   - No changes needed to pandas versions

4. **Update All Deployment Contexts**: Apply the fix consistently across all requirements files
   - Root requirements.txt (for local development)
   - requirements-vercel.txt (for Vercel deployments)
   - Individual API requirements files (for Vercel's per-function builds)

5. **Document the Pin**: Add a comment explaining why lxml is explicitly pinned
   - Helps future maintainers understand the constraint
   - Prevents accidental removal during dependency updates

## Testing Strategy

### Validation Approach

The testing strategy follows a two-phase approach: first, confirm the bug exists with current configuration (exploratory), then verify the fix resolves the issue and preserves all functionality (fix checking and preservation checking).

### Exploratory Fault Condition Checking

**Goal**: Confirm the bug exists BEFORE implementing the fix. Verify that the current configuration (without explicit lxml pin) causes deployment failure on Vercel.

**Test Plan**: Attempt a Vercel deployment with the current requirements files (no explicit lxml pin). Observe the build logs to confirm the ENOENT error occurs during package validation. This confirms our root cause hypothesis.

**Test Cases**:
1. **Current Configuration Deployment**: Deploy with existing requirements.txt files → Should fail with ENOENT error for lxml-6.0.2.dist-info/INSTALLER
2. **Build Log Analysis**: Examine Vercel build logs to identify exact failure point → Should show error during package validation phase
3. **Local Environment Test**: Install dependencies locally and check lxml version → May install 6.0.2, but local environment may not validate metadata as strictly
4. **Metadata Inspection**: If lxml 6.0.2 installs locally, check if INSTALLER file exists → May reveal whether issue is distribution-specific or environment-specific

**Expected Counterexamples**:
- Vercel deployment fails with "ENOENT: no such file or directory, lstat '/vercel/path0/.vercel/python/.venv/lib/python3.12/site-packages/lxml-6.0.2.dist-info/INSTALLER'"
- Possible causes: incomplete lxml 6.0.2 wheel distribution, Vercel build environment metadata validation, pip installation issue in serverless context

### Fix Checking

**Goal**: Verify that with explicit lxml==5.3.0 pinning, Vercel deployments complete successfully without metadata errors.

**Pseudocode:**
```
FOR ALL deployment WHERE isBugCondition(deployment) DO
  result := deployWithFixedRequirements(deployment)
  ASSERT result.buildStatus == "SUCCESS"
  ASSERT result.lxmlVersion == "5.3.0"
  ASSERT fileExists(result.sitePackages + "/lxml-5.3.0.dist-info/INSTALLER")
  ASSERT result.deploymentURL != null
END FOR
```

### Preservation Checking

**Goal**: Verify that all existing API functionality continues to work exactly as before the fix.

**Pseudocode:**
```
FOR ALL apiRequest WHERE NOT affectsDeploymentProcess(apiRequest) DO
  ASSERT handleRequest_original(apiRequest) = handleRequest_fixed(apiRequest)
END FOR
```

**Testing Approach**: Property-based testing is recommended for preservation checking because:
- It generates many test cases automatically across different API endpoints and parameters
- It catches edge cases in data processing that manual tests might miss
- It provides strong guarantees that pandas functionality is unchanged for all data inputs

**Test Plan**: Before applying the fix, document the behavior of all API endpoints and pandas operations. After applying the fix and deploying, verify that all behaviors remain identical.

**Test Cases**:
1. **CVM API Preservation**: Test all /api/v1/cvm/* endpoints → Should return identical responses before and after fix
2. **BACEN API Preservation**: Test all /api/v1/bacen/* endpoints → Should return identical responses before and after fix
3. **B3 API Preservation**: Test all /api/v1/prices/*, /api/v1/securities/*, and /api/v1/b3/* endpoints → Should return identical responses before and after fix
4. **Pandas Data Processing**: Test CSV/Excel parsing operations → Should process data identically before and after fix
5. **XML/HTML Parsing**: If application uses lxml directly or via pandas → Should parse data identically before and after fix

### Unit Tests

- Test that lxml 5.3.0 is installed in the deployment environment
- Test that all required metadata files exist for lxml package
- Test that pandas can import and use lxml for XML/HTML operations
- Test edge cases like empty data files, malformed XML, large datasets

### Property-Based Tests

- Generate random API requests across all three services and verify responses match expected format
- Generate random CSV/Excel data and verify pandas can parse it correctly
- Generate random XML/HTML data and verify lxml can parse it correctly
- Test that deployment succeeds across multiple Vercel regions

### Integration Tests

- Deploy to Vercel staging environment and verify all three APIs are accessible
- Test full request flow: client → Vercel → API → database → response
- Test health check endpoints for all three services
- Verify deployment completes within expected time limits (no timeout issues)
- Test that environment variables and configuration are correctly applied
