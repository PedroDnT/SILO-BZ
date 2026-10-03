# Cloudflare Containers for the portfolio-diagnosis engine

Research for issue #518 (child of map #510). It answers whether the Python
engine of the portfolio-diagnosis demo can run in a Cloudflare Container behind
a Worker, what it costs, how secrets reach it, and what the owner must set up so
ticket #519 can be written. It records findings only. It makes no design
decision and changes nothing in the repository's pipeline.

Throwaway branch `research/cloudflare-container`, not for merge.

## How to read this note

- **Access dates.** Every page was read on 2026-10-02 between about 23:00 and
  23:30 UTC-3 (2026-10-03, 02:00 to 02:30 UTC). Quotes are verbatim. Sources are
  listed at the end with how each was fetched.
- **Two fetch channels.** "Docs search" is the Cloudflare MCP documentation
  search (semantic chunks of developers.cloudflare.com). "Scrape" is a Firecrawl
  fetch of the page. Four scrapes came from Firecrawl's cache, dated in the
  source list. Everything else was a live fetch or a docs-search chunk.
- **Not verified** means no primary source was found or the claim needs a test.
  Section 9 collects them. Nothing in this note is an invented limit or price.
- Times are UTC-3 with UTC in parentheses where they matter.

## 1. Summary

| Question                                                                               | Finding                                                                                                                                                                                                                                                                                                                         |
| -------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Can a Python engine with PDF parsing and rendering run in a Container behind a Worker? | Yes in principle. A Container is any Linux image (`linux/amd64`) run in a Firecracker microVM, reached only through a Worker and its Durable Object. Image size is capped by the instance disk (2 to 20 GB). No Cloudflare page lists poppler, WeasyPrint or Chromium. Whether the engine fits 1 GiB (`basic`) is not verified. |
| Status                                                                                 | Generally available since 2026-04-13, on the Workers Paid plan only. The newer `durable_object` scheduling policy is beta.                                                                                                                                                                                                      |
| Upload handled in memory, never stored?                                                | Disk is ephemeral and reset on sleep. The platform stores nothing unless the code writes it. Two leaks to close: Workers Logs (7 days) and container stdout. Whether request bodies are logged is not documented (not verified).                                                                                                |
| Secrets                                                                                | Worker secret, passed in `env` at container start, or kept in the Worker and injected on the way out by an outbound handler. The client never sees either.                                                                                                                                                                      |
| Cost                                                                                   | Worker plan $5/month floor. A 60-second run costs about $0.0005 to $0.002 on `basic` and about $0.001 to $0.008 on `standard-1`, depending on the idle window. Section 4. LLM provider cost is excluded.                                                                                                                        |
| If Containers do not fit                                                               | Python Workers (Pyodide) cannot run poppler or WeasyPrint. Pure-Python PDF libraries might. Section 5.                                                                                                                                                                                                                          |
| Pages                                                                                  | Cannot host the Container. A separate Worker is needed. Cloudflare recommends Workers Static Assets over Pages for new projects. Section 8.                                                                                                                                                                                     |

## 2. Can the engine run in a Container?

### 2.1 Definition and request path

