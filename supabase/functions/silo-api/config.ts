// silo-api: the tier numbers, in one block (#1059; owner decision 2026-11-03, #1061).
//
// The owner changes a number here without touching logic. Nothing else in
// the gateway holds a tier number: params.ts, paging.ts, run.ts and the
// resource modules read TIERS.
//
// Tier detection, until #1064: no Bearer token (or the publishable key sent
// as one) is "anonymous"; any other Bearer is "signed_in", and PostgREST
// verifies it on the call (an invalid token is refused there as
// unauthorized). The gateway does not decode the JWT. "pro" is declared so
// its numbers live here, but no caller reaches it yet (#1064 adds it and the
// requests-per-minute limit, which nothing enforces today).

export type Tier = "anonymous" | "signed_in" | "pro";

export interface TierLimits {
  /** limit's default and its maximum: a larger limit is coerced to this (AIP-158). */
  page_max: number;
  /** Rows one call may serve across all its pages; null = unlimited. Then meta.tier_cap_reached. */
  rows_per_call: number | null;
  /** The widest from..to on a daily kind, in months; null = none. */
  daily_window_months: number | null;
  /** Ids per panel call. */
  panel_ids: number;
  /** screens and portfolio are served. */
  screens: boolean;
  portfolio: boolean;
  /** panel with no id (a whole family). */
  panel_universe: boolean;
  /** Not enforced yet: #1064. */
  requests_per_minute: number;
}

// BEGIN TIERS
export const TIERS: Record<Tier, TierLimits> = {
  anonymous: {
    page_max: 10,
    rows_per_call: 50,
    daily_window_months: 3,
    panel_ids: 1,
    screens: false,
    portfolio: false,
    panel_universe: false,
    requests_per_minute: 10,
  },
  signed_in: {
    page_max: 100,
    rows_per_call: 1000,
    daily_window_months: 24,
    panel_ids: 3,
    screens: true,
    portfolio: true,
    panel_universe: false,
    requests_per_minute: 30,
  },
  pro: {
    page_max: 1000,
    rows_per_call: null,
    daily_window_months: null,
    panel_ids: 50,
    screens: true,
    portfolio: true,
    panel_universe: true,
    requests_per_minute: 300,
  },
};
// END TIERS

/** How to get a higher tier, said wherever a tier limit is met. */
export const HIGHER_TIER: Record<Tier, string> = {
  anonymous: "Sign in (send Authorization: Bearer <your user JWT>) for the signed-in tier.",
  signed_in: "The pro tier (paid) lifts this; ask the owner.",
  pro: "",
};

/** One SQL page: PostgREST db-max-rows, and the page of every p_after function. */
export const SQL_PAGE = 1000;

/**
 * The most PostgREST requests one v2 request makes. A date-window walk halves
 * a refused window and skips empty ones; when this budget runs out the page
 * is served short, with next_page_url, never cut.
 */
export const MAX_UPSTREAM_CALLS = 12;
