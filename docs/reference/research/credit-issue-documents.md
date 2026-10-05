# Official issue documents of CRA, CRI and debentures: where they are, and can an agent read them

Wayfinder research ticket #604, part of map #510 (portfolio-diagnosis demo).
Researched 2026-10-05 08:55 to 09:45 UTC-3 (11:55 to 12:45 UTC). Every SQL
query is a read-only, bounded SELECT against the production Supabase project
`zcjbtpxuhdekpwcxmepn` (section 6). Every web read is a public GET made
through a third-party fetcher (Exa, Firecrawl), because this session's proxy
blocks `dados.cvm.gov.br`, `conteudo.cvm.gov.br` and `fnet.bmfbovespa.com.br`
from the shell. Nothing was written to any database. The three examples are
public issues picked from public listings; none is a position of the owner's
portfolio (`DEB-01`, `DEB-02` and `CRI-01` were not looked up).

## Answer

1. **Yes, for the two sources that matter, with no login and no captcha.**
   CVM RAD serves debenture escrituras of CVM-registered issuers as text-layer
   PDFs, and B3 Fundos.NET serves the termos de securitização of CRA and CRI
   the same way. An agent fetched one document from each with a plain GET and
   read every field the ticket asks for (section 2).
2. **SILO already holds the RAD index.** `cia_event` carries 1,108 IPE
   documents of category "Escrituras e aditamentos de debêntures" delivered
   from 2025-01-02 to 2026-10-01, from 297 issuers, each with a RAD
   `link_download` (section 3). For a debenture of a registered issuer, the
   agent needs no new crawl: the link is one query away.
3. **SILO does not hold the CRA and CRI documents.** Fundos.NET lists them on
   a separate "certificados" page (`abrirGerenciadorDocumentosCertificadosCVM`)
   that calls the same JSON endpoint SILO's FNET fetcher already uses, with
   `paginaCertificados=true` and `tipoFundo` 5 (CRI) or 6 (CRA). The
   fetcher's own note says tipoFundo 4..6 "return nothing" (it never sends
   `paginaCertificados`), and one CRI document (FNET id 1067691, delivered
   2025-12-22) lies inside the id span SILO stored for that day but is not in
   `fnet_document`. That page has the categories the agent needs: "Termo de
   Securitização" (17), "Aditamento de Termo de Securitização" (19),
   "Escritura/Instrumento de Emissão" (44), "Documentos de Oferta de
   Distribuição Pública" (16) and "Relatório de agência classificadora de
   risco" (36). Whether the JSON listing answers without a browser session was
   **not verified** here (a call without the AJAX header got HTTP 520).
   Verified later the same day: it does, with no captcha (Addendum).
4. **The current version is several documents.** A termo or escritura is
   amended by aditamentos, and an aditamento may restate only the clauses it
   changes. The CRA example's first aditamento carries a consolidated termo
   (Anexo A); the CRI example's first aditamento restates the debentures'
   maturities but not the CRI's. An agent has to read the original and every
   aditamento, newest last, and say which one each field came from.
5. **Rejected for an agent: ANBIMA Data.** ANBIMA's portal terms forbid
   "aplicativos spider ou de mineração de dados ... que atue de modo
   automatizado", ANBIMA says ANBIMA Data's "extração de dados deve ser feita
   de forma manual", and the debenture pages are a JavaScript app that returns
   no content to a plain fetch.
6. **Second line only: securitizadora sites, issuer IR pages, the SND
   (`debentures.com.br`).** They are open and serve PDFs or HTML, but they
   are per-company layouts, lag the regulator (the example issuer's IR page
   did not list the escritura RAD received on 2026-09-30), or cover older
   issues only. Terms of use were not found or not read for any of them.
7. **Recommendation.** Debenture of a CVM-registered issuer: RAD, through
   `cia_event`. CRA and CRI: Fundos.NET certificados, by category 17 and 19,
   then 16 and 36; it needs a fetcher change that is a new ticket, not this
   one. Offer facts (registration number, rito, target investors): CVM's open
   `oferta_distribuicao.zip`. A debenture of an issuer that is not
   CVM-registered has no regulator copy found here: try the SND escrituras
   list, then the coordinator's offer page, else "documento não localizado".
   Section 5.

## 1. The sources

"Fields" means the ticket's seven: issuer CNPJ, lastro, debtor, guarantees,
indexer, maturity, rating. Accessed 2026-10-05 between 09:00 and 09:45 UTC-3.

