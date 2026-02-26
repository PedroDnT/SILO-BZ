# Vercel Deployment Setup

Quick guide to deploy your Brazilian Financial Data APIs to Vercel.

## Quick Start

### 1. Install Vercel CLI

```bash
npm i -g vercel
```

### 2. Login to Vercel

```bash
vercel login
```

### 3. Deploy

```bash
# Preview deployment
./deploy.sh

# Or manually
vercel

# Production deployment
vercel --prod
```

## What Gets Deployed

Your Vercel deployment includes:

- **CVM API** - `/api/v1/cvm/*`
- **BACEN API** - `/api/v1/bacen/*`
- **B3 CALC API** - `/api/v1/prices/*`, `/api/v1/securities/*`
- **Health Check** - `/health`

## Configuration Files

### vercel.json

Main configuration file that defines:
- Build settings for each API
- URL routing
- Environment variables
- Deployment region (São Paulo - gru1)

### requirements-vercel.txt

Python dependencies for Vercel deployment. Optimized for serverless functions.

### .vercelignore

Files to exclude from deployment (tests, cache, local files).

## Environment Variables

Set these in your Vercel dashboard or via CLI:

```bash
vercel env add RATE_LIMIT_ENABLED production
vercel env add RATE_LIMIT_REQUESTS production
vercel env add RATE_LIMIT_WINDOW production
```

Or in the Vercel dashboard:
1. Go to your project
2. Settings → Environment Variables
3. Add variables for Production, Preview, and Development

## Testing Your Deployment

After deployment, test your APIs:

```bash
# Get your deployment URL
VERCEL_URL="your-project.vercel.app"

# Health check
curl https://$VERCEL_URL/health

# CVM API
curl https://$VERCEL_URL/api/v1/cvm/fidc/cadastro?page=1&page_size=5

# BACEN API
curl https://$VERCEL_URL/api/v1/bacen/sgs/well-known

# B3 API
curl https://$VERCEL_URL/api/v1/indexes
```

## Documentation Deployment

### Option 1: Mintlify (Recommended)

1. Sign up at [mintlify.com](https://mintlify.com)
2. Connect your GitHub repository
3. Mintlify auto-detects `mint.json` and deploys
4. Update `mint.json` with your Vercel API URL:

```json
{
  "api": {
    "baseUrl": "https://your-project.vercel.app"
  }
}
```

### Option 2: Vercel Static Site

Deploy docs as a separate Vercel project:

```bash
mintlify build
vercel --name brazilian-financial-docs
```

## Automatic Deployment with GitHub Actions

The `.github/workflows/deploy.yml` file enables automatic deployment on push to main.

### Setup GitHub Secrets

Add these secrets to your GitHub repository:

1. Go to Settings → Secrets and variables → Actions
2. Add these secrets:
   - `VERCEL_TOKEN` - Get from https://vercel.com/account/tokens
   - `VERCEL_ORG_ID` - Run `vercel` locally and check `.vercel/project.json`
   - `VERCEL_PROJECT_ID` - Same as above

### How It Works

- **Pull Requests**: Deploy to preview environment, comment URL on PR
- **Push to main**: Deploy to production automatically

## Custom Domain

### Add Custom Domain

1. Go to your Vercel project
2. Settings → Domains
3. Add your domain (e.g., `api.financialdata.com.br`)
4. Update DNS records as instructed
5. Update `mint.json` with your custom domain

### DNS Configuration

For `api.financialdata.com.br`:

```
Type: CNAME
Name: api
Value: cname.vercel-dns.com
```

## Monitoring

### Vercel Analytics

Enable in project settings:
- Real-time request metrics
- Error tracking
- Performance monitoring

### Custom Logging

View logs in Vercel dashboard or via CLI:

```bash
vercel logs
vercel logs --follow  # Live tail
```

## Troubleshooting

### Cold Starts

Serverless functions have 1-3s cold starts. To minimize:
- Keep dependencies minimal
- Use caching
- Consider Vercel Pro for better performance

### Function Timeout

Default timeout is 10s (Hobby) or 60s (Pro). If you hit limits:
- Optimize slow queries
- Add caching
- Upgrade to Pro or Enterprise

### Import Errors

If imports fail:
- Check `requirements-vercel.txt` includes all dependencies
- Verify Python 3.9+ compatibility
- Test locally with same Python version

### CORS Issues

If you get CORS errors:
- APIs already have CORS enabled (`allow_origins=["*"]`)
- Check browser console for specific errors
- Verify request headers

## Cost Optimization

### Hobby Plan (Free)

- 100 GB bandwidth/month
- 100 hours function execution/month
- Good for: Development, demos, low-traffic APIs

### Pro Plan ($20/month)

- 1 TB bandwidth/month
- 1000 hours function execution/month
- 60s timeout
- Good for: Production APIs with moderate traffic

### Tips to Reduce Costs

1. **Cache responses** - Reduce function invocations
2. **Optimize bundle size** - Faster cold starts
3. **Use CDN** - Serve static content from edge
4. **Monitor usage** - Track bandwidth and execution time

## Alternative Deployment

If Vercel doesn't fit your needs:

### Railway
```bash
railway login
railway init
railway up
```

### Render
```bash
# Create render.yaml and push to GitHub
```

### Docker + VPS
```bash
docker-compose up -d
```

## Support

- **Vercel Docs**: https://vercel.com/docs
- **Vercel Support**: https://vercel.com/support
- **Community**: https://github.com/vercel/vercel/discussions

## Next Steps

1. ✅ Deploy APIs to Vercel
2. ✅ Test all endpoints
3. ✅ Deploy documentation to Mintlify
4. ✅ Update docs with production URLs
5. ⬜ Add custom domain (optional)
6. ⬜ Set up monitoring
7. ⬜ Configure CI/CD
8. ⬜ Add authentication (optional)
