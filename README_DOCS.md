# Brazilian Financial Data APIs - Documentation

Beautiful, interactive documentation for Brazilian financial data APIs built with Mintlify.

## 🚀 Quick Start

### Prerequisites

- Node.js 18+ installed
- npm or yarn

### Run Locally

```bash
# Install Mintlify CLI
npm install -g mintlify

# Start dev server
mintlify dev
```

The documentation will be available at `http://localhost:3000`

## 📁 Project Structure

```
.
├── mint.json                 # Main configuration
├── introduction.mdx          # Homepage
├── quickstart.mdx           # Quick start guide
├── authentication.mdx       # Auth docs
├── rate-limits.mdx          # Rate limiting
│
├── concepts/                # Core concepts
│   ├── pagination.mdx
│   ├── filtering.mdx
│   ├── error-handling.mdx
│   └── data-formats.mdx
│
├── cvm/                     # CVM API docs
│   ├── overview.mdx
│   ├── operations.mdx
│   ├── entities.mdx
│   └── examples.mdx
│
├── bacen/                   # BACEN API docs
│   ├── overview.mdx
│   ├── sgs-series.mdx
│   ├── ptax.mdx
│   ├── expectations.mdx
│   └── examples.mdx
│
├── b3/                      # B3 CALC API docs
│   ├── overview.mdx
│   ├── pricing.mdx
│   ├── securities.mdx
│   └── examples.mdx
│
└── api-reference/           # API reference
    ├── introduction.mdx
    ├── cvm/
    ├── bacen/
    ├── b3/
    └── system/
```

## 🎨 Customization

### Colors

Edit `mint.json`:

```json
{
  "colors": {
    "primary": "#009879",
    "light": "#00d4a0",
    "dark": "#005f4f"
  }
}
```

### Logo

Add your logo files:
- `logo/light.svg` - Logo for light mode
- `logo/dark.svg` - Logo for dark mode
- `favicon.svg` - Favicon

### API Base URL

Update in `mint.json`:

```json
{
  "api": {
    "baseUrl": "https://your-api-domain.com"
  }
}
```

## 📝 Writing Documentation

### Basic Page

```mdx
---
title: 'Page Title'
description: 'Page description for SEO'
---

Your content here...
```

### API Endpoint Page

```mdx
---
title: 'Get Data'
api: 'GET /api/v1/data'
description: 'Retrieve data from the API'
---

## Overview

Description of the endpoint...

## Parameters

<ParamField query="page" type="integer" default="1">
  Page number
</ParamField>

## Response

```json
{
  "data": []
}
```
```

### Code Examples

```mdx
<CodeGroup>

\`\`\`bash cURL
curl -X GET "https://api.example.com/endpoint"
\`\`\`

\`\`\`python Python
import requests
response = requests.get("https://api.example.com/endpoint")
\`\`\`

</CodeGroup>
```

### Components

```mdx
<Note>
  This is a note
</Note>

<Warning>
  This is a warning
</Warning>

<Tip>
  This is a tip
</Tip>

<Card title="Card Title" icon="icon-name" href="/path">
  Card description
</Card>

<Accordion title="Question">
  Answer
</Accordion>
```

## 🚀 Deployment

### Option 1: Mintlify (Recommended)

1. Go to https://dashboard.mintlify.com
2. Connect your GitHub repository
3. Click "Deploy"

Mintlify will auto-deploy on every push to main.

### Option 2: Vercel

```bash
vercel --prod
```

## 📊 What's Documented

### APIs Covered

- **CVM Credit API** - Brazilian credit market data
- **BACEN API** - Central Bank economic indicators
- **B3 CALC API** - Fixed income pricing calculations

### Documentation Includes

- ✅ Getting started guides
- ✅ Core concepts (pagination, filtering, errors)
- ✅ Complete API overviews
- ✅ Practical code examples
- ✅ Interactive API playground
- ✅ Multi-language examples (Python, JavaScript, cURL)

## 🔍 Features

- **Interactive Playground** - Test APIs directly from docs
- **Code Examples** - Python, JavaScript, cURL
- **Search** - Full-text search across all docs
- **Dark Mode** - Automatic dark/light mode
- **Mobile Friendly** - Responsive design
- **Fast** - Optimized for performance

## 📚 Resources

- [Mintlify Documentation](https://mintlify.com/docs)
- [MDX Documentation](https://mdxjs.com/)
- [Icon Library](https://fontawesome.com/icons)

## 🤝 Contributing

To add or update documentation:

1. Edit the relevant `.mdx` file
2. Test locally with `mintlify dev`
3. Commit and push changes
4. Documentation auto-deploys

## 📄 License

[Your License Here]

## 💬 Support

For questions or issues:
- Email: api-support@financialdata.com.br
- GitHub Issues: [Your Repo URL]