| Source                                                                                                       | Access                                                                                                                                                                               | Format                                            | Fields an agent can read                                                                                                                                          | Terms of use                                                                             | One working URL                                                                                                                                                                                                                    |
| ------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **CVM RAD** (Empresas.NET, IPE category "Escrituras e aditamentos de debêntures")                            | open: plain GET, no login, no captcha                                                                                                                                                | PDF with a text layer                             | all seven for a debenture (lastro and debtor are the issuer itself)                                                                                               | not read                                                                                 | <https://www.rad.cvm.gov.br/ENET/frmDownloadDocumento.aspx?Tela=ext&descTipo=IPE&CodigoInstituicao=1&numProtocolo=1573029&numSequencia=1097735&numVersao=1>                                                                        |
| **B3 Fundos.NET, certificados page** (CRI, CRA, "Informações da Securitizadora", OTS)                        | download: open, plain GET by id. Listing: an AJAX endpoint; a call without the `X-Requested-With` header got HTTP 520. The captcha on the page belongs only to "Extrair Inf. Mensal" | PDF with a text layer; listing JSON               | all seven for a CRA or CRI, in the termo and its aditamentos; the anúncio de início has issuer, lastro, debtor and guarantees but not indexer, maturity or rating | none published (`src/fetchers/fnet_fetcher.py:108`: "FNET has no published terms")       | <https://fnet.bmfbovespa.com.br/fnet/publico/downloadDocumento?id=1121483>                                                                                                                                                         |
| **CVM offers system** (SRE, Res. 160)                                                                        | the public site `web.cvm.gov.br/sre-publico-cvm` is a JavaScript app, not read. The open-data copy is a daily zip                                                                    | CSV in a zip                                      | registration and offer facts per offer; columns not read here (the dictionary is a zip the fetchers could not open)                                               | dataset listed under the ODbL licence filter (`license_id=odc-odbl`) of the portal       | <https://dados.cvm.gov.br/dataset/oferta-distrib>                                                                                                                                                                                  |
| **ANBIMA Data**                                                                                              | open site, JavaScript app; a plain fetch of `/debentures/CSRNB4/documentos` returned only the title                                                                                  | HTML rendered in the browser                      | the home page counts "28.708 DOCUMENTOS" for debentures; not read                                                                                                 | portal terms forbid automated collection (quoted in section 1.1); manual extraction only | <https://data.anbima.com.br/debentures/CSRNB4/documentos> (renders only in a browser)                                                                                                                                              |
| **Securitizadora sites**                                                                                     | open                                                                                                                                                                                 | PDF                                               | the termo, when posted                                                                                                                                            | not read                                                                                 | <https://ecoagro.agr.br/public/storage/Arquivo/1732669210CRA_Primato_l_Termo_de_Securitiza%C3%A7%C3%A3o_(v._assinatura)(18672842.6).pdf> (found by search). `app.opeacapital.com/pt/ofertas-publicas-em-andamento` failed to fetch |
| **Issuer IR pages**                                                                                          | open                                                                                                                                                                                 | HTML list, PDF                                    | whatever the issuer posts                                                                                                                                         | not read                                                                                 | <https://ri.brasiltecpar.com.br/>                                                                                                                                                                                                  |
| **SND, `debentures.com.br`** (not in the ticket's list; checked as the route for issuers RAD does not cover) | open                                                                                                                                                                                 | HTML; escritura list; prospectos "em formato EXE" | characteristics page: ISIN, espécie, issue and maturity dates, remuneration type and rate, agents; no CNPJ shown                                                  | not read                                                                                 | <https://www.debentures.com.br/exploreosnd/consultaadados/emissoesdedebentures/caracteristicas_d.asp?tip_deb=publicas&selecao=CSRNB4>                                                                                              |

### 1.1 Quotes behind the table

| Claim                                          | Quote                                                                                                                                                                                                                                                                                                                                                                                                                | Source, accessed                                                                                                                                                                                                                                                                    |
| ---------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Res. 160 says where offer documents go         | "Art. 13. As divulgações requeridas por esta Resolução, inclusive do prospecto preliminar, quando houver, e do prospecto definitivo, devem ser feitas, com destaque e sem restrições de acesso, na página da rede mundial de computadores: I – do ofertante; ... III – das instituições participantes do consórcio de distribuição ...; IV – das entidades administradoras de mercado organizado ...; e V – da CVM." | <https://conteudo.cvm.gov.br/export/sites/cvm/legislacao/resolucoes/anexos/100/resol160consolid.pdf>, 2026-10-05 about 09:32 UTC-3, through Firecrawl's extraction mode (an LLM reading the PDF, so verbatim is likely but not machine-checked; inciso II, on funds, left out here) |
| The same rule, as an offer applies it          | "Quaisquer comunicados ou anúncios relativos à Oferta serão disponibilizados na página da rede mundial de computadores da CVM, da B3, da Emissora e do coordenador, nos termos previstos no artigo 13 da Resolução CVM 160."                                                                                                                                                                                         | FNET id 1067691 (section 2.1), 2026-10-05 about 09:36 UTC-3, Exa                                                                                                                                                                                                                    |
| CVM points CRI and CRA documents to Fundos.NET | page title "Informações de CRI e CRA (Fundos.Net)"; offer documents describe the path "clicar em 'Exibir Filtros', no campo 'Tipo de Certificado' selecionar 'CRI', no campo 'Securitizadora' ..."                                                                                                                                                                                                                   | <https://www.gov.br/cvm/pt-br/assuntos/regulados/consultas-por-participante/companhias/informacoes-de-cri-e-cra-fundos.net>; <https://strapicms.bancobari.com.br/uploads/CRI_39_Emissao_Anuncio_de_Inicio_6269f3c9dd.pdf>, both 2026-10-05 about 09:38 UTC-3, Exa                   |
| The certificados page's filters                | `<select name="tipoFundo">`: 6 "CRA", 5 "CRI", 8 "Informações da Securitizadora", 9 "OTS"; `idCategoriaDocumento` includes 17 "Termo de Securitização", 19 "Aditamento de Termo de Securitização", 44 "Escritura/Instrumento de Emissão", 16 "Documentos de Oferta de Distribuição Pública", 36 "Relatório de agência classificadora de risco"; the captcha block is `quadroCaptcha` with `style="display: none;"`   | <https://fnet.bmfbovespa.com.br/fnet/publico/abrirGerenciadorDocumentosCertificadosCVM>, 2026-10-05 about 09:39 UTC-3, Firecrawl (stealth proxy), HTTP 200                                                                                                                          |
| The listing call and the captcha's scope       | `ajax: { url: 'pesquisarGerenciadorDocumentosDados', ...` with `params.paginaCertificados = 'true' === $('input[name="paginaCertificados"]').val();`; the captcha is shown only by `$("#btnAnexoB").on("click", ... $('.quadroCaptcha').show();`, while `$("#showFiltros")` hides it                                                                                                                                 | <https://fnet.bmfbovespa.com.br/fnet/resources/js/paginas/publico/gerenciador-documentos-cvm.js>, 2026-10-05 about 09:40 UTC-3, Exa                                                                                                                                                 |
| SILO's fetcher never asks for certificados     | "tipoFundo query code → label. 4..6 return nothing (verified 2026-09-24)." and the parameter list has no `paginaCertificados`                                                                                                                                                                                                                                                                                        | `src/fetchers/fnet_fetcher.py:68`, `:12-18`                                                                                                                                                                                                                                         |
| The offers dataset                             | "oferta_resolucao_160.csv: ofertas públicas de distribuição primária ou secundária de valores mobiliários cujos requerimentos foram formulados a partir de 2/1/2023 em rito automático, conforme Resolução CVM 160"; "O conjunto de dados é atualizado diariamente"; "Última Atualização 5 de outubro de 2026, 07:02 (UTC-04:00)"                                                                                    | <https://dados.cvm.gov.br/dataset/oferta-distrib>, 2026-10-05 about 09:30 UTC-3, Firecrawl (live)                                                                                                                                                                                   |
| ANBIMA portal terms                            | "2.4. Neste portal ou aplicativo é terminantemente proibida a utilização de aplicativos spider ou de mineração de dados, de qualquer tipo ou espécie, além de outro aqui não tipificado, mas que atue de modo automatizado ..." Whether this page governs `data.anbima.com.br` is not stated in the excerpt read                                                                                                     | <https://www.anbima.com.br/pt_br/termos-de-uso.htm>, 2026-10-05 about 09:43 UTC-3, Exa search excerpt                                                                                                                                                                               |
| ANBIMA Data is manual                          | "O acesso é gratuito e a extração de dados deve ser feita de forma manual."                                                                                                                                                                                                                                                                                                                                          | <https://www.anbima.com.br/pt_br/noticias/instituicoes-podem-usar-a-nossa-precificacao-para-cumprimento-da-nova-regra-de-marcacao-a-mercado.htm> (2022-10-28), same time                                                                                                            |
| SND has an escritura list beyond RAD           | the list carries rows marked "DISPENSA ICVM 476/09" and "EMISSÃO PRIVADA"; the prospectos page says "Os arquivos estão disponíveis em formato EXE." A query of the list for `Ativo=CSRNB4` (a 2026 issue) returned no row                                                                                                                                                                                            | <https://www.debentures.com.br/exploreosnd/consultaadocumentacao/escrituras/escrituras_f.asp>, the `escrituras_r.asp` result pages and `prospectos_f.asp`, 2026-10-05 about 09:44 UTC-3, Exa                                                                                        |

## 2. Three public examples, fields read by hand

Read from the PDF text the fetcher returned. Clause numbers are the
document's. Values are as filed, including where two documents disagree.

| Field            | Debenture                                                                                                                                                                                                                                                                     | CRA                                                                                                                                                                                            | CRI                                                                                                                                  |
| ---------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| Document         | Escritura of the 5th issue of Brasil Tecnologia e Participações S.A., dated 2026-09-28; RAD, delivered 2026-09-30                                                                                                                                                             | First aditamento (2026-02-25) to the termo of the 441st CRA issue of Eco Securitizadora, with the consolidated termo as Anexo A; FNET id 1121483. Original termo (2026-02-02): FNET id 1099750 | First aditamento to the termo of the 370th CRI issue of Opea Securitizadora; FNET id 829237                                          |
| Issuer CNPJ      | 35.764.708/0001-01 ("companhia aberta ... categoria 'B'")                                                                                                                                                                                                                     | Eco Securitizadora, 10.753.164/0001-43                                                                                                                                                         | Opea Securitizadora, 02.773.542/0001-22                                                                                              |
| Lastro           | none (the issuer owes directly)                                                                                                                                                                                                                                               | 6th issue of debentures of Caramuru Alimentos, private placement, 3 series                                                                                                                     | 6th issue of debentures of Cury Construtora e Incorporadora, private placement, 4 series, represented by CCI                         |
| Debtor           | the issuer; 9 guarantors named (fiadores)                                                                                                                                                                                                                                     | Caramuru Alimentos S.A., 00.080.671/0001-00 ("com registro de companhia aberta perante a CVM")                                                                                                 | Cury Construtora e Incorporadora S.A., 08.797.760/0001-83                                                                            |
| Guarantees       | 4.5.1 "com garantia real, com garantia adicional fidejussória": cessão fiduciária of receivables and linked accounts (minimum monthly flow 5% of the face value plus interest), alienação fiduciária of fibre network and equipment (minimum 25%), fiança of the 9 guarantors | "Garantias Significa a Cessão Fiduciária e a Fiança", "não foram nem serão constituídas garantias específicas, reais ou pessoais, sobre os CRA"                                                | CCI "sem garantia real imobiliária"; the debentures are "da Espécie Quirografária"                                                   |
| Indexer          | 4.13.1 no monetary update; 4.14.1 "100% ... da variação acumulada das taxas médias diárias do DI ... acrescida exponencialmente de ... spread equivalente a 3,40% ... ao ano"                                                                                                 | 6.2 series 1: 109,50% of DI; 6.5 series 2: prefixed 14,85% a.a.; 6.8 series 3: IPCA-updated, 9,10% a.a.                                                                                        | from the bookbuilding recital: 99% of DI, 100% of DI, prefixed 15,0905%, IPCA + 8,1125%                                              |
| Maturity         | 4.6 "vencendo-se, portanto, em 28 de setembro de 2031"                                                                                                                                                                                                                        | series 1 2031-02-17, series 2 2033-02-15, series 3 2036-02-15 (CRA). The lastro debentures: series 1 2031-02-13                                                                                | the aditamento restates the lastro debentures only: 2030-01-11, 2032-01-13, 2032-01-13, 2035-01-11. The CRI maturities are not in it |
| Rating           | 3.5.1 "Não será contratada agência de classificação de risco para atribuir rating às Debêntures."                                                                                                                                                                             | (xvii) "Classificação de Risco: Não haverá classificação de risco para a Emissão."                                                                                                             | an S&P fee is in the cost table ("Agência de Classificação de Risco ... S&P"); no grade in this document                             |
| Target investors | 3.7.1 "Investidores Profissionais"; registro automático                                                                                                                                                                                                                       | not read                                                                                                                                                                                       | not read                                                                                                                             |

### 2.1 What the examples teach an agent

- **The anúncio is not enough.** The CRI anúncio de início of Opea's 528th
  issue (FNET id 1067691) gives issuer, lastro (notas comerciais of Creta
  Incorporação e Participação Ltda., 19.844.045/0001-70), guarantees and ISIN
  `BRRBRACIR0R7`, but no indexer, maturity or rating. The termo is the
  document to look for.
- **Documents disagree with themselves, and are reported as filed.** In that
  anúncio the guarantee list jumps from "(iv)" to "(vi)", the risk paragraph
  says "CCB" while the lastro is notas comerciais, it calls itself "Anúncio de
  Encerramento" once, and the registration line reads "18 de Dezembro ," with
  no year. In the CRA, series 1 matures 2031-02-17 and its lastro series
  2031-02-13. The agent quotes, never reconciles.
- **SILO's registry rows agree where they exist.** `cvm_securit_serie` has the
  CRA's series 3 (`CRA026000MG`, "IPCA + 9,1000% a.a", 2036-02-15) and the
  CRI's series 3 and 4 (`25A1946535` "+ 15,0905% a.a" 2032-01-15;
  `25A1946537` "IPCA+ 8,1125% a.a" 2035-01-15), matched by securitizadora,
  rate and maturity, not by an identifier in the document (neither aditamento
  prints an ISIN). Their `classificacao_risco_atual` is NULL, even for the CRI
  whose cost table pays S&P. The Opea 528th CRI is in `cvm_securit_serie`
  from `data_referencia` 2025-12-01, the month of its registration.

