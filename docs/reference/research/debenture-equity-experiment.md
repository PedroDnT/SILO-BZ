# Debenture signals and subsequent issuer equity residual returns

Owner-authorized implementation sequence, 2026-10-07 (UTC-3). This records the
plan agreed in the conversation, the executable audit and the offline experiment.
Historical capture, broad identity acceptance and confirmatory evaluation remain
open. Predictability has not been demonstrated.
[ADR 0004](../../adr/0004-debenture-market-data-sources.md) remains authoritative.

## 1. Identity and coverage gate: implemented candidate census

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

## 2. Dated evidence and PIT gate: implemented checks, partial evidence

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

The local [reviewed links](../../../research_examples/debenture_equity/reviewed_links.json)
cite official issuance documents and SND records for three **original issuers**:

| Bond / ISIN | Original issuer full CNPJ | Existing FCA equities |
| --- | --- | --- |
| ALPA13 / BRALPADBS051 | 61079117000105, Alpargatas | ALPA3, ALPA4 |
| ALUP18 / BRALUPDBS0C9 | 08364948000138, Alupar | ALUP11 |
| ANIM18 / BRANIMDBS073 | 09288252000132, Ânima | ANIM3 |

Each link records citation/page, original issuance date, review cutoff and actual
knowledge timestamp. Retrospective use assumes no intervening issuer transfer;
the cited original documents are not a comprehensive review of every amendment.
This pilot does not verify all 82 candidate issuers. AURE12 is excluded pending
dated reorganization review; a parent's ticker is never substituted for Aura Almas.

The export reconciles full-capture fact/group counts against capture metadata and
selected-bond export counts independently. The runner rejects missing whole groups,
incomplete nine-metric groups, duplicate facts, equal-time revision ambiguity,
mixed equity revisions/ISINs and incompatible return bases. It chooses a whole
complete, hash-verified snapshot before joining bonds. Source classification
comparison ignores case; original values remain unchanged. Missing observations
and unpublished metrics are excluded, never filled with zero or forward-filled.

## 3. Bounded historical preparation gate: approved, partial execution

Reuse the current ingestor after checking actual missing coverage. Start with a
three-month pilot only after an explicit window and storage allowance are approved;
expand to at least twelve months if continuity, issuer activity and statistical
power justify it. Do not repeat the recovered 06/10 COTAHIST session, run an annual
backfill, or enable permanent credit capture. The existing five-session production
load was separately approved; authorization is not extended to another window.
REUNE rates follow ADR 0004; this continuation adds no REUNE dataset or collection.

Read-only export on 2026-10-07 at **22:01:24 UTC-3** found 191 existing cash/IBOV
sessions from January, 764 equity rows for the four tickers above, and 171 credit
metric rows across the two captures. Both capture censuses reconciled: 13,203 facts /
1,467 groups and 59,670 facts / 6,630 groups. Existing equity and IBOV total-return
series are used directly, with revision and missing-value checks.

Between 01/07 and 06/10 there are 69 known cash sessions, five already captured in
credit and **64 missing sessions**. The proposal covers only 01/07–29/09:

| Sequential slice | Start | End | Known sessions |
| --- | --- | --- | ---: |
| 1 | 2026-07-01 | 2026-07-07 | 5 |
| 2 | 2026-07-08 | 2026-07-14 | 5 |
| 3 | 2026-07-15 | 2026-07-21 | 5 |
| 4 | 2026-07-22 | 2026-07-28 | 5 |
| 5 | 2026-07-29 | 2026-08-04 | 5 |
| 6 | 2026-08-05 | 2026-08-11 | 5 |
| 7 | 2026-08-12 | 2026-08-18 | 5 |
| 8 | 2026-08-19 | 2026-08-25 | 5 |
| 9 | 2026-08-26 | 2026-09-01 | 5 |
| 10 | 2026-09-02 | 2026-09-09 | 5 |
| 11 | 2026-09-10 | 2026-09-16 | 5 |
| 12 | 2026-09-17 | 2026-09-23 | 5 |
| 13 | 2026-09-24 | 2026-09-29 | 4 |

