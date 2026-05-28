---
name: netlify-deploy
description: "Use when: setting up or managing Netlify deployments, GitHub Actions CI/CD workflows, preview deployments, environment config, or troubleshooting deployment issues. Guides comprehensive DevOps workflows from development to production."
---

# Netlify Deployment & CI/CD Workflow

On-demand workflow for managing Netlify deployments, GitHub Actions pipelines, and CI/CD infrastructure.

## Quick Start

```
/netlify-deploy setup        # Initialize Netlify config and GitHub Actions
/netlify-deploy preview      # Configure preview deployments
/netlify-deploy production   # Set up production deployment pipeline
/netlify-deploy troubleshoot # Debug deployment failures
```

## Core Capabilities

### 1. **Netlify Configuration**
- `netlify.toml` setup with build commands, environment variables, and redirects
- Site linking and API token management
- Deploy preview integration with pull requests
- Build caching and optimization

### 2. **GitHub Actions Pipelines**
- Automated build and test workflows
- Conditional deployments (staging, preview, production)
- Status checks and branch protection rules
- Secrets management for API keys and tokens

### 3. **Environment Management**
- Development, staging, and production configuration
- Database connection strings and secrets
- Build-time vs runtime variables
- Branch-specific settings

### 4. **Deployment Strategies**
- Manual deployments for hotfixes
- Automatic deployments on merge to main
- Preview deployments for every PR
- Rollback procedures

## Workflow Steps

### Phase 1: Discovery
- Identify current deployment setup (if any)
- Map target deployment environments
- List required integrations (Netlify, GitHub, databases, APIs)
- Document secrets and access requirements

### Phase 2: Configuration
- Create `netlify.toml` with build settings
- Set up environment-specific `*.env` or `.env.example` files
- Configure GitHub Actions workflows in `.github/workflows/`
- Link Netlify site to repository

### Phase 3: Integration
- Connect GitHub to Netlify for deploy previews
- Set up status checks and required reviews
- Configure webhook notifications
- Test deployment pipeline end-to-end

### Phase 4: Optimization
- Configure build caching strategies
- Optimize dependency installation
- Set up performance monitoring
- Document runbooks for common issues

## Templates

### netlify.toml

```toml
[build]
  command = "npm run build"  # or: python -m build, pip install & python deploy, etc
  functions = "functions"
  publish = "dist"  # or: build/, out/, etc

[build.environment]
  NODE_VERSION = "20"
  PYTHON_VERSION = "3.11"

[[redirects]]
  from = "/api/*"
  to = "/.netlify/functions/:splat"
  status = 200

[[redirects]]
  from = "/*"
  to = "/index.html"
  status = 200

[context.production]
  command = "npm run build:prod"
  
[context.deploy-preview]
  command = "npm run build:preview"
```

### .github/workflows/deploy.yml

```yaml
name: Deploy to Netlify
on:
  push:
    branches: [main, staging]
  pull_request:
    types: [opened, synchronize]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Build
        run: npm run build
        env:
          NODE_ENV: production
      
      - name: Deploy to Netlify
        uses: nwtgck/actions-netlify@v3
        with:
          publish-dir: './dist'
          production-branch: main
          github-token: ${{ secrets.GITHUB_TOKEN }}
          deploy-message: "Deploy from GitHub Actions"
          enable-pull-request-comment: true
          enable-commit-comment: true
        env:
          NETLIFY_AUTH_TOKEN: ${{ secrets.NETLIFY_AUTH_TOKEN }}
          NETLIFY_SITE_ID: ${{ secrets.NETLIFY_SITE_ID }}
```

## Common Patterns

**Preview Deployments on PR**
- Netlify auto-deploys each PR as a unique URL
- Runs `netlify.toml` build command
- Adds status check to PR
- Comments with preview URL

**Production Deployments**
- Only triggered on `main` branch
- Requires manual review or passing tests
- Sets production environment variables
- Enables monitoring and alerting

**Scheduled Backfills**
- Use GitHub Actions schedule (`cron`)
- Trigger long-running tasks (data pipelines, batch jobs)
- Separate from Netlify (use Neon/Postgres tasks or GitHub Actions jobs)

## Troubleshooting

| Issue | Solution |
|-------|----------|
| **Build fails locally but succeeds on Netlify** | Check Node version, environment variables, and dependencies in `netlify.toml` |
| **Preview deploys don't show PR comment** | Verify `GITHUB_TOKEN` has repo access in GitHub Actions secrets |
| **Secrets not available at build time** | Set as build-time variables in Netlify UI or `.env.example` → `.env` during build |
| **Database connection fails in deploy** | Ensure connection string uses `HEROKU_POSTGRESQL_*` or Neon/Supabase public URL, not localhost |

## Next Steps

Once deployed:
1. **Monitor** — Set up error tracking (Sentry, LogRocket, Cloudflare Analytics)
2. **Optimize** — Profile build time, enable caching, lazy-load dependencies
3. **Automate** — Add E2E tests, performance budgets, security scanning
4. **Scale** — Consider edge functions for serverless logic, Netlify Graph for APIs

---

**Note**: For data pipelines (like in iliquid_nightly), consider keeping scheduled jobs separate from Netlify. Use GitHub Actions for orchestration, Neon Postgres for persistence, and deploy only the API/UI layer to Netlify.
