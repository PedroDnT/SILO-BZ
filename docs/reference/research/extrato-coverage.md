# CVM Extrato das Informações: does it fill the fee gap the lâmina leaves

Wayfinder research ticket #524, part of map #510 (portfolio-diagnosis demo).
Measured 2026-10-02 23:38 to 23:44 UTC-3 (2026-10-03 02:38 to 02:44 UTC). Every
HTTP call is a public GET of a CVM file, run on a GitHub Actions runner. Two
read-only, bounded SELECTs against the production Supabase project
`zcjbtpxuhdekpwcxmepn` (section 6). Nothing was written to any database. This
file lives on the throwaway branch `research/extrato-coverage` and is never
merged. It builds on `research/lamina-coverage` (#514, same universe, same
balancete-derived estimate).

## Answer

1. **Yes, on coverage.** The current Extrato file has a `TAXA_ADM` for **21,962
   of the 26,046 FI funds (84.3%)**, against 4,135 (15.9%) for the lâmina's
   latest row and 1,200 (4.6%) for a lâmina from the last 12 months. By PL
   band: 84.5% of the 25,193 funds with PL >= R$1M, 78.2% of the 853 below. The
   funds it covers hold 94.1% of the universe PL (the 4,084 absent hold R$843bn
   of R$14,311bn; the PL sum double-counts funds held by funds, so it is a
   weight only).
2. **It covers CVM 175 classes, not subclasses.** `TP_FUNDO_CLASSE` takes two
   values, `FI` (26,837 rows) and `CLASSES - FIF` (11,959). Of the 21,962
   universe funds found, 11,350 are `FI` and 10,612 are `CLASSES - FIF`, keyed by
   the class CNPJ (`CNPJ_FUNDO_CLASSE`). The header has 117 columns and no
   subclass column, so a fee that differs by subclass cannot be seen.
3. **`TAXA_ADM` is never empty and 0 is not a zero fee.** All 21,962 matched
   funds have a value, so "not informed" cannot be told apart from 0. Exactly
   0 is 4,345 funds (16.7% of the universe, 19.8% of the filled). For the 2,697
   zero funds with an estimate, the balancete charges a median 0.35% a year and
   71.5% charge more than 0.10%. Same trap as the lâmina's zeros (#514).
4. **The value is usable but needs a guard.** Median 0.20, p90 2.0. Unit is %
   a year (section 3). But 115 funds (0.5%) are above 5, 70 above 100, 56 above
   1,000, maximum 14,638.38; for those the balancete estimate is a median
   0.0003 of the filed value, so they are scale errors, not fees.
5. **It agrees with the balancete estimate only half the time.** For the 16,436
   band-A funds with a positive `TAXA_ADM` and an estimate, the median
   estimate/`TAXA_ADM` is 0.994, but only 50.6% fall within +-25%. For rows dated
   within the last two years, about a third have an estimate over twice the filed
   fee. Older rows agree better, so row age is not a proxy for error.
6. **Against the lâmina it matches 59% exactly** (2,264 of 3,812 funds with both),
   and where they differ by more than 5% neither is closer to the estimate in a
   way that holds up: 582 extrato, 809 lâmina overall (the lâmina rows are mostly
   the 2024-09 snapshot), 160 against 158 on lâminas from the last 12 months.
7. **Recommendation: Extrato primary, lâmina second.** The Extrato adds 17,939
   funds to the lâmina's fee coverage (22,285 funds have either, 85.6%; the lâmina
   adds only 323 the Extrato lacks) and is one row per fund. Show the value
   "as filed on DT_COMPTC", treat 0 as unknown, drop values above 5, and keep the
   balancete estimate as the check, not as the fallback. Section 7.

## 1. What the dataset is

