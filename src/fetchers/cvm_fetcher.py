"""CVM fetcher — downloads ZIP/CSV files from dados.cvm.gov.br with retry,
DNS rotation, and on-disk caching, then extracts and parses the CSV payload
into a list of dict rows.

Public surface:
    CVMFetcher().fetch(entity, doc_type, year=None, month=None) -> List[dict]

Used by src/pipeline/cvm_pipeline.py.
"""

import asyncio
import csv
import hashlib
import io
import json
import logging
import os
import socket
import sys
import time
import zipfile
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import aiofiles
import aiohttp
import dns.resolver
from aiohttp.abc import AbstractResolver

from .cvm_config import config, dataset_config

logger = logging.getLogger(__name__)


class RotatingDNSResolver(AbstractResolver):
    """DNS resolver that rotates explicit nameservers for host resolution."""

    def __init__(self, nameservers: List[str], timeout: float = 3.0):
        self.nameservers = nameservers
        self.timeout = timeout

    async def resolve(self, host: str, port: int = 0, family: int = socket.AF_UNSPEC) -> List[Dict[str, Any]]:
        def _resolve_sync() -> List[Dict[str, Any]]:
            for nameserver in self.nameservers:
                try:
                    resolver = dns.resolver.Resolver(configure=False)
                    resolver.nameservers = [nameserver]
                    resolver.lifetime = self.timeout
                    answers = resolver.resolve(host, "A")
                    results = [
                        {
                            "hostname": host,
                            "host": answer.to_text(),
                            "port": port,
                            "family": socket.AF_INET,
                            "proto": 0,
                            "flags": socket.AI_NUMERICHOST,
                        }
                        for answer in answers
                    ]
                    if results:
                        return results
                except Exception:
                    continue

            fallback = socket.getaddrinfo(host, port, family=family, type=socket.SOCK_STREAM)
            return [
                {
                    "hostname": host,
                    "host": addr[4][0],
                    "port": addr[4][1],
                    "family": addr[0],
                    "proto": addr[2],
                    "flags": addr[3],
                }
                for addr in fallback
            ]

        return await asyncio.to_thread(_resolve_sync)

    async def close(self) -> None:
        return None


