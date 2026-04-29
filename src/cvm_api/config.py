import os
from typing import Dict, List
from enum import Enum

class BaseConfig:
    """Base configuration for CVM Credit Market API"""
    API_TITLE = "CVM Credit Market Data API"
    API_VERSION = "1.0.0"
    API_DESCRIPTION = "API for accessing Brazilian CVM credit market data including FIDC, FIP, FIAGRO, and SECURIT"
    

# CVM Base URLs
    CVM_BASE_URL = "https://dados.cvm.gov.br/dados"


# B3 CALC Base URL
    B3_CALC_BASE_URL = "https://www.b3.com.br/calc/api"


# Default pagination
    DEFAULT_PAGE_SIZE = 100
    MAX_PAGE_SIZE = 10000


# File handling
    TEMP_DIR = os.path.join(os.getcwd(), "temp")
    CACHE_DIR = os.path.join(os.getcwd(), "cache")
    ENCODING = "latin-1"
    CSV_SEPARATOR = ";"


# Request settings
    REQUEST_TIMEOUT = 300
    MAX_RETRIES = 3
    RETRY_DELAY = 2


# DNS resolver rotation (for network reliability)
    CVM_DNS_NAMESERVERS = os.getenv("CVM_DNS_NAMESERVERS", "1.1.1.1,8.8.8.8,9.9.9.9")


# B3 CALC Cache settings
    B3_CALC_CACHE_TTL_SECONDS = 1800  # 30 minutes for price data
    B3_CALC_CACHE_MAX_SIZE = 64



class EntityType(str, Enum):
    """Supported CVM entity types"""
    FIDC = "fidc"
    FIP = "fip"
    FIAGRO = "fiagro"
    SECURIT = "securit"


class FIDCDocType(str, Enum):
    """FIDC document types"""
    MENSAL = "mensal"

class FIPDocType(str, Enum):
    """FIP document types"""
    INF_QUADRIMESTRAL = "inf_quadrimestral"
    INF_TRIMESTRAL = "inf_trimestral"

class FIAGRODocType(str, Enum):
    """FIAGRO document types (available from May 2025)"""
    MENSAL = "mensal"

class SECURITDocType(str, Enum):
    """SECURIT document types"""
    CRA_MENSAL = "cra_mensal"
    CRI_MENSAL = "cri_mensal"
    OTS_MENSAL = "ots_mensal"
    DFIN_CRA = "dfin_cra"
    DFIN_CRI = "dfin_cri"

class DatasetConfig:
    """Dataset configuration mappings"""
      
    FIDC_DATASETS: Dict[str, Dict] = {
        "mensal": {
            "url_pattern": "{base_url}/FIDC/DOC/INF_MENSAL/DADOS/inf_mensal_fidc_{year}{month:02d}.zip",
            "is_zip": True,
            "csv_name_pattern": "inf_mensal_fidc_{year}{month:02d}.csv",
            "description": "Monthly information for FIDC funds"
        },
    }
      
    FIP_DATASETS: Dict[str, Dict] = {
        "inf_quadrimestral": {
            "url_pattern": "{base_url}/FIP/DOC/INF_QUADRIMESTRAL/DADOS/inf_quadrimestral_fip_{year}.csv",
            "is_zip": False,
            "description": "Four-month period information for FIP funds — yearly CSV (2024+)"
        },
        "inf_trimestral": {
            "url_pattern": "{base_url}/FIP/DOC/INF_TRIMESTRAL/DADOS/inf_trimestral_fip_{year}.csv",
            "is_zip": False,
            "description": "Quarterly information for FIP funds — yearly CSV (2010–2023)"
        },
    }
      
    FIAGRO_DATASETS: Dict[str, Dict] = {
        "mensal": {
            "url_pattern": "{base_url}/FIAGRO/DOC/INF_MENSAL/DADOS/inf_mensal_fiagro_{year}{month:02d}.zip",
            "is_zip": True,
            "csv_name_pattern": "inf_mensal_fiagro_{year}{month:02d}.csv",
            "description": "Monthly information for FIAGRO funds (available from May 2025)"
        },
    }
      
    SECURIT_DATASETS: Dict[str, Dict] = {
        "cra_mensal": {
            "url_pattern": "{base_url}/SECURIT/DOC/INF_MENSAL_CRA/DADOS/inf_mensal_cra_{year}.zip",
            "is_zip": True,
            "csv_name_pattern": "inf_mensal_cra_{year}.csv",
            "description": "Monthly CRA securitization data — yearly ZIP"
        },
        "cri_mensal": {
            "url_pattern": "{base_url}/SECURIT/DOC/INF_MENSAL_CRI/DADOS/inf_mensal_cri_{year}.zip",
            "is_zip": True,
            "csv_name_pattern": "inf_mensal_cri_{year}.csv",
            "description": "Monthly CRI securitization data — yearly ZIP"
        },
        "ots_mensal": {
            "url_pattern": "{base_url}/SECURIT/DOC/INF_MENSAL_OTS/DADOS/inf_mensal_ots_{year}.zip",
            "is_zip": True,
            "csv_name_pattern": "inf_mensal_ots_{year}.csv",
            "description": "Monthly securitization data for other titles — yearly ZIP"
        },
        "dfin_cra": {
            "url_pattern": "{base_url}/SECURIT/DOC/DFIN_CRA/DADOS/dfin_cra_{year}.csv",
            "is_zip": False,
            "description": "CRA financial statements — yearly CSV (2019+)"
        },
        "dfin_cri": {
            "url_pattern": "{base_url}/SECURIT/DOC/DFIN_CRI/DADOS/dfin_cri_{year}.csv",
            "is_zip": False,
            "description": "CRI financial statements — yearly CSV (2018+)"
        },
    }
      
    @classmethod
    def get_dataset_config(cls, entity: str, doc_type: str) -> Dict:
        """Get dataset configuration for entity and document type"""
        entity_map = {
            "fidc": cls.FIDC_DATASETS,
            "fip": cls.FIP_DATASETS,
            "fiagro": cls.FIAGRO_DATASETS,
            "securit": cls.SECURIT_DATASETS
        }
          
        datasets = entity_map.get(entity.lower())
        if not datasets:
            raise ValueError(f"Unknown entity type: {entity}")
          
        config = datasets.get(doc_type.lower())
        if not config:
            raise ValueError(f"Unknown document type '{doc_type}' for entity '{entity}'")
          
        return config
      
    @classmethod
    def get_available_doc_types(cls, entity: str) -> List[str]:
        """Get list of available document types for an entity"""
        entity_map = {
            "fidc": list(cls.FIDC_DATASETS.keys()),
            "fip": list(cls.FIP_DATASETS.keys()),
            "fiagro": list(cls.FIAGRO_DATASETS.keys()),
            "securit": list(cls.SECURIT_DATASETS.keys())
        }
        return entity_map.get(entity.lower(), [])

config = BaseConfig()
dataset_config = DatasetConfig()
