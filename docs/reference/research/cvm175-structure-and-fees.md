# CVM 175: fund levels, master funds and fees without double counting

Research for map #510 (portfolio-diagnosis demo). Read on 2026-10-03 (UTC-3),
finished 18:10 UTC-3 (21:10 UTC). Primary sources only: the
consolidated text of Resolução CVM 175 on `conteudo.cvm.gov.br` and CVM's
open-data dictionaries on `dados.cvm.gov.br`, both fetched through Firecrawl
(the agent's proxy refuses both hosts directly). Read-only, bounded SELECTs
against the production Supabase project `zcjbtpxuhdekpwcxmepn` (each with a
15 s statement timeout). Nothing was written to any database and no workflow
was dispatched.

## Answer

1. **Levels.** A _fundo_ is the condominium (Parte Geral Art. 4). A _classe_ is
   a segregated patrimônio inside it with its own registro de funcionamento
   (Art. 5 caput, Art. 8 § 2). A _subclasse_ is a slice of a class that may
   differ only in target investor, flow terms, and the fees of administração,
   gestão, distribuição máxima, ingresso and saída (Art. 5 § 5). The rule
   speaks of "inscrições no CNPJ" for classes (Art. 37 § 1 II). It gives no
   CNPJ to a subclass anywhere I read. A _classe de investimento em cotas_
   must hold at least 95% of its PL in quotas of other classes (Anexo I
   Art. 2 VI). The Parte Geral, Anexo I and the Suplementos never use the
   words "master", "feeder" or "espelho" (Anexos II to XII were not
   searched). The open data does: the Extrato has `FUNDO_ESPELHO`, "Indica se é
   fundo-espelho".
2. **Fees.** **Parte Geral Art. 98** is the key article. Any class that may
   buy quotas of other funds "deve estabelecer em seu regulamento que suas
   taxas de administração e gestão compreendem as taxas dos fundos
   investidos". The regulamento may instead state a maximum (investees
   included) and a minimum (excluded). Comparisons must use the maximum
   (§ 1), and the lâmina must highlight it (Anexo I Art. 14 § 2). **Three
   limits apply:**
   - The article covers administração and gestão only, not distribuição or
     performance.
   - § 2 removes listed funds and funds "geridos por partes não relacionadas
     ao gestor do fundo investidor".
   - It binds every class that may hold fund quotas, not only the 95% ones.

   So summing a feeder's disclosed adm/gestão fee and its master's
   **double counts** when the master is unlisted and run by the same or a
   related manager. It **does not double count** (the sum is needed for an
   all-in cost) when the master is listed or run by an unrelated manager.
   Performance and distribution fees are never folded in by Art. 98. CVM's
   all-in concept is the _Taxa Total de Despesas_ of the demonstração de
   desempenho (Suplemento C). It adds investees' expenses "proporcionalmente
   ao valor e período do investimento", with no § 2 exception. It is not in
   any open-data file checked here.

