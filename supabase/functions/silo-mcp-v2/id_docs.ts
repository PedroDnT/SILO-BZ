// silo-mcp-v2: what `id` means on each resource, by the endpoint argument it fills.
//
// The registry's shared `id` doc is one sentence for all 14 resources; what a
// resource really takes depends on the kind (a ticker, a fund CNPJ, an option
// prefix, a list). This file holds one phrase per (endpoint, argument) that a
// kind maps `id` to, and idDoc() composes a resource's id description from the
// registry's own kinds, args, require_one_of and when_empty.
//
// The object between the BEGIN and END markers is STRICT JSON: the OpenAPI
// generator (scripts/gen_openapi_v2.py) parses it and renders the same text,
// and tests/test_mcp_v2.py pins it to the registry (every id mapping has a
// phrase, no phrase is stale, and a kind whose id the gateway normalises as a
// fund CNPJ says so). The Deno test checks this text equals the OpenAPI one.

import type { Plan, ResourceSpec } from "../silo-api/registry.ts";

// BEGIN ID_DOCS
export const ID_DOCS: Record<string, string> = {
  "quote_history.p_ticker": "a B3 ticker (PETR4)",
  "quote_latest.p_ticker": "a B3 ticker (PETR4)",
  "quotes.ticker": "a B3 ticker (none: every ticker of the session)",
  "index_history.p_index": "a B3 index code (IBOV, IFIX, ...)",
  "trade_consolidated_history.p_ticker": "a B3 FORWARD-segment ticker",
  "financials.p_id": "a listed company's ticker, 14-digit CNPJ or CVM code",
  "income_statements.p_id": "a listed company's ticker, 14-digit CNPJ or CVM code",
  "balance_sheets.p_id": "a listed company's ticker, 14-digit CNPJ or CVM code",
  "cash_flow_statements.p_id": "a listed company's ticker, 14-digit CNPJ or CVM code",
  "company_financials.p_id": "a listed company's ticker, 14-digit CNPJ or CVM code",
  "financial_statement_history.p_id": "a listed company's ticker, 14-digit CNPJ or CVM code",
  "fund_profile.p_cnpj": "a 14-digit fund CNPJ (punctuation allowed)",
  "fund_nav.p_cnpj": "a 14-digit fund CNPJ (punctuation allowed)",
  "fund_holdings.p_cnpj": "a 14-digit fund CNPJ (punctuation allowed)",
  "fund_debentures.p_cnpj": "a 14-digit fund CNPJ (punctuation allowed)",
  "fii_property_history.p_cnpj": "a 14-digit fund CNPJ (punctuation allowed)",
  "fidc_portfolio.p_cnpj": "a FIDC's 14-digit fund CNPJ (punctuation allowed)",
  "fidc_tranches.p_cnpj": "a FIDC's 14-digit fund CNPJ (punctuation allowed)",
  "fidc_aging.p_cnpj": "a FIDC's 14-digit fund CNPJ (punctuation allowed)",
  "fidc_cedentes.p_cnpj": "a FIDC's 14-digit fund CNPJ (punctuation allowed)",
  "fidc_sacados.p_cnpj": "a FIDC's 14-digit fund CNPJ (punctuation allowed)",
  "option_chain.p_prefix": "an option prefix, at least 3 characters (PETR)",
  "option_history.p_codneg": "one option code (codneg)",
  "option_exercises.p_prefix": "an option prefix, at least 3 characters (PETR)",
  "termo_history.p_codneg": "one termo code (codneg)",
  "future_series.p_ticker": "one outright futures contract (DI1F27, DOLF27)",
  "future_curve.p_root": "a futures root, DI1, DOL or WDO (none: DI1)",
  "di_settlement.ticker": "one DI1 contract (none: every contract)",
  "macro_series.p_series": "an SGS series label or code (SELIC_META, CDI, IGPM, 432)",
  "inflation.p_series": "one series label (IPCA, IPCA_CORE_EX0, ...; none: every series)",
  "inflation_items.p_item": "an IBGE structure number or SIDRA item code (none: the groups)",
  "focus_expectations.p_indicator": "a Focus indicator (IPCA, Selic, ...; none: every indicator)",
  "short_interest.ticker": "a B3 ticker (none: every ticker)",
  "lending_trades.ticker": "a B3 ticker",
  "lending_participants.ticker": "a B3 ticker",
  "company_events.p_id": "a listed company's ticker, 14-digit CNPJ or CVM code",
  "fund_documents.p_cnpj": "a 14-digit fund CNPJ (punctuation allowed)",
  "fund_restatements.p_cnpj": "a 14-digit fund CNPJ (punctuation allowed; none: every fund's)",
  "fund_restatement_diff.p_cnpj": "a 14-digit fund CNPJ (punctuation allowed)",
  "rj_listed_documents.p_id": "a listed company's ticker, 14-digit CNPJ or CVM code (none: every company's)",
  "panel.p_ids": "a comma-separated list of tickers, fund CNPJs, option or termo tickers and futures codes, up to the tier's id ceiling"
};
// END ID_DOCS

