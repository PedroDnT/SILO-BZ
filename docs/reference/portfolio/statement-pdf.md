# BTG performance report: the PDF reader and the local runner

`src/portfolio/statement_pdf.py` reads the BTG "Relatório de Performance" (advisory co-branded, a
text layer) into the same `Statement` the spreadsheet reader produces, under the same hard rules.
`src/portfolio/consolidate.py` joins several accounts into one portfolio. **No real statement was
opened in building this**: the reader was written from a description of the layout and tested on
synthetic pages (`tests/portfolio_pdf_fixtures.py`). It has never seen a real file; the runner
below is how the owner finds out what it gets right.

## The runner (prints only masked, aggregate output)

```
python -m src.portfolio.statement_pdf FILE.pdf [FILE2.pdf ...] [--consolidate]
```

It prints, per file: the position date, pages and extractor, the number of two-column pages,
positions by type, the total of the lines and the total the statement declares, `linhas não lidas`,
the positions and subtotal of every broker strategy, every sum check with `ok` or `FALHOU` and its
gap, the coverage of the identification-relevant fields (`codigo`, `vencimento`, `taxa_texto`,
`quantidade`, implied quota for funds), how many wrapped names were joined and how many were
ambiguous, and how many detail rows were read and joined. It never prints a name, an account, a
CPF or an asset name; a failed read prints the gap and the rows not read **by page and line and by
shape** (`L` label, `M` money, `P` percent, `-` missing), never by their text. Paste that output.

`--consolidate` then prints the consolidated view: accounts, holders (`T1..Tn`), dates, lines
before and after aggregation, the total, and the notes. A file that fails is reported and the
consolidation is not run.

The extractor is poppler's `pdftotext -layout`, fed the bytes on STDIN (the file never touches the
disk), with `pypdf` in layout mode when poppler is absent (`requirements-report.txt`). Without
either, or with no text layer, the reader raises `StatementFormatError` saying so.

## What the reader relies on

| Layout fact                                                                                                                                                                                                                                                                | How it is used                                                                                                                                                                                                                                                                                                             |
| -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Cover page: lines `Nome ...` and `Conta Investimento ...`                                                                                                                                                                                                                  | Read only to build the `Masker`; the cover is then discarded. Without a `Nome` line nothing is read.                                                                                                                                                                                                                       |
| The footer `Página N de M` is wrong                                                                                                                                                                                                                                        | Page numbers are never used; sections are found by heading.                                                                                                                                                                                                                                                                |
| Stray spaces next to the letter `t` (`At ivo`, `Tot al`, `Fundo de Invest iment o`)                                                                                                                                                                                        | Headings and labels are matched on an accent-stripped, lowercase key with no spaces, hyphens or colons. Position names are kept as printed.                                                                                                                                                                                |
| `Período ... DD/MM/YYYY a DD/MM/YYYY`                                                                                                                                                                                                                                      | The second date is the position date. None found: a format error.                                                                                                                                                                                                                                                          |
| `Patrimônio bruto` (summary) or the final `Saldo Bruto` (roll-forward)                                                                                                                                                                                                     | The statement's own total.                                                                                                                                                                                                                                                                                                 |
| `Distribuição por classe de ativos` with a `Conta corrente` row (else the first `Conta corrente` row before the account movements)                                                                                                                                         | The current account: a position of `tipo` `caixa`, so totals tie.                                                                                                                                                                                                                                                          |
| `Posição consolidada dos investimentos`: classes `Renda Fixa`, `Fundo de Investimento`, `Renda Variável`; strategies `Pós-fixado`, `Inflação`, `Pré-fixado`, `Alternativo`, `Retorno Absoluto`, `Renda Variável`; rows with `Posição bruta` and `% total`; a final `Total` | The leaves (positions) and their subtotals. A heading may carry its subtotal.                                                                                                                                                                                                                                              |
| Two-column pages (left `Renda Fixa`, right `Fundo de Investimento`, `Renda Variável`)                                                                                                                                                                                      | A line is split into row units (a run of money and percent tokens ends a unit when text follows; a gap of 3+ spaces between texts also does), not at a fixed character column, because the text layer rescales columns per page and per line. A continuation page keeps two columns when many of its lines hold two units. |
| Names wrap over 2 to 3 lines and around the numbers                                                                                                                                                                                                                        | A text-only line is a prefix of the next numeric row, or, right after a numeric row and before a heading, a tail of it. A prefix that follows a row could also be a tail: it is joined as a prefix and counted as `ambíguos`. A text line that attaches to nothing is a row not read.                                      |
| `Detalhamento dos Ativos`: one table per strategy (`Ativo`, `Data Inicial`, `Quantidade`, `Resgate`, `Vencimento`, `Taxa`, `Saldo bruto`, ...; renda variável `Ativo`, `Quantidade`, `Saldo bruto`, `Preço`, ...)                                                          | Joined to a position by strategy and `Saldo bruto` equal to the position value (name prefix to break ties): gives `quantidade`, `vencimento`, `taxa_texto` and the price. Detail rows that cannot be read or joined are counted, not fatal.                                                                                |
| Money `1.056.638,06`, percent `1,22%`, a missing value prints `-`                                                                                                                                                                                                          | A `-` where a position value is expected is a row not read. In the detail table it is no value.                                                                                                                                                                                                                            |

