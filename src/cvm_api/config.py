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
    FI = "fi"
    FIDC = "fidc"
    FIP = "fip"
    FIAGRO = "fiagro"
    FII = "fii"
    SECURIT = "securit"


class FIDocType(str, Enum):
    """FI (Fundos de Investimento) document types"""
    INF_DIARIO = "inf_diario"      # daily snapshot per fund — monthly ZIP
    CDA = "cda"                     # portfolio composition — monthly ZIP
    PERFIL_MENSAL = "perfil_mensal" # monthly investor profile — CSV
    BALANCETE = "balancete"         # monthly balance sheet — ZIP

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

class FIIDocType(str, Enum):
    """FII (Fundos de Investimento Imobiliário) document types"""
    MENSAL_GERAL = "mensal_geral"               # monthly general summary — yearly ZIP
    MENSAL_ATIVO_PASSIVO = "mensal_ativo_passivo" # monthly assets/liabilities — yearly ZIP
    TRIMESTRAL = "trimestral"                   # quarterly report — yearly ZIP
    ANUAL = "anual"                             # annual report — yearly ZIP
    DFIN = "dfin"                               # financial statements — yearly CSV

class SECURITDocType(str, Enum):
    """SECURIT document types"""
    CRA_MENSAL = "cra_mensal"
    CRI_MENSAL = "cri_mensal"
    OTS_MENSAL = "ots_mensal"
    DFIN_CRA = "dfin_cra"
    DFIN_CRI = "dfin_cri"

class DatasetConfig:
    """Dataset configuration mappings"""

    FI_DATASETS: Dict[str, Dict] = {
        "inf_diario": {
            "url_pattern": "{base_url}/FI/DOC/INF_DIARIO/DADOS/inf_diario_fi_{year}{month:02d}.zip",
            "is_zip": True,
            "csv_name_pattern": "inf_diario_fi_{year}{month:02d}.csv",
            "description": "Daily fund snapshot (quota price, NAV, flows, quotaholders) — monthly ZIP",
        },
        "cda": {
            "url_pattern": "{base_url}/FI/DOC/CDA/DADOS/cda_fi_{year}{month:02d}.zip",
            "is_zip": True,
            "csv_name_pattern": "cda_fi_BLC_1_{year}{month:02d}.csv",
            "description": "Portfolio composition by asset class — monthly ZIP",
        },
        "perfil_mensal": {
            "url_pattern": "{base_url}/FI/DOC/PERFIL_MENSAL/DADOS/perfil_mensal_fi_{year}{month:02d}.csv",
            "is_zip": False,
            "description": "Monthly investor profile (type, concentration) — monthly CSV",
        },
        "balancete": {
            "url_pattern": "{base_url}/FI/DOC/BALANCETE/DADOS/balancete_fi_{year}{month:02d}.zip",
            "is_zip": True,
            "csv_name_pattern": "balancete_fi_{year}{month:02d}.csv",
            "description": "Monthly balance sheet — monthly ZIP",
        },
    }

    FII_DATASETS: Dict[str, Dict] = {
        "mensal_geral": {
            "url_pattern": "{base_url}/FII/DOC/INF_MENSAL/DADOS/inf_mensal_fii_{year}.zip",
            "is_zip": True,
            "csv_name_pattern": "inf_mensal_fii_geral_{year}.csv",
            "description": "Monthly general summary for FII funds — yearly ZIP",
        },
        "mensal_ativo_passivo": {
            "url_pattern": "{base_url}/FII/DOC/INF_MENSAL/DADOS/inf_mensal_fii_{year}.zip",
            "is_zip": True,
            "csv_name_pattern": "inf_mensal_fii_ativo_passivo_{year}.csv",
            "description": "Monthly assets and liabilities for FII funds — yearly ZIP",
        },
        "trimestral": {
            "url_pattern": "{base_url}/FII/DOC/INF_TRIMESTRAL/DADOS/inf_trimestral_fii_{year}.zip",
            "is_zip": True,
            "csv_name_pattern": "inf_trimestral_fii_{year}.csv",
            "description": "Quarterly report for FII funds — yearly ZIP",
        },
        "anual": {
            "url_pattern": "{base_url}/FII/DOC/INF_ANUAL/DADOS/inf_anual_fii_{year}.zip",
            "is_zip": True,
            "csv_name_pattern": "inf_anual_fii_{year}.csv",
            "description": "Annual report for FII funds — yearly ZIP",
        },
        "dfin": {
            "url_pattern": "{base_url}/FII/DOC/DFIN/DADOS/dfin_fii_{year}.csv",
            "is_zip": False,
            "description": "FII financial statements — yearly CSV",
        },
    }

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
            "fi":      cls.FI_DATASETS,
            "fidc":    cls.FIDC_DATASETS,
            "fip":     cls.FIP_DATASETS,
            "fiagro":  cls.FIAGRO_DATASETS,
            "fii":     cls.FII_DATASETS,
            "securit": cls.SECURIT_DATASETS,
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
            "fi":      list(cls.FI_DATASETS.keys()),
            "fidc":    list(cls.FIDC_DATASETS.keys()),
            "fip":     list(cls.FIP_DATASETS.keys()),
            "fiagro":  list(cls.FIAGRO_DATASETS.keys()),
            "fii":     list(cls.FII_DATASETS.keys()),
            "securit": list(cls.SECURIT_DATASETS.keys()),
        }
        return entity_map.get(entity.lower(), [])

config = BaseConfig()
dataset_config = DatasetConfig()
