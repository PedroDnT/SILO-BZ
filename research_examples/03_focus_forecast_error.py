#!/usr/bin/env python3
"""Reference calculation matching one BCB Focus vintage to IBGE IPCA."""

from decimal import Decimal


def main() -> None:
    focus_median_pct = Decimal("4.59")
    realized_ipca_pct = Decimal("4.26")
    error_pp = focus_median_pct - realized_ipca_pct
    print("Datasets: BCB Focus forecast vintage + IBGE realized annual IPCA")
    print("Target: calendar year 2025; Focus report date: 2024-12-06")
    print(f"Focus median: {focus_median_pct:.2f}%")
    print(f"Realized IPCA: {realized_ipca_pct:.2f}%")
    print(f"Forecast error (forecast minus actual): +{error_pp:.2f} percentage points")
    print("Finding: this vintage overestimated realized 2025 IPCA by 0.33 pp.")
    print("Sources: https://www.bcb.gov.br/content/focus/focus/R20241206.pdf;")
    print("https://agenciadenoticias.ibge.gov.br/agencia-sala-de-imprensa/2013-agencia-de-noticias/releases/45612-ipca-vai-a-0-33-em-dezembro-e-fecha-o-ano-em-4-26")
    print("Limit: a single forecast/outcome pair cannot establish forecast skill.")


if __name__ == "__main__":
    main()
