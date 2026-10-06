# How to show and restructure the portfolio diagnosis report for a consultancy CIO

Question from the owner ("Peu"): what is the best way to show and restructure the SILO portfolio diagnosis report so a consultancy CIO finds it intuitive? He called the report "pouco intuitivo" and gave no more detail, so the causes below were found by reading and rendering the real report.

Measured 2026-10-06 from 13:30 to 13:48 UTC-3 (16:30 to 16:48 UTC). Every source was read on 2026-10-06 in that window; each row of section 2 gives its own time. Read: `AGENTS.md`; `docs/reference/portfolio/redator-revisor.md`, `engine-output.md` (headings and the returns section only) and `brief-client-fit.md`; `src/portfolio/report/render.py` (`_brief`, `render_html`) and `templates/`; the demo report rendered from `tests/fixtures/portfolio/demo_engine_output.json` with `--provider fake`, as HTML (screenshots at 390 px and 1200 px, Playwright and Chromium) and as a 37-page PDF (WeasyPrint, `pdftotext`, page images). Outside the repo: the 29 pages and documents listed in section 2. Nothing was written to SILO, to the database or to the report code, templates, tests or engine. The demo data is synthetic. The screenshots stayed in `/tmp` and are not committed.

How this note was checked: a research subagent wrote it, and the session that ordered it re-read two of its sources on 2026-10-06 (NN/G, "Progressive Disclosure"; GOV.UK Design System, "Details"). Their quotes in rows Q4 and Q5 match the pages word for word. The other quotes were not re-read. The audit counts (pages, words, "L1" uses) come from the synthetic demo report rendered with `--provider fake`.

One limit on the audit: `--provider fake` writes the findings with a template writer. A real Redator run words the findings differently. The structure, the tables, the charts and the fixed text are the same in both, and the audit points rest on those.

## Answer

The report is not hard to read because it is long. It is hard to read because it is built in the order the engine computes things, and not in the order a CIO asks questions. Seven causes, each seen in the real report (section 1):

1. **The answer is not first.** Page 1 is a brief, but it lists counts ("10 of 12 lines identified") and the first three statement lines, not the three things that matter. It has no verdict sentence and no list of what to check with the client.
2. **On screen, 35 pages sit behind one toggle.** There is no table of contents. The PDF prints everything, again with no map.
3. **The vocabulary is the engine's.** "L1" to "L12" appear about 228 times. Raw words (`nao_avaliado`, `close_total_return`, `fund_nav`), repo paths (`src/portfolio/risks.py`), "nota #611" and 27 `api.*` function names reach the reader.
4. **The same fact appears many times.** The fee total appears 6 times, one caveat paragraph 5 times word for word, one restatement about 8 times, and the appendix "Resumo" repeats the brief.
5. **The tables put the answer last.** The risk table has 5 columns and 14 rows. The returns table has 8 columns and is 1,915 px wide in a 1,200 px window. On a phone the return column is off screen.
6. **Every row is hedged, so no hedge stands out.** "a conferir" appears about 52 times and "estimativa" about 36 times. The real gaps are a 16-bullet list on page 35.
7. **The headline cost hides its coverage.** "R$ 16.851,55 por ano" covers 24,35% of the value held in funds. 32,65% has a fee range (kept apart) and 43,00% has no usable fee. Page 1 says "não representa custo total" but not how much it covers.

The fix is a different order and a different form, not less content. Put one page first: who, three or four findings with descriptive titles, the cost in R$ a year with its coverage, and one line on what was not assessed. Then eight short sections, each opening with its answer. Move the line-by-line tables, the methodology and the thresholds to an annex. Say each caveat once, next to the number it changes. Name every position by its name and not by "L5". Section 3 holds the table. Sources support the order, the forms and the language. Rows that rest on my judgement say so.

Two honest limits on the sources. CVM's own lâmina (Suplemento B) is a retail document with a fixed order, and CVM found it almost unused, so it is not a model to copy (section 2c). GIPS governs managers' composites and does not apply to a diagnosis (section 2d).

## 1. Audit of the current report

### 1.1 What the reader sees, in order

On screen the page is the brief, the declared constraints, one collapsed block ("Apêndice: análise completa") and the sources and disclaimer. Everything else is inside the block. In the PDF the block prints open. Page counts come from the position of each heading in the demo PDF (37 pages); they are approximate to a quarter page. Word counts are from the demo HTML, SVG text excluded.

| # | Section | PDF pages | About | Words | Form |
| - | ------- | --------- | ----- | ----- | ---- |
| 1 | Brief para a reunião | 1 | 1 | - | text, bullets (own page by CSS) |
| 2 | Restrições declaradas do cliente | 2 | 0,25 | - | 4 lines; 2 print raw `nao_avaliado` |
| 3 | Resumo (+ Achados que ninguém pegaria à mão) | 2-3 | 1,25 | 409 | 8 findings; 3 are the same restatement |
| 4 | Principais riscos | 3-5 | 2,25 | 760 | 14-row, 5-column table |
| 5 | Quanto a carteira paga em taxas | 5-6 | 1 | 282 | big number, 3 bullets, 5-bullet "não incluído" list |
| 6 | Identificação linha a linha | 6-7 | 1,25 | 389 | 7-column table, 12 rows |
| 7 | Crédito direto no registro da CVM | 7-8 | 1 | 188 | 7-column table |
| 8 | Custo em taxas | 8-12 | 5 | 1,420 | 3 tables, 1 chart; peer comparison (1 of 6 funds compared) |
| 9 | Exposição | 13-19 | 6,5 | 3,093 | 5 tables, 8 charts (5 are flow diagrams) |
| 10 | Concentração e vencimentos | 19-22 | 3 | 676 | 6 tables, 4 charts |
| 11 | Liquidez | 22 | 0,5 | 297 | table, chart |
| 12 | Retorno por posição | 22-27 | 4,5 | 1,635 | 8-column table, 18 rows |
| 13 | Taxa e imposto por posição | 27-31 | 4 | 1,662 | table with long legal text per cell |
| 14 | Equivalente de mercado | 31-33 | 2,25 | 434 | table, prose |
| 15 | Reapresentações | 33 | 0,5 | 201 | table + 3 prose findings |
| 16 | Sinais de risco | 33-35 | 1,25 | 447 | 2 tables, no chart |
| 17 | O que não foi possível avaliar | 35 | 0,75 | 351 | 16 bullets |
| 18 | Metodologia e limitações | 35-37 | 2 | 1,269 | bullets, all thresholds |
| 19 | Fontes e datas, Aviso, assinatura | 37 | 0,75 | - | lists |