The 2026-08 layout (#747, measured on one real report) differs in four ways the reader handles.
The consolidated position is followed by `E, quando abrimos a rentabilidade por estratégia` and
`Atribuição de Resultado` (no `Detalhamento` between), which end the section. A long name is
printed in two halves around a line that can hold only the two columns' values; a line blank in
a column ends that column's row block, so the lower half stays with its row. The column header is
wrapped one word per line (`Posição` / `At ivo` / `brut a`). The summary wraps `Cont a` / value /
`corrent e`, and the PDF itself prints that value with its last digit cut (`R$ 7.841,1`): the cash
is then the gross total minus the consolidated `Total`, accepted only when it extends the printed
digits by one, and `Statement.notes` says so. Check 4 below then ties by construction; check 3
still ties the leaves on their own.

Position typing uses only what the statement prints: a registry code at the end of the name
(`CRA-`, `CRI-`, `CDB-`, `DEB-`, `LCA-`, `LCI-`; `CDCA-` and the like are `outro`) sets the type and
the `codigo` (the part after the hyphen); `BACEN-... - NTNB|NTNF|NTNC|NTNI|LTN|LFT` is `tesouro`
(code `NTN-B 2035-05-15` once the detail gives the maturity); the `Fundo de Investimento` section
is `fundo`; a ticker (`^[A-Z0-9]{4}[0-9]{1,2}$` with at least one letter, so B3SA3 and fixed income ETFs such as
B5P211 count) is `outro` with `codigo` = ticker, because the
statement does not say share or ETF (the identification step asks `lookup`); anything else is
`outro` with no code. The indexer is never read from a name: it is the printed `taxa_texto`, read
by the regex rules of `src/portfolio/rules/indexer_rules.csv`.

## The sum checks

All of these run where their anchors exist, within R$ 0,01 x the number of rows; a failure raises
`StatementTotalMismatch` naming the check and the gap (and, if any, the rows not read):

1. the leaves of each strategy against its printed subtotal;
2. the strategy subtotals against the class total (the leaves against the class total when there
   are no strategy subtotals);
3. the consolidated `Total` (which excludes the current account) against the sum of the leaves;
4. the leaves plus the current account against `Patrimônio bruto`, or the final `Saldo Bruto`.

`Statement.notes` records the checks that ran. If no anchor exists at all the reader raises
`StatementFormatError`. A row that cannot be read stops the read even when the sums happen to tie.

## Consolidation

`consolidate(statements)` returns the aggregated portfolio the engine diagnoses plus the
per-account view. Accounts are `C1..Cn` by order (the real number is never kept); holders are
`T1..Tn` by a salted in-process fingerprint of the masked name (so `[TITULAR]`, the same token for
everyone, still tells two people apart); more than one holder is noted as `multi-titular`. The same
asset in two accounts is aggregated when it has the same `codigo` and maturity (else the same
normalised name and type) and the same position date; the per-account lines stay in `contas`. A
Tesouro title with no maturity is never aggregated. The total is the sum of the statements'
totals. Statements with different dates are not mixed: the dates and the gap are a note and nothing
is aggregated across dates. The same account on the same date twice is refused (it would double
count). The engine output carries both views (`statement.positions` and `statement.accounts`).

## Not verified

The real layout. Likely first failures: a heading spelled differently from the keys above, a
column the reader reads as a continuation, a name wrapped in a way the prefix and tail rules get
wrong, the summary rows being worded differently. The runner's shapes say which.

## BTG "Extrato da Conta Investimento": the second reader

`src/portfolio/statement_pdf_extrato.py` reads the other BTG layout, the "Extrato da Conta
Investimento" (co-branded "One Investimentos | BTG Pactual", landscape), into the same `Statement`
under the same rules: masking at read time, sum checks against the statement's own total, no row
dropped silently, nothing fabricated. **It was written from a description of the owner's files and
tested only on synthetic pages** (`tests/portfolio_extrato_fixtures.py`, also round-tripped through a
real PDF and both extractors). The runner says what it gets right on a real file:

```
python -m src.portfolio.statement_pdf_extrato FILE.pdf [FILE2.pdf ...] [--consolidate] [--mostrar-ativos]
```

The format is picked by content, per file: a first page with "Extrato da Conta Investimento" goes
to this reader, anything else to the performance reader (`read_any_pdf_bytes`). The server's
`POST /diagnose` uses the same detection, and accepts several multipart `file` parts (one statement
per account, 10 MB in all), consolidated before the engine runs. The runner prints, per file, the
sections found (and, for an unknown heading, its first segment and whether the second is `posição`, `detalhamento` and the like, never the rest), positions by type, every sum
check with its gap, the coverage of `codigo`, CNPJ, `vencimento`, `taxa_texto`, `emissor` and
`quantidade`, how wrapped lines were attached (and how many were ambiguous) and the rows not read
by page, line and shape (`L` text, `D` date, `N` number, `P` percent, `C` CNPJ, `-` missing). A
failed read prints the same aggregates. It never prints a name, CPF, account, address, plan
certificate or asset name.

| Layout fact | How it is used |
| --- | --- |
| Cover: "Informações detalhadas sobre investimentos", then the holder name (no label), "Conta investimento N", "CPF ...", the address, "Período de DD/MM/YY a DD/MM/YY" | Read only to mask: name, account and CPF through `Masker`, the address line, its street part and CEP as `[ENDERECO]`. No name line: nothing is read. The period's second date is the position date. |
| Every page: "Extrato da Conta Investimento", "Período ...", the SAC footer, perhaps the holder | Furniture. A line with a mask token is dropped only among a page's first four and last three lines; elsewhere it stays (an exclusive fund may carry the holder's name). |
| "Sumário - Distribuição em DD/MM/YY": `Mercados` and four Saldo columns | The third value (end-date Saldo Bruto) of each class row is that class's subtotal; `Total`'s is the statement's own total. A row without four values is a row not read. No `Total`: a format error. |
| "Fundo de Investimento - Posição": a title line `<name> - Classe CNPJ: <cnpj> [- Cód. Subclasse: ...]` (may wrap), then a data line `<date> <8 values>`, then `Total em fundos` | `codigo` = the CNPJ, `quantidade`, the quota as `preco_unitario`, Saldo Bruto as `valor`; `FIDC` when the name has FIDC or ends in DC, `FII` when it has FII, else `fundo`. The position date stays the period's; a different quota date is counted and noted. The subclass code is not kept. |
| "Renda fixa - Posição - <KIND>": `Emissor, Ativo, Emissão, Vencimento, Liquidez, Carência, Data inicial, Taxa, Quantidade, Preço, Saldo Bruto, IR, IOF, Saldo Líquido`, then a subtotal row with no label | Emissor, Ativo and Taxa may wrap. A data line is the one with the dates and six trailing values; the other lines are attached by column (Emissor left of the Ativo column, Taxa between "Data inicial" and Quantidade; text anywhere else is a row not read). Ativo pieces join with no space, Emissor pieces with one. `CRA-/CRI-/DEB-/CDB-/LCA-/LCI-` set the type (other prefixes `outro`), `codigo` is the part after the hyphen; BACEN rows and `NTNB-P/NTNB/LTN/LFT/NTNF/...` are `tesouro` with `codigo` `NTN-B Principal 2035-05-15` (`identify.parse_tesouro`). `emissor` is stored on the position (a new optional field; not yet in the engine output). |
| How wrapped cells sit around their row | Read once for the whole document: text before a table's first row means cells wrap upwards, text after its last row (or an Ativo ending in `-` on the row) downwards, both means centred, where each row has as many lines above as below and the chain must close at the table's end. No evidence: downwards is assumed and every line between rows is counted as ambiguous. |
| "Renda fixa - Posição Consolidada Por Emissor" | An extra check: its rows (or its `Total`) against the renda fixa positions. Skipped, and said so, when a line is not `<name> <value>`. |
| "Previdência Individual/Interna - Posição - <cert>/PGBL": `Fundo, CNPJ, Data, Quantidade, Cotação, Saldo Bruto`, then `Total`; one table per plan | Each row a `fundo` with the CNPJ as `codigo` and `Previdência PGBL` (or VGBL) as the broker's strategy. The certificate is never kept or printed. |
| "Renda variável - Posição - <KIND>": `Código, Ativo, Qtde., Preço Fechamento, Preço Médio, Saldo Bruto`, then `Total em ...` | `codigo` = ticker, closing price as `preco_unitario`; type by section: ETF, Ações (`ação`), FII, else `outro`. |
| "Conta corrente - Posição": `Data, Valor financeiro` | A `caixa` position, so the totals tie. |
| Detalhamento, Movimentação, Rentabilidade, plan metadata, "Posições abertas por alíquota", Índice, the distribution legends, Perfil de Risco, Disclaimers, Fale Conosco | Skipped. A title-case heading with a dash that matches nothing is skipped and counted; if it held money, the Sumário check fails and names the class it has no reader for. |
| Dates `dd/mm/yy`, money `1.234,56`, prices with up to 9 decimals, quantities `1.725` or `30,0`, missing `-` or `–` | Parsed as printed; the sum checks use Saldo Bruto. |

