# 0007. Dashboard npm alerts: accepted build-time risk

Date: 2026-11-23. Status: accepted (the owner delegated the decision to the orchestrator, issue
#1124, decision comment of 2026-11-23).

## Context

`npm audit --package-lock-only` in `dashboard/` on `main` @ `53a4ae9` lists 36 alerts (2 critical,
9 high, 25 moderate); the decision comment counted 34 (2/8/24) earlier the same day, one high and one
moderate fewer. Nearly all of them come from the versions `@evidence-dev/evidence`
pins. 40.1.8 is its latest release (2026-02-06), and it still pins `@sveltejs/kit` 2.8.4, `vite`
5.4.21, `svelte` 4.2.19 and `typescript` 5.4.2 exactly. The critical fixes need vitest 4.x and the
high ones vite 6.x, zod 4.x or a newer kit, none of which Evidence allows; several sit inside
`@evidence-dev/*` with no fix at all.

## Decision

- **Take the one patch-level fix:** the `body-parser` override goes from 1.20.8 to 1.20.9, which
  clears GHSA-27r3-jxmh-p828 (DoS through trailing bytes after a compressed body). No other
  dependency changes.
- **Accept the rest as build-time risk.** `vercel.json` publishes only the static output
  `dashboard/build`, with no serverless functions. The critical and high advisories are request
  DoS in body-parser and kit, vite dev-server path traversal and file serving, and vitest/tinypool
  test-runner issues. Each needs a running Node server, dev server or test runner, so none is
  reachable on the public site. They apply only to the Vercel build, CI, and a machine running
  `evidence dev`.

After the bump the audit lists 36 alerts (2 critical, 7 high, 27 moderate).

**Accepted packages:**

- Critical: `tinypool`, `vitest`.
- High: `vite`, `zod`, `@sveltejs/kit`, and `@evidence-dev/core-components`, `plugin-connector`,
  `sdk` and `tailwind`.
- Moderate: the other `@evidence-dev/*` packages, `@sveltejs/adapter-static`,
  `vite-plugin-svelte` and its inspector, `@vitest/coverage-v8`, `@vitest/mocker`, `vite-node`,
  `vitefu`, `esbuild`, `svelte`, `svelte-hmr`, `mdsvex`, `@melt-ui/svelte`, `bits-ui`, `cmdk-sv`,
  `@steeze-ui/svelte-icon`, `@typescript-eslint/typescript-estree`, `glob`, `minimatch`,
  `test-exclude` and `echarts`.

**What the static-output argument does not cover.** Some moderate advisories concern code that
ships to the browser: `echarts` < 6.1.0 (XSS), `svelte` <= 5.55.6 (XSS through spread
attributes, DOM clobbering, and during SSR), and some kit advisories (XSS during prerendering).
Each needs attacker-controlled input rendered into the page. They are accepted because the fix
needs svelte 5 or a newer kit, which Evidence does not allow, not because they are unreachable.

**Fixed by the 6.16.2 override (#1195).** After the bump, `body-parser` and `express` still
appeared, only through `qs` 6.16.0 (GHSA-6pq8-jhm2-2vcw, a `qs.stringify` DoS; the range ends at
6.16.0). That advisory is newer than the decision. The `qs` override now pins 6.16.2, which is
outside the range.

## Revisit when

- an Evidence release lifts the kit, vite or svelte pins; or
- any change adds a server, serverless functions or middleware to the dashboard deployment.

Dismissing the accepted alerts in the GitHub Security tab, citing this ADR, is the owner's step:
agents get 403 on the Dependabot alerts API. The repository shows 37 alerts; those outside
`dashboard/` (probably `webapp/` or `deploy/cloudflare/`) are not covered here.