- A Container is reached only through a Worker and a Durable Object.
  > "A Container can only be accessed through its Durable Object. A Worker sends a request to the Durable Object, which accesses the Container through `ctx.container`."

  (<https://developers.cloudflare.com/containers/concepts/architecture/>, scrape.)
- End users cannot reach it directly.
  > "Because all Container requests are passed through a Worker, end-users cannot make non-HTTP TCP or UDP requests to a Container instance."

  (same page.)
- Runtime and architecture.
  > "Each container instance runs in a Firecracker microVM with its own kernel and network."
  > "Containers should be built for the `linux/amd64` architecture"

  (same page.)
- Configuration is `wrangler.jsonc` with a `containers` entry (`class_name`,
  `image: "./Dockerfile"`, `max_instances`), a `durable_objects` binding and an
  `exports` entry with `storage: "sqlite"`.
  (<https://developers.cloudflare.com/containers/>, scrape, last updated 2026-09-30.)
- The Worker forwards the request into the container port with
  `this.ctx.container.getTcpPort(8080).fetch(forwarded)`.
  (<https://developers.cloudflare.com/containers/examples/env-vars-and-secrets/>, scrape.)

### 2.2 Scheduling policy decides the instance sizes

| Policy                                                       | Status          | Sizes allowed                                                                                         | Notes                                                                      |
| ------------------------------------------------------------ | --------------- | ----------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------- |
| `default` (what you get when `scheduling_policy` is omitted) | Not marked beta | `lite`, `basic`, `standard-1` to `standard-4`, or a custom size, set with `instance_type` in Wrangler | `max_instances` supported. Image changes roll out application-wide.        |
| `durable_object`                                             | beta            | `lite`, `standard-1` to `standard-4`, or custom, set in `ctx.container.start({instance})`             | `max_instances` not supported. `cloudflare/debian-trixie` image only here. |

Quotes (<https://developers.cloudflare.com/containers/configuration/scheduling-policy/>,
scrape from Firecrawl cache dated 2026-10-02 21:25 UTC):

> "`durable_object` (beta)"
> "The runtime does not accept `basic` or the legacy `dev` and `standard` aliases."
> "If you omit `instance`, the Container uses `lite`."
> "The `durable_object` policy does not support `max_instances`."
> "Omitting `scheduling_policy` selects `default`."

The overview example runs the Durable Object Container API under the `default`
policy (`image: "./Dockerfile"`, `max_instances: 5`), so `ctx.container` is not
limited to the beta policy. For new applications Cloudflare says:

> "For new applications, use the Durable Object Container API to combine direct container control with Durable Object storage and coordination."

(<https://developers.cloudflare.com/containers/api/>, docs search.) The older
`Container` class (`@cloudflare/containers`) is still supported.

### 2.3 Instance types and limits

(<https://developers.cloudflare.com/containers/platform-details/limits/>, redirected to
`/containers/platform/limits/`, scrape, live fetch, last updated 2026-09-30.)

| Instance type | vCPU | Memory  | Disk  |
| ------------- | ---- | ------- | ----- |
| lite          | 1/16 | 256 MiB | 2 GB  |
| basic         | 1/4  | 1 GiB   | 4 GB  |
| standard-1    | 1/2  | 4 GiB   | 8 GB  |
| standard-2    | 1    | 6 GiB   | 12 GB |
| standard-3    | 2    | 8 GiB   | 16 GB |
| standard-4    | 4    | 12 GiB  | 20 GB |

Custom sizes: minimum 1 vCPU, maximum 4 vCPU, maximum 12 GiB memory, maximum 20 GB
disk, "Minimum 3 GiB memory per vCPU" (the same page).

Account limits: concurrent memory 6 TiB, concurrent vCPU 1,500, concurrent disk 30 TB,
total image storage per account 50 GB. Image size:

> "Image size | Same as instance disk space"

(the same page.) A Chromium or WeasyPrint image has to fit the disk of the type
chosen. Image sizes of poppler, WeasyPrint or Chromium images were not measured here
(not verified).

### 2.4 Cold start and scale to zero

> "Container cold starts can often be in the 1-3 second range, but this is dependent on image size and code execution time, among other factors."

(<https://developers.cloudflare.com/containers/faq/>, scrape, live fetch, last updated 2026-10-02.)

- First deploy: "After you deploy your Worker for the first time, wait several minutes
  before you expect container requests to succeed."
  (<https://developers.cloudflare.com/containers/get-started/>, docs search.)
- Scale to zero:
  > "Charges stop after the container instance goes to sleep, which can happen automatically after a timeout. This makes it easy to scale to zero"

  (<https://developers.cloudflare.com/containers/platform/pricing/>, scrape, live fetch, last updated 2026-08-28.)
- Sleep timers. `Container` class: `sleepAfter` default `"10m"`
  (<https://developers.cloudflare.com/containers/api/container-class/>, docs search).
  Durable Object Container API: `setInactivityTimeout()` accepts more than 0 and at most 6
  hours, and
  > "Without a timeout, Cloudflare stops the container shortly after the Durable Object becomes inactive."

  (<https://developers.cloudflare.com/containers/api/durable-object-container/>, docs search.) "Shortly" is not quantified.
- No built-in autoscaling for stateless apps:
  > "Not today, though Cloudflare plans to add built-in autoscaling in a future release."

  (FAQ, as above.) A new Durable Object name starts a new instance, so one name per
  request gives one container per upload. This is an inference from the cold-start
  text, not a documented pattern for this use.
- A 1-3 second figure for an image carrying poppler plus WeasyPrint or Chromium is
  not verified.

### 2.5 Request duration and body size

| Limit                                | Value                                                                                                                                                                                 | Source                                                                     |
| ------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------- |
| Worker duration, HTTP request        | "No limit" while the client stays connected                                                                                                                                           | <https://developers.cloudflare.com/workers/platform/limits/> (docs search) |
| Durable Object (RPC / HTTP) duration | "Unlimited ... while the caller stays connected"                                                                                                                                      | same page                                                                  |
| Worker CPU time per HTTP request     | 5 min maximum, default 30 seconds. Waiting on `fetch()` does not count                                                                                                                | same page                                                                  |
| Runtime update grace                 | "The runtime gives in-flight requests a 30-second grace period to finish. If a request does not finish within this time, the runtime terminates it."                                  | same page                                                                  |
| Container run time                   | "Cloudflare does not stop a container instance after a fixed maximum runtime." A host restart can stop it: SIGTERM, wait up to 15 minutes, SIGKILL                                    | FAQ                                                                        |
| Request body (client to Worker)      | Free 100 MB, Pro 100 MB, Business 200 MB, Enterprise up to 5 GB. "Request body size limits depend on your Cloudflare account plan, not your Workers plan." Over the limit returns 413 | Workers limits                                                             |
| Worker memory                        | 128 MB per isolate, including WebAssembly                                                                                                                                             | Workers limits                                                             |

Consequences for a 60-second report:

- A 60-second run is inside the documented limits. It can still be cut by a runtime
  update (30-second grace) or a host stop. The Worker should treat a dropped request as
  retryable, and the engine should be idempotent per upload.
- A broker statement is small next to 100 MB. To stay under the 128 MB isolate limit the
  Worker should stream `request.body` into the container (the R2 docs make the same
  point: "consider using Streams"). The limit for the Worker-to-container hop itself was
  not found (not verified).
- Client-facing timeouts on a long open request (for example Cloudflare's proxy read
  timeout) were not researched (not verified). A 60-second synchronous call may need a
  poll or stream design.

### 2.6 Processing in memory, ephemeral disk, logging (privacy)

- Disk:
  > "All disk is ephemeral by default. When a Container instance goes to sleep, the next time it starts, it uses a fresh disk from the container image."

  (FAQ.) Snapshots are opt-in (`durable_object` policy only). FUSE to R2 is opt-in.
  Neither is needed. Anything written to the container disk (a temporary PDF, a rendered
  report) survives until sleep, so the engine should write nothing, or delete files at
  once, and keep the idle window short.
- Durable Object storage: the `exports` entry in every example sets
  `storage: "sqlite"`. The platform does not write to it for you. The code must not call
  `ctx.storage`. The `Container` class getting-started page points out that
  `this.ctx.storage` is available "to persist data that survives container restarts".
- No R2, KV or D1 binding is required to run a container. The env-vars example binds KV
  only to demonstrate passing values. Do not copy it.
- Container logs go to Workers Logs when `observability.enabled` is true:
  > "Logs are subject to the same limits as Workers Logs and are retained for seven days."
  > "Beginning December 1, 2026, Container logs use Cloudflare Observability pricing."

  (FAQ.) Anything the engine prints to stdout or stderr lands there. The engine must
  never print upload content, extracted text or the LLM prompt.
- Worker invocation logs:
  > "All newly created Workers will come with the observability setting enabled by default."

  (<https://developers.cloudflare.com/workers/observability/logs/workers-logs/>, docs search.)
  "By default a Worker will emit invocation logs containing details about the request, response and related metadata."
  The message for a `fetch` is `<Method> <URL>`, so the query string is logged. Trace
  events capture "console.log() statements, exceptions, request metadata, and headers"
  (<https://developers.cloudflare.com/changelog/post/2025-04-07-increase-trace-events-limit/>, docs search).
  Invocation logs can be switched off with `"observability": {"logs": {"invocation_logs": false}}`.
- Whether the request body is ever logged is **not documented**. The pages list
  metadata and headers, not bodies. Absence of a statement is not proof. The owner's
  privacy claim should rest on a test: deploy, send a marked upload, search Workers Logs.
- Data leaves Cloudflare to the LLM provider by design. That is the provider's retention
  policy, not covered here (not verified, out of scope).

## 3. Secrets and egress

### 3.1 Passing the LLM key to the Container

- The Cloudflare FAQ:
  > "You can use Worker Secrets or the Secrets Store to define secrets for your Workers."

  (FAQ.) The example passes them with `env` in `ctx.container.start()`:
  "Pass runtime environment variables through `env` in `ctx.container.start()`. Read Worker secrets, Secrets Store values, and KV data inside the Durable Object before starting its Container."
  "A running process keeps its startup environment. Updating a secret or KV value does not change that process's environment"
  (<https://developers.cloudflare.com/containers/examples/env-vars-and-secrets/>, scrape.)
  That example uses `scheduling_policy: "durable_object"`. Whether `start({env})` is accepted
  under the `default` policy through `ctx.container` was not shown (not verified). The
  `Container` class does take `envVars` and per-start `startOptions.envVars`
  (<https://developers.cloudflare.com/containers/api/container-class/>, docs search).
- Build arguments are not for secrets: "Keep secrets out of build arguments and container images."
- Creating the secret: `npx wrangler secret put <NAME>` (same example). Worker secrets are
  the simpler path. Secrets Store is documented as an open beta with "up to 100 secrets per
  account" and "only one store per account"
  (<https://developers.cloudflare.com/secrets-store/manage-secrets/>, docs search), and a
  token that deploys a Worker bound to a store needs "Account Secrets Store Edit"
  (<https://developers.cloudflare.com/secrets-store/access-control/>, docs search).
- Keeping the key off the client: the browser only talks to the Worker. The key is a
  Worker secret, read in the Durable Object and handed to the container at start.
- Stronger option, so the container never holds the key. Outbound handlers can inject
  credentials:
  > "Use them to: Allow or deny specific origin destinations / Safely inject authorization headers or tokens"

  (<https://developers.cloudflare.com/containers/configuration/outbound-traffic/>, docs search.)
  The Cloudflare sandbox network page describes the pattern: "Keep the token in your Worker
  instead ... your Worker intercepts each request and adds the token."
  (<https://developers.cloudflare.com/sandbox/network/>, docs search.) For HTTPS to
  `api.anthropic.com` this needs `interceptHttps = true` and the container trusting
  `/etc/cloudflare/certs/cloudflare-containers-ca.crt`. Not tested here (not verified end to end).
- Supabase key: the silo-mcp endpoint is public, read-only, "public anon key only" with
  `verify_jwt` off (repository `AGENTS.md`). The engine may need no Supabase secret at all.
  Confirm against `supabase/functions/silo-mcp/` in #519.

### 3.2 Can the Container reach `zcjbtpxuhdekpwcxmepn.supabase.co` and `api.anthropic.com`?

Yes, if internet access is on. The sources disagree on the default, so set it explicitly.

- `Container` class page: `enableInternet` "(`boolean`, default: `true`)"
  (<https://developers.cloudflare.com/containers/api/container-class/>, docs search).
- Outbound traffic page: "By default, a Container will allow internet access, and you can set `deniedHosts` to disallow specific hosts or IPs"
  (<https://developers.cloudflare.com/containers/configuration/outbound-traffic/>, docs search).
- Sandbox security page: "A Container starts with `enableInternet: false` by default, so it cannot reach the Internet."
  (<https://developers.cloudflare.com/sandbox/concepts/security/>, docs search.) The Sandbox 1.0
  migration table adds "`enableInternet` on `start()`, which every call must pass. 0.12 defaulted to true."
  (<https://developers.cloudflare.com/sandbox/sdk/migrate/replace-the-sandbox-class/>, docs search.)
  The raw Durable Object Container API default was not captured. The build must set the flag.
- Allow-listing the two hosts: `enableInternet = false` plus `allowedHosts = ["..."]`. When set,
  > "any host or IP not in the list is denied."
  > "`deniedHosts` applies to HTTP on port `80`. With `interceptHttps = true`, it also applies to HTTPS on port `443`."

  Whether `allowedHosts` filters HTTPS without interception is not stated (not verified).
  With `enableInternet = false` "Only ports `80` and `443` are available."
- Privacy value of an allow-list: the engine can then talk only to the two hosts, so a
  dependency cannot send an upload elsewhere. That is a recommendation, not a Cloudflare claim.

## 4. Cost per report

Sources: <https://developers.cloudflare.com/containers/platform/pricing/> (scrape, live,
last updated 2026-08-28), <https://developers.cloudflare.com/workers/platform/pricing/> and
<https://developers.cloudflare.com/durable-objects/platform/pricing/> (docs search).

### 4.1 Rates and allowances

> "Containers are billed for every 10ms that they are actively running at the following rates, with included monthly usage as part of the $5 USD per month Workers Paid plan"

| Resource                         | Included per month (Workers Paid) | Beyond included           |
| -------------------------------- | --------------------------------- | ------------------------- |
| Memory                           | 25 GiB-hours                      | $0.0000025 per GiB-second |
| CPU                              | 375 vCPU-minutes                  | $0.000020 per vCPU-second |
| Disk                             | 200 GB-hours                      | $0.00000007 per GB-second |
| Egress, North America and Europe | 1 TB                              | $0.025 per GB             |

> "Memory and disk usage are based on the provisioned resources for the instance type you select, while CPU usage is based on active usage only."
The pricing page gives N/A for memory, CPU and disk on the Free plan, and the Containers overview says "Available on Workers Paid plan".

Other lines on the same bill:

- Workers (Standard): 10 million requests and 30 million CPU ms included, then $0.30 per million
  requests and $0.02 per million CPU ms.
- Durable Objects: 1 million requests per month included, then $0.15 per million. Duration 400,000
  GB-s per month, then $12.50 per million GB-s, billed on wall-clock time "while the Durable Object
  is actively running or is idle in memory but unable to hibernate". Their worked examples count
  128 MB per object. At 128 MB, 60 seconds is 7.5 GB-s, so the allowance covers about 53,000 such
  reports. Whether the object stays billed through the container's idle window was not verified.
- Workers Logs: 20 million log events included then $0.60 per million, 7 days retention, until
  2026-12-01, then Cloudflare Observability pricing (50 GB ingestion and 12 GB-month included in
  its worked example, <https://developers.cloudflare.com/observability/pricing/>).
- The plan: "$5 USD per month" (Workers Paid).
- Not on the pricing page and so not priced here: LLM provider cost, domain, any Browser Run use.

### 4.2 Worked example: one 60-second run, small instance

Assumptions, stated so the numbers can be redone: the run is 60 seconds of wall time. CPU is billed
only when active, so the table shows two bounds: busy for all 60 seconds, and busy 30 percent of the
time (waiting on the two LLM calls is idle CPU). Memory and disk bill for the whole time the
instance is running, which includes the idle window before it sleeps. Before any allowance.

`basic` (0.25 vCPU, 1 GiB, 4 GB), 60 s run plus 60 s idle, CPU busy the whole run:

- Memory: 1 GiB x 120 s = 120 GiB-s x $0.0000025 = $0.000300
- CPU: 0.25 vCPU x 60 s = 15 vCPU-s x $0.000020 = $0.000300
- Disk: 4 GB x 120 s = 480 GB-s x $0.00000007 = $0.0000336
- Total about **$0.00063 per report**.

| Instance                           | Idle window after the 60 s run                       | GiB-s | vCPU-s (busy 100 %) | Cost, CPU busy 100 % | Cost, CPU busy 30 % |
| ---------------------------------- | ---------------------------------------------------- | ----- | ------------------- | -------------------- | ------------------- |
| basic                              | none (lower bound, "shortly" is not defined)         | 60    | 15                  | $0.00047             | $0.00026            |
| basic                              | 60 s                                                 | 120   | 15                  | $0.00063             | $0.00042            |
| basic                              | 600 s (`Container` class default `sleepAfter` "10m") | 660   | 15                  | $0.00214             | $0.00193            |
| standard-1 (0.5 vCPU, 4 GiB, 8 GB) | none                                                 | 240   | 30                  | $0.00123             | $0.00081            |
| standard-1                         | 60 s                                                 | 480   | 30                  | $0.00187             | $0.00145            |
| standard-1                         | 600 s                                                | 2,640 | 30                  | $0.00757             | $0.00715            |

The idle window dominates. The default 10-minute `sleepAfter` multiplies the memory and disk bill by 11.
A short timeout (the env-vars example uses 60 seconds) is the cost control.

### 4.3 Monthly cost, 60 s run, CPU busy 100 %, allowances applied

Workers and Durable Object request charges are inside the included 10 million and 1 million requests at
these volumes and are left out. Each row adds the $5 plan floor.

| Reports per month | basic, 60 s idle | basic, 600 s idle | standard-1, 60 s idle | standard-1, 600 s idle |
| ----------------- | ---------------- | ----------------- | --------------------- | ---------------------- |
| 100               | $5.00            | $5.00             | $5.00                 | $5.44                  |
| 1,000             | $5.08            | $6.56             | $6.14                 | $11.84                 |
| 10,000            | $10.61           | $25.62            | $22.95                | $79.97                 |

How far the allowance goes, 60 s run, whichever of memory or CPU runs out first:

- basic, no idle: 1,500 reports (90,000 GiB-s of memory divided by 60; CPU also 1,500).
- basic, 60 s idle: 750 reports (memory). basic, 600 s idle: about 136 (memory).
- standard-1, no idle: 375 (memory). 60 s idle: about 187. 600 s idle: about 34.

LLM provider cost is **excluded** from every number above. It is paid to the provider, not Cloudflare.

## 5. Alternative: Workers with Python Workers (Pyodide)

Limits that apply (<https://developers.cloudflare.com/workers/platform/limits/>, docs search): 128 MB
memory per isolate, 64 MiB Worker size (uncompressed), 1 second startup, 5 minutes CPU maximum.

Package support: "Python Workers support pure and PyEmscripten Python packages on PyPI. Additionally,
Python Workers support packages that are included in Pyodide."
(<https://developers.cloudflare.com/workers/languages/python/packages/>, docs search.)

Pyodide 314.0.7 built-in list (<https://pyodide.org/en/stable/usage/packages-in-pyodide.html>, scrape from
Firecrawl cache dated 2026-10-02 15:38 UTC) includes `lxml`, `Pillow`, `fonttools`, `cffi`, `pandas`,
`numpy`, `python-calamine`, `xlrd`, `httpx`, `openai` and `cryptography`. It does **not** list `pypdf`,
`pdfminer.six`, `pdfplumber`, `reportlab`, `weasyprint`, `pymupdf` or `openpyxl`. Its page says "Pure
Python packages with wheels on PyPI can be loaded directly from PyPI with `micropip.install()`".

What this means for the engine (reading of the lists, not a test):

- XLSX: `python-calamine` and `xlrd` are built in. Reading `.xlsx` through `python-calamine` looks possible.
  Not tested.
- PDF text: `pdftotext` and poppler are native binaries and cannot run in Pyodide. Pure-Python parsers
  (`pypdf`, `pdfminer.six`) could be loaded as pure wheels. Not tested, and accuracy on a given broker
  layout is unmeasured.
- PDF rendering: WeasyPrint needs native text-layout libraries and is not in the built-in list. Treat as
  not available (not verified by a build). Headless Chromium is not part of Workers. Cloudflare has a
  separate headless-browser product, Browser Run ("allows developers to programmatically control and
  interact with a headless browser instance", <https://developers.cloudflare.com/workers/wrangler/configuration/>,
  docs search). Its PDF output, limits, price and upload-privacy behaviour were not researched (not verified).
- Python Workers beta or GA status: the page says "You must add the `python_workers` compatibility flag".
  It does not label itself beta or GA in the text captured (not verified).

Conclusion for #519: Python Workers are a plausible fit for the parse step only. The Portuguese PDF
report needs a Container, or another renderer. One Container doing both steps is simpler.

## 6. Accounts and access the owner must set up

- **Account and plan.** A Cloudflare account on the **Workers Paid plan** ($5 per month). Containers:
  "Available on Workers Paid plan"
  (<https://developers.cloudflare.com/containers/>, scrape).
- **Wrangler login.** `wrangler login` is an interactive OAuth flow. "The wrangler login OAuth flow does not
  currently support granular authorization."
  (<https://developers.cloudflare.com/workers/authorization/>, scrape, live fetch, last updated 2026-09-15.)
  Fine for the first local deploy. CI needs a token.
- **API token for CI.**
  > "Since CI/CD environments are non-interactive, Wrangler requires a Cloudflare API token and account ID to authenticate with the Cloudflare API."

  Create an account-owned token. The guide says: under Permission policies pick "Edit Cloudflare Workers"
  and scope it to the one account
  (<https://developers.cloudflare.com/workers/ci-cd/external-cicd/github-actions/>, docs search, last
  updated 2026-09-18). Role table (Workers authorization page): deploying an existing Worker needs
  `Editor`. Creating a new Worker needs `Admin` at the Workers product scope (same table). Add "Account Secrets Store
  Edit" only if Secrets Store is used.
  **No Container-specific token permission is documented on any page read** (for example for the registry
  push that `wrangler deploy` performs). #519 should confirm with a deploy using the minimal token (not verified).
- **GitHub secrets.** `CLOUDFLARE_ACCOUNT_ID` and `CLOUDFLARE_API_TOKEN`, and the official action
  `cloudflare/wrangler-action@v4` running `wrangler deploy` (same GitHub Actions guide). Do not commit the token.
- **Docker at deploy time.**
  > "If `image` in your Wrangler config is a path to a Dockerfile, start Docker or another Docker-compatible engine."

  A registry image needs no Docker at deploy time. Alternative: Workers Builds, which can build Dockerfile
  images itself. Production branch default `npx wrangler deploy`
  (<https://developers.cloudflare.com/containers/guides/deploy/>, scrape from Firecrawl cache dated
  2026-10-01 13:26 UTC). Whether the GitHub-hosted runner image ships Docker was not checked in a Cloudflare
  page (not verified).
- **Preview URLs.** None for container Workers: "Version URLs are not generated for Workers that implement
  Durable Objects, which includes Containers Workers." Use a second Worker or a Wrangler environment for staging.
- **Account ID.** Found in the dashboard (Zone Overview page, API section, for the Pages guide) or "Find
  account and zone IDs".
- **Secrets.** `npx wrangler secret put ANTHROPIC_API_KEY` for the Worker. The LLM key itself comes from the
  provider's console, with a spend limit set there.
- **Custom domain.** "Unlike Pages, Workers does not support any domain whose nameservers are not managed by
  Cloudflare."
  (<https://developers.cloudflare.com/workers/static-assets/migration-guides/migrate-from-pages/>, docs
  search.) A `*.workers.dev` address works without a domain. A custom name on a domain that is not on
  Cloudflare DNS points toward Pages for the page.
- **Region.** Default is the location nearest the request. Constraints exist:
  regions ENAM, WNAM, EEUR, WEUR, APAC, SAM, ME, OC, AFR (ME, OC and AFR "cannot be used exclusively"), and
  jurisdictions `eu`, `us`, `fedramp`
  (<https://developers.cloudflare.com/containers/concepts/placement/>, docs search, last updated 2026-10-01).
  There is no Brazil-only option in the table. A Brazilian residency requirement would need a decision
  (SAM is the nearest region listed).

## 7. Status, region and plan restrictions

- **GA.** "Cloudflare Containers and Sandboxes are now generally available."
  (<https://developers.cloudflare.com/changelog/post/2026-04-13-containers-sandbox-ga/>, docs search,
  2026-04-13.) The change log description reads "Containers and Sandbox SDK are now generally available on
  the Workers Paid plan."
- **Still beta inside it.** The `durable_object` scheduling policy ("(beta)"), and container snapshots
  ("public beta", 2026-09-30 changelog). Neither is needed.
- **Plan.** Workers Paid only. Free: N/A.
- **Regions.** Section 6. Capacity in ME, OC and AFR is limited.
- **Account-level limits.** 1,500 concurrent vCPU, 6 TiB memory, 30 TB disk, 50 GB image storage. Higher on
  request.

## 8. Design findings (reported, not decided)

- **Pages cannot host the Container.**
  > "You cannot create and deploy a Durable Object within a Pages project."

  A Pages Function can bind a Durable Object from a separate Worker and the binding needs `script_name`
  (<https://developers.cloudflare.com/pages/functions/bindings/> and
  <https://developers.cloudflare.com/pages/functions/wrangler-configuration/>, docs search). So whichever way
  the page is hosted, a separate Worker carries the Container.
- **Cloudflare recommends Workers over Pages for new projects.**
  > "Workers Static Assets is the recommended way to deploy static sites, single-page applications, and full-stack apps on Cloudflare. If you are starting a new project, use Workers instead of Pages. Pages continues to work, but new features and optimizations are focused on Workers."

  (<https://developers.cloudflare.com/workers/best-practices/workers-best-practices/>, docs search.) The upload
  page could therefore be static assets of the same Worker as the container, which removes cross-origin
  calls and one project. Both layouts remain possible: Pages plus Worker (CORS between them), or one Worker.
  The owner's decision to use Pages stands unless the owner changes it.
- **Isolation per upload.** One Durable Object name per request gives each upload its own microVM and disk.
  A shared name would let two users' uploads share a running container. Cost: a cold start per request.
- **Default sizes for the engine.** Memory use of WeasyPrint or Chromium was not measured. `basic` (1 GiB) is
  unproven for either, and Chromium is likely to need `standard-1` or more (not verified).

## 9. Not verified

1. Whether Workers Logs or invocation logs capture request bodies (the docs list metadata and headers only).
2. A Worker-to-container request body size limit.
3. Container start time for an image with poppler plus WeasyPrint or Chromium.
4. Whether `allowedHosts` filters HTTPS without `interceptHttps`.
5. The default of `enableInternet` for raw `ctx.container.start()` (sources conflict on classes).
6. Whether `ctx.container.start({env})` works under the `default` scheduling policy.
7. A Container-specific API token permission, and whether the minimal "Edit Cloudflare Workers" token can push
   images.
8. Whether the Durable Object is billed through the container's idle window.
9. Whether 1 GiB (`basic`) is enough for the engine.
10. Client-facing timeouts on a 60-second open request.
11. That Docker is present on GitHub-hosted runners (a GitHub fact, not read here).
12. Whether Pyodide can run `pypdf`, `pdfminer.six` or `python-calamine` on the owner's statements.
13. Python Workers beta or GA label. Browser Run's PDF features, limits and price.
14. Abuse control for a public upload page (rate limiting, spend caps). Not researched.
15. The provider's retention of the data sent for the two LLM steps.

## 10. Checklist: what the owner must provide for #519

- [ ] Cloudflare account on the Workers Paid plan, with a payment method.
- [ ] Account ID.
- [ ] Decision: Pages for the page plus a separate Worker, or one Worker serving the page as static assets.
- [ ] API token for CI: account-owned, "Edit Cloudflare Workers" on this account only. Admin on the Workers
      product if the deploy creates the Worker. "Account Secrets Store Edit" only if Secrets Store is used.
      #519 confirms the minimum with a real deploy.
- [ ] GitHub repository secrets `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID`.
- [ ] Decision: deploy from GitHub Actions (Docker on the runner) or Workers Builds (Dockerfile built by
      Cloudflare), or `wrangler deploy` locally with Docker.
- [ ] Anthropic (or other LLM) API key with a provider-side spend limit, stored with
      `wrangler secret put`. Never committed, never sent to the browser.
- [ ] Decision: key held by the container (`env` at start) or injected by an outbound handler.
- [ ] Decision: custom domain or `*.workers.dev`. A custom domain on a non-Cloudflare DNS zone points to Pages.
- [ ] Decision: region or jurisdiction constraint, if any.
- [ ] Decision: sleep timeout (60 s suggested by the cost table) and `max_instances`.
- [ ] Privacy settings for #519 to implement and test: `invocation_logs: false` (or an explicit decision to
      keep them), no upload content on stdout or stderr, no use of `ctx.storage`, no KV, R2 or D1 binding,
      no document names or identifiers in the URL or query string, stream the body through the Worker,
      single-use Durable Object name per upload, and a marked-upload test that searches Workers Logs.
- [ ] Egress set explicitly: `enableInternet = false` with an allow-list of
      `zcjbtpxuhdekpwcxmepn.supabase.co` and `api.anthropic.com`, or `true` by decision.
- [ ] Decision on abuse limits for the public page (not researched here).

## Sources

All read 2026-10-02, between about 23:00 and 23:30 UTC-3 (2026-10-03, 02:00 to 02:30 UTC).

| Page                                                                                                                                    | How fetched                                                                    |
| --------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| <https://developers.cloudflare.com/containers/>                                                                                         | Scrape, live                                                                   |
| <https://developers.cloudflare.com/containers/platform/limits/>                                                                         | Scrape, live (requested as `/containers/platform-details/limits/`, redirected) |
| <https://developers.cloudflare.com/containers/platform/pricing/>                                                                        | Scrape, live (requested as `/containers/pricing/`, redirected)                 |
| <https://developers.cloudflare.com/containers/concepts/architecture/>                                                                   | Scrape, live                                                                   |
| <https://developers.cloudflare.com/containers/faq/>                                                                                     | Scrape, live                                                                   |
| <https://developers.cloudflare.com/containers/examples/env-vars-and-secrets/>                                                           | Scrape, live                                                                   |
| <https://developers.cloudflare.com/containers/configuration/environment-variables/>                                                     | Scrape, live                                                                   |
| <https://developers.cloudflare.com/containers/configuration/scheduling-policy/>                                                         | Scrape, Firecrawl cache of 2026-10-02 21:25 UTC                                |
| <https://developers.cloudflare.com/containers/guides/deploy/>                                                                           | Scrape, Firecrawl cache of 2026-10-01 13:26 UTC                                |
| <https://developers.cloudflare.com/containers/llms.txt>                                                                                 | Scrape, Firecrawl cache of 2026-10-01 16:57 UTC                                |
| <https://developers.cloudflare.com/workers/authorization/>                                                                              | Scrape, live                                                                   |
| <https://pyodide.org/en/stable/usage/packages-in-pyodide.html>                                                                          | Scrape, Firecrawl cache of 2026-10-02 15:38 UTC                                |
| Containers outbound traffic, Container class, Durable Object Container, API overview, get-started, placement, image management          | Cloudflare docs search                                                         |
| Workers limits, Workers pricing, Workers Logs, Durable Objects pricing, Observability pricing                                           | Cloudflare docs search                                                         |
| Python Workers packages, Workers best practices, Pages limits, Pages bindings, Pages wrangler configuration, Pages to Workers migration | Cloudflare docs search                                                         |
| GitHub Actions deploy guide, Secrets Store access control and manage secrets, Sandbox network and security pages                        | Cloudflare docs search                                                         |
| Containers GA changelog 2026-04-13, regional placement changelog 2026-04-05, trace events changelog 2025-04-07                          | Cloudflare docs search                                                         |

Direct `curl` to developers.cloudflare.com was blocked by the environment's egress proxy, and Context7 was
over its monthly quota, so neither was used.
