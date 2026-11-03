// silo-api resource `events`: what was filed or restated?
//
// kind company -> api.company_events (id: ticker, CNPJ or CVM code, required),
// fund -> api.fund_documents, restatements -> api.fund_restatements (no id:
// every fund's; hidden family -> p_tipo_fundo), restatement_diff ->
// api.fund_restatement_diff, judicial_recovery -> api.rj_listed_documents (no
// id: every company's). category is the source's own label (p_category,
// p_tipo or p_doc_type). The fund kinds take a fund CNPJ as id. Default
// window: 12 months back from `to` (or today, UTC-3).

import type { Envelope } from "../envelope.ts";
import { normalizeCnpjId, type ParsedRequest } from "../params.ts";
import type { CallContext } from "../postgrest.ts";
import { RESOURCES_BY_NAME } from "../registry.ts";
import { runKind } from "./run.ts";

const EVENTS = RESOURCES_BY_NAME.get("events")!;
const FUND_KINDS = new Set(["fund", "restatements", "restatement_diff"]);

export function events(req: ParsedRequest, ctx: CallContext): Promise<Envelope> {
  return runKind(EVENTS, req, ctx, (kind, _plan, values) => (FUND_KINDS.has(kind) ? normalizeCnpjId(EVENTS, kind, values) : values));
}