If the approved five-session sample repeated, arithmetic implies 644,979,098 bytes
of additional allocated relations (~0.65 GB) and 1,051,268,992 raw UTF-8 bytes
(~1.05 GB). These are scenarios, not forecasts or caps; allocation differs from raw
size and excludes WAL/backups. At preparation time actual quota/headroom was
unverified; the subsequent execution preflight is recorded below.
Execution should stop between slices once newly allocated credit relations reach
1 GB; the last slice can overshoot that threshold. Approval must cover that
behavior and adequate headroom must be verified first.

After specific approval, reuse the existing command for each listed slice, starting
with slice 1 only, then inspect its audit, hash, delivery and storage increase:

```sh
.venv/bin/python -m src.pipeline.b3_credit_pipeline --start 2026-07-01 --end 2026-07-07
```

No new ingestor, schema apply, daily enablement or COTAHIST recovery is needed.
The existing ingestor stores all published DEB groups, not just these three bonds.
Before every subsequent slice, recheck coverage to avoid duplicate recovery;
stop on errors, incompleteness, drops, lost headroom or the allocation threshold.
After completion, regenerate the bounded research export and repeat the audit.
Source latency and split retries determine runtime; no throughput was measured
for this proposed window. Source history availability is not yet validated.

### Approved execution, 2026-10-07 (UTC-3)

The owner explicitly approved all 13 slices in the conversation. Preflight found
87,420,218,515 database bytes against the health workflow's recorded purchased
135 GB allowance; today's DB Health run `37589512910` succeeded. No replication
slots retained WAL. This checks the repository's operational allowance, not direct
filesystem free-space telemetry. Credit relations initially totaled 64,356,352 bytes.

| Slice | Outcome | Authoritative evidence |
| --- | --- | --- |
| 01/07–07/07 | Complete; five delivered sessions, zero drops | Capture `290b974f-246c-4fdb-98f1-e8682755eadb`, audit `ok` |
| 08/07–14/07 | Export transport failure after two attempts | Audit `c7c87c2d-2869-42c0-8d93-d2d2eca626b3`, zero facts written |
| Daily fallback 08/07 | Export transport failure after two attempts | Audit `c096de43-3760-423d-ad75-2732c9ca81f2`, zero facts written |
| Slices 3–13 | Not started | Sequence stopped on the existing ingestor's terminal error |

Successful capture observed at **22:08:49 UTC-3**, completed at 22:08:56. Its
175,737 source rows yielded 6,738 DEB groups, 1,222 bond codes and **60,642 facts**.
All groups had nine distinct metrics. Persisted UTF-8 payload: 23,842,689 bytes;
SHA-256 `82008ec327218286ef2dc0c8a92a335b30883b0e2a33084997e13c6d5260731f`,
recomputed successfully. Source dates remain July; knowledge time remains October.

The weekly failure ran 22:09:27–22:13:32; the existing daily fallback ran
22:13:32–22:17:37. Both logged `B3BdiFetchError`. The logs do not preserve the
underlying transport exception type/message, so its exact network cause is unknown.
Do not reinterpret this as empty trading data or unavailable historical publication.
The terminal process exited 1; no recovery process or current audit remains running.

Allocated credit relations ended at **86,646,784 bytes**, an increase of
**22,290,432 bytes**. The 1 GB stop threshold was not reached. Ten of the 69 known
signal-window sessions now have complete captures; **59 remain missing**. The next
unrecovered approved interval is 08/07–14/07. Resume only after diagnosing/rechecking
the export failure, rechecking coverage and preserving the already captured dates.
The existing approval is recorded; source transport, not owner permission, is now
the immediate blocker. No schema apply, annual backfill, COTAHIST recovery or
permanent enablement occurred.

