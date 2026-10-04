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
| `vencimento`                   | no       | the maturity as printed, same formats as `data_posicao`; feeds the maturity ladder. A value that is not a date makes the row unreadable     |
| `taxa`                         | no       | the rate exactly as printed (`CDI + 1,80%`, `105,00% do CDI`, `IPCA + 8,74%`, `15,41% a.a.`), kept as text; read only by the indexer rules |

Numbers are numeric cells, or text as `1.234,56` or `1234.56`.

## The hard rule

The sum of `valor` must equal `total_extrato` within R$ 0,01 times the number of position rows.
Otherwise the reader raises `StatementTotalMismatch` naming the difference and every row it
could not read (a row with an empty or non-numeric `valor`, an unknown `tipo`, a bad date).
No row is dropped silently. A file that is not the template (no header row, no total, a
missing required column, no rows) raises `StatementFormatError`.

Rows with different `data_posicao` are accepted; the report date is the latest and a note says so.

## Optional columns and repeated assets (engine 1.7)

`vencimento` and `taxa` may be left out, or left blank on any row. For direct credit (CRA, CRI, CDB, LCI, LCA,
debênture) the printed rate is classified by the versioned rules of `src/portfolio/rules/indexer_rules.csv`
(`statement_taxa`): `CDI + x%`, `x% do CDI` and `CDI` are post-fixed CDI, `IPCA + x%` is inflation, a bare `x% a.a.`
is pre-fixed; any other text stays "sem classificação". The indexer is never read from the name.

A consolidated statement may list one asset once per account. The engine merges, before identifying anything, the
rows with the same CNPJ, or the same `codigo` and `vencimento`, or (a fund with no `codigo`) the same name, type and
printed quota, at the same `data_posicao`; the position keeps its source rows. Other rows with no `codigo` are never
merged. The demo has the same CDB twice (rows 9 and 13), merged into one position.
