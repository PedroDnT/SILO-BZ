"""fact_security_monthly holds one row per series per month (issue #428).

The grain was one row per certificate-month, so it kept one series of each
certificate and dropped the others: 140,410 of 320,107 series-months in CVM's
2019-2026 files. The reported value on /securit was 12% to 47% short in the
complete months measured. Cash flows stay per certificate, because CVM files
fluxo_caixa with no series.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANALYTICAL = ROOT / "src" / "store" / "analytical"


def _uncommented(sql: str) -> str:
    return re.sub(r"--[^\n]*", "", sql)


FACT = _uncommented((ANALYTICAL / "05_fact_security_monthly.sql").read_text(encoding="utf-8"))


def test_the_unique_index_is_the_series_month():
    """08 refreshes the fact CONCURRENTLY, which needs a unique index on plain
    columns. The securitizer is not part of a series (test_securit_keys)."""
    m = re.search(
        r"CREATE UNIQUE INDEX ix_fact_security_monthly_pk\s+ON fact_security_monthly \(([^)]*)\)",
        FACT,
    )
    assert m
    assert [c.strip() for c in m.group(1).split(",")] == [
        "instrument_type", "codigo_identificacao", "numero_serie", "period",
    ]


def test_flows_join_on_the_certificate_only():
    """fluxo has no series and its key has a CNPJ. Grouped by cnpj_securit, two
    filers of one certificate-month would duplicate a series row and fail the
    unique index. Joined on it, a series would lose its flows whenever serie and
    fluxo name different filers."""
    start = FACT.index("fluxo_monthly AS (")
    fluxo = FACT[start:FACT.index("\n)", start)]
    assert "cnpj_securit" not in fluxo
    start = FACT.index("LEFT JOIN fluxo_monthly f")
    join = FACT[start:FACT.index(";", start)]
    assert "cnpj_securit" not in join
    for col in ("codigo_identificacao", "instrument_type", "period"):
        assert f"f.{col}" in join


def test_security_identifiers_name_the_series():
    """With one row per series, securitizer:certificate repeats within a month
    (56,087 identifier-months in the 2019-2026 files)."""
    for name in ("07_vw_cross_domain.sql", "09_analytical_functions.sql"):
        sql = _uncommented((ANALYTICAL / name).read_text(encoding="utf-8"))
        tails = re.findall(
            r"s\.cnpj_securit\s*\|\|\s*':'\s*\|\|\s*s\.codigo_identificacao([^,]*)", sql
        )
        assert tails, name
        for tail in tails:
            assert "numero_serie" in tail, f"{name}: {tail.strip()}"