The whole document has 24 tables, 14 charts and about 13,000 words. `render_html` follows the order of the engine blocks, not the order of a reader's questions.

### 1.2 Where a CIO gets lost

Each point has what I saw and where.

**A1. The first page does not say what matters.** Section "Brief para a reunião", page 1 (HTML and PDF). It opens with "Carteira: R$ 6,2 milhões · posições: 12 · não identificadas: 2", then "A carteira em uma frase: Das 12 linhas do extrato, 10 foram identificadas nos dados públicos." That sentence is data coverage, not a finding about the portfolio. The brief shows no verdict, no "points to check" and no client label. The lower third of the page is empty in the PDF.

**A2. The brief picks rows by position, not by weight.** `_brief` takes `list(enumerate(ret.get("lines")))[:3]` and the first three risk rows. In the demo the risk rows come sorted by severity, so that works. The returns do not: they are lines L1 to L3. Page 1 prints "L1: não avaliado; ." with an empty reason and a dangling semicolon, then two lines with the raw words `close_total_return` and `fund_nav`. "12m: cobertura 72,45%. Sem retorno total da carteira." appears for 12m and 6m without saying what "cobertura" means.

**A3. The cost is stated twice on page 1 and six times in the document.** Page 1 has a finding "Custo" and a block "Taxas" with the same R$ 16.851,55. The appendix "Resumo" (page 2) repeats the brief's three findings word for word. This is the pattern the SEC handbook warns about (Q9).

**A4. One toggle hides 35 pages.** On screen, at 390 px and 1200 px, the closed page is 1,968 px and 1,383 px tall. Opened, it is 44,959 px and 28,045 px. There is no table of contents, no section links and no per-section toggle. The only link is "Abrir análise detalhada", which also prints as a dead link in the PDF. The PDF has 37 pages and no map.

**A5. Internal codes reach the reader.** "L1" to "L12" appear about 228 times, and the risk, fee and return tables identify a row by "L5". `nao_avaliado` is printed raw in "Restrições declaradas do cliente" ("Horizonte: nao_avaliado."). The risk section prints "Os limites estão no código do motor (src/portfolio/risks.py)". The tax section prints "src/portfolio/rules/tax/ (nota #611)"; "nota #611" appears 7 times. The sources list holds 27 `api.*` function names. About 52 citations such as "[p17]" and "[p1, p2, p3, p4, p5, p7, p8]" follow the findings, and nothing in the report maps "p17" to a source.

**A6. The same caveat is repeated.** Section "Exposição", flow diagrams "De onde vem a exposição ao mesmo ativo": the paragraph "A parte via fundo é a carteira do fundo no mês da CDA, não na data do extrato; ..." sits under each of 5 diagrams, word for word. The restatement of "MN I FUNDO DE INVESTIMENTO EM DIREITOS CREDITORIOS" appears once in "Resumo" (page 2), three times as "Inadimplência revista depois da entrega" (pages 2-3), once as a risk-table row (page 4), and in "Reapresentações" as a table and three more findings (page 33).

**A7. Wide tables.** Section "Principais riscos": 5 columns (risk, value, level, what it measures, thresholds) and 14 rows. The "Limites" column repeats thresholds that are the same for every portfolio. Section "Retorno por posição": 8 columns (line and base, window, net return, CDI, net minus CDI, volatility, maximum drawdown, and a "taxa por ponto e perda de Sharpe" cell) and 18 rows. At 1,200 px the table is 1,915 px wide and the page scrolls sideways. At 390 px the screenshot shows only "Linha e base" and "Janela"; the return itself needs a sideways swipe.

**A8. Jargon and units in a cell.** "LFT (linha agregada sintética)", "BRSTNCLF1S08", "CDA bloco 4", "p.p.", "Sharpe", "defasada", "semáforo". A CIO knows most market terms. But the report coins its own words (see A5) and never defines "a conferir" once.

**A9. Hedging everywhere.** "a conferir" about 52 times, "estimativa" about 36 times, "não avaliado" about 23 times. Tags sit inside cells ("estimativa, não divulgada") and in text. The reader cannot tell the caveat that changes the answer (the fee covers a quarter of the fund value) from a method note.

**A10. The limits come last.** "O que não foi possível avaliar" is 16 bullets on page 35, after the reader has read 34 pages. Three bullets are "Retorno por posição" and two are "Equivalente de mercado".

**A11. Sections that say little.** "Taxas versus fundos comparáveis" compares 1 fund and prints "não comparado" for 5. "Restrições declaradas do cliente" is a note and three lines when nothing was declared, two of them raw `nao_avaliado`.

**A12. Order follows the engine.** Identification, then credit, then fees, then exposure. A CIO asks first what is wrong or notable, then what it costs, then what it holds. Identification is a method step, not a finding. "Exposição" alone is 3,093 words, mostly repeated caveats.

Screenshots kept in `/tmp/shots` (not committed): `closed_390.png`, `closed_1200.png` (the closed page; A1, A4); `o1200_01.png` (risk table; A7); `o1200_04.png` (fee comparison; A11); `o1200_07.png` (repeated caveat under flow diagrams; A6); `ret.png` (returns table; A7); `m390_risk.png`, `m390_ret.png` (phone; A7); `p80-01.png`, `p80-35.png` (PDF pages 1 and 35; A1, A10).

What already works and stays: the fee headline block ("R$ 16.851,55 por ano · 0,27% da carteira ao ano · taxa de administração divulgada, somada nos fundos com taxa fixa"), the "Não incluído no total" list, the level word printed next to each severity dot, the "não é recomendação" labels, the inline-SVG charts, and the print rule that opens the appendix in the PDF. The text colours pass 4,5:1 in my calculation (smallest: `#6b7280` on white, 4,83:1; `#92400e` on `#fef3c7`, 6,37:1).

## 2. Evidence by question

Each row: the claim, the page, the time it was read (UTC-3, UTC in parentheses) and the verbatim quote. "Analogy" marks a source from another field or a different reader; it supports a design principle, not a rule for this report.

### 2a. Order and depth: answer first, then evidence

