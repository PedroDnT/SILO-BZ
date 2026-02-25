"""Configuration for CVM credit market data backfill operations."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional

class EntityType(Enum):
    """Supported CVM entity types."""
    FIDC = "FIDC"
    FIP = "FIP"
    FIAGRO = "FIAGRO"
    SECURIT = "SECURIT"

class DocumentType(Enum):
    """Supported document types."""
    INF_MENSAL = "INF_MENSAL"
    INF_QUADRIMESTRAL = "INF_QUADRIMESTRAL"
    CRA_MENSAL = "CRA_MENSAL"
    CRI_MENSAL = "CRI_MENSAL"
    LCA_MENSAL = "LCA_MENSAL"
    LCI_MENSAL = "LCI_MENSAL"

class Frequency(Enum):
    """Data frequency types."""
    MONTHLY = "monthly"
    QUADRIMESTRAL = "quadrimestral"

@dataclass
class EntityConfig:
    """Configuration for a specific entity and document type."""
    entity_type: EntityType
    doc_type: DocumentType
    frequency: Frequency
    start_date: str  # YYYYMM format
    base_url_template: str
    file_extension: str = "csv"
    
    def get_url(self, period: str) -> str:
        """Generate download URL for a specific period."""
        return self.base_url_template.format(
            entity=self.entity_type.value,
            doc_type=self.doc_type.value,
            period=period
        )
    
    def get_file_path(self, base_dir: Path, period: str) -> Path:
        """Generate local file path for a specific period."""
        entity_dir = base_dir / self.entity_type.value / self.doc_type.value
        entity_dir.mkdir(parents=True, exist_ok=True)
        return entity_dir / f"{period}.{self.file_extension}"

class BackfillConfig:
    """Main configuration for backfill operations."""
    
    # Base configuration
    BASE_DIR = Path("data/cvm_backfill")
    METADATA_DIR = BASE_DIR / ".metadata"
    LOG_DIR = BASE_DIR / ".logs"
    
    # Download configuration
    MAX_WORKERS = 5
    REQUEST_TIMEOUT = 60  # seconds
    MAX_RETRIES = 3
    RETRY_DELAY = 2  # seconds
    
    # CVM data URLs (adjust these to actual CVM endpoints)
    CVM_BASE_URL = "https://dados.cvm.gov.br/dados"
    
    # Entity configurations
    ENTITY_CONFIGS: Dict[str, EntityConfig] = {
        # FIDC - Monthly reports since 2019
        "FIDC_INF_MENSAL": EntityConfig(
            entity_type=EntityType.FIDC,
            doc_type=DocumentType.INF_MENSAL,
            frequency=Frequency.MONTHLY,
            start_date="201901",
            base_url_template=f"{CVM_BASE_URL}/FIDC/DOC/INF_MENSAL/DADOS/inf_mensal_fidc_{{period}}.csv"
        ),
        
        # FIP - Quadrimestral reports since 2019
        "FIP_INF_QUADRIMESTRAL": EntityConfig(
            entity_type=EntityType.FIP,
            doc_type=DocumentType.INF_QUADRIMESTRAL,
            frequency=Frequency.QUADRIMESTRAL,
            start_date="201901",
            base_url_template=f"{CVM_BASE_URL}/FIP/DOC/INF_QUADRIMESTRAL/DADOS/inf_quadrimestral_fip_{{period}}.csv"
        ),
        
        # FIAGRO - Monthly reports since 2021
        "FIAGRO_INF_MENSAL": EntityConfig(
            entity_type=EntityType.FIAGRO,
            doc_type=DocumentType.INF_MENSAL,
            frequency=Frequency.MONTHLY,
            start_date="202101",
            base_url_template=f"{CVM_BASE_URL}/FIAGRO/DOC/INF_MENSAL/DADOS/inf_mensal_fiagro_{{period}}.csv"
        ),
        
        # SECURIT - CRA Monthly since 2019
        "SECURIT_CRA_MENSAL": EntityConfig(
            entity_type=EntityType.SECURIT,
            doc_type=DocumentType.CRA_MENSAL,
            frequency=Frequency.MONTHLY,
            start_date="201901",
            base_url_template=f"{CVM_BASE_URL}/SECURIT/DOC/CRA_MENSAL/DADOS/cra_mensal_{{period}}.csv"
        ),
        
        # SECURIT - CRI Monthly since 2019
        "SECURIT_CRI_MENSAL": EntityConfig(
            entity_type=EntityType.SECURIT,
            doc_type=DocumentType.CRI_MENSAL,
            frequency=Frequency.MONTHLY,
            start_date="201901",
            base_url_template=f"{CVM_BASE_URL}/SECURIT/DOC/CRI_MENSAL/DADOS/cri_mensal_{{period}}.csv"
        ),
        
        # SECURIT - LCA Monthly since 2019
        "SECURIT_LCA_MENSAL": EntityConfig(
            entity_type=EntityType.SECURIT,
            doc_type=DocumentType.LCA_MENSAL,
            frequency=Frequency.MONTHLY,
            start_date="201901",
            base_url_template=f"{CVM_BASE_URL}/SECURIT/DOC/LCA_MENSAL/DADOS/lca_mensal_{{period}}.csv"
        ),
        
        # SECURIT - LCI Monthly since 2019
        "SECURIT_LCI_MENSAL": EntityConfig(
            entity_type=EntityType.SECURIT,
            doc_type=DocumentType.LCI_MENSAL,
            frequency=Frequency.MONTHLY,
            start_date="201901",
            base_url_template=f"{CVM_BASE_URL}/SECURIT/DOC/LCI_MENSAL/DADOS/lci_mensal_{{period}}.csv"
        ),
    }
    
    @classmethod
    def get_config(cls, entity: str, doc_type: str) -> Optional[EntityConfig]:
        """Get configuration for specific entity and document type."""
        key = f"{entity}_{doc_type}"
        return cls.ENTITY_CONFIGS.get(key)
    
    @classmethod
    def get_all_configs(cls) -> List[EntityConfig]:
        """Get all entity configurations."""
        return list(cls.ENTITY_CONFIGS.values())
    
    @classmethod
    def get_configs_by_entity(cls, entity: str) -> List[EntityConfig]:
        """Get all configurations for a specific entity."""
        return [
            config for config in cls.ENTITY_CONFIGS.values()
            if config.entity_type.value == entity
        ]
    
    @classmethod
    def initialize_directories(cls):
        """Create necessary directories."""
        cls.BASE_DIR.mkdir(parents=True, exist_ok=True)
        cls.METADATA_DIR.mkdir(parents=True, exist_ok=True)
        cls.LOG_DIR.mkdir(parents=True, exist_ok=True)
        
        # Create entity directories
        for config in cls.ENTITY_CONFIGS.values():
            entity_dir = cls.BASE_DIR / config.entity_type.value / config.doc_type.value
            entity_dir.mkdir(parents=True, exist_ok=True)

def generate_periods(start_date: str, end_date: str, frequency: Frequency) -> List[str]:
    """Generate list of periods between start and end dates.
    
    Args:
        start_date: Start date in YYYYMM format
        end_date: End date in YYYYMM format
        frequency: Data frequency (monthly or quadrimestral)
    
    Returns:
        List of period strings in YYYYMM format
    """
    start_year = int(start_date[:4])
    start_month = int(start_date[4:6])
    end_year = int(end_date[:4])
    end_month = int(end_date[4:6])
    
    periods = []
    
    if frequency == Frequency.MONTHLY:
        # Generate all months
        year, month = start_year, start_month
        while year < end_year or (year == end_year and month <= end_month):
            periods.append(f"{year}{month:02d}")
            month += 1
            if month > 12:
                month = 1
                year += 1
    
    elif frequency == Frequency.QUADRIMESTRAL:
        # Generate quadrimestral periods (every 4 months: 01, 05, 09)
        year = start_year
        months = [1, 5, 9]
        
        while year <= end_year:
            for month in months:
                if (year > end_year or 
                    (year == end_year and month > end_month)):
                    break
                if (year > start_year or 
                    (year == start_year and month >= start_month)):
                    periods.append(f"{year}{month:02d}")
            year += 1
    
    return periods

def get_current_period(frequency: Frequency) -> str:
    """Get current period based on frequency.
    
    Returns:
        Current period in YYYYMM format
    """
    now = datetime.now()
    year = now.year
    month = now.month
    
    if frequency == Frequency.QUADRIMESTRAL:
        # Find the most recent quadrimestral period
        if month >= 9:
            month = 9
        elif month >= 5:
            month = 5
        else:
            month = 1
    
    return f"{year}{month:02d}"