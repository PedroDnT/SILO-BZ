# SILO

The language of SILO's public read side: diagnosing a mixed investment portfolio from disclosed holdings, financial documents and quantitative comparisons, and serving Brazilian market, macro and company data to external research callers.

## Language

### Portfolio analysis

**Mixed portfolio**:
An investor's collection of fund positions and directly held financial assets.

**Portfolio snapshot**:
The client-supplied description of a mixed portfolio at a valuation date: position identifiers, quantities or current values, and the date. SILO analyzes it per request and never stores it.
_Avoid_: Saved portfolio, account.

**Demo portfolio**:
A fixed portfolio snapshot of real positions, chosen to contain known findings, used as the acceptance test.
_Avoid_: Treating a passing demo portfolio as evidence that arbitrary portfolios are handled.

**Portfolio diagnosis**:
The single analysis of a portfolio snapshot that yields look-through exposures, qualitative warnings, and benchmark comparisons. Every client (MCP tool, web page) calls the same diagnosis.
_Avoid_: Putting analysis logic in a client.

**Unknown section**:
A part of a portfolio diagnosis (exposures, warnings, or benchmarks) that could not be computed, reported with the verbatim SILO error and the affected positions instead of being omitted or estimated.
_Avoid_: Partial results presented as complete; silent retries.

**Look-through exposure**:
An indirect exposure through assets held by an owned fund, including further fund holdings when disclosures permit identification.
_Avoid_: Treating a fund position as a fully known set of underlying assets.

**Shared exposure**:
Exposure through multiple portfolio positions to the same security, issuer, or economic group; those relationships are distinct and must be identified explicitly.
_Avoid_: Correlation as a synonym for common ownership exposure.

**Issuer match**:
Two exposures share an issuer when their issuer CNPJs share the same 8-digit root. Economic-group links beyond that are not assessed.
_Avoid_: Inferring issuer or group from names.

**What-if portfolio**:
A hypothetical allocation used to compare exposures and estimated risk with the current portfolio.
_Avoid_: Trade instruction.

**Minimum-variance allocation**:
Weights that minimize estimated portfolio variance for a specified asset universe, risk model, and constraints.
_Avoid_: Maximum-return portfolio or guaranteed lowest future risk.

**Qualitative warning**:
An evidence-linked finding or information gap relevant to portfolio risk that is not fully represented by the quantitative comparison.
_Avoid_: Confirmed loss or default when only a clause or uncertainty has been identified.

**Material revision**:
A restatement that changes a named economically meaningful field beyond a disclosed threshold. Other changes are "revised, not assessed".
_Avoid_: Calling every restatement material, or presenting SILO's thresholds as a regulatory standard.

**Estimation window**:
The historical period of monthly returns used to estimate risk (five years by default).
_Avoid_: Confusing it with the analysis horizon the user selects.

**Optional constraint**:
A restriction explicitly selected by the user for a what-if allocation, including one motivated by a qualitative warning.

**Direct holding**:
A financial asset held in the investor's own portfolio, including a fund position or a government bond.

**Underlying holding**:
An asset held by a fund in the investor's portfolio; it contributes indirect exposure rather than an additional direct portfolio allocation.
_Avoid_: Double-counting the fund position and its underlying assets.

**Equal risk contribution allocation**:
Weights targeting equal contributions from the selected portfolio components to estimated portfolio volatility, accounting for their covariance.
_Avoid_: Equal invested amounts or guaranteed diversification of underlying economic exposures.

### Research data

**Research caller**:
An external repository that consumes SILO data to build features, signals, models or backtests. It depends only on SILO's public read contract.
_Avoid_: Treating a research caller as a dashboard or a portfolio diagnosis client.

**Research universe**:
The set of instruments a research caller may select from: listed equities and units, defined by the ISIN's own instrument code (shares `ACN`; units `CDA` / `UNT` with a ticker ending 11). BDRs, fund quotas, indices and subscription receipts are outside it, even when they are Brazilian companies' receipts or track the market.
_Avoid_: A hard-coded list of currently active tickers.

**Raw close**:
The closing price as traded on the session, in the quotation unit B3 published.
_Avoid_: Calling a raw close "the price" when a return is being computed across corporate events.

**Price-adjusted close**:
A raw close made continuous across splits, groupings and bonus shares, so a price series has no jump caused by a change in share count. It is anchored to the latest session: past levels change when a new event lands, its returns do not.
_Avoid_: Treating it as a return series; it ignores cash distributions. Reading a past level as the price seen that day.

**Total-return close**:
A price-adjusted close that also reinvests cash distributions (dividends and JCP), so its changes are the shareholder's return.
_Avoid_: Adjusted close without saying which of the two is meant.

**First observed / last observed**:
The first and last session on which SILO holds a trade for a ticker. They are facts about SILO's tape, not about the listing.
_Avoid_: Listing date, delisting date.

**Listing date / delisting date**:
The dates a company filed as the start and end of a security's listing, each tied to the filing version that stated it.
_Avoid_: Deriving them from the tape or from a company's current filing.

**Current classification**:
A company attribute (setor, segmento) that SILO holds only as of today. It is not point-in-time and must be labelled as current wherever it is served.
_Avoid_: Using it as if it were the classification at a past date without saying so.

**Benchmark index**:
A market index level series (Ibovespa) as published by its administrator. An ETF that tracks it, such as BOVA11, is a separate instrument and never substitutes for it.
_Avoid_: Using an ETF's price as the index.

### Debenture secondary market

**Traded rate**:
The rate at which a debenture actually changed hands on a session, as the trade register published it. A session with no trade has no traded rate.
_Avoid_: Filling a session without a trade from the last trade or from an indicative rate.

**Indicative rate**:
An administrator's daily estimate of where a debenture would trade (ANBIMA's). It is a model output, not a trade.
_Avoid_: Calling it a market price or a traded rate.

**Contractual rate**:
The coupon or spread over the indexer that the debenture's deed fixes at issue.
_Avoid_: Treating it as the market yield.

**Debenture spread**:
A traded rate's distance from its indexer family's benchmark: the quoted spread for a DI+ debenture, and the real yield minus a duration-matched NTN-B yield for an IPCA+ debenture. A %DI quote is not converted into a spread.
_Avoid_: One spread across indexer families.

**Ultimate obligor**:
The entity that must pay a debenture: its issuer, or a guarantor that gave a personal guarantee (fiança, aval) under the deed and its amendments. A bond signal reaches an equity through its ultimate obligor.
_Avoid_: Treating a collateral provider as an obligor; inferring the obligor from a name or a shared economic group.

**Collateral provider**:
The entity whose assets secure a debenture (alienação or cessão fiduciária of shares, receivables or property). It owes nothing beyond those assets and may be a third party.
_Avoid_: Mapping a bond signal to a collateral provider's equity.

**Liquid debenture**:
In a month, a debenture with an issue value above R$300mm that traded at least R$10mm and on at least 40% of sessions in each of the two prior months (the eligibility rule of a BTG Pactual debenture index). It judges whether observed trades are enough for research; it does not bound what is stored.
_Avoid_: Treating a debenture outside it as having no price.