| ID | Source | Read | Verbatim quote |
| -- | ------ | ---- | -------------- |
| Q1 | NN/G, Amy Schade, "Inverted Pyramid: Writing for Comprehension", 2018-02-11, <https://www.nngroup.com/articles/inverted-pyramid/> | 13:30 (16:30) | "Start content with the most important piece of information so readers can get the main point, regardless of how much they read." And: "Frontload all elements of content with important information. The main headline should be descriptive. The story should start with the main point. Each heading or subheading should be descriptive." |
| Q2 | NN/G, Rachel Krause, "Creating Engaging Reports & Asynchronous Presentations", 2022-04-03, <https://www.nngroup.com/articles/engaging-reports-presentations/> | 13:30 (16:30) | "Structure Your Report for 3 Audiences". "Just the headlines: The headlines should be aimed towards someone who is likely not involved in the day-to-day inner working of the project, but needs to be kept in the loop to make high-level decisions. If they were to read only the headlines, they should still be able to make sense of the research." "The big themes: These include the top takeaways ... but not the nitty-gritty details of how you got there." "In-depth details: Data-driven team members ... appreciate the details on process and methodology". |
| Q3 | NN/G, Rachel Krause, "Turning Complex Data into Compelling Stories: A 5-Step Process", 2020-07-19, <https://www.nngroup.com/articles/complex-data-compelling-stories/> | 13:30 (16:30) | "A common mistake ... is organizing their deliverable — whether it’s a report or slide deck of findings — in a chronological order that matches what happened in the research study ... When you’re running through your data chronologically, your artifact becomes an account of what participants did in the study instead of a story of the central questions that your audience cares about." "Start by writing a one-sentence headline that captures each theme". Its example: "Most UX Professionals Are Satisfied with Their Careers" against "Career Satisfaction". |
| Q4 | NN/G, Jakob Nielsen, "Progressive Disclosure", 2006-12-03, <https://www.nngroup.com/articles/progressive-disclosure/> | 13:30 (16:30) | "Progressive disclosure defers advanced or rarely used features to a secondary screen, making applications easier to learn and less error-prone." "You have to disclose everything that users frequently need up front, so that they have to progress to the secondary display only on rare occasions." "In a system designed with progressive disclosure, the very fact that something appears on the initial display tells users that it's important." "designs that go beyond 2 disclosure levels typically have low usability because users often get lost when moving between the levels." |
| Q5 | GOV.UK Design System, Details, <https://design-system.service.gov.uk/components/details/> | 13:31 (16:31) | "Use the details component to make a page easier to scan when it contains information that only some users will need." "Do not use the details component to hide information that the majority of your users will need." |
| Q6 | GOV.UK Design System, Accordion, <https://design-system.service.gov.uk/components/accordion/> | 13:31 (16:31) | "Accordions hide content from the user. Not all users will notice them or understand how they work." "Do not use an accordion for content that all users need to see." |
| Q7 | NN/G, Jakob Nielsen, "How Users Read on the Web", 1997-09-30, <https://www.nngroup.com/articles/how-users-read-on-the-web/> | 13:30 (16:30) | "79 percent of our test users always scanned any new page they came across; only 16 percent read word-by-word." Its scannable-text list includes "the inverted pyramid style, starting with the conclusion" and "half the word count (or less) than conventional writing". Analogy: a 1997 web study. |
| Q8 | NN/G, Jakob Nielsen, F-shaped pattern (original eyetracking study), <https://www.nngroup.com/articles/f-shaped-pattern-reading-web-content-discovered/> | 13:30 (16:30) | "Start subheads, paragraphs, and bullet points with information-carrying words that users will notice when scanning down the left side of your content in the final stem of their F-behavior." Analogy: a web-page study, not a print report. |
| Q9 | SEC, "A Plain English Handbook", Office of Investor Education and Assistance, August 1998, <https://www.sec.gov/pdf/handbook.pdf> (the first request got HTTP 403; a second one with a browser user agent opened the PDF) | 13:32 (16:32) | "A summary should orient the reader, highlighting the most important points that are presented in greater detail in the prospectus. Many summaries now seem as long as the document itself and consist merely of paragraphs copied straight from the body of the document." Under "Eliminate redundant information": "Question the need for repeating any information. Reading the same material two or three times can bore and even trouble readers. Most readers skip over paragraphs if they think they’ve read them before." |
| Q10 | SEC handbook, Appendix text of Rule 421(d), same PDF | 13:32 (16:32) | "To enhance the readability of the prospectus, you must use plain English principles in the organization, language, and design of the front and back cover pages, the summary, and the risk factors section." (The PDF prints the paragraph mark as "(d) ( )".) Minimum principles: "(i) Short sentences; (ii) Definite, concrete, everyday words; (iii) Active voice; (iv) Tabular presentation or bullet lists for complex material, whenever possible; (v) No legal jargon or highly technical business terms; and (vi) No multiple negatives." Scope: a US prospectus. Analogy only. |
| Q11 | Minto Pyramid Principle, publisher page, <https://www.barbaraminto.com/> | 13:39 (16:39) | "The Minto Pyramid Principle says that your thinking will be easy for a reader to grasp if you present the ideas organized as a pyramid under a single point." And: "It has become a standard text used by all of the major consulting firms, many large corporations, and some government offices." The page gives only this one-sentence statement of the method; I did not read the book. |

What this supports: put the conclusion first (Q1, Q9, Q11), write each heading as a finding (Q1, Q3), serve three depths (Q2), keep the first display for what most readers need and push the rest down one level (Q4, Q5), and do not hide what most readers need (Q5, Q6). The "3 audiences" and Minto's reach in consulting firms suit a consultancy CIO well. NN/G warns against ordering by how the analysis ran (Q3), which is what the engine-order report does.

### 2b. Tables, charts or text

