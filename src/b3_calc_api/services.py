import asyncio
import logging
import re
import httpx
import random
from datetime import datetime, date, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin

if __package__:
    from .config import (
        config,
        SecurityType,
        B3_CALC_ENDPOINTS,
        SAMPLE_DEBENTURES,
        SAMPLE_CRAS,
        SAMPLE_CRIS,
        SAMPLE_INDEXES
    )
    from .models import (
        SecurityInfo,
        SecurityListResponse,
        SecurityPriceResponse,
        PriceCalculationResult,
        PaginationInfo,
        IndexesResponse,
        MarketDataResponse
    )
else:
    from config import (
        config,
        SecurityType,
        B3_CALC_ENDPOINTS,
        SAMPLE_DEBENTURES,
        SAMPLE_CRAS,
        SAMPLE_CRIS,
        SAMPLE_INDEXES
    )
    from models import (
        SecurityInfo,
        SecurityListResponse,
        SecurityPriceResponse,
        PriceCalculationResult,
        PaginationInfo,
        IndexesResponse,
        MarketDataResponse
    )

logger = logging.getLogger(__name__)

class CacheManager:
    """Simple in-memory cache manager with TTL support"""

    def __init__(self, max_size: int = 64, ttl_seconds: int = 1800):
        self._cache: Dict[str, Tuple[Any, datetime]] = {}
        self._max_size = max_size
        self._ttl_seconds = ttl_seconds
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Optional[Any]:
        """Get value from cache"""
        async with self._lock:
            if key in self._cache:
                value, timestamp = self._cache[key]
                if (datetime.now(timezone.utc) - timestamp).total_seconds() < self._ttl_seconds:
                    return value
                else:
                    # Expired, remove it
                    del self._cache[key]
            return None

    async def set(self, key: str, value: Any) -> None:
        """Set value in cache"""
        async with self._lock:
            if len(self._cache) >= self._max_size:
                # Remove oldest entry (simple FIFO)
                oldest_key = next(iter(self._cache))
                del self._cache[oldest_key]
            self._cache[key] = (value, datetime.now(timezone.utc))