Sum checks, all within R$ 0,01 x the number of rows: every table's own subtotal against its rows;
each Sumário class against the positions of its sections; the positions against the Sumário
`Total`; the per-emissor table against renda fixa. A failure or a row not read raises
`StatementTotalMismatch`.

**Not verified** (no real file was opened): the column positions `pdftotext` gives the real file
(wrapped text is placed by column, with two characters of slack), whether a heading wraps or repeats
on a continuation page, Sumário rows for classes not listed here (COE, derivatives), the spelling of
other renda variável and renda fixa kinds, and how the Emissor wraps (`ARTESANA` / `L` is joined as
`ARTESANA L`).

## The extrato with no text layer for its labels: the OCR path

Some of the owner's extratos draw every label as vector outlines: `pdftotext` returns only the
numbers (dates, quantities, prices, money and percents, in a monospace font) and the SAC /
Ouvidoria footer. The headings, the cover, fund names, CNPJs, Emissor, Ativo codes, the rate text,
the Sumário labels and the ETF codes are pictures. `src/portfolio/statement_ocr.py` reads such a
file as a hybrid and hands the same parser layout text:

1. **Detection.** The first page's text layer holds the SAC or Ouvidoria footer but no
   "Extrato da Conta Investimento". Page 1 alone is then read by OCR. If it shows the extrato
   heading (with two OCR errors at most), the other pages are read too. If not, the file goes to
   the performance reader exactly as before, and the other pages are never OCR'd. A file whose
   heading is in its text layer (this extrato's other form, the performance report) never reaches
   OCR. OCR needs `pdftotext`, `pdftoppm` and `tesseract` with `por`. When page 1 holds nothing but
   numbers beside the footer and the tools are missing, or OCR finds no heading, the read stops
   with a `StatementFormatError` saying so.
2. **Numbers from the text layer.** `pdftotext -bbox` (bytes on STDIN) gives every number with its
   box, in PDF points.
3. **Labels from OCR.** Each page is rendered with `pdftoppm -r 300 -gray` and the image is piped
   into `tesseract stdin stdout -l por tsv` (one thread each, pages in parallel on the CPUs
   the process may use, at most 4; `SILO_OCR_WORKERS` overrides). The cover uses `--psm 4`, which the
   masking was built on. The table pages use `--psm 11` (sparse text): each word is read on its own,
   so a wrapped cell centred half a pitch off its row is not merged into the date row. On the real
   files, psm 4 read such a wrapped CRA code as an unrelated word. A code-like word (letters and digits) read with
   confidence under 60 is read again on its own: only its box is rendered (`pdftoppm -x -y -W -H`)
   and read as one line (`--psm 7`). The new reading replaces the old only when tesseract is more
   confident in it. On a real page this undid a doubled round glyph (`CRA0O…` read again as `CRAO…`). Word boxes are
   scaled to points. Nothing touches the disk, and tesseract's stderr is discarded.
4. **Merge.** An OCR word that overlaps a text-layer token is dropped, so the text layer always wins
   for numbers. So is a numeric-looking OCR word on a text-layer token's line and column, and so is
   a stray mark (`|`, quotes, specks). Tokens join a line when their vertical centres are within 0.3
   of the font size, so the wrapped cells of a centred row, half a pitch away, stay separate lines.
   On a line, two OCR words with a word space between them form a phrase with single spaces, by
   their boxes alone. A wider gap keeps two spaces, which the parser reads as a column gap. x is
   mapped to character columns on the finer of the monospace advance and a narrow OCR character
   width. A text-layer token is placed by its right edge, because the tables right-align their
   numbers, so a column keeps one end column whatever the length of its values. Each line also
   carries its vertical centre, in font-size units, to the parser.
5. **The same parser, in OCR mode** (`parse_extrato_pages(..., ocr_mode=True)`). It matches the
   known headings with one OCR error (two in the long ones), the cover's
   "Informações detalhadas" line and "Extrato da Conta Investimento" the same way, and accepts a
   column header with one garbled word among three. It reads the period with or without the `a`
   between the dates, upper-cases a B3 code, and drops a page's header line carrying "Conta
   investimento" whether or not its holder name was masked, since one OCR letter off would escape
   the mask. Anywhere else, two or more consecutive words that read as consecutive words of the
   holder's name, each at most one letter off, become `[TITULAR]` (an exclusive fund's name, for
   instance). The word `CNP)` is read as `CNPJ`.
