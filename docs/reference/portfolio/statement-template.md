# Statement template (spreadsheet)

The input the engine reads today. One sheet (the first of an `.xlsx`, or a `.csv` with `,` or
`;`). An example filled with the demo positions and fictitious holder data:
[`statement-template.xlsx`](statement-template.xlsx), built by
`python scripts/build_portfolio_statement_template.py`. The file is read once and never stored:
the holder's name, CPF and account number are replaced by fixed tokens at read time
(`src/portfolio/mask.py`), before anything is logged or passed on.

## Layout

A header block of `key | value` rows, a blank row, the position header row, then one row per
position.

| Header key      | Required | Meaning                                                                  |
| --------------- | -------- | ------------------------------------------------------------------------ |
| `total_extrato` | yes      | the statement's own total (R$)                                           |
| `titular`       | no       | holder name (masked to `[TITULAR]`)                                      |
| `cpf`           | no       | holder CPF, or a person-like CNPJ (masked to `[CPF]` / `[CNPJ_TITULAR]`) |
| `conta`         | no       | account number (masked to `[CONTA]`)                                     |
| `corretora`     | no       | broker name                                                              |

| Position column                | Required | Meaning                                                                                                                                    |
| ------------------------------ | -------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| `linha_extrato`                | yes      | the name as printed on the statement                                                                                                       |
| `tipo`                         | yes      | `ação`, `fundo`, `FII`, `ETF`, `FIDC`, `tesouro`, `debênture`, `CRI`, `CRA`, `CDB`, `LCI`, `LCA`, `outro` (accents and case do not matter) |
| `codigo`                       | no       | ticker, CNPJ (with or without punctuation), ISIN, or for `tesouro` the title and maturity, `NTN-B 2035-05-15`                              |
| `quantidade`, `preco_unitario` | no       | for a fund, `preco_unitario` is the quota the statement prints: it is the resolver's tie-break between a feeder and its master             |
| `valor`                        | yes      | the position's value (R$). The engine never revalues it                                                                                    |
| `data_posicao`                 | yes      | `YYYY-MM-DD` or `DD/MM/YYYY`, or a date cell                                                                                               |

Numbers are numeric cells, or text as `1.234,56` or `1234.56`.

## The hard rule

The sum of `valor` must equal `total_extrato` within R$ 0,01 times the number of position rows.
Otherwise the reader raises `StatementTotalMismatch` naming the difference and every row it
could not read (a row with an empty or non-numeric `valor`, an unknown `tipo`, a bad date).
No row is dropped silently. A file that is not the template (no header row, no total, a
missing required column, no rows) raises `StatementFormatError`.

Rows with different `data_posicao` are accepted; the report date is the latest and a note says so.
