"""What the daily run re-reads, in one place.

The pipeline (`cvm_pipeline`) plans its daily slices from these numbers, and
the two alarms that decide whether a failed slice is the daily run's to heal
read the same ones: `scripts/check_staleness.py` imports them, and
`.github/workflows/health.yml` restates them as env values that
`tests/test_health_workflow.py` pins to this module. Change a number here and
those tests fail until the workflow agrees.

No imports beyond the standard library, so anything can read it.
"""
from __future__ import annotations

# Monthly datasets: the trailing window `_monthly_targets` probes for gaps
# (env CVM_DAILY_LOOKBACK_MONTHS overrides it in the pipeline).
DAILY_LOOKBACK_MONTHS = 4

# The four CDA blocks are re-read for every month M until month M+5 ends
# (issue #551; env CVM_CDA_REFRESH_MONTHS overrides it in the pipeline).
CDA_DOC_TYPES = frozenset({"cda", "cda_acoes", "cda_cotas", "cda_debentures"})
CDA_REFRESH_MONTHS = 5

# FII yearly files: the previous year is re-read from January through this
# month, because December's reports land in last year's file early in the year.
FII_PREVIOUS_YEAR_THROUGH_MONTH = 3


def daily_window_sql(alias: str = "e") -> str:
    """SQL predicate: the cvm_ingest_log slice `alias` is one daily_update retries.

    Three %s parameters, in order: DAILY_LOOKBACK_MONTHS, CDA_REFRESH_MONTHS,
    FII_PREVIOUS_YEAR_THROUGH_MONTH. The health workflow carries the same
    predicate as its `DAILY_WINDOW` shell variable.
    """
    a = alias
    cda = ", ".join(f"'{d}'" for d in sorted(CDA_DOC_TYPES))
    return f"""(
       {a}.period_year IS NULL
    OR ({a}.period_month IS NULL
        AND {a}.period_year = EXTRACT(YEAR FROM CURRENT_DATE)::int)
    OR ({a}.period_month IS NOT NULL
        AND make_date({a}.period_year, {a}.period_month, 1)
            >= (date_trunc('month', CURRENT_DATE)
                - (%s::int - 1) * INTERVAL '1 month')::date)
    OR ({a}.entity = 'fi' AND {a}.doc_type IN ({cda})
        AND {a}.period_month IS NOT NULL
        AND make_date({a}.period_year, {a}.period_month, 1)
            >= (date_trunc('month', CURRENT_DATE)
                - %s::int * INTERVAL '1 month')::date)
    OR ({a}.entity = 'fii' AND {a}.period_month IS NULL
        AND {a}.period_year = EXTRACT(YEAR FROM CURRENT_DATE)::int - 1
        AND EXTRACT(MONTH FROM CURRENT_DATE)::int <= %s::int)
)"""


def daily_window_params() -> tuple:
    """The parameters `daily_window_sql` expects, in order."""
    return (DAILY_LOOKBACK_MONTHS, CDA_REFRESH_MONTHS, FII_PREVIOUS_YEAR_THROUGH_MONTH)
