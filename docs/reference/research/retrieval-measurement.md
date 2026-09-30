# Research-sized retrieval on today's public interface

Wayfinder ticket [#376](https://github.com/PedroDnT/SILO-BZ/issues/376), map
[#371](https://github.com/PedroDnT/SILO-BZ/issues/371). Measured 2026-09-28
around 13:20 UTC-3 (16:20 UTC), against the live project, with the public SDK
(`sdk/silo_client`) and the publishable key from `skill.md`: exactly what an
external research caller has. Read-only. Harness:
[`retrieval_measurement.py`](retrieval_measurement.py), which the build phase
can reuse as the verification harness (`--workers`, `--n`, `--years`, `--skip`).

## Answer

A research-sized retrieval works today, is fast, and is never silently cut. Its
costs are in caller complexity, not in time:

| Retrieval                                               | Requests            | Wall-clock | Rows    | Refusals | Notes                       |
| ------------------------------------------------------- | ------------------- | ---------- | ------- | -------- | --------------------------- |
| 100 liquid equities/units, "10 years" daily, sequential | 188                 | 70.3 s     | 162,055 | 0        | 0.72 s median per ticker    |
| same, 8 workers                                         | 188                 | 12.9 s     | 162,055 | 0        | no 429                      |
| same, 16 workers                                        | 188                 | 7.8 s      | 162,055 | 0        | no 429; p95 latency 1.15 s  |
| IBOV11 via `quote_history`                              | 1                   | 0.2 s      | 316     | 0        | settlement days only (#374) |
| CDI 15 years via `macro_series`                         | 3 refused tries + 6 | 1.1 s      | 3,767   | 3        | only 3-year chunks fit      |
| PETR4 fundamentals 2019→, 8 statements                  | 36                  | 11 s       | 18,236  | 14       | halving on refusal          |

Plus 3 requests to pick the universe. Whole sequential run: 237 requests,
84.8 s, zero HTTP 429, p50 354 ms, p95 602 ms, max 859 ms. Row counts are
identical across the three quote runs.

## Findings the interface decision needs

1. **"10 years" is 7.7 years.** The tape starts 2019-01-02 (PETR4's first row
   in `api.equities`). A 2016-09-26 → 2026-09-25 request returns 1,927 rows for
   a name listed throughout, with no refusal and no hint that the window was
   longer than the data. 69 of 100 names start on 2019-01-02; the rest start
   later (IPOs, renames). A caller cannot tell "not loaded" from "not listed"
   from the response alone; `coverage()` has no start date for `quotes`.
2. **One ticker per call, one cursor per ticker.** 100 names cost 188 quote
   requests (two 1,000-row pages per full-history name). The paging is correct
   (0 duplicate dates, pages end short) but the caller writes the fan-out.
3. **Parallelism is free today.** 16 concurrent anonymous workers drew no rate
   limiting and cut wall-clock 9×. No limit is documented, so this is an
   observation, not a guarantee.
4. **Macro has no cursor, and the ticket #380 estimate is optimistic.** CDI over
   4 years (≈1,004 business days) refuses; 3-year chunks are the widest that
   fit, so 15 years is 6 calls (2019 onward is 3). The refusals are cheap
   (~0.2 s) and say why.
5. **Fundamentals refuse or time out, unpredictably.** 2019 → today for PETR4
   refuses on 6 of 8 statements (DMPL needs 8 windows, BPP 4). In the first
   (cold) run the same whole-window calls on BPA, BPP, DRE, DFC_MI and DFC_MD
   hit the 3 s anonymous statement timeout instead (57014, HTTP 500), so the
   caller must handle both errors with the same halving loop. DFC_MD is empty
   for PETR4 (it files DFC_MI).
6. **Ticker series have holes that are corporate events.** NATU3 returns 552
   rows on one ISIN (`BRNATUACNOR6`) with a gap from 2019-12-17 to 2025-07-02,
   while the company traded under another code. Recent renames (AXIA3 from
   2025-11-10, MBRF3, AZZA3) start mid-window. Relevant to the research
   universe ticket (#378).

## Universe used

Today's (2026-09-25) 100 most-traded standard-lot tickers on board `02` from
`api.equities` + `api.units`, by volume. Survivorship-biased on purpose: this
measures cost, not a research universe.

```
PETR4 BBAS3 VALE3 ITUB4 EMBJ3 AXIA3 RENT3 VBBR3 PRIO3 UGPA3 BPAC11 BBDC4 PETR3
RADL3 SBSP3 WEGE3 B3SA3 MGLU3 CPLE3 RDOR3 KLBN11 ABEV3 EQTL3 ASAI3 ITSA4 VIVT3
TIMS3 AZZA3 BBSE3 CSMG3 ENEV3 CYRE3 SUZB3 SMFT3 ENGI11 IGTI11 MOTV3 CMIG4 CURY3
COGN3 BEEF3 LREN3 ECOR3 GGBR4 YDUQ3 ALOS3 VIVA3 TEND3 DIRR3 SAUD3 CSNA3 POMO4
AXIA7 IRBR3 NATU3 CEAB3 RAIL3 BBDC3 MULT3 TOTS3 CSAN3 MOVI3 ITUB3 VAMO3 AURE3
FLRY3 HYPE3 CXSE3 MBRF3 MRVE3 BRAP4 PSSA3 HAPV3 CPFE3 TAEE11 EZTC3 GGPS3 CBAV3
PGMN3 GOAU4 RAPT4 EGIE3 SIMH3 SANB11 USIM5 ALUP11 SLCE3 SAPR11 ALPA4 SBFG3
ORVR3 CMIN3 JHSF3 ISAE4 TTEN3 BRAV3 RECV3 RENT4 PLPL3 SMTO3
```

## Reproduce

```bash
pip install -e sdk/
python docs/reference/research/retrieval_measurement.py                       # sequential, all four
python docs/reference/research/retrieval_measurement.py --workers 8 --skip cdi,fund,ibov
```