3. **Data.**
   - The Extrato (`TAXA_ADM`, one number, at class level, no subclass, no
     gestão or distribution split) and the lâmina (`TAXA_ADM`, `_MIN`,
     `_MAX`, per class or subclass) carry the fee.
   - The CVM-175 registry files carry no fee column (verified from the
     columns SILO keeps; the dictionary zip was not readable here).
   - `registro_classe.Classe_Cotas` is S/N on FIF classes only. Its meaning
     is inferred, not read: 6,856 of 7,011 `S` classes hold at least 95% of
     PL in fund quotas in CDA 2026-08, against a median of 63% for `N`.
   - No file names the master. The link is CDA block 2 (`cnpj_cota`).
   - **For FICs with a fee range, the Extrato `TAXA_ADM` equals the lâmina
     maximum in 596 of 993 cases and the minimum in 218.** That fits the
     Art. 98 § 1 reading (the filed fee includes the investees'), but it does
     not prove it: non-FIC classes show the same pattern (341 of 602), so a
     range may also be a PL-tier fee (Art. 48 § 2 XIX b). Whether feeder plus
     master double counts depends on whether the master is unlisted and run
     by a related manager. The open data does not state that relation.
   - SILO cannot walk fundo → classe today. Only 132 of 36,770 class rows
     find their parent fund's row, because both land on the same
     `(cnpj, entity_type)` key. Subclasses are not ingested.
4. **The external proposal fails on all four points.** Sections 4 and 5 give
   the evidence.
   - `cad_fi` is the "Não Adaptados RCVM175" file, and 8 of 26,046 active FI
     funds have a fee from it.
   - "> 10 → / 100" fits 2 of the 6 test funds.
   - "> 90% in one fund" misses 2,291 classes CVM flags as FIC and flags 728
     it does not.
   - "Shell fee + master fee" double counts whenever Art. 98 applies.

## 1. Levels: fundo, classe, subclasse

| Fact                                                          | Evidence                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| ------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| The fund is the condominium                                   | Parte Geral Art. 4: "O fundo de investimento é uma comunhão de recursos, constituído sob a forma de condomínio de natureza especial, destinado à aplicação em ativos financeiros, bens e direitos, de acordo com a regra específica aplicável à categoria do fundo."                                                                                                                                                                                                                          |
| Classes are segregated patrimônios                            | Art. 5 caput: "O regulamento do fundo de investimento pode prever a existência de diferentes classes de cotas, com direitos e obrigações distintos, devendo o administrador constituir um patrimônio segregado para cada classe de cotas." § 2: "Cada patrimônio segregado responde somente por obrigações referentes à respectiva classe de cotas."                                                                                                                                          |
| A fund without classes still issues one class                 | Art. 5 § 3: "O fundo que não contar com diferentes classes de cotas deve efetuar emissões de cotas em classe única, preservada a possibilidade de serem constituídas subclasses."                                                                                                                                                                                                                                                                                                             |
| What a subclass may differ in                                 | Art. 5 § 5: "As subclasses de cotas podem ser diferenciadas exclusivamente por: I – público-alvo; II – prazos e condições de aplicação, amortização e resgate; e III – taxas de administração, gestão, máxima de distribuição, ingresso e saída." § 4: "É vedada a afetação ou a vinculação, a qualquer título, de parcela do patrimônio de uma classe de cotas a qualquer subclasse." § 6 lets subclasses of _classes restritas_ differ by "outros direitos econômicos e direitos políticos" |
| Documents per level                                           | Art. 3 IV: "anexos (descritivos de classes): partes do regulamento do fundo essenciais à constituição de classes de cotas"; V: "apêndices (descritivos de subclasses): partes do anexo da classe que disciplinam as características específicas de cada subclasse de cotas, se houver". Parágrafo único II: "as referências a 'classe' e a 'classe de cotas' alcançam os fundos de investimento que emitem cotas em classe única"                                                             |
| Each class is registered                                      | Art. 8 § 2: "Caso o fundo tenha mais de uma classe de cotas, cada classe deve obter seu próprio registro de funcionamento, o qual pode ser requerido à CVM concomitantemente ou após a obtenção do registro do fundo." Art. 9 speaks of the "registro de funcionamento de fundo, classe e subclasse de cotas"                                                                                                                                                                                 |
| Classes have a CNPJ; subclasses are not given one in the rule | Art. 37 § 1 II (statements to the investor): "a denominação e o número de inscrição no CNPJ do fundo e, caso o fundo possua diferentes classes de cotas, a denominação de toda classe investida, suas inscrições no CNPJ e, se for o caso, especificação das subclasses investidas". No CNPJ for a subclass appears in the Parte Geral or Anexo I. **Not verified:** whether CVM assigns one in its systems                                                                                   |
| Class CNPJ usually equals the fund CNPJ (data, not rule)      | `src/pipeline/ingest_misc.py` docstring, measured 2026-08-28: 36,492 of 36,606 `CNPJ_Classe` values are also a `CNPJ_Fundo`. On 2026-10-03, the 36,770 class rows in `cvm_fund_registry` point to 36,703 distinct `ID_Registro_Fundo` values: multi-class funds are rare                                                                                                                                                                                                                      |
| Classe de investimento em cotas                               | Anexo I Art. 2 VI: "classe de investimento em cotas: classe de cotas que deve aplicar no mínimo 95% (noventa e cinco por cento) do patrimônio líquido em cotas de outras classes"                                                                                                                                                                                                                                                                                                             |
| Naming                                                        | Anexo I Art. 3 § 1: "Caso o fundo possua somente classes de investimento em cotas, sua denominação pode utilizar a expressão 'Fundo de Investimento em Cotas'." § 2: "Deve constar da denominação da classe de investimento em cotas a expressão 'Classe de Investimento em Cotas'."                                                                                                                                                                                                          |
| Type of the investee                                          | Anexo I Art. 71: "As classes de investimento em cotas devem adquirir classes do mesmo tipo que a sua, exceto no caso de classes tipificadas como 'Multimercado', que podem investir em cotas de FIF de qualquer tipo". Art. 72: the regulamento "e, se aplicável, sua lâmina deve especificar o percentual máximo do patrimônio líquido que pode ser aplicado em uma única classe"                                                                                                            |
| No issuer limit for fund quotas                               | Anexo I Art. 44 V: "não há limites quando: ... b) o emissor for fundo de investimento". So a class that is _not_ a classe de investimento em cotas may still put most of its PL in one fund                                                                                                                                                                                                                                                                                                   |
| Master/feeder                                                 | The words "master", "feeder" and "espelho" do not occur in the Parte Geral, Anexo I or the Suplementos (0 hits in the three consolidated PDFs). The concept exists only in CVM's data: the Extrato's `FUNDO_ESPELHO` "Indica se é fundo-espelho" (`meta_extrato_fi.txt`)                                                                                                                                                                                                                      |
| When classes and subclasses became possible                   | Art. 140 § 2 (wording of Res. 200/24): "O art. 5º desta Resolução, referente à possibilidade de os fundos possuírem diferentes classes e subclasses de cotas, entra em vigor em 1º de outubro de 2024."                                                                                                                                                                                                                                                                                       |

**How the engine should walk the levels.** Go fundo → classe (the patrimônio,
the CNPJ, the portfolio in the CDA, the NAV) → subclasse (fees and terms
only, no portfolio of its own, Art. 5 § 4). A fee belongs to the class unless
an apêndice sets it per subclass (section 2).

## 2. Fees: definitions, where set, and the investee rule

| Fee                           | Definition (verbatim)                                                                                                                                                                                                                                                                    | Set in                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| ----------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Taxa de administração         | Parte Geral Art. 3 XXXIII: "taxa cobrada do fundo para remunerar o administrador e os prestadores dos serviços por ele contratados e que não constituam encargos do fundo"                                                                                                               | Class annex, Art. 48 § 2 XIX: "taxas de administração e de gestão, que devem ser expressas em: a) um percentual anual fixo do patrimônio líquido (base 252 dias); ou b) um valor nominal em moeda corrente nacional, que pode variar em função de faixas de valores do patrimônio líquido" (inciso XIX added by Res. 181/23, which revoked the fund-level § 1 VII). § 4: "Caso a classe de cotas conte com subclasses que possuam diferentes taxas de administração e gestão, essas taxas devem ser disciplinadas no apêndice descritivo das subclasses." |
| Taxa de gestão                | Art. 3 XXXIV: "taxa cobrada do fundo para remunerar o gestor e os prestadores dos serviços por ele contratados e que não constituam encargos do fundo"                                                                                                                                   | Same as above                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| Taxa máxima de distribuição   | Art. 3 XXXVII: "taxa cobrada do fundo, representativa do montante total para remuneração dos distribuidores, expressa em percentual anual do patrimônio líquido (base 252 dias)"                                                                                                         | Class annex, Art. 48 § 2 XI; may differ by subclass (Art. 5 § 5 III)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| Taxa de ingresso              | Art. 3 XXXV: "taxa paga pelo cotista ao patrimônio da classe ao aplicar recursos em uma classe de cotas, conforme previsão do regulamento"                                                                                                                                               | Class annex, Art. 48 § 2 XII; may differ by subclass                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| Taxa de saída                 | Art. 3 XXXVI: "taxa paga pelo cotista ao patrimônio da classe ao resgatar recursos de uma classe de cotas, conforme previsão do regulamento"                                                                                                                                             | Same                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| Taxa de performance (FIF)     | Anexo I Art. 2 XVII: "taxa cobrada do fundo em função do resultado da classe ou do cotista". Art. 28: "O regulamento pode estabelecer a cobrança de taxa de performance pelo gestor", with a benchmark, at least 100% of it, at most semiannually, "após a dedução de todas as despesas" | Class annex, Anexo I Art. 15 II and its parágrafo único (Res. 181/23): "Caso o fundo conte com diferentes classes de cotas, as matérias previstas nos incisos do caput devem ser disciplinadas no anexo da classe a que se referirem." Art. 29 allows the computation "com base no resultado da classe ou subclasse"                                                                                                                                                                                                                                      |
| Taxa máxima de custódia (FIF) | Anexo I Art. 15 I: "taxa máxima de custódia, expressa em percentual anual do patrimônio líquido da classe; (base 252 dias)"                                                                                                                                                              | Class annex (Art. 15 parágrafo único)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |

**The investee rule, verbatim (Parte Geral, Capítulo VI, Seção III –
Remuneração):**

> Art. 98. A classe de cotas que possa adquirir cotas de outros fundos de
> investimento deve estabelecer em seu regulamento que suas taxas de
> administração e gestão compreendem as taxas dos fundos investidos.
>
> § 1º Para efeitos do disposto no caput, o regulamento pode estabelecer taxas
> máximas, compreendendo as taxas dos fundos investidos, e taxas mínimas, que
> não incluam as taxas dos fundos investidos, caso em que qualquer canal ou
> material de divulgação que efetue comparação de qualquer natureza entre
> classes de cotas, deve referir-se, na comparação, apenas às taxas máximas,
> permitida a referência, em nota, às taxas mínimas e às taxas efetivas em
> outros períodos.
>
> § 2º As aplicações em classes de cotas dos seguintes fundos de investimento
> não devem ser consideradas para os efeitos do caput e do § 1º:
>
> I – fundos cujas cotas sejam admitidas à negociação em mercado organizado; e
>
> II – fundos geridos por partes não relacionadas ao gestor do fundo investidor.

Around it:

| Fact                                                               | Evidence                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| ------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| The lâmina shows the maximum                                       | Anexo I Art. 14 § 2: "Caso o regulamento estabeleça taxas mínimas e máximas, englobando as taxas das classes investidas, conforme previsto no art. 98, § 1º, da parte geral da Resolução, a lâmina deve destacar as taxas máximas." Suplemento B item 4 offers "[A taxa de administração pode variar de [●]% a [●]% do patrimônio líquido ao ano]"                                                                                                                                                                                                                                            |
| Rebates from the investee reduce the investor's fee, not add to it | Art. 99: with a rebate agreement "que deve ser paga diretamente pela classe investida a classes investidoras ... o valor das correspondentes parcelas das taxas de administração ou gestão deve ser subtraído e limitado aos valores destinados pela classe investida". In force since 2024-10-01 (Art. 140 § 4, wording of Res. 200/24)                                                                                                                                                                                                                                                      |
| Performance fee of investees is not folded in                      | Anexo I Art. 31: "Ao adquirir cotas de classes que cobrem taxa de performance, a classe deve atender às condições estipuladas no art. 28". This is a condition on the investee, not an inclusion rule                                                                                                                                                                                                                                                                                                                                                                                         |
| What advertising must show                                         | Art. 56 IV: "divulgar as taxas de administração, de gestão e máxima de distribuição, observado que, na hipótese de a taxa ser calculada na forma do art. 48, § 1º, VII, 'b', a informação deve consistir no percentual do patrimônio líquido correspondente ao valor da taxa debitada da classe, na mesma data"                                                                                                                                                                                                                                                                               |
| CVM's all-in cost: Taxa Total de Despesas                          | Suplemento C (demonstração de desempenho) expense table: "Taxa de administração (inclui as taxas de administração de outros fundos em que esta classe tenha investido)"; "Taxa de gestão (inclui as taxas de gestão e, se for o caso, de outros fundos em que esta classe tenha investido)"; then "TAXA TOTAL DE DESPESAS". Its note: "Despesas de fundos investidos: as despesas apresentadas foram acrescidas das despesas de outros fundos e classes de cotas em que [este fundo] ou [esta classe de cotas] tenha feito aplicações, proporcionalmente ao valor e período do investimento." |
| The lâmina's expense ratio                                         | Suplemento B item 4: "As despesas pagas pela classe de cotas representaram [●]% do seu patrimônio líquido diário médio". **Not verified:** whether this figure includes investees' expenses. The Suplemento C note above is in Suplemento C, not B                                                                                                                                                                                                                                                                                                                                            |
| Amendments                                                         | The consolidated PDFs carry amendment notes from Res. 181/23, 184/23, 187/23, 200/24, 206/24, 209/24 and 214/24. None is attached to Art. 98. Res. 181/23 moved the fee clause from the fund's general part to the class annex (Art. 48) and added Art. 48 § 4 and Anexo I Art. 15 parágrafo único. Res. 187/23's notes sit on other provisions (among them Anexo I Arts. 44 § 3 and 75 § 2); none is on a fee article. Res. 240/26 is listed as an amendment but its page says it "Altera o Anexo Normativo II" (FIDC) only, and the consolidated PDFs carry no note from it                                                                      |

**Conclusion on double counting.**

- For administração and gestão, a disclosed fee of a class that may hold fund
  quotas already includes the fees of investee funds that are unlisted and
  run by the same or a related manager (Art. 98 caput).
- When the regulamento gives a range, the maximum is the inclusive figure and
  the minimum is the class's own (§ 1).
- Summing feeder and master therefore double counts in exactly that case.
- It is the right thing to do only for investees § 2 excludes: listed funds
  (ETFs, listed FIIs) and funds of unrelated managers.
- For performance and distribution fees, nothing is folded in, so the
  investee's fee is extra cost. The share borne is proportional to the
  holding, as in Suplemento C.

**Not verified:**

- Funds that have not adapted to CVM 175 filed under ICVM 555. I did not
  read ICVM 555's fee article. Many Extrato rows predate adaptation (all six
  in section 5 are dated 2024-05-03), so their regime may differ.
