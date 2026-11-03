// silo-api resource `coverage`: how fresh is it and what exists?
//
// kind freshness -> api.coverage(), with the source's `as_of` returned as
// `data_through` (in v2, `as_of` is reserved for point-in-time reads); kind
// metrics -> api.metric_coverage(); kind catalog -> api.catalog(), one JSON
// object as data[0]. `dataset` narrows freshness by dataset name and metrics
// by fund family; a name no row carries is refused with the known names.

import type { Envelope } from "../envelope.ts";
import type { ParsedRequest } from "../params.ts";
import type { CallContext } from "../postgrest.ts";
import { RESOURCES_BY_NAME } from "../registry.ts";
import { runKind } from "./run.ts";

const COVERAGE = RESOURCES_BY_NAME.get("coverage")!;

export function coverage(req: ParsedRequest, ctx: CallContext): Promise<Envelope> {
  return runKind(COVERAGE, req, ctx);
}
