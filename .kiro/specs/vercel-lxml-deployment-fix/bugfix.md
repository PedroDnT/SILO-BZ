# Bugfix Requirements Document

## Introduction

This bugfix addresses a Vercel deployment failure caused by a missing INSTALLER metadata file for the lxml package (version 6.0.2) during Python virtual environment setup. The error prevents successful deployment of the iliquid_nightly Brazilian financial data infrastructure platform to Vercel's serverless environment.

The lxml package is a transitive dependency (likely from pandas) that is not explicitly declared in the project's requirements files. During Vercel's build process, the Python environment setup attempts to access metadata files for installed packages, but the INSTALLER file for lxml-6.0.2 is missing from the expected location, causing an ENOENT (file not found) error that halts the deployment.

## Bug Analysis

### Current Behavior (Defect)

1.1 WHEN Vercel builds the Python environment for deployment THEN the system fails with error "ENOENT: no such file or directory, lstat '/vercel/path0/.vercel/python/.venv/lib/python3.12/site-packages/lxml-6.0.2.dist-info/INSTALLER'"

1.2 WHEN lxml is installed as a transitive dependency without explicit version pinning THEN the system may install version 6.0.2 which has incomplete or corrupted package metadata

1.3 WHEN the deployment process attempts to validate installed packages THEN the system cannot complete the build due to missing metadata files

### Expected Behavior (Correct)

2.1 WHEN Vercel builds the Python environment for deployment THEN the system SHALL complete the build successfully without ENOENT errors related to package metadata

2.2 WHEN lxml is required as a transitive dependency THEN the system SHALL install a version with complete and valid package metadata that passes Vercel's validation checks

2.3 WHEN the deployment process validates installed packages THEN the system SHALL find all required metadata files and proceed to successful deployment

### Unchanged Behavior (Regression Prevention)

3.1 WHEN deploying the CVM API service THEN the system SHALL CONTINUE TO build and deploy the FastAPI application to the /api/v1/cvm/* routes

3.2 WHEN deploying the BACEN API service THEN the system SHALL CONTINUE TO build and deploy the FastAPI application to the /api/v1/bacen/* routes

3.3 WHEN deploying the B3 CALC API service THEN the system SHALL CONTINUE TO build and deploy the FastAPI application to the /api/v1/prices/* and /api/v1/securities/* routes

3.4 WHEN pandas is imported and used for data processing THEN the system SHALL CONTINUE TO provide all pandas functionality including CSV/Excel parsing capabilities

3.5 WHEN the application processes XML/HTML data (if applicable) THEN the system SHALL CONTINUE TO parse and process such data correctly

3.6 WHEN existing API endpoints are called after deployment THEN the system SHALL CONTINUE TO return correct responses with the same data formats and behavior
