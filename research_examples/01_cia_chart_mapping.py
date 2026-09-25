#!/usr/bin/env python3
"""Reference calculation: CVM statement census and account-chart context.

Expected counts are transcribed from docs/CIA_DATA_MAP.md; this is not a fresh
row-level download. It demonstrates the reproducible percentage calculation
and why chart context matters when combining company and financial-statement
data.
"""

from decimal import Decimal


def main() -> None:
    statement_rows = Decimal("50439")
    rows_without_code_311 = Decimal("282")
    pct = rows_without_code_311 / statement_rows * 100
    print("Datasets: CVM company/chart context + financial-statement accounts")
    print(f"Statement rows in documented census: {statement_rows}")
    print(f"Rows without account code 3.11: {rows_without_code_311}")
    print(f"Share without 3.11: {pct:.4f}%")
    print("Finding: company_financials.net_income returns NULL for this set;")
    print("the filed labels/chart context identify bank-B 3.09 as net income.")
    print("Measured 3.09 fallback was numerically harmless in this census, but")
    print("code meaning varies by chart; read labels before comparing companies.")
    print("Sources: docs/CIA_DATA_MAP.md; https://dados.cvm.gov.br/dataset/cia_aberta-doc-itr;")
    print("https://dados.cvm.gov.br/dataset/cia_aberta-doc-dfp")
    print("Limit: documented census, not a current full-universe rerun or earnings measure.")


if __name__ == "__main__":
    main()
