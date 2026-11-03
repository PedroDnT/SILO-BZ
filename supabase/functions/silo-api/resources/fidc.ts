// silo-api resource `fidc`: what is inside this FIDC?
//
// id is a FIDC CNPJ (punctuation stripped, 14 digits or bad_request). One kind
// per api.fidc_* function: portfolio (item -> p_kind), tranches (series ->
// p_series), aging, cedentes (the hidden cedente is the reverse lookup;
// exactly one of id and cedente), sacados. With no id, kind portfolio lists
// the FIDC registry (api.funds, entity_type fidc). Default window: 2 years.
// ?help carries the FIDC delinquency regime break (2020-11).

import type { Envelope } from "../envelope.ts";
import { normalizeCnpjId, type ParsedRequest } from "../params.ts";
import type { CallContext } from "../postgrest.ts";
import { RESOURCES_BY_NAME } from "../registry.ts";
import { runKind } from "./run.ts";

const FIDC = RESOURCES_BY_NAME.get("fidc")!;

export function fidc(req: ParsedRequest, ctx: CallContext): Promise<Envelope> {
  return runKind(FIDC, req, ctx, (kind, _plan, values) => normalizeCnpjId(FIDC, kind, values));
}