## 3. What SILO already holds (numbers)

| Fact                                                                             | Value                                                                                                                            | Query  |
| -------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------- | ------ |
| IPE "Escrituras e aditamentos de debêntures", delivered 2025-01-02 to 2026-10-01 | 1,108 documents, 297 issuers (`cd_cvm`), 1,108 with a RAD `frmDownloadDocumento.aspx` link                                       | Q2     |
| Of those, by `assunto`                                                           | 427 name an aditamento, 334 an escritura only, 346 neither (often "Emissão de Valores Mobiliários"), 1 without `assunto`         | Q3     |
| Other IPE offer documents since 2024-01-01                                       | "Aviso ao Mercado" 841, "Anúncio de Início" 825, "Anúncio de Encerramento" 796, "Prospecto" 191, "Lâmina de Oferta de Dívida" 96 | Q1     |
| FNET register rows whose name mentions a securitizadora                          | 400, all funds (FIDCs with "securitização" in the name); no CRI or CRA document                                                  | Q4     |
| Delivery day 2025-12-22 in `fnet_document`                                       | 553 rows, ids 1,067,281 to 1,068,098; id 1,067,691 (the Opea CRI anúncio) absent                                                 | Q5, Q6 |

`cia_event` is keyed on the filer's CVM code (`cd_cvm`): an issuer with no
CVM code files no IPE, so its escritura has no RAD row. The SND list carries
rows marked "DISPENSA ICVM 476/09" and "EMISSÃO PRIVADA" (section 1.1), so
such issues exist; how many of today's issues are in that case, and whether
`DEB-01`/`DEB-02` are, was not checked.

