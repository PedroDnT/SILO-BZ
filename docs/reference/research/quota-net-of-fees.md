# Is the reported quota net of the fund's fees?

Decision ticket #610, part of map #510 (portfolio-diagnosis demo). Read on
2026-10-05, finished 13:10 UTC-3 (16:10 UTC). Primary sources only: the
consolidated texts of Resolução CVM 175 (Parte Geral, Anexo Normativo I and
Anexo Normativo V) and of Instrução CVM 555 on `conteudo.cvm.gov.br`, and CVM's
Informe Diário dictionary and dataset page on `dados.cvm.gov.br`. The agent's
shell proxy refuses gov.br, so every text was fetched through Exa or Firecrawl
(see Sources). No database was queried. Nothing was written to any database and
no workflow was dispatched.

The question: is `VL_QUOTA` in the CVM Informe Diário (stored in
`cvm_fi_diario.vl_quota`, served by `api.fund_nav`) already net of the
administration fee, the management fee, the performance fee and the other fund
expenses (encargos)? It closes the "not verified" premise of
[`portfolio-return-coverage.md`](portfolio-return-coverage.md) section 7.

## Answer

1. **Yes for administração, gestão and distribuição; yes for performance; yes
   for the encargos the class bears.** The rule builds the answer in four
   steps:
   - **The quota is PL divided by the number of quotas** (Parte Geral Art. 14
     § 1, § 2 for a subclass; ICVM 555 Art. 11 § 1; Anexo V Art. 10 for ETFs).
   - **The fees are expenses of the class.** Art. 117 lists, as _encargos_
     "que lhe podem ser debitadas diretamente", the "taxas de administração e
     de gestão" (XVI) and the "taxa máxima de distribuição" (XVIII). Anexo I
     Art. 77 adds, for a FIF, the "taxa de performance" (I) and the "taxa
     máxima de custódia" (III). ICVM 555 Art. 132 XII has "as taxas de
     administração e de performance".
   - **They are accrued every business day.** Parte Geral Art. 117 § 2: "Nas
     classes abertas, as taxas devidas aos prestadores de serviços devem ser
     provisionadas por dia útil, sempre como despesa da classe". ICVM 555
     Art. 85 § 3 says the same for "as taxas de administração e de
     performance".
   - **A provision is a liability.** ICVM 555 Art. 2 XLI defines
     "provisionamento" as "o registro contábil de um passivo, ainda que
     estimado". A liability lowers PL, so it lowers PL ÷ quotas. CVM 175's
     Parte Geral defines neither "patrimônio líquido" nor "provisionamento";
     the bridge for CVM 175 funds is ICVM 555's definition plus the accounting
     plan (COFI), which was **not read**. This step is an inference, not a
     quote.

   So the daily quota a fund files is after the fees accrued up to that day,
   whatever day they are paid: the payment date is "conforme estabelecido no
   regulamento" and does not move the quota.

2. **The CVM dictionary says nothing about fees.** `meta_inf_diario_fi.txt`
   describes `VL_QUOTA` only as "Valor da cota". That is a negative result: the
   dictionary neither confirms nor denies "net of fees". The answer rests on
   the rule above, not on the file's metadata.
