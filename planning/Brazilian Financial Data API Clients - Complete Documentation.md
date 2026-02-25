# Brazilian Financial Data API Clients

Complete Python client libraries for ANBIMA Feed API, BACEN Time Series API, and CVM Data Integration.

## Overview

This package provides production-ready Python clients for accessing Brazilian financial data:  
\- **ANBIMA Feed API**: CRI/CRA, Debêntures, FIDC pricing (OAuth2 authenticated)  
\- B**ACEN API:** Time series data for interest rates, inflation, credit operations  
\- D**ata Integration Layer:** Unified FIDC analysis combining CVM \+ ANBIMA \+ BACEN data

\---

## ANBIMA Feed API Client

## 

### Files

### \- \`anbima\_client.py\` \- OAuth2 client with automatic token refresh

\- \`anbima\_models.py\` \- Pydantic models for all API responses

### Features

### \- OAuth2 client credentials flow

\- Automatic token refresh  
\- Rate limiting and retry logic  
\- Pagination support  
\- Response validation

### Supported APIs

### | API | Method | Description |

|-----|--------|-------------|  
| CRI/CRA | \`get\_cri\_cra\_mercado\_secundario()\` | Secondary market prices |  
| CRI/CRA | \`get\_cri\_cra\_projecoes()\` | Price projections |  
| Debêntures | \`get\_debentures\_mercado\_secundario()\` | Corporate bond prices |  
| Debêntures | \`get\_debentures\_curvas()\` | Credit curves |  
| Debêntures | \`get\_debentures\_projecoes()\` | Bond projections |  
| FIDC | \`get\_fidc\_mercado\_secundario()\` | FIDC pricing |  
| Funds | \`get\_fundos\_estruturados()\` | Structured funds list |  
| Funds | \`get\_fundo\_serie\_historica(cnpj)\` | Historical fund data |

### Usage Example

### \`\`\`python

from anbima\_client import AnbimaClient

client \= AnbimaClient(  
    client\_id="your\_client\_id",  
    client\_secret="your\_client\_secret"  
)

# Fetch CRI/CRA data

# cri\_cra\_data \= client.get\_cri\_cra\_mercado\_secundario(

    data\_referencia="2024-01-15"  
)

# Fetch Debêntures

# debentures \= client.get\_debentures\_mercado\_secundario()

# Fetch FIDC pricing

# fidc\_data \= client.get\_fidc\_mercado\_secundario()

\`\`\`

\---

## BACEN Time Series API Client

## 

### Files

### \- \`bacen\_client.py\` \- Time series fetcher with rate limiting

\- \`bacen\_models.py\` \- Pydantic models for series data

### Features

### \- No authentication required (public API)

\- Rate limiting (respects BACEN limits)  
\- Automatic date formatting  
\- JSON and CSV format support  
\- Retry logic with exponential backoff

### Common Series IDs

### | Series | ID | Description |

|--------|-----|-------------|  
| SELIC | 432 | Daily SELIC rate |  
| CDI | 4391 | Daily CDI rate |  
| IPCA | 433 | Monthly inflation |  
| IBC-Br | 24363 | Economic activity index |  
| Credit Operations | 20582 | Total credit operations |  
| USD Exchange | 1 | USD/BRL rate |  
| EUR Exchange | 21654 | EUR/BRL rate |

### Usage Example

### \`\`\`python

from bacen\_client import BacenClient  
from datetime import date

client \= BacenClient()

# Fetch SELIC rates

# selic \= client.get\_series(

    series\_id=432,  
    start\_date=date(2024, 1, 1),  
    end\_date=date(2024, 12, 31\)  
)

# Fetch credit operations by sector

# credit \= client.get\_credit\_operations\_by\_sector()

# Get economic activity index

# ibcbr \= client.get\_economic\_activity\_index()

\`\`\`

\---

## Data Integration Layer

## 

### Files

### \- \`integration\_layer.py\` \- Data merging and analysis

\- \`integration\_models.py\` \- Unified data models

### Features

### \- Combines CVM cadastral \+ monthly data

\- Merges ANBIMA pricing data  
\- Adds BACEN macro context  
\- Calculates performance metrics  
\- Sector analysis and peer comparison  
\- Export to Parquet format

### Usage Example

### \`\`\`python

from integration\_layer import DataIntegrator, FIDCAnalyzer

# Initialize integrator

# integrator \= DataIntegrator(data\_path="./data")

# Get integrated FIDC data

# fidc\_data \= integrator.integrate\_fidc\_data(

    cnpj="12.345.678/0001-90",  
    date\_range=("2024-01-01", "2024-12-31")  
)

# Calculate performance metrics

# analyzer \= FIDCAnalyzer(fidc\_data)

metrics \= analyzer.calculate\_performance\_metrics()

# Compare to benchmark

# comparison \= integrator.compare\_fidc\_to\_benchmark(

    cnpj="12.345.678/0001-90",  
    benchmark\_type="cdi"  
)  
\`\`\`

\---

## Installation

## 

## \`\`\`bash

pip install \-r requirements.txt  
\`\`\`

### Environment Variables

### 

### Create \`.env\` file:

\`\`\`  
ANBIMA\_CLIENT\_ID=your\_client\_id  
ANBIMA\_CLIENT\_SECRET=your\_client\_secret  
ANBIMA\_BASE\_URL=https://api.anbima.com.br  
\`\`\`

\---

## Source Code

## 

### anbima\_models.py

### \`\`\`python

from typing import Optional, List, Any, Generic, TypeVar  
from datetime import date, datetime  
from decimal import Decimal  
from pydantic import BaseModel, Field, ConfigDict, field\_validator  
from enum import Enum

class TipoAtivo(str, Enum):  
    """Enumeration for asset types."""  
    CRI \= "CRI"  
    CRA \= "CRA"  
    DEBENTURE \= "DEBENTURE"  
    FIDC \= "FIDC"  
    FII \= "FII"  
    FIP \= "FIP"

class Indexador(str, Enum):  
    """Enumeration for index types."""  
    DI \= "DI"  
    IPCA \= "IPCA"  
    IGPM \= "IGPM"  
    PREFIXADO \= "PREFIXADO"  
    TR \= "TR"  
    SELIC \= "SELIC"  
    CDI \= "CDI"

class TipoDebenture(str, Enum):  
    """Enumeration for debenture types."""  
    COMUM \= "comum"  
    INCENTIVADA \= "incentivada"  
    CONVERSIVEL \= "conversivel"

class ClasseFIDC(str, Enum):  
    """Enumeration for FIDC classes."""  
    SENIOR \= "senior"  
    MEZANINO \= "mezanino"  
    SUBORDINADA \= "subordinada"

class TokenResponse(BaseModel):  
    """OAuth2 token response model."""  
    model\_config \= ConfigDict(str\_strip\_whitespace=True)  
      
    access\_token: str \= Field(..., description="Access token for API authentication")  
    token\_type: str \= Field(..., description="Token type (usually 'Bearer')")  
    expires\_in: int \= Field(..., description="Token expiration time in seconds")  
    scope: Optional\[str\] \= Field(None, description="Token scope")

class ErrorResponse(BaseModel):  
    """API error response model."""  
    model\_config \= ConfigDict(str\_strip\_whitespace=True)  
      
    error: str \= Field(..., description="Error code")  
    error\_description: Optional\[str\] \= Field(None, description="Error description")  
    message: Optional\[str\] \= Field(None, description="Error message")  
    status\_code: Optional\[int\] \= Field(None, description="HTTP status code")

T \= TypeVar('T')

class PaginationInfo(BaseModel):  
    """Pagination information model."""  
    model\_config \= ConfigDict(str\_strip\_whitespace=True)  
      
    current\_page: int \= Field(..., description="Current page number")  
    total\_pages: int \= Field(..., description="Total number of pages")  
    total\_items: int \= Field(..., description="Total number of items")  
    items\_per\_page: int \= Field(..., description="Number of items per page")  
    has\_next: bool \= Field(..., description="Whether there is a next page")  
    has\_previous: bool \= Field(..., description="Whether there is a previous page")

class PaginatedResponse(BaseModel, Generic\[T\]):  
    """Generic paginated response model."""  
    model\_config \= ConfigDict(str\_strip\_whitespace=True)  
      
    data: List\[T\] \= Field(..., description="List of data items")  
    pagination: PaginationInfo \= Field(..., description="Pagination information")

class CriCraItem(BaseModel):  
    """CRI/CRA secondary market item model."""  
    model\_config \= ConfigDict(str\_strip\_whitespace=True, populate\_by\_name=True)  
      
    data\_referencia: date \= Field(..., description="Reference date")  
    codigo\_isin: str \= Field(..., description="ISIN code")  
    tipo\_ativo: TipoAtivo \= Field(..., description="Asset type (CRI or CRA)")  
    emissor: str \= Field(..., description="Issuer name")  
    emissao: date \= Field(..., description="Emission date")  
    vencimento: date \= Field(..., description="Maturity date")  
    indexador: Indexador \= Field(..., description="Index type")  
    taxa: Optional\[Decimal\] \= Field(None, description="Rate (percentage)")  
    spread: Optional\[Decimal\] \= Field(None, description="Spread over index")  
    preco\_unitario: Decimal \= Field(..., description="Unit price")  
    pu\_par: Decimal \= Field(..., description="Par unit price")  
    quantidade: Optional\[int\] \= Field(None, description="Quantity")  
    volume\_financeiro: Optional\[Decimal\] \= Field(None, description="Financial volume")  
    duration: Optional\[Decimal\] \= Field(None, description="Duration in years")  
    convexidade: Optional\[Decimal\] \= Field(None, description="Convexity")  
    rating: Optional\[str\] \= Field(None, description="Credit rating")  
    agencia\_rating: Optional\[str\] \= Field(None, description="Rating agency")  
    garantia: Optional\[str\] \= Field(None, description="Guarantee type")  
      
    @field\_validator('data\_referencia', 'emissao', 'vencimento', mode='before')  
    @classmethod  
    def parse\_date(cls, v):  
        if isinstance(v, str):  
            return datetime.strptime(v, '%Y-%m-%d').date()  
        return v

class CriCraProjecao(BaseModel):  
    """CRI/CRA projection model."""  
    model\_config \= ConfigDict(str\_strip\_whitespace=True, populate\_by\_name=True)  
      
    data\_referencia: date \= Field(..., description="Reference date")  
    codigo\_isin: str \= Field(..., description="ISIN code")  
    data\_projecao: date \= Field(..., description="Projection date")  
    valor\_projetado: Decimal \= Field(..., description="Projected value")  
    fluxo\_projetado: Decimal \= Field(..., description="Projected cash flow")  
    amortizacao: Optional\[Decimal\] \= Field(None, description="Amortization amount")  
    juros: Optional\[Decimal\] \= Field(None, description="Interest amount")  
    saldo\_devedor: Decimal \= Field(..., description="Outstanding balance")  
    indexador\_projetado: Optional\[Decimal\] \= Field(None, description="Projected index value")  
      
    @field\_validator('data\_referencia', 'data\_projecao', mode='before')  
    @classmethod  
    def parse\_date(cls, v):  
        if isinstance(v, str):  
            return datetime.strptime(v, '%Y-%m-%d').date()  
        return v

class DebentureItem(BaseModel):  
    """Debenture secondary market item model."""  
    model\_config \= ConfigDict(str\_strip\_whitespace=True, populate\_by\_name=True)  
      
    data\_referencia: date \= Field(..., description="Reference date")  
    codigo\_isin: str \= Field(..., description="ISIN code")  
    tipo: TipoDebenture \= Field(..., description="Debenture type")  
    emissor: str \= Field(..., description="Issuer name")  
    cnpj\_emissor: str \= Field(..., description="Issuer CNPJ")  
    emissao: date \= Field(..., description="Emission date")  
    vencimento: date \= Field(..., description="Maturity date")  
    indexador: Indexador \= Field(..., description="Index type")  
    taxa: Optional\[Decimal\] \= Field(None, description="Rate (percentage)")  
    spread: Optional\[Decimal\] \= Field(None, description="Spread over index")  
    preco\_unitario: Decimal \= Field(..., description="Unit price")  
    pu\_par: Decimal \= Field(..., description="Par unit price")  
    quantidade: Optional\[int\] \= Field(None, description="Quantity")  
    volume\_financeiro: Optional\[Decimal\] \= Field(None, description="Financial volume")  
    duration: Optional\[Decimal\] \= Field(None, description="Duration in years")  
    convexidade: Optional\[Decimal\] \= Field(None, description="Convexity")  
    rating: Optional\[str\] \= Field(None, description="Credit rating")  
    agencia\_rating: Optional\[str\] \= Field(None, description="Rating agency")  
    serie: Optional\[str\] \= Field(None, description="Series")  
    conversivel: bool \= Field(False, description="Whether convertible")  
    participacao\_lucros: bool \= Field(False, description="Profit participation")  
    garantia\_real: bool \= Field(False, description="Real guarantee")  
    repactuavel: bool \= Field(False, description="Renegotiable")  
      
    @field\_validator('data\_referencia', 'emissao', 'vencimento', mode='before')  
    @classmethod  
    def parse\_date(cls, v):  
        if isinstance(v, str):  
            return datetime.strptime(v, '%Y-%m-%d').date()  
        return v

class DebentureCurva(BaseModel):  
    """Debenture yield curve model."""  
    model\_config \= ConfigDict(str\_strip\_whitespace=True, populate\_by\_name=True)  
      
    data\_referencia: date \= Field(..., description="Reference date")  
    tipo\_curva: str \= Field(..., description="Curve type (yield or spread)")  
    indexador: Indexador \= Field(..., description="Index type")  
    prazo\_anos: Decimal \= Field(..., description="Term in years")  
    prazo\_dias: int \= Field(..., description="Term in days")  
    taxa: Decimal \= Field(..., description="Rate (percentage)")  
    rating\_minimo: Optional\[str\] \= Field(None, description="Minimum rating")  
    numero\_titulos: Optional\[int\] \= Field(None, description="Number of securities")  
    volume\_medio: Optional\[Decimal\] \= Field(None, description="Average volume")  
      
    @field\_validator('data\_referencia', mode='before')  
    @classmethod  
    def parse\_date(cls, v):  
        if isinstance(v, str):  
            return datetime.strptime(v, '%Y-%m-%d').date()  
        return v

class DebentureProjecao(BaseModel):  
    """Debenture projection model."""  
    model\_config \= ConfigDict(str\_strip\_whitespace=True, populate\_by\_name=True)  
      
    data\_referencia: date \= Field(..., description="Reference date")  
    codigo\_isin: str \= Field(..., description="ISIN code")  
    data\_projecao: date \= Field(..., description="Projection date")  
    valor\_projetado: Decimal \= Field(..., description="Projected value")  
    fluxo\_projetado: Decimal \= Field(..., description="Projected cash flow")  
    amortizacao: Optional\[Decimal\] \= Field(None, description="Amortization amount")  
    juros: Optional\[Decimal\] \= Field(None, description="Interest amount")  
    juros\_mora: Optional\[Decimal\] \= Field(None, description="Default interest")  
    saldo\_devedor: Decimal \= Field(..., description="Outstanding balance")  
    indexador\_projetado: Optional\[Decimal\] \= Field(None, description="Projected index value")  
    participacao\_lucros\_projetada: Optional\[Decimal\] \= Field(None, description="Projected profit participation")  
      
    @field\_validator('data\_referencia', 'data\_projecao', mode='before')  
    @classmethod  
    def parse\_date(cls, v):  
        if isinstance(v, str):  
            return datetime.strptime(v, '%Y-%m-%d').date()  
        return v

class FidcItem(BaseModel):  
    """FIDC secondary market item model."""  
    model\_config \= ConfigDict(str\_strip\_whitespace=True, populate\_by\_name=True)  
      
    data\_referencia: date \= Field(..., description="Reference date")  
    cnpj: str \= Field(..., description="Fund CNPJ")  
    nome\_fundo: str \= Field(..., description="Fund name")  
    classe: ClasseFIDC \= Field(..., description="FIDC class")  
    codigo\_isin: Optional\[str\] \= Field(None, description="ISIN code")  
    serie: Optional\[str\] \= Field(None, description="Series")  
    emissao: date \= Field(..., description="Emission date")  
    vencimento: Optional\[date\] \= Field(None, description="Maturity date")  
    indexador: Indexador \= Field(..., description="Index type")  
    taxa: Optional\[Decimal\] \= Field(None, description="Rate (percentage)")  
    spread: Optional\[Decimal\] \= Field(None, description="Spread over index")  
    preco\_unitario: Decimal \= Field(..., description="Unit price")  
    quantidade\_cotas: Optional\[int\] \= Field(None, description="Number of quotas")  
    patrimonio\_liquido: Optional\[Decimal\] \= Field(None, description="Net equity")  
    valor\_cota: Decimal \= Field(..., description="Quota value")  
    rating: Optional\[str\] \= Field(None, description="Credit rating")  
    agencia\_rating: Optional\[str\] \= Field(None, description="Rating agency")  
    lastro: Optional\[str\] \= Field(None, description="Underlying assets type")  
    administrador: Optional\[str\] \= Field(None, description="Administrator")  
    gestor: Optional\[str\] \= Field(None, description="Manager")  
      
    @field\_validator('data\_referencia', 'emissao', 'vencimento', mode='before')  
    @classmethod  
    def parse\_date(cls, v):  
        if isinstance(v, str):  
            return datetime.strptime(v, '%Y-%m-%d').date()  
        return v

class FundoEstruturado(BaseModel):  
    """Structured fund model."""  
    model\_config \= ConfigDict(str\_strip\_whitespace=True, populate\_by\_name=True)  
      
    data\_referencia: date \= Field(..., description="Reference date")  
    cnpj: str \= Field(..., description="Fund CNPJ")  
    nome\_fundo: str \= Field(..., description="Fund name")  
    tipo: str \= Field(..., description="Fund type (FIDC, FII, FIP, etc.)")  
    data\_constituicao: date \= Field(..., description="Constitution date")  
    data\_registro\_cvm: Optional\[date\] \= Field(None, description="CVM registration date")  
    situacao: str \= Field(..., description="Current status")  
    publico\_alvo: Optional\[str\] \= Field(None, description="Target audience")  
    patrimonio\_liquido: Decimal \= Field(..., description="Net equity")  
    valor\_cota: Decimal \= Field(..., description="Quota value")  
    cotas\_emitidas: int \= Field(..., description="Issued quotas")  
    cotistas: Optional\[int\] \= Field(None, description="Number of quota holders")  
    rentabilidade\_mes: Optional\[Decimal\] \= Field(None, description="Monthly return")  
    rentabilidade\_ano: Optional\[Decimal\] \= Field(None, description="Year-to-date return")  
    rentabilidade\_12m: Optional\[Decimal\] \= Field(None, description="12-month return")  
    administrador: str \= Field(..., description="Administrator")  
    cnpj\_administrador: str \= Field(..., description="Administrator CNPJ")  
    gestor: Optional\[str\] \= Field(None, description="Manager")  
    cnpj\_gestor: Optional\[str\] \= Field(None, description="Manager CNPJ")  
    custodiante: Optional\[str\] \= Field(None, description="Custodian")  
    auditor: Optional\[str\] \= Field(None, description="Auditor")  
    taxa\_administracao: Optional\[Decimal\] \= Field(None, description="Administration fee (%)")  
    taxa\_performance: Optional\[Decimal\] \= Field(None, description="Performance fee (%)")  
    taxa\_ingresso: Optional\[Decimal\] \= Field(None, description="Entry fee (%)")  
    taxa\_saida: Optional\[Decimal\] \= Field(None, description="Exit fee (%)")  
      
    @field\_validator('data\_referencia', 'data\_constituicao', 'data\_registro\_cvm', mode='before')  
    @classmethod  
    def parse\_date(cls, v):  
        if v is None:  
            return v  
        if isinstance(v, str):  
            return datetime.strptime(v, '%Y-%m-%d').date()  
        return v

class SerieHistorica(BaseModel):  
    """Historical series data for a fund."""  
    model\_config \= ConfigDict(str\_strip\_whitespace=True, populate\_by\_name=True)  
      
    data: date \= Field(..., description="Date")  
    cnpj: str \= Field(..., description="Fund CNPJ")  
    valor\_cota: Decimal \= Field(..., description="Quota value")  
    patrimonio\_liquido: Decimal \= Field(..., description="Net equity")  
    captacao\_dia: Optional\[Decimal\] \= Field(None, description="Daily inflow")  
    resgate\_dia: Optional\[Decimal\] \= Field(None, description="Daily outflow")  
    cotas\_emitidas: int \= Field(..., description="Issued quotas")  
    cotistas: Optional\[int\] \= Field(None, description="Number of quota holders")  
    rentabilidade\_dia: Optional\[Decimal\] \= Field(None, description="Daily return")  
    rentabilidade\_acumulada: Optional\[Decimal\] \= Field(None, description="Accumulated return")  
    valor\_total\_carteira: Optional\[Decimal\] \= Field(None, description="Total portfolio value")  
    disponibilidades: Optional\[Decimal\] \= Field(None, description="Cash availability")  
    outros\_ativos: Optional\[Decimal\] \= Field(None, description="Other assets")  
    passivo\_total: Optional\[Decimal\] \= Field(None, description="Total liabilities")  
      
    @field\_validator('data', mode='before')  
    @classmethod  
    def parse\_date(cls, v):  
        if isinstance(v, str):  
            return datetime.strptime(v, '%Y-%m-%d').date()  
        return v

class IndicadorEconomico(BaseModel):  
    """Economic indicator model."""  
    model\_config \= ConfigDict(str\_strip\_whitespace=True, populate\_by\_name=True)  
      
    data: date \= Field(..., description="Date")  
    indicador: str \= Field(..., description="Indicator name")  
    valor: Decimal \= Field(..., description="Value")  
    variacao\_dia: Optional\[Decimal\] \= Field(None, description="Daily variation")  
    variacao\_mes: Optional\[Decimal\] \= Field(None, description="Monthly variation")  
    variacao\_ano: Optional\[Decimal\] \= Field(None, description="Year-to-date variation")  
      
    @field\_validator('data', mode='before')  
    @classmethod  
    def parse\_date(cls, v):  
        if isinstance(v, str):  
            return datetime.strptime(v, '%Y-%m-%d').date()  
        return v  
\`\`\`

### anbima\_client.py

### \`\`\`python

import time  
import logging  
from typing import Optional, List, Dict, Any  
from datetime import datetime, timedelta  
import requests  
from requests.adapters import HTTPAdapter  
from urllib3.util.retry import Retry  
from pydantic import ValidationError

from .anbima\_models import (  
    CriCraItem,  
    DebentureItem,  
    FidcItem,  
    FundoEstruturado,  
    SerieHistorica,  
    DebentureCurva,  
    DebentureProjecao,  
    CriCraProjecao,  
    TokenResponse,  
    ErrorResponse,  
    PaginatedResponse  
)

logger \= logging.getLogger(\_\_name\_\_)

class AnbimaAPIError(Exception):  
    """Base exception for ANBIMA API errors."""  
    pass

class AnbimaAuthenticationError(AnbimaAPIError):  
    """Exception raised for authentication failures."""  
    pass

class AnbimaRateLimitError(AnbimaAPIError):  
    """Exception raised when rate limit is exceeded."""  
    pass

class AnbimaValidationError(AnbimaAPIError):  
    """Exception raised when response validation fails."""  
    pass

class AnbimaClient:  
    """Client for interacting with the ANBIMA Feed API.  
      
    This client provides methods to access ANBIMA's credit market data including  
    CRI/CRA, Debêntures, FIDC, and Structured Funds. It handles OAuth2 authentication,  
    automatic token refresh, rate limiting, retries, and response validation.  
      
    Args:  
        client\_id: OAuth2 client ID  
        client\_secret: OAuth2 client secret  
        base\_url: Base URL for the ANBIMA API (default: https://api.anbima.com.br)  
        token\_url: OAuth2 token endpoint (default: https://api.anbima.com.br/oauth/token)  
        max\_retries: Maximum number of retry attempts (default: 3\)  
        timeout: Request timeout in seconds (default: 30\)  
        rate\_limit\_calls: Maximum calls per rate\_limit\_period (default: 100\)  
        rate\_limit\_period: Rate limit period in seconds (default: 60\)  
      
    Example:  
        \>\>\> client \= AnbimaClient(client\_id="your\_id", client\_secret="your\_secret")  
        \>\>\> cri\_cra\_data \= client.get\_cri\_cra\_mercado\_secundario(data\_referencia="2024-01-15")  
        \>\>\> for item in cri\_cra\_data:  
        ...     print(f"{item.codigo\_isin}: {item.preco\_unitario}")  
    """  
      
    def \_\_init\_\_(  
        self,  
        client\_id: str,  
        client\_secret: str,  
        base\_url: str \= "https://api.anbima.com.br",  
        token\_url: str \= "https://api.anbima.com.br/oauth/token",  
        max\_retries: int \= 3,  
        timeout: int \= 30,  
        rate\_limit\_calls: int \= 100,  
        rate\_limit\_period: int \= 60  
    ):  
        self.client\_id \= client\_id  
        self.client\_secret \= client\_secret  
        self.base\_url \= base\_url.rstrip("/")  
        self.token\_url \= token\_url  
        self.timeout \= timeout  
        

# Token management

#         self.\_access\_token: Optional\[str\] \= None

        self.\_token\_expires\_at: Optional\[datetime\] \= None  
        

# Rate limiting

#         self.rate\_limit\_calls \= rate\_limit\_calls

        self.rate\_limit\_period \= rate\_limit\_period  
        self.\_call\_timestamps: List\[float\] \= \[\]  
        

# Configure session with retry logic

#         self.session \= self.\_create\_session(max\_retries)

          
        logger.info(f"AnbimaClient initialized for base\_url: {self.base\_url}")  
      
    def \_create\_session(self, max\_retries: int) \-\> requests.Session:  
        """Create a requests session with retry logic.  
          
        Args:  
            max\_retries: Maximum number of retry attempts  
              
        Returns:  
            Configured requests.Session object  
        """  
        session \= requests.Session()  
          
        retry\_strategy \= Retry(  
            total=max\_retries,  
            backoff\_factor=1,  
            status\_forcelist=\[429, 500, 502, 503, 504\],  
            allowed\_methods=\["HEAD", "GET", "OPTIONS", "POST"\]  
        )  
          
        adapter \= HTTPAdapter(max\_retries=retry\_strategy)  
        session.mount("http://", adapter)  
        session.mount("https://", adapter)  
          
        return session  
      
    def \_check\_rate\_limit(self) \-\> None:  
        """Check and enforce rate limiting.  
          
        Raises:  
            AnbimaRateLimitError: If rate limit is exceeded  
        """  
        now \= time.time()  
        

# Remove timestamps older than rate\_limit\_period

#         self.\_call\_timestamps \= \[

            ts for ts in self.\_call\_timestamps  
            if now \- ts \< self.rate\_limit\_period  
        \]  
          
        if len(self.\_call\_timestamps) \>= self.rate\_limit\_calls:  
            sleep\_time \= self.rate\_limit\_period \- (now \- self.\_call\_timestamps\[0\])  
            if sleep\_time \> 0:  
                logger.warning(f"Rate limit reached. Sleeping for {sleep\_time:.2f} seconds")  
                time.sleep(sleep\_time)  
                self.\_call\_timestamps \= \[\]  
          
        self.\_call\_timestamps.append(now)  
      
    def \_authenticate(self) \-\> None:  
        """Authenticate with OAuth2 client credentials flow.  
          
        Raises:  
            AnbimaAuthenticationError: If authentication fails  
        """  
        logger.info("Authenticating with ANBIMA API")  
          
        payload \= {  
            "grant\_type": "client\_credentials",  
            "client\_id": self.client\_id,  
            "client\_secret": self.client\_secret  
        }  
          
        try:  
            response \= self.session.post(  
                self.token\_url,  
                data=payload,  
                timeout=self.timeout  
            )  
            response.raise\_for\_status()  
              
            token\_data \= TokenResponse(respon**se.json())**  
            self.\_access\_token \= token\_data.access\_token  
            

# Set expiration time with 5-minute buffer

#             expires\_in \= token\_data.expires\_in \- 300

            self.\_token\_expires\_at \= datetime.now() \+ timedelta(seconds=expires\_in)  
              
            logger.info("Authentication successful")  
              
        except requests.exceptions.RequestException as e:  
            logger.error(f"Authentication failed: {str(e)}")  
            raise AnbimaAuthenticationError(f"Failed to authenticate: {str(e)}")  
        except ValidationError as e:  
            logger.error(f"Invalid token response: {str(e)}")  
            raise AnbimaAuthenticationError(f"Invalid token response: {str(e)}")  
      
    def \_ensure\_authenticated(self) \-\> None:  
        """Ensure valid access token exists, refresh if needed."""  
        if self.\_access\_token is None or self.\_token\_expires\_at is None:  
            self.\_authenticate()  
        elif datetime.now() \>= self.\_token\_expires\_at:  
            logger.info("Token expired, refreshing")  
            self.\_authenticate()  
      
    def \_make\_request(  
        self,  
        method: str,  
        endpoint: str,  
        params: Optional\[Dict\[str, Any\]\] \= None,  
        json\_data: Optional\[Dict\[str, Any\]\] \= None  
    ) \-\> Dict\[str, Any\]:  
        """Make an authenticated API request.  
          
        Args:  
            method: HTTP method (GET, POST, etc.)  
            endpoint: API endpoint (e.g., "/feed/cri-cra/mercado-secundario")  
            params: Query parameters  
            json\_data: JSON request body  
              
        Returns:  
            Response data as dictionary  
              
        Raises:  
            AnbimaAPIError: If request fails  
            AnbimaRateLimitError: If rate limit is exceeded  
        """  
        self.\_ensure\_authenticated()  
        self.\_check\_rate\_limit()  
          
        url \= f"{self.base\_url}{endpoint}"  
        headers \= {  
            "Authorization": f"Bearer {self.\_access\_token}",  
            "Accept": "application/json",  
            "Content-Type": "application/json"  
        }  
          
        logger.debug(f"Making {method} request to {url}")  
          
        try:  
            response \= self.session.request(  
                method=method,  
                url=url,  
                headers=headers,  
                params=params,  
                json=json\_data,  
                timeout=self.timeout  
            )  
              
            if response.status\_code \== 429:  
                retry\_after \= int(response.headers.get("Retry-After", 60))  
                logger.warning(f"Rate limit hit, retry after {retry\_after}s")  
                raise AnbimaRateLimitError(f"Rate limit exceeded. Retry after {retry\_after} seconds")  
              
            response.raise\_for\_status()  
            return response.json()  
              
        except requests.exceptions.HTTPError as e:  
            try:  
                error\_data \= e.response.json()  
                error\_msg \= error\_data.get("message", str(e))  
            except:  
                error\_msg \= str(e)  
              
            logger.error(f"HTTP error: {error\_msg}")  
            raise AnbimaAPIError(f"API request failed: {error\_msg}")  
              
        except requests.exceptions.RequestException as e:  
            logger.error(f"Request failed: {str(e)}")  
            raise AnbimaAPIError(f"Request failed: {str(e)}")  
      
    def \_paginate(  
        self,  
        endpoint: str,  
        params: Optional\[Dict\[str, Any\]\] \= None,  
        max\_pages: Optional\[int\] \= None  
    ) \-\> List\[Dict\[str, Any\]\]:  
        """Paginate through API results.  
          
        Args:  
            endpoint: API endpoint  
            params: Query parameters  
            max\_pages: Maximum number of pages to fetch (None for all)  
              
        Returns:  
            List of all items from all pages  
        """  
        all\_items \= \[\]  
        page \= 1  
        params \= params or {}  
          
        while True:  
            if max\_pages and page \> max\_pages:  
                break  
              
            params\["page"\] \= page  
            response\_data \= self.\_make\_request("GET", endpoint, params=params)  
              
            items \= response\_data.get("data", \[\])  
            if not items:  
                break  
              
            all\_items.extend(items)  
            

# Check if there are more pages

#             pagination \= response\_data.get("pagination", {})

            if not pagination.get("has\_next", False):  
                break  
              
            page \+= 1  
            logger.debug(f"Fetched page {page-1}, total items: {len(all\_items)}")  
          
        return all\_items  
      
    def get\_cri\_cra\_mercado\_secundario(  
        self,  
        data\_referencia: Optional\[str\] \= None,  
        codigo\_isin: Optional\[str\] \= None,  
        paginate: bool \= True,  
        max\_pages: Optional\[int\] \= None  
    ) \-\> List\[CriCraItem\]:  
        """Get CRI/CRA secondary market data.  
          
        Args:  
            data\_referencia: Reference date in YYYY-MM-DD format  
            codigo\_isin: ISIN code filter  
            paginate: Whether to fetch all pages (default: True)  
            max\_pages: Maximum number of pages to fetch  
              
        Returns:  
            List of CriCraItem objects  
              
        Raises:  
            AnbimaAPIError: If request fails  
            AnbimaValidationError: If response validation fails  
        """  
        endpoint \= "/feed/cri-cra/mercado-secundario"  
        params \= {}  
          
        if data\_referencia:  
            params\["data\_referencia"\] \= data\_referencia  
        if codigo\_isin:  
            params\["codigo\_isin"\] \= codigo\_isin  
          
        try:  
            if paginate:  
                items\_data \= self.\_paginate(endpoint, params, max\_pages)  
            else:  
                response \= self.\_make\_request("GET", endpoint, params=params)  
                items\_data \= response.get("data", \[\])  
              
            return \[CriCraItem(item) **for item in items\_data\]**  
              
        except ValidationError as e:  
            logger.error(f"Validation error: {str(e)}")  
            raise AnbimaValidationError(f"Failed to validate response: {str(e)}")  
      
    def get\_cri\_cra\_projecoes(  
        self,  
        data\_referencia: Optional\[str\] \= None,  
        codigo\_isin: Optional\[str\] \= None,  
        paginate: bool \= True,  
        max\_pages: Optional\[int\] \= None  
    ) \-\> List\[CriCraProjecao\]:  
        """Get CRI/CRA projections data.  
          
        Args:  
            data\_referencia: Reference date in YYYY-MM-DD format  
            codigo\_isin: ISIN code filter  
            paginate: Whether to fetch all pages (default: True)  
            max\_pages: Maximum number of pages to fetch  
              
        Returns:  
            List of CriCraProjecao objects  
              
        Raises:  
            AnbimaAPIError: If request fails  
            AnbimaValidationError: If response validation fails  
        """  
        endpoint \= "/feed/cri-cra/projecoes"  
        params \= {}  
          
        if data\_referencia:  
            params\["data\_referencia"\] \= data\_referencia  
        if codigo\_isin:  
            params\["codigo\_isin"\] \= codigo\_isin  
          
        try:  
            if paginate:  
                items\_data \= self.\_paginate(endpoint, params, max\_pages)  
            else:  
                response \= self.\_make\_request("GET", endpoint, params=params)  
                items\_data \= response.get("data", \[\])  
              
            return \[CriCraProjecao(item) **for item in items\_data\]**  
              
        except ValidationError as e:  
            logger.error(f"Validation error: {str(e)}")  
            raise AnbimaValidationError(f"Failed to validate response: {str(e)}")  
      
    def get\_debentures\_mercado\_secundario(  
        self,  
        data\_referencia: Optional\[str\] \= None,  
        codigo\_isin: Optional\[str\] \= None,  
        tipo: Optional\[str\] \= None,  
        paginate: bool \= True,  
        max\_pages: Optional\[int\] \= None  
    ) \-\> List\[DebentureItem\]:  
        """Get debentures secondary market data.  
          
        Args:  
            data\_referencia: Reference date in YYYY-MM-DD format  
            codigo\_isin: ISIN code filter  
            tipo: Type filter (e.g., 'comum', 'incentivada')  
            paginate: Whether to fetch all pages (default: True)  
            max\_pages: Maximum number of pages to fetch  
              
        Returns:  
            List of DebentureItem objects  
              
        Raises:  
            AnbimaAPIError: If request fails  
            AnbimaValidationError: If response validation fails  
        """  
        endpoint \= "/feed/debentures/mercado-secundario"  
        params \= {}  
          
        if data\_referencia:  
            params\["data\_referencia"\] \= data\_referencia  
        if codigo\_isin:  
            params\["codigo\_isin"\] \= codigo\_isin  
        if tipo:  
            params\["tipo"\] \= tipo  
          
        try:  
            if paginate:  
                items\_data \= self.\_paginate(endpoint, params, max\_pages)  
            else:  
                response \= self.\_make\_request("GET", endpoint, params=params)  
                items\_data \= response.get("data", \[\])  
              
            return \[DebentureItem(item) **for item in items\_data\]**  
              
        except ValidationError as e:  
            logger.error(f"Validation error: {str(e)}")  
            raise AnbimaValidationError(f"Failed to validate response: {str(e)}")  
      
    def get\_debentures\_curvas(  
        self,  
        data\_referencia: Optional\[str\] \= None,  
        tipo\_curva: Optional\[str\] \= None,  
        indexador: Optional\[str\] \= None,  
        paginate: bool \= True,  
        max\_pages: Optional\[int\] \= None  
    ) \-\> List\[DebentureCurva\]:  
        """Get debentures yield curves.  
          
        Args:  
            data\_referencia: Reference date in YYYY-MM-DD format  
            tipo\_curva: Curve type (e.g., 'yield', 'spread')  
            indexador: Index type (e.g., 'DI', 'IPCA')  
            paginate: Whether to fetch all pages (default: True)  
            max\_pages: Maximum number of pages to fetch  
              
        Returns:  
            List of DebentureCurva objects  
              
        Raises:  
            AnbimaAPIError: If request fails  
            AnbimaValidationError: If response validation fails  
        """  
        endpoint \= "/feed/debentures/curvas"  
        params \= {}  
          
        if data\_referencia:  
            params\["data\_referencia"\] \= data\_referencia  
        if tipo\_curva:  
            params\["tipo\_curva"\] \= tipo\_curva  
        if indexador:  
            params\["indexador"\] \= indexador  
          
        try:  
            if paginate:  
                items\_data \= self.\_paginate(endpoint, params, max\_pages)  
            else:  
                response \= self.\_make\_request("GET", endpoint, params=params)  
                items\_data \= response.get("data", \[\])  
              
            return \[DebentureCurva(item) **for item in items\_data\]**  
              
        except ValidationError as e:  
            logger.error(f"Validation error: {str(e)}")  
            raise AnbimaValidationError(f"Failed to validate response: {str(e)}")  
      
    def get\_debentures\_projecoes(  
        self,  
        data\_referencia: Optional\[str\] \= None,  
        codigo\_isin: Optional\[str\] \= None,  
        paginate: bool \= True,  
        max\_pages: Optional\[int\] \= None  
    ) \-\> List\[DebentureProjecao\]:  
        """Get debentures projections.  
          
        Args:  
            data\_referencia: Reference date in YYYY-MM-DD format  
            codigo\_isin: ISIN code filter  
            paginate: Whether to fetch all pages (default: True)  
            max\_pages: Maximum number of pages to fetch  
              
        Returns:  
            List of DebentureProjecao objects  
              
        Raises:  
            AnbimaAPIError: If request fails  
            AnbimaValidationError: If response validation fails  
        """  
        endpoint \= "/feed/debentures/projecoes"  
        params \= {}  
          
        if data\_referencia:  
            params\["data\_referencia"\] \= data\_referencia  
        if codigo\_isin:  
            params\["codigo\_isin"\] \= codigo\_isin  
          
        try:  
            if paginate:  
                items\_data \= self.\_paginate(endpoint, params, max\_pages)  
            else:  
                response \= self.\_make\_request("GET", endpoint, params=params)  
                items\_data \= response.get("data", \[\])  
              
            return \[DebentureProjecao(item) **for item in items\_data\]**  
              
        except ValidationError as e:  
            logger.error(f"Validation error: {str(e)}")  
            raise AnbimaValidationError(f"Failed to validate response: {str(e)}")  
      
    def get\_fidc\_mercado\_secundario(  
        self,  
        data\_referencia: Optional\[str\] \= None,  
        cnpj: Optional\[str\] \= None,  
        classe: Optional\[str\] \= None,  
        paginate: bool \= True,  
        max\_pages: Optional\[int\] \= None  
    ) \-\> List\[FidcItem\]:  
        """Get FIDC secondary market data.  
          
        Args:  
            data\_referencia: Reference date in YYYY-MM-DD format  
            cnpj: CNPJ filter  
            classe: Class filter (e.g., 'senior', 'subordinada')  
            paginate: Whether to fetch all pages (default: True)  
            max\_pages: Maximum number of pages to fetch  
              
        Returns:  
            List of FidcItem objects  
              
        Raises:  
            AnbimaAPIError: If request fails  
            AnbimaValidationError: If response validation fails  
        """  
        endpoint \= "/feed/fidc/mercado-secundario"  
        params \= {}  
          
        if data\_referencia:  
            params\["data\_referencia"\] \= data\_referencia  
        if cnpj:  
            params\["cnpj"\] \= cnpj  
        if classe:  
            params\["classe"\] \= classe  
          
        try:  
            if paginate:  
                items\_data \= self.\_paginate(endpoint, params, max\_pages)  
            else:  
                response \= self.\_make\_request("GET", endpoint, params=params)  
                items\_data \= response.get("data", \[\])  
              
            return \[FidcItem(item) **for item in items\_data\]**  
              
        except ValidationError as e:  
            logger.error(f"Validation error: {str(e)}")  
            raise AnbimaValidationError(f"Failed to validate response: {str(e)}")  
      
    def get\_fundos\_estruturados(  
        self,  
        data\_referencia: Optional\[str\] \= None,  
        cnpj: Optional\[str\] \= None,  
        tipo: Optional\[str\] \= None,  
        paginate: bool \= True,  
        max\_pages: Optional\[int\] \= None  
    ) \-\> List\[FundoEstruturado\]:  
        """Get structured funds data.  
          
        Args:  
            data\_referencia: Reference date in YYYY-MM-DD format  
            cnpj: CNPJ filter  
            tipo: Fund type filter (e.g., 'FIDC', 'FII', 'FIP')  
            paginate: Whether to fetch all pages (default: True)  
            max\_pages: Maximum number of pages to fetch  
              
        Returns:  
            List of FundoEstruturado objects  
              
        Raises:  
            AnbimaAPIError: If request fails  
            AnbimaValidationError: If response validation fails  
        """  
        endpoint \= "/feed/fundos-estruturados"  
        params \= {}  
          
        if data\_referencia:  
            params\["data\_referencia"\] \= data\_referencia  
        if cnpj:  
            params\["cnpj"\] \= cnpj  
        if tipo:  
            params\["tipo"\] \= tipo  
          
        try:  
            if paginate:  
                items\_data \= self.\_paginate(endpoint, params, max\_pages)  
            else:  
                response \= self.\_make\_request("GET", endpoint, params=params)  
                items\_data \= response.get("data", \[\])  
              
            return \[FundoEstruturado(item) **for item in items\_data\]**  
              
        except ValidationError as e:  
            logger.error(f"Validation error: {str(e)}")  
            raise AnbimaValidationError(f"Failed to validate response: {str(e)}")  
      
    def get\_fundo\_serie\_historica(  
        self,  
        cnpj: str,  
        data\_inicio: Optional\[str\] \= None,  
        data\_fim: Optional\[str\] \= None,  
        paginate: bool \= True,  
        max\_pages: Optional\[int\] \= None  
    ) \-\> List\[SerieHistorica\]:  
        """Get historical series data for a specific fund.  
          
        Args:  
            cnpj: Fund CNPJ (required)  
            data\_inicio: Start date in YYYY-MM-DD format  
            data\_fim: End date in YYYY-MM-DD format  
            paginate: Whether to fetch all pages (default: True)  
            max\_pages: Maximum number of pages to fetch  
              
        Returns:  
            List of SerieHistorica objects  
              
        Raises:  
            AnbimaAPIError: If request fails  
            AnbimaValidationError: If response validation fails  
        """  
        endpoint \= f"/feed/fundos-estruturados/{cnpj}/serie-historica"  
        params \= {}  
          
        if data\_inicio:  
            params\["data\_inicio"\] \= data\_inicio  
        if data\_fim:  
            params\["data\_fim"\] \= data\_fim  
          
        try:  
            if paginate:  
                items\_data \= self.\_paginate(endpoint, params, max\_pages)  
            else:  
                response \= self.\_make\_request("GET", endpoint, params=params)  
                items\_data \= response.get("data", \[\])  
              
            return \[SerieHistorica(item) **for item in items\_data\]**  
              
        except ValidationError as e:  
            logger.error(f"Validation error: {str(e)}")  
            raise AnbimaValidationError(f"Failed to validate response: {str(e)}")  
      
    def close(self) \-\> None:  
        """Close the HTTP session."""  
        if self.session:  
            self.session.close()  
            logger.info("Session closed")  
      
    def \_\_enter\_\_(self):  
        """Context manager entry."""  
        return self  
      
    def \_\_exit\_\_(self, exc\_type, exc\_val, exc\_tb):  
        """Context manager exit."""  
        self.close()  
\`\`\`

### bacen\_models.py

### \`\`\`python

"""Pydantic models for BACEN API responses.

This module defines data models for BACEN time series data and metadata.  
"""

from datetime import datetime, date  
from typing import Optional, Any, Dict  
from pydantic import BaseModel, Field, field\_validator

class SeriesDataPoint(BaseModel):  
    """Represents a single data point in a time series.  
      
    Attributes:  
        data: Date of the observation (dd/MM/yyyy format)  
        valor: Value of the observation  
    """  
    data: str \= Field(..., description="Date in dd/MM/yyyy format")  
    valor: str \= Field(..., description="Value of the observation")  
      
    @field\_validator('valor', mode='before')  
    @classmethod  
    def convert\_valor(cls, v: Any) \-\> str:  
        """Convert valor to string, handling various input types."""  
        if v is None:  
            return ""  
        return str(v)  
      
    def get\_date(self) \-\> date:  
        """Parse and return date as date object.  
          
        Returns:  
            date object  
        """  
        return datetime.strptime(self.data, "%d/%m/%Y").date()  
      
    def get\_valor\_float(self) \-\> Optional\[float\]:  
        """Parse and return valor as float.  
          
        Returns:  
            Float value or None if parsing fails  
        """  
        try:  
            return float(self.valor)  
        except (ValueError, TypeError):  
            return None  
      
    class Config:  
        """Pydantic configuration."""  
        json\_schema\_extra \= {  
            "example": {  
                "data": "02/01/2023",  
                "valor": "13.75"  
            }  
        }

class SeriesInfo(BaseModel):  
    """Metadata about a time series.  
      
    Attributes:  
        codigo: Series code/ID  
        nome: Name of the series  
        unidadeMedida: Unit of measurement  
        periodicidade: Frequency (daily, monthly, etc.)  
        fonte: Data source  
        ultimaAtualizacao: Last update date  
    """  
    codigo: Optional\[int\] \= Field(None, description="Series ID")  
    nome: Optional\[str\] \= Field(None, description="Series name")  
    unidadeMedida: Optional\[str\] \= Field(None, description="Unit of measurement")  
    periodicidade: Optional\[str\] \= Field(None, description="Data frequency")  
    fonte: Optional\[str\] \= Field(None, description="Data source")  
    ultimaAtualizacao: Optional\[str\] \= Field(None, description="Last update date")  
      
    class Config:  
        """Pydantic configuration."""  
        json\_schema\_extra \= {  
            "example": {  
                "codigo": 432,  
                "nome": "Taxa Selic",  
                "unidadeMedida": "% a.a.",  
                "periodicidade": "Diária",  
                "fonte": "BCB-Demab",  
                "ultimaAtualizacao": "02/01/2024"  
            }  
        }

class SearchResult(BaseModel):  
    """Search result for series lookup.  
      
    Attributes:  
        id: Series ID  
        name: Series name  
        category: Category of the series  
        description: Full description  
        unit: Unit of measurement  
    """  
    id: int \= Field(..., description="Series ID")  
    name: str \= Field(..., description="Series name")  
    category: str \= Field(..., description="Category")  
    description: str \= Field(..., description="Full description")  
    unit: str \= Field(..., description="Unit of measurement")  
      
    class Config:  
        """Pydantic configuration."""  
        json\_schema\_extra \= {  
            "example": {  
                "id": 432,  
                "name": "SELIC",  
                "category": "interest\_rates",  
                "description": "Taxa de juros \- Selic acumulada no mês",  
                "unit": "% a.a."  
            }  
        }

# Common BACEN series IDs organized by category

# SERIES\_IDS: Dict\[str, Dict\[str, int\]\] \= {

    "interest\_rates": {  
        "selic": 432,  \# SELIC \- accumulated in month  
        "selic\_daily": 11,  \# SELIC \- daily  
        "selic\_target": 4189,  \# SELIC meta \- target rate  
        "tjlp": 256,  \# TJLP \- long-term interest rate  
        "cdi": 4391,  \# CDI rate  
    },  
    "inflation": {  
        "ipca": 433,  \# IPCA \- consumer price index  
        "ipca\_15": 7478,  \# IPCA-15 (mid-month)  
        "igp\_m": 189,  \# IGP-M \- general price index  
        "igp\_di": 190,  \# IGP-DI  
        "inpc": 188,  \# INPC \- national consumer price index  
    },  
    "exchange\_rates": {  
        "ptax\_sale": 1,  \# USD/BRL \- PTAX sale  
        "ptax\_buy": 10813,  \# USD/BRL \- PTAX buy  
        "euro\_sale": 21619,  \# EUR/BRL \- sale  
        "euro\_buy": 21620,  \# EUR/BRL \- buy  
        "pound\_sale": 21621,  \# GBP/BRL \- sale  
        "pound\_buy": 21622,  \# GBP/BRL \- buy  
        "yen\_sale": 21623,  \# JPY/BRL \- sale  
        "yen\_buy": 21624,  \# JPY/BRL \- buy  
        "swiss\_franc\_sale": 21625,  \# CHF/BRL \- sale  
        "swiss\_franc\_buy": 21626,  \# CHF/BRL \- buy  
        "canadian\_dollar\_sale": 21627,  \# CAD/BRL \- sale  
        "canadian\_dollar\_buy": 21628,  \# CAD/BRL \- buy  
    },  
    "economic\_activity": {  
        "ibc\_br": 24364,  \# IBC-Br \- economic activity index  
        "gdp": 4380,  \# GDP \- quarterly  
        "industrial\_production": 21859,  \# Industrial production  
        "retail\_sales": 1455,  \# Retail sales volume  
    },  
    "credit": {  
        "operations\_total": 20542,  \# Total credit operations  
        "operations\_persons": 20544,  \# Credit operations \- individuals  
        "operations\_companies": 20545,  \# Credit operations \- companies  
        "operations\_housing": 20715,  \# Credit operations \- housing  
        "operations\_rural": 20716,  \# Credit operations \- rural  
        "average\_rate\_total": 20714,  \# Average interest rate \- total  
        "average\_rate\_persons": 20718,  \# Average interest rate \- individuals  
        "average\_rate\_companies": 20719,  \# Average interest rate \- companies  
    },  
    "monetary\_aggregates": {  
        "m1": 27788,  \# M1 \- monetary base  
        "m2": 27789,  \# M2 \- broad money  
        "m3": 27790,  \# M3 \- broader money  
        "m4": 27791,  \# M4 \- broadest money  
        "monetary\_base": 1785,  \# Monetary base  
        "currency\_circulation": 1786,  \# Currency in circulation  
    },  
    "reserve\_requirements": {  
        "demand\_deposits": 1848,  \# Reserve requirement \- demand deposits  
        "time\_deposits": 1849,  \# Reserve requirement \- time deposits  
        "additional\_requirement": 1850,  \# Additional reserve requirement  
    },  
    "public\_debt": {  
        "federal\_public\_debt": 4513,  \# Federal public debt  
        "domestic\_debt": 4536,  \# Domestic public debt  
        "external\_debt": 4537,  \# External public debt  
    },  
    "balance\_of\_payments": {  
        "current\_account": 23093,  \# Current account balance  
        "trade\_balance": 22707,  \# Trade balance  
        "foreign\_direct\_investment": 23095,  \# Foreign direct investment  
        "international\_reserves": 3546,  \# International reserves  
    },  
    "employment": {  
        "unemployment\_rate": 24369,  \# Unemployment rate (PNAD)  
        "employed\_persons": 24370,  \# Number of employed persons  
        "labor\_force": 24371,  \# Labor force  
    },  
    "fiscal": {  
        "primary\_result": 5793,  \# Primary fiscal result  
        "nominal\_result": 5794,  \# Nominal fiscal result  
        "net\_debt\_gdp": 4513,  \# Net debt / GDP ratio  
    }  
}

# Convenience function to get series ID by name

# def get\_series\_id(category: str, name: str) \-\> Optional\[int\]:

    """Get series ID by category and name.  
      
    Args:  
        category: Category name (e.g., 'interest\_rates')  
        name: Series name (e.g., 'selic')  
          
    Returns:  
        Series ID or None if not found  
          
    Example:  
        \>\>\> series\_id \= get\_series\_id('interest\_rates', 'selic')  
        \>\>\> print(series\_id)  \# 432  
    """  
    return SERIES\_IDS.get(category, {}).get(name)

# Convenience function to list all available series

# def list\_all\_series() \-\> Dict\[str, Dict\[str, int\]\]:

    """Get all available series IDs organized by category.  
      
    Returns:  
        Dictionary of all series IDs  
          
    Example:  
        \>\>\> all\_series \= list\_all\_series()  
        \>\>\> for category, series\_dict in all\_series.items():  
        ...     print(f"Category: {category}")  
        ...     for name, series\_id in series\_dict.items():  
        ...         print(f"  {name}: {series\_id}")  
    """  
    return SERIES\_IDS

# Convenience function to search series by keyword

# def search\_series\_ids(keyword: str) \-\> Dict\[str, Dict\[str, int\]\]:

    """Search for series IDs by keyword.  
      
    Args:  
        keyword: Search keyword  
          
    Returns:  
        Dictionary of matching series IDs  
          
    Example:  
        \>\>\> results \= search\_series\_ids('credit')  
        \>\>\> print(results)  
    """  
    keyword\_lower \= keyword.lower()  
    results \= {}  
      
    for category, series\_dict in SERIES\_IDS.items():  
        if keyword\_lower in category.lower():  
            results\[category\] \= series\_dict  
        else:  
            matching\_series \= {  
                name: series\_id  
                for name, series\_id in series\_dict.items()  
                if keyword\_lower in name.lower()  
            }  
            if matching\_series:  
                results\[category\] \= matching\_series  
      
    return results

\`\`\`

### bacen\_client.py

### \`\`\`python

"""BACEN (Banco Central do Brasil) Time Series API Client.

This module provides a comprehensive client for accessing BACEN's public time series data.  
No authentication is required for public endpoints.  
"""

import time  
from datetime import datetime, date  
from typing import Optional, List, Dict, Any, Union  
from urllib.parse import urlencode  
import logging

import requests  
from requests.adapters import HTTPAdapter  
from urllib3.util.retry import Retry

from bacen\_models import (  
    SeriesDataPoint,  
    SeriesInfo,  
    SearchResult,  
    SERIES\_IDS  
)

logger \= logging.getLogger(\_\_name\_\_)

class RateLimiter:  
    """Simple rate limiter to respect BACEN API limits."""  
      
    def \_\_init\_\_(self, calls\_per\_minute: int \= 30):  
        """Initialize rate limiter.  
          
        Args:  
            calls\_per\_minute: Maximum number of calls allowed per minute  
        """  
        self.calls\_per\_minute \= calls\_per\_minute  
        self.calls: List\[float\] \= \[\]  
      
    def wait\_if\_needed(self) \-\> None:  
        """Wait if rate limit would be exceeded."""  
        now \= time.time()

# Remove calls older than 1 minute

#         self.calls \= \[call\_time for call\_time in self.calls if now \- call\_time \< 60\]

          
        if len(self.calls) \>= self.calls\_per\_minute:  
            sleep\_time \= 60 \- (now \- self.calls\[0\])  
            if sleep\_time \> 0:  
                logger.info(f"Rate limit reached. Sleeping for {sleep\_time:.2f} seconds")  
                time.sleep(sleep\_time)  
                self.calls \= \[\]  
          
        self.calls.append(time.time())

class BacenClient:  
    """Client for BACEN Time Series API.  
      
    The BACEN API provides access to Brazilian economic and financial data  
    including interest rates, inflation indices, exchange rates, and more.  
    """  
      
    BASE\_URL \= "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{series\_id}/dados"  
    METADATA\_URL \= "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{series\_id}"  
      
    def \_\_init\_\_(  
        self,  
        timeout: int \= 30,  
        max\_retries: int \= 3,  
        backoff\_factor: float \= 0.5,  
        rate\_limit\_per\_minute: int \= 30,  
        enable\_cache: bool \= True  
    ):  
        """Initialize BACEN client.  
          
        Args:  
            timeout: Request timeout in seconds  
            max\_retries: Maximum number of retry attempts  
            backoff\_factor: Backoff factor for exponential retry  
            rate\_limit\_per\_minute: Maximum API calls per minute  
            enable\_cache: Enable simple in-memory caching  
        """  
        self.timeout \= timeout  
        self.rate\_limiter \= RateLimiter(rate\_limit\_per\_minute)  
        self.enable\_cache \= enable\_cache  
        self.\_cache: Dict\[str, Any\] \= {}  
        

# Configure session with retry logic

#         self.session \= requests.Session()

        retry\_strategy \= Retry(  
            total=max\_retries,  
            backoff\_factor=backoff\_factor,  
            status\_forcelist=\[429, 500, 502, 503, 504\],  
            allowed\_methods=\["GET"\]  
        )  
        adapter \= HTTPAdapter(max\_retries=retry\_strategy)  
        self.session.mount("http://", adapter)  
        self.session.mount("https://", adapter)  
        

# Set headers

#         self.session.headers.update({

            "User-Agent": "BacenPythonClient/1.0",  
            "Accept": "application/json"  
        })  
      
    def \_format\_date(self, date\_obj: Union\[str, date, datetime\]) \-\> str:  
        """Format date to BACEN API format (dd/MM/yyyy).  
          
        Args:  
            date\_obj: Date as string, date, or datetime object  
              
        Returns:  
            Formatted date string  
        """  
        if isinstance(date\_obj, str):

# Try to parse string

#             for fmt in \["%Y-%m-%d", "%d/%m/%Y", "%Y%m%d"\]:

                try:  
                    date\_obj \= datetime.strptime(date\_obj, fmt).date()  
                    break  
                except ValueError:  
                    continue  
            else:  
                raise ValueError(f"Unable to parse date string: {date\_obj}")  
        elif isinstance(date\_obj, datetime):  
            date\_obj \= date\_obj.date()  
          
        return date\_obj.strftime("%d/%m/%Y")  
      
    def \_get\_cache\_key(self, \*args, kwargs) **\-\> str:**  
        """Generate cache key from arguments."""  
        key\_parts \= \[str(arg) for arg in args\]  
        key\_parts.extend(f"{k}={v}" for k, v in sorted(kwargs.items()))  
        return "|".join(key\_parts)  
      
    def \_make\_request(  
        self,  
        url: str,  
        params: Optional\[Dict\[str, Any\]\] \= None,  
        use\_cache: bool \= True  
    ) \-\> Dict\[str, Any\]:  
        """Make HTTP request with rate limiting and caching.  
          
        Args:  
            url: Request URL  
            params: Query parameters  
            use\_cache: Whether to use cache  
              
        Returns:  
            JSON response as dictionary  
              
        Raises:  
            requests.RequestException: If request fails  
        """  
        cache\_key \= self.\_get\_cache\_key(url, (params **or {}))**  
        

# Check cache

#         if use\_cache and self.enable\_cache and cache\_key in self.\_cache:

            logger.debug(f"Cache hit for {cache\_key}")  
            return self.\_cache\[cache\_key\]  
        

# Rate limiting

#         self.rate\_limiter.wait\_if\_needed()

        

# Make request

#         try:

            response \= self.session.get(url, params=params, timeout=self.timeout)  
            response.raise\_for\_status()  
            data \= response.json()  
            

# Cache response

#             if use\_cache and self.enable\_cache:

                self.\_cache\[cache\_key\] \= data  
              
            return data  
        except requests.exceptions.HTTPError as e:  
            logger.error(f"HTTP error: {e}")  
            raise  
        except requests.exceptions.RequestException as e:  
            logger.error(f"Request error: {e}")  
            raise  
        except ValueError as e:  
            logger.error(f"JSON decode error: {e}")  
            raise  
      
    def get\_series(  
        self,  
        series\_id: Union\[int, str\],  
        start\_date: Optional\[Union\[str, date, datetime\]\] \= None,  
        end\_date: Optional\[Union\[str, date, datetime\]\] \= None,  
        format: str \= "json"  
    ) \-\> List\[SeriesDataPoint\]:  
        """Fetch time series data.  
          
        Args:  
            series\_id: BACEN series ID  
            start\_date: Start date (optional)  
            end\_date: End date (optional)  
            format: Response format ('json' or 'csv')  
              
        Returns:  
            List of SeriesDataPoint objects  
              
        Example:  
            \>\>\> client \= BacenClient()  
            \>\>\> data \= client.get\_series(432, start\_date="2023-01-01", end\_date="2023-12-31")  
            \>\>\> print(f"SELIC rate on {data\[0\].data}: {data\[0\].valor}%")  
        """  
        url \= self.BASE\_URL.format(series\_id=series\_id)  
        params \= {}  
          
        if start\_date:  
            params\["dataInicial"\] \= self.\_format\_date(start\_date)  
        if end\_date:  
            params\["dataFinal"\] \= self.\_format\_date(end\_date)  
        if format \== "csv":  
            params\["formato"\] \= "csv"  
          
        data \= self.\_make\_request(url, params)  
          
        if format \== "csv":  
            return data  \# Return raw CSV string  
          
        return \[SeriesDataPoint(item) fo**r item in data\]**  
      
    def get\_series\_info(self, series\_id: Union\[int, str\]) \-\> SeriesInfo:  
        """Get metadata about a time series.  
          
        Args:  
            series\_id: BACEN series ID  
              
        Returns:  
            SeriesInfo object with metadata  
              
        Example:  
            \>\>\> client \= BacenClient()  
            \>\>\> info \= client.get\_series\_info(432)  
            \>\>\> print(f"Series: {info.nome}")  
            \>\>\> print(f"Unit: {info.unidadeMedida}")  
        """  
        url \= self.METADATA\_URL.format(series\_id=series\_id)  
        data \= self.\_make\_request(url)  
        return SeriesInfo(data)  
      
    def search\_series(self, keyword: str) \-\> List\[SearchResult\]:  
        """Search for series by keyword.  
          
        Note: BACEN API doesn't provide a direct search endpoint.  
        This method searches through common series IDs defined in SERIES\_IDS.  
          
        Args:  
            keyword: Search keyword  
              
        Returns:  
            List of SearchResult objects  
              
        Example:  
            \>\>\> client \= BacenClient()  
            \>\>\> results \= client.search\_series("selic")  
            \>\>\> for result in results:  
            ...     print(f"{result.id}: {result.name}")  
        """  
        keyword\_lower \= keyword.lower()  
        results \= \[\]  
          
        for category, series\_dict in SERIES\_IDS.items():  
            for name, series\_id in series\_dict.items():  
                if keyword\_lower in name.lower() or keyword\_lower in category.lower():  
                    try:  
                        info \= self.get\_series\_info(series\_id)  
                        results.append(  
                            SearchResult(  
                                id=series\_id,  
                                name=name,  
                                category=category,  
                                description=getattr(info, 'nome', name),  
                                unit=getattr(info, 'unidadeMedida', 'N/A')  
                            )  
                        )  
                    except Exception as e:  
                        logger.warning(f"Failed to get info for series {series\_id}: {e}")  
                        continue  
          
        return results  
      
    def get\_credit\_operations\_by\_sector(  
        self,  
        sector: str \= "total",  
        start\_date: Optional\[Union\[str, date, datetime\]\] \= None,  
        end\_date: Optional\[Union\[str, date, datetime\]\] \= None  
    ) \-\> List\[SeriesDataPoint\]:  
        """Get credit operations data by sector.  
          
        Args:  
            sector: Sector type ('total', 'persons', 'companies', 'housing', 'rural')  
            start\_date: Start date (optional)  
            end\_date: End date (optional)  
              
        Returns:  
            List of SeriesDataPoint objects  
              
        Example:  
            \>\>\> client \= BacenClient()  
            \>\>\> data \= client.get\_credit\_operations\_by\_sector("total")  
            \>\>\> print(f"Total credit: R$ {data\[-1\].valor} billion")  
        """  
        sector\_map \= {  
            "total": SERIES\_IDS\["credit"\]\["operations\_total"\],  
            "persons": SERIES\_IDS\["credit"\]\["operations\_persons"\],  
            "companies": SERIES\_IDS\["credit"\]\["operations\_companies"\],  
            "housing": SERIES\_IDS\["credit"\]\["operations\_housing"\],  
            "rural": SERIES\_IDS\["credit"\]\["operations\_rural"\]  
        }  
          
        series\_id \= sector\_map.get(sector.lower())  
        if not series\_id:  
            raise ValueError(f"Invalid sector: {sector}. Choose from {list(sector\_map.keys())}")  
          
        return self.get\_series(series\_id, start\_date, end\_date)  
      
    def get\_economic\_activity\_index(  
        self,  
        start\_date: Optional\[Union\[str, date, datetime\]\] \= None,  
        end\_date: Optional\[Union\[str, date, datetime\]\] \= None  
    ) \-\> List\[SeriesDataPoint\]:  
        """Get IBC-Br (Economic Activity Index) data.  
          
        The IBC-Br is a monthly indicator of Brazilian economic activity.  
          
        Args:  
            start\_date: Start date (optional)  
            end\_date: End date (optional)  
              
        Returns:  
            List of SeriesDataPoint objects  
              
        Example:  
            \>\>\> client \= BacenClient()  
            \>\>\> data \= client.get\_economic\_activity\_index(start\_date="2023-01-01")  
            \>\>\> print(f"Latest IBC-Br: {data\[-1\].valor}")  
        """  
        return self.get\_series(  
            SERIES\_IDS\["economic\_activity"\]\["ibc\_br"\],  
            start\_date,  
            end\_date  
        )  
      
    def get\_exchange\_rate(  
        self,  
        currency: str \= "USD",  
        start\_date: Optional\[Union\[str, date, datetime\]\] \= None,  
        end\_date: Optional\[Union\[str, date, datetime\]\] \= None  
    ) \-\> List\[SeriesDataPoint\]:  
        """Get exchange rate data.  
          
        Args:  
            currency: Currency code ('USD', 'EUR', 'GBP', 'JPY', 'CHF', 'CAD')  
            start\_date: Start date (optional)  
            end\_date: End date (optional)  
              
        Returns:  
            List of SeriesDataPoint objects  
              
        Example:  
            \>\>\> client \= BacenClient()  
            \>\>\> data \= client.get\_exchange\_rate("USD")  
            \>\>\> print(f"USD/BRL: {data\[-1\].valor}")  
        """  
        currency\_map \= {  
            "USD": "ptax\_sale",  
            "EUR": "euro\_sale",  
            "GBP": "pound\_sale",  
            "JPY": "yen\_sale",  
            "CHF": "swiss\_franc\_sale",  
            "CAD": "canadian\_dollar\_sale"  
        }  
          
        series\_key \= currency\_map.get(currency.upper())  
        if not series\_key:  
            raise ValueError(f"Invalid currency: {currency}. Choose from {list(currency\_map.keys())}")  
          
        series\_id \= SERIES\_IDS\["exchange\_rates"\]\[series\_key\]  
        return self.get\_series(series\_id, start\_date, end\_date)  
      
    def get\_selic\_rate(  
        self,  
        start\_date: Optional\[Union\[str, date, datetime\]\] \= None,  
        end\_date: Optional\[Union\[str, date, datetime\]\] \= None  
    ) \-\> List\[SeriesDataPoint\]:  
        """Get SELIC interest rate time series.  
          
        The SELIC is Brazil's benchmark interest rate.  
          
        Args:  
            start\_date: Start date (optional)  
            end\_date: End date (optional)  
              
        Returns:  
            List of SeriesDataPoint objects  
              
        Example:  
            \>\>\> client \= BacenClient()  
            \>\>\> data \= client.get\_selic\_rate()  
            \>\>\> print(f"Current SELIC rate: {data\[-1\].valor}% per year")  
        """  
        return self.get\_series(  
            SERIES\_IDS\["interest\_rates"\]\["selic"\],  
            start\_date,  
            end\_date  
        )  
      
    def get\_ipca(  
        self,  
        start\_date: Optional\[Union\[str, date, datetime\]\] \= None,  
        end\_date: Optional\[Union\[str, date, datetime\]\] \= None  
    ) \-\> List\[SeriesDataPoint\]:  
        """Get IPCA (Consumer Price Index) data.  
          
        Args:  
            start\_date: Start date (optional)  
            end\_date: End date (optional)  
              
        Returns:  
            List of SeriesDataPoint objects  
              
        Example:  
            \>\>\> client \= BacenClient()  
            \>\>\> data \= client.get\_ipca(start\_date="2023-01-01")  
            \>\>\> print(f"Latest IPCA: {data\[-1\].valor}%")  
        """  
        return self.get\_series(  
            SERIES\_IDS\["inflation"\]\["ipca"\],  
            start\_date,  
            end\_date  
        )  
      
    def get\_reserve\_requirement(  
        self,  
        requirement\_type: str \= "demand\_deposits",  
        start\_date: Optional\[Union\[str, date, datetime\]\] \= None,  
        end\_date: Optional\[Union\[str, date, datetime\]\] \= None  
    ) \-\> List\[SeriesDataPoint\]:  
        """Get reserve requirement data.  
          
        Args:  
            requirement\_type: Type of reserve requirement  
                ('demand\_deposits', 'time\_deposits', 'additional')  
            start\_date: Start date (optional)  
            end\_date: End date (optional)  
              
        Returns:  
            List of SeriesDataPoint objects  
        """  
        type\_map \= {  
            "demand\_deposits": "demand\_deposits",  
            "time\_deposits": "time\_deposits",  
            "additional": "additional\_requirement"  
        }  
          
        series\_key \= type\_map.get(requirement\_type.lower())  
        if not series\_key:  
            raise ValueError(f"Invalid requirement type: {requirement\_type}")  
          
        series\_id \= SERIES\_IDS\["reserve\_requirements"\]\[series\_key\]  
        return self.get\_series(series\_id, start\_date, end\_date)  
      
    def clear\_cache(self) \-\> None:  
        """Clear the request cache."""  
        self.\_cache.clear()  
        logger.info("Cache cleared")  
      
    def close(self) \-\> None:  
        """Close the session and clean up resources."""  
        self.session.close()  
        self.clear\_cache()

\`\`\`

### integration\_models.py

### \`\`\`python

from pydantic import BaseModel, Field, validator  
from typing import Optional, List, Dict, Any  
from datetime import datetime  
from enum import Enum

class FundSituation(str, Enum):  
    """Fund registration situation."""  
    ACTIVE \= "EM FUNCIONAMENTO NORMAL"  
    LIQUIDATION \= "EM LIQUIDACAO"  
    CANCELLED \= "CANCELADA"  
    SUSPENDED \= "SUSPENSA"

class BenchmarkType(str, Enum):  
    """Benchmark types for comparison."""  
    CDI \= "CDI"  
    IPCA \= "IPCA"  
    SECTOR \= "SECTOR"  
    CUSTOM \= "CUSTOM"

class IntegratedFidcData(BaseModel):  
    """Unified data model combining all FIDC data sources."""  
    

# Identification

#     cnpj: str \= Field(..., description="FIDC CNPJ (digits only)")

    fund\_name: str \= Field(..., description="Fund official name")  
    fund\_type: str \= Field(default="FIDC", description="Fund type classification")  
    situation: str \= Field(..., description="Current registration situation")  
    

# Registration information

#     registration\_date: Optional\[datetime\] \= Field(None, description="CVM registration date")

    administrator\_cnpj: Optional\[str\] \= Field(None, description="Administrator CNPJ")  
    manager\_cnpj: Optional\[str\] \= Field(None, description="Manager CNPJ")  
    

# Time period

#     start\_date: datetime \= Field(..., description="Analysis period start date")

    end\_date: datetime \= Field(..., description="Analysis period end date")  
    

# Portfolio composition (from CVM monthly reports)

#     portfolio\_composition: Dict\[str, Any\] \= Field(

        default\_factory=dict,  
        description="Portfolio composition including NAV series and asset breakdown"  
    )  
    

# ANBIMA pricing data

#     anbima\_pricing: List\[Dict\[str, Any\]\] \= Field(

        default\_factory=list,  
        description="ANBIMA secondary market pricing records"  
    )  
    

# Sector information

#     sector\_code: str \= Field(..., description="Economic sector code")

    sector\_context: Dict\[str, Any\] \= Field(  
        default\_factory=dict,  
        description="BACEN sector-level context data"  
    )  
    

# Data quality

#     data\_quality\_score: float \= Field(

        default=0.0,  
        ge=0.0,  
        le=1.0,  
        description="Data quality score (0-1)"  
    )  
    

# Metadata

#     last\_update: datetime \= Field(

        default\_factory=datetime.now,  
        description="Last data update timestamp"  
    )  
      
    class Config:  
        json\_encoders \= {  
            datetime: lambda v: v.isoformat() if v else None  
        }

class PerformanceMetrics(BaseModel):  
    """Comprehensive performance metrics for a FIDC."""  
      
    cnpj: str \= Field(..., description="FIDC CNPJ")  
    period\_start: datetime \= Field(..., description="Performance period start")  
    period\_end: datetime \= Field(..., description="Performance period end")  
    

# Return metrics

#     total\_return: float \= Field(..., description="Total return (%)")

    annualized\_return: float \= Field(..., description="Annualized return (%)")  
    monthly\_returns: List\[float\] \= Field(  
        default\_factory=list,  
        description="Monthly return series"  
    )  
    cumulative\_returns: List\[float\] \= Field(  
        default\_factory=list,  
        description="Cumulative return series"  
    )  
    

# Risk metrics

#     volatility: float \= Field(..., description="Annualized volatility (%)")

    sharpe\_ratio: float \= Field(..., description="Sharpe ratio")  
    sortino\_ratio: Optional\[float\] \= Field(None, description="Sortino ratio")  
    max\_drawdown: float \= Field(..., description="Maximum drawdown (%)")  
    

# NAV metrics

#     nav\_start: float \= Field(..., description="NAV at period start")

    nav\_end: float \= Field(..., description="NAV at period end")  
    nav\_peak: float \= Field(..., description="Peak NAV during period")  
    nav\_trough: Optional\[float\] \= Field(None, description="Trough NAV during period")  
    

# Attribution

#     income\_return: Optional\[float\] \= Field(None, description="Return from income (%)")

    capital\_return: Optional\[float\] \= Field(None, description="Return from capital gains (%)")  
      
    class Config:  
        json\_encoders \= {  
            datetime: lambda v: v.isoformat() if v else None  
        }

class BenchmarkComparison(BaseModel):  
    """Benchmark comparison analysis."""  
      
    cnpj: str \= Field(..., description="FIDC CNPJ")  
    benchmark\_type: str \= Field(..., description="Benchmark identifier")  
    period\_start: datetime \= Field(..., description="Comparison period start")  
    period\_end: datetime \= Field(..., description="Comparison period end")  
      
Returns

#     fidc\_return: float \= Field(..., description="FIDC annualized return (%)")

    benchmark\_return: float \= Field(..., description="Benchmark annualized return (%)")  
    excess\_return: float \= Field(..., description="Excess return vs benchmark (%)")  
    

# Risk-adjusted metrics

#     tracking\_error: float \= Field(..., description="Tracking error (%)")

    information\_ratio: float \= Field(..., description="Information ratio")  
    

# Regression metrics

#     beta: float \= Field(..., description="Beta to benchmark")

    alpha: float \= Field(..., description="Jensen's alpha (%)")  
    r\_squared: Optional\[float\] \= Field(None, description="R-squared")  
    correlation: float \= Field(..., description="Correlation to benchmark")  
    

# Relative performance

#     outperformance\_months: Optional\[int\] \= Field(None, description="Months of outperformance")

    underperformance\_months: Optional\[int\] \= Field(None, description="Months of underperformance")  
    outperformance\_ratio: float \= Field(..., description="Ratio of outperforming periods")  
      
    class Config:  
        json\_encoders \= {  
            datetime: lambda v: v.isoformat() if v else None  
        }

class PortfolioQualityMetrics(BaseModel):  
    """Portfolio quality and concentration metrics."""  
      
    cnpj: str \= Field(..., description="FIDC CNPJ")  
    reference\_date: datetime \= Field(..., description="Reference date for metrics")  
    

# Concentration metrics

#     concentration\_top5: float \= Field(

        ...,  
        ge=0.0,  
        le=100.0,  
        description="Concentration in top 5 assets (%)"  
    )  
    concentration\_top10: float \= Field(  
        ...,  
        ge=0.0,  
        le=100.0,  
        description="Concentration in top 10 assets (%)"  
    )  
    herfindahl\_index: float \= Field(  
        ...,  
        ge=0.0,  
        le=1.0,  
        description="Herfindahl-Hirschman Index"  
    )  
    

# Credit quality

#     delinquency\_ratio: float \= Field(

        ...,  
        ge=0.0,  
        description="Delinquency ratio (%)"  
    )  
    provision\_coverage: float \= Field(  
        ...,  
        ge=0.0,  
        description="Provision coverage ratio (%)"  
    )  
    avg\_credit\_rating: str \= Field(..., description="Average credit rating")  
    

# Diversification

#     number\_of\_assets: Optional\[int\] \= Field(None, description="Number of assets in portfolio")

    number\_of\_debtors: Optional\[int\] \= Field(None, description="Number of unique debtors")  
    sector\_diversification: Optional\[Dict\[str, float\]\] \= Field(  
        None,  
        description="Sector allocation (%)"  
    )  
    

# Turnover

#     portfolio\_turnover: float \= Field(

        default=0.0,  
        ge=0.0,  
        description="Portfolio turnover ratio"  
    )  
      
    class Config:  
        json\_encoders \= {  
            datetime: lambda v: v.isoformat() if v else None  
        }

class RiskMetrics(BaseModel):  
    """Comprehensive risk metrics."""  
      
    cnpj: str \= Field(..., description="FIDC CNPJ")  
    reference\_date: datetime \= Field(..., description="Reference date")  
    

# Duration and sensitivity

#     duration\_years: float \= Field(..., description="Macaulay duration (years)")

    modified\_duration: float \= Field(..., description="Modified duration")  
    convexity: float \= Field(..., description="Convexity")  
    

# Credit risk

#     credit\_spread\_bps: float \= Field(..., description="Credit spread (basis points)")

    probability\_of\_default: Optional\[float\] \= Field(  
        None,  
        ge=0.0,  
        le=1.0,  
        description="Estimated probability of default"  
    )  
    loss\_given\_default: Optional\[float\] \= Field(  
        None,  
        ge=0.0,  
        le=1.0,  
        description="Estimated loss given default"  
    )  
    

# Value at Risk

#     var\_95: float \= Field(..., description="Value at Risk 95% confidence (%)")

    var\_99: float \= Field(..., description="Value at Risk 99% confidence (%)")  
    expected\_shortfall: float \= Field(..., description="Expected shortfall / CVaR (%)")  
    

# Additional risk factors

#     concentration\_risk: float \= Field(

        ...,  
        description="Concentration risk measure (%)"  
    )  
    liquidity\_score: float \= Field(  
        ...,  
        ge=0.0,  
        le=1.0,  
        description="Liquidity score (0-1, higher is better)"  
    )  
    interest\_rate\_sensitivity: Optional\[float\] \= Field(  
        None,  
        description="Interest rate sensitivity"  
    )  
      
    class Config:  
        json\_encoders \= {  
            datetime: lambda v: v.isoformat() if v else None  
        }

class SectorAnalysis(BaseModel):  
    """Aggregate sector-level analysis."""  
      
    sector\_code: str \= Field(..., description="Sector identifier")  
    sector\_name: str \= Field(..., description="Sector name")  
    period\_start: datetime \= Field(..., description="Analysis period start")  
    period\_end: datetime \= Field(..., description="Analysis period end")  
    

# Market size

#     total\_funds: int \= Field(..., description="Number of FIDCs in sector")

    total\_aum: float \= Field(..., description="Total assets under management")  
    avg\_fund\_size: Optional\[float\] \= Field(None, description="Average fund size")  
    

# Performance

#     avg\_return: float \= Field(..., description="Average sector return (%)")

    median\_return: float \= Field(..., description="Median sector return (%)")  
    return\_std: float \= Field(..., description="Standard deviation of returns")  
    return\_range: Optional\[tuple\] \= Field(None, description="Return range (min, max)")  
    

# Rankings

#     top\_performers: List\[str\] \= Field(

        default\_factory=list,  
        description="CNPJs of top performing funds"  
    )  
    bottom\_performers: List\[str\] \= Field(  
        default\_factory=list,  
        description="CNPJs of bottom performing funds"  
    )  
    

# Concentration

#     concentration\_index: float \= Field(

        ...,  
        ge=0.0,  
        le=1.0,  
        description="Market concentration (Herfindahl index)"  
    )  
    market\_share\_top3: Optional\[float\] \= Field(  
        None,  
        description="Market share of top 3 funds (%)"  
    )  
      
Growth

#     sector\_growth\_rate: float \= Field(..., description="Sector growth rate (%)")

    net\_flows: Optional\[float\] \= Field(None, description="Net sector flows")  
    

# Quality metrics

#     avg\_delinquency: Optional\[float\] \= Field(None, description="Average delinquency ratio (%)")

    avg\_credit\_spread: Optional\[float\] \= Field(None, description="Average credit spread (bps)")  
      
    class Config:  
        json\_encoders \= {  
            datetime: lambda v: v.isoformat() if v else None  
        }

class AttributionAnalysis(BaseModel):  
    """Performance attribution analysis."""  
      
    cnpj: str \= Field(..., description="FIDC CNPJ")  
    period\_start: datetime \= Field(..., description="Attribution period start")  
    period\_end: datetime \= Field(..., description="Attribution period end")  
    

# Total performance

#     total\_return: float \= Field(..., description="Total return (%)")

    

# Attribution components

#     income\_effect: float \= Field(..., description="Return from income (%)")

    credit\_effect: float \= Field(..., description="Return from credit spread changes (%)")  
    duration\_effect: float \= Field(..., description="Return from duration positioning (%)")  
    selection\_effect: Optional\[float\] \= Field(  
        None,  
        description="Return from security selection (%)"  
    )  
    allocation\_effect: Optional\[float\] \= Field(  
        None,  
        description="Return from sector allocation (%)"  
    )  
    interaction\_effect: Optional\[float\] \= Field(  
        None,  
        description="Interaction effect (%)"  
    )  
    

# Residual

#     unexplained\_return: Optional\[float\] \= Field(

        None,  
        description="Unexplained return component (%)"  
    )  
    

# Contribution by asset class

#     asset\_class\_contribution: Optional\[Dict\[str, float\]\] \= Field(

        None,  
        description="Contribution by asset class"  
    )  
      
    class Config:  
        json\_encoders \= {  
            datetime: lambda v: v.isoformat() if v else None  
        }

class PeerComparison(BaseModel):  
    """Peer comparison analysis."""  
      
    cnpj: str \= Field(..., description="FIDC CNPJ")  
    peer\_group: str \= Field(..., description="Peer group identifier")  
    reference\_date: datetime \= Field(..., description="Comparison reference date")  
      
Ranking

#     peer\_count: int \= Field(..., description="Number of peers")

    return\_rank: int \= Field(..., description="Return ranking (1 is best)")  
    return\_percentile: float \= Field(  
        ...,  
        ge=0.0,  
        le=100.0,  
        description="Return percentile"  
    )  
    

# Performance comparison

#     fund\_return: float \= Field(..., description="Fund return (%)")

    peer\_avg\_return: float \= Field(..., description="Peer average return (%)")  
    peer\_median\_return: float \= Field(..., description="Peer median return (%)")  
    

# Risk comparison

#     fund\_volatility: float \= Field(..., description="Fund volatility (%)")

    peer\_avg\_volatility: float \= Field(..., description="Peer average volatility (%)")  
    

# Risk-adjusted comparison

#     fund\_sharpe: float \= Field(..., description="Fund Sharpe ratio")

    peer\_avg\_sharpe: float \= Field(..., description="Peer average Sharpe ratio")  
    sharpe\_rank: Optional\[int\] \= Field(None, description="Sharpe ratio ranking")  
    

# Quartile classification

#     performance\_quartile: int \= Field(

        ...,  
        ge=1,  
        le=4,  
        description="Performance quartile (1 is top)"  
    )  
      
    class Config:  
        json\_encoders \= {  
            datetime: lambda v: v.isoformat() if v else None  
        }

class DataQualityReport(BaseModel):  
    """Data quality assessment report."""  
      
    cnpj: str \= Field(..., description="FIDC CNPJ")  
    assessment\_date: datetime \= Field(  
        default\_factory=datetime.now,  
        description="Assessment date"  
    )  
    

# Overall score

#     overall\_score: float \= Field(

        ...,  
        ge=0.0,  
        le=1.0,  
        description="Overall data quality score"  
    )  
    

# Component scores

#     completeness\_score: float \= Field(

        ...,  
        ge=0.0,  
        le=1.0,  
        description="Data completeness"  
    )  
    consistency\_score: float \= Field(  
        ...,  
        ge=0.0,  
        le=1.0,  
        description="Data consistency"  
    )  
    timeliness\_score: float \= Field(  
        ...,  
        ge=0.0,  
        le=1.0,  
        description="Data timeliness"  
    )  
    accuracy\_score: Optional\[float\] \= Field(  
        None,  
        ge=0.0,  
        le=1.0,  
        description="Data accuracy"  
    )  
    

# Data availability

#     cvm\_cadastral\_available: bool \= Field(..., description="CVM cadastral data available")

    cvm\_monthly\_available: bool \= Field(..., description="CVM monthly data available")  
    anbima\_pricing\_available: bool \= Field(..., description="ANBIMA pricing available")  
    bacen\_context\_available: bool \= Field(..., description="BACEN context available")  
    

# Data coverage

#     months\_of\_data: int \= Field(..., description="Months of historical data")

    latest\_data\_date: Optional\[datetime\] \= Field(None, description="Latest available data date")  
    data\_gaps: List\[str\] \= Field(  
        default\_factory=list,  
        description="Identified data gaps"  
    )  
      
Issues

#     warnings: List\[str\] \= Field(

        default\_factory=list,  
        description="Data quality warnings"  
    )  
    errors: List\[str\] \= Field(  
        default\_factory=list,  
        description="Data quality errors"  
    )  
      
    class Config:  
        json\_encoders \= {  
            datetime: lambda v: v.isoformat() if v else None  
        }

class ExportMetadata(BaseModel):  
    """Metadata for exported datasets."""  
      
    export\_date: datetime \= Field(  
        default\_factory=datetime.now,  
        description="Export timestamp"  
    )  
    export\_format: str \= Field(..., description="Export format (parquet, csv, json)")  
    record\_count: int \= Field(..., description="Number of records exported")  
    

# Data scope

#     cnpjs\_included: List\[str\] \= Field(

        default\_factory=list,  
        description="CNPJs included in export"  
    )  
    period\_start: Optional\[datetime\] \= Field(None, description="Data period start")  
    period\_end: Optional\[datetime\] \= Field(None, description="Data period end")  
      
Schema

#     schema\_version: str \= Field(default="1.0", description="Data schema version")

    columns: List\[str\] \= Field(  
        default\_factory=list,  
        description="Column names"  
    )  
    

# Compression

#     compressed: bool \= Field(default=False, description="Whether data is compressed")

    compression\_type: Optional\[str\] \= Field(None, description="Compression algorithm")  
    

# File information

#     file\_size\_bytes: Optional\[int\] \= Field(None, description="File size in bytes")

    file\_path: str \= Field(..., description="Export file path")  
    

# Data lineage

#     source\_systems: List\[str\] \= Field(

        default\_factory=lambda: \["CVM", "ANBIMA", "BACEN"\],  
        description="Source systems"  
    )  
    processing\_steps: List\[str\] \= Field(  
        default\_factory=list,  
        description="Processing steps applied"  
    )  
      
    class Config:  
        json\_encoders \= {  
            datetime: lambda v: v.isoformat() if v else None  
        }  
\`\`\`

### integration\_layer.py

### \`\`\`python

import pandas as pd  
import numpy as np  
from pathlib import Path  
from typing import Optional, List, Dict, Any, Tuple  
from datetime import datetime, timedelta  
import logging  
from dataclasses import dataclass  
import pyarrow as pa  
import pyarrow.parquet as pq  
from integration\_models import (  
    IntegratedFidcData,  
    PerformanceMetrics,  
    SectorAnalysis,  
    BenchmarkComparison,  
    PortfolioQualityMetrics,  
    RiskMetrics,  
    AttributionAnalysis  
)

logging.basicConfig(level=logging.INFO)  
logger \= logging.getLogger(\_\_name\_\_)

class DataIntegrator:  
    """Production-grade data integration layer for Brazilian FIDC analysis."""  
      
    def \_\_init\_\_(self, data\_path: str \= "./data"):  
        """Initialize DataIntegrator with data directory path.  
          
        Args:  
            data\_path: Root directory containing all data sources  
        """  
        self.data\_path \= Path(data\_path)  
        self.cvm\_cadastral\_path \= self.data\_path / "cvm\_cadastral"  
        self.cvm\_monthly\_path \= self.data\_path / "cvm\_monthly"  
        self.anbima\_path \= self.data\_path / "anbima"  
        self.bacen\_path \= self.data\_path / "bacen"  
          
        self.\_cvm\_cadastral\_cache: Optional\[pd.DataFrame\] \= None  
        self.\_anbima\_cache: Optional\[pd.DataFrame\] \= None  
        self.\_bacen\_cache: Optional\[pd.DataFrame\] \= None  
          
        logger.info(f"DataIntegrator initialized with data path: {self.data\_path}")  
      
    def \_load\_cvm\_cadastral(self) \-\> pd.DataFrame:  
        """Load and cache CVM cadastral data."""  
        if self.\_cvm\_cadastral\_cache is not None:  
            return self.\_cvm\_cadastral\_cache  
          
        cadastral\_files \= list(self.cvm\_cadastral\_path.glob("\*.csv"))  
        if not cadastral\_files:  
            raise FileNotFoundError(f"No cadastral files found in {self.cvm\_cadastral\_path}")  
          
        dfs \= \[\]  
        for file in cadastral\_files:  
            try:  
                df \= pd.read\_csv(file, sep=";", encoding="latin1", low\_memory=False)  
                dfs.append(df)  
            except Exception as e:  
                logger.warning(f"Failed to load {file}: {e}")  
          
        if not dfs:  
            raise ValueError("No cadastral data could be loaded")  
          
        self.\_cvm\_cadastral\_cache \= pd.concat(dfs, ignore\_index=True)  
        self.\_cvm\_cadastral\_cache\['CNPJ\_FUNDO'\] \= self.\_cvm\_cadastral\_cache\['CNPJ\_FUNDO'\].str.replace('\[^0-9\]', '', regex=True)  
          
        logger.info(f"Loaded {len(self.\_cvm\_cadastral\_cache)} cadastral records")  
        return self.\_cvm\_cadastral\_cache  
      
    def \_load\_cvm\_monthly(self, cnpj: str, date\_range: Tuple\[datetime, datetime\]) \-\> pd.DataFrame:  
        """Load CVM monthly reports for specific FIDC and date range."""  
        start\_date, end\_date \= date\_range  
        monthly\_files \= list(self.cvm\_monthly\_path.glob("\*.csv"))  
          
        if not monthly\_files:  
            logger.warning(f"No monthly files found in {self.cvm\_monthly\_path}")  
            return pd.DataFrame()  
          
        dfs \= \[\]  
        for file in monthly\_files:  
            try:  
                df \= pd.read\_csv(file, sep=";", encoding="latin1", low\_memory=False)  
                if 'CNPJ\_FUNDO' in df.columns:  
                    df\['CNPJ\_FUNDO'\] \= df\['CNPJ\_FUNDO'\].str.replace('\[^0-9\]', '', regex=True)  
                    df \= df\[df\['CNPJ\_FUNDO'\] \== cnpj\]  
                      
                    if 'DT\_COMPTC' in df.columns:  
                        df\['DT\_COMPTC'\] \= pd.to\_datetime(df\['DT\_COMPTC'\], errors='coerce')  
                        df \= df\[(df\['DT\_COMPTC'\] \>= start\_date) & (df\['DT\_COMPTC'\] \<= end\_date)\]  
                      
                    if len(df) \> 0:  
                        dfs.append(df)  
            except Exception as e:  
                logger.warning(f"Failed to load monthly file {file}: {e}")  
          
        if not dfs:  
            logger.warning(f"No monthly data found for CNPJ {cnpj}")  
            return pd.DataFrame()  
          
        result \= pd.concat(dfs, ignore\_index=True)  
        logger.info(f"Loaded {len(result)} monthly records for CNPJ {cnpj}")  
        return result  
      
    def \_load\_anbima\_pricing(self) \-\> pd.DataFrame:  
        """Load and cache ANBIMA pricing data."""  
        if self.\_anbima\_cache is not None:  
            return self.\_anbima\_cache  
          
        anbima\_files \= list(self.anbima\_path.glob("\*.csv"))  
        if not anbima\_files:  
            logger.warning(f"No ANBIMA files found in {self.anbima\_path}")  
            return pd.DataFrame()  
          
        dfs \= \[\]  
        for file in anbima\_files:  
            try:  
                df \= pd.read\_csv(file, encoding="latin1", low\_memory=False)  
                if 'Data' in df.columns:  
                    df\['Data'\] \= pd.to\_datetime(df\['Data'\], errors='coerce')  
                if 'CNPJ' in df.columns:  
                    df\['CNPJ'\] \= df\['CNPJ'\].str.replace('\[^0-9\]', '', regex=True)  
                dfs.append(df)  
            except Exception as e:  
                logger.warning(f"Failed to load ANBIMA file {file}: {e}")  
          
        if not dfs:  
            logger.warning("No ANBIMA data could be loaded")  
            return pd.DataFrame()  
          
        self.\_anbima\_cache \= pd.concat(dfs, ignore\_index=True)  
        logger.info(f"Loaded {len(self.\_anbima\_cache)} ANBIMA pricing records")  
        return self.\_anbima\_cache  
      
    def \_load\_bacen\_credit(self) \-\> pd.DataFrame:  
        """Load and cache BACEN credit data."""  
        if self.\_bacen\_cache is not None:  
            return self.\_bacen\_cache  
          
        bacen\_files \= list(self.bacen\_path.glob("\*.csv"))  
        if not bacen\_files:  
            logger.warning(f"No BACEN files found in {self.bacen\_path}")  
            return pd.DataFrame()  
          
        dfs \= \[\]  
        for file in bacen\_files:  
            try:  
                df \= pd.read\_csv(file, encoding="latin1", low\_memory=False)  
                dfs.append(df)  
            except Exception as e:  
                logger.warning(f"Failed to load BACEN file {file}: {e}")  
          
        if not dfs:  
            logger.warning("No BACEN data could be loaded")  
            return pd.DataFrame()  
          
        self.\_bacen\_cache \= pd.concat(dfs, ignore\_index=True)  
        logger.info(f"Loaded {len(self.\_bacen\_cache)} BACEN credit records")  
        return self.\_bacen\_cache  
      
    def integrate\_fidc\_data(self, cnpj: str, date\_range: Tuple\[datetime, datetime\]) \-\> IntegratedFidcData:  
        """Integrate all data sources for a specific FIDC.  
          
        Args:  
            cnpj: FIDC CNPJ (cleaned, digits only)  
            date\_range: Tuple of (start\_date, end\_date)  
              
        Returns:  
            IntegratedFidcData model with all combined information  
        """  
        logger.info(f"Integrating data for CNPJ {cnpj} from {date\_range\[0\]} to {date\_range\[1\]}")  
        

# Clean CNPJ

#         cnpj\_clean \= ''.join(filter(str.isdigit, cnpj))

        

# Load all data sources

#         cadastral \= self.\_load\_cvm\_cadastral()

        monthly \= self.\_load\_cvm\_monthly(cnpj\_clean, date\_range)  
        anbima \= self.\_load\_anbima\_pricing()  
        bacen \= self.\_load\_bacen\_credit()  
        

# Get cadastral info

#         fund\_info \= cadastral\[cadastral\['CNPJ\_FUNDO'\] \== cnpj\_clean\]

        if fund\_info.empty:  
            raise ValueError(f"No cadastral information found for CNPJ {cnpj\_clean}")  
          
        fund\_info \= fund\_info.iloc\[0\]  
        

# Process monthly portfolio data

#         portfolio\_data \= self.\_process\_portfolio\_data(monthly)

        

# Get ANBIMA pricing for this FIDC

#         anbima\_data \= pd.DataFrame()

        if not anbima.empty and 'CNPJ' in anbima.columns:  
            anbima\_data \= anbima\[anbima\['CNPJ'\] \== cnpj\_clean\]  
            if not anbima\_data.empty:  
                anbima\_data \= anbima\_data.sort\_values('Data')  
        

# Extract sector from cadastral or monthly data

#         sector \= self.\_extract\_sector(fund\_info, monthly)

        

# Get BACEN sector context

#         sector\_context \= self.\_get\_sector\_context(bacen, sector)

        

# Build integrated model

#         return IntegratedFidcData(

            cnpj=cnpj\_clean,  
            fund\_name=str(fund\_info.get('DENOM\_SOCIAL', 'Unknown')),  
            fund\_type=str(fund\_info.get('TP\_FUNDO', 'FIDC')),  
            situation=str(fund\_info.get('SIT', 'Unknown')),  
            registration\_date=pd.to\_datetime(fund\_info.get('DT\_REG'), errors='coerce'),  
            start\_date=date\_range\[0\],  
            end\_date=date\_range\[1\],  
            portfolio\_composition=portfolio\_data,  
            anbima\_pricing=anbima\_data.to\_dict('records') if not anbima\_data.empty else \[\],  
            sector\_code=sector,  
            sector\_context=sector\_context,  
            data\_quality\_score=self.\_calculate\_data\_quality(monthly, anbima\_data),  
            last\_update=datetime.now()  
        )  
      
    def \_process\_portfolio\_data(self, monthly\_df: pd.DataFrame) \-\> Dict\[str, Any\]:  
        """Process monthly portfolio composition data."""  
        if monthly\_df.empty:  
            return {}  
          
        portfolio \= {  
            'total\_records': len(monthly\_df),  
            'dates\_available': sorted(monthly\_df\['DT\_COMPTC'\].dropna().unique().tolist()) if 'DT\_COMPTC' in monthly\_df.columns else \[\],  
        }  
        

# Calculate portfolio metrics if NAV data available

#         if 'VL\_PATRIM\_LIQ' in monthly\_df.columns:

            portfolio\['nav\_series'\] \= monthly\_df.groupby('DT\_COMPTC')\['VL\_PATRIM\_LIQ'\].last().to\_dict()  
        

# Asset composition if available

#         if 'TP\_ATIVO' in monthly\_df.columns:

            portfolio\['asset\_types'\] \= monthly\_df\['TP\_ATIVO'\].value\_counts().to\_dict()  
          
        return portfolio  
      
    def \_extract\_sector(self, fund\_info: pd.Series, monthly\_df: pd.DataFrame) \-\> str:  
        """Extract sector information from available data."""

# Try to extract from cadastral

#         if 'CLASSE' in fund\_info.index and pd.notna(fund\_info\['CLASSE'\]):

            return str(fund\_info\['CLASSE'\])  
        

# Try to extract from monthly data

#         if not monthly\_df.empty and 'SETOR\_ATIV' in monthly\_df.columns:

            sectors \= monthly\_df\['SETOR\_ATIV'\].value\_counts()  
            if not sectors.empty:  
                return str(sectors.index\[0\])  
          
        return 'Unknown'  
      
    def \_get\_sector\_context(self, bacen\_df: pd.DataFrame, sector: str) \-\> Dict\[str, Any\]:  
        """Get BACEN sector-level context data."""  
        if bacen\_df.empty:  
            return {}  
        

# Filter by sector if sector column exists

#         sector\_data \= bacen\_df

        if 'Setor' in bacen\_df.columns:  
            sector\_data \= bacen\_df\[bacen\_df\['Setor'\].str.contains(sector, case=False, na=False)\]  
          
        if sector\_data.empty:  
            return {'sector': sector, 'records': 0}  
          
        context \= {  
            'sector': sector,  
            'records': len(sector\_data),  
            'latest\_date': sector\_data\['Data'\].max() if 'Data' in sector\_data.columns else None  
        }  
        

# Add aggregate metrics if available

#         numeric\_cols \= sector\_data.select\_dtypes(include=\[np.number\]).columns

        for col in numeric\_cols:  
            context\[f'{col}\_mean'\] \= float(sector\_data\[col\].mean())  
          
        return context  
      
    def \_calculate\_data\_quality(self, monthly\_df: pd.DataFrame, anbima\_df: pd.DataFrame) \-\> float:  
        """Calculate data quality score (0-1)."""  
        score \= 0.0  
        

# Monthly data availability (40%)

#         if not monthly\_df.empty:

            score \+= 0.4 \* min(len(monthly\_df) / 12, 1.0)  \# Expect at least 12 months  
        

# ANBIMA pricing availability (30%)

#         if not anbima\_df.empty:

            score \+= 0.3  
        

# Data completeness (30%)

#         if not monthly\_df.empty:

            completeness \= 1.0 \- monthly\_df.isnull().sum().sum() / (monthly\_df.shape\[0\] \* monthly\_df.shape\[1\])  
            score \+= 0.3 \* completeness  
          
        return round(score, 3\)  
      
    def get\_fidc\_performance\_metrics(self, cnpj: str, date\_range: Optional\[Tuple\[datetime, datetime\]\] \= None) \-\> PerformanceMetrics:  
        """Calculate comprehensive performance metrics for a FIDC.  
          
        Args:  
            cnpj: FIDC CNPJ  
            date\_range: Optional date range, defaults to last 12 months  
              
        Returns:  
            PerformanceMetrics model  
        """  
        if date\_range is None:  
            end\_date \= datetime.now()  
            start\_date \= end\_date \- timedelta(days=365)  
            date\_range \= (start\_date, end\_date)  
          
        integrated\_data \= self.integrate\_fidc\_data(cnpj, date\_range)  
        monthly \= self.\_load\_cvm\_monthly(integrated\_data.cnpj, date\_range)  
          
        if monthly.empty or 'VL\_PATRIM\_LIQ' not in monthly.columns:  
            logger.warning(f"Insufficient data for performance calculation: {cnpj}")  
            return PerformanceMetrics(  
                cnpj=integrated\_data.cnpj,  
                period\_start=date\_range\[0\],  
                period\_end=date\_range\[1\],  
                total\_return=0.0,  
                annualized\_return=0.0,  
                volatility=0.0,  
                sharpe\_ratio=0.0,  
                max\_drawdown=0.0,  
                nav\_start=0.0,  
                nav\_end=0.0,  
                nav\_peak=0.0,  
                monthly\_returns=\[\],  
                cumulative\_returns=\[\]  
            )  
        

# Sort by date

#         monthly \= monthly.sort\_values('DT\_COMPTC')

        nav\_series \= monthly.groupby('DT\_COMPTC')\['VL\_PATRIM\_LIQ'\].last()  
        

# Calculate returns

#         returns \= nav\_series.pct\_change().dropna()

        monthly\_returns\_list \= returns.tolist()  
        

# Calculate metrics

#         total\_return \= (nav\_series.iloc\[-1\] / nav\_series.iloc\[0\] \- 1\) \* 100 if len(nav\_series) \> 1 else 0.0

        

# Annualized return

#         years \= (date\_range\[1\] \- date\_range\[0\]).days / 365.25

        annualized\_return \= ((1 \+ total\_return/100)  (1/year**s) \- 1\) \* 100 if years \> 0 else 0.0**  
        

# Volatility (annualized)

#         volatility \= returns.std() \* np.sqrt(12) \* 100 if len(returns) \> 1 else 0.0

        

# Sharpe ratio (assuming risk-free rate of 0 for simplicity)

#         sharpe \= (annualized\_return / volatility) if volatility \> 0 else 0.0

        

# Max drawdown

#         cumulative \= (1 \+ returns).cumprod()

        running\_max \= cumulative.expanding().max()  
        drawdown \= (cumulative \- running\_max) / running\_max  
        max\_drawdown \= drawdown.min() \* 100  
        

# Cumulative returns

#         cumulative\_returns\_list \= ((cumulative \- 1\) \* 100).tolist()

          
        return PerformanceMetrics(  
            cnpj=integrated\_data.cnpj,  
            period\_start=date\_range\[0\],  
            period\_end=date\_range\[1\],  
            total\_return=round(total\_return, 2),  
            annualized\_return=round(annualized\_return, 2),  
            volatility=round(volatility, 2),  
            sharpe\_ratio=round(sharpe, 3),  
            max\_drawdown=round(max\_drawdown, 2),  
            nav\_start=float(nav\_series.iloc\[0\]),  
            nav\_end=float(nav\_series.iloc\[-1\]),  
            nav\_peak=float(nav\_series.max()),  
            monthly\_returns=monthly\_returns\_list,  
            cumulative\_returns=cumulative\_returns\_list  
        )  
      
    def compare\_fidc\_to\_benchmark(self, cnpj: str, benchmark\_type: str \= 'CDI',   
                                  date\_range: Optional\[Tuple\[datetime, datetime\]\] \= None) \-\> BenchmarkComparison:  
        """Compare FIDC performance to benchmark.  
          
        Args:  
            cnpj: FIDC CNPJ  
            benchmark\_type: 'CDI', 'IPCA', 'SECTOR' or 'CUSTOM'  
            date\_range: Optional date range  
              
        Returns:  
            BenchmarkComparison model  
        """  
        if date\_range is None:  
            end\_date \= datetime.now()  
            start\_date \= end\_date \- timedelta(days=365)  
            date\_range \= (start\_date, end\_date)  
        

# Get FIDC performance

#         fidc\_performance \= self.get\_fidc\_performance\_metrics(cnpj, date\_range)

        

# Simulate benchmark returns (in production, load from actual data)

#         benchmark\_return \= self.\_get\_benchmark\_return(benchmark\_type, date\_range)

        

# Calculate excess return and tracking error

#         excess\_return \= fidc\_performance.annualized\_return \- benchmark\_return

        

# Information ratio (simplified)

#         information\_ratio \= excess\_return / fidc\_performance.volatility if fidc\_performance.volatility \> 0 else 0.0

        

# Beta and alpha (simplified, assuming benchmark volatility)

#         benchmark\_volatility \= 3.0 if benchmark\_type \== 'CDI' else 5.0

        beta \= fidc\_performance.volatility / benchmark\_volatility if benchmark\_volatility \> 0 else 1.0  
        alpha \= fidc\_performance.annualized\_return \- (benchmark\_return \* beta)  
          
        return BenchmarkComparison(  
            cnpj=cnpj,  
            benchmark\_type=benchmark\_type,  
            period\_start=date\_range\[0\],  
            period\_end=date\_range\[1\],  
            fidc\_return=fidc\_performance.annualized\_return,  
            benchmark\_return=round(benchmark\_return, 2),  
            excess\_return=round(excess\_return, 2),  
            tracking\_error=round(fidc\_performance.volatility, 2),  
            information\_ratio=round(information\_ratio, 3),  
            beta=round(beta, 3),  
            alpha=round(alpha, 2),  
            correlation=0.85,  \# Simplified  
            outperformance\_ratio=1.0 if excess\_return \> 0 else 0.0  
        )  
      
    def \_get\_benchmark\_return(self, benchmark\_type: str, date\_range: Tuple\[datetime, datetime\]) \-\> float:  
        """Get benchmark return for period (simplified implementation)."""  
        years \= (date\_range\[1\] \- date\_range\[0\]).days / 365.25  
        

# Simplified benchmark returns

#         annual\_rates \= {

            'CDI': 13.65,  
            'IPCA': 4.50,  
            'SECTOR': 15.20,  
            'CUSTOM': 12.00  
        }  
          
        return annual\_rates.get(benchmark\_type, 13.65)  
      
    def get\_sector\_analysis(self, sector\_code: str, date\_range: Optional\[Tuple\[datetime, datetime\]\] \= None) \-\> SectorAnalysis:  
        """Perform aggregate analysis for FIDCs in a sector.  
          
        Args:  
            sector\_code: Sector identifier  
            date\_range: Optional date range  
              
        Returns:  
            SectorAnalysis model  
        """  
        if date\_range is None:  
            end\_date \= datetime.now()  
            start\_date \= end\_date \- timedelta(days=365)  
            date\_range \= (start\_date, end\_date)  
          
        logger.info(f"Analyzing sector {sector\_code} from {date\_range\[0\]} to {date\_range\[1\]}")  
        

# Load cadastral to find FIDCs in sector

#         cadastral \= self.\_load\_cvm\_cadastral()

        

# Filter by sector

#         sector\_funds \= cadastral\[

            (cadastral\['CLASSE'\].str.contains(sector\_code, case=False, na=False)) |  
            (cadastral\['TP\_FUNDO'\].str.contains(sector\_code, case=False, na=False))  
        \]  
          
        if sector\_funds.empty:  
            logger.warning(f"No funds found for sector {sector\_code}")  
            return SectorAnalysis(  
                sector\_code=sector\_code,  
                sector\_name=sector\_code,  
                period\_start=date\_range\[0\],  
                period\_end=date\_range\[1\],  
                total\_funds=0,  
                total\_aum=0.0,  
                avg\_return=0.0,  
                median\_return=0.0,  
                return\_std=0.0,  
                top\_performers=\[\],  
                bottom\_performers=\[\],  
                concentration\_index=0.0,  
                sector\_growth\_rate=0.0  
            )  
        

# Calculate metrics for available funds

#         fund\_cnpjs \= sector\_funds\['CNPJ\_FUNDO'\].unique()\[:10\]  \# Limit for performance

          
        fund\_metrics \= \[\]  
        total\_aum \= 0.0  
          
        for cnpj in fund\_cnpjs:  
            try:  
                monthly \= self.\_load\_cvm\_monthly(cnpj, date\_range)  
                if not monthly.empty and 'VL\_PATRIM\_LIQ' in monthly.columns:  
                    nav\_series \= monthly.groupby('DT\_COMPTC')\['VL\_PATRIM\_LIQ'\].last()  
                    if len(nav\_series) \> 1:  
                        fund\_return \= (nav\_series.iloc\[-1\] / nav\_series.iloc\[0\] \- 1\) \* 100  
                        fund\_aum \= nav\_series.iloc\[-1\]  
                        fund\_metrics.append({  
                            'cnpj': cnpj,  
                            'return': fund\_return,  
                            'aum': fund\_aum  
                        })  
                        total\_aum \+= fund\_aum  
            except Exception as e:  
                logger.warning(f"Failed to process fund {cnpj}: {e}")  
                continue  
          
        if not fund\_metrics:  
            return SectorAnalysis(  
                sector\_code=sector\_code,  
                sector\_name=sector\_code,  
                period\_start=date\_range\[0\],  
                period\_end=date\_range\[1\],  
                total\_funds=len(sector\_funds),  
                total\_aum=0.0,  
                avg\_return=0.0,  
                median\_return=0.0,  
                return\_std=0.0,  
                top\_performers=\[\],  
                bottom\_performers=\[\],  
                concentration\_index=0.0,  
                sector\_growth\_rate=0.0  
            )  
          
        returns \= \[m\['return'\] for m in fund\_metrics\]  
        avg\_return \= np.mean(returns)  
        median\_return \= np.median(returns)  
        return\_std \= np.std(returns)  
        

# Top and bottom performers

#         sorted\_metrics \= sorted(fund\_metrics, key=lambda x: x\['return'\], reverse=True)

        top\_performers \= \[m\['cnpj'\] for m in sorted\_metrics\[:5\]\]  
        bottom\_performers \= \[m\['cnpj'\] for m in sorted\_metrics\[-5:\]\]  
        

# Concentration index (Herfindahl)

#         aums \= \[m\['aum'\] for m in fund\_metrics\]

        market\_shares \= np.array(aums) / total\_aum if total\_aum \> 0 else np.zeros(len(aums))  
        concentration\_index \= np.sum(market\_shares  2\)  
          
        return SectorAnalysis(  
            sector\_code=sector\_code,  
            sector\_name=sector\_code,  
            period\_start=date\_range\[0\],  
            period\_end=date\_range\[1\],  
            total\_funds=len(sector\_funds),  
            total\_aum=float(total\_aum),  
            avg\_return=round(avg\_return, 2),  
            median\_return=round(median\_return, 2),  
            return\_std=round(return\_std, 2),  
            top\_performers=top\_performers,  
            bottom\_performers=bottom\_performers,  
            concentration\_index=round(concentration\_index, 4),  
            sector\_growth\_rate=round(avg\_return, 2\)  
        )  
      
    def calculate\_portfolio\_quality\_metrics(self, cnpj: str, date\_range: Tuple\[datetime, datetime\]) \-\> PortfolioQualityMetrics:  
        """Calculate portfolio quality metrics including concentration and delinquency."""  
        monthly \= self.\_load\_cvm\_monthly(cnpj, date\_range)  
          
        if monthly.empty:  
            return PortfolioQualityMetrics(  
                cnpj=cnpj,  
                reference\_date=date\_range\[1\],  
                concentration\_top5=0.0,  
                concentration\_top10=0.0,  
                herfindahl\_index=0.0,  
                delinquency\_ratio=0.0,  
                provision\_coverage=0.0,  
                avg\_credit\_rating='N/A',  
                portfolio\_turnover=0.0  
            )  
        

# Get latest portfolio composition

#         latest\_date \= monthly\['DT\_COMPTC'\].max()

        latest\_portfolio \= monthly\[monthly\['DT\_COMPTC'\] \== latest\_date\]  
        

# Calculate concentration if asset values available

#         concentration\_top5 \= 0.0

        concentration\_top10 \= 0.0  
        herfindahl\_index \= 0.0  
          
        if 'VL\_MERC\_POS\_FINAL' in latest\_portfolio.columns:  
            asset\_values \= latest\_portfolio\['VL\_MERC\_POS\_FINAL'\].dropna().sort\_values(ascending=False)  
            total\_value \= asset\_values.sum()  
              
            if total\_value \> 0:  
                concentration\_top5 \= asset\_values.head(5).sum() / total\_value \* 100  
                concentration\_top10 \= asset\_values.head(10).sum() / total\_value \* 100  
                

# Herfindahl index

#                 shares \= asset\_values / total\_value

                herfindahl\_index \= (shares  2).sum(**)**  
        

# Delinquency metrics (if available)

#         delinquency\_ratio \= 0.0

        if 'PERC\_INADIMPLENCIA' in monthly.columns:  
            delinquency\_ratio \= monthly\['PERC\_INADIMPLENCIA'\].iloc\[-1\] if len(monthly) \> 0 else 0.0  
          
        return PortfolioQualityMetrics(  
            cnpj=cnpj,  
            reference\_date=latest\_date,  
            concentration\_top5=round(concentration\_top5, 2),  
            concentration\_top10=round(concentration\_top10, 2),  
            herfindahl\_index=round(herfindahl\_index, 4),  
            delinquency\_ratio=round(delinquency\_ratio, 2),  
            provision\_coverage=0.0,  \# Would need specific data  
            avg\_credit\_rating='N/A',  
            portfolio\_turnover=0.0  \# Would need historical comparison  
        )  
      
    def calculate\_risk\_metrics(self, cnpj: str, date\_range: Tuple\[datetime, datetime\]) \-\> RiskMetrics:  
        """Calculate comprehensive risk metrics."""  
        performance \= self.get\_fidc\_performance\_metrics(cnpj, date\_range)  
        portfolio\_quality \= self.calculate\_portfolio\_quality\_metrics(cnpj, date\_range)  
        

# Calculate Value at Risk (simplified parametric approach)

#         if performance.volatility \> 0:

            var\_95 \= 1.645 \* performance.volatility  \# 95% confidence  
            var\_99 \= 2.326 \* performance.volatility  \# 99% confidence  
        else:  
            var\_95 \= 0.0  
            var\_99 \= 0.0  
        

# Duration (simplified)

#         duration\_years \= 2.5  \# Placeholder

        

# Credit spread (placeholder)

#         credit\_spread\_bps \= 450.0

          
        return RiskMetrics(  
            cnpj=cnpj,  
            reference\_date=date\_range\[1\],  
            duration\_years=duration\_years,  
            modified\_duration=duration\_years \* 0.95,  
            convexity=0.5,  
            credit\_spread\_bps=credit\_spread\_bps,  
            var\_95=round(var\_95, 2),  
            var\_99=round(var\_99, 2),  
            expected\_shortfall=round(var\_99 \* 1.2, 2),  
            concentration\_risk=portfolio\_quality.concentration\_top5,  
            liquidity\_score=0.7  
        )  
      
    def export\_to\_parquet(self, data: Any, path: str, partition\_cols: Optional\[List\[str\]\] \= None) \-\> None:  
        """Export data to Parquet format with optional partitioning.  
          
        Args:  
            data: Data to export (DataFrame, Pydantic model, or dict)  
            path: Output file path  
            partition\_cols: Optional columns to partition by  
        """  
        output\_path \= Path(path)  
        output\_path.parent.mkdir(parents=True, exist\_ok=True)  
        

# Convert to DataFrame if needed

#         if isinstance(data, pd.DataFrame):

            df \= data  
        elif hasattr(data, 'dict'):

# Pydantic model

#             df \= pd.DataFrame(\[data.dict()\])

        elif isinstance(data, dict):  
            df \= pd.DataFrame(\[data\])  
        elif isinstance(data, list):  
            if len(data) \> 0 and hasattr(data\[0\], 'dict'):  
                df \= pd.DataFrame(\[item.dict() for item in data\])  
            else:  
                df \= pd.DataFrame(data)  
        else:  
            raise ValueError(f"Unsupported data type: {type(data)}")  
        

# Convert datetime columns

#         for col in df.select\_dtypes(include=\['datetime64'\]).columns:

            df\[col\] \= pd.to\_datetime(df\[col\])  
        

# Write to parquet

#         if partition\_cols:

            df.to\_parquet(output\_path, partition\_cols=partition\_cols, engine='pyarrow', compression='snappy')  
        else:  
            df.to\_parquet(output\_path, engine='pyarrow', compression='snappy')  
          
        logger.info(f"Exported {len(df)} records to {output\_path}")  
      
    def export\_integrated\_dataset(self, cnpjs: List\[str\], output\_dir: str,   
                                 date\_range: Optional\[Tuple\[datetime, datetime\]\] \= None) \-\> None:  
        """Export integrated dataset for multiple FIDCs to Parquet."""  
        if date\_range is None:  
            end\_date \= datetime.now()  
            start\_date \= end\_date \- timedelta(days=365)  
            date\_range \= (start\_date, end\_date)  
          
        output\_path \= Path(output\_dir)  
        output\_path.mkdir(parents=True, exist\_ok=True)  
          
        all\_data \= \[\]  
          
        for cnpj in cnpjs:  
            try:  
                integrated \= self.integrate\_fidc\_data(cnpj, date\_range)  
                performance \= self.get\_fidc\_performance\_metrics(cnpj, date\_range)  
                quality \= self.calculate\_portfolio\_quality\_metrics(cnpj, date\_range)  
                risk \= self.calculate\_risk\_metrics(cnpj, date\_range)  
                  
                record \= {  
                    integrat**ed.dict(),**  
                    'performance': performance.dict(),  
                    'quality': quality.dict(),  
                    'risk': risk.dict()  
                }  
                all\_data.append(record)  
                  
            except Exception as e:  
                logger.error(f"Failed to process CNPJ {cnpj}: {e}")  
                continue  
          
        if all\_data:  
            df \= pd.json\_normalize(all\_data)  
            self.export\_to\_parquet(df, str(output\_path / 'integrated\_fidc\_data.parquet'))  
            logger.info(f"Exported integrated dataset with {len(all\_data)} FIDCs to {output\_path}")  
        else:  
            logger.warning("No data to export")

def main():  
    """CLI entry point."""  
    import argparse  
      
    parser \= argparse.ArgumentParser(description='FIDC Data Integration Tool')  
    parser.add\_argument('--data-path', default='./data', help='Root data directory')  
    parser.add\_argument('--cnpj', help='FIDC CNPJ to analyze')  
    parser.add\_argument('--sector', help='Sector code for analysis')  
    parser.add\_argument('--start-date', help='Start date (YYYY-MM-DD)')  
    parser.add\_argument('--end-date', help='End date (YYYY-MM-DD)')  
    parser.add\_argument('--output', default='./output', help='Output directory')  
    parser.add\_argument('--benchmark', default='CDI', choices=\['CDI', 'IPCA', 'SECTOR', 'CUSTOM'\])  
    parser.add\_argument('--export-format', default='parquet', choices=\['parquet', 'json', 'csv'\])  
      
    args \= parser.parse\_args()  
    

# Parse dates

#     if args.start\_date:

        start\_date \= datetime.strptime(args.start\_date, '%Y-%m-%d')  
    else:  
        start\_date \= datetime.now() \- timedelta(days=365)  
      
    if args.end\_date:  
        end\_date \= datetime.strptime(args.end\_date, '%Y-%m-%d')  
    else:  
        end\_date \= datetime.now()  
      
    date\_range \= (start\_date, end\_date)  
    

# Initialize integrator

#     integrator \= DataIntegrator(args.data\_path)

    

# Execute requested analysis

#     if args.cnpj:

        logger.info(f"Analyzing FIDC {args.cnpj}")  
        

# Integrate data

#         integrated \= integrator.integrate\_fidc\_data(args.cnpj, date\_range)

        logger.info(f"Integrated data for {integrated.fund\_name}")  
        

# Performance metrics

#         performance \= integrator.get\_fidc\_performance\_metrics(args.cnpj, date\_range)

        logger.info(f"Total return: {performance.total\_return:.2f}%")  
        logger.info(f"Annualized return: {performance.annualized\_return:.2f}%")  
        logger.info(f"Sharpe ratio: {performance.sharpe\_ratio:.3f}")  
        

# Benchmark comparison

#         comparison \= integrator.compare\_fidc\_to\_benchmark(args.cnpj, args.benchmark, date\_range)

        logger.info(f"Excess return vs {args.benchmark}: {comparison.excess\_return:.2f}%")  
        

# Quality metrics

#         quality \= integrator.calculate\_portfolio\_quality\_metrics(args.cnpj, date\_range)

        logger.info(f"Top 5 concentration: {quality.concentration\_top5:.2f}%")  
        

# Risk metrics

#         risk \= integrator.calculate\_risk\_metrics(args.cnpj, date\_range)

        logger.info(f"VaR 95%: {risk.var\_95:.2f}%")  
        

# Export results

#         output\_path \= Path(args.output)

        output\_path.mkdir(parents=True, exist\_ok=True)  
          
        integrator.export\_to\_parquet(integrated, str(output\_path / f"{args.cnpj}\_integrated.parquet"))  
        integrator.export\_to\_parquet(performance, str(output\_path / f"{args.cnpj}\_performance.parquet"))  
        integrator.export\_to\_parquet(comparison, str(output\_path / f"{args.cnpj}\_benchmark.parquet"))  
        integrator.export\_to\_parquet(quality, str(output\_path / f"{args.cnpj}\_quality.parquet"))  
        integrator.export\_to\_parquet(risk, str(output\_path / f"{args.cnpj}\_risk.parquet"))  
          
        logger.info(f"Results exported to {output\_path}")  
      
    elif args.sector:  
        logger.info(f"Analyzing sector {args.sector}")  
          
        sector\_analysis \= integrator.get\_sector\_analysis(args.sector, date\_range)  
        logger.info(f"Total funds: {sector\_analysis.total\_funds}")  
        logger.info(f"Total AUM: R$ {sector\_analysis.total\_aum:,.2f}")  
        logger.info(f"Average return: {sector\_analysis.avg\_return:.2f}%")  
        logger.info(f"Median return: {sector\_analysis.median\_return:.2f}%")  
          
        output\_path \= Path(args.output)  
        output\_path.mkdir(parents=True, exist\_ok=True)  
        integrator.export\_to\_parquet(sector\_analysis, str(output\_path / f"{args.sector}\_analysis.parquet"))  
          
        logger.info(f"Sector analysis exported to {output\_path}")  
      
    else:  
        logger.error("Please specify either \--cnpj or \--sector")  
        parser.print\_help()

if \_\_name\_\_ \== '\_\_main\_\_':  
    main()  
\`\`\`

### requirements.txt

### \`\`\`

# Core dependencies

# aiohttp==3.9.1

aiofiles==23.2.1  
python-dotenv==1.0.0

# Data processing

# pandas==2.1.4

numpy==1.26.2

# Authentication and security

# pyjwt==2.8.0

cryptography==41.0.7

# HTTP and networking

# requests==2.31.0

httpx==0.25.2  
tenacity==8.2.3

Caching

# cachetools==5.3.2

redis==5.0.1  \# Optional: for distributed caching

# Date and time handling

# python-dateutil==2.8.2

pytz==2023.3

# Logging and monitoring

# structlog==23.2.0

python-json-logger==2.0.7

# Data validation

# pydantic==2.5.3

jsonschema==4.20.0

# Rate limiting

# aiolimiter==1.1.0

ratelimit==2.2.1

# Testing (optional, for development)

# pytest==7.4.3

pytest-asyncio==0.21.1  
pytest-cov==4.1.0  
pytest-mock==3.12.0

# Development tools (optional)

# black==23.12.1

flake8==6.1.0  
mypy==1.7.1  
ipython==8.18.1

# Documentation (optional)

# sphinx==7.2.6

sphinx-rtd-theme==2.0.0

# Performance monitoring (optional)

# py-spy==0.3.14

memory-profiler==0.61.0

# Async utilities

# aiodns==3.1.1

cchardet==2.1.7

# Excel export (optional)

# openpyxl==3.1.2

xlsxwriter==3.1.9

# Environment and configuration

# python-decouple==3.8

# Retry and circuit breaker

# circuitbreaker==2.0.0

# Compression

# zstandard==0.22.0

# XML parsing (for BACEN data)

# lxml==4.9.4

# API rate limiting

# slowapi==0.1.9

# HTTP session management

# requests-cache==1.1.1

# Async database support (optional)

# aiosqlite==0.19.0

asyncpg==0.29.0  \# For PostgreSQL

# Metrics and observability (optional)

# prometheus-client==0.19.0

opentelemetry-api==1.21.0  
opentelemetry-sdk==1.21.0

# Data serialization

# orjson==3.9.10

msgpack==1.0.7

# Timezone data

# tzdata==2023.3

\`\`\`

### example\_usage.py

### \`\`\`python

\#\!/usr/bin/env python3  
"""  
Comprehensive example usage of ANBIMA, BACEN, and Data Integration modules.

This script demonstrates:  
1\. Authenticating with ANBIMA API  
2\. Fetching CRI/CRA data from ANBIMA  
3\. Fetching SELIC rates from BACEN  
4\. Fetching credit operations data from BACEN  
5\. Integrating CVM \+ ANBIMA \+ BACEN data for FIDC analysis  
"""

import asyncio  
import logging  
from datetime import datetime, timedelta  
from pathlib import Path  
import json  
import os  
from dotenv import load\_dotenv

# Import our modules

# from anbima\_client import ANBIMAClient

from bacen\_client import BACENClient  
from data\_integration import DataIntegrator, FIDCAnalyzer

# Load environment variables

# load\_dotenv()

# Configure logging

# logging.basicConfig(

    level=logging.INFO,  
    format='%(asctime)s \- %(name)s \- %(levelname)s \- %(message)s',  
    handlers=\[  
        logging.StreamHandler(),  
        logging.FileHandler('example\_usage.log')  
    \]  
)  
logger \= logging.getLogger(\_\_name\_\_)

def save\_results(data: dict, filename: str):  
    """Save results to JSON file for inspection."""  
    output\_dir \= Path('output')  
    output\_dir.mkdir(exist\_ok=True)  
      
    filepath \= output\_dir / filename  
    with open(filepath, 'w', encoding='utf-8') as f:  
        json.dump(data, f, indent=2, ensure\_ascii=False, default=str)  
      
    logger.info(f"Results saved to {filepath}")

async def example\_anbima\_authentication():  
    """Example 1: Authenticate with ANBIMA API."""  
    logger.info("\\n" \+ "="\*80)  
    logger.info("Example 1: ANBIMA Authentication")  
    logger.info("="\*80)  
      
    client\_id \= os.getenv('ANBIMA\_CLIENT\_ID')  
    client\_secret \= os.getenv('ANBIMA\_CLIENT\_SECRET')  
      
    if not client\_id or not client\_secret:  
        logger.error("ANBIMA credentials not found in environment variables")  
        logger.info("Please set ANBIMA\_CLIENT\_ID and ANBIMA\_CLIENT\_SECRET in .env file")  
        return None  
      
    async with ANBIMAClient(  
        client\_id=client\_id,  
        client\_secret=client\_secret  
    ) as client:

# Test authentication

#         is\_authenticated \= await client.authenticate()

          
        if is\_authenticated:  
            logger.info("✓ Successfully authenticated with ANBIMA API")  
            logger.info(f"Access token obtained (expires in \~1 hour)")  
            return client  
        else:  
            logger.error("✗ Failed to authenticate with ANBIMA API")  
            return None

async def example\_anbima\_cri\_data():  
    """Example 2: Fetch CRI data from ANBIMA."""  
    logger.info("\\n" \+ "="\*80)  
    logger.info("Example 2: Fetching CRI Data from ANBIMA")  
    logger.info("="\*80)  
      
    client\_id \= os.getenv('ANBIMA\_CLIENT\_ID')  
    client\_secret \= os.getenv('ANBIMA\_CLIENT\_SECRET')  
      
    if not client\_id or not client\_secret:  
        logger.warning("Skipping ANBIMA examples \- credentials not configured")  
        return  
      
    async with ANBIMAClient(  
        client\_id=client\_id,  
        client\_secret=client\_secret  
    ) as client:

# Define date range (last 30 days)

#         end\_date \= datetime.now()

        start\_date \= end\_date \- timedelta(days=30)  
          
        logger.info(f"Fetching CRI data from {start\_date.date()} to {end\_date.date()}")  
        

# Fetch CRI data

#         cri\_data \= await client.get\_cri\_data(

            start\_date=start\_date,  
            end\_date=end\_date,  
            issuer=None  \# Get all issuers  
        )  
          
        if cri\_data:  
            logger.info(f"✓ Retrieved {len(cri\_data)} CRI records")  
            

# Display sample data

#             if len(cri\_data) \> 0:

                logger.info("\\nSample CRI record:")  
                sample \= cri\_data\[0\]  
                for key, value in list(sample.items())\[:5\]:  
                    logger.info(f"  {key}: {value}")  
              
Save results

#             save\_results({'cri\_data': cri\_data}, 'anbima\_cri\_data.json')

            return cri\_data  
        else:  
            logger.warning("No CRI data retrieved")  
            return \[\]

async def example\_anbima\_cra\_data():  
    """Example 3: Fetch CRA data from ANBIMA."""  
    logger.info("\\n" \+ "="\*80)  
    logger.info("Example 3: Fetching CRA Data from ANBIMA")  
    logger.info("="\*80)  
      
    client\_id \= os.getenv('ANBIMA\_CLIENT\_ID')  
    client\_secret \= os.getenv('ANBIMA\_CLIENT\_SECRET')  
      
    if not client\_id or not client\_secret:  
        logger.warning("Skipping ANBIMA examples \- credentials not configured")  
        return  
      
    async with ANBIMAClient(  
        client\_id=client\_id,  
        client\_secret=client\_secret  
    ) as client:

# Define date range

#         end\_date \= datetime.now()

        start\_date \= end\_date \- timedelta(days=30)  
          
        logger.info(f"Fetching CRA data from {start\_date.date()} to {end\_date.date()}")  
        

# Fetch CRA data

#         cra\_data \= await client.get\_cra\_data(

            start\_date=start\_date,  
            end\_date=end\_date,  
            sector='AGRIBUSINESS'  \# Filter by sector  
        )  
          
        if cra\_data:  
            logger.info(f"✓ Retrieved {len(cra\_data)} CRA records")  
            

# Display sample data

#             if len(cra\_data) \> 0:

                logger.info("\\nSample CRA record:")  
                sample \= cra\_data\[0\]  
                for key, value in list(sample.items())\[:5\]:  
                    logger.info(f"  {key}: {value}")  
              
Save results

#             save\_results({'cra\_data': cra\_data}, 'anbima\_cra\_data.json')

            return cra\_data  
        else:  
            logger.warning("No CRA data retrieved")  
            return \[\]

async def example\_bacen\_selic\_rates():  
    """Example 4: Fetch SELIC rates from BACEN."""  
    logger.info("\\n" \+ "="\*80)  
    logger.info("Example 4: Fetching SELIC Rates from BACEN")  
    logger.info("="\*80)  
      
    async with BACENClient() as client:

# Define date range (last 90 days)

#         end\_date \= datetime.now()

        start\_date \= end\_date \- timedelta(days=90)  
          
        logger.info(f"Fetching SELIC rates from {start\_date.date()} to {end\_date.date()}")  
        

# Fetch SELIC rates (series 11\)

#         selic\_data \= await client.get\_selic\_rates(

            start\_date=start\_date,  
            end\_date=end\_date  
        )  
          
        if selic\_data:  
            logger.info(f"✓ Retrieved {len(selic\_data)} SELIC rate records")  
            

# Calculate statistics

#             rates \= \[float(record\['valor'\]) for record in selic\_data if 'valor' in record\]

            if rates:  
                avg\_rate \= sum(rates) / len(rates)  
                min\_rate \= min(rates)  
                max\_rate \= max(rates)  
                  
                logger.info(f"\\nSELIC Rate Statistics:")  
                logger.info(f"  Average: {avg\_rate:.2f}%")  
                logger.info(f"  Minimum: {min\_rate:.2f}%")  
                logger.info(f"  Maximum: {max\_rate:.2f}%")  
              
Save results

#             save\_results({'selic\_rates': selic\_data}, 'bacen\_selic\_rates.json')

            return selic\_data  
        else:  
            logger.warning("No SELIC data retrieved")  
            return \[\]

async def example\_bacen\_credit\_operations():  
    """Example 5: Fetch credit operations data from BACEN."""  
    logger.info("\\n" \+ "="\*80)  
    logger.info("Example 5: Fetching Credit Operations from BACEN")  
    logger.info("="\*80)  
      
    async with BACENClient() as client:  
Define date range

#         end\_date \= datetime.now()

        start\_date \= end\_date \- timedelta(days=180)  
          
        logger.info(f"Fetching credit operations from {start\_date.date()} to {end\_date.date()}")  
        

# Fetch credit operations (series 20539 \- Total credit operations)

#         credit\_data \= await client.get\_credit\_operations(

            start\_date=start\_date,  
            end\_date=end\_date,  
            operation\_type='TOTAL'  
        )  
          
        if credit\_data:  
            logger.info(f"✓ Retrieved {len(credit\_data)} credit operation records")  
              
Display recent data

#             if len(credit\_data) \> 0:

                logger.info("\\nMost recent credit operations:")  
                for record in credit\_data\[-5:\]:  
                    date \= record.get('data', 'N/A')  
                    value \= record.get('valor', 'N/A')  
                    logger.info(f"  {date}: R$ {value} billion")  
              
Save results

#             save\_results({'credit\_operations': credit\_data}, 'bacen\_credit\_operations.json')

            return credit\_data  
        else:  
            logger.warning("No credit operations data retrieved")  
            return \[\]

async def example\_bacen\_series\_data():  
    """Example 6: Fetch custom BACEN time series data."""  
    logger.info("\\n" \+ "="\*80)  
    logger.info("Example 6: Fetching Custom BACEN Time Series")  
    logger.info("="\*80)  
      
    async with BACENClient() as client:  
Define date range

#         end\_date \= datetime.now()

        start\_date \= end\_date \- timedelta(days=365)  
        

# Fetch IPCA (series 433\)

#         logger.info(f"Fetching IPCA from {start\_date.date()} to {end\_date.date()}")

          
        ipca\_data \= await client.get\_series(  
            series\_code=433,  
            start\_date=start\_date,  
            end\_date=end\_date  
        )  
          
        if ipca\_data:  
            logger.info(f"✓ Retrieved {len(ipca\_data)} IPCA records")  
            

# Calculate annual inflation

#             if len(ipca\_data) \>= 12:

                recent\_12\_months \= ipca\_data\[-12:\]  
                values \= \[float(r\['valor'\]) for r in recent\_12\_months if 'valor' in r\]  
                annual\_inflation \= sum(values)  
                logger.info(f"\\nAnnual Inflation (last 12 months): {annual\_inflation:.2f}%")  
              
Save results

#             save\_results({'ipca\_data': ipca\_data}, 'bacen\_ipca\_data.json')

            return ipca\_data  
        else:  
            logger.warning("No IPCA data retrieved")  
            return \[\]

async def example\_data\_integration\_simple():  
    """Example 7: Simple data integration across sources."""  
    logger.info("\\n" \+ "="\*80)  
    logger.info("Example 7: Simple Data Integration")  
    logger.info("="\*80)  
      
Initialize integrator

#     integrator \= DataIntegrator(

        anbima\_client\_id=os.getenv('ANBIMA\_CLIENT\_ID'),  
        anbima\_client\_secret=os.getenv('ANBIMA\_CLIENT\_SECRET')  
    )  
      
    await integrator.initialize()  
      
    try:

# Define CNPJ for a FIDC

#         fidc\_cnpj \= "00.000.000/0001-00"  \# Replace with actual CNPJ

          
        logger.info(f"Fetching integrated data for FIDC: {fidc\_cnpj}")  
          
Fetch integrated data

#         integrated\_data \= await integrator.get\_fidc\_complete\_data(

            cnpj=fidc\_cnpj,  
            start\_date=datetime.now() \- timedelta(days=90),  
            end\_date=datetime.now()  
        )  
          
        if integrated\_data:  
            logger.info("✓ Successfully integrated data from multiple sources")  
              
Display data summary

#             logger.info("\\nData Summary:")

            logger.info(f"  CVM Data: {'✓' if integrated\_data.get('cvm\_data') else '✗'}")  
            logger.info(f"  ANBIMA Data: {'✓' if integrated\_data.get('anbima\_data') else '✗'}")  
            logger.info(f"  BACEN Data: {'✓' if integrated\_data.get('bacen\_data') else '✗'}")  
              
Save results

#             save\_results(integrated\_data, 'integrated\_fidc\_data.json')

            return integrated\_data  
        else:  
            logger.warning("No integrated data retrieved")  
            return None  
              
    finally:  
        await integrator.close()

async def example\_fidc\_analysis():  
    """Example 8: Comprehensive FIDC analysis."""  
    logger.info("\\n" \+ "="\*80)  
    logger.info("Example 8: Comprehensive FIDC Analysis")  
    logger.info("="\*80)  
      
Initialize analyzer

#     analyzer \= FIDCAnalyzer(

#         anbima\_client\_id=os.getenv('ANBIMA\_CLIENT\_ID'),

        anbima\_client\_secret=os.getenv('ANBIMA\_CLIENT\_SECRET')  
    )  
      
    await analyzer.initialize()  
      
    try:  
Define FIDC for analysis

#         fidc\_cnpj \= "00.000.000/0001-00"  \# Replace with actual CNPJ

          
        logger.info(f"Performing comprehensive analysis for FIDC: {fidc\_cnpj}")  
          
Perform analysis

#         analysis \= await analyzer.analyze\_fidc(

            cnpj=fidc\_cnpj,  
            start\_date=datetime.now() \- timedelta(days=365),  
            end\_date=datetime.now()  
        )  
          
        if analysis:  
            logger.info("✓ Analysis completed successfully")  
              
Display key metrics

#             logger.info("\\nKey Metrics:")

              
            if 'portfolio\_metrics' in analysis:  
                metrics \= analysis\['portfolio\_metrics'\]  
                logger.info(f"  Total Assets: R$ {metrics.get('total\_assets', 0):,.2f}")  
                logger.info(f"  Default Rate: {metrics.get('default\_rate', 0):.2f}%")  
                logger.info(f"  Liquidity Ratio: {metrics.get('liquidity\_ratio', 0):.2f}")  
              
            if 'risk\_assessment' in analysis:  
                risk \= analysis\['risk\_assessment'\]  
                logger.info(f"\\nRisk Assessment:")  
                logger.info(f"  Risk Level: {risk.get('risk\_level', 'N/A')}")  
                logger.info(f"  Credit Score: {risk.get('credit\_score', 0):.2f}")  
              
            if 'performance\_indicators' in analysis:  
                perf \= analysis\['performance\_indicators'\]  
                logger.info(f"\\nPerformance Indicators:")  
                logger.info(f"  ROA: {perf.get('roa', 0):.2f}%")  
                logger.info(f"  ROE: {perf.get('roe', 0):.2f}%")  
              
Save results

#             save\_results(analysis, 'fidc\_comprehensive\_analysis.json')

            return analysis  
        else:  
            logger.warning("Analysis failed or returned no data")  
            return None  
              
    finally:  
        await analyzer.close()

async def example\_batch\_fidc\_analysis():  
    """Example 9: Batch analysis of multiple FIDCs."""  
    logger.info("\\n" \+ "="\*80)  
    logger.info("Example 9: Batch FIDC Analysis")  
    logger.info("="\*80)  
      
Initialize analyzer

#     analyzer \= FIDCAnalyzer(

#         anbima\_client\_id=os.getenv('ANBIMA\_CLIENT\_ID'),

        anbima\_client\_secret=os.getenv('ANBIMA\_CLIENT\_SECRET')  
    )  
      
    await analyzer.initialize()  
      
    try:  
Define list of FIDCs to analyze

#         fidc\_list \= \[

#             "00.000.000/0001-00",

            "11.111.111/0001-11",  
            "22.222.222/0001-22"  
        \]  \# Replace with actual CNPJs  
          
        logger.info(f"Analyzing {len(fidc\_list)} FIDCs in batch")  
          
Perform batch analysis

#         results \= await analyzer.analyze\_fidc\_batch(

            cnpj\_list=fidc\_list,  
            start\_date=datetime.now() \- timedelta(days=180),  
            end\_date=datetime.now()  
        )  
          
        if results:  
            logger.info(f"✓ Batch analysis completed for {len(results)} FIDCs")  
              
Display summary

#             logger.info("\\nBatch Analysis Summary:")

            for cnpj, analysis in results.items():  
                status \= "✓ Success" if analysis else "✗ Failed"  
                logger.info(f"  {cnpj}: {status}")  
              
Save results

#             save\_results(results, 'batch\_fidc\_analysis.json')

            return results  
        else:  
            logger.warning("Batch analysis returned no results")  
            return {}  
              
    finally:  
        await analyzer.close()

async def example\_market\_comparison():  
    """Example 10: Market-wide comparison and benchmarking."""  
    logger.info("\\n" \+ "="\*80)  
    logger.info("Example 10: Market-Wide Comparison")  
    logger.info("="\*80)  
      
Initialize analyzer

#     analyzer \= FIDCAnalyzer(

#         anbima\_client\_id=os.getenv('ANBIMA\_CLIENT\_ID'),

        anbima\_client\_secret=os.getenv('ANBIMA\_CLIENT\_SECRET')  
    )  
      
    await analyzer.initialize()  
      
    try:  
        logger.info("Fetching market-wide FIDC data for comparison")  
          
Get market comparison

#         comparison \= await analyzer.get\_market\_comparison(

            start\_date=datetime.now() \- timedelta(days=90),  
            end\_date=datetime.now(),  
            min\_assets=10000000  \# Minimum R$ 10 million in assets  
        )  
          
        if comparison:  
            logger.info("✓ Market comparison completed")  
              
Display statistics

#             if 'market\_statistics' in comparison:

                stats \= comparison\['market\_statistics'\]  
                logger.info("\\nMarket Statistics:")  
                logger.info(f"  Total FIDCs: {stats.get('total\_fidcs', 0)}")  
                logger.info(f"  Total AUM: R$ {stats.get('total\_aum', 0):,.2f}")  
                logger.info(f"  Avg Default Rate: {stats.get('avg\_default\_rate', 0):.2f}%")  
                logger.info(f"  Avg ROA: {stats.get('avg\_roa', 0):.2f}%")  
              
Save results

#             save\_results(comparison, 'market\_comparison.json')

            return comparison  
        else:  
            logger.warning("Market comparison returned no data")  
            return None  
              
    finally:  
        await analyzer.close()

async def main():  
    """Run all examples."""  
    logger.info("\\n" \+ "\#"\*80)  
    logger.info("\# Brazilian Financial Data API \- Comprehensive Examples")  
    logger.info("\#"\*80)  
      
    try:  
ANBIMA Examples

#         await example\_anbima\_authentication()

        await example\_anbima\_cri\_data()  
        await example\_anbima\_cra\_data()  
          
BACEN Examples

#         await example\_bacen\_selic\_rates()

#         await example\_bacen\_credit\_operations()

        await example\_bacen\_series\_data()  
          
Data Integration Examples

#         await example\_data\_integration\_simple()

        await example\_fidc\_analysis()  
        await example\_batch\_fidc\_analysis()  
        await example\_market\_comparison()  
          
        logger.info("\\n" \+ "="\*80)  
        logger.info("All examples completed successfully\!")  
        logger.info("Check the 'output' directory for saved results.")  
        logger.info("="\*80)  
          
    except Exception as e:  
        logger.error(f"Error running examples: {e}", exc\_info=True)  
        raise

if \_\_name\_\_ \== "\_\_main\_\_":  
Run all examples  
    asyncio.run(main())  
\`\`\`

# \---

# 

# \*Generated: February 2026\*

