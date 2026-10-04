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
