# RJ seed: administradores judiciais and their websites

Seed data for epic #841 (links to the court documents of companies in
recuperação judicial). Built for #844 on 2026-10-12. The collector in #845
reads it. Nothing here is fetched by the daily run yet.

## Why AJ websites

Lei 11.101, art. 22, I, "k" (Lei 14.112/2020) requires each administrador
judicial (AJ) to keep a website where anyone can consult the main pieces of the
case. CNJ Resolução 393/2021 requires each state court (TJ) to keep a public
registry of AJs. There is no national list: the CNJ portal needs a gov.br login.

## Files

### `tj_registries.csv`: one row per TJ, plus the CNJ portal

| Column          | Meaning                                                    |
| --------------- | ---------------------------------------------------------- |
| `tj`            | TJ sigla, or `CNJ`                                         |
| `registry_url`  | The public registry page that was checked                  |
| `data_endpoint` | The JSON, CSV or form endpoint behind the page, when found |
| `format`        | How the list is published                                  |
| `status`        | `used`, `unusable`, `blocked` or `not_found`               |
| `n_entries`     | AJ entries read from the registry                          |
| `notes`         | Why a registry is unusable or blocked, and what is partial |

Measured 2026-10-12: 16 of 27 TJs used, 1,891 AJ entries. Seven are blocked
for a foreign egress, block robots, or disallow the list in `robots.txt`: TJAM,
TJAP, TJMS, TJRN, TJRO, TJSE and TJTO. TJES lists only peritos, TJMT was in
maintenance, TJPE needs a login, and no public registry was found for TJSC.

### `aj_sites.csv`: one row per AJ website

| Column                 | Meaning                                                                                                 |
| ---------------------- | ------------------------------------------------------------------------------------------------------- |
| `domain`               | The site's host, without `www.`                                                                         |
| `aj_names`             | AJ names linked to the site (registry rows, search results)                                             |
| `cnpj`                 | The firm's CNPJ, only when a source printed it                                                          |
| `tjs`                  | TJs where the AJ was found                                                                              |
| `case_list_url`        | The page that lists the AJ's cases                                                                      |
| `structure`            | `html` (list in raw HTML), `js` (only after rendering), `login`, `none` (no case list) or `fetch_error` |
| `robots_ok`            | `yes`, `no` (disallows the case path) or `unknown`                                                      |
| `platform`             | CMS or vendor fingerprint; sites on one platform can share one adapter                                  |
| `n_cases`              | Cases visible on the list page when checked                                                             |
| `has_process_number`   | The case page shows a CNJ process number                                                                |
| `has_doc_links`        | The case page links documents                                                                           |
| `case_page_example`    | One case page that was opened                                                                           |
| `fetch_error`, `notes` | What failed, and anything an adapter author needs to know                                               |

Measured 2026-10-12: 258 AJ sites. 164 are `html`, 18 `js`, 10 `login`, 36
`none` and 30 `fetch_error`. 149 show document links on a case page. Four sites
disallow the case path in `robots.txt`, and no adapter may read them. 26
candidate sites turned out not to be AJ sites and are not listed.

## How it was built

1. Each TJ registry was read with plain HTTP, or with Playwright and the JSON
   endpoint behind the page.
2. AJ websites came from the registries, from AJ firms found by search, and
   from the list in #844.
3. Every firm in a registry that matched no known site was searched by name.
   A site counts only when the page or a search result ties it to the firm.
4. Every site was fetched, and its `robots.txt` was read.
5. A random sample of 25 sites was fetched again. Every case list loaded, and
   23 of 25 classes matched; the two mismatches were corrected.

## Limits

- **Coverage.** The inventory is complete only for the registries in `status = used`.
  An AJ who is registered only in a blocked TJ, and who was not found by
  search, is missing.
- **Individuals.** About 1,300 registry entries are individuals, and most have
  no website. Their names are not stored here (LGPD). Only `n_entries` is kept.
- **Point in time.** Sites change. #845 needs a watchdog that fails when a site
  that had cases returns none.
- **No personal data.** The files hold no CPF, e-mail, phone or address.
