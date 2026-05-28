import { defineConfig } from 'drizzle-kit'

export default defineConfig({
  dialect: 'postgresql',
  schema: './db/schema.ts',
  out: 'netlify/database/migrations',
  dbCredentials: {
    url: process.env.NETLIFY_DATABASE_URL!,
  },
})