class B3CalcService:
    """Service for interfacing with B3 CALC fixed income pricing API"""

    def __init__(self):
        self.base_url = config.B3_CALC_BASE_URL
        self.timeout = config.REQUEST_TIMEOUT
        self.max_retries = config.MAX_RETRIES
        self.retry_delay = config.RETRY_DELAY
        self._client: Optional[httpx.AsyncClient] = None
        self._cache = CacheManager(
            max_size=config.CACHE_MAX_SIZE,
            ttl_seconds=config.CACHE_TTL_SECONDS
        )

        # Security type code patterns for auto-detection
        self.CODE_PATTERNS = {
            SecurityType.DEBENTURE: re.compile(r"^[A-Z]{4}[0-9]{2}$"),  # e.g., VALE12
            SecurityType.CRI: re.compile(r"^[0-9]{2}[A-Z]{1}[0-9]{7}-[0-9]{2}$"),
            SecurityType.CRA: re.compile(r"^[0-9]{2}[A-Z]{1}[0-9]{7}-[0-9]{2}$"),
        }

        logger.info("B3CalcService initialized")

    async def initialize(self) -> None:
        """Initialize the HTTP client"""
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=10.0,
                read=self.timeout,
                write=10.0,
                pool=5.0,
            ),
            limits=httpx.Limits(
                max_connections=20,
                max_keepalive_connections=10,
                keepalive_expiry=30,
            ),
            headers={
                "User-Agent": "B3CalcAPI/1.0 (https://github.com/your-repo)",
                "Accept-Encoding": "gzip, deflate, br",
            },
            follow_redirects=True,
        )
        logger.info("B3CalcService HTTP client initialized")

    async def close(self) -> None:
        """Close the HTTP client"""
        if self._client:
            await self._client.aclose()
            self._client = None
        logger.info("B3CalcService closed")

    async def _request(
        self,
        endpoint: str,
        method: str = "GET",
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Make request to B3 CALC API"""
        if not self._client:
            raise RuntimeError("HTTP client is not initialized.")

        url = f"{self.base_url}{endpoint}"
        logger.info(f"B3 CALC API request: {method} {url}")

        try:
            if method == "GET":
                response = await self._client.get(url, params=params)
            elif method == "POST":
                response = await self._client.post(url, json=json_body, params=params)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")

            if response.status_code == 404:
                raise FileNotFoundError(f"Resource not found: {url}")
            if response.status_code == 400:
                raise ValueError(f"Bad request to B3 CALC API: {response.text}")

            response.raise_for_status()

            try:
                return response.json()
            except Exception:
                # Some endpoints may return non-JSON for list data
                text = response.text.strip()
                if text:
                    return {"raw": text, "lines": text.split("\n")}
                return {}

        except httpx.TimeoutException as exc:
            logger.error(f"Timeout requesting B3 CALC API: {url}")
            raise TimeoutError(f"B3 CALC API request timed out: {url}") from exc
        except httpx.NetworkError as exc:
            logger.error(f"Network error requesting B3 CALC API: {url}: {exc}")
            raise ConnectionError(f"B3 CALC API network error: {str(exc)}") from exc

    def _detect_security_type(self, code: str) -> Optional[SecurityType]:
        """Auto-detect security type from code format"""
        for security_type, pattern in self.CODE_PATTERNS.items():
            if pattern.match(code.upper()):
                return security_type
        return None

    def _parse_security_list(
        self,
        raw_data: Dict[str, Any],
        security_type: SecurityType,
    ) -> List[SecurityInfo]:
        """Parse B3 CALC API response into SecurityInfo list"""
        securities = []

        # Handle different response formats
        if isinstance(raw_data, list):
            items = raw_data
        elif "data" in raw_data:
            items = raw_data["data"]
        elif "securities" in raw_data:
            items = raw_data["securities"]
        elif "lines" in raw_data:
            # Plain text response - each line is a code
            lines = [line.strip() for line in raw_data["lines"] if line.strip()]
            for line in lines:
                if line and not line.startswith("#"):
                    parts = line.split(";")
                    code = parts[0].strip() if parts else line
                    name = parts[1].strip() if len(parts) > 1 else None
                    securities.append(
                        SecurityInfo(
                            code=code,
                            name=name,
                            security_type=security_type.value,
                        )
                    )
            return securities
        elif "raw" in raw_data:
            # Try to parse raw text
            raw_text = raw_data["raw"]
            for line in raw_text.split("\n"):
                line = line.strip()
                if line and not line.startswith("#"):
                    securities.append(
                        SecurityInfo(
                            code=line,
                            security_type=security_type.value,
                        )
                    )
            return securities
        else:
            items = []

        for item in items:
            if isinstance(item, str):
                securities.append(
                    SecurityInfo(
                        code=item,
                        security_type=security_type.value,
                    )
                )
            elif isinstance(item, dict):
                securities.append(
                    SecurityInfo(
                        code=item.get("code", item.get("codigo", item.get("id", ""))),
                        name=item.get("name", item.get("nome")),
                        issuer=item.get("issuer", item.get("emissor")),
                        isin=item.get("isin", item.get("ISIN")),
                        security_type=security_type.value,
                        index=item.get("index", item.get("indice")),
                        rate=item.get("rate", item.get("taxa")),
                        maturity_date=item.get(
                            "maturity_date", item.get("vencimento")
                        ),
                        issue_date=item.get("issue_date", item.get("emissao")),
                        status=item.get("status"),
                    )
                )

        return securities

    async def list_securities(
        self,
        security_type: SecurityType,
        page: int = 1,
        page_size: int = 100,
        search: Optional[str] = None,
    ) -> SecurityListResponse:
        """List available securities of a given type from B3 CALC"""
        cache_key = f"b3calc:list:{security_type}:{search or ''}"
        cached = await self._cache.get(cache_key)

        if cached is not None:
            all_securities = cached
            logger.info(f"Cache hit for B3 CALC list: {cache_key}")
        else:
            # Try to fetch from API, fall back to sample data
            try:
                endpoint_map = {
                    SecurityType.DEBENTURE: B3_CALC_ENDPOINTS["debentures_list"],
                    SecurityType.CRA: B3_CALC_ENDPOINTS["cra_list"],
                    SecurityType.CRI: B3_CALC_ENDPOINTS["cri_list"],
                }
                endpoint = endpoint_map[security_type]

                params = {}
                if search:
                    params["q"] = search

                raw_data = await self._request(endpoint, params=params)
                all_securities = self._parse_security_list(raw_data, security_type)

                # If no securities returned, use sample data
                if not all_securities:
                    logger.warning(
                        f"No securities returned from B3 CALC for {security_type}. "
                        "Using sample data."
                    )
                    all_securities = self._get_sample_securities(security_type)

            except (FileNotFoundError, ConnectionError, TimeoutError) as exc:
                logger.warning(
                    f"B3 CALC API unavailable for {security_type}: {exc}. "
                    "Using sample data."
                )
                all_securities = self._get_sample_securities(security_type)

            # Apply search filter if provided and not already applied by API
            if search:
                search_lower = search.lower()
                all_securities = [
                    s for s in all_securities
                    if search_lower in (s.code or "").lower()
                    or search_lower in (s.name or "").lower()
                    or search_lower in (s.issuer or "").lower()
                ]

            await self._cache.set(cache_key, all_securities)

        # Apply pagination
        total = len(all_securities)
        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        page_securities = all_securities[start_idx:end_idx]

        return SecurityListResponse(
            security_type=security_type.value,
            page=page,
            page_size=page_size,
            total=total,
            securities=page_securities,
        )

    def _get_sample_securities(self, security_type: SecurityType) -> List[SecurityInfo]:
        """Get sample securities for demonstration"""
        samples_map = {
            SecurityType.DEBENTURE: SAMPLE_DEBENTURES,
            SecurityType.CRA: SAMPLE_CRAS,
            SecurityType.CRI: SAMPLE_CRIS,
        }

        samples = samples_map.get(security_type, [])
        return [
            SecurityInfo(
                code=s["code"],
                name=s["name"],
                issuer=s["issuer"],
                security_type=security_type.value,
                index=s.get("index"),
                rate=s.get("rate"),
                maturity_date=s.get("maturity_date"),
                issue_date=s.get("issue_date"),
            )
            for s in samples
        ]

    async def get_security_price(
        self,
        code: str,
        security_type: Optional[SecurityType] = None,
        settlement_date: Optional[str] = None,
    ) -> SecurityPriceResponse:
        """Get price calculation for a fixed income security"""
        # Auto-detect security type if not provided
        if security_type is None:
            security_type = self._detect_security_type(code)
            if security_type is None:
                raise ValueError(
                    f"Cannot auto-detect security type for code '{code}'. "
                    "Please specify the security_type parameter."
                )

        # Build cache key
        today = settlement_date or date.today().isoformat()
        cache_key = f"b3calc:price:{security_type}:{code}:{today}"
        cached = await self._cache.get(cache_key)

        if cached is not None:
            logger.info(f"Cache hit for price: {cache_key}")
            result = cached
            result.cached = True
            return result

        # Determine endpoint
        endpoint_map = {
            SecurityType.DEBENTURE: B3_CALC_ENDPOINTS["debenture_price"],
            SecurityType.CRA: B3_CALC_ENDPOINTS["cra_price"],
            SecurityType.CRI: B3_CALC_ENDPOINTS["cri_price"],
        }
        endpoint = endpoint_map[security_type]

        # Build request parameters
        params = {"code": code, "codigo": code}
        if settlement_date:
            params["settlementDate"] = settlement_date
            params["dataLiquidacao"] = settlement_date

        try:
            raw_data = await self._request(endpoint, params=params)
        except (FileNotFoundError, ConnectionError, TimeoutError) as exc:
            logger.warning(
                f"B3 CALC API unavailable for price of {code}: {exc}. "
                "Using sample data."
            )
            raw_data = self._generate_sample_price(code, security_type)

        # Parse price response
        price_result = self._parse_price_response(raw_data, settlement_date or today)

        # Try to extract security info
        security_info = self._parse_security_info(raw_data, code, security_type)

        result = SecurityPriceResponse(
            code=code,
            security_type=security_type.value,
            security_info=security_info,
            price=price_result,
            raw_response=raw_data if isinstance(raw_data, dict) else None,
            cached=False,
        )

        await self._cache.set(cache_key, result)
        return result

    def _generate_sample_price(self, code: str, security_type: SecurityType) -> Dict[str, Any]:
        """Generate sample price data for demonstration"""
        base_pu = 1000.0 + random.uniform(-50, 200)
        return {
            "codigo": code,
            "pu": round(base_pu, 6),
            "puPar": round(base_pu / 1000.0, 6),
            "taxaRetorno": round(random.uniform(10.0, 15.0), 4),
            "duration": round(random.uniform(200, 1000), 2),
            "dv01": round(random.uniform(0.05, 0.50), 6),
            "juroAcumulado": round(random.uniform(0, 50), 6),
            "dataLiquidacao": date.today().isoformat(),
            "taxaReferencia": round(random.uniform(10.5, 11.5), 4),
            "indice": "CDI",
            "percentualIndice": round(random.uniform(95, 120), 2),
            "_sample": True,
        }

    def _parse_price_response(
        self,
        raw_data: Dict[str, Any],
        settlement_date: str,
    ) -> PriceCalculationResult:
        """Parse B3 CALC price response into PriceCalculationResult"""
        if not isinstance(raw_data, dict):
            return PriceCalculationResult(settlement_date=settlement_date)

        def safe_float(value: Any) -> Optional[float]:
            try:
                return float(value) if value is not None else None
            except (ValueError, TypeError):
                return None

        return PriceCalculationResult(
            pu=safe_float(raw_data.get("pu", raw_data.get("PU", raw_data.get("precoUnitario")))),
            pu_par=safe_float(
                raw_data.get("puPar", raw_data.get("PU_PAR", raw_data.get("percentualPar")))
            ),
            yield_rate=safe_float(
                raw_data.get("taxaRetorno", raw_data.get("yield", raw_data.get("taxa")))
            ),
            duration=safe_float(
                raw_data.get("duration", raw_data.get("Duration", raw_data.get("duracao")))
            ),
            modified_duration=safe_float(
                raw_data.get("modifiedDuration", raw_data.get("durationModificada"))
            ),
            dv01=safe_float(raw_data.get("dv01", raw_data.get("DV01"))),
            accrued_interest=safe_float(
                raw_data.get("juroAcumulado", raw_data.get("accruedInterest", raw_data.get("jurosCorridos")))
            ),
            settlement_date=raw_data.get(
                "dataLiquidacao", raw_data.get("settlementDate", settlement_date)
            ),
            reference_rate=safe_float(
                raw_data.get("taxaReferencia", raw_data.get("referenceRate", raw_data.get("cdi")))
            ),
        )

    def _parse_security_info(
        self,
        raw_data: Dict[str, Any],
        code: str,
        security_type: SecurityType,
    ) -> Optional[SecurityInfo]:
        """Extract security info from price response"""
        if not isinstance(raw_data, dict):
            return SecurityInfo(code=code, security_type=security_type.value)

        return SecurityInfo(
            code=code,
            name=raw_data.get("nome", raw_data.get("name", raw_data.get("descricao"))),
            issuer=raw_data.get("emissor", raw_data.get("issuer", raw_data.get("empresa"))),
            isin=raw_data.get("isin", raw_data.get("ISIN")),
            security_type=security_type.value,
            index=raw_data.get("indice", raw_data.get("index", raw_data.get("indexador"))),
            rate=raw_data.get(
                "percentualIndice", raw_data.get("percentual", raw_data.get("spread"))
            ),
            maturity_date=raw_data.get(
                "vencimento", raw_data.get("maturityDate", raw_data.get("dataVencimento"))
            ),
            issue_date=raw_data.get(
                "emissao", raw_data.get("issueDate", raw_data.get("dataEmissao"))
            ),
            status=raw_data.get("situacao", raw_data.get("status")),
        )

    async def get_indexes(self) -> IndexesResponse:
        """Get current financial indexes from B3 CALC"""
        cache_key = f"b3calc:indexes:{date.today().isoformat()}"
        cached = await self._cache.get(cache_key)

        if cached is not None:
            return cached

        try:
            endpoint = B3_CALC_ENDPOINTS["indexes"]
            data = await self._request(endpoint)
            await self._cache.set(cache_key, IndexesResponse(**data))
            return IndexesResponse(**data)
        except Exception as exc:
            logger.warning(f"Could not fetch indexes from B3 CALC: {exc}")
            # Return sample indexes
            sample = SAMPLE_INDEXES.copy()
            sample["timestamp"] = datetime.now(timezone.utc).isoformat()
            result = IndexesResponse(**sample)
            await self._cache.set(cache_key, result)
            return result

    async def get_market_data(self) -> MarketDataResponse:
        """Get general market data including indexes and market status"""
        indexes_response = await self.get_indexes()

        # For now, return indexes as market data
        # In a real implementation, this would aggregate multiple data sources
        return MarketDataResponse(
            reference_date=indexes_response.reference_date,
            indexes=indexes_response.indexes,
            market_status="open",  # Simplified - would check actual market hours
        )
