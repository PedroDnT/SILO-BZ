"""Offline contracts for the CVM offerings ingest (#1005).

Fixtures are real rows cut from oferta_distribuicao.zip as published on
2026-10-21 (latin-1, ';', CRLF), header unchanged.
"""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

from src.fetchers.cvm_config import DatasetConfig
from src.pipeline import ingest_oferta as O

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests/fixtures/cvm_oferta"


def read(name):
    with open(FIX / name, encoding="latin-1", newline="") as f:
        return list(csv.DictReader(f, delimiter=";"))


def run(fn, rows):
    calls = []

    def fake(conn, table, records, conflict_columns=None):
        calls.append((table, records, conflict_columns))
        return len(records)

    with patch.object(O, "upsert_rows", side_effect=fake):
        n = fn(object(), rows)
    return n, calls


def test_res160_rows_land_on_their_own_key():
    n, [(table, records, key)] = run(O.ingest_oferta_160, read("oferta_resolucao_160.csv"))
    assert n == 5 and table == "cvm_oferta_distrib_160" and key == "numero_requerimento"
    first = next(r for r in records if r["numero_requerimento"] == "395")
    assert first["valor_mobiliario"] == "Debêntures"
    assert len(first["cnpj_emissor"]) == 14 and first["cnpj_emissor"].isdigit()
    assert first["valor_total_registrado"] == 950000000.0
    assert first["data_requerimento"] == date(2023, 1, 5)
    assert first["source_file"] == "oferta_resolucao_160.csv"
    # Investor-type counts are not typed: they stay in raw, as filed.
    assert "Num_Invest_Pessoa_Natural" in first["raw"]


def test_icvm400_keeps_registered_debentures_and_drops_what_has_no_key():
    n, [(table, records, key)] = run(O.ingest_oferta_400, read("oferta_distribuicao.csv"))
    assert table == "cvm_oferta_distrib_400" and key == "numero_registro_oferta,serie"
    keys = {(r["numero_registro_oferta"], r["serie"]) for r in records}
    # Fixture: 3 good rows, 1 with no registration number, a repeated key (2 rows),
    # 1 ICVM 476 debenture and 1 ICVM 400 CRI.
    assert n == 3
    assert keys == {("CVM/SRE/SEC/2022/003", "2"), ("CVM/SRE/DEB/2022/023", "Única"),
                    ("CVM/SRE/DEB/1990/002", "2")}
    assert all(r["rito_oferta"].startswith("ICVM 400") for r in records)


def test_missing_issuer_cnpj_stays_null_never_padded():
    _, [(_, records, _)] = run(O.ingest_oferta_400, read("oferta_distribuicao.csv"))
    old = next(r for r in records if r["numero_registro_oferta"] == "CVM/SRE/DEB/1990/002")
    assert old["cnpj_emissor"] is None


def test_invalid_issuer_cnpj_is_dropped():
    rows = read("oferta_resolucao_160.csv")
    rows[0]["CNPJ_Emissor"] = "11.222.333/0001-82"
    n, _ = run(O.ingest_oferta_160, rows)
    assert n == 4


def test_repeated_key_drops_every_copy_instead_of_choosing_one():
    rows = read("oferta_resolucao_160.csv")
    rows[1]["Numero_Requerimento"] = rows[0]["Numero_Requerimento"]
    n, [(_, records, _)] = run(O.ingest_oferta_160, rows)
    assert n == 3 and rows[0]["Numero_Requerimento"] not in {r["numero_requerimento"] for r in records}


def test_a_drifted_header_raises():
    rows = [{k.replace("Numero_Requerimento", "Num_Req"): v for k, v in r.items()}
            for r in read("oferta_resolucao_160.csv")]
    with pytest.raises(Exception, match="numero_requerimento"):
        run(O.ingest_oferta_160, rows)


def test_unparsed_number_is_kept_in_raw():
    rows = read("oferta_resolucao_160.csv")
    rows[0]["Valor_Total_Registrado"] = "n/d"
    _, [(_, records, _)] = run(O.ingest_oferta_160, rows)
    bad = next(r for r in records if r["numero_requerimento"] == rows[0]["Numero_Requerimento"])
    assert bad["valor_total_registrado"] is None
    assert bad["raw"]["_unparsed"] == {"Valor_Total_Registrado": "n/d"}


def test_config_points_both_doc_types_at_the_same_zip():
    a = DatasetConfig.get_dataset_config("oferta", "distrib_160")
    b = DatasetConfig.get_dataset_config("oferta", "distrib")
    assert a["url_pattern"] == b["url_pattern"]
    assert a["url_pattern"].endswith("/OFERTA/DISTRIB/DADOS/oferta_distribuicao.zip")
    assert (a["csv_name_pattern"], b["csv_name_pattern"]) == (
        "oferta_resolucao_160.csv", "oferta_distribuicao.csv")


def test_oferta_is_not_in_the_daily_run():
    import inspect
    from src.pipeline.cvm_pipeline import CVMIngestor
    assert "oferta" not in inspect.getsource(CVMIngestor.daily_update)