## 4. Method

- Read the ticket and the map's Notes. Listed SILO's tables with `fnet`,
  `cvm_securit_` and IPE content, then ran the bounded SELECTs in section 6.
- For each source, one public GET of a page or document through Exa
  (`web_fetch_exa`, `web_search_exa`) or Firecrawl (`firecrawl_scrape`,
  `firecrawl_search`); the session shell cannot reach CVM or FNET. Firecrawl
  ran out of credits at 09:40 UTC-3; the rest went through Exa. Large documents
  were saved by the tool and searched with `grep`; no document is in the
  repository.
- Examples: the debenture is the newest row of Q2b whose `assunto` names an
  "INSTRUMENTO PARTICULAR DE ESCRITURA" (delivered 2026-09-30; the two newer
  rows are an aditamento and an unnamed "Emissão de Valores Mobiliários"); the CRA and CRI are the first CRA and CRI termos (or
  aditamentos) on FNET that a web search returned with a 2025-2026 date. The
  Opea 528th CRI anúncio came from a search for the SRE URL.
- A GitHub Actions probe (the method of `extrato-coverage.md`) would have
  answered the open FNET question; it was not run, because changing a
  workflow file for a throwaway run was not authorised in this session.

## 5. Recommendation

For an agent that must find the issue document of a credit line SILO does not
identify (first level only: issuer and lastro):

