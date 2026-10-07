# Debenture signals and subsequent issuer equity residual returns

Owner-authorized implementation sequence, 2026-10-07 (UTC-3). This records the
plan agreed in the conversation and the first executable audit gate. It does
not claim the full experiment is implemented or that predictability is proven.
[ADR 0004](../../adr/0004-debenture-market-data-sources.md) remains authoritative.

## 1. Identity and coverage gate: implemented, links still unverified

[Runner and instructions](../../../research_examples/debenture_equity/README.md)
provide a read-only, single-capture SQL audit and an offline JSON-to-table report.
No production credentials are read by the runner. No dataset, mapping table,
schema, workflow or public API is added. Name matches remain candidate evidence;
full CNPJ → stock ticker comes from FCA. No issuer stock ticker is required for
a debenture to exist. A parent's stock is never substituted automatically.

The query was executed through Supabase MCP on 2026-10-07 (UTC-3), against existing
capture `f7d46926-0349-4d54-a198-ffbad8045065`. Its hash verified, status was complete,
zero rows were dropped and all five expected sessions arrived. Source interval:
2026-09-30–2026-10-06; retrieved 2026-10-07 at 17:44:29 UTC-3. Stored raw UTF-8
payload: 82,130,390 bytes. The capture contains 59,670 facts, 6,630 source groups,
1,181 DEB codes and nine metrics. These are five observed sessions, not continuous
deep history or original publication vintages.

| Candidate classification | Debenture codes |
| --- | ---: |
| Unique full-CNPJ name candidate | 804 |
| Multiple CNPJ candidates | 2 |
| No candidate | 375 |
| Unique candidate with any registered equity/unit | 428 |
| Unique candidate with positive equity cash closes in the window | 365 |

The last row covers **82 distinct candidate CNPJs**, not 365 independent equity
outcomes. The extra name aliases include `cia_company.raw.DENOM_COMERC`; no
additional unique match depends solely on that commercial-name field in the
prior staged audit. The present query includes all cash short names within the
window rather than only 05/10. It reproduced the same unique/ambiguous/unmatched
census. Its output retains each alias and source; it does not rank a name as proof.

| Ambiguous bond | Candidate CNPJs | Disposition |
| --- | --- | --- |
| CMTC11, BRCMTCDBS004, Construtora Metrocasa | 27743642000137; 27743642000218 | Same 8-digit root, different establishments; no full-CNPJ choice inferred |
| MGPRA0, BRMGPRDBS076, Concessão Metroviária do Rio de Janeiro | 02327817000102; 10324624000118 | Different roots with the same normalized legal name; issuer link unresolved |

Bounded company-register inspection finds Metrocasa CVM 27340 under the first
CNPJ; the second is an FCA-name candidate. The two metro CNPJs have CVM 16810 and
22144, and commercial names METRÔ RIO / METRÔRIO. Neither ambiguous candidate has
an eligible equity/unit ticker in the audited registration set. These facts do
not identify the issuance's contractual issuer. Keep these bonds outside the
confirmed sample until issuance evidence settles the link.

Current verdict: **PARTIALLY READY**. Price/PU and quantity/count/volume exist;
rate/spread and outstanding are absent from this captured source. Turnover can
only be volume or quantity activity without an outstanding denominator. Holdings
marks are not market trades. Yield cannot be derived from PU alone under V1.

## 2. Dated evidence and PIT gate: pending

Review each selected bond's issuer using issuance code/ISIN and a documentary
CNPJ reference. Record citation, validity dates and when SILO knew the evidence.
Legal/commercial-name agreement alone cannot clear this gate. Distinguish issuer
from ultimate obligor; any guarantor study is separately evidenced under #660.

Audit by session: delivery versus absence of a bond; null metrics; classifications;
revisions; and calendar freshness. Select the whole latest complete snapshot per
source/date available at the cutoff before joining facts, so later removals do
not resurrect old bonds. Do not forward-fill. Current historical downloads are
retrospective observation-date evidence; strict historical PIT cannot be recovered
by relabeling their trade date. Separate that study from prospective knowledge-time
validation. FCA reference dates and latest aliases do not establish publication times.

## 3. Bounded historical preparation gate: pending approval of a concrete load

Reuse the current ingestor after checking actual missing coverage. Start with a
three-month pilot only after an explicit window and storage allowance are approved;
expand to at least twelve months if continuity, issuer activity and statistical
power justify it. Do not repeat the recovered 06/10 COTAHIST session, run an annual
backfill, or enable permanent credit capture. The existing five-session production
load was separately approved; authorization is not extended to another window.
REUNE rates follow ADR 0004; this continuation adds no REUNE dataset or collection.

## 4. Experiment contract: pending implementation after data gates

Primary target: issuer equity residual return over five trading sessions after
signal availability. Secondary horizons: one and twenty sessions. Select the
issuer's equity class using prior liquidity only. Use verified compatible adjusted
or total returns for equities and the market benchmark; estimate beta on a trailing
window that ends before the signal. Freeze the estimation window and date splits
before inspecting predictive results. Sector controls are robustness checks.

Compare an equity-only baseline with the same baseline plus credit activity and
price signals. Keep price changes distinct from bond total returns: amortization,
coupons, maturities and stale quotes can move PU mechanically. If necessary cash-flow
information is absent, exclude affected price windows or restrict the first model
to liquidity signals. Add rate/spread signals only after conventions and observed
rates exist. Aggregate to one issuer/date observation without treating repeated
last/reference PU or multiple bonds as independent issuer outcomes.

## 5. Evaluation and decision gate: pending

Freeze chronological development, validation and untouched-test intervals. Account
for overlapping horizons and dependence across issuers/dates; predeclare multiple
comparison handling. Run issuer shuffles, realistic availability delays and exclusions
of dominant issuers/days. Report sample attrition, effect sizes and uncertainty.
Costs and capacity are required before a tradability claim. Distinguish incremental
out-of-sample evidence, unsupported hypothesis and insufficient evidence. No five-day
capture can settle the research question.

Execution estimates after gate clearance: documentary review initially 2–4 hours;
coverage audit about one day; historical preparation 1–3 days subject to source
latency and approval; model/evaluation 2–4 days. Prospective validation requires
elapsed market history. No remaining stage is represented as completed by this audit.
