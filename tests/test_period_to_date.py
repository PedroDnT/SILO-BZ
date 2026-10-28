import pytest

from src.pipeline.cvm_pipeline import _period_to_date


def test_valid_iso_date_passes_through():
    assert _period_to_date("2024-01-31") == "2024-01-31"


@pytest.mark.parametrize("bad", [None, "", "ab-cd-ef", "2024-1", "2024-13-01"])
def test_missing_or_malformed_period_raises(bad):
    with pytest.raises(ValueError):
        _period_to_date(bad)


@pytest.mark.parametrize("dt,kept", [("2024-01-31", True), ("", False), (None, False), ("ab-cd-ef", False)])
def test_seed_drops_row_with_bad_period(dt, kept):
    from scripts.seed_local_db import _norm_fidc_mensal

    row = {"CNPJ_FUNDO": "00000000000191"}
    if dt is not None:
        row["DT_COMPTC"] = dt
    assert (_norm_fidc_mensal(row) is not None) is kept