1. **Debenture, issuer registered at CVM:** query `cia_event` for
   `categoria = 'Escrituras e aditamentos de debêntures'` by `cnpj_cia`, read
   every row newest last, and fetch each `link_download`. No new ingest.
2. **CRA or CRI:** Fundos.NET certificados, categories 17 and 19 (termo and
   aditamentos), then 16 (offer documents) and 36 (rating reports). This needs
   the FNET fetcher to send `paginaCertificados=true` with `tipoFundo` 5 and 6. That is a separate ticket (owner's rule: discovery is not
   prioritization); a first test is one delivery day of each type, checked
   against the id gap of section 3.
3. **Offer facts** (registration number, rito, investors): CVM's
   `oferta_distribuicao.zip`, open and daily, after its columns are read.
4. **Fallbacks, in order:** the SND escritura list, the securitizadora or
   coordinator's offer page, the issuer's IR page. Each answer says which
   source it came from.
5. **Never:** ANBIMA Data by automation. A CDB or CDCA (roadmap) has no
   public document found here.

Every field the agent extracts is a quote with the document, its date and its
clause, and a disagreement between documents is shown, not resolved.

## 6. SQL (re-run 2026-10-05, results above)

```sql
-- Q1 offer and indenture categories in IPE since 2024
select categoria, tipo, count(*) n, min(data_entrega) first_d, max(data_entrega) last_d
from cia_event
where data_entrega >= '2024-01-01'
  and (categoria ilike '%deb%' or tipo ilike '%deb%' or tipo ilike '%escritura%'
       or categoria ilike '%escritura%' or tipo ilike '%oferta%' or categoria ilike '%oferta%')
group by 1, 2 order by n desc limit 40;

-- Q2 escrituras since 2025
select count(*) n_docs, count(distinct cd_cvm) n_issuers,
       count(*) filter (where link_download like 'https://www.rad.cvm.gov.br/ENET/frmDownloadDocumento.aspx?%') n_rad_links,
       min(data_entrega)::date first_d, max(data_entrega)::date last_d
from cia_event
where categoria = 'Escrituras e aditamentos de debêntures' and data_entrega >= '2025-01-01';

-- Q2b the newest escrituras, where the debenture example came from
select cd_cvm, cnpj_cia, data_entrega::date, left(assunto, 120) assunto, protocolo, versao, link_download
from cia_event
where categoria = 'Escrituras e aditamentos de debêntures' and data_entrega >= '2026-09-01'
order by data_entrega desc limit 8;

-- Q3 escritura or aditamento, by assunto
select count(*) filter (where assunto ilike '%aditamento%') n_aditamento_in_assunto,
       count(*) filter (where assunto ilike '%escritura%' and assunto not ilike '%aditamento%') n_escritura_only,
       count(*) filter (where assunto not ilike '%escritura%' and assunto not ilike '%aditamento%') n_neither,
       count(*) filter (where assunto is null) n_null
from cia_event
where categoria = 'Escrituras e aditamentos de debêntures' and data_entrega >= '2025-01-01';

-- Q4 securitizadora names in the FNET register
select categoria, tipo_documento, count(*) n, min(delivered_at)::date first_d,
       max(delivered_at)::date last_d, min(fund_name) example_name
from fnet_document where fund_name ilike '%securitiz%'
group by 1, 2 order by n desc limit 15;

-- Q5 one delivery day around the CRI anúncio
select delivered_at::date d, count(*) n, min(fnet_id::bigint) min_id, max(fnet_id::bigint) max_id
from fnet_document
where delivered_at >= '2025-12-19' and delivered_at < '2025-12-24'
group by 1 order by 1;

-- Q6 the anúncio itself
select fnet_id from fnet_document where fnet_id in (1067691) limit 5;

-- Q7 the examples in the CVM securitization registry
select codigo_isin, min(data_referencia) first_ref, max(data_referencia) last_ref, count(*) n
from cvm_securit_serie
where codigo_isin in ('BRRBRACIR0R7', 'BRRBRACRISD6', 'BRRBRACRISE4', 'BRECOACRAMA5')
group by 1 order by 1;
select distinct on (codigo_isin) codigo_isin, codigo_cetip, numero_serie, data_vencimento,
       taxa_juros, situacao, classificacao_risco_atual, data_referencia
from cvm_securit_serie
where cnpj_securit = '02773542000122' and data_referencia >= '2026-06-01'
  and (taxa_juros like '%8,1125%' or taxa_juros like '%15,0905%')
order by codigo_isin, data_referencia desc limit 20;
select distinct on (codigo_isin) instrument_type, codigo_isin, codigo_cetip, numero_serie,
       data_vencimento, taxa_juros, situacao, classificacao_risco_atual, data_referencia
from cvm_securit_serie
where cnpj_securit = '10753164000143'
  and data_vencimento in ('2031-02-17', '2033-02-15', '2036-02-15')
  and data_referencia >= '2026-02-01'
order by codigo_isin, data_referencia desc limit 20;
```

