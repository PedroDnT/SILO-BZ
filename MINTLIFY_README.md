# Mintlify Documentation Site

This directory contains the Mintlify documentation site for the Brazilian Financial Data APIs.

## Quick Start

### Prerequisites

- Node.js 18+ installed
- npm or yarn package manager

### Installation

1. Install Mintlify CLI globally:

```bash
npm install -g mintlify
```

2. Navigate to the project root directory (where `mint.json` is located)

### Running Locally

Start the development server:

```bash
mintlify dev
```

The documentation site will be available at `http://localhost:3000`

### Building for Production

Build the static site:

```bash
mintlify build
```

## Project Structure

```
.
├── mint.json                 # Main configuration file
├── introduction.mdx          # Homepage
├── quickstart.mdx           # Quick start guide
├── authentication.mdx       # Authentication docs
├── rate-limits.mdx          # Rate limiting docs
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
├── api-reference/           # API reference docs
│   ├── introduction.mdx
│   ├── cvm/
│   │   ├── list-operations.mdx
│   │   ├── get-operation.mdx
│   │   └── endpoints.mdx
│   ├── bacen/
│   │   ├── well-known-series.mdx
│   │   ├── get-series.mdx
│   │   └── ...
│   ├── b3/
│   │   ├── debentures.mdx
│   │   └── ...
│   └── system/
│       └── health.mdx
│
├── sdks/                    # SDK documentation
│   ├── python.mdx
│   ├── javascript.mdx
│   └── java.mdx
│
└── guides/                  # User guides
    ├── getting-started.mdx
    ├── best-practices.mdx
    ├── use-cases.mdx
    └── troubleshooting.mdx
```

## Configuration

### mint.json

The `mint.json` file contains all configuration for the documentation site:

- **Navigation**: Define the sidebar structure
- **Branding**: Colors, logos, and styling
- **API Settings**: Base URL and authentication
- **Tabs**: Top-level navigation tabs
- **Anchors**: External links in the navigation

### Customization

#### Colors

Edit the `colors` section in `mint.json`:

```json
"colors": {
  "primary": "#009879",
  "light": "#00d4a0",
  "dark": "#005f4f"
}
```

#### Logo

Add your logo files to a `logo/` directory:
- `logo/light.svg` - Logo for light mode
- `logo/dark.svg` - Logo for dark mode

#### Favicon

Add `favicon.svg` to the root directory

## Writing Documentation

### MDX Format

All documentation files use MDX (Markdown + JSX). This allows you to use:

- Standard Markdown syntax
- React components
- Mintlify-specific components

### Frontmatter

Every MDX file must start with frontmatter:

```mdx
---
title: 'Page Title'
description: 'Page description for SEO'
---
```

### API Endpoints

For API reference pages, add the `api` field:

```mdx
---
title: 'List Operations'
api: 'GET /api/v1/cvm/{entity}/{doc_type}'
description: 'Retrieve paginated list of CVM data'
---
```

### Components

Mintlify provides many built-in components:

#### Cards

```mdx
<Card title="Title" icon="icon-name" href="/path">
  Description
</Card>

<CardGroup cols={2}>
  <Card title="Card 1" icon="icon1" href="/path1">
    Description 1
  </Card>
  <Card title="Card 2" icon="icon2" href="/path2">
    Description 2
  </Card>
</CardGroup>
```

#### Code Blocks

```mdx
<CodeGroup>

\`\`\`python Python
print("Hello World")
\`\`\`

\`\`\`javascript JavaScript
console.log("Hello World");
\`\`\`

</CodeGroup>
```

#### Accordions

```mdx
<AccordionGroup>
  <Accordion title="Question 1">
    Answer 1
  </Accordion>
  <Accordion title="Question 2">
    Answer 2
  </Accordion>
</AccordionGroup>
```

#### Callouts

```mdx
<Note>
  This is a note
</Note>

<Tip>
  This is a tip
</Tip>

<Warning>
  This is a warning
</Warning>

<Info>
  This is info
</Info>
```

#### Parameters

```mdx
<ParamField path="entity" type="string" required>
  Entity type description
</ParamField>

<ParamField query="page" type="integer" default="1">
  Page number
</ParamField>
```

#### Response Fields

```mdx
<ResponseField name="data" type="array">
  Array of records
  <Expandable title="properties">
    <ResponseField name="id" type="string">
      Record ID
    </ResponseField>
  </Expandable>
</ResponseField>
```

#### Request/Response Examples

```mdx
<RequestExample>

\`\`\`bash cURL
curl -X GET "https://api.example.com/endpoint"
\`\`\`

</RequestExample>

<ResponseExample>

\`\`\`json Response
{
  "data": []
}
\`\`\`

</ResponseExample>
```

## Deployment

### Mintlify Hosting

1. Sign up at [mintlify.com](https://mintlify.com)
2. Connect your GitHub repository
3. Mintlify will automatically deploy on push to main

### Custom Hosting

Build and deploy the static site:

```bash
mintlify build
# Deploy the generated files from the build directory
```

## API Playground

The interactive API playground is automatically enabled for pages with the `api` field in frontmatter. Configure it in `mint.json`:

```json
"api": {
  "baseUrl": "https://api.financialdata.com.br",
  "auth": {
    "method": "key",
    "name": "X-API-Key"
  },
  "playground": {
    "mode": "show"
  }
}
```

## Next Steps

1. **Complete Missing Pages**: Create the remaining documentation pages listed in `mint.json`
2. **Add Examples**: Add more code examples and use cases
3. **Customize Branding**: Add your logos and adjust colors
4. **Test Locally**: Run `mintlify dev` and test all pages
5. **Deploy**: Push to GitHub and deploy via Mintlify

## Resources

- [Mintlify Documentation](https://mintlify.com/docs)
- [MDX Documentation](https://mdxjs.com/)
- [Icon Library](https://fontawesome.com/icons)

## Support

For issues or questions:
- Mintlify: [support@mintlify.com](mailto:support@mintlify.com)
- Project: [api-support@financialdata.com.br](mailto:api-support@financialdata.com.br)
