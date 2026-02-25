import os
import io
import csv
import socket
import logging
import asyncio
import zipfile
import aiohttp
import aiofiles
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
import math
import time
import hashlib
import json
import dns.resolver
from aiohttp.abc import AbstractResolver

if __package__:
    from .config import config, dataset_config
    from .models import DataResponse, PaginationInfo
    from ..validation_utils import validator, ValidationError, ValidationWarning
else:
    from config import config, dataset_config
    from models import DataResponse, PaginationInfo
    from validation_utils import validator, ValidationError, ValidationWarning

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

                    results = []
                    for answer in answers:
                        ip_address = answer.to_text()
                        results.append({
                            "hostname": host,
                            "host": ip_address,
                            "port": port,
                            "family": socket.AF_INET,
                            "proto": 0,
                            "flags": socket.AI_NUMERICHOST,
                        })

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

class CVMCreditDataService:
    """Service for downloading and processing CVM credit market data"""

    def __init__(self):
        """Initialize the CVM data service"""
        self.base_url = config.CVM_BASE_URL
        self.temp_dir = config.TEMP_DIR
        self.cache_dir = config.CACHE_DIR
        self.encoding = config.ENCODING
        self.separator = config.CSV_SEPARATOR
        self.timeout = config.REQUEST_TIMEOUT
        self.max_retries = config.MAX_RETRIES
        self.retry_delay = config.RETRY_DELAY
        self.dns_nameservers = [
            nameserver.strip()
            for nameserver in getattr(config, "CVM_DNS_NAMESERVERS", "").split(",")
            if nameserver.strip()
        ]

        # Create directories if they don't exist
        os.makedirs(self.temp_dir, exist_ok=True)
        os.makedirs(self.cache_dir, exist_ok=True)

        logger.info(f"CVMCreditDataService initialized with temp_dir: {self.temp_dir}, cache_dir: {self.cache_dir}")

    def _normalize_entity(self, entity: str) -> str:
        """Lowercase and strip entity name."""
        if not isinstance(entity, str) or not entity.strip():
            raise ValueError("Entity must be a non-empty string")
        return entity.strip().lower()

    def _normalize_doc_type(self, doc_type: str) -> str:
        """Lowercase, strip, and normalise separators in doc_type."""
        if not isinstance(doc_type, str) or not doc_type.strip():
            raise ValueError("Document type must be a non-empty string")
        return doc_type.strip().lower().replace("-", "_")

    def _resolve_doc_type_alias(self, entity: str, doc_type: str) -> str:
        """Resolve common doc_type aliases to the canonical value in dataset_config.

        Fixes e.g. get_data('fidc', 'cadastral') when config registers 'cad',
        or get_data('fidc', 'mensal') when config registers 'inf_mensal'.
        """
        available = dataset_config.get_available_doc_types(entity)
        if doc_type in available:
            return doc_type

        alias_map: Dict[str, tuple] = {
            "cadastral": ("cadastral", "cad", "cadastro"),
            "cad": ("cad", "cadastral", "cadastro"),
            "cadastro": ("cadastro", "cadastral", "cad"),
            "mensal": ("mensal", "inf_mensal"),
            "inf_mensal": ("inf_mensal", "mensal"),
            "trimestral": ("trimestral", "inf_trimestral"),
            "inf_trimestral": ("inf_trimestral", "trimestral"),
            "quadrimestral": ("quadrimestral", "inf_quadrimestral"),
            "inf_quadrimestral": ("inf_quadrimestral", "quadrimestral"),
            "anual": ("anual", "inf_anual"),
            "inf_anual": ("inf_anual", "anual"),
            # securit subtypes
            "cra": ("cra", "cra_mensal"),
            "cra_mensal": ("cra_mensal", "cra"),
            "cri": ("cri", "cri_mensal"),
            "cri_mensal": ("cri_mensal", "cri"),
            "ots": ("ots", "ots_mensal"),
            "ots_mensal": ("ots_mensal", "ots"),
        }
        for candidate in alias_map.get(doc_type, ()):
            if candidate in available:
                return candidate

        # Generic fallback: toggle the "inf_" prefix
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

    def _get_rotated_nameservers(self, attempt: int) -> List[str]:
        """Rotate DNS nameserver order by retry attempt."""
        if not self.dns_nameservers:
            return []

        shift = attempt % len(self.dns_nameservers)
        return self.dns_nameservers[shift:] + self.dns_nameservers[:shift]

    async def _build_client_session(self, timeout: aiohttp.ClientTimeout, attempt: int) -> aiohttp.ClientSession:
        """Create HTTP client session with DNS rotation when supported."""
        rotated_nameservers = self._get_rotated_nameservers(attempt)
        if not rotated_nameservers:
            return aiohttp.ClientSession(timeout=timeout, trust_env=True)

        try:
            resolver = RotatingDNSResolver(nameservers=rotated_nameservers)
            connector = aiohttp.TCPConnector(
                resolver=resolver,
                family=socket.AF_UNSPEC,
                ttl_dns_cache=300
            )
            logger.info(f"Using DNS resolvers for attempt {attempt + 1}: {', '.join(rotated_nameservers)}")
            return aiohttp.ClientSession(timeout=timeout, connector=connector, trust_env=True)
        except Exception as e:
            logger.warning(f"Custom DNS resolver unavailable, falling back to system resolver: {str(e)}")
            return aiohttp.ClientSession(timeout=timeout, trust_env=True)

    def _get_cache_key(self, url: str) -> str:
        """Generate a cache key from URL"""
        return hashlib.md5(url.encode()).hexdigest()

    def _get_cache_path(self, cache_key: str) -> str:
        """Get the full path for a cache file"""
        return os.path.join(self.cache_dir, f"{cache_key}.cache")

    def _get_cache_metadata_path(self, cache_key: str) -> str:
        """Get the full path for cache metadata"""
        return os.path.join(self.cache_dir, f"{cache_key}.meta")

    def _is_cache_valid(self, cache_key: str, max_age_hours: int = 24) -> bool:
        """Check if cache is still valid based on age"""
        metadata_path = self._get_cache_metadata_path(cache_key)
        if not os.path.exists(metadata_path):
            return False

        try:
            with open(metadata_path, 'r') as f:
                metadata = json.load(f)

            cached_time = datetime.fromisoformat(metadata['timestamp'])
            age_hours = (datetime.now() - cached_time).total_seconds() / 3600

            return age_hours < max_age_hours
        except Exception as e:
            logger.warning(f"Error checking cache validity: {str(e)}")
            return False

    async def _load_from_cache(self, cache_key: str) -> Optional[bytes]:
        """Load content from cache if available and valid"""
        cache_path = self._get_cache_path(cache_key)

        if not os.path.exists(cache_path) or not self._is_cache_valid(cache_key):
            return None

        try:
            async with aiofiles.open(cache_path, 'rb') as f:
                content = await f.read()
            logger.info(f"Loaded {len(content)} bytes from cache for key: {cache_key}")
            return content
        except Exception as e:
            logger.warning(f"Error loading from cache: {str(e)}")
            return None

    async def _save_to_cache(self, cache_key: str, content: bytes, url: str) -> None:
        """Save content to cache with metadata"""
        cache_path = self._get_cache_path(cache_key)
        metadata_path = self._get_cache_metadata_path(cache_key)

        try:
            # Save content
            async with aiofiles.open(cache_path, 'wb') as f:
                await f.write(content)

            # Save metadata
            metadata = {
                'timestamp': datetime.now().isoformat(),
                'url': url,
                'size': len(content)
            }

            async with aiofiles.open(metadata_path, 'w') as f:
                await f.write(json.dumps(metadata, indent=2))

            logger.info(f"Saved {len(content)} bytes to cache for key: {cache_key}")
        except Exception as e:
            logger.warning(f"Error saving to cache: {str(e)}")

    def _validate_parameters(self, entity: str, doc_type: str, year: Optional[int], month: Optional[int]) -> None:
        """Validate request parameters"""
        dataset_conf = dataset_config.get_dataset_config(entity, doc_type)

        # Check if year/month are required
        url_pattern = dataset_conf["url_pattern"]

        if "{year}" in url_pattern and year is None:
            raise ValueError(f"Year parameter is required for {entity}/{doc_type}")

        if "{month" in url_pattern and month is None:
            raise ValueError(f"Month parameter is required for {entity}/{doc_type}")

        # Validate year range
        if year is not None:
            now = datetime.now()
            current_year = now.year
            if year < 2000 or year > current_year:
                raise ValueError(f"Year must be between 2000 and {current_year}")

        # Validate month range
        if month is not None:
            if month < 1 or month > 12:
                raise ValueError("Month must be between 1 and 12")
            # Reject future months (data not yet published)
            if year is not None:
                now = datetime.now()
                if year == now.year and month > now.month:
                    raise ValueError(
                        f"Month {month} is in the future for year {year}; "
                        f"latest available is {now.month}"
                    )

    def _build_url(self, entity: str, doc_type: str, year: Optional[int], month: Optional[int]) -> Tuple[str, Dict]:
        """Build the download URL based on entity, doc_type, year, and month"""
        dataset_conf = dataset_config.get_dataset_config(entity, doc_type)
        url_pattern = dataset_conf["url_pattern"]

        # Format URL with parameters — only pass kwargs that exist so
        # format specs like {month:02d} never receive a non-integer.
        fmt_kwargs: Dict[str, Any] = {"base_url": self.base_url}
        if year is not None:
            fmt_kwargs["year"] = year
        if month is not None:
            fmt_kwargs["month"] = month
        url = url_pattern.format(**fmt_kwargs)

        return url, dataset_conf

    async def _download_file(self, url: str) -> bytes:
        """Download file from URL with retry logic and caching"""
        cache_key = self._get_cache_key(url)

        # Try to load from cache first
        cached_content = await self._load_from_cache(cache_key)
        if cached_content is not None:
            logger.info(f"Using cached content for URL: {url}")
            return cached_content

        # Cache miss, download from URL
        for attempt in range(self.max_retries):
            try:
                logger.info(f"Downloading from {url} (attempt {attempt + 1}/{self.max_retries})")

                timeout = aiohttp.ClientTimeout(total=self.timeout)
                async with await self._build_client_session(timeout, attempt) as session:
                    async with session.get(url) as response:
                        if response.status == 404:
                            raise ValueError(f"Data not found at URL: {url}. The requested period may not be available.")

                        if response.status != 200:
                            raise Exception(f"HTTP {response.status}: Failed to download file from {url}")

                        content = await response.read()
                        logger.info(f"Successfully downloaded {len(content)} bytes from {url}")

                        # Save to cache
                        await self._save_to_cache(cache_key, content, url)

                        return content

            except aiohttp.ClientError as e:
                logger.warning(f"Download attempt {attempt + 1} failed: {str(e)}")
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(self.retry_delay * (attempt + 1))
                else:
                    raise Exception(f"Failed to download file after {self.max_retries} attempts: {str(e)}")

            except Exception as e:
                logger.error(f"Unexpected error during download: {str(e)}")
                raise

    def _extract_csv_from_zip(self, zip_content: bytes, csv_name_pattern: str, year: Optional[int], month: Optional[int]) -> str:
        """Extract CSV content from ZIP file"""
        try:
            # Format the expected CSV filename
            csv_filename = csv_name_pattern.format(year=year or "", month=month or "")

            with zipfile.ZipFile(io.BytesIO(zip_content)) as zip_file:
                # List all files in the ZIP
                file_list = zip_file.namelist()
                logger.info(f"Files in ZIP: {file_list}")

                # Try to find the CSV file
                csv_file = None
                for filename in file_list:
                    if filename.lower().endswith('.csv'):
                        if csv_filename.lower() in filename.lower():
                            csv_file = filename
                            break

                # If exact match not found, try to use the first CSV
                if not csv_file:
                    for filename in file_list:
                        if filename.lower().endswith('.csv'):
                            csv_file = filename
                            logger.warning(f"Using first CSV file found: {csv_file}")
                            break

                if not csv_file:
                    raise ValueError(f"No CSV file found in ZIP archive")

                # Extract and decode CSV content
                csv_content = zip_file.read(csv_file).decode(self.encoding)

                logger.info(f"Extracted CSV file: {csv_file} ({len(csv_content)} characters)")
                return csv_content

        except zipfile.BadZipFile:
            raise ValueError("Invalid ZIP file format")
        except Exception as e:
            logger.error(f"Error extracting CSV from ZIP: {str(e)}")
            raise

    def _parse_csv_content(self, csv_content: str) -> List[Dict[str, Any]]:
        """Parse CSV content into list of dictionaries"""
        try:
            csv_reader = csv.DictReader(
                io.StringIO(csv_content),
                delimiter=self.separator
            )

            data = []
            for row in csv_reader:
                # Clean up field names and values
                cleaned_row = {}
                for key, value in row.items():
                    if key:  # Skip empty keys
                        clean_key = key.strip()
                        clean_value = value.strip() if value else None
                        cleaned_row[clean_key] = clean_value

                if cleaned_row:  # Only add non-empty rows
                    data.append(cleaned_row)

            logger.info(f"Parsed {len(data)} records from CSV")

            # Validate parsed data
            self._validate_parsed_data(data)

            return data

        except Exception as e:
            logger.error(f"Error parsing CSV content: {str(e)}")
            raise ValueError(f"Failed to parse CSV data: {str(e)}")

    def _validate_parsed_data(self, data: List[Dict[str, Any]]) -> None:
        """Validate parsed CSV data for common issues"""
        if not data:
            raise ValueError("No data records found in CSV")

        first_row = next((row for row in data if row), {})
        if not first_row:
            logger.warning("All parsed rows are empty")
            return

        # Log validation summary
        total_records = len(data)
        field_count = len(first_row)
        logger.info(f"Data validation passed: {total_records} records, {field_count} fields per record")

        # Check for completely empty records
        empty_records = sum(1 for row in data if all(v is None or v == "" for v in row.values()))
        if empty_records > 0:
            logger.warning(f"Found {empty_records} completely empty records out of {total_records}")

        # Basic field validation - ensure common fields exist
        common_fields = ['CNPJ', 'DENOM', 'DATA', 'VALOR']  # Common patterns in CVM data
        available_fields = set(first_row.keys())

        found_common = [field for field in common_fields if any(field in key.upper() for key in available_fields)]
        if found_common:
            logger.info(f"Found common fields: {found_common}")

    def _validate_data_quality(self, data: List[Dict[str, Any]], entity: str, doc_type: str) -> Dict[str, Any]:
        """Perform comprehensive data quality validation using validation utilities"""
        # Define validation rules based on entity and document type
        validation_config = self._get_validation_config(entity, doc_type)

        # Use the comprehensive validator
        quality_report = validator.validate_dataset(data, validation_config)

        logger.info(f"Data quality validation completed: {len(quality_report['validation_errors'])} errors, {len(quality_report['warnings'])} warnings")
        return quality_report

    def _get_validation_config(self, entity: str, doc_type: str) -> Dict[str, Any]:
        """Get validation configuration for entity and document type"""
        base_config = {
            "required_fields": [],
            "field_types": {},
            "business_rules": []
        }

        # Entity-specific validation rules
        if entity.lower() == "fidc":
            # Only "mensal" is registered for FIDC
            if "mensal" in doc_type.lower():
                base_config["field_types"] = {
                    "CNPJ_FUNDO": "cnpj",
                    "DT_COMPTC": "date",
                    "VL_TOTAL": "numeric",
                    "VL_QUOTA": "numeric"
                }

        elif entity.lower() == "fip":
            # inf_quadrimestral / inf_trimestral — no "cadastral" doc_type in config
            base_config["field_types"] = {
                "CNPJ_FUNDO": "cnpj",
            }

        elif entity.lower() == "fiagro":
            # Only "mensal" is registered for FIAGRO
            if "mensal" in doc_type.lower():
                base_config["field_types"] = {
                    "CNPJ_FUNDO": "cnpj",
                    "DT_COMPTC": "date",
                }

        elif entity.lower() == "securit":
            # cra_mensal / cri_mensal / ots_mensal
            if "mensal" in doc_type.lower():
                base_config["field_types"] = {
                    "CNPJ_SECURIT": "cnpj",
                    "DT_EMISSAO": "date",
                    "VL_EMISSAO": "numeric",
                    "QT_TITULOS": "numeric"
                }

        return base_config

    def _validate_fidc_cadastral_data(self, data: List[Dict[str, Any]], validation_report: Dict[str, Any]) -> None:
        """Validate FIDC cadastral data for required fields and formats"""
        required_fields = ['CNPJ_FUNDO', 'DENOM_SOCIAL', 'DT_REG']
        available_fields = set(data[0].keys()) if data else set()

        for field in required_fields:
            if field not in available_fields:
                validation_report["validation_errors"].append(f"Required field '{field}' missing from FIDC cadastral data")

        # Validate CNPJ format (basic check)
        cnpj_field = None
        for field in available_fields:
            if 'CNPJ' in field.upper():
                cnpj_field = field
                break

        if cnpj_field:
            invalid_cnpjs = 0
            for row in data:
                cnpj = row.get(cnpj_field, "")
                if cnpj and not self._is_valid_cnpj_format(cnpj):
                    invalid_cnpjs += 1

            if invalid_cnpjs > 0:
                validation_report["warnings"].append(f"Found {invalid_cnpjs} records with invalid CNPJ format")

    def _is_valid_cnpj_format(self, cnpj: str) -> bool:
        """Basic CNPJ format validation"""
        if not cnpj:
            return False

        # Remove formatting characters
        cnpj = ''.join(filter(str.isdigit, cnpj))

        # CNPJ should have 14 digits
        return len(cnpj) == 14

    def _paginate_data(self, data: List[Dict[str, Any]], page: int, page_size: int) -> Tuple[List[Dict[str, Any]], PaginationInfo]:
        """Paginate data and return page with pagination info"""
        total_items = len(data)
        total_pages = math.ceil(total_items / page_size) if total_items > 0 else 0

        # Calculate start and end indices
        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size

        # Get page data
        page_data = data[start_idx:end_idx]

        # Create pagination info
        pagination_info = PaginationInfo(
            page=page,
            page_size=page_size,
            total_items=total_items,
            total_pages=total_pages,
            has_next=page < total_pages,
            has_previous=page > 1
        )

        return page_data, pagination_info

    async def get_data(
        self,
        entity: str,
        doc_type: str,
        year: Optional[int] = None,
        month: Optional[int] = None,
        page: int = 1,
        page_size: int = config.DEFAULT_PAGE_SIZE
    ) -> DataResponse:
        """Get data for specified entity and document type"""
        start_time = time.time()

        try:
            # Normalise + resolve aliases before any validation or URL building
            entity = self._normalize_entity(entity)
            doc_type = self._normalize_doc_type(doc_type)
            doc_type = self._resolve_doc_type_alias(entity, doc_type)

            # Validate parameters
            self._validate_parameters(entity, doc_type, year, month)

            # Build URL
            url, dataset_conf = self._build_url(entity, doc_type, year, month)
            logger.info(f"Processing request: {entity}/{doc_type} from {url}")

            # Download file
            file_content = await self._download_file(url)

            # Handle ZIP or direct CSV
            if dataset_conf["is_zip"]:
                csv_content = self._extract_csv_from_zip(
                    file_content,
                    dataset_conf["csv_name_pattern"],
                    year,
                    month
                )
            else:
                csv_content = file_content.decode(self.encoding)

            # Parse CSV content
            all_data = self._parse_csv_content(csv_content)

            # Perform data quality validation
            validation_report = self._validate_data_quality(all_data, entity, doc_type)

            # Paginate data
            page_data, pagination_info = self._paginate_data(all_data, page, page_size)

            # Build metadata
            metadata = {
                "source_url": url,
                "description": dataset_conf["description"],
                "is_zip": dataset_conf["is_zip"],
                "processing_time_seconds": round(time.time() - start_time, 2),
                "data_quality": validation_report
            }

            if year:
                metadata["year"] = year
            if month:
                metadata["month"] = month

            # Create response
            response = DataResponse(
                entity=entity,
                doc_type=doc_type,
                data=page_data,
                pagination=pagination_info,
                metadata=metadata
            )

            logger.info(f"Request completed successfully in {metadata['processing_time_seconds']}s: {len(page_data)} records returned")
            return response

        except ValueError as e:
            # Re-raise validation errors
            raise

        except Exception as e:
            logger.error(f"Error processing request: {str(e)}", exc_info=True)
            raise Exception(f"Failed to process data request: {str(e)}")

    def cleanup_temp_files(self) -> None:
        """Clean up temporary files"""
        try:
            if os.path.exists(self.temp_dir):
                for filename in os.listdir(self.temp_dir):
                    file_path = os.path.join(self.temp_dir, filename)
                    try:
                        if os.path.isfile(file_path):
                            os.unlink(file_path)
                    except Exception as e:
                        logger.error(f"Error deleting {file_path}: {str(e)}")
                logger.info("Temporary files cleaned up")
        except Exception as e:
            logger.error(f"Error during cleanup: {str(e)}")

    def clear_cache(self) -> None:
        """Clear all cached files"""
        try:
            if os.path.exists(self.cache_dir):
                cleared_count = 0
                for filename in os.listdir(self.cache_dir):
                    file_path = os.path.join(self.cache_dir, filename)
                    try:
                        if os.path.isfile(file_path):
                            os.unlink(file_path)
                            cleared_count += 1
                    except Exception as e:
                        logger.error(f"Error deleting {file_path}: {str(e)}")
                logger.info(f"Cache cleared: {cleared_count} files removed")
        except Exception as e:
            logger.error(f"Error during cache cleanup: {str(e)}")

    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        try:
            stats = {
                "cache_dir": self.cache_dir,
                "total_files": 0,
                "total_size_bytes": 0,
                "oldest_file": None,
                "newest_file": None
            }

            if os.path.exists(self.cache_dir):
                files = [f for f in os.listdir(self.cache_dir) if f.endswith('.meta')]
                stats["total_files"] = len(files)

                oldest_time = None
                newest_time = None

                for meta_file in files:
                    try:
                        meta_path = os.path.join(self.cache_dir, meta_file)
                        with open(meta_path, 'r') as f:
                            metadata = json.load(f)

                        file_time = datetime.fromisoformat(metadata['timestamp'])
                        stats["total_size_bytes"] += metadata.get('size', 0)

                        if oldest_time is None or file_time < oldest_time:
                            oldest_time = file_time
                        if newest_time is None or file_time > newest_time:
                            newest_time = file_time

                    except Exception as e:
                        logger.warning(f"Error reading cache metadata {meta_file}: {str(e)}")

                if oldest_time:
                    stats["oldest_file"] = oldest_time.isoformat()
                if newest_time:
                    stats["newest_file"] = newest_time.isoformat()

            return stats
        except Exception as e:
            logger.error(f"Error getting cache stats: {str(e)}")
            return {"error": str(e)}