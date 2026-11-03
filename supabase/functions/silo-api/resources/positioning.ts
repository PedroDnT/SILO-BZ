// silo-api resource `positioning`: who is short, lending or flowing in?
//
// Every kind is one GET (callView) on a view, newest first, from and to as a
// range on its date column: short_interest -> api.short_interest,
// short_by_sector -> api.short_interest_by_sector, lending ->
// api.lending_trades, lending_brokers -> api.lending_participants,
// investor_flow -> api.investor_flow. A selection over one page is refused
// (over_limit) unless limit asks for the newest N (run.ts). Default window:
// 3 months back from `to` (or today, UTC-3). Tickers are sent upper case.
//
// Read docs/agents/dataset-notes.md, "B3 BDI ratchet": the short-interest
// fact reads only B3's own Total rows (is_total), and a lending broker
// (doador / tomador) is a brokerage, not a beneficial owner. ?help says both.

import type { Envelope } from "../envelope.ts";
import type { ParsedRequest } from "../params.ts";
import type { CallContext } from "../postgrest.ts";
import { RESOURCES_BY_NAME } from "../registry.ts";
import { runKind } from "./run.ts";

const POSITIONING = RESOURCES_BY_NAME.get("positioning")!;

export function positioning(req: ParsedRequest, ctx: CallContext): Promise<Envelope> {
  return runKind(POSITIONING, req, ctx, (_kind, _plan, values) =>
    typeof values.id === "string" ? { ...values, id: values.id.toUpperCase() } : values
  );
}