3. **Performance fee: provisioned, not only recognised when paid.** CVM 175
   does not name the performance fee in Art. 117 § 2 ("taxas devidas aos
   prestadores de serviços"); ICVM 555 Art. 85 § 3 did name it. The difference
   in wording is a finding. Under CVM 175 the provision is still explicit in
   Anexo I: Art. 28 § 5 speaks of "a taxa de performance a ser provisionada e
   paga", § 6 lets the gestor "não apropriar a taxa de performance provisionada
   no período", and Art. 7 § 2 and Art. 22 § 1 require a second quota "antes de
   descontada a provisão para o pagamento da taxa de performance" for the
   _método do ajuste_. A second quota "before the provision" only makes sense
   if the ordinary quota is after it. The performance fee is also computed on
   a quota already net of the other fees: Art. 28 § 1 IV, "cobrança após a
   dedução de todas as despesas, inclusive das taxas devidas aos prestadores de
   serviços essenciais".
4. **Other encargos (auditor, custody, taxes, legal costs).** Art. 117 caput
   lets them be "debitadas diretamente" from the class, so they reduce PL and
   the quota. The daily-accrual rule of § 2 covers fees owed to service
   providers; when a non-fee expense is recognised (accrued daily or booked
   when incurred) is a COFI matter that was **not read**.
5. **ETFs: the same for the management fee, and no performance fee at all.**
   Anexo V Art. 7: "É vedada a cobrança de qualquer taxa de performance aos
   cotistas ou à classe de cotas." Its Art. 10 defines the "valor patrimonial
   da cota" as PL ÷ quotas "no encerramento do dia", and Art. 34 I a) has the
   administrator send it to CVM daily. Anexo V never uses the word "aberta", so
   whether Art. 117 § 2 (daily accrual "nas classes abertas") binds an ETF in
   so many words was **not verified**; the Parte Geral encargos (Art. 117
   XVI) apply to every fund. An ETF's exchange close is a market price, not
   this quota; the rule says nothing about it.
6. **Not net of:** taxa de ingresso and taxa de saída (paid by the investor
   "ao patrimônio da classe", Art. 3 XXXV and XXXVI), income tax and
   come-cotas (#611, #612), and the _ajuste individual_ of the método do
   ajuste, which "não é despesa do fundo" (Anexo I Art. 29 § 1 II).

**For the engine (#606):** a 12-month return from two `api.fund_nav` quotas is
net of the fund's administração, gestão, distribuição, performance (where
charged) and the encargos it bears, and gross of income tax and of
ingresso/saída fees. The label "líquido das taxas do fundo, bruto de IR" holds,
with the caveats in "Not verified".

## Quotes

All quotes are verbatim from the fetched text. Where the consolidated text
prints an inciso twice (old and new wording), the current wording is quoted.

### Resolução CVM 175, Parte Geral (consolidated, "COM AS ALTERAÇÕES INTRODUZIDAS PELAS RESOLUÇÕES CVM Nº 181/23, 184/23, 187/23, 200/24, 206/24, 209/24 E 214/24")

| Claim                                                      | Article                   | Quote                                                                                                                                                                                                                                                                                                                |
| ---------------------------------------------------------- | ------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Quota = PL ÷ quotas                                        | Art. 14 § 1               | "O valor da cota resulta da divisão do valor do patrimônio líquido da respectiva classe pelo número de cotas da mesma classe."                                                                                                                                                                                       |
| Same for a subclass                                        | Art. 14 § 2               | "Caso a classe tenha subclasses, o valor da cota de cada subclasse resulta da divisão do valor do patrimônio líquido atribuído à respectiva subclasse pelo número de cotas da mesma subclasse."                                                                                                                      |
| Administration fee is charged to the fund                  | Art. 3 XXXIII             | "taxa de administração: taxa cobrada do fundo para remunerar o administrador e os prestadores dos serviços por ele contratados e que não constituam encargos do fundo;"                                                                                                                                              |
| Management fee is charged to the fund                      | Art. 3 XXXIV              | "taxa de gestão: taxa cobrada do fundo para remunerar o gestor e os prestadores dos serviços por ele contratados e que não constituam encargos do fundo;"                                                                                                                                                            |
| Distribution fee is charged to the fund                    | Art. 3 XXXVII             | "taxa máxima de distribuição de cotas: taxa cobrada do fundo, representativa do montante total para remuneração dos distribuidores, expressa em percentual anual do patrimônio líquido (base 252 dias);"                                                                                                             |
| Entry and exit fees are paid by the investor, not the fund | Art. 3 XXXV, XXXVI        | "taxa de ingresso: taxa paga pelo cotista ao patrimônio da classe ao aplicar recursos em uma classe de cotas"; "taxa de saída: taxa paga pelo cotista ao patrimônio da classe ao resgatar recursos de uma classe de cotas"                                                                                           |
| Encargos are debited from the class                        | Art. 3 XXII               | "encargos do fundo: despesas específicas que podem ser debitadas diretamente da classe de cotas, não estando inclusas nas taxas destinadas aos prestadores de serviços essenciais;"                                                                                                                                  |
| The encargos list                                          | Art. 117 caput            | "Constituem encargos do fundo as seguintes despesas, que lhe podem ser debitadas diretamente, assim como de suas classes de cotas, se houver, sem prejuízo de outras despesas previstas nesta Resolução ou em regulamentação específica:"                                                                            |
| Examples of non-fee encargos                               | Art. 117 I, IV, XII       | "I – taxas, impostos ou contribuições federais, estaduais, municipais ou autárquicas, que recaiam ou venham a recair sobre os bens, direitos e obrigações do fundo;" "IV – honorários e despesas do auditor independente;" "XII – despesas com liquidação, registro e custódia de operações com ativos da carteira;" |
| Fees in the encargos                                       | Art. 117 XVI, XVII, XVIII | "XVI – taxas de administração e de gestão;" "XVII – montantes devidos a fundos investidores na hipótese de acordo de remuneração com base na taxa de administração, performance ou gestão, observado o disposto no art. 99;" "XVIII – taxa máxima de distribuição;" (XVIII with wording of Res. CVM 181/23)          |
| **Daily accrual**                                          | **Art. 117 § 2**          | **"Nas classes abertas, as taxas devidas aos prestadores de serviços devem ser provisionadas por dia útil, sempre como despesa da classe e apropriadas conforme estabelecido no regulamento."**                                                                                                                      |
| Expenses outside the list fall on the provider             | Art. 118 caput            | "Quaisquer despesas não previstas como encargos do fundo, inclusive aquelas de que trata o art. 96, § 4º, correm por conta do prestador de serviço essencial que a tiver contratado, sem prejuízo do disposto no § 5º do mesmo artigo."                                                                              |
| Provision appears in the fee-rebate rule                   | Art. 99                   | "o valor das correspondentes parcelas das taxas de administração ou gestão deve ser subtraído e limitado aos valores destinados pela classe investida ao provisionamento ou pagamento das despesas com as referidas taxas."                                                                                          |

### Resolução CVM 175, Anexo Normativo I (Fundos de Investimento Financeiro)

| Claim                                           | Article         | Quote                                                                                                                                                                                                                                                                                                                                                         |
| ----------------------------------------------- | --------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Quota computed at the close                     | Art. 7 caput    | "Para os efeitos deste Anexo Normativo I, o valor da cota deve ser calculado no encerramento do dia, que deve ser entendido como o horário de fechamento dos mercados em que a classe de cotas atue."                                                                                                                                                         |
| Ajuste method: a gross quota is also computed   | Art. 7 § 2      | "A classe que efetuar cobrança de taxa de performance utilizando o método do ajuste deve calcular o valor da cota da classe que será debitada sempre antes de descontada a provisão para o pagamento da taxa de performance."                                                                                                                                 |
| D-1 quota option                                | Art. 6 caput    | "Quando se tratar de classes de cotas tipificada como “Renda Fixa” ou registradas como “Exclusivas” ou “Previdenciárias”, o regulamento pode estabelecer que o valor da cota do dia seja calculado a partir do patrimônio líquido do dia anterior, devidamente atualizado por 1 (um) dia útil."                                                               |
| Daily publication of quota and PL               | Art. 22 I       | "calcular e divulgar o valor da cota e do patrimônio líquido das classes e subclasses de cotas abertas: a) diariamente;"                                                                                                                                                                                                                                      |
| Ajuste method: the gross quota is published too | Art. 22 § 1     | "Caso a taxa de performance seja cobrada pelo método do ajuste, o administrador deve divulgar o valor da cota antes de descontada a provisão para o pagamento da taxa de performance, com o mesmo destaque dado ao valor da cota referida no inciso I do caput."                                                                                              |
| Informe diário is filed within one business day | Art. 24 I       | "I – informe diário, no prazo de 1 (um) dia útil;"                                                                                                                                                                                                                                                                                                            |
| Performance fee definition                      | Art. 2 XVII     | "taxa de performance: taxa cobrada do fundo em função do resultado da classe ou do cotista;"                                                                                                                                                                                                                                                                  |
| Performance after all other expenses            | Art. 28 § 1 IV  | "cobrança após a dedução de todas as despesas, inclusive das taxas devidas aos prestadores de serviços essenciais, podendo incluir na base do cálculo os valores recebidos pelos cotistas a título de amortização ou de rendimentos previstos no art. 36 deste Anexo Normativo I."                                                                            |
| Charged at least half-yearly                    | Art. 28 § 1 III | "cobrança por período, no mínimo, semestral;"                                                                                                                                                                                                                                                                                                                 |
| **Performance is provisioned**                  | **Art. 28 § 5** | **"Caso o valor da cota base atualizada pelo índice de referência seja inferior ao valor da cota base, a taxa de performance a ser provisionada e paga deve ser: I – calculada sobre a diferença entre o valor da cota antes de descontada a provisão para o pagamento da taxa de performance e o valor da cota base valorizada pelo índice de referência;"** |
| Provisioned performance may be carried over     | Art. 28 § 6     | "Na hipótese do § 5º, a critério do gestor é permitido não apropriar a taxa de performance provisionada no período, prorrogando a cobrança para o período seguinte, desde que:"                                                                                                                                                                               |
| Ajuste is not a fund expense                    | Art. 29 § 1 II  | "o ajuste individual é calculado de acordo com a situação particular de cada aplicação do cotista e não é despesa do fundo;"                                                                                                                                                                                                                                  |
| Performance and custody are FIF encargos        | Art. 77         | "Em acréscimo aos encargos dispostos no art. 117 da parte geral da Resolução, o regulamento do FIF pode prever como encargos as seguintes despesas, que podem ser debitadas diretamente de suas classes de cotas:" … "I – taxa de performance; e III – taxa máxima de custódia." (inciso II was not in either extraction)                                     |

### Resolução CVM 175, Anexo Normativo V (Fundos de Índice)

| Claim                                | Article     | Quote                                                                                                                                                                                                                                                                                                                         |
| ------------------------------------ | ----------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **No performance fee in an ETF**     | **Art. 7**  | **"É vedada a cobrança de qualquer taxa de performance aos cotistas ou à classe de cotas."**                                                                                                                                                                                                                                  |
| ETF quota = PL ÷ quotas at the close | Art. 10     | "O valor patrimonial da cota é o resultante da divisão do valor do patrimônio líquido do fundo, da classe ou da subclasse de cotas, conforme o caso, pelo número de cotas existentes no encerramento do dia, apurado com base nos mesmos critérios utilizados para o cálculo do valor de fechamento do índice de referência." |
| Daily filing to CVM                  | Art. 34 I   | "O administrador deve encaminhar à CVM, por meio de sistema eletrônico disponível na rede mundial de computadores, as seguintes informações: I – diariamente: a) valor patrimonial da cota; b) patrimônio líquido da classe de cotas; e c) valor das emissões e resgates de cotas efetuados no dia;"                          |
| Valuation follows the COFI           | Art. 12 § 5 | "…conforme os critérios de avaliação e apropriação contábil e demais requisitos constantes do Plano Contábil dos Fundos de Investimento – COFI, editado pela CVM."                                                                                                                                                            |

### Instrução CVM 555 (legacy funds, consolidated)

| Claim                                    | Article             | Quote                                                                                                                                                                                                                                                                    |
| ---------------------------------------- | ------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Provision is a liability                 | Art. 2 XLI          | "provisionamento: é o registro contábil de um passivo, ainda que estimado, em função de obrigação já constituída;"                                                                                                                                                       |
| Quota = PL ÷ quotas at the close         | Art. 11 § 1         | "O valor da cota do dia é resultante da divisão do valor do patrimônio líquido pelo número de cotas do fundo, apurados, ambos, no encerramento do dia, assim entendido, para os efeitos desta Instrução, como o horário de fechamento dos mercados em que o fundo atue." |
| **Daily accrual, performance named**     | **Art. 85 § 3**     | **"Nos fundos abertos, as taxas de administração e de performance devem ser provisionadas por dia útil, sempre como despesa do fundo e apropriadas conforme estabelecido no regulamento."**                                                                              |
| Performance after the administration fee | Art. 86 § 1 IV      | "cobrança após a dedução de todas as despesas, inclusive da taxa de administração podendo incluir na base do cálculo os valores recebidos pelos cotistas a título de amortização ou de rendimentos nos termos do art. 4º, parágrafo único."                              |
| Encargos list                            | Art. 132 caput, XII | "Constituem encargos do fundo as seguintes despesas, que lhe podem ser debitadas diretamente:" … "XII – as taxas de administração e de performance;"                                                                                                                     |

### CVM open data

| Claim                                | Source                   | Quote                                                                                                                                                                                                                                                            |
| ------------------------------------ | ------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `VL_QUOTA` is only "the quota value" | `meta_inf_diario_fi.txt` | "Campo: VL_QUOTA … Descrição : Valor da cota … Tipo Dados: numeric … Precisão : 27 … Scale : 12"                                                                                                                                                                 |
| The dataset holds the quota as filed | `fi-doc-inf_diario` page | "O INFORME DIÁRIO é um demonstrativo que contém as seguintes informações do fundo, relativas à data de competência: Valor total da carteira do fundo; Patrimônio líquido; Valor da cota; Captações realizadas no dia; Resgates pagos no dia; Número de cotistas" |

## Not verified

- **That a provision lowers PL under CVM 175.** CVM 175 defines neither
  "patrimônio líquido" nor "provisionamento"; the link uses ICVM 555 Art. 2
  XLI and accounting sense. The COFI (Plano Contábil dos Fundos de
  Investimento), which Anexo V Art. 12 § 5 cites, was not read.
- **When non-fee encargos hit the quota** (auditor, custody, taxes, legal
  costs): accrued daily or booked when incurred. Art. 117 § 2 covers fees owed
  to service providers only; the timing for the rest is in the COFI, not read.
- **Which quota a método-do-ajuste fund files as `VL_QUOTA`.** Anexo I
  Art. 22 § 1 makes it publish two (after and before the performance
  provision); the Informe Diário has one field.
- **The D-1 quota of Art. 6** (Renda Fixa, Exclusivas, Previdenciárias): such
  a quota is computed from yesterday's PL "devidamente atualizado por 1 (um)
  dia útil". How that day's fee accrual enters it was not read.
- **Whether an ETF is a "classe aberta" for Art. 117 § 2.** Anexo V never
  uses the word. Whether Anexo V Art. 34's daily "valor patrimonial da cota"
  is the same Informe Diário feed as `cvm_fi_diario` was not checked. Repo
  knowledge, not a primary source: `docs/agents/dataset-notes.md` records
  that a registry ETF has no 2026 `cvm_fi_diario` row, so `api.fund_nav`
  should not be expected to serve an ETF quota.
- **Anexo I Art. 77 inciso II.** Both PDF extractions (Exa and Firecrawl)
  printed only incisos I and III.
- **Closed classes.** Art. 117 § 2 is written for "classes abertas"; how a
  closed FIF class accrues its fees was not read. FIDC, FII, FIP and FIAGRO
  annexes (II, III, IV, VI) were not read.
- **Legacy ETFs under Instrução CVM 359** and the performance-fee rules of
  CVM 175 Anexo XI (previdenciários) were not read.
- **Investee fees in a fund of funds.** By the same rule an investee's fees
  should already be inside the investee's quota, and so inside the investor's
  PL; this is an inference, not a quote. Parte Geral Art. 98 (see
  [`cvm175-structure-and-fees.md`](cvm175-structure-and-fees.md)) governs how
  the investor's fee is stated, not how its quota is computed. Not checked
  against a filing.
- **No filing was checked.** No fund's regulamento, balancete or quota series
  was compared with a fee to confirm the rule in practice.

## Sources

All accessed 2026-10-05 (UTC-3).

- Resolução CVM 175 index page, listing the Parte Geral, Anexos Normativos
  I to XII and the Suplementos:
  <https://conteudo.cvm.gov.br/legislacao/resolucoes/resol175.html> (Exa,
  live fetch).
- Parte Geral, consolidated (76 pages):
  <https://conteudo.cvm.gov.br/export/sites/cvm/legislacao/resolucoes/anexos/100/resol175consolid_ParteGeral.pdf>.
  Full text through Exa (live fetch, no cache date given); three Firecrawl
  `directQuote` queries (first a cache miss, then a cache entry of 2026-10-05
  13:02 UTC-3, 16:02 UTC) gave the same wording for Arts. 3, 14, 117 and 118.
  Arts. 3, 14, 99, 117, 118.
- Anexo Normativo I (FIF), consolidated (49 pages):
  <https://conteudo.cvm.gov.br/export/sites/cvm/legislacao/resolucoes/anexos/100/resol175consolid_Anexo01.pdf>.
  Full text through Exa (live fetch); one Firecrawl query (cache entry of
  2026-10-03 18:00 UTC-3, 21:00 UTC). Arts. 2, 6, 7, 22, 24, 28, 29, 77.
- Anexo Normativo V (Fundos de Índice), consolidated:
  <https://conteudo.cvm.gov.br/export/sites/cvm/legislacao/resolucoes/anexos/100/resol175consolid_Anexo05.pdf>
  (Exa, live fetch). Arts. 7, 10, 12, 34.
- Instrução CVM 555, consolidated:
  <https://conteudo.cvm.gov.br/export/sites/cvm/legislacao/instrucoes/anexos/500/inst555consolid.pdf>
  (Exa, live fetch). Arts. 2, 11, 85, 86, 132.
- Informe Diário dictionary:
  <https://dados.cvm.gov.br/dados/FI/DOC/INF_DIARIO/META/meta_inf_diario_fi.txt>
  (Firecrawl, `maxAge: 0`, live).
- Informe Diário dataset page:
  <https://dados.cvm.gov.br/dataset/fi-doc-inf_diario> (Exa, live; "Última
  Atualização setembro 3, 2026, 11:00 (UTC)", 08:00 UTC-3).