6. **Normalisation, per field, recorded and never invented.** Each position gets
   `fonte_texto = "ocr"`, `codigo_conferido`, `taxa_conferida` and `ajustes_ocr`:
   - **codes:** `CRA` is `CRA` + 2 digits + 6 alphanumerics, `CRI` is 2 digits, a letter and 7
     digits, `DEB` is 4 letters + 2 digits, and a B3 ticker is 4 letters + 1 or 2 digits.
     `O`/`0`, `I`/`l`/`1`, `S`/`5` and `B`/`8` are swapped only at a position whose class the
     shape fixes. A code with no known shape (`CDB`, `LCA`, `LCI`, `CDCA`), or one that still does
     not match its shape, is kept as read with `codigo_conferido = false`;
   - **CNPJ** (funds and previdência): letters inside a CNPJ-shaped word become digits. If the check
     digits fail, single substitutions from a short confusion set (0/8, 3/8, 5/6, 6/8, 1/7) are
     tried, and the result is accepted only when exactly one is valid (noted in `ajustes_ocr`).
     Otherwise the CNPJ is kept and unverified. The cover CPF is repaired the same way, only so the
     masker hides its exact digits;
   - **rate text:** `aa.` becomes `a.a.`, `CDl` becomes `CDI`, `lPCA` becomes `IPCA` and `+` gets
     its spaces. A percent with no comma and three or more digits gets its comma back before the
     last two, because BTG prints every rate with two decimals (`1716%` becomes `17,16%`). Anything
     else (one decimal, a stray character) is kept as read with `taxa_conferida = false`. The rate
     only feeds the indexer class (CDI / IPCA / a.a.).
