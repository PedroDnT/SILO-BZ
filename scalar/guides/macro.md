# Macro and inflation

SILO serves four macro data sources: BACEN SGS time series, IPCA via IBGE SIDRA, PTAX, and Focus (market expectations).

## BACEN macro series

`macro_series()` serves the non-inflation BACEN SGS codes registered in `api.macro_registry()`.

```bash
POST /rpc/macro_series
{
  "p_code": 4189,
  "p_from": "2020-01-01",
  "p_to": "2024-12-31"
}
```

`p_code` is the SGS series code. To see all available codes:

```bash
POST /rpc/macro_registry
{}
```

IPCA codes are explicitly refused here — use `inflation()` for those. The refusal message says so.

Common codes used in research:

| Code | Series                     |
| ---- | -------------------------- |
| 4189 | CDI daily rate             |
| 4390 | Selic overnight rate       |
| 7326 | Credit — total outstanding |
| 1    | Savings rate               |

## IPCA inflation

`inflation()` returns IPCA group-level data with IBGE SIDRA weights.

```bash
POST /rpc/inflation
{
  "p_from": "2023-01-01",
  "p_to": "2024-12-31"
}
```

Each row: `reference_date`, `group_code`, `group_name`, `monthly_change`, `weight`.

The eight IPCA groups follow IBGE's order, not BACEN's. BACEN's SGS codes 1640–1643 map to Comunicação / Saúde / Despesas pessoais / Educação — a different order. Never reorder by intuition; use the `group_code` from this endpoint.

`inflation_items()` returns the full item-level breakdown with weights — 377 items. Use it when you need subgroup analysis.

## PTAX

`ptax()` returns Banco Central's PTAX closing rate. One row per business day, in BRL/USD.

```bash
POST /rpc/ptax
{
  "p_from": "2024-01-02",
  "p_to": "2024-12-31"
}
```

The ingest keeps the last PTAX bulletin Olinda returns per day. For a completed day this is the Fechamento PTAX. The bulletin type is not stored — if you need intraday bulletins, query Olinda directly.

## Focus market expectations

`focus_expectations()` returns the weekly revision path for a single indicator and horizon.

```bash
POST /rpc/focus_expectations
{
  "p_endpoint": "ExpectativasMercadoAnuais",
  "p_horizon": "2025",
  "p_indicator": "IPCA",
  "p_from": "2024-01-01",
  "p_to": "2024-12-31"
}
```

Each row is a survey date. Successive rows form the revision path — how consensus moved over time for the same horizon. This is not a vintage archive of corrections to old survey dates; it is the path of current-week consensus as of each Monday.

The ingest refreshes the trailing 30 days of each active endpoint daily. Pre-migration-16 history may lack some horizons.

## Combining macro with equities

The standard pattern for a macro-driven factor model:

```python
import silo
import pandas as pd

client = silo.Client(api_key="...")

# Equity panel
prices = client.panel(
    ids=["PETR4", "VALE3", "ITUB4"],
    metrics=["close_adj"],
    start="2020-01-02",
    end="2024-12-31",
)

# CDI daily rate
cdi = client.macro_series(code=4189, start="2020-01-01", end="2024-12-31")

# Merge on date — macro is published with a lag, align accordingly
combined = prices.join(cdi.set_index("date")["value"], on="date")
```
