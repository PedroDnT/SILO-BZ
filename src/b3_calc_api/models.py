from pydantic import BaseModel, Field
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

class SecurityInfo(BaseModel):
    """Security information model"""
    code: str = Field(..., description="Security code/identifier")
    name: Optional[str] = Field(None, description="Security name")
    issuer: Optional[str] = Field(None, description="Issuer name")
    isin: Optional[str] = Field(None, description="ISIN code")
    security_type: str = Field(..., description="Security type (debentures, cra, cri)")
    index: Optional[str] = Field(None, description="Reference index (CDI, IPCA, etc.)")
    rate: Optional[float] = Field(None, description="Interest rate or spread")
    maturity_date: Optional[str] = Field(None, description="Maturity date")
    issue_date: Optional[str] = Field(None, description="Issue date")
    status: Optional[str] = Field(None, description="Security status")

class PriceCalculationResult(BaseModel):
    """Price calculation result for a security"""
    pu: Optional[float] = Field(None, description="Unit price (PU)")
    pu_par: Optional[float] = Field(None, description="PU as percentage of par")
    yield_rate: Optional[float] = Field(None, description="Yield to maturity")
    duration: Optional[float] = Field(None, description="Duration in days")
    modified_duration: Optional[float] = Field(None, description="Modified duration")
    dv01: Optional[float] = Field(None, description="Dollar value of 01 basis point")
    accrued_interest: Optional[float] = Field(None, description="Accrued interest")
    settlement_date: Optional[str] = Field(None, description="Settlement date used")
    reference_rate: Optional[float] = Field(None, description="Reference rate used (CDI, IPCA, etc.)")
    extra: Optional[Dict[str, Any]] = Field(None, description="Additional calculation fields")

class SecurityPriceResponse(BaseModel):
    """Response model for security price calculation"""
    code: str = Field(..., description="Security code")
    security_type: str = Field(..., description="Security type")
    security_info: Optional[SecurityInfo] = Field(None, description="Security information")
    price: Optional[PriceCalculationResult] = Field(None, description="Price calculation result")
    raw_response: Optional[Dict[str, Any]] = Field(None, description="Raw API response for debugging")
    cached: bool = Field(False, description="Whether the response was served from cache")
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat(), description="Response timestamp")

class SecurityListResponse(BaseModel):
    """Response model for listing securities"""
    security_type: str = Field(..., description="Security type")
    page: int = Field(..., description="Current page")
    page_size: int = Field(..., description="Page size")
    total: int = Field(..., description="Total number of securities")
    securities: List[SecurityInfo] = Field(..., description="List of securities")
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat(), description="Response timestamp")

class IndexData(BaseModel):
    """Index data model"""
    name: str = Field(..., description="Index name")
    value: float = Field(..., description="Index value")
    change: Optional[float] = Field(None, description="Change from previous period")
    change_percent: Optional[float] = Field(None, description="Percentage change")
    last_update: str = Field(..., description="Last update timestamp")

class MarketDataResponse(BaseModel):
    """Market data response model"""
    reference_date: str = Field(..., description="Reference date for the data")
    indexes: Dict[str, Any] = Field(..., description="Financial indexes data")
    market_status: str = Field(..., description="Market status (open, closed, etc.)")
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat(), description="Response timestamp")

class IndexesResponse(BaseModel):
    """Indexes response model"""
    reference_date: str = Field(..., description="Reference date")
    indexes: Dict[str, Any] = Field(..., description="Financial indexes")
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat(), description="Response timestamp")

class AvailableEndpointsResponse(BaseModel):
    """Available endpoints response model"""
    endpoints: List[Dict[str, Any]] = Field(..., description="List of available endpoints")
    version: str = Field(..., description="API version")
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat(), description="Response timestamp")