7. **Columns by position, not by count.** The real missing-value dash is an outline. The text layer
   never carries it, and tesseract reads some and drops most. So a fund row has 8 or 7 values
   instead of 9, and a renda fixa row has no carência, data inicial, IR or IOF value at all.
   In OCR mode, no table is read by counting tokens:
   - **Funds:** Saldo Bruto is the row's number in the column of the `Total em fundos` value.
     Quantity and quota are the two numbers before it, after the date and the invested value.
   - **Renda fixa:** a row is the line with the Emissão and Vencimento dates. Saldo Bruto is its
     number in the column of the subtotal's first value, and Quantidade and Preço are the two
     numbers before it. The rate starts after the row's own Liquidez value and any carência, data
     inicial or dash speck after it. When no Liquidez value was read, it starts 40% of the way from
     the `Data inicial` header to the `Taxa` header. Emissor and Ativo are left of the Emissão date,
     split at the header's `Ativo`.
   - **Specks:** a one- or two-letter OCR reading of a dash or a rule (`o`, `ã`, `x`, never `+` or
     `do`) is ignored and counted.
   - **Quantity × unit price:** in every table it must give Saldo Bruto, within R$ 0,05 or 0,001%
     of the value, whichever is larger. A row that fails is a row not read, because a value was
     taken from the wrong column. The subtotals only check what was taken as Saldo Bruto.
   - **Wrapped cells:** in a table whose cells are centred, each wrapped Emissor, Ativo or rate line
     goes to the row on its page whose numbers it sits closest to. No lines are counted, so a speck
     between rows cannot shift the count. A line exactly half-way is ambiguous and counted.
