// silo-api resource `search`: what is this name or id?
//
// kind any / company -> api.lookup (at most 20 rows; `truncated` says when
// more matched), kind fund -> api.search_funds (refuses above the tier
// ceiling: over_limit), kind universe -> api.research_universe. An empty q
// lists the research universe (with no id, a resource lists what it holds);
// as_of then reads it at a date, dead names included. search takes no id, so
// meta.id_known is null.

import type { Envelope } from "../envelope.ts";
import type { ParsedRequest } from "../params.ts";
import type { CallContext } from "../postgrest.ts";
import { RESOURCES_BY_NAME } from "../registry.ts";
import { runKind } from "./run.ts";

const SEARCH = RESOURCES_BY_NAME.get("search")!;

export function search(req: ParsedRequest, ctx: CallContext): Promise<Envelope> {
  return runKind(SEARCH, req, ctx);
}
