"""Focus horizon per endpoint (issue #945).

ExpectativasMercadoSelic publishes the COPOM meeting in "Reuniao" and has no
"DataReferencia". Keyed on DataReferencia, every Selic row stored horizon NULL
and the (endpoint_name, indicador, reference_date, horizon) key kept one
meeting per survey date. The payloads below are the live shape, recorded from
olinda.bcb.gov.br on 2026-10-13 (UTC-3) with the baseCalculo=0 filter the
fetcher applies.
"""

from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Two meetings, one survey date: the shape the old key collapsed to one row.
SELIC_PAYLOAD: List[Dict[str, Any]] = [
    {"Indicador": "Selic", "Data": "2026-10-09", "Reuniao": "R6/2028",
     "Media": 10.6847, "Mediana": 10.5000, "DesvioPadrao": 0.9026,
     "Minimo": 8.5000, "Maximo": 13.0000, "numeroRespondentes": 88,
     "baseCalculo": 0},
    {"Indicador": "Selic", "Data": "2026-10-09", "Reuniao": "R5/2028",
     "Media": 10.8761, "Mediana": 10.7500, "DesvioPadrao": 0.8783,
     "Minimo": 8.7500, "Maximo": 13.5000, "numeroRespondentes": 109,
     "baseCalculo": 0},
]

ANUAIS_PAYLOAD: List[Dict[str, Any]] = [
    {"Indicador": "IPCA", "Data": "2026-10-09", "DataReferencia": "2027",
     "Media": 4.1, "Mediana": 4.0, "DesvioPadrao": 0.3, "baseCalculo": 0},
]


async def _ingest(payloads: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    from src.pipeline.bacen_pipeline import BacenIngestor

    upserted: List[Dict[str, Any]] = []

    def _fake_upsert(client, table, rows, **kw):
        assert table == "bacen_expectativas"
        assert kw["conflict_columns"] == "endpoint_name,indicador,reference_date,horizon"
        upserted.extend(rows)
        return len(rows)

    async def _get(endpoint_name, indicador=None, start=None, limit=100):
        return payloads.get(endpoint_name, [])

    with patch("src.pipeline.bacen_pipeline.BacenClient") as mock_client_cls, \
         patch("src.pipeline.bacen_pipeline.get_pg_client", return_value=MagicMock()), \
         patch("src.pipeline.bacen_pipeline.upsert_rows", side_effect=_fake_upsert), \
         patch("src.pipeline.bacen_pipeline.EXPECTATIVAS_ENDPOINTS", list(payloads)), \
         patch("src.pipeline.bacen_pipeline.EXPECTATIVAS_INDICATORS",
               {e: None for e in payloads}):
        mock_client_cls.return_value.get_expectativas = AsyncMock(side_effect=_get)
        count = await BacenIngestor().ingest_expectativas("2026-10-01")

    assert count == len(upserted)
    return upserted


@pytest.mark.asyncio
async def test_selic_meetings_on_one_survey_date_keep_distinct_horizons():
    rows = await _ingest({"ExpectativasMercadoSelic": SELIC_PAYLOAD})

    assert len(rows) == 2
    assert {r["horizon"] for r in rows} == {"R6/2028", "R5/2028"}
    assert {r["reference_date"] for r in rows} == {"2026-10-09"}
    keys = {(r["endpoint_name"], r["indicador"], r["reference_date"], r["horizon"])
            for r in rows}
    assert len(keys) == 2, "the natural key must not collapse the two meetings"
    by_meeting = {r["horizon"]: r for r in rows}
    assert by_meeting["R5/2028"]["median"] == 10.75
    assert by_meeting["R6/2028"]["median"] == 10.5


@pytest.mark.asyncio
async def test_other_endpoints_still_key_on_datareferencia():
    rows = await _ingest({"ExpectativasMercadoAnuais": ANUAIS_PAYLOAD})

    assert [r["horizon"] for r in rows] == ["2027"]


@pytest.mark.asyncio
async def test_missing_horizon_field_stays_null_never_synthesized():
    no_meeting = {k: v for k, v in SELIC_PAYLOAD[0].items() if k != "Reuniao"}
    # A Reuniao on a non-Selic endpoint is not its horizon field either.
    anuais_no_ref = {k: v for k, v in ANUAIS_PAYLOAD[0].items() if k != "DataReferencia"}
    anuais_no_ref["Reuniao"] = "R1/2027"

    rows = await _ingest({
        "ExpectativasMercadoSelic": [no_meeting],
        "ExpectativasMercadoAnuais": [anuais_no_ref],
    })

    assert [r["horizon"] for r in rows] == [None, None]
