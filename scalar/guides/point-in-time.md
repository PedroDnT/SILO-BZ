# Point-in-time fundamentals

Every fundamental function accepts `p_as_of DATE` to read what was publicly known on a specific date. This is essential for backtesting: using `NULL` (the default) gives you today's most restated view of history, which is not what was available to a model running in real time.

## How it works

With `p_as_of = T`:

1. SILO filters `cia_filing` to documents CVM received before T (`dt_receb < T`)
2. Of the remaining versions, it keeps the highest `versao` for each `(company, doc_type, reference_period)`
3. Only those lines are returned

A document received on T itself is excluded. A document with no received date is always dropped.

## Example: PETR4 in a 2022 backtest

PETR's 2021 annual report (DFP) was filed on 2022-03-07. If you run a backtest with signals as of 2022-02-28, you should not see it — it had not been filed yet.

```bash
POST /rpc/income_statements
{
  "p_id": "PETR4",
  "p_from": "2021-01-01",
  "p_to": "2021-12-31",
  "p_as_of": "2022-02-28"
}
```

This returns the ITR filed for the quarter ended 2021-09-30 (received 2021-11-10) — the most recent filing CVM had received before 2022-02-28. The annual report filed on 2022-03-07 does not appear.

## NULL is not point-in-time

```bash
POST /rpc/income_statements
{
  "p_id": "PETR4",
  "p_from": "2021-01-01",
  "p_to": "2021-12-31"
}
```

This returns the latest version of each filing — including any restatements filed after the original period. Appropriate for current fundamental analysis; not appropriate for a backtest.

## Restatement tracking

`financial_statement_history()` returns every stored version of a filing, including the received date of each version:

```bash
POST /rpc/financial_statement_history
{
  "p_id": "PETR4",
  "p_statement": "DRE",
  "p_from": "2023-01-01",
  "p_to": "2023-12-31"
}
```

The `filing_received_date` column on each row shows when CVM received it. This is the same date the `p_as_of` filter uses.

## The recipe for a panel backtest

```python
import silo
from datetime import date

client = silo.Client(api_key="...")

# Rebalancing dates
rebal_dates = ["2021-06-30", "2021-12-31", "2022-06-30", "2022-12-31"]

for as_of in rebal_dates:
    # Universe at this date
    universe = client.research_universe(as_of=as_of)

    # Fundamentals known at this date
    for cnpj in universe["cnpj"].dropna():
        stmt = client.income_statements(
            p_id=cnpj,
            p_as_of=as_of,
            p_from=str(date.fromisoformat(as_of).replace(year=date.fromisoformat(as_of).year - 2)),
            p_to=as_of,
        )
        # process stmt...
```

## Covered functions

All five fundamental functions support `p_as_of`:

- `financials` — raw account lines from any statement
- `company_financials` — structured income statement with standard field names
- `income_statements` — revenue, EBIT, EBITDA, net income by label
- `balance_sheets` — assets, liabilities, equity
- `cash_flow_statements` — operating, investing, financing cash flows

The filter cost is about 450ms on six years of PETR's consolidated lines — within the anon 3s budget.
