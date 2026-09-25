# Research question specifications

Nine questions are answerable after their stated source and quality checks.
Three are explicit limits of the current data.

## Answerable questions

| ID | Question | Inputs and calculation | Caveat / acceptance check |
| --- | --- | --- | --- |
| Q1 | Which firms repeatedly convert operating earnings into cash? | Consolidated CVM DRE and DFC, joined by issuer, fiscal period, scope and filing version; derive quarter CFO from ITR cumulative values and compare with earnings. | Restrict differences to the same fiscal-year start and version; show levels where earnings are zero or negative. |
| Q2 | How sensitive is reported profitability to CVM account-chart differences? | Join `cia_account` rows to `cia_company` context and FCA issuer/ticker mapping; test statement-code coverage by chart and use account labels. | The documented 3.11 net-income code misses a bank-specific chart; do not treat a single code as universal. |
| Q3 | Do filing restatements change historical cash-conversion conclusions? | Recompute Q1 across preserved CVM filing versions. | Do not replace prior versions or select versions using future information in a backtest. |
| Q4 | Which FII property reports show the greatest disclosed vacancy area? | Join quarterly fund and property disclosures on fund/class CNPJ, reference date and version; multiply area by reported vacancy fraction. | This is reported property area, not independently measured physical occupancy; establish metric coverage before ranking funds. |
| Q5 | How concentrated are property income and reported delinquency within an FII? | Aggregate property-reported revenue share and delinquency by fund/date/version, with property-level contributions. | Do not infer the fund's total portfolio or cash collections from a single property row. |
| Q6 | How complete are the reported property-level operating metrics across FII filings? | Measure presence and null rates for area, vacancy, delinquency, rent and development fields by filing/date. | Distinguish missing disclosure from a reported zero; latest-version selection must be explicit. |
| Q7 | How do Focus median expectations for IPCA, Selic and GDP revise as the target horizon approaches? | BCB survey-date vintages grouped by indicator and target month/year; calculate changes between successive survey dates. | Keep forecast horizon and statistic type fixed; do not mix 30-day and smoothed products. |
| Q8 | How large are Focus median forecast errors at a fixed horizon? | Match each dated BCB forecast to the corresponding realized IBGE/official macro series using a stated horizon convention. | Show vintage and horizon; one observation is an example, not a forecast-skill estimate. |
| Q9 | Do expectation revisions differ across inflation regimes? | Join BCB Focus vintages to realized IPCA and define regimes using a pre-specified rule; compare revision distributions. | Regime association is descriptive and sensitive to sample window and regime definition. |

## Limitation questions

| ID | Requested question | Why current data cannot answer it | Additional data or design required |
| --- | --- | --- | --- |
| L1 | Does high cash conversion cause future equity outperformance? | Accounting-price association is confounded by sector, leverage, selection and survivorship. | Point-in-time universe, delisting returns, controls and out-of-sample identification design. |
| L2 | Do FII property vacancy and delinquency figures predict realized property cash collections? | Periodic disclosures are snapshots and do not link property measures to subsequent tenant-level receipts. | Stable property identifiers and validated subsequent rent/collection outcomes. |
| L3 | Does a Focus forecast miss measure the skill of individual forecasters or the causal effect of monetary policy? | Aggregate medians omit participant-level forecast paths and do not identify policy effects. | Consistent individual forecast vintages and a separate causal identification strategy. |
