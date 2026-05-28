# Netlify Deploy Skill

Comprehensive workflow for managing Netlify deployments and GitHub Actions CI/CD pipelines.

## Usage

Invoke via `/netlify-deploy` in Claude Code to:
- Set up Netlify configuration (`netlify.toml`)
- Create GitHub Actions deployment workflows
- Manage environment-specific settings
- Troubleshoot deployment issues

## Included Assets

- **SKILL.md** — Workflow steps, templates, and troubleshooting guide
- **Templates** — `netlify.toml` and `.github/workflows/deploy.yml` examples

## Key Features

✅ Preview deployments on pull requests
✅ Automatic production deploys on merge
✅ Environment-specific build configuration
✅ GitHub Actions integration
✅ Secrets and variable management
✅ Build caching and optimization
✅ Rollback and troubleshooting guides

## For This Project (iliquid_nightly)

This project has:
- **Data pipelines** (BACEN, CVM ingestors) → Keep on GitHub Actions / Neon Postgres
- **Daily updates** → Use GitHub Actions scheduling (cron)
- **Cloud backfill** → Separate workflow from Netlify

Only deploy API/UI layers to Netlify, not the core data pipeline infrastructure.