| Claim | Source | Accessed |
| ----- | ------ | -------- |
| The dataset holds the Extratos das Informações (versão 2.0) of ICVM 555 funds "nos últimos cinco anos". The "current" file has the latest version for all funds and is refreshed daily; the yearly files are refreshed weekly with re-filings | <https://dados.cvm.gov.br/dataset/fi-doc-extrato> | 2026-10-02 about 23:35 UTC-3 (2026-10-03 about 02:35 UTC), through Firecrawl, cache entry 2026-10-03 02:33 UTC |
| Page shows "Última Atualização 2 de outubro de 2026, 07:00 (UTC-04:00)", i.e. 08:00 UTC-3 (11:00 UTC) if the label is right. The page lists resources for the current file and 2021..2026 | same | same |
| The directory also has `extrato_fi_2015.csv` .. `extrato_fi_2020.csv` (not on the page's resource list), so "yearly files since 2021" in the ticket understates it. `extrato_fi.csv` is listed as 33M, last modified "02-Oct-2026 01:21" (timezone of the listing not stated); the 2022..2026 yearly files all "26-Sep-2026 11:29..11:31" | <https://dados.cvm.gov.br/dados/FI/DOC/EXTRATO/DADOS/> | 2026-10-02 about 23:36 UTC-3 (2026-10-03 about 02:36 UTC), live (`cacheState: miss`) |
| Dictionary: `TAXA_ADM` decimal(15,6) "Taxa de administração" (no unit stated); `TAXA_PERFM` numeric(27,12); `DT_COMPTC` "Data de competência do documento"; `CNPJ_FUNDO_CLASSE` varchar(18) "CNPJ do fundo/classe"; `CLASSE_ANBIMA`, `EXISTE_TAXA_*`, `TAXA_INGRESSO_*`, `TAXA_SAIDA_*`, `TAXA_CUSTODIA_MAX` are defined as the ticket lists them | <https://dados.cvm.gov.br/dados/FI/DOC/EXTRATO/META/meta_extrato_fi.txt> | same (file is ISO-8859-1, accents arrive as U+FFFD through Firecrawl; the runner decoded it correctly) |
| The XML standard behind the file says `TX_ADM` "para fundos destinados a investidores não qualificados, esse campo deve ser numérico e preenchido com % ao ano (base 252); para fundos destinados exclusivamente a investidores qualificados, preencha conforme estabelecida em regulamento (limitado a 400 caracteres)" | <https://cvmweb.cvm.gov.br/SWB/Sistemas/SCW/PadroesXML/PadraoXMLInfExtratoV2.asp> (linked from the dataset page) | 2026-10-03 about 00:00 UTC-3 (03:00 UTC), through Firecrawl |

## 2. Method

- **Universe (denominator).** The 26,046 FI funds of #514: a `vl_quota` in
  `fact_fund_monthly` in 2026-07..2026-09; 25,193 in band A (PL >= R$1M), 853 in
  band B. List: `.github/research/lamina_universe.txt` (CNPJ, band, in
  `cvm_fi_diario` 2026-09, PL, two balancete-derived fee estimates; public
  registry facts). The balancete estimate is the one defined in
  `lamina-coverage.md` section 2 (`est_aug`, % a year, 22,802 funds have it). The
  Extrato file has no PL column, so the PL >= R$1M share uses the universe band.
- **Extrato side.** `.github/research/extrato_coverage.py`, run as workflow
  `lamina_header_probe.yml` on this branch (file overwritten so GitHub dispatches
  it from this ref, the same trick as #514; `workflow_dispatch` only, no secrets,
  `contents: read`). Run 1: run 37090491647, job 111109593283, commit 2c405ca,
  02:38:16 to 02:39:34 UTC, green, 0 failed downloads. Run 2: run 37090718251,
  job 111110285670, commit fd3d6b8, 02:42:17 to 02:44:10 UTC, green. Run 2 is
  run 1 plus the sections "agreement by group", "zeros by group", "outliers",
  "which source is closer", "absent funds" and a smaller sample; sections 3 to 5
  below up to the lâmina comparison are from run 1, the rest from run 2 (the
  current file can change daily; 4 minutes apart, the shared lines match).
- Header, encoding and separator are detected, not assumed. Each CNPJ is
  normalised (strip non-digits, zero-pad to 14). Per CNPJ the newest
  `DT_COMPTC` wins, ties prefer a row with `TAXA_ADM`. The lâmina side re-reads
  the 92 monthly zips of #514 (2019-01..2026-08), latest row per fund, class-level
  row preferred.
- Ages are measured in days to 2026-10-02.

## 3. The file

| Fact | Value |
| ---- | ----- |
| Size / encoding / separator | 34,155,539 bytes; not valid UTF-8, decoded as ISO-8859-1 with 0 replacement characters; `;` |
| Header | 117 columns, starting `TP_FUNDO_CLASSE;CNPJ_FUNDO_CLASSE;DENOM_SOCIAL;DT_COMPTC;CONDOM;...`; the 117 columns are the dictionary's. The `QT_DIA_CONVERSAO_COTA` match in the script's "CNPJ-like" probe is a name collision, not an ID column. The 2020..2026 yearly files have the identical header (hash 117ae6f5); 2015..2019 differ (not diffed) |
| Rows / distinct CNPJ | 38,796 rows, 38,796 distinct CNPJ: **exactly one row per CNPJ**, as the dataset page says |
| CNPJ format | punctuated `##.###.###/####-##` in all 38,796 rows (the pipeline's `coerce("cnpj")` already strips it) |
| `TP_FUNDO_CLASSE` | `FI` 26,837; `CLASSES - FIF` 11,959; nothing else |
| Match to the universe | 21,962 of 26,046 (84.3%); 4,084 universe funds absent; 16,834 file CNPJs are outside the universe (funds with no quota in 2026-07..09) |
| Unit of `TAXA_ADM` | % a year. The XML standard says so (section 1), and the median balancete estimate (a % a year) over `TAXA_ADM` is 0.994. Dictionary silent |
| Fill rates, universe funds found | `TAXA_ADM` 100%; `TAXA_CUSTODIA_MAX` 100%; `CLASSE_ANBIMA` 98.9%; `TAXA_PERFM` and `PARAM_TAXA_PERFM` 24.8% (it is filled when `EXISTE_TAXA_PERFM` = S); `TAXA_SAIDA_PR` 3.3% (717 funds charge an exit fee); `TAXA_INGRESSO_PR` 7 funds (0.03%); redemption-term columns 100% except `QT_DIA_RESGATE_COTAS` (2.9%) |

Yearly files (versions, not funds): 2024 has 11,119 rows over 8,401 CNPJ; 2025,
13,590 over 10,399; 2026, 6,565 over 5,202 (all `CLASSES - FIF`). Folding the
current file with 2024..2026 adds **0 universe funds** and no `TAXA_ADM`, and no
current row is older than a yearly row for the same CNPJ. So for this question
the current file is enough.

## 4. Coverage of the universe

Funds; percentage of the segment. "Positive" = `TAXA_ADM` > 0.

| Segment | n | in file | `TAXA_ADM` = 0 | positive |
| ------- | -: | ------: | -------------: | -------: |
| All | 26,046 | 21,962 (84.3%) | 4,345 (16.7%) | 17,617 (67.6%) |
| A, PL >= R$1M | 25,193 | 21,295 (84.5%) | 4,202 (16.7%) | 17,093 (67.8%) |
| B, PL < R$1M | 853 | 667 (78.2%) | 143 (16.8%) | 524 (61.4%) |
| D, in `cvm_fi_diario` 2026-09 | 25,478 | 21,548 (84.6%) | 4,257 (16.7%) | 17,291 (67.9%) |
| A and D | 25,082 | 21,254 (84.7%) | 4,191 (16.7%) | 17,063 (68.0%) |

By PL bucket (PL share is a weight; the 39 negative-PL funds sit in no bucket):

| PL bucket | funds | in file (funds / PL share) | positive (funds / PL share) |
| --------- | ----: | -------------------------: | --------------------------: |
| < 1M | 814 | 647 / 63% | 509 / 49% |
| 1M to 10M | 3,488 | 2,849 / 82% | 2,322 / 66% |
| 10M to 100M | 12,713 | 10,563 / 84% | 8,718 / 69% |
| 100M to 1bn | 7,101 | 6,155 / 88% | 4,812 / 67% |
| >= 1bn | 1,891 | 1,728 / 96% | 1,241 / 60% |

Compared with the lâmina on the same 26,046 (`COVERAGE` line, run 1): lâmina
latest row with `TAXA_ADM` 4,135 (15.9%); lâmina of the last 12 months 1,200
(4.6%); Extrato filled 21,962 (84.3%), positive 17,617 (67.6%); either source
22,285 (85.6%); Extrato fee but no lâmina fee 18,150; lâmina of the last 12
months with a fee but Extrato absent 209.

## 5. How old each row is, and what the zeros and outliers are

**Age of the row** (`DT_COMPTC`, days to 2026-10-02, the 21,962 universe funds):
p10 127, p25 317, **p50 597**, p75 1,376, p90 2,251, p99 3,766, max 4,001.

| Age | funds | share |
| --- | ----: | ----: |
| 1 to 30 days | 635 | 2.9% |
| 31 to 90 | 914 | 4.2% |
| 91 to 180 | 1,452 | 6.6% |
| 181 to 365 | 3,088 | 14.1% |
| 366 to 730 | 6,891 | 31.4% |
| more than 730 | 8,982 | 40.9% |

Only 27.7% are dated within a year. This is the date of the filed version, not
how old the information is: a fund files a new Extrato when something changes
(the 2025-05 to 2025-06 spike, 1,334 rows in 2025-06, fits the CVM 175
conversion, but that is a reading of the month counts, not something the page
says). Evidence that age is not a proxy for error: against the balancete
estimate, rows older than 730 days agree better (59.8% within +-25%) than rows
under 366 days (42.7%), see below.

**Agreement with the balancete estimate** (band A, `TAXA_ADM` > 0, `est_aug`
present, n = 16,436): median ratio 0.994; within +-25% 50.6%; within x0.5..2
62.1%; within 0.25 percentage points 63.9%. With `est_jul` (n = 16,368): median
1.091, 52.5%. By group (share within +-25% / share of estimate over twice the
fee / under half):

| Group | n | within +-25% | est > 2x | est < 0.5x |
| ----- | -: | -----------: | -------: | ---------: |
| row <= 365 days | 4,295 | 42.7% | 31.9% | 14.0% |
| row 366 to 730 days | 5,282 | 45.0% | 34.6% | 10.9% |
| row > 730 days | 6,859 | 59.8% | 10.1% | 16.9% |
| `FI` | 8,706 | 57.8% | 14.1% | 15.6% |
| `CLASSES - FIF` | 7,730 | 42.4% | 34.4% | 12.6% |
| fund of funds (`FUNDO_COTAS` = S) | 7,088 | 52.1% | 18.8% | 17.6% |
| not fund of funds | 9,348 | 49.4% | 27.4% | 11.6% |

Recent filings, mostly CVM 175 classes, are where the balancete charges more than
twice the filed `TAXA_ADM`. **Why is not established.** One hypothesis is that the
class-level `TAXA_ADM` is only the administration part of a fee the balancete
books whole (CVM 175 splits the fee into administration, management and
distribution); I did not read the CVM 175 Extrato rules to test it.

**Zeros** (4,345 funds). Profile: 3,281 are not funds of funds and 1,064 are
(24.5%, against 43.3% of positive fees); 624 say they charge a performance fee;
2,100 `FI` and 2,245 `CLASSES - FIF`; `EXISTE_TAXA_INGRESSO` is N for all. By
`PUBLICO_ALVO`, zeros are 27.3% of "público em geral" funds (2,673 of 9,784),
13.2% of professional (985 of 7,465), 15.8% of previdenciário, 13.0% of
qualified (268 of 2,057). So the zeros are not mainly the qualified-investor
free-text case (where the standard says the numeric field may not hold the
fee); they are most common where the numeric is mandatory. With an `est_aug`
(A band, n = 2,663): median 0.30% a year for funds that are not funds of funds,
0.57% for funds of funds; share above 0.10%: 63.5% (rows 366 to 730 days) to
75.1% (rows under 366 days). Why a fund files 0 is not established.

**Outliers.** 115 funds above 5 (110 in band A; 91 `FI`, 24 `CLASSES - FIF`;
87 rows older than 730 days); 102 above 10, 70 above 100, 56 above 1,000. The
estimate over the filed value has a median 0.00028 (n = 107): consistent with
values filed in the wrong scale (a fee in basis points or in reais), not with
real fees. Cause not examined.

## 6. Against the lâmina, and the absent funds

**Funds with a `TAXA_ADM` in both** (Extrato current row, lâmina latest row;
n = 3,812). Exactly equal: 2,264 (59.4%); within 5%: 60.8%. Both exactly 0:
557. Extrato 0 and lâmina > 0: 150. Extrato > 0 and lâmina 0: 610. Split by
lâmina age: 12 months or less, n = 991, 62.0% equal; older, n = 2,821, 58.5%
equal. Where the lâmina `TAXA_ADM` is empty and it gives a min/max (variable
fee) but the Extrato has a value (n = 960): Extrato inside [min, max] for 84.9%
(of the 772 with a positive min), median Extrato/min 1.22.

**Which is closer to the balancete estimate when they differ by more than 5%**
(n = 1,391 with an estimate): Extrato closer for 582, lâmina for 809. On lâminas of
the last 12 months only (n = 318): Extrato 160, lâmina 158. Most lâmina rows are
the 2024-09 snapshot (#514), so the overall edge to the lâmina says the Extrato
is not always the fresher fee; the 12-month subset is a coin flip.

**The 4,084 universe funds absent from the current file.** 3,898 in band A; PL
R$843.1bn of R$14,311.2bn (5.9%); by PL: 825 under R$10M, 2,150 R$10M to 100M,
946 R$100M to 1bn, 163 over R$1bn. 3,488 have a balancete estimate (median 0.40%
a year). 377 have any lâmina and 323 have a lâmina `TAXA_ADM`. None is in
`extrato_fi_2015..2026`: they never filed an Extrato in these files. I checked
the names of the five largest absent funds and the two absent demo funds with
two bounded SELECTs on `cvm_fund_registry` (columns `cnpj`, `fund_name`,
`status`, `tp_fundo`, `dt_reg`; 2026-10-03 about 00:00 UTC-3, 03:00 UTC): six of
the seven are "Classes de Cotas de Fundos FIF" registered 2023-11 to 2025-12
(Bradesco Ultra Previdência FIE II 2025-06, Health Cash 2023-11, Bradesco
Debêntures Incentivadas CDI II 2024-04, MT Global II 2025-12, XP Bancos FIC FIF
2025-05, XP Liquidez FIC FIF 2024-02); the seventh (CNPJ 15831754000160, PL
R$35.5bn, status CANCELADA in the registry) is a cancelled fund. That fits "new
CVM 175 classes have not filed an Extrato" but seven funds do not establish it;
the rule was not tested on the 4,084. (`cvm_fund_registry.taxa_adm` from
migration 64 does not exist in the live database yet, the query for it errored,
so the registry's `cad_fi` fee was not compared.)

**The five demo funds.** Three are in the current Extrato:
42592315000115 (`TAXA_ADM` 4.00, `DT_COMPTC` 2025-05-26, estimate 1.81, lâmina
empty), 35377390000106 (0.11, 2019-11-21, estimate 0.110), 08935128000159
(0.23, 2022-05-04, estimate 0.026, lâmina 0.03: here the Extrato is 9 times the
estimate and the lâmina is not). 50088190000119 and 51488342000133 are absent
(both XP FIC FIF classes).

## 7. Recommendation, and what was not verified

**Should the Extrato be the primary disclosed-fee source, the lâmina second?**
Yes, for a fund-coverage reason, with three rules:

1. Coverage decides it: 84.3% against 15.9% (4.6% from the last year), one row
   per fund, class CNPJ, current as of the day.
2. Read 0 as "unknown", not "free" (4,345 funds; the balancete says most of them
   pay). Reject `TAXA_ADM` > 5 (115 funds) as a scale error.
3. Use the lâmina second: it adds 323 funds the Extrato lacks, and the min/max of
   a variable fee, which the Extrato does not carry. Do not prefer it where both
   exist: a coin flip on fresh lâminas.
4. Keep the balancete estimate beside the disclosed fee: they agree within 25%
   for half the funds, and for recent CVM 175 filings the estimate is often more
   than twice the filed fee. The Extrato is the fee as filed, not the fee paid.

The Extrato also holds what the lâmina does not: the performance-fee flag and
terms (24.8% of funds), entry and exit fees, custody fee, `CLASSE_ANBIMA`
(98.9%) and redemption terms. SILO ingests none of it today.

**Not verified.** Why 4,084 funds are absent (section 6 is seven funds).
Why a fund files 0. What `TAXA_ADM` contains for a CVM 175 class (administration
only or the global fee) and whether it is the class or a subclass value; the
Extrato file carries no subclass. When CVM requires a new Extrato (fee change or
not), so what a stale row means. The cause of the 115 outliers. The meaning of
`DT_COMPTC` beyond the dictionary's "data de competência do documento". The
`TAXA_CUSTODIA_MAX` and `TAXA_PERFM` values (fill rates only). Whether the
2015..2019 headers differ in anything that matters. The balancete estimate is a
derived number, not a disclosed fee, so "agreement" measures the two against each
other, not against the truth; it is also not defined for 3,244 funds (22,802 of
26,046 have it). The runs measured the file as it stood on 2026-10-02 to 03.
