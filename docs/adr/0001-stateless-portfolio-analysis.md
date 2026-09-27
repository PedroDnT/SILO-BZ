# 0001. Portfolio analysis is stateless: SILO stores no user portfolios

Date: 2026-09-26. Status: accepted. Context: `docs/planning/PORTFOLIO_DIAGNOSIS.md`, #340.

## Decision

SILO does not store user portfolios, accounts, or what-if runs. Every portfolio
diagnosis takes a **portfolio snapshot** (identifiers, quantities or values,
valuation date) in the request and returns exposures, warnings and benchmark
comparisons without persisting the snapshot. Saving is the client's job.

## Why

SILO is a read-only warehouse of public data with no user state and no write
path from clients. Stored portfolios would add authentication, personal data
under LGPD, and a fourth product surface. A stateless call serves humans (a web
page) and agents (MCP) the same way.

## When to revisit

Only if **monitoring** enters scope: alerts on new filings or restatements that
affect a saved portfolio. Monitoring is the first feature that needs SILO to
remember a portfolio between requests. Anything short of that stays stateless.

## Consequences

- No user tables, no auth, no personal data in Supabase.
- The diagnosis engine reads only schema `api` with the public anon key.
- A client that wants history or saved what-ifs keeps them itself.
