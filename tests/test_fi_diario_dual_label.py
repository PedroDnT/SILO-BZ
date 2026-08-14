"""FI inf_diario dual-label collisions: prefer the CVM-175 tp_fundo.

Some CNPJs are filed twice on the same day under both the legacy ("FI") and
CVM-175 ("CLASSES - FIF") label, same empty ID_SUBCLASSE. The unique key is
(cnpj, dt_comptc, id_subclasse), so upsert_rows() last-write-wins. ingest_fi
sorts the CVM-175 row last so the winner is deterministic regardless of CSV
order. See src/pipeline/ingest_fi.py and migrations/17.
"""
from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

from src.pipeline.ingest_fi import ingest_fi_diario


def _row(tp_fundo: str, patrim: str) -> Dict[str, Any]:
    return {
        "TP_FUNDO_CLASSE": tp_fundo,
        "CNPJ_FUNDO_CLASSE": "12.345.678/0001-90",
        "ID_SUBCLASSE": None,
        "DT_COMPTC": "2025-06-30",
        "VL_TOTAL": patrim,
        "VL_QUOTA": "1.0",
        "VL_PATRIM_LIQ": patrim,
        "CAPTC_DIA": "0.00",
        "RESG_DIA": "0.00",
        "NR_COTST": "1",
    }


def _client() -> MagicMock:
    cur = MagicMock()
    cur.__enter__ = lambda s: s
    cur.__exit__ = MagicMock(return_value=False)
    client = MagicMock()
    client.cursor.return_value = cur
    client.reconnect = MagicMock()
    return client


@pytest.mark.parametrize("cvm175_first", [False, True])
def test_dual_label_prefers_cvm175_regardless_of_csv_order(cvm175_first: bool) -> None:
    legacy = _row("FI", "36600000.00")
    cvm175 = _row("CLASSES - FIF", "925000000.00")
    raw: List[Dict[str, Any]] = (
        [cvm175, legacy] if cvm175_first else [legacy, cvm175]
    )

    captured: List[Any] = []
    with patch("psycopg2.extras.execute_values") as mock_ev:
        mock_ev.side_effect = lambda cur, sql, vals, **kw: captured.extend(vals)
        n = ingest_fi_diario(_client(), raw)

    assert n == 1, "same-key dual labels must collapse to one upsert row"
    assert len(captured) == 1
    winner = captured[0]
    assert "CLASSES - FIF" in winner
    assert 925_000_000.0 in winner
    assert 36_600_000.0 not in winner
    assert "" in winner  # blank id_subclasse, coerced from None


def test_distinct_subclasses_are_not_collapsed() -> None:
    """A genuine CVM-175 multi-subclasse fund must keep both rows."""
    a = _row("CLASSES - FIF", "36600000.00")
    a["ID_SUBCLASSE"] = "RBMFN"
    b = _row("CLASSES - FIF", "925000000.00")
    b["ID_SUBCLASSE"] = "MZMRC"

    captured: List[Any] = []
    with patch("psycopg2.extras.execute_values") as mock_ev:
        mock_ev.side_effect = lambda cur, sql, vals, **kw: captured.extend(vals)
        n = ingest_fi_diario(_client(), [a, b])

    assert n == 2
    assert {row[2] for row in captured} == {"RBMFN", "MZMRC"}
