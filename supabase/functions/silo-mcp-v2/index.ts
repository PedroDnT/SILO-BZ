// silo-mcp-v2: a read-only remote MCP server over the silo-api v2 gateway.
// Entry point only; the wiring is server.ts and the behaviour is tools.ts.
// Would serve at https://<project-ref>.supabase.co/functions/v1/silo-mcp-v2.
// Not deployed: a merge deploys no Edge Function, and a deploy needs the owner.

import "@supabase/functions-js/edge-runtime.d.ts";
import { makeHandler } from "./server.ts";

Deno.serve(makeHandler());