- No public file states whether a given investee is "parte relacionada" to
  the investor's manager in the Art. 98 § 2 II sense.

## 3. Which open-data file carries what

| File (dataset)                                                                                                | Level                                                                                                        | Fee columns                                                                                                                                                                                                                                                                                                                                                                    | Fund-of-funds / master columns                                                                                                                                                                     | In SILO                                                                                                         |
| ------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------- |
| `registro_fundo.csv`, `registro_classe.csv`, `registro_subclasse.csv` in `registro_fundo_classe.zip` (FI/CAD) | fund, class, subclass                                                                                        | **none** in the two files SILO keeps: the residual raw keys of 46,823 fund rows and 36,770 class rows have no fee key (2026-10-03). The dictionary `meta_registro_fundo_classe.zip` holds `meta_registro_fundo.txt`, `meta_registro_classe.txt`, `meta_registro_subclasse.txt` (member names seen in the zip), but it could not be unzipped here, so **the meta was not read** | class: `Classe_Cotas`, plus `ID_Registro_Fundo` pointing to the parent fund. No master CNPJ column among the kept keys                                                                             | fund and class into `cvm_fund_registry` (`raw`); subclass **not ingested**, so its columns are **not verified** |
| `cad_fi.csv` (FI/CAD, "Fundos de Investimento – Não Adaptados RCVM175")                                       | legacy fund                                                                                                  | `TAXA_ADM` "Taxa de administração", Numérico, real; `TAXA_PERFM`; `INF_TAXA_ADM` / `INF_TAXA_PERFM` varchar 400 (`meta_cad_fi.txt`). No unit stated                                                                                                                                                                                                                            | `FUNDO_COTAS` "Indica se é fundo de cotas", S/N                                                                                                                                                    | `cvm_fund_registry.taxa_adm` (migration 64)                                                                     |
| `extrato_fi.csv` (FI/DOC/EXTRATO)                                                                             | `CNPJ_FUNDO_CLASSE` "CNPJ do fundo/classe"; `TP_FUNDO_CLASSE` is `FI` or `CLASSES - FIF`; no subclass column | `TAXA_ADM` (one number, no gestão or distribution split), `TAXA_PERFM`, `TAXA_CUSTODIA_MAX`, `TAXA_INGRESSO_*`, `TAXA_SAIDA_*`                                                                                                                                                                                                                                                 | `FUNDO_COTAS` "Indica se é fundo de cotas"; `FUNDO_ESPELHO` "Indica se é fundo-espelho"; `NEGOC_MERC` (quotas listed, the § 2 I test for the _investee_); `APLIC_MAX_FUNDO_LIGADO`; no master CNPJ | `cvm_fi_extrato`                                                                                                |
| `lamina_fi_YYYYMM.csv` (FI/DOC/LAMINA)                                                                        | class or subclass (`ID_SUBCLASSE`)                                                                           | `TP_TAXA_ADM` Fixa/Variável, `TAXA_ADM`, `TAXA_ADM_MIN`, `TAXA_ADM_MAX`, `TAXA_PERFM` (text), `TAXA_ENTR`, `TAXA_SAIDA`, `PR_PL_DESPESA` (dictionary as recorded in `lamina-coverage.md` § 1)                                                                                                                                                                                  | none                                                                                                                                                                                               | `cvm_fi_lamina`                                                                                                 |
| CDA block 2 (FI/DOC/CDA)                                                                                      | class                                                                                                        | none                                                                                                                                                                                                                                                                                                                                                                           | `cnpj_cota` (the held fund), `emissor_ligado` (CVM's flag, per the dataset notes); the position value gives the share of PL                                                                        | `cvm_fi_cda_cotas`                                                                                              |

What the data shows:

| Fact                                                                                           | Evidence (read-only SQL, 2026-10-03, before 18:10 UTC-3 / 21:10 UTC)                                                                                                                                                                                                                                                       |
| ---------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `Classe_Cotas` takes S/N on FIF classes and is empty on FIDC, FII, FIP, FIAGRO classes         | `fi`: N 15,888 active + 869 cancelled, S 9,497 + 412; every other entity type NULL                                                                                                                                                                                                                                                        |
| `Classe_Cotas = S` means a classe de investimento em cotas (inferred from data; meta not read) | CDA 2026-08, fund quotas summed by held CNPJ over `fact_fund_monthly.vl_patrim_liq` for 2026-08: of 7,011 `S` classes, 6,856 (97.8%) hold >= 95% of PL in fund quotas (median 100%). Of 6,841 `N` classes, 2,308 do (median 62.6%)                                                                                                        |
| One dominant investee is common but not universal among `S`                                    | `S`: 4,720 have one investee > 90% of PL, 4,596 >= 95%. So the > 90%-in-one rule misses 2,291 of the 7,011 `S` classes (155 of them hold less than 95% in quotas altogether). `N`: 728 have one investee > 90%                                                                                                                                                                         |
| The dominant investee is often outside the group                                               | Classes with one investee >= 95% of PL, by that row's `emissor_ligado`: `S` 2,472 S / 2,124 N; `N` 425 S / 214 N. **Not verified:** that `emissor_ligado` equals Art. 98 § 2 II's "parte relacionada ao gestor"; the CDA dictionary was not readable here (zip). Use it only as a candidate proxy                                         |
| `FUNDO_ESPELHO` is the feeder flag in the data                                                 | latest Extrato row per CNPJ: filled only when `FUNDO_COTAS = S`; S on 1,902 `FI` + 533 `CLASSES - FIF` rows                                                                                                                                                                                                                               |
| **The Extrato fee of a FIC with a range is usually the maximum**                                | latest Extrato row joined to the latest lâmina row (class-level row preferred), lâmina `Variável` with distinct min and max, Extrato `FUNDO_COTAS = S`: 993 funds; Extrato `TAXA_ADM` = lâmina max 596, = min 218, neither 179. Same for non-FIC `Variável`: 602 with a range, max 341, min 144. The two rows can be from different dates. Because non-FICs show the same pattern, this does not by itself show that the range is the Art. 98 § 1 range |
| SILO cannot walk fundo → classe as stored                                                      | class rows whose `raw->>'ID_Registro_Fundo'` matches a fund-level row: **132 of 36,770**. Cause: both files upsert into `cvm_fund_registry` on `(cnpj, entity_type)` and the class CNPJ is the fund CNPJ, so whichever loads last owns `raw`                                                                                              |
| Caveat on the CDA month                                                                        | rows in `cvm_fi_cda_cotas`: 129,399 in 2026-03, 128,994 in 2026-05, then 81,899 / 81,015 / 81,006 in 2026-06..08. The cause was not investigated, so the 2026-08 shares above may cover fewer classes than earlier months                                                                                                                 |

## 4. The external proposal, claim by claim

| Claim                                                        | Verdict                                                      | Evidence                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| ------------------------------------------------------------ | ------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| "Use cad_fi (inf_cadastral_fi) as the definitive fee source" | **Not supported**                                            | CVM's dataset page lists `cad_fi.csv` as "Fundos de Investimento – Não Adaptados RCVM175". In SILO, 14,120 registry rows carry a `cad_fi` `TAXA_ADM`; 14,115 of them are cancelled, and **8** are among the 26,046 FI funds with a `vl_quota` in `fact_fund_monthly` 2026-07..09 (the dataset notes' figure, 7 of 25,178 funds reporting NAV on 2026-09-15, was measured on another denominator). The Extrato covers 21,962 of the same 26,046 (`extrato-coverage.md`)                               |
| "Because sites like StatusInvest use it"                     | **Not verified for StatusInvest; contradicted for one site** | StatusInvest was not checked. etfsbrasil.com.br shows "Taxa de administração total 45,00%" for CNPJ 50197313000150 (read 2026-10-03). SILO holds no `cad_fi` fee for that CNPJ (`taxa_adm` NULL, row is a class row with `Classe_Cotas = S`). The Extrato value is 45.0 (`DT_COMPTC` 2024-05-03). The site's figure matches the Extrato, not `cad_fi`. Which file the site reads is not known                                                                           |
| "If a fee is > 10%, divide by 100"                           | **Fits 2 of the 6 test funds**                               | Extrato → lâmina: 49995610000161 25 → 0.25, 36443522000105 25 → 0.25 (fit); 09720710000160 8 → 0.8 (left at 8 by the rule); 39540780000106 7 → 0.07 (left at 7); 50197313000150 45 → 0.06 (rule gives 0.45); 47423757000151 65 → 0.45 (rule gives 0.65). Over all 18 funds with an Extrato `TAXA_ADM` in (5, 100] and a lâmina fee, the ratio is 100 (7 funds), 10 (2), 1.00 (3, at 7, 7.5 and 8.5, where both documents agree), and 15, 144, 160, 228 and 750 (1 each). One lâmina is 0 (18 in all). No constant divisor fits |
| "A fund with > 90% of PL in one other fund is a shell"       | **Not the regulatory test**                                  | The legal category is the classe de investimento em cotas, >= 95% in quotas of _any number_ of classes (Anexo I Art. 2 VI). CVM publishes it as `Classe_Cotas` / `FUNDO_COTAS`. The 90%-in-one rule misses 2,291 `S` classes and flags 728 `N` classes (section 3). Art. 98 applies to any class that _may_ hold fund quotas, so a concentration threshold is not what decides the fee treatment                                                                                                     |
| "Effective fee = shell fee + master fee"                     | **Double counts where Art. 98 applies**                      | Art. 98 caput and § 1 (section 2). For FICs with a range, the Extrato `TAXA_ADM` equals the lâmina maximum in 596 of 993 cases (section 3), consistent with an all-in filed fee. Among FICs with one investee >= 95% of PL, 2,124 of 4,596 have that investee flagged `emissor_ligado = N`; if that flag tracks § 2 II (not verified), summing is correct for them. The sum is correct only for § 2 investees (listed, or an unrelated manager) and for performance/distribution fees                                                                                                                                                                                                                                        |