Q7's last query also returns `BRECOACRACP4` ("CDI + 1,8000 a.a.", rated
"brAA(sf)", maturing 2031-02-17): another Eco CRA (`CRA0230012X`), not the
441st issue's series 1, whose rate is 109,50% of DI. The 441st's series 1 and
2 were not found by rate and maturity.

## 7. Not verified

- **Verified (Addendum, A.1):** the Fundos.NET JSON listing answers
  `paginaCertificados=true` with `tipoFundo` 5 and 6 to a third-party GET
  with no captcha, login, cookie or session, and a document downloads by id
  the same way. One day's `recordsTotal`: 136 CRI (2026-10-02), 121 CRA
  (2026-10-01 and 02 together). Still not isolated: which request headers
  the endpoint requires (the fetcher's headers are not visible).
- Whether Fundos.NET certificados carry every termo: posting rules were not
  read, only the categories the page offers.
- **Still not verified (Addendum, A.2):** the data dictionary of
  `oferta_distribuicao.csv` and `oferta_resolucao_160.csv`. The meta zip
  could not be opened by any tool here. Some column names are known from
  CVM's resource note and from third-party code (A.2); whether the files
  carry the ISIN, lastro, debtor, rating or indexer is not known.
- The terms of use of RAD, the CVM open-data portal (beyond the ODbL licence
  filter), B3, the securitizadora sites, the issuer IR pages and the SND.
  `robots.txt` was not read for any source.
- Whether `www.anbima.com.br/pt_br/termos-de-uso.htm` governs
  `data.anbima.com.br`, and whether ANBIMA Data has an open document link per
  debenture behind its app.
- The Res. 160 Art. 13 text is an LLM extraction from the PDF (Firecrawl), not
  a byte-level copy.
- RAD coverage of issuers that are not companhias abertas; the SND list's
  coverage of 2023+ issues (one query returned nothing).
- The scanned-PDF rate: the three documents read had a text layer; an
  escritura scanned without OCR would not.
- The owner's `DEB-01`, `DEB-02` and `CRI-01` were not looked up (no real
  portfolio data in this note).

