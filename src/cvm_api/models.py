from pydantic import BaseModel, ConfigDict, Field
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone

class HealthResponse(BaseModel):
    """Health check response model"""
    status: str = Field(..., description="Service health status")
    timestamp: str = Field(..., description="Current timestamp")
    version: str = Field(..., description="API version")

class ErrorResponse(BaseModel):
    """Error response model"""
    error: str = Field(..., description="Error message")
    status_code: int = Field(..., description="HTTP status code")
    timestamp: str = Field(..., description="Error timestamp")

class PaginationInfo(BaseModel):
    """Pagination information model"""
    page: int = Field(..., description="Current page number", ge=1)
    page_size: int = Field(..., description="Number of items per page", ge=1)
    total_items: int = Field(..., description="Total number of items", ge=0)
    total_pages: int = Field(..., description="Total number of pages", ge=0)
    has_next: bool = Field(..., description="Whether there is a next page")
    has_previous: bool = Field(..., description="Whether there is a previous page")

class DataResponse(BaseModel):
    """Generic data response model"""
    entity: str = Field(..., description="Entity type (fidc, fip, fiagro, securit)")
    doc_type: str = Field(..., description="Document type")
    data: List[Dict[str, Any]] = Field(..., description="Data records")
    pagination: PaginationInfo = Field(..., description="Pagination information")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat(), description="Response timestamp")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "entity": "fidc",
                "doc_type": "cadastral",
                "data": [
                    {
                        "CNPJ_FUNDO": "12.345.678/0001-90",
                        "DENOM_SOCIAL": "FUNDO DE INVESTIMENTO EXEMPLO",
                        "DT_REG": "2020-01-15"
                    }
                ],
                "pagination": {
                    "page": 1,
                    "page_size": 100,
                    "total_items": 250,
                    "total_pages": 3,
                    "has_next": True,
                    "has_previous": False
                },
                "metadata": {
                    "year": 2023,
                    "month": 12,
                    "source_url": "https://dados.cvm.gov.br/dados/FIDC/CAD/DADOS/cad_fidc.csv"
                },
                "timestamp": "2024-01-15T10:30:00.000Z"
            }
        }
    )

class EntityInfo(BaseModel):
    """Entity information model"""
    entity: str = Field(..., description="Entity identifier")
    name: str = Field(..., description="Full entity name")
    doc_types: List[str] = Field(..., description="Available document types")
    description: str = Field(..., description="Entity description")

class AvailableEndpointsResponse(BaseModel):
    """Available endpoints response model"""
    entities: List[EntityInfo] = Field(..., description="List of available entities")
    base_url: str = Field(..., description="Base URL pattern for endpoints")
    version: str = Field(..., description="API version")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "entities": [
                    {
                        "entity": "fidc",
                        "name": "FIDC - Fundos de Investimento em Direitos Creditórios",
                        "doc_types": ["cadastral", "mensal", "trimestral", "anual", "quadrimestral", "dfin"],
                        "description": "Investment funds in credit rights"
                    }
                ],
                "base_url": "/api/v1/{entity}/{doc_type}",
                "version": "1.0.0"
            }
        }
    )

class FIDCCadastralData(BaseModel):
    """FIDC Cadastral data model"""
    model_config = ConfigDict(extra="allow")

    cnpj_fundo: Optional[str] = Field(None, description="Fund CNPJ")
    denom_social: Optional[str] = Field(None, description="Social denomination")
    dt_reg: Optional[str] = Field(None, description="Registration date")
    dt_cancel: Optional[str] = Field(None, description="Cancellation date")
    sit: Optional[str] = Field(None, description="Current status")
    tp_fundo: Optional[str] = Field(None, description="Fund type")

class FIPCadastralData(BaseModel):
    """FIP Cadastral data model"""
    model_config = ConfigDict(extra="allow")

    cnpj_fundo: Optional[str] = Field(None, description="Fund CNPJ")
    denom_social: Optional[str] = Field(None, description="Social denomination")
    dt_reg: Optional[str] = Field(None, description="Registration date")
    dt_cancel: Optional[str] = Field(None, description="Cancellation date")
    sit: Optional[str] = Field(None, description="Current status")
    tp_fundo: Optional[str] = Field(None, description="Fund type")

class FIAGROCadastralData(BaseModel):
    """FIAGRO Cadastral data model"""
    model_config = ConfigDict(extra="allow")

    cnpj_fundo: Optional[str] = Field(None, description="Fund CNPJ")
    denom_social: Optional[str] = Field(None, description="Social denomination")
    dt_reg: Optional[str] = Field(None, description="Registration date")
    dt_cancel: Optional[str] = Field(None, description="Cancellation date")
    sit: Optional[str] = Field(None, description="Current status")
    tp_fundo: Optional[str] = Field(None, description="Fund type")

class SECURITCadastralData(BaseModel):
    """SECURIT Cadastral data model"""
    model_config = ConfigDict(extra="allow")

    cnpj_securit: Optional[str] = Field(None, description="Securitization company CNPJ")
    denom_social: Optional[str] = Field(None, description="Social denomination")
    dt_reg: Optional[str] = Field(None, description="Registration date")
    dt_cancel: Optional[str] = Field(None, description="Cancellation date")
    sit: Optional[str] = Field(None, description="Current status")