| ID | Source | Read | Verbatim quote |
| -- | ------ | ---- | -------------- |
| Q12 | Stephen Few, "Effectively Communicating Numbers: Selecting the Best Means and Manner of Display", Perceptual Edge, November 2005, <https://www.perceptualedge.com/articles/Whitepapers/Communicating_Numbers.pdf> | 13:32 (16:32) | "Tables work best when the display will be used to look up individual values or the quantitative values must be precise. Graphs work best when the message you wish to communicate resides in the shape of the data (that is, in patterns, trends, and exceptions)." "If you need to do some of both, then display the data in both ways: in a table and in a graph." In his relationship table: Ranking: "Bars (horizontal or vertical)"; Time-Series: "Lines to emphasize the overall shape of the data"; Part-to-Whole: "Pie charts are commonly used to display part-to-whole relationships, but they don’t work nearly as well as bar graphs because it is much harder to compare the sizes of slices than the length of bars." |
| Q13 | Stephen Few, "Dashboard Design for Real-Time Situation Awareness", <https://www.perceptualedge.com/articles/Whitepapers/Dashboard_Design.pdf> | 13:32 (16:32) | "The term “dashboard” refers to a single screen information display that is used to monitor what’s going on in some aspect of the business." "By placing all of the information that you need to monitor (at least at a high level) on a single screen, simultaneously available to our eyes, we work around the limitations of short term memory by reducing the need to rely on it." Analogy: a monitoring display; used only for the idea of one screen. |
| Q14 | Edward Tufte, "Sparkline theory and practice", <https://www.edwardtufte.com/notebook/sparkline-theory-and-practice-edward-tufte/> | 13:32 (16:32) | "A sparkline is a small intense, simple, word-sized graphic with typographic resolution." "Sparklines have obvious applications for financial and economic data— by tracking and comparing changes over time, by showing overall trend along with local detail. Embedded in a data table, this sparkline depicts an exchange rate" |
| Q15 | NN/G, Page Laubheimer, "Data Tables: Four Major User Tasks", 2022-04-03, <https://www.nngroup.com/articles/data-tables/> | 13:30 (16:30) | "The default order of the columns should reflect the importance of the data to the user and related columns should be adjacent." The first column "should be a human-readable record identifier instead of a “mystery meat” automatically generated ID". "Sometimes the columns users wish to compare are far away from each other — with one being even perhaps off canvas and requiring horizontal scrolling to view." |
| Q16 | W3C, WCAG 2.1 (page shows "W3C Recommendation 06 May 2025"), <https://www.w3.org/TR/WCAG21/> | 13:32 (16:32) | 1.4.1 Use of Color: "Color is not used as the only visual means of conveying information, indicating an action, prompting a response, or distinguishing a visual element." 1.4.3 Contrast (Minimum): "The visual presentation of text and images of text has a contrast ratio of at least 4.5:1, except for the following:" 1.4.11 Non-text Contrast, "Graphical Objects": "Parts of graphics required to understand the content". |
| Q17 | FDA, "Communicating Risks and Benefits: An Evidence-Based User’s Guide", 2011, <https://www.fda.gov/media/81597/download>, Chapter 7 | 13:39 (16:39) | "Describing risks solely with words, such as You have a low chance of experiencing a side effect is ineffective." "Reduce the amount of information shown as much as possible. ... with more information, patients may not know where to focus their attention and what information should be most important in their decisions." "Take care using interpretive labels or symbols to convey the meaning of important information." Analogy: health risk, lay readers. |
| Q18 | SEC handbook (same PDF as Q9), "Use tables to increase clarity" | 13:32 (16:32) | "Use tables to increase clarity and cut down text. Tables often convey information more quickly and clearly than text." |

What this supports, by content type:

- **A cost total:** one number in text, big, with its unit and its base; no chart. A single value is a look-up, which Few puts in text or a table (Q12). The per-fund cost is a ranking, so horizontal bars with the value written on each bar (Q12); the existing chart already does this.
- **A ranking of exposures:** horizontal bars with labels in the body; the exact table in the annex (Q12: both when you need both). No pie (Q12).
- **A return series against a benchmark:** the reader needs two or three precise numbers (return, CDI, difference), so a short table (Q12, Q18). A sparkline per row adds the shape (Q14, and Q12 "shape of the data"). The engine carries `month_ends[]` for each line. I did not check whether it carries a month-end CDI series, so whether a sparkline can also show the CDI is open (section 5).
- **Risk flags:** a table with the number, the level word and one sentence. The number beside the label (Q17, first quote) and the word beside the dot (Q16, 1.4.1). The amber dot has 1,83:1 against white in my calculation. It carries no meaning alone, so 1.4.11 is not triggered, but keep the word.
- **A list of documents:** a short table in a fixed column order, name first (Q15).
- **Every table:** the position's name in the first column and the answer in the next (Q15). A table wider than the page is a layout defect (Q15, third quote); keep each body table to about four columns.

### 2c. What a regulated Brazilian investor document puts first

Read from the publishers. The term in force is "lâmina de informações básicas"; the heading inside the model still says "LÂMINA DE INFORMAÇÕES ESSENCIAIS". The ticket text used the second name.