## Addendum 2026-10-05 (UTC-3)

Tested 2026-10-05 from 10:00 to 10:20 UTC-3 (13:00 to 13:20 UTC). Closes two
items of section 7. Every request was a public GET made through a third-party
fetcher (Firecrawl `firecrawl_scrape`, Exa `web_fetch_exa`), because this
session's shell and built-in fetch cannot reach `fnet.bmfbovespa.com.br` or
`dados.cvm.gov.br`. The browser tool could not start (no Chromium in the
session), so no XHR was watched. No captcha was solved, bypassed or read, and
no captcha parameter was sent. The documents named below are public listings,
not positions of the owner's portfolio.

### A.1 Fundos.NET certificados: the listing answers without the captcha

Base: `https://fnet.bmfbovespa.com.br/fnet/publico/`. Each call is the
endpoint SILO's fetcher uses, plus `paginaCertificados=true`.

| Call (query string)                                                                                   | HTTP | Observed                                                                                                     |
| ----------------------------------------------------------------------------------------------------- | ---- | ------------------------------------------------------------------------------------------------------------ |
| `pesquisarGerenciadorDocumentosDados?d=1&s=0&l=10&paginaCertificados=true&tipoFundo=6&dataInicial=01/10/2026&dataFinal=02/10/2026` | 200  | JSON, `"recordsTotal":121`; first row "BSIP CRA Emissão:1 Série:3 Frigorifico Redentor 04/2017 BRBSIPCRA004", "Informe Mensal de CRA" |
| same, without `paginaCertificados`                                                                    | 200  | `{"data":[],"draw":1,"recordsFiltered":0,"recordsTotal":0}`                                                  |
| `...&l=5&paginaCertificados=true&tipoFundo=5&idCategoriaDocumento=17&dataInicial=01/09/2026&dataFinal=30/09/2026` | 200  | `"recordsTotal":35`, every row `"categoriaDocumento":"Termo de Securitização"`; first id 1306837             |
| `...&l=1&paginaCertificados=true&tipoFundo=5&dataInicial=02/10/2026&dataFinal=02/10/2026`, first try | 520  | Cloudflare page "Web server is returning an unknown error", 2026-10-05 10:08 UTC-3 (13:08 UTC)               |
| the same call, a few minutes later                                                                    | 200  | `"recordsTotal":136`; first row "BRAZILIAN SC CRI Emissão:1 Série:238 ...", "Ata da Assembleia"             |
| `downloadDocumento?id=1306837`                                                                        | 200  | `application/pdf`, 189 pages; text read: "TERMO DE SECURITIZAÇÃO DE CRÉDITOS IMOBILIÁRIOS ... 111ª ... EMISSÃO DA LEVERAGE COMPANHIA SECURITIZADORA ... CNPJ n° 48.415.978/0001-40" |