## 4. Experiment contract: offline implementation, pilot only

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

[protocol.json](../../../research_examples/debenture_equity/protocol.json) freezes
January equity warm-up, July–October signals, 14/08 training and 04/09 validation
cutoffs, next-session close entry, 126-session beta (100 valid pairs minimum),
20-session prior liquidity (10 observations minimum), and ridge penalties tuned
only on validation. Baseline features are equity momentum, volatility and volume;
credit additions are extragroup volume, trade count and distinct active bonds.
The target subtracts trailing alpha and beta times IBOV log total return.
Labels crossing the next split are purged; test targets never tune or refit models.

**This protocol is a plumbing-only pilot.** Even assuming complete coverage and
daily issuer trading, its primary horizon permits at most **27 training, nine
validation and 15 test dates** after purges and future-label availability, below
the declared 30/10/60 floors. Three reviewed issuers also cannot meet the 20-issuer
test floor. Recovering the 64 sessions cannot make this protocol confirmatory.
Do not lower floors after seeing outcomes. A separate longer protocol, broader
documentary sample and sample/power assessment must precede confirmatory scoring.

## 5. Evaluation and decision gate: implemented method, no usable primary sample

Freeze chronological development, validation and untouched-test intervals. Account
for overlapping horizons and dependence across issuers/dates; predeclare multiple
comparison handling. Run issuer shuffles, realistic availability delays and exclusions
of dominant issuers/days. Report sample attrition, effect sizes and uncertainty.
Costs and capacity are required before a tradability claim. Distinguish incremental
out-of-sample evidence, unsupported hypothesis and insufficient evidence. No five-day
capture can settle the research question.

The runner implements paired out-of-sample MSE gain, crossed issuer/calendar-block
bootstrap, Bonferroni adjustment for the three horizons, within-date issuer credit
vector shuffles, two-session delayed entry, and refits excluding dominant issuers
or activity dates. These are methodological checks, not a validated power analysis.
Sector robustness remains unavailable without accepted dated classifications;
favorable statistical checks alone cannot produce a final favorable verdict.

Real-data execution produced **four issuer/date outcomes, all horizon one**;
zero five- or twenty-session outcomes fit the stored capture and fixed outcome end.
The 64 missing credit sessions were reported separately. All horizons are
**inconclusive**, and no p-value or predictive effect was estimated. Strict PIT
mode yielded zero rows: all historical credit was retrieved later, and equity/index
endpoints expose current revisions rather than original-date vintages.

Reproducibility identifiers (SHA-256; source payloads/results remain ignored locally):

```text
protocol c26a949418ebc10f5d948f27cfcd16460c0d79512b648d2b898d7d6b657c5122
bundle   d243b0ccc99afc4d45eb303b63bda0004e7288a4bb5ef91efae381146697dbfa
links    3ccc7afbfadb73bad95548c4856a923ade783f02f50c59c9310c71aaefdae7c3
```

After the approved partial recovery, a fresh bounded export at **22:17:54 UTC-3**
reconciled all three stored captures and 297 selected metric rows. The runner
produced **19 rows across horizons: nine at one session, five at five sessions and
five at twenty sessions**. These are overlapping issuer/date outcomes, not 19
independent observations. Training/validation/test coverage remains insufficient;
all horizons remain inconclusive and strict PIT still yields zero rows.
The new bundle SHA-256 is
`30a28ffe602694235c9f7bb8cf2383ef6cd075389fe1c3f6ccb2c4b0c8506826`;
protocol and identity hashes are unchanged. The earlier four-row run above is
retained as evidence before recovery, not current coverage.

Execution estimates after gate clearance: documentary review initially 2–4 hours;
coverage audit about one day; historical preparation 1–3 days subject to source
latency and approval; model/evaluation 2–4 days. Prospective validation requires
elapsed market history. The full research plan remains open; offline implementation
and a prepared capture proposal do not complete its empirical acceptance gates.