/** The ID_DOCS key of a plan's id mapping, or null when the plan takes no id. */
export function idKey(plan: Plan): string | null {
  const arg = plan.args?.id;
  return arg ? `${plan.endpoint}.${arg}` : null;
}

function kinds(names: string[]): string {
  return `${names.length > 1 ? "kinds" : "kind"} ${names.join(", ")}`;
}

/**
 * A resource's id description, from the registry: what each kind takes, which
 * kinds need it, what a kind does with none, and which kinds take none.
 * null when the resource takes no id. Throws on a mapping with no phrase.
 */
export function idDoc(r: ResourceSpec): string | null {
  if (!(r.shared ?? []).includes("id")) return null;
  const entries = Object.entries(r.kinds ?? {});
  const single = entries.length === 1;
  const byPhrase = new Map<string, string[]>();
  const required: string[] = [];
  const either: string[] = [];
  const empty = new Map<string, string[]>();
  const none: string[] = [];
  for (const [name, kind] of entries) {
    const key = idKey(kind);
    if (!key) {
      none.push(name);
      continue;
    }
    const phrase = ID_DOCS[key];
    if (!phrase) throw new Error(`silo-mcp-v2: no ID_DOCS phrase for ${r.name} kind ${name} (${key})`);
    byPhrase.set(phrase, [...(byPhrase.get(phrase) ?? []), name]);
    const req = kind.require_one_of ?? [];
    if (req.length === 1 && req[0] === "id") required.push(name);
    else if (req.includes("id")) either.push(`${name}: id or ${req.filter((x) => x !== "id").join(" or ")} is required`);
    if (kind.when_empty?.parameter === "id") {
      const ep = `api.${kind.when_empty.plan.endpoint}`;
      empty.set(ep, [...(empty.get(ep) ?? []), name]);
    }
  }
  const parts: string[] = [];
  const verb = (names: string[], one: string, many: string) => (names.length > 1 ? many : one);
  const what = [...byPhrase].map(([phrase, names]) => `${names.join(", ")} ${verb(names, "takes", "take")} ${phrase}`);
  parts.push(single ? `The id is ${[...byPhrase.keys()].join("; ")}.` : `By kind: ${what.join("; ")}.`);
  if (required.length) parts.push(`Required for ${kinds(required)}.`);
  for (const e of either) parts.push(`Kind ${e}.`);
  for (const [ep, names] of empty) parts.push(`With no id, ${kinds(names)} ${verb(names, "reads", "read")} ${ep} (what SILO holds).`);
  if (none.length) parts.push(`${kinds(none).replace(/^k/, "K")} ${verb(none, "takes", "take")} no id.`);
  return parts.join(" ");
}