| ID | Source | Read | Verbatim quote |
| -- | ------ | ---- | -------------- |
| Q19 | CVM, Resolução CVM 175, Suplementos (Suplemento B, lâmina de FIF), <https://conteudo.cvm.gov.br/export/sites/cvm/legislacao/resolucoes/anexos/100/resol175consolid_Suplementos.pdf> | 13:38 (16:38) | "SUPLEMENTO B – LÂMINA DE INFORMAÇÕES BÁSICAS – FIF". Opening: "Esta lâmina contém um resumo das informações essenciais sobre o [nome completo do fundo e, se for o caso, da classe de cotas], administrado por [...]. As informações completas sobre esse fundo podem ser obtidas em seu Regulamento ... Antes de investir, compare a classe de cotas com outras classes da mesma categoria." Items 1 to 12, in order: "1. PÚBLICO-ALVO", "2. OBJETIVOS DA CLASSE DE COTAS", "3. POLÍTICA DE INVESTIMENTOS", "4. CONDIÇÕES DE INVESTIMENTO", "5. COMPOSIÇÃO DA CARTEIRA: ... as 5 espécies de ativos em que a carteira concentra seus investimentos são", "6. RISCO: o [nome do gestor] classifica as carteiras de ativos que administra numa escala de 1 a 5", "7. HISTÓRICO DE RENTABILIDADE" (the model offers "[HISTÓRICO DE RENTABILIDADE ... (para todos os fundos, exceto os estruturados)] OU [SIMULAÇÃO DE DESEMPENHO (para fundos estruturados)]"), "8. EXEMPLO COMPARATIVO", "9. SIMULAÇÃO DE DESPESAS", "10. POLÍTICA DE DISTRIBUIÇÃO DE COTAS", "11. SERVIÇO DE ATENDIMENTO AO COTISTA", "12. SUPERVISÃO E FISCALIZAÇÃO". Item 8: "Se você tivesse aplicado R$ 1.000,00 (mil reais) na classe de cotas ... você poderia resgatar R$[●], já deduzidos impostos" and "As despesas, incluindo a taxa de administração, [a taxa de performance (se houver) ], e as despesas operacionais e de serviços teriam custado R$[●]." Reference month at the top: "Informações referentes a [mês] de [ano]". |
| Q20 | CVM, Anexo Normativo I da Resolução 175, art. 14, <https://conteudo.cvm.gov.br/export/sites/cvm/legislacao/resolucoes/anexos/100/resol175consolid_Anexo01.pdf> | 13:33 (16:33) | "O administrador de classe aberta que seja destinada ao público em geral deve elaborar lâmina de informações básicas e mantê-la atualizada." "§ 1º É facultado ao administrador formatar a lâmina livremente desde que: I – a ordem das informações seja mantida;" |
| Q21 | CVM, Edital de Consulta Pública SDM nº 07/25 (prazo 6 de março de 2026), <https://conteudo.cvm.gov.br/export/sites/cvm/audiencias_publicas/ap_sdm/anexos/2025/Edital_de_Consulta_Publica_SDM_0725.pdf> | 13:31 (16:31) | "A Lâmina, instituída pela Instrução CVM nº 522, de 2012, busca apresentar informações relevantes de forma comparável, acessível e amigável. Após mais de uma década, os dados indicam que a iniciativa não atingiu o seu propósito: em 2025, sua busca mensal nos sistemas da CVM representa cerca de 0,1% das contas ativas de fundos, evidenciando sua irrelevância como fonte de consulta." And: "as chamadas “lâminas comerciais”, de formato livre, podem fornecer resultados similares, ou até superiores, à “lâmina regulatória”." |
| Q22 | CVM, Ofício-Circular nº 6/2024/CVM/SIN, 15 de outubro de 2024, <https://conteudo.cvm.gov.br/cvm_institucional/export/sites/cvm/legislacao/oficios-circulares/sin/anexos/oc-sin-0624.pdf> | 13:35 (16:35) | "o gestor será responsável por disponibilizar em seu website o sumário de remuneração em área pública e de fácil acesso ao investidor." |
| Q23 | ANBIMA, OF. DIR. 009/2026 to CVM, 6 de março de 2026, <https://www.anbima.com.br/data/files/99/06/03/3D/B402D910BD15EFC9F82BA2A8/OF_DIR_009_2026_Regime%20Informacional%20FIF%20-Assinado.PDF> | 13:39 (16:39) | "a adoção de uma linguagem mais acessível e alinhada ao investidor é elemento central para estimular o interesse e o uso efetivo dos informes." "o uso excessivo de linguagem técnica e formal, que pode reduzir o engajamento dos investidores com as informações disponibilizadas." |
| Q24 | SEC handbook (same PDF as Q9), jargon | 13:32 (16:32) | "Ruthlessly eliminate jargon and legalese. Instead, use short, common words to get your points across. In those instances where there is no plain English alternative, explain what the term means when you first use it." And: "Last, don’t create new jargon that’s unique to your document in the form of acronyms or other words. It’s asking too much of your readers to memorize a new vocabulary while they are trying to understand complicated concepts. This holds true for individual and institutional investors." |
| Q25 | GOV.UK, A to Z style guide, <https://www.gov.uk/guidance/style-guide/a-to-z-of-gov-uk-style> | 13:31 (16:31) | "All content on GOV.UK should be written in plain English. You should also make sure you use language your audience will understand" (the sentence goes on). Also: "If you have to publish legal jargon, it will be a publication so write a plain English summary." |

What this supports, with care:

- The CVM lâmina is for a retail investor choosing a fund. It opens with a one-paragraph "what this is" and "compare before you invest" (Q19). Then come who it is for, objective and policy, the five largest asset types, a 1-to-5 risk scale, history, and costs in R$ for R$ 1.000 (items 8 and 9). It ends with distribution, service and supervision (items 10 to 12). Cost sits near the end. A CIO who reviews a portfolio is a different reader, so the order is not a template.
- What to borrow, as ideas and not as rules that bind this report: a one-paragraph opening that says what the document is and is not; the top five holdings by type; costs written in reais and not only in percent; a short scale for risk; the reference month at the top.
- CVM itself found the fixed lâmina almost unused (0,1% of active accounts) and proposed to drop it in favour of free-format "lâminas comerciais" (Q21). A fixed form is not proof of an intuitive one. Whether CVM adopted the proposal after the 6 March 2026 deadline is not verified.
- CVM has a "sumário de remuneração", a fee summary that must be easy to reach (Q22). The regulator treats fee transparency as its own summary. This supports a fee box on page 1; it is a weak source for placement.
- On plain language: ANBIMA names "linguagem técnica e formal" as a cause of low use (Q23). I did not find a CVM page titled "linguagem simples" (section 5). So the plain-language rules come from the SEC handbook (US), which names "individual and institutional investors" (Q24), and from GOV.UK (Q25). Both are analogy, not Brazilian rules.
- The Extrato das Informações has no reader-facing layout here: it is a 117-column data file (`extrato-coverage.md`). It is not used.

### 2d. How professional reporting standards order a performance and cost report

