# Deployment Fixes Applied

## Issues Fixed

### 1. Missing CVM API Requirements File
**Problem:** `src/cvm_api/requirements.txt` was missing, causing Vercel to fail during build.

**Fix:** Created `src/cvm_api/requirements.txt` with all necessary dependencies.

### 2. Deprecated Vercel Configuration
**Problem:** The `name` property in `vercel.json` is deprecated.

**Fix:** Removed the `name` property from `vercel.json`.

### 3. Inconsistent Dependencies
**Problem:** Each API had different dependency versions, causing potential conflicts.

**Fix:** Standardized all three APIs to use the same core dependency versions:
- fastapi==0.109.2
- uvicorn[standard]==0.27.1
- pydantic==2.6.1
- pandas==2.2.0
- numpy==1.26.4
- httpx==0.27.0
- python-dateutil==2.9.0.post0
- slowapi==0.1.9
- rich==13.7.0

### 4. Removed Development Dependencies
**Problem:** B3 API had development tools (black, mypy, isort) in production requirements.

**Fix:** Removed development dependencies from production requirements.txt files.

## Files Modified

1. `vercel.json` - Removed deprecated `name` property
2. `src/cvm_api/requirements.txt` - Created with standardized dependencies
3. `src/bacen_api/requirements.txt` - Updated with standardized dependencies
4. `src/b3_calc_api/requirements.txt` - Updated with standardized dependencies, removed dev tools

## Deploy Again

Now you can deploy again:

```bash
vercel --prod
```

## What Was Fixed

The root cause was:
1. Missing requirements.txt for CVM API
2. Inconsistent dependency versions across APIs
3. Deprecated configuration causing warnings

All three APIs now have:
- ✅ Consistent dependency versions
- ✅ Only production dependencies
- ✅ Complete requirements.txt files
- ✅ Clean Vercel configuration

## Verification

After deployment, test:

```bash
export API_URL="https://your-deployment.vercel.app"

# Test all APIs
curl $API_URL/health
curl $API_URL/api/v1/endpoints
curl "$API_URL/api/v1/bacen/sgs/well-known"
curl "$API_URL/api/v1/indexes"
```

All should return 200 OK.
