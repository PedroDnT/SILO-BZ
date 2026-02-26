# Deployment Guide - Vercel

This guide covers deploying both the APIs and Mintlify documentation to Vercel.

## Prerequisites

- Vercel account (sign up at https://vercel.com)
- Vercel CLI installed: `npm install -g vercel`
- Git repository pushed to GitHub/GitLab/Bitbucket

## Architecture Overview

The deployment consists of two parts:

1. **API Backend** - Three FastAPI services (CVM, BACEN, B3 CALC)
2. **Documentation Site** - Mintlify documentation

## Part 1: Deploy APIs to Vercel

### Step 1: Install Vercel CLI

```bash
npm install -g vercel
```

### Step 2: Login to Vercel

```bash
vercel login
```

### Step 3: Configure Project

The project already has a `vercel.json` configuration file that defines:

- Three Python builds (one for each API)
- Route mappings to direct traffic to the correct API
- Environment variables
- São Paulo region (gru1) for low latency

### Step 4: Deploy

From the project root directory:

```bash
# Deploy to preview
vercel

# Deploy to production
vercel --prod
```

### Step 5: Configure Environment Variables (Optional)

If you want to enable rate limiting or other features:

```bash
vercel env add RATE_LIMIT_ENABLED
# Enter: true

vercel env add RATE_LIMIT_REQUESTS
# Enter: 100

vercel env add RATE_LIMIT_WINDOW
# Enter: 60
```

### Step 6: Test the Deployment

Once deployed, Vercel will provide a URL like `https://your-project.vercel.app`

Test the endpoints:

```bash
# Health check
curl https://your-project.vercel.app/health

# CVM API
curl https://your-project.vercel.app/api/v1/cvm/fidc/cadastro?page=1&page_size=10

# BACEN API
curl https://your-project.vercel.app/api/v1/bacen/sgs/well-known

# B3 CALC API
curl https://your-project.vercel.app/api/v1/indexes
```

## Part 2: Deploy Mintlify Documentation

### Option A: Deploy via Mintlify Dashboard (Recommended)

1. Go to https://dashboard.mintlify.com
2. Click "New Documentation"
3. Connect your GitHub repository
4. Select the repository containing your docs
5. Mintlify will auto-detect the `mint.json` file
6. Click "Deploy"

Mintlify will automatically:
- Build and deploy your documentation
- Provide a URL like `https://your-docs.mintlify.app`
- Auto-deploy on every push to main branch

### Option B: Deploy Mintlify to Vercel

If you prefer to host the docs on Vercel:

1. Create a separate Vercel project for docs
2. Add build configuration:

```json
{
  "buildCommand": "mintlify build",
  "outputDirectory": ".mintlify",
  "installCommand": "npm install -g mintlify"
}
```

3. Deploy:

```bash
vercel --prod
```

## Custom Domain Setup

### For APIs

1. Go to your Vercel project dashboard
2. Navigate to Settings → Domains
3. Add your custom domain (e.g., `api.financialdata.com.br`)
4. Follow Vercel's DNS configuration instructions
5. Update `mint.json` with your custom domain:

```json
{
  "api": {
    "baseUrl": "https://api.financialdata.com.br"
  }
}
```

### For Documentation

1. In Mintlify dashboard or Vercel project
2. Add custom domain (e.g., `docs.financialdata.com.br`)
3. Configure DNS records as instructed

## Environment-Specific Configuration

### Development

```bash
# Local development
uvicorn src.cvm_api.main:app --reload --port 8000
uvicorn src.bacen_api.main:app --reload --port 8002
uvicorn src.b3_calc_api.main:app --reload --port 8001

# Local docs
mintlify dev
```

### Staging

Create a separate Vercel project for staging:

```bash
vercel --scope your-team --project staging-apis
```

### Production

```bash
vercel --prod
```

## Monitoring and Logs

### View Logs

```bash
# Real-time logs
vercel logs your-project.vercel.app --follow

# Recent logs
vercel logs your-project.vercel.app
```

### Vercel Dashboard

Monitor your deployment at https://vercel.com/dashboard:
- Request metrics
- Error rates
- Response times
- Bandwidth usage

## Performance Optimization

### 1. Enable Caching

Add cache headers to API responses:

```python
from fastapi import Response

@app.get("/api/v1/data")
async def get_data(response: Response):
    response.headers["Cache-Control"] = "public, max-age=3600"
    return {"data": "..."}
```

### 2. Use Edge Functions

For frequently accessed endpoints, consider Vercel Edge Functions for lower latency.

### 3. Optimize Lambda Size

The current configuration sets `maxLambdaSize: 15mb`. Monitor actual sizes:

```bash
vercel inspect your-deployment-url
```

## Troubleshooting

### Issue: Lambda Timeout

**Solution**: Increase timeout in `vercel.json`:

```json
{
  "functions": {
    "src/*/main.py": {
      "maxDuration": 30
    }
  }
}
```

### Issue: Cold Starts

**Solution**: 
- Keep lambdas warm with periodic health checks
- Consider upgrading to Vercel Pro for faster cold starts

### Issue: Import Errors

**Solution**: Ensure all dependencies are in `requirements.txt`:

```bash
pip freeze > requirements.txt
```

### Issue: 404 on API Routes

**Solution**: Check route configuration in `vercel.json` matches your API paths.

## CI/CD Integration

### GitHub Actions

Create `.github/workflows/deploy.yml`:

```yaml
name: Deploy to Vercel

on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      
      - name: Deploy to Vercel
        uses: amondnet/vercel-action@v20
        with:
          vercel-token: ${{ secrets.VERCEL_TOKEN }}
          vercel-org-id: ${{ secrets.VERCEL_ORG_ID }}
          vercel-project-id: ${{ secrets.VERCEL_PROJECT_ID }}
          vercel-args: '--prod'
```

### GitLab CI

Create `.gitlab-ci.yml`:

```yaml
deploy:
  stage: deploy
  script:
    - npm install -g vercel
    - vercel --token $VERCEL_TOKEN --prod
  only:
    - main
```

## Cost Estimation

### Vercel Pricing (as of 2024)

**Hobby (Free)**
- 100 GB bandwidth/month
- Unlimited deployments
- Automatic HTTPS
- Good for testing/development

**Pro ($20/month)**
- 1 TB bandwidth/month
- Faster builds
- Team collaboration
- Analytics

**Enterprise (Custom)**
- Custom bandwidth
- SLA guarantees
- Dedicated support

### Mintlify Pricing

**Free Tier**
- Unlimited page views
- Auto-deployment
- Custom domain
- Perfect for most use cases

**Pro ($120/month)**
- Advanced analytics
- Custom branding
- Priority support

## Security Best Practices

1. **Environment Variables**: Store sensitive data in Vercel environment variables
2. **CORS**: Configure CORS properly for production
3. **Rate Limiting**: Enable rate limiting in production
4. **HTTPS**: Always use HTTPS (automatic with Vercel)
5. **API Keys**: Implement API key authentication for production

## Rollback Strategy

If a deployment has issues:

```bash
# List deployments
vercel ls

# Promote a previous deployment to production
vercel promote <deployment-url>
```

## Health Checks

Set up monitoring with services like:
- Vercel Analytics (built-in)
- UptimeRobot (external monitoring)
- Datadog (comprehensive monitoring)

Example health check endpoint:

```python
@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": "1.0.0"
    }
```

## Next Steps

1. Deploy APIs to Vercel
2. Deploy documentation to Mintlify
3. Configure custom domains
4. Set up monitoring
5. Enable CI/CD
6. Test all endpoints
7. Share documentation with users

## Support

- Vercel Documentation: https://vercel.com/docs
- Mintlify Documentation: https://mintlify.com/docs
- Project Issues: [Your GitHub Issues URL]
