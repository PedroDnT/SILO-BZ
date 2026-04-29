"""
BacenService: business logic layer for the BACEN API.

Wraps BacenClient calls and assembles Pydantic response models,
keeping main.py to FastAPI wiring only.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

if __package__:
    from ..clients.bacen_client import BacenClient
    from .config import WELL_KNOWN_SGS, EXPECTATIVAS_ENDPOINTS
    from .models import (
        SGSSeriesResponse,
        WellKnownSeriesResponse,
        PTAXRateResponse,
        PTAXMoedasResponse,
        ExpectativasResponse,
        AvailableExpectativasResponse,
        TaxaJurosResponse,
    )
else:
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))
    from src.clients.bacen_client import BacenClient
    from src.bacen_api.config import WELL_KNOWN_SGS, EXPECTATIVAS_ENDPOINTS
    from src.bacen_api.models import (
        SGSSeriesResponse,
        WellKnownSeriesResponse,
        PTAXRateResponse,
        PTAXMoedasResponse,
        ExpectativasResponse,
        AvailableExpectativasResponse,
        TaxaJurosResponse,
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class BacenService:
    """Orchestrates BACEN data fetching and response assembly."""

    def __init__(self) -> None:
        self._client = BacenClient()

    # ── SGS ──────────────────────────────────────────────────────────────────

    def get_well_known_series(self) -> WellKnownSeriesResponse:
        return WellKnownSeriesResponse(series=WELL_KNOWN_SGS, timestamp=_now())

    async def get_sgs_series(
        self,
        series_code: int,
        label: str = "value",
        start: Optional[str] = None,
        end: Optional[str] = None,
        last: Optional[int] = None,
    ) -> SGSSeriesResponse:
        data = await self._client.get_sgs_series(
            codes={label: series_code}, start=start, end=end, last=last
        )
        return SGSSeriesResponse(
            series_code=series_code,
            series_label=label,
            total_records=len(data),
            data=data,
            timestamp=_now(),
        )

    async def get_sgs_multi(
        self,
        codes_str: str,
        start: Optional[str] = None,
        end: Optional[str] = None,
        last: Optional[int] = None,
    ) -> SGSSeriesResponse:
        codes_dict: Dict[str, int] = {}
        for pair in codes_str.split(","):
            pair = pair.strip()
            if ":" not in pair:
                raise ValueError(f"Invalid pair '{pair}'. Use 'LABEL:CODE'.")
            lbl, code_str = pair.split(":", 1)
            codes_dict[lbl.strip()] = int(code_str.strip())

        data = await self._client.get_sgs_series(
            codes=codes_dict, start=start, end=end, last=last
        )
        return SGSSeriesResponse(
            codes=codes_dict,
            total_records=len(data),
            data=data,
            timestamp=_now(),
        )

    # ── PTAX ─────────────────────────────────────────────────────────────────

    async def get_ptax_dolar(self, date: str) -> PTAXRateResponse:
        data = await self._client.get_ptax_dolar_dia(date)
        return PTAXRateResponse(
            query_type="CotacaoDolarDia",
            total_records=len(data),
            data=data,
            timestamp=_now(),
        )

    async def get_ptax_dolar_periodo(self, start: str, end: str) -> PTAXRateResponse:
        data = await self._client.get_ptax_dolar_periodo(start, end)
        return PTAXRateResponse(
            query_type="CotacaoDolarPeriodo",
            total_records=len(data),
            data=data,
            timestamp=_now(),
        )

    async def get_ptax_moeda(self, moeda: str, date: str) -> PTAXRateResponse:
        data = await self._client.get_ptax_moeda_dia(moeda.upper(), date)
        return PTAXRateResponse(
            query_type="CotacaoMoedaDia",
            moeda=moeda.upper(),
            total_records=len(data),
            data=data,
            timestamp=_now(),
        )

    async def get_ptax_moeda_periodo(
        self, moeda: str, start: str, end: str
    ) -> PTAXRateResponse:
        data = await self._client.get_ptax_moeda_periodo(moeda.upper(), start, end)
        return PTAXRateResponse(
            query_type="CotacaoMoedaPeriodo",
            moeda=moeda.upper(),
            total_records=len(data),
            data=data,
            timestamp=_now(),
        )

    async def get_ptax_moedas(self) -> PTAXMoedasResponse:
        data = await self._client.get_ptax_moedas()
        return PTAXMoedasResponse(
            total_records=len(data),
            currencies=data,
            timestamp=_now(),
        )

    # ── Expectativas ─────────────────────────────────────────────────────────

    def list_expectativas(self) -> AvailableExpectativasResponse:
        return AvailableExpectativasResponse(
            endpoints=EXPECTATIVAS_ENDPOINTS, timestamp=_now()
        )

    async def get_expectativas(
        self,
        endpoint_name: str,
        indicador: Optional[str] = None,
        start: Optional[str] = None,
        limit: int = 100,
    ) -> ExpectativasResponse:
        if endpoint_name not in EXPECTATIVAS_ENDPOINTS:
            raise ValueError(
                f"Unknown endpoint '{endpoint_name}'. "
                f"Valid options: {EXPECTATIVAS_ENDPOINTS}"
            )
        data = await self._client.get_expectativas(
            endpoint_name=endpoint_name,
            indicador=indicador,
            start=start,
            limit=limit,
        )
        return ExpectativasResponse(
            endpoint=endpoint_name,
            indicador=indicador,
            start_date=start,
            total_records=len(data),
            data=data,
            timestamp=_now(),
        )

    # ── TaxaJuros ────────────────────────────────────────────────────────────

    async def get_taxas_juros(
        self, endpoint_name: str, limit: int = 100
    ) -> TaxaJurosResponse:
        data = await self._client.get_taxas_juros(
            endpoint_name=endpoint_name, limit=limit
        )
        return TaxaJurosResponse(
            endpoint=endpoint_name,
            total_records=len(data),
            data=data,
            timestamp=_now(),
        )
