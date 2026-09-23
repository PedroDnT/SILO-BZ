# Shared research contract (read before researching)

## Context
SILO (github PedroDnT/SILO-BZ) is a Brazilian public financial-data warehouse: daily GitHub Actions ingest of CVM (funds FI/FIDC/FII/FIP/FIAGRO/CRI-CRA, listed-company ITR/DFP + IPE events + ticker map, CDA holdings), B3 (COTAHIST EOD tape incl. options/termo, securities-lending book + trade-by-trade lending tape with brokers, investor-type flows, IBOV/IBRA/SMLL constituents, instrument registry, corporate events), BACEN (SGS, PTAX, Focus), IBGE (IPCA item tree), ANBIMA class bulletin. Serves: a free public read API (Supabase PostgREST schema `api`: panel, lookup, coverage, fund_nav, fund_holdings, fidc_cedentes/sacados/portfolio, financials, short_interest, investor_flow, lending, option_chain, inflation...), a free Evidence.dev dashboard (17 pages incl. FIDC credit monitor, suspicious-deal screens, dormant funds, short monitor, flows), agent docs (catalog, llms.txt, skill.md). NO: LLM/chat, own MCP, alerts, watchlists, Excel add-in, adjusted prices, intraday, DI curve, estimates, unstructured documents, restatement history. Stance: accountability, never fabricate, no advice/ratings.
Benchmark competitor: Tomé (agentetome.com, by Liqi) — free AI agent over CVM/FNET documents with restatement diffs, verified quotes, radar/monitor, MCP.

## Segments (priority order)
S1 Investment & financial-markets professionals (buy/sell-side analysts, gestoras, allocators, traders, credit/equity research) — PRIMARY
S2 Structured-credit professionals (FIDC, CRI/CRA, FII)
S3 AI agents / developers
S4 Accountability / research (journalists, academics, regulator-adjacent)

## Evidence rule (non-negotiable)
Y or P requires a URL you actually fetched or a search excerpt you saw. If unsure: `?` (unknown). Never infer a feature from marketing adjectives. Date is 2026-09-23. Label inferences as inference.
Values: Y = yes, P = partial/limited, N = verified absent, ? = unknown.

## Capability grid (IDs)
Coverage: C1 FI funds daily NAV/flows · C2 FIDC informe metrics · C3 FII · C4 FIP/FIAGRO · C5 CRI/CRA · C6 ETF · C7 fund holdings look-through (CDA) · C8 listed-co statements · C9 company events/fatos relevantes · C10 ownership/shareholders · C11 dividends · C12 analyst estimates/consensus · C13 equities EOD · C14 intraday/real-time · C15 options · C16 futures/DI curve · C17 secondary fixed income/debenture prices (ANBIMA) · C18 securities lending/short interest · C19 investor-type flows · C20 index composition · C21 macro (BACEN/Focus/IBGE) · C22 unstructured docs text (regulamentos, atas, rating reports)
Quality: Q1 history depth (state years) · Q2 restatement/version history · Q3 source citation per number · Q4 adjusted prices · Q5 point-in-time data
Analytics: A1 screeners · A2 rankings/league tables · A3 peer comparison · A4 risk metrics · A5 anomaly/forensic screens · A6 alerts/monitoring · A7 portfolio/watchlist · A8 cross-entity joins (fund→issuer→company/originator)
Access: X1 web UI · X2 Excel/Sheets add-in · X3 REST API · X4 SDK · X5 MCP/agent integration · X6 NL chat/AI assistant · X7 bulk download
Trust: T1 explicit no-fabrication/citation stance · T2 coverage/freshness transparency
Business: B1 free tier (Y/N) · B2 price (text) · B3 target segment(s) S1–S4
Ops: O1 how coverage grows (manual / agentic / unknown) · O2 pipeline auditability claims

## Output format
Write the FULL report to the file path you were given (markdown). It must contain:
1. For each DEEP platform: a profile (who, what, data sources/licensors, pricing, segment, AI features, differentiators, weaknesses) + the full grid as a table `ID | value | evidence URL | note`.
2. For each SHALLOW platform: a 4–6 line profile + only its notable Y/P capabilities with URLs + any capability SILO has that it clearly lacks.
3. "Gaps vs SILO": capabilities these platforms offer that SILO lacks, per segment, with which platforms offer them.
4. "What SILO has that none of these offer": candidate white space, each with the negative evidence (queries run, pages checked).
5. Sources list.
Then RETURN to the caller a concise summary (≤700 words): top findings, top 5 gaps vs SILO for S1 and for the track's segment, white-space candidates, and the file path.
Do not modify any file in the repo /home/user/SILO-BZ. Do not create accounts or log in anywhere.
