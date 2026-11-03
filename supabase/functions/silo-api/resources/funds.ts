// silo-api resource `funds`: what is this fund and how is it doing?
//
// id is a fund CNPJ (punctuation stripped, 14 digits or bad_request). kind
// profile -> api.fund_profile, and with no id the api.funds registry view (a
// GET, refused when the selection holds more than one page unless limit asks
// for the first N); nav -> api.fund_nav (family -> p_entity_type); holdings
// -> api.fund_holdings and debentures -> api.fund_debentures, where the hidden
// holding is the reverse lookup (p_ticker / p_issuer) and exactly one of id
// and holding is required; properties -> api.fii_property_history. Default
// window: 3 years back from `to` (or today, UTC-3).

import type { Envelope } from "../envelope.ts";
import { normalizeCnpjId, type ParsedRequest } from "../params.ts";
import type { CallContext } from "../postgrest.ts";
import { RESOURCES_BY_NAME } from "../registry.ts";
import { runKind } from "./run.ts";

const FUNDS = RESOURCES_BY_NAME.get("funds")!;

export function funds(req: ParsedRequest, ctx: CallContext): Promise<Envelope> {
  return runKind(FUNDS, req, ctx, (kind, _plan, values) => normalizeCnpjId(FUNDS, kind, values));
}
