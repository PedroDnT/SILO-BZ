-- D1b Does the factor convention tighten when the two prints are adjacent?
--
-- WHY THIS EXISTS. Diagnostic 09 measured the two candidate conventions across
-- every event with a print on both sides of the entitlement date, and returned
-- a result that is suggestive but not shippable:
--
--     label          events  median vs 1+f/100   within +-5%
--     DESDOBRAMENTO     424             0.9963         76.4%
--     BONIFICACAO        80             0.9979         82.5%
--
-- A median 0.37% from a perfect fit is not a coincidence — that IS the
-- convention. But 76% of events landing inside +-5% is not enough to rescale
-- every historical price on, and the gap between "the median is exact" and
-- "a quarter of events miss by more than 5%" needs an explanation before any
-- adjustment ships.
--
-- THE HYPOTHESIS THIS TESTS. vw_b3_share_count_event takes the LAST print on or
-- before the entitlement date and the FIRST print after it. For a liquid name
-- those are consecutive sessions and the ratio is almost pure corporate action.
-- For an illiquid one the "after" print can be days or weeks later, and every
-- session in between contributes real price movement that has nothing to do
-- with the split. If that is the whole story, the hit rate should climb sharply
-- as the gap narrows, and be near-total at a one-session gap.
--
-- If it does climb, the convention is verified and close_adj can ship for the
-- labels that verify. If the hit rate is flat across gap buckets, the
-- dispersion is something else — a per-issuer or per-era convention difference,
-- or bad factors — and no adjustment should ship on this evidence.
--
-- Either way this is a measurement, not an adjustment: nothing here writes.
WITH ev AS (
    SELECT
        e.label,
        e.factor,
        e.last_date_prior,
        (SELECT b.trade_date
           FROM public.b3_cotahist b
          WHERE b.isin = e.isin AND b.tpmerc = '010'
            AND b.trade_date <= e.last_date_prior
          ORDER BY b.trade_date DESC, b.codbdi
          LIMIT 1)                                       AS d_before,
        (SELECT b.trade_date
           FROM public.b3_cotahist b
          WHERE b.isin = e.isin AND b.tpmerc = '010'
            AND b.trade_date > e.last_date_prior
          ORDER BY b.trade_date, b.codbdi
          LIMIT 1)                                       AS d_after,
        (SELECT b.preco_fechamento / NULLIF(b.fator_cotacao, 0)
           FROM public.b3_cotahist b
          WHERE b.isin = e.isin AND b.tpmerc = '010'
            AND b.trade_date <= e.last_date_prior
          ORDER BY b.trade_date DESC, b.codbdi
          LIMIT 1)                                       AS p_before,
        (SELECT b.preco_fechamento / NULLIF(b.fator_cotacao, 0)
           FROM public.b3_cotahist b
          WHERE b.isin = e.isin AND b.tpmerc = '010'
            AND b.trade_date > e.last_date_prior
          ORDER BY b.trade_date, b.codbdi
          LIMIT 1)                                       AS p_after
      FROM public.b3_corporate_event e
     WHERE e.event_class = 'stock'
       AND e.factor IS NOT NULL AND e.factor > 0
), scored AS (
    SELECT
        label,
        -- Calendar days between the two prints. Not trading sessions: a
        -- calendar gap of 1-4 days spans a normal weekend, so the buckets below
        -- are drawn to keep "consecutive sessions" in the first bucket.
        (d_after - d_before)                             AS gap_days,
        p_before / NULLIF(p_after, 0)                    AS price_ratio,
        (p_before / NULLIF(p_after, 0)) / factor         AS vs_direct,
        (p_before / NULLIF(p_after, 0))
            / NULLIF(1 + factor / 100.0, 0)              AS vs_percent
      FROM ev
     WHERE p_before IS NOT NULL AND p_after IS NOT NULL AND p_after > 0
       AND d_before IS NOT NULL AND d_after IS NOT NULL
)
SELECT
    label,
    CASE
        WHEN gap_days <= 4  THEN '1 consecutive sessions'
        WHEN gap_days <= 10 THEN '2 within 10 days'
        WHEN gap_days <= 40 THEN '3 within 40 days'
        ELSE                     '4 over 40 days'
    END                                                          AS gap_bucket,
    count(*)                                                     AS events,
    round(percentile_cont(0.5) WITHIN GROUP (ORDER BY vs_percent)::numeric, 4)
                                                                 AS median_vs_percent,
    round(100.0 * avg((abs(vs_percent - 1) <= 0.05)::int), 1)    AS pct_within_5_percent,
    round(percentile_cont(0.5) WITHIN GROUP (ORDER BY vs_direct)::numeric, 4)
                                                                 AS median_vs_direct,
    round(100.0 * avg((abs(vs_direct  - 1) <= 0.05)::int), 1)    AS pct_within_5_direct
  FROM scored
 GROUP BY label, 2
 ORDER BY label, 2;
