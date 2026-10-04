# Total-return prices

SILO provides three price fields on `quote_history`:

| Field                | What it is                                                          |
| -------------------- | ------------------------------------------------------------------- |
| `close`              | Raw COTAHIST close — unadjusted for anything                        |
| `close_adj`          | Adjusted for corporate events (splits, bonus shares) only           |
| `close_total_return` | `close_adj` with cash distributions reinvested at the ex-date close |

Select them via `p_fields`:

```bash
POST /rpc/quote_history
{
  "p_ticker": "PETR4",
  "p_from": "2019-01-02",
  "p_to": "2024-12-31",
  "p_fields": ["date", "close", "close_adj", "close_total_return"]
}
```

## `close_adj`: corporate-event adjustment

Anchored to the instrument's latest session. Splits and bonus shares are applied so that the historical close is comparable to today's share count. B3's published corporate-event history drives the adjustment — nothing is derived from price moves.

`close_adj` refuses for sessions where the adjustment factor cannot be computed (e.g., a session before a corporate event whose ISIN cannot be resolved). When it refuses, it returns `22023` naming the session.

## `close_total_return`: cash distributions reinvested

The level is `close_adj` divided by the product of `(1 + cash / ex-session close)` over every distribution that went ex after the session. The latest session equals `close_adj`. An earlier session is lower by every cash payment made since.

Cash distributions included: dividends (`DIVIDENDO`), interest on equity (`JRS CAP PROPRIO`, gross of withholding), yields (`RENDIMENTO`), and capital reductions (`REST CAP DIN`). B3's full published history drives this — SILO does not compute distributions from price moves.

### When it is NULL

`close_total_return` is NULL for a session when any of these apply (the reason is in `close_total_return_null_reason`):

- `close_adj` cannot be computed for the session (same causes)
- The ISIN has no resolved distribution in B3's history — either a non-payer, or an ISIN whose issuer B3 does not match to the tape (188 of 639 universe ISINs on 2026-09-30)
- A later distribution of this share class has no proven ISIN (731 events, 53 issuers, hitting 101 of 639 tickers — none of the large caps)
- A distribution B3's supplement lists is missing from the history
- A distribution has no ex-date close within 7 calendar days

The ex-date rule: SILO looks for the first printed session after the last cum session, within 7 calendar days. A paper that does not print within a week has no price to reinvest at.

### What to do with NULLs

In a cross-sectional study, NULLs will appear for some tickers on some sessions. The safest approach is to treat a NULL `close_total_return` as unavailable for that instrument for the affected period, rather than falling back to `close_adj` and silently mixing two different return series. The `close_total_return_null_reason` column tells you whether the NULL is structural (non-payer) or a data gap.

## Practical guidance

- **Price return only:** use `close_adj`. It is never NULL for a session that has a valid close.
- **Total return for a payer:** use `close_total_return`, check for NULLs.
- **Cross-sectional total return:** filter to `cnpj_basis IS NOT NULL AND close_total_return IS NOT NULL` before ranking — the NULL pattern is not random.
- **Never use `close` for returns across a corporate event.** It is unadjusted — PETR4 had a 1:10 reverse split in 2022.
