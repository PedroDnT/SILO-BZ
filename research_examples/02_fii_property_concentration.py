#!/usr/bin/env python3
"""Reference join/calculation for one CVM FII fund/property report pair.

Values match the Via Parque Shopping fixture in
tests/test_fii_trimestral_field_maps.py. This reproduces arithmetic on that
published-shaped example; it is not a universe-level portfolio ranking.
"""

from decimal import Decimal


def main() -> None:
    fund_cnpj = "00.332.266/0001-31"
    property_cnpj = "00.332.266/0001-31"
    fund_date = property_date = "2025-03-31"
    fund_version = property_version = "1"
    area_m2 = Decimal("56508.93")
    vacancy_fraction = Decimal("0.124")
    delinquency_fraction = Decimal("0.231726")
    revenue_share = Decimal("0.979772")

    assert (fund_cnpj, fund_date, fund_version) == (
        property_cnpj, property_date, property_version
    )
    vacant_area = area_m2 * vacancy_fraction
    print("Datasets: CVM FII fund report + CVM FII property report")
    print(f"Join: CNPJ={fund_cnpj}, date={fund_date}, version={fund_version}")
    print(f"Reported area: {area_m2} m2; vacancy: {vacancy_fraction:.3%}")
    print(f"Calculated vacant area: {vacant_area:.2f} m2")
    print(f"Reported delinquency: {delinquency_fraction:.4%}")
    print(f"Reported property revenue share: {revenue_share:.4%}")
    print("Finding: the example property reports high revenue reliance alongside")
    print("material vacancy and delinquency; investigate concentration and collection risk.")
    print("Source: https://dados.cvm.gov.br/dataset/fii-doc-inf_trimestral")
    print("Limit: one property snapshot; not a whole-fund ranking or verified time series.")


if __name__ == "__main__":
    main()
