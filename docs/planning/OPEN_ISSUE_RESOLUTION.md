# Open issue resolution plan — 2026-10-06 (UTC-3)

Initial GitHub snapshot at 23:59 UTC-3 on 2026-10-05: open issues #607, #517, #510 and #628;
only open PR #658 at that snapshot. Update: #658 merged at 00:00:48 UTC-3 on 2026-10-06 and #607 closed; the raw-upload regression remains on main and is repaired in a separate follow-up PR. #614 is a resolved priority decision, not proof of deployment.
The local Coordinator active board had zero claims before this task claimed its
bounded fix and planning paths. This does not prove external Cloud/Wizard sessions
are idle. No additional agents were launched.

## Execution order and closure evidence

| Order | Work | Dependency / action | Done and close when |
| --- | --- | --- | --- |
| 0 | Repair #658 smoke regression | Parse request.form only for multipart; raw curl form-urlencoded bytes remain unread until _upload. Keep empty body 400, unknown nonempty body 415, unauthorized 401. Regression tests exercise the smoke's exact content type and a valid binary XLSX. | Follow-up PR Engine image and Tests CI succeed on the fix SHA; do not weaken the smoke expectation. |
| 1 | #607 brief | #658 merged and #607 closed; do not rebuild it. Review the brief/appendix and declared client-constraint scope. Integrate only after CI; then deploy Worker and engine and inspect HTML, explicit PDF, cost and privacy results. Synthetic brief is one page; actual GPT output may span more and must be inspected. | #658 has closed the implementation issue. Record live verification separately; an issue close never proves deploy. |
| 2 | #517 real BTG parser validation | #516 is closed: the samples already exist. Deterministic parser and consolidation are built. Owner runs the existing local command below on the two real PDFs; only masked aggregate output is shared. Use any failed sum check to make one bounded parser fix with synthetic regression fixture. | All statement/section/portfolio sum checks pass, no line silently dropped, position dates compatible for consolidation, masked field coverage recorded on #517. No new parser or LLM extractor without measured failure. |
| 3 | #510 MVP end-to-end verdict | After #607 integration and #517 evidence: reconcile the live API catalog/MCP with merged features, then Worker/engine revision. Validate returned brief, complete appendix, returns basis/coverage, fees provenance, client constraints, real GPT narrative, US$1 cap, privacy probes and trace behavior. HTML-only runs intentionally have no stored PDF; document that distinction. Investigator remains off until supervised run; distinguish this optional activation from core diagnosis readiness. | An authorized run on the owner's real consolidated portfolio meets destination: every position identified or explicitly flagged, no dropped value, sums reconcile, report hosted, mandatory validation evidence posted. READY only for observed checks; remaining gaps named. |
| Separate track | #628 bond → equity research | Research only; read current main and the outcomes of the existing Cloud/Wizard sessions before any implementation spec. Reuse the credit-document note, rate/DI contracts, issuer mappings. Verify lawful source access, history, usable traded data and point-in-time limits; measure ~20 listed issuers. | Cited note under docs/reference/research with one supported verdict, coverage/missingness and smallest proposed data contract. No schema, ingest, workflow, secrets or backfill changes in this issue. |

## Immediate handoff

Real PDFs stay on the owner's machine. The existing runner (not a new build):

```bash
python -m src.portfolio.statement_pdf FIRST.pdf SECOND.pdf --consolidate
```

Share only its masked aggregates and sum-check outcomes. The earlier issue records
a session classifier restriction; do not infer that current tool capability or an
empty Coordinator board removes that restriction. Do not fetch or parse real
statements through an agent shell as part of this plan.

## Coordination boundaries

One execution task owns the #658 correction and live-validation sequence. A separate
research task for #628 can be assigned on demand with only the research note as its
write boundary; it may not apply SQL or deploy. Before any assignment, check active
claims and reconcile Cloud/Wizard work. The Coordinator provides boundaries, not
unattended agent execution or permission for deployments.

Do not close #517 or #510 on synthetic tests, PR merge or stale map text. Update
#510's old build-slice descriptions only from then-current production evidence.
No new feature expansion until the existing MVP is validated.