8. **Headings and furniture in OCR mode.**
   - The index and the Disclaimers pages open no table. Their footnote titles repeat `Fundos de
     Investimento - Posição` and `Renda Fixa - Posição`.
   - `Previdência Individual - Posições abertas por alíquota` is skipped, and so is any
     `Fundos de Investimento - ...` heading (plural).
   - The page head above `Período` (the logo, read as stray words) joins no table.
   - A column header line may carry its footnote markers (`Saldo Líquido R$ 3`), its dates (the
     Sumário's) and, in OCR text, one- or two-letter specks and `IRR$`.
   - A fund title's CNPJ may have a dot dropped or read as a space (`11.222 333/0001-81`).
9. **Sum checks unchanged and decisive.** If OCR misses a heading, its numbers belong to no table.
   The Sumário check then fails, and the failure lists every line with money that no section took,
   `pN:lM (shape ...)`, never its text.

The runner prints, for an OCR read, the word counts (OCR, text layer, dropped as duplicates, dropped
as numeric, stray marks) and the verified and unverified counts. `--mostrar-ativos` prints one line
per position: type, the asset as printed, `codigo`, CNPJ, `vencimento`, `taxa`, `valor` and the
flags (`lido por OCR`, `código conferido` / `NÃO conferido`, the adjustments). The owner allowed
asset names. Holder data stays masked, since the cover is read only to build the masker and then
discarded. The ten synthetic pages take about 3 s on four cores; a real 19-page file took about 11 s on four cores, re-reads included. The
engine image installs `tesseract-ocr` and `tesseract-ocr-por`, and `engine_image.yml` reads a
synthetic image-only statement inside it with `SILO_REQUIRE_OCR=1`.

**Read on the owner's two real files (2026-10-04)**, 19 pages each. Both reconcile, with every sum
check `ok` and every row's quantity × price equal to its Saldo Bruto: 41 positions in all. All 12
fund and previdência CNPJs were read correctly. So were 18 of the 19 distinct registry codes and
tickers. The regression fixtures rebuild the real file's shapes with invented data
(`tests/portfolio_ocr_fixtures.real_layout_pages`, also built as an outlined PDF and read through
tesseract). No real page, image or OCR text is in the repository.

**Known limits:**

- One debenture code (four letters and `11`) reads as three to six wrong characters at every dpi
  and mode tried. It is kept as read with `codigo_conferido = false`, and its value reconciles.
- A CDB, LCA, LCI or CDCA code has no known shape, so it is kept as read and unverified even when
  right.
- A FIP is typed `fundo`: `Position` has no FIP type.
- The rate text and the Emissor are OCR with no check digit. A rate is flagged only when it does
  not look like a rate.

Matching the codes against SILO (`cvm_securit_serie.codigo_cetip`, the CDA `cd_ativo`) is the next
step.