| ID | Source | Read | Verbatim quote |
| -- | ------ | ---- | -------------- |
| Q26 | CFA Institute, GIPS Standards for Firms, 2020, <https://www.gipsstandards.org/wp-content/uploads/2021/03/2020_gips_standards_firms.pdf> | 13:38 (16:38) | Scope: "The GIPS standards are ethical standards for investment performance presentation to ensure fair representation and full disclosure of investment performance." "The GIPS standards require firms to create and maintain composites for all strategies for which the firm manages segregated accounts or markets to segregated accounts." |
| Q27 | Same, provisions 4.A.1 and 4.A.3 and Appendix A | 13:38 (16:38) | "4.A.3 The firm must clearly label or identify: a. The periods that are presented. b. If composite returns are gross-of-fees or net-of-fees." "4.A.1 ... e. The total return for the benchmark for each annual period and for all other periods for which composite returns are presented, unless the firm determines there is no appropriate benchmark." The sample composite report in Appendix A prints annual gross return, net return and benchmark return side by side in one table, with the notes as lettered footnotes (a), (b) under it. |
| Q28 | CFA Institute Research and Policy Center, "Investment Performance Reporting", 29 October 2019, <https://rpc.cfainstitute.org/policy/positions/investment-performance-reporting> | 13:39 (16:39) | "The best performance reports give up-to-date information about fund performance in a consistent, accessible, and understandable manner." "Investment performance must be fairly represented and fully disclosed. Information regarding the risks taken, the costs incurred, and the results achieved allow investors to understand their portfolio’s performance and fairly evaluate their investment managers." |
| Q29 | CFA Institute, Standard V(B) Communication with Clients and Prospective Clients, <https://www.cfainstitute.org/standards/professionals/code-ethics-standards/standards-of-practice-v-b> | 13:39 (16:39) | "Distinguish between fact and opinion in the presentation of investment analysis and recommendations." "Disclose to clients and prospective clients significant limitations and risks associated with the investment process." "In the case of complex quantitative analyses, members and candidates must clearly separate fact from statistical conjecture and must identify the known limitations of an analysis." |

Where GIPS does not apply, in plain words. GIPS governs investment managers that claim compliance for their composites (Q26). A diagnosis of one client's statement is not a composite, the author is not a manager and no one claims compliance. I read only the Overview, provisions 4.A.1 to 4.A.3 and the Appendix A samples of a 146-page document. I saw no rule on page order, but I did not search all of it. What carries over as practice, not as compliance:

- Label the period and whether a return is net or gross of fees (Q27). The report already carries a basis label per line; it should be a column header, not text in each cell.
- Put the benchmark next to the return in the same table (Q27). The report does this with the CDI; keep it.
- Present measured facts apart from estimates and state known limits (Q29). The report's "estimativa" labels match this. The CFA texts support the labels; they do not support repeating them in every cell.
- Present risks, costs and results as the three things an investor needs (Q28). This supports a first page with those three.

### 2e. Warnings and caveats without burying the answer

| ID | Source | Read | Verbatim quote |
| -- | ------ | ---- | -------------- |
| Q30 | NN/G, Neusesser and Sunwall, "Error-Message Guidelines", 2023-05-14, <https://www.nngroup.com/articles/error-message-guidelines/> | 13:30 (16:30) | "Display the error message close to the error's source." "Design errors based on their impact. Design your error messages to indicate the problem's severity." "Avoid technical jargon and use language familiar to your users instead." "Hide or minimize the use of obscure error codes or abbreviations; show them for technical diagnostic purposes only." Analogy: error messages in interfaces; used for placement, severity and code words. |
| Q31 | NN/G, Kim Flaherty, "Indicators, Validations, and Notifications", 2024-01-17, <https://www.nngroup.com/articles/indicators-validations-notifications/> | 13:30 (16:30) | "The best way to communicate system status varies depending on several key factors:" the list is "The type of information being communicated", "The urgency of the information — how important it is that the user sees it immediately" and "Whether the user needs to take action as a result of the information". |
| Q32 | GOV.UK Design System, Warning text, <https://design-system.service.gov.uk/components/warning-text/> | 13:31 (16:31) | "Use the warning text component when you need to warn users about something important, such as legal consequences of an action, or lack of action, that they might take." |
| Q33 | GOV.UK Design System, Inset text, <https://design-system.service.gov.uk/components/inset-text/> | 13:31 (16:31) | "Use inset text very sparingly - it’s less effective if it’s overused." "Some users do not notice inset text if it’s used on complex pages or near to other visually prominent elements. For this reason, avoid using inset text as a way of highlighting very important information that users need to see." |

What this supports. Sort caveats by what they change, as NN/G sorts messages by impact (Q30, Q31):

1. A caveat that changes the headline goes into the headline sentence, because boxes get missed (Q33) and a warning component is for something important (Q32). Example: "R$ 16.851,55 por ano, em fundos com taxa fixa divulgada que somam 24,35% do valor em fundos; 32,65% têm só uma faixa de taxa (à parte) e 43,00% não têm taxa utilizável."
2. A caveat that changes one section is one line under that section title, next to the numbers it changes (Q30, "close to the source").
3. A method note goes once into the methodology, not under every chart (Q9, "Eliminate redundant information").
4. Code words ("a conferir" as a tag, enums) are shown once with a plain meaning, and the raw code stays in the run trace (Q30, Q24).

Keep the number beside any level word (Q17) and keep fact and estimate labelled apart (Q29).

## 3. Recommendation

### 3.1 Proposed order, form and what moves

"Fonte" gives the evidence ID from section 2. "Juízo" means the row rests on my judgement with no source. A row can have both: the source supports the principle and my judgement sets the detail.