Two cautions on the scale-error rows:

- Most mismatched names start with "INTER". Their administrator CNPJ was not
  checked.
- The lâmina is not an independent check of the Extrato, because the same
  administrator files both. The independent check is the balancete estimate
  of `lamina-coverage.md` / `extrato-coverage.md`.

## 5. What this means for the engine (inputs for the owner, not decisions)

- **Levels.** Use class CNPJ for portfolio, NAV and CDA. Take the
  subclass from the lâmina's `ID_SUBCLASSE` for fees. `registro_subclasse.csv`
  would give the official list but is not ingested. Walking fundo → classe in
  SILO needs the fund and class registry rows kept apart. That is a candidate
  ticket, not done here (owner's rule on discovered work).
- **Shell → real fund.** Use `Classe_Cotas = S` (or Extrato `FUNDO_COTAS`)
  as the flag and CDA block 2 for the investees with their weights. Follow
  the chain recursively, because a FIC may hold FICs.
- **Fee without double counting.** Show the investor-level class fee as
  disclosed. With a lâmina range, label the maximum "inclui as taxas dos
  fundos investidos (Art. 98 § 1)" and the minimum "da própria classe". Add
  investee adm/gestão fees only for listed or unrelated-manager investees,
  weighted by the CDA share. Add investee performance fees always, as a
  separate line. Never apply a fixed divisor. `extrato-coverage.md`
  recommends dropping Extrato values above 5 as scale errors.

## Sources

All accessed 2026-10-03 (UTC-3) through Firecrawl unless noted.

- Resolução CVM 175, page listing the consolidated text and amendments:
  <https://conteudo.cvm.gov.br/legislacao/resolucoes/resol175.html> (cache
  entry 2026-10-02 16:21 UTC-3, 19:21 UTC).
