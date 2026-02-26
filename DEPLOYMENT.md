# Deployment Guide

This guide covers deploying the Brazilian Financial Data APIs and documentation to Vercel.

## Prerequisites

1. [Vercel account](https://vercel.com/signup)
2. [Vercel CLI](https://vercel.com/docs/cli) installed: `npm i -g vercel`
3. Git repository connected to Vercel

## Architecture

The project consists of:

1. **API Services** (FastAPI) - Deployed as Vercel Serverless Functions
   - CVM API (port 8000 locally)
   - BACEN API (port 8002 locally)
   - B3 CALC API (port 8001 locally)

2. **Documentation** (Mintlify) - Deployed separately to Vercel or Mintlify hosting

## Deployment Options

### Option 1: Deploy APIs to Vercel (Recommended)

The APIs are configured to deploy as Vercel Serverless Functions using the `vercel.json` configuration.

#### Step 1: Install Vercel CLI

```bash
npm i -g vercel
```

#### Step 2: Login to Vercel

```bash
vercel login
```

#### Step 3: Deploy

```bash
# Deploy to preview
vercel

# Deploy to production
vercel --prod
```

#### Step 4: Configure Environment Variables

In the Vercel dashboard, add these environment variables:

```
RATE_LIMIT_ENABLED=false
RATE_LIMIT_REQUESTS=1000
RATE_LIMIT_WINDOW=60
```

### Option 2: Deploy Documentation to Mintlify

Mintlify provides free hosting for documentation sites.

#### Step 1: Sign up at Mintlify

Visit [mintlify.com](https://mintlify.com) and create an account.

#### Step 2: Connect Repository

1. Connect your GitHub repository
2. Mintlify will auto-detect the `mint.json` configuration
3. Deploy automatically on push to main branch

#### Step 3: Update API Base URL

After deploying the APIs, update `mint.json`:

```json
{
  "api": {
    "baseUrl": "https://your-vercel-deployment.vercel.app",
    "auth": {
      "method": "key",
      "name": "X-API-Key"
    }
  }
}
```

### Option 3: Deploy Everything to Vercel

You can deploy both APIs and documentation to Vercel.

#### For Documentation:

Create a separate Vercel project for the Mintlify docs:

```bash
cd /path/to/your/project
vercel --name brazilian-financial-docs
```

## API Endpoints After Deployment

Once deployed, your APIs will be available at:

```
https://your-project.vercel.app/api/v1/cvm/...
https://your-project.vercel.app/api/v1/bacen/...
https://your-project.vercel.app/api/v1/prices/...
https://your-project.vercel.app/health
```

## Testing Deployment

Test your deployed APIs:

```bash
# Health check
curl https://your-project.vercel.app/health

# CVM API
curl https://your-project.vercel.app/api/v1/cvm/fidc/cadastro?page=1&page_size=10

# BACEN API
curl https://your-project.vercel.app/api/v1/bacen/sgs/well-known

# B3 API
curl https://your-project.vercel.app/api/v1/indexes
```

## Vercel Configuration

### vercel.json

The `vercel.json` file configures:

- **Builds**: Each FastAPI app is built as a Python serverless function
- **Routes**: URL routing to the appropriate API
- **Environment**: Default environment variables
- **Regions**: Deployed to São Paulo (gru1) for low latency in Brazil

### Serverless Function Limits

Vercel Serverless Functions have these limits:

- **Execution time**: 10s (Hobby), 60s (Pro), 900s (Enterprise)
- **Memory**: 1024 MB (Hobby), 3008 MB (Pro)
- **Payload size**: 4.5 MB request, 4.5 MB response

If you need longer execution times or larger payloads, consider:
1. Upgrading to Vercel Pro
2. Using Vercel Edge Functions for faster cold starts
3. Deploying to a traditional server (AWS, GCP, Azure)

## Authentication (Optional)

Currently, the APIs don't require authentication. To add API key authentication:

### Option 1: Vercel Edge Middleware

Create `middleware.py`:

```python
from fastapi import Header, HTTPException

async def verify_api_key(x_api_key: str = Header(None)):
    if not x_api_key:
        raise HTTPException(status_code=401, detail="API key required")
    
    # Validate against environment variable or database
    valid_keys = os.getenv("API_KEYS", "").split(",")
    if x_api_key not in valid_keys:
        raise HTTPException(status_code=403, detail="Invalid API key")
    
    return x_api_key
```

Then add to your endpoints:

```python
@app.get("/api/v1/...")
async def endpoint(api_key: str = Depends(verify_api_key)):
    # Your endpoint logic
    pass
```

### Option 2: Vercel Edge Config

Use Vercel's Edge Config for fast API key validation:

```bash
vercel env add API_KEYS production
```

## Monitoring

### Vercel Analytics

Enable Vercel Analytics in your dashboard:
1. Go to your project settings
2. Enable "Analytics"
3. View request metrics, errors, and performance

### Custom Logging

Add structured logging to your FastAPI apps:

```python
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

@app.middleware("http")
async def log_requests(request: Request, call_next):
    start_time = datetime.now()
    response = await call_next(request)
    duration = (datetime.now() - start_time).total_seconds()
    
    logger.info(
        f"{request.method} {request.url.path} "
        f"status={response.status_code} duration={duration}s"
    )
    
    return response
```

## Troubleshooting

### Cold Starts

Serverless functions have cold starts (1-3 seconds). To minimize:

1. Keep function size small (< 5 MB)
2. Minimize dependencies
3. Use Vercel Edge Functions for critical paths
4. Consider keeping functions warm with scheduled pings

### Import Errors

If you see import errors:

1. Ensure all dependencies are in `requirements-vercel.txt`
2. Check Python version compatibility (Vercel uses Python 3.9)
3. Verify relative imports work with Vercel's structure

### Timeout Errors

If functions timeout:

1. Optimize database queries
2. Add caching for expensive operations
3. Consider upgrading to Vercel Pro for 60s timeout
4. Move long-running tasks to background jobs

## Cost Estimation

### Vercel Hobby (Free)

- 100 GB bandwidth/month
- 100 hours serverless function execution/month
- Unlimited deployments
- Good for: Development, small projects, demos

### Vercel Pro ($20/month)

- 1 TB bandwidth/month
- 1000 hours serverless function execution/month
- 60s function timeout
- Good for: Production APIs with moderate traffic

### Vercel Enterprise (Custom pricing)

- Custom bandwidth and execution limits
- 900s function timeout
- SLA guarantees
- Good for: High-traffic production APIs

## Alternative Deployment Options

If Vercel doesn't meet your needs:

### Railway

```bash
railway login
railway init
railway up
```

### Render

```bash
# Create render.yaml
services:
  - type: web
    name: brazilian-financial-apis
    env: python
    buildCommand: pip install -r requirements.txt
    startCommand: uvicorn src.cvm_api.main:app --host 0.0.0.0 --port $PORT
```

### AWS Lambda + API Gateway

Use AWS SAM or Serverless Framework for deployment.

### Traditional VPS

Deploy with Docker Compose to DigitalOcean, Linode, or AWS EC2.

## Next Steps

1. Deploy APIs to Vercel
2. Deploy documentation to Mintlify
3. Update documentation with production URLs
4. Set up monitoring and alerts
5. Configure custom domain (optional)
6. Add authentication (optional)
7. Set up CI/CD with GitHub Actions

## Support

- Vercel Docs: https://vercel.com/docs
- Mintlify Docs: https://mintlify.com/docs
- FastAPI Docs: https://fastapi.tiangolo.com/deployment/