Result:

- **Verified.** The listing returns rows for CRI and CRA with no captcha,
  login, cookie or session. A month-wide window answered when filtered by
  category (35 termos), not only a day.
- The control call explains the fetcher's note "4..6 return nothing": without
  `paginaCertificados=true` the same CRA window returns 0 rows.
- **Verified.** A document downloads by id with no captcha. Firecrawl's PDF
  parser returned the text; whether this PDF has a text layer or was OCR'd by
  the parser was not checked.
- The 520 came and went on identical parameters, so it is an intermittent
  origin error, not a captcha or a header wall. Section 7's earlier 520 is
  not evidence of a header rule either.
- Rows carry the security in `descricaoFundo` (securitizadora, CRA or CRI,
  issue, series, name, ISIN) and `"cnpjFundo":null`, `"fundoOuClasse":"Certifcado ou Inf. Sec."`
  (sic). No issuer or debtor CNPJ is on the row.
- Not isolated: which headers the endpoint needs. Firecrawl sends its own
  headers, which the result does not show; a plain client with only
  `X-Requested-With`, as in `fnet_fetcher.py`, was not run.
- The captcha on the page belongs to the keyword and "Extrair Inf. Mensal"
  features (section 1.1); nothing tested here needed it.

### A.2 CVM offers dataset: columns, partly

Dataset page `https://dados.cvm.gov.br/dataset/oferta-distrib`, read
2026-10-05. The data dictionary is
`https://dados.cvm.gov.br/dados/OFERTA/DISTRIB/META/meta_oferta_distribuicao.zip`
(3,073 bytes, dated 15-Apr-2026 in the directory listing). It could not be
opened: Exa returned `CRAWL_UNEXPECTED_CONTENT_TYPE`, Firecrawl refuses
`application/zip`, the built-in fetch got `EGRESS_BLOCKED`, the shell got
`CONNECT tunnel failed, response 403`, and Parallel was rate-limited.

What CVM itself states (CKAN `package_show?id=oferta-distrib`, resource
"Ofertas de Distribuição"): "Novas colunas incluídas a partir de maio/2022:
Modalidade_Oferta; Data_Inicio_Oferta; Tipo_Societario_Emissor;
Tipo_Fundo_Investimento; Ultimo_Comunicado; Data_Comunicado. Além disso, as
colunas Modalidade_Registro_Oferta e Modalidade_Dispensa_Oferta foram
renomeadas para Modalidade_Registro e Modalidade_Dispensa_Registro". That
note is about `oferta_distribuicao.csv`.

Column names of `oferta_resolucao_160.csv` used by third-party code that
reads the CSV (read 2026-10-05; not CVM's dictionary, no descriptions):

| Column                                        | Seen in                                                                 | Relevant to                     |
| --------------------------------------------- | ----------------------------------------------------------------------- | ------------------------------- |
| `Numero_Requerimento`, `Numero_Processo`      | both in `thaissalzer/monitor_debentures` `automacao_cvm.py`; `Numero_Requerimento` also in `marcioyoshida/Signals-Competitor-Intelligence` `docs/DATA_SOURCES.md` | the offer's id; the SRE page is `web.cvm.gov.br/sre-publico-cvm/#/oferta-publica/<Numero_Requerimento>` in that code |
| `Nome_Emissor`, `CNPJ_Emissor`                | `DATA_SOURCES.md`                                                       | issuer (the securitizadora for a CRA or CRI) |
| `Valor_Mobiliario`                            | both; value "Debêntures" in the code, "Cotas de FIDC" in the doc        | security type                   |
| `Titulo_incentivado`                          | `automacao_cvm.py` (value "S")                                          | incentivized debenture flag     |
| `Nome_Lider`, `CNPJ_Lider`                    | `DATA_SOURCES.md`                                                       | lead coordinator                |
| `Data_Registro`, `Data_requerimento`, `Valor_Total_Registrado`, `Status_Requerimento`, `Tipo_Oferta`, `Rito_Requerimento` | `DATA_SOURCES.md` | dates, amount, status, rito     |

Result: **still not verified.** No source read here names a column for the
lastro, the debtor, the guarantees, the indexer, the rating or the ISIN; that
is unknown, not absent. Opening the meta zip needs a client that can reach
`dados.cvm.gov.br` (a GitHub Actions run or a local machine).
