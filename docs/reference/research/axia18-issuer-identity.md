# AXIA18: documentary issuer identity

Issue: [#805](https://github.com/PedroDnT/SILO-BZ/issues/805).
Primary documents reviewed on 2026-10-09 at 17:34 UTC-3.
Scope: the debenture `DEB / AXIA18 / BRAXIADBS0C8`, not every security
whose code starts with AXIA.

## Finding

**The original issuer CNPJ is documentarily established as
`00001180000126`.** The original issuance notice puts that CNPJ and the
first-series ISIN `BRAXIADBS0C8` in the same document. This is stronger than
matching an issuer name or guessing from the instrument code.

| Claim | Primary evidence and locator | Confidence |
| --- | --- | --- |
| Original issuer is Centrais Elétricas Brasileiras S.A. – Eletrobras, CNPJ `00.001.180/0001-26`; first-series ISIN is `BRAXIADBS0C8` | [Original commencement notice](https://ofertaspublicas.xpi.com.br/wp-content/uploads/sites/10/2026/02/Deb.-AXIA-Energia-8-Emissao-Anuncio-de-Inicio-v.-publicacao110132642.1.pdf#page=1), PDF p. 1, heading and first-series identifier | High: identifiers appear together |
| Series 1 belongs to issuance 8, dated 15/02/2026; registration `CVM/SRE/AUT/DEB/PRI/2026/097` is dated 24/02/2026 | Same notice, pp. 1–2 | High |
| Current market code AXIA18 identifies that same ISIN, series 001/emission 008, registration suffix 2026/097 | [Instrument characteristics](https://www.debentures.com.br/exploreosnd/consultaadados/emissoesdedebentures/caracteristicas_d.asp?selecao=AXIA18&tip_deb=publicas), fields Ativo, ISIN, Série/Emissão, Registro and Datas | High for the current identifier bridge; this is a mutable page |
| The same corporation approved changing its legal name to AXIA Energia S.A. on 15/04/2026 | [Original meeting minutes](https://api.mziq.com/mzfilemanager/v2/d/abb77a17-3348-4bc7-849a-154998e06ca3/0c57c560-2f87-6f4b-3efe-872f5f3e1f75?origin=2), PDF p. 1 CNPJ/date, p. 6 extraordinary resolution (i), pp. 36–37 consolidated bylaws | High for approval; no separate registry-effective timestamp established |

An [issuer-filed commencement notice translation](https://www.sec.gov/Archives/edgar/data/1439124/000129281426000509/axia20260225_6k1.htm)
corroborates the original issuer, CNPJ, ISIN and issue date. Locators:
opening heading; section 1; signature dated 25/02/2026. Its section 5 gives
24/02/2026 as the notice publication date. These document dates are not
this repository's observation timestamps.

## Dates and knowledge boundaries

The original notice's p. 2 records the deed dated 06/02/2026 and amendment
dated 23/02/2026. Its p. 5 schedules notice publication for 24/02/2026 and
financial settlement for 25/02/2026. Its p. 7 limits resale by reference to
article 86(I) of resolution 160. The initial offer was restricted to
professional investors (p. 2). This review does not establish the later
date when each resale restriction expired or an unrestricted investor universe.

Use 15/02/2026 only as the documented **issue date / earliest economic
identity boundary**, not as the date SILO knew this reviewed link. Current
review knowledge begins at the observation time above. A historical
point-in-time claim needs independently preserved publication/receipt evidence
and the relevant as-of policy. A dated public document discovered today does
not retroactively become a SILO observation on its printed date.

## Conflicts and exclusions

The [issuer's current debt page](https://ri.axia.com.br/acoes-dividas-e-dividendos/divida-axia-energia/)
lists AXIA18 and maturity 15/02/2033, but displays issue date **15/02/2025**.
That date conflicts with the dated original notice and the instrument
characteristics page (both 2026). Do not import the 2025 date; retain this
conflict in provenance. The original notice is the selected issuance-date
authority.

No document reviewed establishes `ELET18` as an earlier code for this
debenture, nor an old-to-new ISIN bridge. Existing ELET-prefixed debt on the
issuer's debt page does not prove such an alias. Leave aliases empty.

The supplied warehouse observation `SHARES / AXIA18 / BRAXIAA08PC5`
is outside this document's scope. Its different ISIN must not be replaced by
the debenture's ISIN or joined solely on `AXIA18`. Retain the security type
and exact ISIN in the instrument identity; the CNPJ is the issuer join key.

This review establishes original issuer identity, not a stock ticker's
historical validity, a change of obligor, yield, coupon-adjusted return or
residual equity return. No complete amendment/novation review was performed.
It therefore does not certify that no later obligor change occurred.

## Repository application

`research_examples/debenture_equity/reviewed_links.json` records this as
`reviewed_original_issuer`, keyed by `(AXIA18, BRAXIADBS0C8)`. Its economic
interval starts on 15/02/2026 and is bounded through 08/10/2026. Applying
the original issuer throughout that interval is an explicitly retained
retrospective assumption of no intervening issuer transfer, not documentary
certification of continuous liability. `known_at` is the actual review time
on 09/10/2026; strict as-of selection cannot use the link on earlier dates.

The warehouse's latest 2026 listing filing for CNPJ `00001180000126`
(`cia_ticker`, document `159987`, version 4, reference 01/01/2026) contains
AXIA3 (ordinary shares) and AXIA7 (preferred shares), both with no reported
end date. This filing was fetched on 28/08/2026 at 05:24:00 UTC-3.
The observed adjusted-price history contains 27 dates for each ticker
between 01/09/2026 and 08/10/2026. These observations support a current
issuer-to-equity candidate set, not historical publication-time eligibility,
a selection of one share class, total return, or a residual-return result.
Earlier ELET listings are not automatically spliced into this interval.

The existing experiment matches the exact code and ISIN; it does not join
through the registry's SHARES row by code alone. No selector, schema,
serving contract or production mapping was changed. The citation locators
are recorded, but this review did not retain and hash the original PDFs.
