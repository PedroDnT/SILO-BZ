# PGBL and VGBL: what public data shows about the plan, its loading fee, its FIE and the tax regime

Wayfinder research ticket #612, part of map #510 (portfolio-diagnosis demo).
Measured 2026-10-05 09:15 to 09:40 UTC-3 (12:15 to 12:40 UTC). Web pages were
read through Firecrawl, Parallel Search and Exa, and the Open Insurance
specifications were downloaded from `raw.githubusercontent.com`. Fifteen
read-only, bounded SELECTs (and one that errored on a wrong column name) ran against the production Supabase project
`zcjbtpxuhdekpwcxmepn` (section 5). Nothing was written to any database. No
client statement or portfolio was read. The public example in section 6 came
from a web search, not from any statement.

## Answer

A pension line has five layers. The table shows where each one is public.

| Layer                                  | SUSEP open data                                                                                                                          | Open Insurance phase 1 (open data)                                                                                                         | CVM (and SILO)                                                                                                          | Broker statement (BTG)                                                                                                                          |
| -------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| Plan (product, processo SUSEP)         | Yes. The Olinda `produtos` service and the Consulta Pública give the insurer, its CNPJ, the processo number, the ramo and the regulation | Yes. `susepProcessNumber` and the product type (`PGBL`, `VGBL`, ...)                                                                       | No                                                                                                                      | The plan type (`PGBL` or `VGBL`) is in the table heading. The certificate is printed but the reader drops it                                    |
| Loading fee (carregamento)             | Not in either service's fields. It is in the plan's regulation, a document per processo                                                  | Yes, as a range per product: `loadingAntecipated` and `loadingLate`, each with `minValue` and `maxValue` in %                              | No                                                                                                                      | Not read. "plan metadata" is skipped                                                                                                            |
| FIE (the plan's fund)                  | No. The SES fund tables hold only a provision total per insurer and month                                                                | Yes. `investmentFunds[].cnpjNumber`, with `maximumAdministrationFee`, for each product                                                     | Yes, as an ordinary fund keyed by CNPJ: Extrato, informe diário, CDA, registry. But no CVM column says "this is an FIE" | Yes. Each pension row prints the fund's CNPJ                                                                                                    |
| Funds inside the FIE                   | No                                                                                                                                       | No                                                                                                                                         | Yes. CDA block 2 (`cvm_fi_cda_cotas`) lists them, by CNPJ, each month                                                   | No                                                                                                                                              |
| Tax regime (progressive or regressive) | No                                                                                                                                       | No. It is a field of the **contract**, `taxRegime: [PROGRESSIVO, REGRESSIVO]`, in the phase-2 API, which "Requer consentimento do cliente" | No. `Tributacao_Longo_Prazo` in the CVM registry is the fund's own income-tax treatment, not the plan's                 | Not read. A heading "Previdência Individual - Posições abertas por alíquota" exists and is skipped. Whether it shows the regime is not verified |

In one line: **the plan-to-FIE link is public only from the insurer's own
disclosure.** That disclosure is its Open Insurance phase-1 product data, which
gives the FIE's CNPJ under the processo number, or its product sheet. The broker
statement already prints the FIE's CNPJ, and that is the link the engine uses
today. SUSEP's own open data identifies the plan (processo, insurer, ramo) but
not its loading fee or its FIE. The tax regime is the client's choice for each
contract. It is public nowhere and can only come from the client: their
certificate, or a consented phase-2 call. When the regime is unknown, the report
shows both scenarios (owner, Q13.1, 2026-10-05).

Corrected in the addendum of 2026-10-05: SUSEP does publish the carregamento
and the FIE CNPJ for a plan on sale, as fields of its PGBL/VGBL plan search
(`Plano.aspx/Detalhar`), and the Open Insurance phase-1 endpoint answers live
for XP, Icatu, Bradesco and Caixa. The table above says otherwise for SUSEP.

Recommendation (no build in this ticket): keep the CNPJ printed on the statement
as the FIE key, and keep reading the FIE as a fund through the existing
`portfolio_*` functions. Show the carregamento only when the client supplies it.
Do not take it from a product range. Label the regime "escolha do cliente; não
informado" with both scenarios. Two follow-ups are worth tickets, if the owner
wants them: (a) measure whether the BTG "Posições abertas por alíquota" table
shows the regime; (b) try one insurer's live phase-1 `/life-pension` endpoint for
the carregamento range and the FIE list.

## 1. Sources

| Claim                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              | Source                                                                                                                                                                                                                                            | Accessed                                                                                                    |
| -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| SUSEP's open-data plan (PDA 2026-2028, dated "Setembro / 2026") lists "Consulta de Produtos": "Informações atualizadas relativas aos produtos de seguros, previdência e capitalização comercializados pelas empresas supervisionadas pela SUSEP", "Tempo real", catalogued 12/2019. It also lists "Sistema de Estatísticas da Susep – SES (BDESTATIST)": "contribuições, benefícios, resgates e provisões técnicas de previdência complementar aberta/produtos de acumulação financeira", "Semanal"                                                                                                                                                                                                                                                                                                                                                                                                                                                | <https://www.gov.br/susep/pt-br/arquivos/arquivos-licitacoes-contratos/2026_09_set_pda_2026-2028.pdf/@@display-file/file>, linked from <https://www.gov.br/susep/pt-br/acesso-a-informacao/dados-abertos> (page "Modificado em 30/09/2026 13:40") | 2026-10-05 about 09:20 UTC-3 (12:20 UTC), Firecrawl, live                                                   |
| Olinda `produtos` v1 (OData) returns exactly six fields: `tipoproduto`, `entnome`, `cnpj` (the insurer's), `numeroprocesso` ("Número do processo registrado na Susep ... As condições contratuais/regulamentos estão disponíveis para consulta no sítio da Susep"), `ramo` ("... de previdência (por assunto) ..."), `subramo`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     | <https://dados.susep.gov.br/olinda/servico/produtos/versao/v1/documentacao>                                                                                                                                                                       | 2026-10-05 about 09:25 UTC-3 (12:25 UTC), Firecrawl, live                                                   |
| Consulta Pública de Produtos: "Confira aqui se as Condições Contratuais/Regulamento do seu seguro, plano de previdência complementar aberta ou título de capitalização contratados são registrados na SUSEP." "As Condições Contratuais/Regulamento são identificadas pelo número do processo SUSEP de seu registro". Lookup by "Nº Processo"                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      | <https://www2.susep.gov.br/safe/menumercado/REP2/Produto.aspx/Consultar>                                                                                                                                                                          | 2026-10-05 about 09:35 UTC-3 (12:35 UTC), Exa and Parallel                                                  |
| SES: product queries "PGBL: Provisão Matemática de Benefícios a Conceder ( Fundos )" and the VGBL one. "Base de Dados do SES, atualizada até 202607 (gerada em 05/10/2026 00:59:58)". "Os dados apresentados foram extraídos diretamente dos Formulários de Informações Periódicas (FIP)". "atualizadas semanalmente"                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              | <https://www2.susep.gov.br/menuestatistica/SES/principal.aspx>                                                                                                                                                                                    | 2026-10-05 about 09:28 UTC-3 (12:28 UTC), Firecrawl, live                                                   |
| SES table documentation: `ses_pgbl_fundos.csv` and `Ses_vgbl_fundos.csv` each have three columns: `coenti` "Código da Empresa", `damesano` "Ano e mês da informação", `fundos` "Valor da Provisão"                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 | <https://www2.susep.gov.br/menuestatistica/SES/download/Documentacao_das_tabelas.rtf>                                                                                                                                                             | 2026-10-05 about 09:29 UTC-3 (12:29 UTC), Firecrawl with an LLM extraction (not a full read; see section 7) |
| Open Insurance phase 1, `life-pension` v3.0.0: "APIs Open Data do Open Insurance Brasil"; "API de informações de Planos de Previdência e Seguros de Pessoas ambos com cobertura por sobrevivência". Path `/life-pension` under `/open-insurance/products-services/v3`, no security scheme. Fields: `type` enum including `PGBL` and `VGBL`; `susepProcessNumber`; `investmentFunds` "Lista com as informações do(s) Fundo(s) de Investimento(s) disponíveis para o período de diferimento/acumulação ou de concessão", with `cnpjNumber`, `companyName`, `maximumAdministrationFee` "Taxa Máxima de Administração – em %"; `loadingAntecipated` "Percentual de carregamento cobrado quando do pagamento do prêmio/contribuição. Para coletivos Valor máximo"; `loadingLate` "Percentual de taxa de carregamento cobrado quando da efetivação de resgate ou portabilidade"; each with `minValue` and `maxValue`. The schema has no tax-regime field | <https://raw.githubusercontent.com/br-openinsurance/areadesenvolvedor/main/docs/specs/fase-1/life-pension/life-pension-v3.0.0.yaml> (and `docs/specs/current/life-pension.yaml`, v2.0.0, same fields)                                             | 2026-10-05 about 09:30 UTC-3 (12:30 UTC), `curl`, live                                                      |
| Open Insurance phase 2, `insurance-life-pension` v1.5.0: "Requer consentimento do cliente para todos os `endpoints`." Contract field `taxRegime`, "Regime Tributário", `enum: [PROGRESSIVO, REGRESSIVO]`. `FIE[].FIECNPJ` "CNPJ do FIE". Loading charged as an amount (`chargedInAdvanceAmount` "Valor do carregamento cobrado de forma antecipada", `postedChargedAmount`)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        | <https://raw.githubusercontent.com/br-openinsurance/areadesenvolvedor/main/docs/specs/current/insurance-life-pension.yaml>                                                                                                                        | same                                                                                                        |
| Public example: XP's sheet for "XP Seg Superprev FIM", "PGBL/VGBL", "35.420.569/0001-90", "Maio\|2026", "Processo SUSEP PGBL ... 15414.632689/2019-60", "Processo SUSEP VGBL 15414.632690/2019-94", "Taxa Adm. (%)¹ ... 0,60%" ("¹ Taxa de administração efetiva"), "Gestor XP Vida e Previdência", and: "Os planos de previdência apresentam tributação no resgate ou recebimento de renda, conforme sua escolha na contratação: tributação progressiva compensável ou tributação regressiva definitiva."                                                                                                                                                                                                                                                                                                                                                                                                                                         | <https://fundos.xpi.com.br/docs-fundos/Caracteristica_35420569000190_v181.pdf>                                                                                                                                                                    | 2026-10-05 about 09:33 UTC-3 (12:33 UTC), Exa                                                               |
| The BTG statement reader: "Previdência Individual/Interna - Posição - <cert>/PGBL": `Fundo, CNPJ, Data, Quantidade, Cotação, Saldo Bruto`. Each row becomes a `fundo` with the CNPJ as `codigo`. "The certificate is never kept or printed." "plan metadata, 'Posições abertas por alíquota'" are skipped                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          | `docs/reference/portfolio/statement-pdf.md` in this repository                                                                                                                                                                                    | read 2026-10-05                                                                                             |

## 2. Method

1. Read SUSEP's open-data page and its newest plan (PDA 2026-2028) to list what
   SUSEP publishes, then read the documentation of each candidate: the Olinda
   `produtos` service, the Consulta Pública, and the SES download.
2. The PDA does not name the Open Insurance APIs, but SUSEP's Open Insurance
   rules make insurers publish product data openly (phase 1). The specification
   YAMLs are in the public repository `br-openinsurance/areadesenvolvedor`. Both
   the phase-1 `life-pension` (open) and the phase-2 `insurance-life-pension`
   (consented) specifications were read field by field.
3. In SILO, counted the funds whose latest Extrato has an ANBIMA class starting
   `PREVIDÊNCIA`, and how many of those report one quotaholder in the informe
   diário (an FIE's only quotaholder is the insurer). Checked which registry
   fields could flag an FIE.
4. Took one public FIE from a web search for an insurer's product sheet. Read it
   in SILO (Extrato, registry, informe diário, CDA block 2).

The shell's proxy refused `www2.susep.gov.br`, `dados.susep.gov.br`,
`br-openinsurance.github.io`, `fundos.xpi.com.br` and
`data.directory.opinbrasil.com.br`. Those were read through the search tools.

## 3. SUSEP

- **Plan identity is open.** Olinda `produtos` (OData: JSON, CSV or XML through
  `$format`) has one row per product: insurer, insurer CNPJ, processo, ramo,
  subramo. The Consulta Pública opens the regulation (Condições
  Contratuais/Regulamento) for a processo number. The regulation is where the
  carregamento is written, as a document, not a field. Reading it is a per-plan
  PDF read; it was not done here. (Corrected in the addendum of 2026-10-05:
  SUSEP's PGBL/VGBL plan search shows the carregamento and the FIE CNPJ as
  fields, for plans on sale.)
- **No FIE in SUSEP's open data.** Olinda has no fund field. (Corrected in
  the addendum of 2026-10-05: the PGBL/VGBL plan search lists the FIE CNPJ.) The SES fund tables
  (`ses_pgbl_fundos`, `ses_vgbl_fundos`) give the provision (PMBaC) total per
  insurer code and month, with no fund identifier. SES is a weekly zip of CSVs
  taken from the FIP forms, and its base ran to 2026-07 when read.
- **No tax regime anywhere in SUSEP's open data.** It belongs to the contract,
  not to the product.

## 4. Open Insurance

- **Phase 1 is open product data, served by each insurer** at
  `<insurer base>/open-insurance/products-services/v3/life-pension` (paged JSON,
  no consent). For each product it gives the processo, the type (PGBL, VGBL,
  ...), the **carregamento range** (`loadingAntecipated` and `loadingLate`, each
  with a min and max in %), and **the FIEs the product can invest in**, by CNPJ,
  with a maximum administration fee. This is the only public place found that
  links a processo to its FIE CNPJ in a machine-readable form.
- **But the range is not the client's fee.** The product gives a min and max.
  The rate a given contract pays is in the contract. "Para coletivos Valor
  máximo" makes the same point for group plans.
- **Phase 2 is the client's contract, behind consent.** It has `taxRegime`
  (PROGRESSIVO or REGRESSIVO), the FIE CNPJ and balance per contract, and the
  loading actually charged as an amount. SILO has no consent flow and the map
  rules out Open Finance (Pluggy, Belvo), so phase 2 is out of scope.
- **Not verified:** that a given insurer serves phase 1 live, and what its data
  holds. The participants directory
  (<https://data.directory.opinbrasil.com.br/participants>) was reachable through
  Exa, but only a truncated first page came back. No insurer's `/life-pension`
  endpoint was called. (Done in the addendum of 2026-10-05.)

## 5. CVM, in SILO

An FIE is an ordinary CVM fund with its own CNPJ. Everything SILO holds for a
fund (Extrato, lâmina, informe diário, CDA, registry) applies to it. What CVM
does not publish is a flag saying "this fund is an FIE", or which plan it serves.

Latest Extrato rows with a pension ANBIMA class (any status, newest `dt_comptc`
2026-10-02):

```sql
SELECT count(*) AS n_prev,
 count(*) FILTER (WHERE tp_fundo_classe='FI') AS n_fi,
 count(*) FILTER (WHERE tp_fundo_classe='CLASSES - FIF') AS n_fif,
 count(*) FILTER (WHERE denom_social ILIKE '%PREVID%') AS name_prev,
 count(*) FILTER (WHERE denom_social ~* '\mFIE\M|INVESTIMENTO ESPECIALIZADO|ESPECIALMENTE CONSTITU') AS name_fie,
 count(*) FILTER (WHERE taxa_adm > 0 AND taxa_adm <= 5) AS fee_plausible,
 count(*) FILTER (WHERE taxa_adm = 0) AS fee_zero,
 percentile_cont(0.5) WITHIN GROUP (ORDER BY taxa_adm) FILTER (WHERE taxa_adm > 0 AND taxa_adm <= 5) AS median_fee,
 max(dt_comptc) AS newest
FROM vw_fi_extrato_latest WHERE classe_anbima ILIKE 'PREVID%';
-- 5090 | 3292 | 1798 | 1701 | 257 | 4357 | 726 | 1 | 2026-10-02
```

- 5,090 rows: 3,292 `FI` and 1,798 `CLASSES - FIF`. Only 1,701 have "PREVID" in
  the name and 257 an FIE-like name, so the name is not a key.
- `TAXA_ADM`: 4,357 in (0, 5], 726 exactly 0 (read as "not informed", as in
  #524), median 1.0 among the plausible.
- 27 class labels, from `PREVIDÊNCIA - MULTIMERCADOS LIVRE` (2,776) down
  (`SELECT classe_anbima, count(*) ... GROUP BY 1`).

`publico_alvo` (`SELECT publico_alvo, count(*) FROM vw_fi_extrato_latest WHERE
classe_anbima ILIKE 'PREVID%' GROUP BY 1 ORDER BY 2 DESC LIMIT 10`):
`PREVIDENCIÁRIO` 2,880, `INVESTIDORES PROFISSIONAIS` 1,716, `PÚBLICO EM GERAL`
455, `INVESTIDORES QUALIFICADOS` 39. The pension class covers more than FIEs:
it also holds the funds FIEs invest in, which are usually filed as
professional-investor funds.

One quotaholder, the FIE's signature, in the last informe diário of 2026-09-24
to 2026-09-30:

```sql
SELECT count(*) AS n_prev_reporting, count(*) FILTER (WHERE d.nr_cotst = 1) AS one_quotaholder, count(*) FILTER (WHERE d.nr_cotst <= 5) AS le5
FROM vw_fi_extrato_latest e JOIN LATERAL (SELECT nr_cotst FROM cvm_fi_diario f WHERE f.cnpj = e.cnpj AND f.dt_comptc BETWEEN '2026-09-24' AND '2026-09-30' ORDER BY f.dt_comptc DESC LIMIT 1) d ON true
WHERE e.classe_anbima ILIKE 'PREVID%';
-- 3645 | 2927 | 3372
```

2,927 of the 3,645 reporting (80.3%) have exactly one quotaholder. That is a
proxy for "FIE or a fund held by one FIE", not a definition.

The CVM 175 class registry has `Exclusivo` and `Tributacao_Longo_Prazo` in
`raw`, and no FIE field (`SELECT c.raw->>'Exclusivo', c.raw->>'Tributacao_Longo_Prazo',
count(*) FROM cvm_registro_classe c WHERE c.classificacao_anbima ILIKE 'Previd%'
GROUP BY 1,2`): of 4,604 pension classes, 3,638 are `Exclusivo = S`, and
`Tributacao_Longo_Prazo` is mostly `N/A`. That field is the fund's own IR
treatment. It says nothing about the plan holder's progressive or regressive
choice. `Publico_Alvo` there is `Profissional` for 4,509 of 4,604.

## 6. Public example: XP Seg Superprev FIM (CNPJ 35.420.569/0001-90)

This example came from a web search for an insurer's product sheet. It is not
from any client.

| Layer          | What is public                                                                                                                                                                                                                                                                                                | Where                                                                                     |
| -------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------- |
| Plan           | PGBL processo 15414.632689/2019-60, VGBL processo 15414.632690/2019-94; insurer XP Vida e Previdência S.A., CNPJ 29.408.732/0001-05                                                                                                                                                                           | XP's product sheet, "Maio\|2026"                                                          |
| Loading fee    | The sheet has a "Taxa de carregamento" cell. In the extracted text "Não há" sits between "Liquidação de Resgate" and "Taxa de carregamento", so which cell it belongs to is not established                                                                                                                   | same; not verified                                                                        |
| FIE            | `XP SEGUROS SUPERPREV FUNDO DE INVESTIMENTO FINANCEIRO MULTIMERCADO - RESPONSABILIDADE LIMITADA`, `CLASSES - FIF`, `PREVIDÊNCIA - MULTIMERCADOS LIVRE`, `INVESTIDORES PROFISSIONAIS`; registry `Exclusivo = S`, `Publico_Alvo = Profissional`; informe diário 2026-09-30: PL R$509,833,632.61, `nr_cotst = 1` | SILO: `vw_fi_extrato_latest`, `cvm_fund_registry`, `cvm_registro_classe`, `cvm_fi_diario` |
| Fees, as filed | Extrato `TAXA_ADM` 2.6 (`DT_COMPTC` 2025-06-13); the sheet prints "0,60%" as "Taxa de administração efetiva". Shown side by side and not reconciled. The two may measure different things (a maximum against an effective rate), and that is not verified                                                     | SILO; XP's sheet                                                                          |
| Funds inside   | CDA block 2, 2026-08: 29 funds held, R$505.9 million                                                                                                                                                                                                                                                          | SILO `cvm_fi_cda_cotas`                                                                   |
| Tax regime     | Not public: "conforme sua escolha na contratação: tributação progressiva compensável ou tributação regressiva definitiva"                                                                                                                                                                                     | XP's sheet                                                                                |

Queries (each re-runnable):

```sql
SELECT cnpj, denom_social, tp_fundo_classe, classe_anbima, publico_alvo, taxa_adm, taxa_perfm, dt_comptc
FROM vw_fi_extrato_latest WHERE cnpj = '35420569000190';
SELECT r.cnpj_classe, r.denominacao_social, r.tipo_classe, r.classificacao_anbima, r.classe_cotas
FROM cvm_registro_classe r WHERE r.cnpj_classe = '35420569000190' LIMIT 5;
SELECT entity_type, raw->>'Exclusivo' AS exclusivo, raw->>'Publico_Alvo' AS publico_alvo
FROM cvm_fund_registry WHERE cnpj='35420569000190' LIMIT 5;
SELECT dt_comptc, vl_patrim_liq, nr_cotst FROM cvm_fi_diario
WHERE cnpj = '35420569000190' AND dt_comptc >= '2026-09-01' ORDER BY dt_comptc DESC LIMIT 1;
SELECT period, count(*) AS n_rows, count(DISTINCT cnpj_cota) AS n_funds_held, round(sum(vl_merc_pos_final)/1e6,1) AS rs_mm
FROM cvm_fi_cda_cotas WHERE cnpj = '35420569000190'
 AND period = (SELECT max(period) FROM cvm_fi_cda_cotas WHERE cnpj = '35420569000190') GROUP BY period;
```

The registry has `classe_cotas = false` for this class, although XP calls it "um
fundo de fundos de previdência (FoF)". That value is as filed.

## 7. Not verified

Status after the addendum of 2026-10-05 (A1 to A6 below). The original wording
of each item is kept; the status follows it.

1. That any insurer serves the phase-1 `/life-pension` endpoint live, and whether
   the XP processos above appear there with this FIE's CNPJ and a carregamento
   range. **Closed (A2, A3).** XP, Icatu, Bradesco and Caixa answered HTTP 200
   with `loadingAntecipated`, `loadingLate` and `investmentFunds[].cnpjNumber`;
   Brasilprev answered HTTP 400. The XP Superprev processo was not on the one XP
   page read (10 of 625 records), but SUSEP's plan page links that processo to
   this FIE's CNPJ, with the carregamento (A3).
2. The SES documentation was read through an LLM extraction, not line by line.
   Only the three columns of the two fund tables are claimed. **Open.** Not
   re-read.
3. Which cell "Não há" belongs to on XP's sheet: Taxa de carregamento,
   Liquidação de Resgate or Taxa Perf. **Closed for the plan (A3), open for the
   sheet.** SUSEP gives the PGBL processo 15414.632689/2019-60 a carregamento of
   0,00 and 0,00. The sheet itself was not re-read.
4. Why the Extrato's 2.6 and the sheet's 0,60% differ. **Open (A4).** There are
   now three values for this FIE: 2.6 (Extrato), 0,60 (XP's fund page, "ao ano")
   and 0 (XP's phase-1 `maximumAdministrationFee`).
5. Whether the BTG heading "Previdência Individual - Posições abertas por
   alíquota" shows the regime (a regressive table by holding period) or only the
   rates. It is skipped today. Measuring it needs the owner's local runner.
   **Open.** Unchanged.
6. The Olinda `produtos` rows themselves. Only the field documentation was read;
   the shell could not reach `dados.susep.gov.br`. **Open (A5).** The service
   root answers; both collection queries returned HTTP 500.
7. Whether the regulation PDFs behind the Consulta Pública state the carregamento
   in a uniform place that could be read automatically. **Closed for plans on
   sale (A3).** SUSEP's PGBL/VGBL plan search shows the carregamento as fields
   ("Percentual 1 (até 10%)"), so no PDF read is needed for those. Plans no longer
   sold were not checked.
8. Whether SUSEP rules require the FIE's CNPJ in the participant's certificate or
   statement. No regulation was read for this note. **Closed (A6).** Circular
   SUSEP 698/2024 requires "denominação e CNPJ do(s) FIE(s) vinculado(s) ao
   plano" daily (art. 78, II) and in the yearly statement (art. 79, III).

## Addendum 2026-10-05 (UTC-3)

Measured 2026-10-05 10:00 to 10:20 UTC-3 (13:00 to 13:20 UTC). Endpoints were
called through Firecrawl with `maxAge: 0` (a live fetch, which reports the HTTP
status) and, where noted, through Exa, which reports no status. The shell's proxy
refused `data.directory.opinbrasil.com.br`, `dados.susep.gov.br` and
`insurance-openfinance.xpi.com.br` (CONNECT 403). Only public product data and
public regulation were read: no client statement, contract or consented API. No
SQL ran for this addendum.

### A1. The participants directory

`https://data.directory.opinbrasil.com.br/participants`: HTTP 200,
`application/json`, 38 organisations, each `"Status":"Active"`. The phase-1
family read here is `products-services_life-pension`; `products-services_pension-plan`
is a separate family, not read. The paths the directory lists are
`/open-insurance/products-services/v1/...` and `/v2/...`, not the `v3` of the
specification read in section 4. Organisations listing a `life-pension`
endpoint: Bradesco, Icatu, Itaú, Mapfre, Porto (a sandbox host), Safra (an
`api-hml` host for v2), Zurich, Zurich Santander, Brasilprev, BTG Pactual Vida e
Previdência (an `openinsurance-dev` host for v2), Caixa Vida e Previdência, Rio
Grande, Sul América and XP. The homologation and sandbox hosts are as filed.

### A2. Phase-1 `life-pension`: four insurers answer, one refuses

| Insurer                     | URL                                                                                         | Result | Records                                   | Sample (as filed)                                                                                                                                                                                                                                                                                                                 |
| --------------------------- | ------------------------------------------------------------------------------------------- | ------ | ----------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| XP Vida e Previdência       | `https://insurance-openfinance.xpi.com.br/open-insurance/products-services/v2/life-pension` | 200    | `"totalRecords":625`, 63 pages            | `"PGBL INDIVIDUAL SPARTA INFLAÇÃO"`, `"susepProcessNumber":"15414.615915/2022-43"`, `"cnpjNumber":"44843813000119"`, `"companyName":"Sparta Inflação Prev Advisory XP Seg FICFIRF CP"`, `"maximumAdministrationFee":"0"`, `"loadingAntecipated":{"minValue":"0","maxValue":"0"}`, `"loadingLate":{"minValue":"0","maxValue":"0"}` |
| Icatu Seguros               | `https://opin.icatuseguros.com.br/open-insurance/products-services/v2/life-pension`         | 200    | `"totalRecords":31318`, 1,253 pages of 25 | `"ICATU VGBL - ANGARIAÇÃO"`, `"susepProcessNumber":"15414.902074/2019-14"`, `"cnpjNumber":"33499011000117"`, `"companyName":"FINACAP ICATU PREVIDENCIÁRIO 70 FIM"`, `"maximumAdministrationFee":"1,8"`, `"loadingAntecipated":{"minValue":"0","maxValue":"0"}`                                                                    |
| Bradesco Vida e Previdência | `https://opin.bradescoseguros.com.br/open-insurance/products-services/v2/life-pension`      | 200    | `"totalRecords":17775`, 1,778 pages       | `"PGBL SPX LANCER PLUS"`, `"susepProcessNumber":"15414600741202214"`, `"cnpjNumber":"42461943000161"`, `"companyName":"BRADESCO SPX LANCER PLUS PGBL/VGBL FIC MULTIMERCADO"`, `"maximumAdministrationFee":"2.0"`, `"loadingAntecipated":{"minValue":"0.0","maxValue":"0.0"}`                                                      |
| Caixa Vida e Previdência    | `https://api.caixavidaeprevidencia.com.br/open-insurance/products-services/v2/life-pension` | 200    | `"totalRecords":1`                        | `"FEDERALPREV CRESCER - 1000"`, `"susepProcessNumber":"15414.005446/2011-05"`, `"cnpjNumber":"38122278000104"`, `"companyName":"FUNDO SEM VARIACAO DE COTA"`, `"maximumAdministrationFee":"20"`, `"loadingAntecipated":{"minValue":"10.000","maxValue":"4.122"}`                                                                  |
| Brasilprev                  | `https://opin.brasilprev.com.br/open-insurance/products-services/v2/life-pension`           | 400    | none                                      | `{"errors":[{"code":"400","detail":"Parameter 'cache-control' is required.","title":"Malformed Request"}]}`                                                                                                                                                                                                                       |

What this shows, as filed:

- **The fields exist and are filled.** Each product carries the processo, the
  type (`PGBL` or `VGBL`), `costs.loadingAntecipated` and `loadingLate` (min and
  max) and one or more `investmentFunds[].cnpjNumber`. That is the
  processo-to-FIE link, in JSON, from four insurers.
- **The values need care.** XP files `"maximumAdministrationFee":"0"` for every
  fund on the page read, so XP's phase 1 is not a fee source. Icatu writes
  `"1,8"` with a comma, Bradesco `"2.0"` with a dot. Bradesco writes the processo
  without punctuation (`15414600741202214`). Caixa's only record gives the
  insurer's own CNPJ (38122278000104) as the fund's, a fee of `"20"`, and a
  loading `minValue` above its `maxValue`. Nothing here is corrected.
- **Paging.** XP ignores `page-size` (a request for 1,000 returned 10) and its v2
  URL returns v1 `links`. Only page 1 of each insurer was read. The XP Superprev
  processos of section 6 are not on XP's page 1; the other 62 pages were not
  read.
- **Brasilprev is not shown to be down.** It asks for a `cache-control` request
  header, which the scraping tools cannot send.
- **Timestamps.** Icatu's `requestTime` reads `2026-10-05T10:11:39Z` and Caixa's
  `2026-10-05T10:11:55Z`, for calls made at about 13:11 UTC. These servers stamp
  UTC-3 time with a `Z`. Quoted as filed.

### A3. SUSEP's PGBL/VGBL plan search has the carregamento and the FIE

`https://www2.susep.gov.br/safe/menumercado/PVGBL/Plano.aspx/Detalhar/24737?tipoPlanoId=1`:
HTTP 200, `text/html`. SUSEP describes the system as a "pesquisa quanto aos
principais parâmetros técnicos dos planos do tipo PGBL/VGBL aprovados pela
SUSEP, que estejam atualmente aptos para comercialização"
(`https://www2.susep.gov.br/menuatendimento/vgblpgbl/menuempresa_2011.asp?plano=vg`,
read through Exa). Plan 24737, as filed:

- "Tipo: PGBL Individual", "Processo N°.: 15414.632689/2019-60", "Seguradora: XP
  VIDA E PREVIDÊNCIA S.A.", "Data da primeira aprovação: 15/01/2020".
- "Carregamento", "Forma: Cobrado quando do recebimento dos prêmios e da
  efetivação de pedidos de resgate e/ou portabilidade", "Percentual 1 (até 10%):
  0,00", "Percentual 2 (até 10%): 0,00".
- "Fundos de investimento para o período de acumulação": "35.420.569/0001-90 |
  XP SEGUROS SUPERPREV FUNDO DE INVESTIMENTO MULTIMERCADO | Composto | 0,00 |
  70,00". What Min. and Máx. measure is not stated on the page.

So SUSEP itself links the section-6 processo to the section-6 FIE, with the
carregamento as a field. Plan 24738 (read through Exa) is a different XP PGBL:
processo 15414.632691/2019-39, FIE 35.420.532/0001-62, carregamento 0,00 and
0,00. It came back for `tipoPlanoId=4`, so that parameter looks ignored. The
VGBL processo 15414.632690/2019-94 was not found. The list page is
`https://www2.susep.gov.br/safe/menumercado/PVGBL/Plano.aspx`. It is HTML, one
page per plan; no download or API was found.

### A4. The Superprev fee, still not reconciled

XP's fund page (`https://conteudos.xpi.com.br/previdencia-privada/xp-seg-superprev-fim/`,
read through Exa): "CNPJ 35.420.569/0001-90", "Taxa de Administração (ao ano)
0,60 %", "Liquidação de Resgate D+2 (Dias Úteis)". The page has no carregamento
line. Two aggregators print the Extrato's value: "Taxa de administração total
2,60%" (etfsbrasil.com.br) and "TAXA DE ADMINISTRAÇÃO 2,60%" (investidor10.com.br).
A total of the FIE and its underlying funds, against the FIE's own 0,60, would
explain the gap, but no primary document read says so. Item 4 stays open.

### A5. Olinda `produtos`

`https://dados.susep.gov.br/olinda/servico/produtos/versao/v1/odata/`: HTTP 200,
an AtomPub service document with one collection, `DadosProdutos`.
`.../DadosProdutos?$top=5&$format=json`, and the same collection with
`$filter=numeroprocesso eq '15414.632689/2019-60'`: HTTP 500, `"codigo" : 500,
"mensagem" : "Erro desconhecido"`. The rows were not read. Whether the
collection needs parameters, or the service was failing, was not established.

### A6. What SUSEP makes the insurer tell the participant

Circular SUSEP nº 698, de 4 de abril de 2024 (EAPC plans; Circular nº 699 of the
same date has the same lists for insurers' survival-cover plans, art. 80 and
81), read through Exa from
`https://www.in.gov.br/en/web/dou/-/circular-susep-n-698-de-4-de-abril-de-2024-553936390`
and `https://www2.susep.gov.br/safe/scripts/bnweb/bnmapi.exe?router=upload%2F28312`:

- Art. 78, daily: "II - denominação e CNPJ do(s) FIE(s) vinculado(s) ao plano";
  "IX - quando for o caso, informação sobre o critério de tributação escolhido
  pelo participante".
- Art. 79, at least yearly: "II - número do processo administrativo por meio do
  qual o plano foi aprovado pela Susep"; "III - denominação e CNPJ do(s) FIE(s)
  vinculado(s) ao plano"; "VI - valor pago a título de carregamento no período de
  competência referenciado no extrato"; "XX - a taxa de administração e a taxa de
  performance efetivamente aplicadas relativas ao(s) FIE(s) vinculado(s) ao
  plano"; "XXI - quando for o caso, informação sobre o critério de tributação
  escolhido pelo participante".

The client's yearly statement from the insurer therefore carries the processo,
the FIE CNPJ, the carregamento paid, the fees actually applied and, where it
applies, the tax regime. That backs the recommendation: take these from the
client's own documents, and use a product range only as context.

### What changes

- The plan-to-FIE link and the carregamento are public in two places, not one:
  the insurer's phase-1 JSON and SUSEP's PGBL/VGBL plan search. Both are per
  insurer or per plan (paged JSON, or one HTML page per plan); neither is a bulk
  file.
- The recommendation stands: the statement's CNPJ stays the FIE key, and the
  carregamento and the regime come from the client. Two tickets are worth
  considering if the owner wants them: (a) the BTG "por alíquota" table
  (unchanged); (b) reading SUSEP's plan search, or one insurer's phase-1 pages,
  to check a statement's FIE CNPJ against its processo. No build in this
  addendum.