class CVMFetcher:
    """Fetch + parse CVM datasets. No storage, no HTTP API surface."""

    def __init__(self) -> None:
        self.base_url = config.CVM_BASE_URL
        self.temp_dir = config.TEMP_DIR
        self.cache_dir = config.CACHE_DIR
        self.encoding = config.ENCODING
        self.separator = config.CSV_SEPARATOR
        self.timeout = config.REQUEST_TIMEOUT
        self.max_retries = config.MAX_RETRIES
        self.retry_delay = config.RETRY_DELAY
        self.dns_nameservers = [
            ns.strip()
            for ns in (config.CVM_DNS_NAMESERVERS or "").split(",")
            if ns.strip()
        ]
        os.makedirs(self.temp_dir, exist_ok=True)
        os.makedirs(self.cache_dir, exist_ok=True)

    # ---------------------------------------------------------------- helpers
    def _normalize(self, value: str, label: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{label} must be a non-empty string")
        return value.strip().lower().replace("-", "_") if label == "doc_type" else value.strip().lower()

    def _resolve_doc_type_alias(self, entity: str, doc_type: str) -> str:
        available = dataset_config.get_available_doc_types(entity)
        if doc_type in available:
            return doc_type

        alias_map: Dict[str, tuple] = {
            "mensal": ("mensal", "inf_mensal"),
            "inf_mensal": ("inf_mensal", "mensal"),
            "trimestral": ("trimestral", "inf_trimestral"),
            "inf_trimestral": ("inf_trimestral", "trimestral"),
            "quadrimestral": ("quadrimestral", "inf_quadrimestral"),
            "inf_quadrimestral": ("inf_quadrimestral", "quadrimestral"),
            "anual": ("anual", "inf_anual"),
            "cra": ("cra_mensal",),
            "cri": ("cri_mensal",),
            "ots": ("ots_mensal",),
        }
        for candidate in alias_map.get(doc_type, ()):
            if candidate in available:
                return candidate
        if doc_type.startswith("inf_"):
            candidate = doc_type.removeprefix("inf_")
            if candidate in available:
                return candidate
        else:
            candidate = f"inf_{doc_type}"
            if candidate in available:
                return candidate
        raise ValueError(
            f"Unknown document type '{doc_type}' for entity '{entity}'. "
            f"Available: {', '.join(available)}"
        )

    # ---------------------------------------------------------------- DNS
    def _rotated_nameservers(self, attempt: int) -> List[str]:
        if not self.dns_nameservers:
            return []
        shift = attempt % len(self.dns_nameservers)
        return self.dns_nameservers[shift:] + self.dns_nameservers[:shift]

    async def _build_session(self, timeout: aiohttp.ClientTimeout, attempt: int) -> aiohttp.ClientSession:
        rotated = self._rotated_nameservers(attempt)
        if not rotated:
            return aiohttp.ClientSession(timeout=timeout, trust_env=True)
        try:
            connector = aiohttp.TCPConnector(
                resolver=RotatingDNSResolver(nameservers=rotated),
                family=socket.AF_UNSPEC,
                ttl_dns_cache=300,
            )
            return aiohttp.ClientSession(timeout=timeout, connector=connector, trust_env=True)
        except Exception as exc:
            logger.warning(f"Custom DNS resolver unavailable, using system resolver: {exc}")
            return aiohttp.ClientSession(timeout=timeout, trust_env=True)

    # ---------------------------------------------------------------- cache
    def _cache_paths(self, url: str) -> Tuple[str, str]:
        key = hashlib.md5(url.encode()).hexdigest()
        return (
            os.path.join(self.cache_dir, f"{key}.cache"),
            os.path.join(self.cache_dir, f"{key}.meta"),
        )

    def _is_cache_valid(self, meta_path: str, max_age_hours: int = 24) -> bool:
        if not os.path.exists(meta_path):
            return False
        try:
            with open(meta_path, "r") as f:
                metadata = json.load(f)
            cached = datetime.fromisoformat(metadata["timestamp"])
            if cached.tzinfo is None:
                cached = cached.replace(tzinfo=timezone.utc)
            return (datetime.now(timezone.utc) - cached).total_seconds() / 3600 < max_age_hours
        except Exception:
            return False

    async def _load_cache(self, cache_path: str, meta_path: str) -> Optional[bytes]:
        if not os.path.exists(cache_path) or not self._is_cache_valid(meta_path):
            return None
        try:
            async with aiofiles.open(cache_path, "rb") as f:
                return await f.read()
        except Exception:
            return None

    async def _save_cache(self, cache_path: str, meta_path: str, content: bytes, url: str) -> None:
        try:
            async with aiofiles.open(cache_path, "wb") as f:
                await f.write(content)
            metadata = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "url": url,
                "size": len(content),
            }
            async with aiofiles.open(meta_path, "w") as f:
                await f.write(json.dumps(metadata, indent=2))
        except Exception as exc:
            logger.warning(f"Cache write failed: {exc}")

    # ---------------------------------------------------------------- validate params
    def _validate_params(self, entity: str, doc_type: str, year: Optional[int], month: Optional[int]) -> None:
        ds = dataset_config.get_dataset_config(entity, doc_type)
        url_pattern = ds["url_pattern"]
        if "{year}" in url_pattern and year is None:
            raise ValueError(f"year is required for {entity}/{doc_type}")
        if "{month" in url_pattern and month is None:
            raise ValueError(f"month is required for {entity}/{doc_type}")
        if year is not None:
            now = datetime.now(timezone.utc)
            if year < 2000 or year > now.year:
                raise ValueError(f"year must be between 2000 and {now.year}")
        if month is not None:
            if month < 1 or month > 12:
                raise ValueError("month must be between 1 and 12")
            if year is not None:
                now = datetime.now(timezone.utc)
                if year == now.year and month > now.month:
                    raise ValueError(
                        f"month {month} is in the future for year {year}; latest available is {now.month}"
                    )

    def _build_url(self, entity: str, doc_type: str, year: Optional[int], month: Optional[int]) -> Tuple[str, Dict]:
        ds = dataset_config.get_dataset_config(entity, doc_type)
        kwargs: Dict[str, Any] = {"base_url": self.base_url}
        if year is not None:
            kwargs["year"] = year
        if month is not None:
            kwargs["month"] = month
        return ds["url_pattern"].format(**kwargs), ds

    # ---------------------------------------------------------------- HTTP
    async def _download(self, url: str) -> bytes:
        cache_path, meta_path = self._cache_paths(url)
        cached = await self._load_cache(cache_path, meta_path)
        if cached is not None:
            return cached

        for attempt in range(self.max_retries):
            try:
                timeout = aiohttp.ClientTimeout(total=self.timeout)
                async with await self._build_session(timeout, attempt) as session:
                    async with session.get(url) as response:
                        if response.status == 404:
                            raise ValueError(f"Data not found at {url}")
                        if response.status != 200:
                            raise RuntimeError(f"HTTP {response.status} from {url}")
                        content = await response.read()
                        await self._save_cache(cache_path, meta_path, content, url)
                        return content
            except aiohttp.ClientError as exc:
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(self.retry_delay * (attempt + 1))
                    continue
                raise RuntimeError(f"Download failed after {self.max_retries} attempts: {exc}") from exc

        raise RuntimeError(f"Download failed for {url}")

    # ---------------------------------------------------------------- parse
    def _extract_csv_from_zip(
        self,
        zip_content: bytes,
        csv_name_pattern: str,
        year: Optional[int],
        month: Optional[int],
    ) -> str:
        expected = csv_name_pattern.format(year=year or "", month=month or "")
        with zipfile.ZipFile(io.BytesIO(zip_content)) as zf:
            files = zf.namelist()
            csv_file = next(
                (f for f in files if f.lower().endswith(".csv") and expected.lower() in f.lower()),
                None,
            )
            if not csv_file:
                csv_file = next((f for f in files if f.lower().endswith(".csv")), None)
            if not csv_file:
                raise ValueError(f"No CSV file found in ZIP. Files: {files}")
            return zf.read(csv_file).decode(self.encoding)

    def _parse_csv(self, csv_content: str) -> List[Dict[str, Any]]:
        # Some CVM CSVs have very long fields (e.g. FI perfil_mensal).
        # Raise the Python csv module's default 128KB limit.
        try:
            csv.field_size_limit(sys.maxsize)
        except OverflowError:
            csv.field_size_limit(2 ** 31 - 1)
        reader = csv.DictReader(io.StringIO(csv_content), delimiter=self.separator)
        rows: List[Dict[str, Any]] = []
        for row in reader:
            cleaned = {
                k.strip(): (v.strip() if v else None)
                for k, v in row.items()
                if k
            }
            if cleaned:
                rows.append(cleaned)
        return rows

    # ---------------------------------------------------------------- public API
    async def fetch(
        self,
        entity: str,
        doc_type: str,
        year: Optional[int] = None,
        month: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Download, decompress (if needed), and parse one CVM CSV. Returns
        the full list of row dicts. Caller is responsible for storage."""
        entity = self._normalize(entity, "entity")
        doc_type = self._normalize(doc_type, "doc_type")
        doc_type = self._resolve_doc_type_alias(entity, doc_type)

        self._validate_params(entity, doc_type, year, month)
        url, ds = self._build_url(entity, doc_type, year, month)
        logger.info(f"CVM fetch: {entity}/{doc_type} year={year} month={month} -> {url}")

        started = time.time()
        content = await self._download(url)

        if ds["is_zip"]:
            csv_text = self._extract_csv_from_zip(content, ds["csv_name_pattern"], year, month)
        else:
            csv_text = content.decode(self.encoding)

        rows = self._parse_csv(csv_text)
        logger.info(f"CVM parse: {entity}/{doc_type} -> {len(rows)} rows in {time.time() - started:.1f}s")
        return rows

    # Backwards-compat alias used by pipeline imports written before the rename.
    download_and_parse = fetch