| # | Proposed section (Portuguese title) | What the reader learns | Best form and why | Cut or move | Rename | Fonte |
| - | ----------------------------------- | ---------------------- | ----------------- | ----------- | ------ | ----- |
| 1 | **Resumo para a reunião** (page 1 only) | Who and when; the three or four findings; the cost per year and how much of the portfolio it covers; what was not assessed; where to read more | Text and one cost box. Header strip (value, number of positions, reference date, identified share, declared constraints or "restrições não informadas"). One opening sentence. 3-4 findings, each a descriptive title plus one line with the number. Cost box. One line "não avaliado". Contents list with links | From the brief: the "A carteira em uma frase" coverage sentence (moves to the strip), the duplicate "Custo" and "Taxas", the first-three-lines returns block, the "cobertura" lines, the "Limitações" paragraph (becomes one line) | "Brief para a reunião" to "Resumo para a reunião" (Juízo: "brief" is English). Keep the page break after it | Q1, Q2, Q9, Q11, Q13 (one page), Q19 (opening, reference month, costs in R$). Header strip and the pick of 3-4 findings: Juízo |
| 2 | **O que pede atenção** | Which risk rows are at "atenção" or "moderado", with the number | Table of 4 columns: risk, value, level (word plus dot), one sentence. Only rows at atenção or moderado; the rest in the annex | The "Limites" and "O que mede" columns go to the annex table and the methodology; the "Risco no maior nível do semáforo" paragraph (repeats the first row) | "Principais riscos" to "O que pede atenção"; "Semáforo" to "Nível" | Q15 (importance order, 4 columns), Q16 (word beside dot), Q17 (number beside label), Q10 (tabular). Showing only moderate and above: Juízo |
| 3 | **Quanto a carteira paga em taxas** | The R$ per year, the share of fund value it covers, what is outside it | Big number in text with its base; per-fund horizontal bars (existing chart); the "Não incluído no total" list kept as 4-5 bullets | Merge with "Custo em taxas": peers table, fund-of-funds table and per-fund fee table go to the annex; the peers table stays in the body only if 2 or more funds compare | "Custo em taxas" becomes the annex block "Taxa por fundo" | Q12 (bars for a ranking, text for one value), Q19 (R$ and not only %), Q22 (the fee summary is its own item). The headline block stays as is |
| 4 | **O que a carteira tem** (exposição) | What the money is in, and where one asset sits under several funds | Bar chart by asset class; table of the 10 largest underlying assets; one table "mesmo ativo em mais de uma posição", plus the flow diagram for the largest overlap only | The other 4 flow diagrams go to the annex; the repeated caveat paragraph is said once under the table; "Indexador" and "Setor" charts go to the annex unless one bucket is flagged by the engine | "Exposição" to "O que a carteira tem"; "Sobreposição" to "Mesmo ativo em mais de uma posição"; "LFT (linha agregada sintética)" to "Tesouro Selic (LFT), posições somadas" (Juízo on wording) | Q12 (bars, no pie), Q9 (say once), Q19 (top 5 by type). One diagram in the body: Juízo |
| 5 | **Concentração e liquidez** | The largest issuer, fund and manager; how much is out of reach by D+30 | One table of 4-5 rows (largest issuer, fund, manager, FGC check, share beyond D+30) with the same 4 columns as row 2; maturity bars | Merge "Concentração e vencimentos" and "Liquidez". The detail tables (issuers, funds, FGC by issuer, manager, maturity by year) go to the annex | One title for both | Q15, Q12. The merge: Juízo |
| 6 | **Retorno passado contra o CDI** | For each position that could be evaluated: return in 12 months, CDI, difference | Table of 4 columns: position name, 12m return, CDI, difference. A sparkline per fund row if the engine can supply it. Basis label as a column header and footnote | The 6-month window, volatility, drawdown, "taxa por ponto" and "perda de Sharpe" go to the annex. The 8-column table goes to the annex. The prose findings that restate the table are cut | "Retorno por posição" to "Retorno passado contra o CDI" | Q12 (precise values in a table), Q14 (sparkline), Q15 (importance order, no horizontal scroll), Q27 (label period and net or gross; benchmark beside) |
| 7 | **Imposto por posição** | The legal rate that applies per position, as a fact, with what is missing | Table of 4 columns: position, rate, basis (law in a footnote), what is missing ("a conferir" once, with its meaning) | Long legal text per cell goes to footnotes or the annex. "src/portfolio/rules/tax/" and "nota #611" leave the reader's text | "Taxa e imposto por posição" to "Imposto por posição" (fees are in row 3). Keep "informativo; não é recomendação" | Q10, Q24, Q30 (no code words). The split of fee and tax: Juízo |
| 8 | **Informes reapresentados e movimento incomum de cota** | Which funds re-filed a report or moved out of their class | One table of funds (fund, what happened, size of change) and at most one finding per fund | The 3 repeated findings merge by fund; the "Sinais de risco" class table goes to the annex | "Reapresentações" and "Sinais de risco" become one section | Q9 (no repeats), Q3 (one headline per theme). The merge: Juízo |
| 9 | **O que não foi possível avaliar** | The limits that change a reading, grouped by effect | Short list of 5-7 bullets grouped by what each changes (the fee, the return, the exposure), with R$ and the share of the portfolio. Full list in the annex | The 16 bullets go to the annex; the three "Retorno por posição" bullets become one | Keep the title; it is plain | Q29 (state limits), Q30 and Q31 (by impact). Placing it before the annex: Juízo |
| A | **Anexo** (opened by default in the PDF; on screen one toggle per block, 2 levels at most) | Line-by-line evidence for anyone who wants to check | Tables as today, each with the position name first | Moves in: identification line by line, direct credit table, fee per fund, peers, fund-of-funds table, the 4 other flow diagrams, indexer and sector, maturity and FGC tables, the 14-row risk table with thresholds, the full return table, tax facts, ETF equivalents, class table | "Identificação linha a linha" to "Como cada posição foi identificada"; "Equivalente de mercado" to "ETF comparável (não é recomendação)" | Q2 (in-depth tier), Q4 (two levels), Q5 and Q6 (hide only what a minority needs) |
| B | **Metodologia, fontes e aviso** (end) | How numbers were made, which data and dates, the fixed disclaimer, the signature | Bullets as today | The thresholds list is here, once. The `api.*` list and the "[p17]" citations leave the reader's text (kept in the run trace; render as numbered footnotes if the owner wants them visible). The signature and the disclaimer stay as they are | "Fontes e datas dos dados" stays | Q24, Q30 (diagnostic codes only for diagnostics). The disclaimer and signature stay: owner rule |

### 3.2 Page 1, as a mock (demo numbers; synthetic)

Every line below is fixed text with placeholders that the renderer resolves from the engine, as `_brief` does today. The Redator types no number. The Revisor rules 5 and 6 in `redator-revisor.md` bind Redator prose only, so the table-only "atenção" rule is not broken by a fixed title that names the level.

```
Diagnóstico de carteira                       Referência 30/09/2026 · gerado 03/10/2026
Carteira de R$ 6,2 milhões · 12 posições · 10 identificadas · restrições do cliente não informadas
[Exemplo com dados ilustrativos]

Em uma frase: três pontos a conferir com o cliente, e taxas de administração
divulgadas de R$ 16.851,55 por ano.

1. Um emissor passa do limite do FGC. BANCO EXEMPLO soma R$ 390.000,00, R$ 140.000,00 acima de R$ 250.000,00; a conferir: o limite é por CPF e instituição.
2. Duas posições são a mesma carteira por baixo. Duas linhas investem no mesmo fundo, XP BANCOS MASTER.
3. Um fundo de crédito reapresentou o informe. MN I FIDC mudou a inadimplência em três competências; sem avaliação de materialidade.
4. Um fundo saiu da faixa da sua classe. XP LIQUIDEZ, em 09/2026.

Custo      R$ 16.851,55 por ano  (0,27% da carteira)
           Só taxa de administração divulgada, em fundos que somam 24,35% do valor em fundos.
           32,65% têm só uma faixa de taxa (à parte) e 43,00% não têm taxa utilizável. Não é o custo total.

Não avaliado: 2 posições sem fonte pública (R$ 390.000,00); retorno de 6 posições.   Detalhes: seção 9.

Nesta análise: 2 Atenção · 3 Taxas · 4 O que a carteira tem · 5 Concentração e liquidez · 6 Retorno · 7 Imposto · 8 Informes e movimento · 9 Não avaliado · Anexo
Não é recomendação de investimento. Aviso na última página.
```

