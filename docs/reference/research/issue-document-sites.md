# Sites that publish the issue documents of CRA, CRI and debentures

Map #510 (investigator, #604, #605). Measured 2026-10-06 (UTC-3), with two Exa Agent runs (US$ 0.10 and US$ 0.50, 72 searches).
What was read: public pages only, through Exa's page reader. Nothing was written to SILO, and no page was
signed into. The owner asked for the list on 2026-10-06, naming the "banco de documentos" of the investment
banking area of banks (BTG's "Banco de Emissões" as the example).

## Answer

Twenty-six official pages from 23 institutions were opened: 7 investment-banking pages (BR Partners, Bradesco BBI,
Santander, ABC Brasil, Banco BV, Itaú BBA, Banco Pine), 3 broker pages (XP, Banco Inter, Terra), 8 securitization
companies (Opea, Eco, Gaia, Habitasec, RB Capital, Bari, Travessia, Canal), 4 fiduciary agents (Oliveira Trust,
Vórtx, Simplific Pavarini, Pentágono) and B3's CRA prospectus archive. Twenty-four read without a login; Banco Inter
and Pentágono came back `unknown` (readable text, but whether a login or captcha gates the list was not established).

Three things the table does not say loudly enough:

- **BTG was not found.** The run opened btgpactual.com but did not reach the "Banco de Emissões" the owner
  described, and the more-than-100-issues claim is unverified. The BTG entries in
  `src/portfolio/rules/investigator/coordinators.yaml` were approved by the owner from his own knowledge of the site, not from this note.
- **"public" means the page text was readable without signing in.** It does not mean every download link is
  open, and some gateways show only titles or links, so they need a browser check before an agent depends on them.
- **No page proved that its search takes a CETIP/B3 code.** Several show the ISIN or the IF code on the issue
  page; only Oliveira Trust (issuer or asset code) and Canal (identifier filters) say they filter by one. Matching
  to a position still goes through `api.portfolio_instruments`, not through these sites' search.

## Pages read

| Institution | Kind | Access | Document list | Section | What it lists | Lookup by |
| --- | --- | --- | --- | --- | --- | --- |
| XP Investimentos CCTVM S.A. | broker | public | https://ofertaspublicas.xpi.com.br/ | Ofertas Públicas | CRA, CRI, debêntures, notas comerciais; Prospecto, Lâmina, Aviso ao Mercado, Anúncio de Início e de Encerramento, Comunicado ao Mercado | by offering title only |
| BR Partners Banco de Investimento S.A. | bank_ib | public | https://www.brpartners.com.br/pt-BR/transactions/public-offering.html | Ofertas Públicas | CRI, FIDC, notas comerciais, FII; same document types | by offering title only |
| Opea Securitizadora S.A. | securitizadora | public | https://app.opea.com.br/pt/emissoes/26C4077795 | Documentos da Emissão | CRI; Termo de Securitização, Anúncios, Atas, Memória de Cálculo, Informe Mensal CVM | page shows ISIN and IF code |
| Banco Bradesco BBI S/A | bank_ib | public | https://bradescobbi.com.br/en/public-offers | Public offers | information and documents about available offers | not established |
| Santander | bank_ib | public | https://www.santander.com.br/assessoria-financeira-e-mercado-de-capitais/ofertas-publicas/ofertas-em-andamento | Ofertas em andamento | debêntures, CRI, CRA, FIDC, ações, notas comerciais, FII; prospectuses; market notices; market communications; offer announcements; closing announcements | not established |
| Banco ABC Brasil | bank_ib | public | https://www.abcbrasil.com.br/abc-corporate/investment-banking/mercado-de-capitais-dcm/ofertas-de-renda-fixa/ | Ofertas de renda fixa | debêntures, CRI, CRA, notas comerciais escriturais; offer documents (individual offer entries) | not established |
| Banco Votorantim / banco BV | bank_ib | public | https://www.bv.com.br/institucional/ofertas-publicas | Ofertas Públicas / Ofertas em andamento | CRI, CRA, debêntures; anúncio de encerramento; anúncio de início; aviso ao mercado; comunicado ao mercado; prospecto preliminar; prospecto definitivo; lâmina | not established |
| Banco Inter | broker | unknown | https://inter.co/pra-voce/investimentos/ofertas-publicas/cra-cereal-406a-emissao/ | CRA Cereal - 406ª Emissão | CRA; Prospecto Preliminar; Lâmina da Oferta; Aviso ao Mercado; Material Publicitário | not established |
| Eco Securitizadora de Direitos Creditórios do Agronegócio S.A. | securitizadora | public | https://ecoagro.agr.br/emissoes-integra/211 | Documentos da Oferta | CRA; Atas de Assembleias; Convocação de Assembleia; Demonstrações Financeiras; Relatórios; Termos de Securitização | ISIN (displayed; search not verified); CETIP (displayed; search not verified); número da emissão (displayed; search not verified) |
| Gaia Impacto Securitizadora S.A. (Grupo Gaia) | securitizadora | public | https://emissoes.grupogaia.com.br/ | Operações e Emissões | not established on the page | not established |
| Gaia Impacto Securitizadora S.A | securitizadora | public | https://emissoes.grupogaia.com.br/cra-taboa-ii/ | Documentos da Operação / Arquivos da Operação | CRA; Termo de Securitização; Aditamentos; Anúncio de Inicio da Oferta; Anúncio de Encerramento; Informe Mensal; Demonstrações Financeiras; Relatório Anual; Edital; Ata de Assembleia | ISIN (displayed; search not verified) |
| Habitasec Securitizadora S.A. | securitizadora | public | https://habitasec.com.br/lista-de-emissoes/ | Emissões | CRI, CRA;  | ISIN (displayed; search not verified); IF B3 (displayed; search not verified) |
| RB Capital Companhia de Securitização | securitizadora | public | https://www.rbinvestimentos.com/produtos/ofertas-publicas/ | Ofertas Públicas | CRI, CRA, Debêntures, Cotas de fundos, FIP, FII, FIAGRO, IPO, CDCA; Anúncio de Início; Anúncio de Encerramento; Prospecto Definitivo; Comunicado ao Mercado; Material Publicitário | not established |
| Bari Securitizadora S.A. | securitizadora | public | https://barisec.com.br/ | Emissões de CRIs | CRI; Emissões (operation pages) | B3 IF (displayed; search not verified) |
| Oliveira Trust Distribuidora de Títulos e Valores Mobiliários S.A. | fiduciary_agent | public | https://www.oliveiratrust.com.br/investidor/ativos | Lista de ativos | CRI, CRA, Debêntures, FIDCs; Relatórios Anuais; Informes Mensais FIDCs; documentos | not established |
| Oliveira Trust | fiduciary_agent | public | https://api-site.oliveiratrust.com.br/fiduciario/?item1=Investidor&item2=CRA | CRA | CRA; downloads | emissor ou código do ativo; ISIN (displayed; search not verified) |
| Vórtx | fiduciary_agent | public | https://www.vortx.com.br/investidor/dcm | Títulos de Dívida | CRA, CRI, Debêntures, outros títulos;  | Cód IF (displayed; search not verified) |
| Vórtx | fiduciary_agent | public | https://www.vortx.com.br/investidor/dcm/operacao?id=91320 | ISEC - COPAGRIL - CRI - Emissão 4 / Série 205 | CRI; Documentos; Relatórios Anuais; Relatórios de Garantias; Assembleias; Fatos Relevantes; Outras Emissões; Obrigações | Código ISIN (exibido; pesquisa não verificada) |
| Simplific Pavarini | fiduciary_agent | public | https://www.simplificpavarini.com.br/006/debentures.php | Debêntures / issue list | CRI, Debêntures; Issue/asset records | CETIP/B3 IF (displayed; search not verified) |
| Itaú BBA | bank_ib | public | https://www.itau.com.br/itaubba-pt/ofertas-publicas | Ofertas Públicas | ofertas públicas | not established |
| Banco Pine | bank_ib | public | https://www.pine.com/relacao-com-investidores/outras-informacoes/pine-dtvm/ | Ofertas Públicas coordenadas pela Pine Investimentos DTVM | debêntures, FII; Manual de Procedimento de Ofertas Públicas; prospecto; protocolo; comunicado ao mercado; anúncio de início; anúncio de encerramento | not established |
| TRAVESSIA SECURITIZADORA S.A. | securitizadora | public | https://www.grupotravessia.com/emissoes/operacao/atlas_21_2/ | Documentos da oferta | CRA; Termo de Securitização; Anúncio de Início; Anúncio de Encerramento; Relatório do Agente Fiduciário; Demonstrações Financeiras; Edital; Atas/Termos de AGD | CETIP/B3 IF (displayed; search not verified); ISIN (displayed; search not verified) |
| Canal Companhia de Securitização S.A. | securitizadora | public | https://www.canalsecuritizadora.com.br/emissoes | Emissões | CRI, CRA, CR, debêntures securitizadas; Documentos de emissão/oferta | CETIP/B3 IF; ISIN |
| Pentágono S.A. Distribuidora de Títulos e Valores Mobiliários | fiduciary_agent | unknown | https://ebonds.pentagonotrustee.com.br/ | E-Bonds / informações públicas relativas ao mercado de capitais | Debêntures, Notas promissórias, Letras financeiras, Certificados de recebíveis imobiliários, Certificados de recebíveis do agronegócio; Informações públicas e atualizações sobre ativos | Código do ativo (exibido; busca não verificada) |
| B3 | other | public | https://www.b3.com.br/pt_br/produtos-e-servicos/negociacao/renda-fixa/cra/prospectos/ | CRA — Prospectos (S_Prosp) | CRA; Prospecto preliminar; Prospecto definitivo; Anúncio de Inicio de Distribuição | not established |
| Terra Investimentos | broker | public | https://www.terrainvestimentos.com.br/ofertas-publicas/ | Ofertas Públicas | debêntures, cotas de fundo de investimento imobiliário, cotas de fundo de investimento em direitos creditórios, certificados de recebíveis imobiliários; prospecto; regulamento; documentos de ofertas públicas | not established |

## Not verified

These were looked for and not confirmed. "Not verified" is not proof that the page does not exist.

- BTG Pactual: Opened the official institutional site, but did not reach the claimed Banco de Emissões or verify the >100-issues claim.
- Banco do Brasil Investimentos: Opened official Oferta Pública de Ativos page; it exposed only a title, not readable issue-document entries.
- Safra: Opened Ofertas Públicas page; it describes CRI, CRA and debentures but no issue-by-issue document list was exposed.
- Genial: The official list link was identified, but the list itself was not retrievable; login requirement was not established.
- Daycoval: Opened DCM Ofertas Públicas URL; returned portal/browser shell rather than readable document entries.
- Vinci: No official issue-document list was verified.
- Modal: Official pages reviewed were explanatory, not issue-document lists.
- C6: Official capital-markets educational pages reviewed did not provide issue-document lists.
- Sicredi: Opened compliance documents page, not CRA/CRI/debenture issuance documents.
- Sicoob: Official manuals and auction material found; no qualifying issue-document list verified.
- Caixa: Opened official/RI pages, but no qualifying issue-document list was exposed.
- BNDES: Opened capital-markets service page; coordination service descriptions are not a document list.
- Virgo: Opened official site, but no exact readable issuance-document list was verified.
- True Securities: Legacy site points to a different current operator; no separate official list verified under this name.
- Brazil Realty: No official opened issue-document list verified.
- Cibrasec: Documents appear in the B3 CRA archive; a separate official institutional list was not verified.
- Ápice: No official opened issue-document list verified.
- Isec: Documents appear in the B3 CRA archive; a separate official institutional list was not verified.
- Planner: Official page describes fiduciary services; no opened public issue-document list verified.
- Rio Bravo: Offer PDFs found, but no qualifying debt issue-document list verified.
- Cashme: No official opened issue-document list verified.
- VERT: Opened institutional regulatory-document gateway, but it is not itself a list of issue documents; CRA prospectuses are present in B3 archive.
- B3 CRI/debêntures document tabs: CRI product and general public-offering pages were opened, but exact instrument-specific document tabs/lists were not verified. Only the CRA archive is included. ANBIMA coordinator-registration coverage was not independently established.

## XP's legal name, for the coordinator entry

`XP Investimentos Corretora de Câmbio, Títulos e Valores Mobiliários S.A.` (XP Investimentos CCTVM S.A.),
CNPJ 02.332.886/0001-04. Three sources agree: XP's own page (conteudos.xpi.com.br, "A XP Investimentos CCTVM S/A,
inscrita sob o CNPJ: 02.332.886/0001-04"), a document it filed on Fundos.NET (id 31389, same CNPJ in the
administrator's own words) and ANBIMA's institution profile. The `ofertaspublicas.xpi.com.br` page itself shows no CNPJ.
The XP entry in `coordinators.yaml` stays `proposta`: approving it is the owner's call (Q39).

## Caveats on the data

- Bradesco BBI's CNPJ came back as `06.271.464.0073-93`, which is not a valid 14-digit CNPJ shape (probably
  `06.271.464/0073-93`). It was not used anywhere. Nothing in this note's CNPJ column was checked except XP's.
- Exa's `lookup_by` entries marked "displayed" mean an identifier appears on the issue page, not that the site can be searched by it.
- Not a census: the coordinator registry of ANBIMA and the B3 CRI and debenture document tabs were not covered.

## Sources

Every row's page URL is in the table; Exa's evidence quote for each is in the run output
(`agent_run_e1dd3f04d84d422096ce28108e24b1d3`, `agent_run_114c4a764c184c01bd206f02490b288f`).
