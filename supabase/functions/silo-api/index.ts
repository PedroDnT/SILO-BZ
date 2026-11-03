// silo-api: the v2 gateway over SILO's schema `api` (docs/planning/API_V2.md).
// Entry point only; the wiring is server.ts and the resources are registry.ts.
// Would serve at https://<project-ref>.supabase.co/functions/v1/silo-api/v2/.
// Not deployed: a merge deploys no Edge Function, and a deploy needs the owner.

import "@supabase/functions-js/edge-runtime.d.ts";
import { makeHandler } from "./server.ts";

Deno.serve(makeHandler());
