// silo-mcp — a read-only remote MCP server over SILO's schema `api`.
// Entry point only; the wiring is server.ts and the behaviour is tools.ts.
// Deployed at https://<project-ref>.supabase.co/functions/v1/silo-mcp.

import "@supabase/functions-js/edge-runtime.d.ts";
import { makeHandler } from "./server.ts";

Deno.serve(makeHandler());