Items 1 to 4 reuse the engine's own findings and risk rows. Whether the single "Em uma frase" line can be built from placeholders alone, without a typed conclusion, is a design check for the owner.

### 3.3 What stays as it is

- The fee headline block and its "Não incluído no total" list.
- The level word printed beside each severity dot (Q16).
- The "não é recomendação" labels, the signature and the fixed disclaimer.
- The inline-SVG charts and the print rule that opens the annex in the PDF.
- The engine as the only source of numbers, and the Revisor.

### 3.4 Rows that rest on my judgement alone

- Show only moderate and above in the body table (row 2).
- Merge "Concentração" with "Liquidez", and "Reapresentações" with "Sinais de risco" (rows 5 and 8).
- One flow diagram in the body and four in the annex (row 4).
- The "Em uma frase" line and the choice of three or four findings (row 1).
- Split fee and tax into separate sections (row 7).
- "Resumo para a reunião" over "Brief" (row 1).
- About 10 pages of body and the rest in the annex. No source gives a page count. The nearest is "half the word count (or less)" (Q7), a web-writing rule.
- Place "O que não foi possível avaliar" before the annex (row 9).

## 4. Open questions for the owner

1. **Page 1 should say who the client is, but the report is masked.** The contract allows no name, no id and no free text (`brief-client-fit.md`). May the CIO type a display label after the build (not sent to the engine or the Redator), printed on page 1 only? *Recommendation:* yes. Without it, page 1 shows the reference date and the declared constraints, which carry no personal data.
2. **Is a list of "pontos a conferir na reunião" inside the "no recommendation" rule?** Each item would be a fact the engine already flags "a conferir" (FGC limit, restatement, shared exposure), with fixed wording and no action on any asset. *Recommendation:* yes, under that limit.
3. **Which channel is primary, the PDF or the HTML?** The brief says HTML on screen and PDF on request. A CIO who reviews before a meeting may print. *Recommendation:* design page 1 for paper first; the HTML adds the contents links.
4. **May the reader's text drop the `[p17]` citations and the `api.*` list?** They stay in the run trace (ADR 0003) and the Revisor rules do not change. In the report they become numbered footnotes or disappear. *Recommendation:* drop the `api.*` list from the report and render citations as numbered footnotes tied to "Fontes e datas".
5. **May page 1 carry one line pointing to the Aviso?** The disclaimer text and the signature do not change; only a pointer is added. *Recommendation:* yes.

## 5. Not verified

- **CVM "linguagem simples".** I found no CVM page with that title. Searches returned news items about a 2023 CVM survey (58% of 714 investors find market language hard). I did not open a CVM primary page for it, so it is not used.
- **Whether CVM adopted the proposal to drop the lâmina** (Edital SDM 07/25, deadline 6 March 2026). The Suplemento B text I read is the consolidated PDF as served on 2026-10-06.
- **ANBIMA codes on fund disclosure.** I read one ANBIMA primary document (the letter, Q23). I did not find or read the ANBIMA code or rule that sets the content of a "lâmina comercial".
- **Extrato das Informações layout.** Not re-read from CVM; `extrato-coverage.md` cites it. Not used here.
- **GIPS and page order.** Only the Overview, provisions 4.A.1 to 4.A.3 and the Appendix A samples were read. I saw no rule on page order, but 146 pages were not searched for one. CFA Institute materials on "client reporting" beyond Q28 and Q29 were not read.
- **Minto.** Only the publisher's one-sentence statement; no book.
- **FDA and EU.** The FDA guide is read (Q17) as an analogy for health risk. No EU plain-language risk-communication page was opened.
- **Few and Tufte.** Few's two papers and Tufte's sparkline page were read. Tufte's pages on small multiples and "The Visual Display of Quantitative Information" were not opened as a source.
- **Search tools.** Parallel Search and Firecrawl were rate- or credit-limited, so discovery used WebSearch and direct URLs. Exa was not tried (its server needs sign-in in this session). Every quote above comes from a page or PDF I opened and searched, not from a search snippet. Exception: the 2023 CVM survey figures in the first bullet are from a search summary and are not used.
- **The demo is synthetic and uses `--provider fake`.** A real Redator would write other findings. Page counts and word counts are for this demo.
- **Contrast.** I computed the 4,5:1 and 3:1 ratios from the CSS colours by hand. I did not run an accessibility tool and did not check the SVG chart colours.
- **Sparkline with CDI.** `returns.lines[].month_ends[]` exists. Whether the engine carries month-end CDI values for a second line was not checked.
- **No user test.** No CIO read the report. The causes come from reading and rendering it. NN/G itself says to test the result (Q4's source: "invest extra time in user testing").

## 6. Added by the owner after this note: performance attribution per asset

Request (owner, 2026-10-06): "um performance attribution de cada ativo", that is, how much each asset added to or took from the portfolio's return. This note did not research it, and no source here supports a design for it. What the repository already fixes, and what the request has to respect:

- The returns block (engine 1.10, `docs/reference/portfolio/engine-output.md`) gives each position its own net return over 12 and 6 months, the CDI over the same dates and the difference. The owner decided in ticket #606 that there is no portfolio total, because only part of the value has a return series (69,6% of the synthetic demo value).
- Attribution needs the weights at the start of the window and the cash flows in it. A statement gives positions at one date and no flows. Any figure built from one statement would assume the current positions were held through the window. It would be a back-cast, and the report would have to say so next to the number.
- A contribution per asset sums to a total for the part that has a return series. That total conflicts with the #606 rule unless the owner allows it, labelled with its coverage.
- Every number would come from the engine, as for the rest of the report. No LLM writes it.

Open question for the owner: is a back-cast contribution acceptable if it is labelled as one, with the coverage of the part it sums? The recommendation is yes. It stays out of the proposed order in section 3 until the owner decides.