class PeriodicReportData(BaseModel):
    """Generic periodic report data model"""
    model_config = ConfigDict(extra="allow")

    cnpj_fundo: Optional[str] = Field(None, description="Fund CNPJ")
    dt_comptc: Optional[str] = Field(None, description="Competence date")
    vl_total: Optional[str] = Field(None, description="Total value")
    vl_quota: Optional[str] = Field(None, description="Quota value")
    vl_patrim_liq: Optional[str] = Field(None, description="Net equity value")

class EmissionData(BaseModel):
    """Emission data model for SECURIT"""
    model_config = ConfigDict(extra="allow")

    cnpj_securit: Optional[str] = Field(None, description="Securitization company CNPJ")
    tp_ativo: Optional[str] = Field(None, description="Asset type")
    dt_emissao: Optional[str] = Field(None, description="Emission date")
    vl_emissao: Optional[str] = Field(None, description="Emission value")
    qt_titulos: Optional[str] = Field(None, description="Number of titles")


class CNPJRegistryEntry(BaseModel):
    """A single fund registration record for a CNPJ across entity types"""
    entity: str = Field(..., description="Entity type (fidc, fip, fiagro)")
    fund_name: Optional[str] = Field(None, description="Fund social denomination (DENOM_SOCIAL)")
    status: Optional[str] = Field(None, description="Fund status (SIT field)")
    registration_date: Optional[str] = Field(None, description="Registration date (DT_REG)")
    cancellation_date: Optional[str] = Field(None, description="Cancellation date (DT_CANCEL)")
    fund_type: Optional[str] = Field(None, description="Fund type (TP_FUNDO or CLASSE)")
    raw: Dict[str, Any] = Field(default_factory=dict, description="All raw fields from source CSV")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "entity": "fidc",
                "fund_name": "FUNDO DE INVESTIMENTO EXEMPLO FIC FIDC",
                "status": "EM FUNCIONAMENTO NORMAL",
                "registration_date": "2018-03-12",
                "cancellation_date": None,
                "fund_type": "Aberto",
                "raw": {"CNPJ_FUNDO": "12.345.678/0001-90", "DENOM_SOCIAL": "FUNDO DE INVESTIMENTO EXEMPLO FIC FIDC"}
            }
        }
    )


class PeriodicSnapshot(BaseModel):
    """One row of periodic (mensal/quarterly) data for a fund — full raw CSV row preserved"""
    source_entity: str = Field(..., description="Entity type (fidc, fiagro)")
    doc_type: str = Field(..., description="Document type (mensal, trimestral, anual)")
    period: str = Field(..., description="Competence period as reported (DT_COMPTC or similar)")
    quota_value: Optional[str] = Field(None, description="Quota/unit price (VL_QUOTA) — current price signal")
    net_asset_value: Optional[str] = Field(None, description="Net asset value (VL_PATRIM_LIQ)")
    total_portfolio: Optional[str] = Field(None, description="Total portfolio value (VL_TOTAL or VL_CARTEIRA_TOTAL)")
    delinquency_value: Optional[str] = Field(None, description="Delinquency / inadimplência value (VL_INADIMPL or similar)")
    num_quotaholders: Optional[str] = Field(None, description="Number of quota holders (NR_COTST)")
    raw: Dict[str, Any] = Field(default_factory=dict, description="All raw fields from the source CSV row")


class EmissionRecord(BaseModel):
    """One emission record from SECURIT datasets (CRA, CRI, LCA, LCI) — full raw CSV row preserved"""
    instrument_type: str = Field(..., description="Instrument type (cra_mensal, cri_mensal, lca_mensal, lci_mensal)")
    emission_date: Optional[str] = Field(None, description="Emission date (DT_EMISSAO)")
    maturity_date: Optional[str] = Field(None, description="Maturity / vencimento date (DT_VENCTO)")
    emission_value: Optional[str] = Field(None, description="Total emission value (VL_EMISSAO)")
    unit_price: Optional[str] = Field(None, description="Unit price at emission (VL_UNIT or PU_EMISSAO)")
    num_titles: Optional[str] = Field(None, description="Number of titles issued (QT_TITULOS)")
    outstanding_value: Optional[str] = Field(None, description="Current outstanding value (VL_TOTAL)")
    asset_type: Optional[str] = Field(None, description="Underlying asset type (TP_ATIVO)")
    raw: Dict[str, Any] = Field(default_factory=dict, description="All raw fields from the source CSV row")


class CNPJRegistryResponse(BaseModel):
    """Cross-entity registry lookup result for a CNPJ — used for fraud detection"""
    cnpj: str = Field(..., description="Requested CNPJ (normalized, digits only)")
    year: int = Field(..., description="Year queried")
    month: Optional[int] = Field(None, description="Month queried for periodic data (None = cadastral only)")
    registrations: List[CNPJRegistryEntry] = Field(..., description="Fund registrations (cadastral) across FIDC, FIP, FIAGRO")
    periodic_snapshots: List[PeriodicSnapshot] = Field(default_factory=list, description="Periodic financial data rows (current price, NAV, defaults) — populated when month is provided")
    emissions: List[EmissionRecord] = Field(default_factory=list, description="SECURIT emission records where this CNPJ is the issuer (CRA/CRI/LCA/LCI)")
    found_in: List[str] = Field(..., description="Entity types where CNPJ was found")
    not_found_in: List[str] = Field(..., description="Entity types where CNPJ was not found")
    source_urls: Dict[str, str] = Field(default_factory=dict, description="Source URLs keyed by entity/doc_type")
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat(), description="Response timestamp")