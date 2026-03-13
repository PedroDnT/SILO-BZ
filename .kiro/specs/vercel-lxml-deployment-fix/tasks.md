# Implementation Plan

- [-] 1. Write bug condition exploration test
  - **Property 1: Fault Condition** - Vercel Deployment Fails with lxml 6.0.2 Metadata Error
  - **CRITICAL**: This test MUST FAIL on unfixed code - failure confirms the bug exists
  - **DO NOT attempt to fix the test or the code when it fails**
  - **NOTE**: This test encodes the expected behavior - it will validate the fix when it passes after implementation
  - **GOAL**: Surface counterexamples that demonstrate the bug exists
  - **Scoped PBT Approach**: Scope the property to the concrete failing case - Vercel deployment with current requirements files (no explicit lxml pin)
  - Test that Vercel deployment with current configuration fails with ENOENT error for lxml-6.0.2.dist-info/INSTALLER
  - Verify the error occurs during package validation phase (isBugCondition: deployment.buildPhase == "package_validation" AND lxml version == "6.0.2" AND INSTALLER file missing)
  - Run test on UNFIXED code (current requirements files without lxml pin)
  - **EXPECTED OUTCOME**: Test FAILS with "ENOENT: no such file or directory, lstat '/vercel/path0/.vercel/python/.venv/lib/python3.12/site-packages/lxml-6.0.2.dist-info/INSTALLER'"
  - Document counterexamples found: deployment failure logs, exact error message, build phase where failure occurs
  - Mark task complete when test is written, run, and failure is documented
  - _Requirements: 1.1, 1.2, 1.3_

- [~] 2. Write preservation property tests (BEFORE implementing fix)
  - **Property 2: Preservation** - API Functionality and Data Processing Unchanged
  - **IMPORTANT**: Follow observation-first methodology
  - Observe behavior on UNFIXED code for non-buggy inputs (successful local API operations)
  - Document current API endpoint responses for CVM, BACEN, and B3 services
  - Document pandas data processing behavior (CSV/Excel parsing)
  - Write property-based tests capturing observed behavior patterns from Preservation Requirements
  - Test that all API endpoints return expected responses (Property 2: For any API request that worked before, SHALL produce exactly the same behavior after)
  - Test that pandas functionality remains operational (CSV/Excel parsing, data transformations)
  - Test that XML/HTML parsing capabilities work correctly (if used by application)
  - Property-based testing generates many test cases for stronger guarantees
  - Run tests on UNFIXED code (local environment or successful deployment if available)
  - **EXPECTED OUTCOME**: Tests PASS (this confirms baseline behavior to preserve)
  - Mark task complete when tests are written, run, and passing on unfixed code
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6_

- [~] 3. Fix for Vercel lxml deployment failure

  - [~] 3.1 Pin lxml to version 5.3.0 in all requirements files
    - Add `lxml==5.3.0` to requirements.txt (root level) before pandas dependency
    - Add `lxml==5.3.0` to requirements-vercel.txt before pandas dependency
    - Add `lxml==5.3.0` to src/cvm_api/requirements.txt before pandas dependency
    - Add `lxml==5.3.0` to src/bacen_api/requirements.txt before pandas dependency
    - Add `lxml==5.3.0` to src/b3_calc_api/requirements.txt before pandas dependency
    - Add comment explaining the pin: "# Pin lxml to 5.3.0 to avoid Vercel deployment metadata issues with 6.0.2"
    - _Bug_Condition: isBugCondition(deployment) where deployment.installedPackages["lxml"].version == "6.0.2" AND NOT fileExists(INSTALLER file)_
    - _Expected_Behavior: deployment.buildStatus == "SUCCESS" AND deployment.lxmlVersion == "5.3.0" AND fileExists(lxml-5.3.0.dist-info/INSTALLER)_
    - _Preservation: All API functionality (CVM, BACEN, B3), pandas data processing, and XML/HTML parsing must remain unchanged_
    - _Requirements: 2.1, 2.2, 2.3, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6_

  - [~] 3.2 Verify bug condition exploration test now passes
    - **Property 1: Expected Behavior** - Successful Deployment with Complete Metadata
    - **IMPORTANT**: Re-run the SAME test from task 1 - do NOT write a new test
    - The test from task 1 encodes the expected behavior
    - When this test passes, it confirms the expected behavior is satisfied
    - Run bug condition exploration test from step 1 (Vercel deployment with fixed requirements)
    - Verify deployment completes successfully without ENOENT errors
    - Verify lxml 5.3.0 is installed with complete metadata (INSTALLER file exists)
    - Verify deployment URL is accessible
    - **EXPECTED OUTCOME**: Test PASSES (confirms bug is fixed)
    - _Requirements: 2.1, 2.2, 2.3_

  - [~] 3.3 Verify preservation tests still pass
    - **Property 2: Preservation** - API Functionality and Data Processing Unchanged
    - **IMPORTANT**: Re-run the SAME tests from task 2 - do NOT write new tests
    - Run preservation property tests from step 2
    - Verify all CVM API endpoints return identical responses
    - Verify all BACEN API endpoints return identical responses
    - Verify all B3 API endpoints return identical responses
    - Verify pandas data processing produces identical results
    - Verify XML/HTML parsing (if used) produces identical results
    - **EXPECTED OUTCOME**: Tests PASS (confirms no regressions)
    - Confirm all tests still pass after fix (no regressions)
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6_

- [~] 4. Checkpoint - Ensure all tests pass
  - Verify bug condition exploration test passes (deployment succeeds with lxml 5.3.0)
  - Verify all preservation tests pass (API functionality unchanged)
  - Verify deployment completes within expected time limits
  - Verify all three services (CVM, BACEN, B3) are accessible at their respective routes
  - Ensure all tests pass, ask the user if questions arise
