# Pre-Deployment Checklist

Use this checklist to ensure everything is ready before deploying to Vercel.

## ✅ Code & Configuration

### API Code
- [ ] All three APIs run locally without errors
  ```bash
  uvicorn src.cvm_api.main:app --reload --port 8000
  uvicorn src.bacen_api.main:app --reload --port 8002
  uvicorn src.b3_calc_api.main:app --reload --port 8001
  ```
- [ ] Health check endpoints return 200 OK
- [ ] CORS is properly configured
- [ ] Error handling is implemented
- [ ] Rate limiting is configured (optional)

### Dependencies
- [ ] All dependencies are in `requirements.txt`
- [ ] No missing imports
- [ ] Python version specified (3.9+)

### Vercel Configuration
- [ ] `vercel.json` exists and is valid
- [ ] All three API builds are defined
- [ ] Routes are correctly mapped
- [ ] Environment variables are set (if needed)
- [ ] Region is set to `gru1` (São Paulo)

## ✅ Documentation

### Mintlify Setup
- [ ] `mint.json` is valid JSON
- [ ] All navigation pages exist
- [ ] No broken internal links
- [ ] API base URL is correct
- [ ] Colors and branding are set

### Content
- [ ] All 21+ documentation pages are created
- [ ] Code examples are tested and work
- [ ] No placeholder text remains
- [ ] Images/logos are added (optional)

### Local Testing
- [ ] Run `mintlify dev` successfully
- [ ] All pages load without errors
- [ ] Navigation works correctly
- [ ] Search functionality works
- [ ] API playground loads (if applicable)

## ✅ Testing

### API Endpoints

Test each endpoint locally:

**CVM API (Port 8000)**
```bash
curl http://localhost:8000/health
curl http://localhost:8000/api/v1/endpoints
curl "http://localhost:8000/api/v1/fidc/cadastro?page=1&page_size=5"
```

**BACEN API (Port 8002)**
```bash
curl http://localhost:8002/health
curl http://localhost:8002/api/v1/bacen/sgs/well-known
curl "http://localhost:8002/api/v1/bacen/sgs/11?label=SELIC&last=1"
```

**B3 CALC API (Port 8001)**
```bash
curl http://localhost:8001/health
curl http://localhost:8001/api/v1/indexes
```

- [ ] All health checks return 200
- [ ] All test endpoints return valid data
- [ ] Error responses are properly formatted
- [ ] Response times are acceptable

### Error Handling
- [ ] 404 errors return proper JSON
- [ ] 500 errors are caught and logged
- [ ] Validation errors return 400/422
- [ ] Rate limit errors return 429 (if enabled)

## ✅ Security

### API Security
- [ ] No sensitive data in code
- [ ] No hardcoded credentials
- [ ] Environment variables for secrets
- [ ] CORS configured for production
- [ ] Rate limiting enabled (recommended)

### Documentation
- [ ] No API keys in examples
- [ ] Security best practices documented
- [ ] Authentication guide is clear

## ✅ Performance

### API Optimization
- [ ] Response sizes are reasonable
- [ ] Database queries are optimized (if applicable)
- [ ] Caching headers are set (optional)
- [ ] Lambda size is under 15MB

### Documentation
- [ ] Images are optimized
- [ ] No large files in repo
- [ ] Build time is reasonable

## ✅ Git & Repository

### Version Control
- [ ] All changes are committed
- [ ] `.gitignore` excludes sensitive files
- [ ] No `.env` files in repo
- [ ] Clean commit history

### Repository Setup
- [ ] README.md is updated
- [ ] LICENSE file exists
- [ ] Documentation is in repo
- [ ] No unnecessary files

## ✅ Vercel Account

### Account Setup
- [ ] Vercel account created
- [ ] Vercel CLI installed (`npm install -g vercel`)
- [ ] Logged in (`vercel login`)
- [ ] Team/organization set up (if needed)

### Project Configuration
- [ ] Project name decided
- [ ] Region selected (gru1 - São Paulo)
- [ ] Environment variables prepared
- [ ] Custom domain ready (optional)

## ✅ Deployment Plan

### Pre-Deployment
- [ ] Backup current code
- [ ] Test in staging first (optional)
- [ ] Notify team of deployment
- [ ] Schedule deployment time

### Deployment Steps
1. [ ] Run `vercel` for preview deployment
2. [ ] Test preview deployment thoroughly
3. [ ] Run `vercel --prod` for production
4. [ ] Verify production deployment
5. [ ] Test all endpoints in production
6. [ ] Check Vercel logs for errors

### Post-Deployment
- [ ] Monitor error rates
- [ ] Check response times
- [ ] Verify all endpoints work
- [ ] Test documentation site
- [ ] Update DNS (if using custom domain)

## ✅ Monitoring

### Setup Monitoring
- [ ] Vercel Analytics enabled
- [ ] Error tracking configured
- [ ] Uptime monitoring (optional)
- [ ] Log aggregation (optional)

### Health Checks
- [ ] Set up external health checks
- [ ] Configure alerts for downtime
- [ ] Monitor response times
- [ ] Track error rates

## ✅ Documentation Deployment

### Mintlify
- [ ] Mintlify account created
- [ ] Repository connected
- [ ] Auto-deploy configured
- [ ] Custom domain set (optional)

### Testing
- [ ] Documentation site loads
- [ ] All pages are accessible
- [ ] Search works
- [ ] API playground works
- [ ] Mobile view is correct

## ✅ Final Checks

### Before Going Live
- [ ] All tests pass
- [ ] No console errors
- [ ] No broken links
- [ ] Performance is acceptable
- [ ] Security is configured

### Communication
- [ ] Deployment announcement ready
- [ ] Documentation URL shared
- [ ] Support channels set up
- [ ] Feedback mechanism in place

## 🚀 Ready to Deploy!

Once all items are checked:

```bash
# Preview deployment
vercel

# Test thoroughly, then:
vercel --prod
```

## 📋 Post-Deployment Verification

After deployment, verify:

```bash
# Replace with your actual Vercel URL
export API_URL="https://your-project.vercel.app"

# Test all APIs
curl $API_URL/health
curl $API_URL/api/v1/endpoints
curl "$API_URL/api/v1/bacen/sgs/well-known"
curl "$API_URL/api/v1/indexes"
```

Expected results:
- [ ] All endpoints return 200 OK
- [ ] Response times < 2 seconds
- [ ] No 500 errors in logs
- [ ] Documentation site is live

## 🎉 Success Criteria

Your deployment is successful when:

1. ✅ All API endpoints respond correctly
2. ✅ Documentation site is accessible
3. ✅ No errors in Vercel logs
4. ✅ Response times are acceptable
5. ✅ Health checks pass
6. ✅ Users can access the APIs
7. ✅ Documentation is searchable
8. ✅ API playground works (if enabled)

## 🆘 Rollback Plan

If something goes wrong:

```bash
# List deployments
vercel ls

# Promote previous deployment
vercel promote <previous-deployment-url>
```

## 📞 Support

If you encounter issues:
- Check Vercel logs: `vercel logs --follow`
- Review Vercel documentation: https://vercel.com/docs
- Check Mintlify docs: https://mintlify.com/docs
- Contact support if needed

---

**Last Updated**: 2024-02-26
**Version**: 1.0.0
