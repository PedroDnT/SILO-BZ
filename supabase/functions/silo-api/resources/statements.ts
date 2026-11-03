// silo-api resource `statements`: what did the company file?
//
// kind all -> api.financials (every line, long), income / balance / cashflow ->
// api.income_statements / balance_sheets / cash_flow_statements, headline ->
// api.company_financials, versions -> api.financial_statement_history (hidden
// statement, default DRE). period maps to p_doc_type (quarterly itr, annual
// dfp); company_financials takes none, so there period selects on the rows'
// doc_type. scope maps to p_scope (con, ind). as_of is the point-in-time read.
// Rows pass through as filed: period_months stays on every row that has a span
// (a quarterly filing holds the 3-month and the year-to-date figure). With no
// id, every kind lists the research universe, whose cnpj links a ticker to its
// filer.

import type { Envelope } from "../envelope.ts";
import type { ParsedRequest } from "../params.ts";
import type { CallContext } from "../postgrest.ts";
import { RESOURCES_BY_NAME } from "../registry.ts";
import { runKind } from "./run.ts";

const STATEMENTS = RESOURCES_BY_NAME.get("statements")!;

export function statements(req: ParsedRequest, ctx: CallContext): Promise<Envelope> {
  return runKind(STATEMENTS, req, ctx);
}