- Parte Geral, consolidated:
  <https://conteudo.cvm.gov.br/export/sites/cvm/legislacao/resolucoes/anexos/100/resol175consolid_ParteGeral.pdf>
  (76 pages; cache entry 2026-10-03 10:41 UTC-3, 13:41 UTC). Arts. 3, 4, 5,
  8, 9, 37, 48, 56, 97 to 100, 117 and 140.
- Anexo Normativo I (FIF), consolidated:
  <https://conteudo.cvm.gov.br/export/sites/cvm/legislacao/resolucoes/anexos/100/resol175consolid_Anexo01.pdf>
  (49 pages, live fetch). Arts. 2, 3, 14, 15, 28 to 31, 44,
  71 and 72.
- Suplementos, consolidated:
  <https://conteudo.cvm.gov.br/export/sites/cvm/legislacao/resolucoes/anexos/100/resol175consolid_Suplementos.pdf>
  (104 pages, live fetch). Suplemento B (lâmina) item 4 and
  Suplemento C (demonstração de desempenho) expense table and notes.
- Resolução CVM 240 page:
  <https://conteudo.cvm.gov.br/legislacao/resolucoes/resol240.html> (live).
- FI/CAD dataset page: <https://dados.cvm.gov.br/dataset/fi-cad> (live; "Última Atualização 3 de outubro de 2026, 07:00 (UTC-04:00)").
- FI/CAD META directory and `meta_cad_fi.txt`:
  <https://dados.cvm.gov.br/dados/FI/CAD/META/>,
  <https://dados.cvm.gov.br/dados/FI/CAD/META/meta_cad_fi.txt> (live).
  `meta_registro_fundo_classe.zip` was listed (2,222 bytes, "03-Oct-2026
  01:16") but neither Firecrawl nor Parallel could unzip it.
- Extrato dictionary:
  <https://dados.cvm.gov.br/dados/FI/DOC/EXTRATO/META/meta_extrato_fi.txt>
  (cache entry 2026-10-03 18:06 UTC-3, 21:06 UTC).
- Lâmina and CDA META directories:
  <https://dados.cvm.gov.br/dados/FI/DOC/LAMINA/META/>,
  <https://dados.cvm.gov.br/dados/FI/DOC/CDA/META/> (live; both hold only a
  zip, not read here; the lâmina dictionary is quoted from
  `lamina-coverage.md` § 1).
- etfsbrasil.com.br fund page:
  <https://www.etfsbrasil.com.br/fundos/50197313000150> (live). Secondary site, used only to test claim d.
- SILO warehouse, read-only: `cvm_fund_registry`, `cvm_fi_extrato`,
  `cvm_fi_lamina`, `cvm_fi_cda_cotas`, `fact_fund_monthly` (Supabase project
  `zcjbtpxuhdekpwcxmepn`). Code read: `src/pipeline/ingest_misc.py`,
  `src/parsers/field_maps/fund_registry.py`,
  `src/store/migrations/64_fund_registry_fees.sql`.
- Related notes: [`extrato-coverage.md`](extrato-coverage.md),
  [`lamina-coverage.md`](lamina-coverage.md),
  [`portfolio-diagnosis-phase0.md`](portfolio-diagnosis-phase0.md).
