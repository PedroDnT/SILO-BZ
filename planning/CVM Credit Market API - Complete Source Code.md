# CVM Credit Market API \- Source Code

Complete FastAPI service for Brazilian CVM credit market data.

## File Overview

\- 9 files, \~60KB of code  
\- Stack: FastAPI, Python 3.12, Docker  
\- Entities: FIDC, FIP, FIAGRO, SECURIT

\---

## config.py

\`\`\`python  
import os  
from typing import Dict, List  
from enum import Enum

class BaseConfig:  
    """Base configuration for CVM Credit Market API"""  
    API\_TITLE \= "CVM Credit Market Data API"  
    API\_VERSION \= "1.0.0"  
    API\_DESCRIPTION \= "API for accessing Brazilian CVM credit market data including FIDC, FIP, FIAGRO, and SECURIT"  
    

# CVM Base URLs

    CVM\_BASE\_URL \= "https://dados.cvm.gov.br/dados"  
    

# Default pagination

    DEFAULT\_PAGE\_SIZE \= 100  
    MAX\_PAGE\_SIZE \= 10000  
    

# File handling

    TEMP\_DIR \= os.path.join(os.getcwd(), "temp")  
    ENCODING \= "latin-1"  
    CSV\_SEPARATOR \= ";"  
    

# Request settings

    REQUEST\_TIMEOUT \= 300  
    MAX\_RETRIES \= 3  
    RETRY\_DELAY \= 2

class EntityType(str, Enum):  
    """Supported entity types"""  
    FIDC \= "fidc"  
    FIP \= "fip"  
    FIAGRO \= "fiagro"  
    SECURIT \= "securit"

class FIDCDocType(str, Enum):  
    """FIDC document types"""  
    CADASTRAL \= "cadastral"  
    MENSAL \= "mensal"  
    TRIMESTRAL \= "trimestral"  
    ANUAL \= "anual"  
    QUADRIMESTRAL \= "quadrimestral"  
    DFIN \= "dfin"

class FIPDocType(str, Enum):  
    """FIP document types"""  
    CADASTRAL \= "cadastral"  
    INF\_QUADRIMESTRAL \= "inf\_quadrimestral"  
    DFIN \= "dfin"

class FIAGRODocType(str, Enum):  
    """FIAGRO document types"""  
    CADASTRAL \= "cadastral"  
    MENSAL \= "mensal"  
    TRIMESTRAL \= "trimestral"  
    ANUAL \= "anual"  
    DFIN \= "dfin"

class SECURITDocType(str, Enum):  
    """SECURIT document types"""  
    CADASTRAL \= "cadastral"  
    CRA\_MENSAL \= "cra\_mensal"  
    CRI\_MENSAL \= "cri\_mensal"  
    LCA\_MENSAL \= "lca\_mensal"  
    LCI\_MENSAL \= "lci\_mensal"

class DatasetConfig:  
    """Dataset configuration mappings"""  
      
    FIDC\_DATASETS: Dict\[str, Dict\] \= {  
        "cadastral": {  
            "url\_pattern": "{base\_url}/FIDC/CAD/DADOS/cad\_fidc.csv",  
            "is\_zip": False,  
            "description": "Cadastral data for FIDC funds"  
        },  
        "mensal": {  
            "url\_pattern": "{base\_url}/FIDC/DOC/INF\_MENSAL/DADOS/inf\_mensal\_fidc\_{year}{month:02d}.zip",  
            "is\_zip": True,  
            "csv\_name\_pattern": "inf\_mensal\_fidc\_{year}{month:02d}.csv",  
            "description": "Monthly information for FIDC funds"  
        },  
        "trimestral": {  
            "url\_pattern": "{base\_url}/FIDC/DOC/INF\_TRIMESTRAL/DADOS/inf\_trimestral\_fidc\_{year}{month:02d}.zip",  
            "is\_zip": True,  
            "csv\_name\_pattern": "inf\_trimestral\_fidc\_{year}{month:02d}.csv",  
            "description": "Quarterly information for FIDC funds"  
        },  
        "anual": {  
            "url\_pattern": "{base\_url}/FIDC/DOC/INF\_ANUAL/DADOS/inf\_anual\_fidc\_{year}.zip",  
            "is\_zip": True,  
            "csv\_name\_pattern": "inf\_anual\_fidc\_{year}.csv",  
            "description": "Annual information for FIDC funds"  
        },  
        "quadrimestral": {  
            "url\_pattern": "{base\_url}/FIDC/DOC/INF\_QUADRIMESTRAL/DADOS/inf\_quadrimestral\_fidc\_{year}{month:02d}.zip",  
            "is\_zip": True,  
            "csv\_name\_pattern": "inf\_quadrimestral\_fidc\_{year}{month:02d}.csv",  
            "description": "Four-month period information for FIDC funds"  
        },  
        "dfin": {  
            "url\_pattern": "{base\_url}/FIDC/DOC/DFIN/DADOS/dfin\_fidc\_{year}.zip",  
            "is\_zip": True,  
            "csv\_name\_pattern": "dfin\_fidc\_{year}.csv",  
            "description": "Financial statements for FIDC funds"  
        }  
    }  
      
    FIP\_DATASETS: Dict\[str, Dict\] \= {  
        "cadastral": {  
            "url\_pattern": "{base\_url}/FIP/CAD/DADOS/cad\_fip.csv",  
            "is\_zip": False,  
            "description": "Cadastral data for FIP funds"  
        },  
        "inf\_quadrimestral": {  
            "url\_pattern": "{base\_url}/FIP/DOC/INF\_QUADRIMESTRAL/DADOS/inf\_quadrimestral\_fip\_{year}{month:02d}.zip",  
            "is\_zip": True,  
            "csv\_name\_pattern": "inf\_quadrimestral\_fip\_{year}{month:02d}.csv",  
            "description": "Four-month period information for FIP funds"  
        },  
        "dfin": {  
            "url\_pattern": "{base\_url}/FIP/DOC/DFIN/DADOS/dfin\_fip\_{year}.zip",  
            "is\_zip": True,  
            "csv\_name\_pattern": "dfin\_fip\_{year}.csv",  
            "description": "Financial statements for FIP funds"  
        }  
    }  
      
    FIAGRO\_DATASETS: Dict\[str, Dict\] \= {  
        "cadastral": {  
            "url\_pattern": "{base\_url}/FIAGRO/CAD/DADOS/cad\_fiagro.csv",  
            "is\_zip": False,  
            "description": "Cadastral data for FIAGRO funds"  
        },  
        "mensal": {  
            "url\_pattern": "{base\_url}/FIAGRO/DOC/INF\_MENSAL/DADOS/inf\_mensal\_fiagro\_{year}{month:02d}.zip",  
            "is\_zip": True,  
            "csv\_name\_pattern": "inf\_mensal\_fiagro\_{year}{month:02d}.csv",  
            "description": "Monthly information for FIAGRO funds"  
        },  
        "trimestral": {  
            "url\_pattern": "{base\_url}/FIAGRO/DOC/INF\_TRIMESTRAL/DADOS/inf\_trimestral\_fiagro\_{year}{month:02d}.zip",  
            "is\_zip": True,  
            "csv\_name\_pattern": "inf\_trimestral\_fiagro\_{year}{month:02d}.csv",  
            "description": "Quarterly information for FIAGRO funds"  
        },  
        "anual": {  
            "url\_pattern": "{base\_url}/FIAGRO/DOC/INF\_ANUAL/DADOS/inf\_anual\_fiagro\_{year}.zip",  
            "is\_zip": True,  
            "csv\_name\_pattern": "inf\_anual\_fiagro\_{year}.csv",  
            "description": "Annual information for FIAGRO funds"  
        },  
        "dfin": {  
            "url\_pattern": "{base\_url}/FIAGRO/DOC/DFIN/DADOS/dfin\_fiagro\_{year}.zip",  
            "is\_zip": True,  
            "csv\_name\_pattern": "dfin\_fiagro\_{year}.csv",  
            "description": "Financial statements for FIAGRO funds"  
        }  
    }  
      
    SECURIT\_DATASETS: Dict\[str, Dict\] \= {  
        "cadastral": {  
            "url\_pattern": "{base\_url}/SECURIT/CAD/DADOS/cad\_securit.csv",  
            "is\_zip": False,  
            "description": "Cadastral data for securitization companies"  
        },  
        "cra\_mensal": {  
            "url\_pattern": "{base\_url}/SECURIT/EMISSAO/CRA/MENSAL/DADOS/emissao\_cra\_mensal\_{year}{month:02d}.csv",  
            "is\_zip": False,  
            "description": "Monthly CRA issuance data"  
        },  
        "cri\_mensal": {  
            "url\_pattern": "{base\_url}/SECURIT/EMISSAO/CRI/MENSAL/DADOS/emissao\_cri\_mensal\_{year}{month:02d}.csv",  
            "is\_zip": False,  
            "description": "Monthly CRI issuance data"  
        },  
        "lca\_mensal": {  
            "url\_pattern": "{base\_url}/SECURIT/EMISSAO/LCA/MENSAL/DADOS/emissao\_lca\_mensal\_{year}{month:02d}.csv",  
            "is\_zip": False,  
            "description": "Monthly LCA issuance data"  
        },  
        "lci\_mensal": {  
            "url\_pattern": "{base\_url}/SECURIT/EMISSAO/LCI/MENSAL/DADOS/emissao\_lci\_mensal\_{year}{month:02d}.csv",  
            "is\_zip": False,  
            "description": "Monthly LCI issuance data"  
        }  
    }  
      
    @classmethod  
    def get\_dataset\_config(cls, entity: str, doc\_type: str) \-\> Dict:  
        """Get dataset configuration for entity and document type"""  
        entity\_map \= {  
            "fidc": cls.FIDC\_DATASETS,  
            "fip": cls.FIP\_DATASETS,  
            "fiagro": cls.FIAGRO\_DATASETS,  
            "securit": cls.SECURIT\_DATASETS  
        }  
          
        datasets \= entity\_map.get(entity.lower())  
        if not datasets:  
            raise ValueError(f"Unknown entity type: {entity}")  
          
        config \= datasets.get(doc\_type.lower())  
        if not config:  
            raise ValueError(f"Unknown document type '{doc\_type}' for entity '{entity}'")  
          
        return config  
      
    @classmethod  
    def get\_available\_doc\_types(cls, entity: str) \-\> List\[str\]:  
        """Get list of available document types for an entity"""  
        entity\_map \= {  
            "fidc": list(cls.FIDC\_DATASETS.keys()),  
            "fip": list(cls.FIP\_DATASETS.keys()),  
            "fiagro": list(cls.FIAGRO\_DATASETS.keys()),  
            "securit": list(cls.SECURIT\_DATASETS.keys())  
        }  
        return entity\_map.get(entity.lower(), \[\])

config \= BaseConfig()  
dataset\_config \= DatasetConfig()  
\`\`\`

\---

## models.py

\`\`\`python  
from pydantic import BaseModel, Field, validator  
from typing import List, Dict, Any, Optional  
from datetime import datetime

class HealthResponse(BaseModel):  
    """Health check response model"""  
    status: str \= Field(..., description="Service health status")  
    timestamp: str \= Field(..., description="Current timestamp")  
    version: str \= Field(..., description="API version")

class ErrorResponse(BaseModel):  
    """Error response model"""  
    error: str \= Field(..., description="Error message")  
    status\_code: int \= Field(..., description="HTTP status code")  
    timestamp: str \= Field(..., description="Error timestamp")

class PaginationInfo(BaseModel):  
    """Pagination information model"""  
    page: int \= Field(..., description="Current page number", ge=1)  
    page\_size: int \= Field(..., description="Number of items per page", ge=1)  
    total\_items: int \= Field(..., description="Total number of items", ge=0)  
    total\_pages: int \= Field(..., description="Total number of pages", ge=0)  
    has\_next: bool \= Field(..., description="Whether there is a next page")  
    has\_previous: bool \= Field(..., description="Whether there is a previous page")

class DataResponse(BaseModel):  
    """Generic data response model"""  
    entity: str \= Field(..., description="Entity type (fidc, fip, fiagro, securit)")  
    doc\_type: str \= Field(..., description="Document type")  
    data: List\[Dict\[str, Any\]\] \= Field(..., description="Data records")  
    pagination: PaginationInfo \= Field(..., description="Pagination information")  
    metadata: Dict\[str, Any\] \= Field(default\_factory=dict, description="Additional metadata")  
    timestamp: str \= Field(default\_factory=lambda: datetime.utcnow().isoformat(), description="Response timestamp")  
      
    class Config:  
        schema\_extra \= {  
            "example": {  
                "entity": "fidc",  
                "doc\_type": "cadastral",  
                "data": \[  
                    {  
                        "CNPJ\_FUNDO": "12.345.678/0001-90",  
                        "DENOM\_SOCIAL": "FUNDO DE INVESTIMENTO EXEMPLO",  
                        "DT\_REG": "2020-01-15"  
                    }  
                \],  
                "pagination": {  
                    "page": 1,  
                    "page\_size": 100,  
                    "total\_items": 250,  
                    "total\_pages": 3,  
                    "has\_next": True,  
                    "has\_previous": False  
                },  
                "metadata": {  
                    "year": 2023,  
                    "month": 12,  
                    "source\_url": "https://dados.cvm.gov.br/dados/FIDC/CAD/DADOS/cad\_fidc.csv"  
                },  
                "timestamp": "2024-01-15T10:30:00.000Z"  
            }  
        }

class EntityInfo(BaseModel):  
    """Entity information model"""  
    entity: str \= Field(..., description="Entity identifier")  
    name: str \= Field(..., description="Full entity name")  
    doc\_types: List\[str\] \= Field(..., description="Available document types")  
    description: str \= Field(..., description="Entity description")

class AvailableEndpointsResponse(BaseModel):  
    """Available endpoints response model"""  
    entities: List\[EntityInfo\] \= Field(..., description="List of available entities")  
    base\_url: str \= Field(..., description="Base URL pattern for endpoints")  
    version: str \= Field(..., description="API version")  
      
    class Config:  
        schema\_extra \= {  
            "example": {  
                "entities": \[  
                    {  
                        "entity": "fidc",  
                        "name": "FIDC \- Fundos de Investimento em Direitos Creditórios",  
                        "doc\_types": \["cadastral", "mensal", "trimestral", "anual", "quadrimestral", "dfin"\],  
                        "description": "Investment funds in credit rights"  
                    }  
                \],  
                "base\_url": "/api/v1/{entity}/{doc\_type}",  
                "version": "1.0.0"  
            }  
        }

class FIDCCadastralData(BaseModel):  
    """FIDC Cadastral data model"""  
    cnpj\_fundo: Optional\[str\] \= Field(None, description="Fund CNPJ")  
    denom\_social: Optional\[str\] \= Field(None, description="Social denomination")  
    dt\_reg: Optional\[str\] \= Field(None, description="Registration date")  
    dt\_cancel: Optional\[str\] \= Field(None, description="Cancellation date")  
    sit: Optional\[str\] \= Field(None, description="Current status")  
    tp\_fundo: Optional\[str\] \= Field(None, description="Fund type")  
      
    class Config:  
        extra \= "allow"

class FIPCadastralData(BaseModel):  
    """FIP Cadastral data model"""  
    cnpj\_fundo: Optional\[str\] \= Field(None, description="Fund CNPJ")  
    denom\_social: Optional\[str\] \= Field(None, description="Social denomination")  
    dt\_reg: Optional\[str\] \= Field(None, description="Registration date")  
    dt\_cancel: Optional\[str\] \= Field(None, description="Cancellation date")  
    sit: Optional\[str\] \= Field(None, description="Current status")  
    tp\_fundo: Optional\[str\] \= Field(None, description="Fund type")  
      
    class Config:  
        extra \= "allow"

class FIAGROCadastralData(BaseModel):  
    """FIAGRO Cadastral data model"""  
    cnpj\_fundo: Optional\[str\] \= Field(None, description="Fund CNPJ")  
    denom\_social: Optional\[str\] \= Field(None, description="Social denomination")  
    dt\_reg: Optional\[str\] \= Field(None, description="Registration date")  
    dt\_cancel: Optional\[str\] \= Field(None, description="Cancellation date")  
    sit: Optional\[str\] \= Field(None, description="Current status")  
    tp\_fundo: Optional\[str\] \= Field(None, description="Fund type")  
      
    class Config:  
        extra \= "allow"

class SECURITCadastralData(BaseModel):  
    """SECURIT Cadastral data model"""  
    cnpj\_securit: Optional\[str\] \= Field(None, description="Securitization company CNPJ")  
    denom\_social: Optional\[str\] \= Field(None, description="Social denomination")  
    dt\_reg: Optional\[str\] \= Field(None, description="Registration date")  
    dt\_cancel: Optional\[str\] \= Field(None, description="Cancellation date")  
    sit: Optional\[str\] \= Field(None, description="Current status")  
      
    class Config:  
        extra \= "allow"

class PeriodicReportData(BaseModel):  
    """Generic periodic report data model"""  
    cnpj\_fundo: Optional\[str\] \= Field(None, description="Fund CNPJ")  
    dt\_comptc: Optional\[str\] \= Field(None, description="Competence date")  
    vl\_total: Optional\[str\] \= Field(None, description="Total value")  
    vl\_quota: Optional\[str\] \= Field(None, description="Quota value")  
    vl\_patrim\_liq: Optional\[str\] \= Field(None, description="Net equity value")  
      
    class Config:  
        extra \= "allow"

class EmissionData(BaseModel):  
    """Emission data model for SECURIT"""  
    cnpj\_securit: Optional\[str\] \= Field(None, description="Securitization company CNPJ")  
    tp\_ativo: Optional\[str\] \= Field(None, description="Asset type")  
    dt\_emissao: Optional\[str\] \= Field(None, description="Emission date")  
    vl\_emissao: Optional\[str\] \= Field(None, description="Emission value")  
    qt\_titulos: Optional\[str\] \= Field(None, description="Number of titles")  
      
    class Config:  
        extra \= "allow"  
\`\`\`

\---

## services.py

## 

\`\`\`python  
import os  
import io  
import csv  
import logging  
import asyncio  
import zipfile  
import aiohttp  
import aiofiles  
from typing import List, Dict, Any, Optional, Tuple  
from datetime import datetime  
import math  
import time

from config import config, dataset\_config  
from models import DataResponse, PaginationInfo

logger \= logging.getLogger(\_\_name\_\_)

class CVMCreditDataService:  
    """Service for downloading and processing CVM credit market data"""  
      
    def \_\_init\_\_(self):  
        """Initialize the CVM data service"""  
        self.base\_url \= config.CVM\_BASE\_URL  
        self.temp\_dir \= config.TEMP\_DIR  
        self.encoding \= config.ENCODING  
        self.separator \= config.CSV\_SEPARATOR  
        self.timeout \= config.REQUEST\_TIMEOUT  
        self.max\_retries \= config.MAX\_RETRIES  
        self.retry\_delay \= config.RETRY\_DELAY  
        

# Create temp directory if it doesn't exist

#         os.makedirs(self.temp\_dir, exist\_ok=True)

        logger.info(f"CVMCreditDataService initialized with temp\_dir: {self.temp\_dir}")  
      
    def \_validate\_parameters(self, entity: str, doc\_type: str, year: Optional\[int\], month: Optional\[int\]) \-\> None:  
        """Validate request parameters"""  
        dataset\_conf \= dataset\_config.get\_dataset\_config(entity, doc\_type)  
        

# Check if year/month are required

#         url\_pattern \= dataset\_conf\["url\_pattern"\]

          
        if "{year}" in url\_pattern and year is None:  
            raise ValueError(f"Year parameter is required for {entity}/{doc\_type}")  
          
        if "{month" in url\_pattern and month is None:  
            raise ValueError(f"Month parameter is required for {entity}/{doc\_type}")  
        

# Validate year range

#         if year is not None:

            current\_year \= datetime.now().year  
            if year \< 2000 or year \> current\_year:  
                raise ValueError(f"Year must be between 2000 and {current\_year}")  
        

# Validate month range

#         if month is not None:

            if month \< 1 or month \> 12:  
                raise ValueError("Month must be between 1 and 12")  
      
    def \_build\_url(self, entity: str, doc\_type: str, year: Optional\[int\], month: Optional\[int\]) \-\> Tuple\[str, Dict\]:  
        """Build the download URL based on entity, doc\_type, year, and month"""  
        dataset\_conf \= dataset\_config.get\_dataset\_config(entity, doc\_type)  
        url\_pattern \= dataset\_conf\["url\_pattern"\]  
        

# Format URL with parameters

#         url \= url\_pattern.format(

            base\_url=self.base\_url,  
            year=year or "",  
            month=month or ""  
        )  
          
        return url, dataset\_conf  
      
    async def \_download\_file(self, url: str) \-\> bytes:  
        """Download file from URL with retry logic"""  
        for attempt in range(self.max\_retries):  
            try:  
                logger.info(f"Downloading from {url} (attempt {attempt \+ 1}/{self.max\_retries})")  
                  
                timeout \= aiohttp.ClientTimeout(total=self.timeout)  
                async with aiohttp.ClientSession(timeout=timeout) as session:  
                    async with session.get(url) as response:  
                        if response.status \== 404:  
                            raise ValueError(f"Data not found at URL: {url}. The requested period may not be available.")  
                          
                        if response.status \!= 200:  
                            raise Exception(f"HTTP {response.status}: Failed to download file from {url}")  
                          
                        content \= await response.read()  
                        logger.info(f"Successfully downloaded {len(content)} bytes from {url}")  
                        return content  
              
            except aiohttp.ClientError as e:  
                logger.warning(f"Download attempt {attempt \+ 1} failed: {str(e)}")  
                if attempt \< self.max\_retries \- 1:  
                    await asyncio.sleep(self.retry\_delay \* (attempt \+ 1))  
                else:  
                    raise Exception(f"Failed to download file after {self.max\_retries} attempts: {str(e)}")  
              
            except Exception as e:  
                logger.error(f"Unexpected error during download: {str(e)}")  
                raise  
      
    def \_extract\_csv\_from\_zip(self, zip\_content: bytes, csv\_name\_pattern: str, year: Optional\[int\], month: Optional\[int\]) \-\> str:  
        """Extract CSV content from ZIP file"""  
        try:

# Format the expected CSV filename

#             csv\_filename \= csv\_name\_pattern.format(year=year or "", month=month or "")

              
            with zipfile.ZipFile(io.BytesIO(zip\_content)) as zip\_file:

# List all files in the ZIP

#                 file\_list \= zip\_file.namelist()

                logger.info(f"Files in ZIP: {file\_list}")  
                

# Try to find the CSV file

#                 csv\_file \= None

                for filename in file\_list:  
                    if filename.lower().endswith('.csv'):  
                        if csv\_filename.lower() in filename.lower():  
                            csv\_file \= filename  
                            break  
                

# If exact match not found, try to use the first CSV

#                 if not csv\_file:

                    for filename in file\_list:  
                        if filename.lower().endswith('.csv'):  
                            csv\_file \= filename  
                            logger.warning(f"Using first CSV file found: {csv\_file}")  
                            break  
                  
                if not csv\_file:  
                    raise ValueError(f"No CSV file found in ZIP archive")  
                

# Extract and decode CSV content

#                 csv\_content \= zip\_file.read(csv\_file).decode(self.encoding)

                logger.info(f"Extracted CSV file: {csv\_file} ({len(csv\_content)} characters)")  
                return csv\_content  
          
        except zipfile.BadZipFile:  
            raise ValueError("Invalid ZIP file format")  
        except Exception as e:  
            logger.error(f"Error extracting CSV from ZIP: {str(e)}")  
            raise  
      
    def \_parse\_csv\_content(self, csv\_content: str) \-\> List\[Dict\[str, Any\]\]:  
        """Parse CSV content into list of dictionaries"""  
        try:  
            csv\_reader \= csv.DictReader(  
                io.StringIO(csv\_content),  
                delimiter=self.separator  
            )  
              
            data \= \[\]  
            for row in csv\_reader:

# Clean up field names and values

#                 cleaned\_row \= {}

                for key, value in row.items():  
                    if key:  \# Skip empty keys  
                        clean\_key \= key.strip()  
                        clean\_value \= value.strip() if value else None  
                        cleaned\_row\[clean\_key\] \= clean\_value  
                  
                if cleaned\_row:  \# Only add non-empty rows  
                    data.append(cleaned\_row)  
              
            logger.info(f"Parsed {len(data)} records from CSV")  
            return data  
          
        except Exception as e:  
            logger.error(f"Error parsing CSV content: {str(e)}")  
            raise ValueError(f"Failed to parse CSV data: {str(e)}")  
      
    def \_paginate\_data(self, data: List\[Dict\[str, Any\]\], page: int, page\_size: int) \-\> Tuple\[List\[Dict\[str, Any\]\], PaginationInfo\]:  
        """Paginate data and return page with pagination info"""  
        total\_items \= len(data)  
        total\_pages \= math.ceil(total\_items / page\_size) if total\_items \> 0 else 0  
        

# Calculate start and end indices

#         start\_idx \= (page \- 1\) \* page\_size

        end\_idx \= start\_idx \+ page\_size  
        

# Get page data

#         page\_data \= data\[start\_idx:end\_idx\]

        

# Create pagination info

#         pagination\_info \= PaginationInfo(

            page=page,  
            page\_size=page\_size,  
            total\_items=total\_items,  
            total\_pages=total\_pages,  
            has\_next=page \< total\_pages,  
            has\_previous=page \> 1  
        )  
          
        return page\_data, pagination\_info  
      
    async def get\_data(  
        self,  
        entity: str,  
        doc\_type: str,  
        year: Optional\[int\] \= None,  
        month: Optional\[int\] \= None,  
        page: int \= 1,  
        page\_size: int \= config.DEFAULT\_PAGE\_SIZE  
    ) \-\> DataResponse:  
        """Get data for specified entity and document type"""  
        start\_time \= time.time()  
          
        try:

# Validate parameters

#             self.\_validate\_parameters(entity, doc\_type, year, month)

            

# Build URL

#             url, dataset\_conf \= self.\_build\_url(entity, doc\_type, year, month)

            logger.info(f"Processing request: {entity}/{doc\_type} from {url}")  
            

# Download file

#             file\_content \= await self.\_download\_file(url)

            

# Handle ZIP or direct CSV

#             if dataset\_conf\["is\_zip"\]:

                csv\_content \= self.\_extract\_csv\_from\_zip(  
                    file\_content,  
                    dataset\_conf\["csv\_name\_pattern"\],  
                    year,  
                    month  
                )  
            else:  
                csv\_content \= file\_content.decode(self.encoding)  
            

# Parse CSV content

#             all\_data \= self.\_parse\_csv\_content(csv\_content)

            

# Paginate data

#             page\_data, pagination\_info \= self.\_paginate\_data(all\_data, page, page\_size)

            

# Build metadata

#             metadata \= {

                "source\_url": url,  
                "description": dataset\_conf\["description"\],  
                "is\_zip": dataset\_conf\["is\_zip"\],  
                "processing\_time\_seconds": round(time.time() \- start\_time, 2\)  
            }  
              
            if year:  
                metadata\["year"\] \= year  
            if month:  
                metadata\["month"\] \= month  
            

# Create response

#             response \= DataResponse(

                entity=entity,  
                doc\_type=doc\_type,  
                data=page\_data,  
                pagination=pagination\_info,  
                metadata=metadata  
            )  
              
            logger.info(f"Request completed successfully in {metadata\['processing\_time\_seconds'\]}s: {len(page\_data)} records returned")  
            return response  
          
        except ValueError as e:

# Re-raise validation errors

#             raise

          
        except Exception as e:  
            logger.error(f"Error processing request: {str(e)}", exc\_info=True)  
            raise Exception(f"Failed to process data request: {str(e)}")  
      
    def cleanup\_temp\_files(self) \-\> None:  
        """Clean up temporary files"""  
        try:  
            if os.path.exists(self.temp\_dir):  
                for filename in os.listdir(self.temp\_dir):  
                    file\_path \= os.path.join(self.temp\_dir, filename)  
                    try:  
                        if os.path.isfile(file\_path):  
                            os.unlink(file\_path)  
                    except Exception as e:  
                        logger.error(f"Error deleting {file\_path}: {str(e)}")  
                logger.info("Temporary files cleaned up")  
        except Exception as e:  
            logger.error(f"Error during cleanup: {str(e)}")  
\`\`\`

\---

## main.py

## 

\`\`\`python  
from fastapi import FastAPI, HTTPException, Query, Path  
from fastapi.responses import JSONResponse  
from fastapi.middleware.cors import CORSMiddleware  
from typing import Optional, List, Dict, Any  
import logging  
from datetime import datetime

from config import (  
    config,  
    dataset\_config,  
    EntityType,  
    FIDCDocType,  
    FIPDocType,  
    FIAGRODocType,  
    SECURITDocType  
)  
from models import (  
    DataResponse,  
    ErrorResponse,  
    HealthResponse,  
    AvailableEndpointsResponse,  
    EntityInfo  
)  
from services import CVMCreditDataService

# Configure logging

# logging.basicConfig(

    level=logging.INFO,  
    format='%(asctime)s \- %(name)s \- %(levelname)s \- %(message)s'  
)  
logger \= logging.getLogger(\_\_name\_\_)

# Initialize FastAPI app

# app \= FastAPI(

    title=config.API\_TITLE,  
    version=config.API\_VERSION,  
    description=config.API\_DESCRIPTION,  
    docs\_url="/docs",  
    redoc\_url="/redoc"  
)

# Configure CORS

# app.add\_middleware(

    CORSMiddleware,  
    allow\_origins=\["\*"\],  
    allow\_credentials=True,  
    allow\_methods=\["\*"\],  
    allow\_headers=\["\*"\],  
)

# Initialize service

# data\_service \= CVMCreditDataService()

@app.get("/", response\_model=Dict\[str, str\])  
async def root():  
    """Root endpoint with API information"""  
    return {  
        "service": config.API\_TITLE,  
        "version": config.API\_VERSION,  
        "documentation": "/docs",  
        "health": "/health",  
        "endpoints": "/api/v1/endpoints"  
    }

@app.get("/health", response\_model=HealthResponse)  
async def health\_check():  
    """Health check endpoint"""  
    return HealthResponse(  
        status="healthy",  
        timestamp=datetime.utcnow().isoformat(),  
        version=config.API\_VERSION  
    )

@app.get("/api/v1/endpoints", response\_model=AvailableEndpointsResponse)  
async def get\_available\_endpoints():  
    """Get all available endpoints and their descriptions"""  
    entities \= \[  
        EntityInfo(  
            entity="fidc",  
            name="FIDC \- Fundos de Investimento em Direitos Creditórios",  
            doc\_types=dataset\_config.get\_available\_doc\_types("fidc"),  
            description="Investment funds in credit rights"  
        ),  
        EntityInfo(  
            entity="fip",  
            name="FIP \- Fundos de Investimento em Participações",  
            doc\_types=dataset\_config.get\_available\_doc\_types("fip"),  
            description="Private equity investment funds"  
        ),  
        EntityInfo(  
            entity="fiagro",  
            name="FIAGRO \- Fundos de Investimento nas Cadeias Produtivas Agroindustriais",  
            doc\_types=dataset\_config.get\_available\_doc\_types("fiagro"),  
            description="Agroindustrial investment funds"  
        ),  
        EntityInfo(  
            entity="securit",  
            name="SECURIT \- Securitizadoras",  
            doc\_types=dataset\_config.get\_available\_doc\_types("securit"),  
            description="Securitization companies"  
        )  
    \]  
      
    return AvailableEndpointsResponse(  
        entities=entities,  
        base\_url="/api/v1/{entity}/{doc\_type}",  
        version=config.API\_VERSION  
    )

@app.get("/api/v1/fidc/{doc\_type}", response\_model=DataResponse)  
async def get\_fidc\_data(  
    doc\_type: FIDCDocType \= Path(..., description="Type of FIDC document"),  
    year: Optional\[int\] \= Query(None, description="Year for the data (required for periodic reports)"),  
    month: Optional\[int\] \= Query(None, ge=1, le=12, description="Month for the data (required for periodic reports)"),  
    page: int \= Query(1, ge=1, description="Page number"),  
    page\_size: int \= Query(config.DEFAULT\_PAGE\_SIZE, ge=1, le=config.MAX\_PAGE\_SIZE, description="Items per page")  
):  
    """Get FIDC data by document type"""  
    try:  
        logger.info(f"Request: FIDC {doc\_type.value} \- year={year}, month={month}, page={page}, page\_size={page\_size}")  
          
        result \= await data\_service.get\_data(  
            entity="fidc",  
            doc\_type=doc\_type.value,  
            year=year,  
            month=month,  
            page=page,  
            page\_size=page\_size  
        )  
          
        return result  
          
    except ValueError as e:  
        logger.error(f"Validation error: {str(e)}")  
        raise HTTPException(status\_code=400, detail=str(e))  
    except Exception as e:  
        logger.error(f"Error processing FIDC request: {str(e)}", exc\_info=True)  
        raise HTTPException(status\_code=500, detail=f"Internal server error: {str(e)}")

@app.get("/api/v1/fip/{doc\_type}", response\_model=DataResponse)  
async def get\_fip\_data(  
    doc\_type: FIPDocType \= Path(..., description="Type of FIP document"),  
    year: Optional\[int\] \= Query(None, description="Year for the data (required for periodic reports)"),  
    month: Optional\[int\] \= Query(None, ge=1, le=12, description="Month for the data (required for periodic reports)"),  
    page: int \= Query(1, ge=1, description="Page number"),  
    page\_size: int \= Query(config.DEFAULT\_PAGE\_SIZE, ge=1, le=config.MAX\_PAGE\_SIZE, description="Items per page")  
):  
    """Get FIP data by document type"""  
    try:  
        logger.info(f"Request: FIP {doc\_type.value} \- year={year}, month={month}, page={page}, page\_size={page\_size}")  
          
        result \= await data\_service.get\_data(  
            entity="fip",  
            doc\_type=doc\_type.value,  
            year=year,  
            month=month,  
            page=page,  
            page\_size=page\_size  
        )  
          
        return result  
          
    except ValueError as e:  
        logger.error(f"Validation error: {str(e)}")  
        raise HTTPException(status\_code=400, detail=str(e))  
    except Exception as e:  
        logger.error(f"Error processing FIP request: {str(e)}", exc\_info=True)  
        raise HTTPException(status\_code=500, detail=f"Internal server error: {str(e)}")

@app.get("/api/v1/fiagro/{doc\_type}", response\_model=DataResponse)  
async def get\_fiagro\_data(  
    doc\_type: FIAGRODocType \= Path(..., description="Type of FIAGRO document"),  
    year: Optional\[int\] \= Query(None, description="Year for the data (required for periodic reports)"),  
    month: Optional\[int\] \= Query(None, ge=1, le=12, description="Month for the data (required for periodic reports)"),  
    page: int \= Query(1, ge=1, description="Page number"),  
    page\_size: int \= Query(config.DEFAULT\_PAGE\_SIZE, ge=1, le=config.MAX\_PAGE\_SIZE, description="Items per page")  
):  
    """Get FIAGRO data by document type"""  
    try:  
        logger.info(f"Request: FIAGRO {doc\_type.value} \- year={year}, month={month}, page={page}, page\_size={page\_size}")  
          
        result \= await data\_service.get\_data(  
            entity="fiagro",  
            doc\_type=doc\_type.value,  
            year=year,  
            month=month,  
            page=page,  
            page\_size=page\_size  
        )  
          
        return result  
          
    except ValueError as e:  
        logger.error(f"Validation error: {str(e)}")  
        raise HTTPException(status\_code=400, detail=str(e))  
    except Exception as e:  
        logger.error(f"Error processing FIAGRO request: {str(e)}", exc\_info=True)  
        raise HTTPException(status\_code=500, detail=f"Internal server error: {str(e)}")

@app.get("/api/v1/securit/{doc\_type}", response\_model=DataResponse)  
async def get\_securit\_data(  
    doc\_type: SECURITDocType \= Path(..., description="Type of SECURIT document"),  
    year: Optional\[int\] \= Query(None, description="Year for the data (required for periodic reports)"),  
    month: Optional\[int\] \= Query(None, ge=1, le=12, description="Month for the data (required for monthly reports)"),  
    page: int \= Query(1, ge=1, description="Page number"),  
    page\_size: int \= Query(config.DEFAULT\_PAGE\_SIZE, ge=1, le=config.MAX\_PAGE\_SIZE, description="Items per page")  
):  
    """Get SECURIT data by document type"""  
    try:  
        logger.info(f"Request: SECURIT {doc\_type.value} \- year={year}, month={month}, page={page}, page\_size={page\_size}")  
          
        result \= await data\_service.get\_data(  
            entity="securit",  
            doc\_type=doc\_type.value,  
            year=year,  
            month=month,  
            page=page,  
            page\_size=page\_size  
        )  
          
        return result  
          
    except ValueError as e:  
        logger.error(f"Validation error: {str(e)}")  
        raise HTTPException(status\_code=400, detail=str(e))  
    except Exception as e:  
        logger.error(f"Error processing SECURIT request: {str(e)}", exc\_info=True)  
        raise HTTPException(status\_code=500, detail=f"Internal server error: {str(e)}")

@app.exception\_handler(HTTPException)  
async def http\_exception\_handler(request, exc):  
    """Custom HTTP exception handler"""  
    return JSONResponse(  
        status\_code=exc.status\_code,  
        content=ErrorResponse(  
            error=exc.detail,  
            status\_code=exc.status\_code,  
            timestamp=datetime.utcnow().isoformat()  
        ).dict()  
    )

@app.exception\_handler(Exception)  
async def general\_exception\_handler(request, exc):  
    """General exception handler"""  
    logger.error(f"Unhandled exception: {str(exc)}", exc\_info=True)  
    return JSONResponse(  
        status\_code=500,  
        content=ErrorResponse(  
            error="Internal server error",  
            status\_code=500,  
            timestamp=datetime.utcnow().isoformat()  
        ).dict()  
    )

if \_\_name\_\_ \== "\_\_main\_\_":  
    import uvicorn  
    uvicorn.run(app, host="0.0.0.0", port=8000)  
\`\`\`

\---

## requirements.txt

## 

## \`\`\`

# Core Framework

# fastapi==0.109.0

uvicorn\[standard\]==0.27.0  
pydantic==2.5.3  
pydantic-settings==2.1.0

# ASGI Server

# gunicorn==21.2.0

# Database

# sqlalchemy==2.0.25

alembic==1.13.1  
psycopg2-binary==2.9.9  
aiosqlite==0.19.0

# Redis & Caching

# redis==5.0.1

hiredis==2.3.2  
aioredis==2.0.1

# HTTP Client

# httpx==0.26.0

aiohttp==3.9.1  
requests==2.31.0

# Data Processing

# pandas==2.1.4

numpy==1.26.3  
python-dateutil==2.8.2

# Data Validation

# email-validator==2.1.0

python-multipart==0.0.6

# Authentication & Security

# python-jose\[cryptography\]==3.3.0

passlib\[bcrypt\]==1.7.4  
bcrypt==4.1.2  
cryptography==42.0.0

# Environment & Configuration

# python-dotenv==1.0.0

# Logging & Monitoring

# loguru==0.7.2

python-json-logger==2.0.7

# API Documentation

# pydantic\[email\]==2.5.3

# Rate Limiting

# slowapi==0.1.9

# Background Tasks

# celery==5.3.6

flower==2.0.1

# Testing

# pytest==7.4.4

pytest-asyncio==0.23.3  
pytest-cov==4.1.0  
pytest-mock==3.12.0  
httpx==0.26.0  
faker==22.0.0

# Code Quality

# black==23.12.1

flake8==7.0.0  
mypy==1.8.0  
isort==5.13.2  
pylint==3.0.3  
pre-commit==3.6.0

# Data Export

# openpyxl==3.1.2

xlsxwriter==3.1.9

# Utilities

# python-slugify==8.0.1

click==8.1.7  
rich==13.7.0  
tqdm==4.66.1

# Timezone

# pytz==2023.3.post1

# Prometheus Metrics

# prometheus-client==0.19.0

prometheus-fastapi-instrumentator==6.1.0

# Sentry Integration

# sentry-sdk\[fastapi\]==1.39.2

# AWS SDK (Optional)

# boto3==1.34.21

# botocore==1.34.21

# 

# Google Cloud (Optional)

# google-cloud-storage==2.14.0

# 

# Data Compression

# python-snappy==0.6.1

# XML/HTML Parsing

# lxml==5.1.0

beautifulsoup4==4.12.3

# Job Scheduling

# apscheduler==3.10.4

# API Client Generation

# openapi-spec-validator==0.7.1

# Performance

# orjson==3.9.12

ujson==5.9.0

# Database Migrations

# yoyo-migrations==8.2.0

# Health Checks

# py-healthcheck==1.10.1

\`\`\`

\---

## Dockerfile

## 

## \`\`\`dockerfile

# Build stage

# FROM python:3.12-slim AS builder

# Set build arguments

# ARG PYTHON\_VERSION=3.12

ARG BUILD\_DATE  
ARG VCS\_REF

# Labels

# LABEL maintainer="DevOps Team"

LABEL org.opencontainers.image.created=${BUILD\_DATE}  
LABEL org.opencontainers.image.revision=${VCS\_REF}  
LABEL org.opencontainers.image.title="CVM Credit Market API"  
LABEL org.opencontainers.image.description="Brazilian Credit Market Data API from CVM"  
LABEL org.opencontainers.image.version="1.0.0"

# Set environment variables

# ENV PYTHONUNBUFFERED=1 \\

    PYTHONDONTWRITEBYTECODE=1 \\  
    PIP\_NO\_CACHE\_DIR=1 \\  
    PIP\_DISABLE\_PIP\_VERSION\_CHECK=1 \\  
    PIP\_DEFAULT\_TIMEOUT=100 \\  
    POETRY\_VERSION=1.7.1 \\  
    POETRY\_HOME="/opt/poetry" \\  
    POETRY\_NO\_INTERACTION=1 \\  
    POETRY\_VIRTUALENVS\_CREATE=false

# Install system dependencies

# RUN apt-get update && apt-get install \-y \--no-install-recommends \\

    build-essential \\  
    curl \\  
    git \\  
    libpq-dev \\  
    && rm \-rf /var/lib/apt/lists/\*

# Create application directory

# WORKDIR /app

# Copy requirements file

# COPY requirements.txt .

# Install Python dependencies

# RUN pip install \--upgrade pip setuptools wheel && \\

    pip install \--no-cache-dir \-r requirements.txt

# Runtime stage

# FROM python:3.12-slim AS runtime

# Set environment variables

# ENV PYTHONUNBUFFERED=1 \\

    PYTHONDONTWRITEBYTECODE=1 \\  
    PATH="/app/.local/bin:$PATH" \\  
    ENVIRONMENT=production

# Install runtime dependencies

# RUN apt-get update && apt-get install \-y \--no-install-recommends \\

    curl \\  
    ca-certificates \\  
    libpq5 \\  
    tini \\  
    && rm \-rf /var/lib/apt/lists/\* && \\  
    apt-get clean

# Create non-root user

# RUN groupadd \-r appuser && \\

    useradd \-r \-g appuser \-u 1000 \-m \-s /bin/bash appuser && \\  
    mkdir \-p /app /app/data /app/logs && \\  
    chown \-R appuser:appuser /app

# Set working directory

# WORKDIR /app

# Copy Python packages from builder

# COPY \--from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages

COPY \--from=builder /usr/local/bin /usr/local/bin

# Copy application code

# COPY \--chown=appuser:appuser . .

# Switch to non-root user

# USER appuser

# Create necessary directories with correct permissions

# RUN mkdir \-p data logs && \\

    chmod 755 data logs

# Expose port

# EXPOSE 8000

# Health check

# HEALTHCHECK \--interval=30s \--timeout=10s \--start-period=40s \--retries=3 \\

    CMD curl \-f http://localhost:8000/health || exit 1

# Use tini as entrypoint for proper signal handling

# ENTRYPOINT \["/usr/bin/tini", "--"\]

# Run application with uvicorn

# CMD \["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4", "--log-level", "info", "--access-log", "--proxy-headers", "--forwarded-allow-ips", "\*"\]

\`\`\`

\---

## docker-compose.yml

## 

## \`\`\`yaml

version: '3.8'

services:  
  cvm-credit-api:  
    build:  
      context: .  
      dockerfile: Dockerfile  
      args:  
        PYTHON\_VERSION: 3.12  
    image: cvm-credit-api:latest  
    container\_name: cvm-credit-api  
    restart: unless-stopped  
    ports:  
      \- "${API\_PORT:-8000}:8000"  
    environment:  
      \- ENVIRONMENT=${ENVIRONMENT:-production}  
      \- LOG\_LEVEL=${LOG\_LEVEL:-INFO}  
      \- DATABASE\_URL=${DATABASE\_URL:-sqlite:///./cvm\_credit.db}  
      \- REDIS\_URL=${REDIS\_URL:-}  
      \- CACHE\_TTL=${CACHE\_TTL:-3600}  
      \- MAX\_WORKERS=${MAX\_WORKERS:-4}  
      \- API\_TITLE=${API\_TITLE:-CVM Credit Market API}  
      \- API\_VERSION=${API\_VERSION:-1.0.0}  
      \- CORS\_ORIGINS=${CORS\_ORIGINS:-\*}  
      \- RATE\_LIMIT\_ENABLED=${RATE\_LIMIT\_ENABLED:-true}  
      \- RATE\_LIMIT\_REQUESTS=${RATE\_LIMIT\_REQUESTS:-100}  
      \- RATE\_LIMIT\_WINDOW=${RATE\_LIMIT\_WINDOW:-60}  
    volumes:  
      \- ./data:/app/data  
      \- ./logs:/app/logs  
    healthcheck:  
      test: \["CMD", "curl", "-f", "http://localhost:8000/health"\]  
      interval: 30s  
      timeout: 10s  
      retries: 3  
      start\_period: 40s  
    networks:  
      \- cvm-network  
    depends\_on:  
      postgres:  
        condition: service\_healthy  
      redis:  
        condition: service\_healthy

  postgres:  
    image: postgres:16-alpine  
    container\_name: cvm-credit-postgres  
    restart: unless-stopped  
    environment:  
      \- POSTGRES\_USER=${POSTGRES\_USER:-cvmuser}  
      \- POSTGRES\_PASSWORD=${POSTGRES\_PASSWORD:-cvmpassword}  
      \- POSTGRES\_DB=${POSTGRES\_DB:-cvmcredit}  
      \- PGDATA=/var/lib/postgresql/data/pgdata  
    volumes:  
      \- postgres-data:/var/lib/postgresql/data  
    ports:  
      \- "${POSTGRES\_PORT:-5432}:5432"  
    healthcheck:  
      test: \["CMD-SHELL", "pg\_isready \-U ${POSTGRES\_USER:-cvmuser} \-d ${POSTGRES\_DB:-cvmcredit}"\]  
      interval: 10s  
      timeout: 5s  
      retries: 5  
    networks:  
      \- cvm-network  
    profiles:  
      \- with-db

  redis:  
    image: redis:7-alpine  
    container\_name: cvm-credit-redis  
    restart: unless-stopped  
    command: redis-server \--appendonly yes \--requirepass ${REDIS\_PASSWORD:-redispassword}  
    ports:  
      \- "${REDIS\_PORT:-6379}:6379"  
    volumes:  
      \- redis-data:/data  
    healthcheck:  
      test: \["CMD", "redis-cli", "--raw", "incr", "ping"\]  
      interval: 10s  
      timeout: 5s  
      retries: 5  
    networks:  
      \- cvm-network  
    profiles:  
      \- with-cache

  nginx:  
    image: nginx:alpine  
    container\_name: cvm-credit-nginx  
    restart: unless-stopped  
    ports:  
      \- "${NGINX\_PORT:-80}:80"  
      \- "${NGINX\_SSL\_PORT:-443}:443"  
    volumes:  
      \- ./nginx.conf:/etc/nginx/nginx.conf:ro  
      \- ./ssl:/etc/nginx/ssl:ro  
    depends\_on:  
      \- cvm-credit-api  
    networks:  
      \- cvm-network  
    profiles:  
      \- with-nginx

networks:  
  cvm-network:  
    driver: bridge  
    name: cvm-network

volumes:  
  postgres-data:  
    driver: local  
    name: cvm-postgres-data  
  redis-data:  
    driver: local  
    name: cvm-redis-data  
\`\`\`

\---

## README.md

## 

## \`\`\`markdown

# CVM Credit Market API

# 

# A high-performance REST API for accessing Brazilian credit market data from CVM (Comissão de Valores Mobiliários). This service provides comprehensive endpoints for querying credit operations, debentures, and market analytics.

## Features

## 

## \- 🚀 High-performance FastAPI application

\- 🐳 Production-ready Docker setup with multi-stage builds  
\- 📊 Comprehensive credit market data endpoints  
\- 💾 Support for SQLite and PostgreSQL databases  
\- 🔄 Optional Redis caching for improved performance  
\- 📈 Built-in analytics and aggregation endpoints  
\- 🔍 Advanced filtering and pagination  
\- 📝 Automatic API documentation (Swagger/ReDoc)  
\- 🛡️ Rate limiting and security features  
\- 📦 Easy deployment with Docker Compose

Quick Start

Prerequisites

### \- Docker 20.10+

### \- Docker Compose 2.0+

\- (Optional) Python 3.12+ for local development

### Using Docker Compose (Recommended)

### 

### 1\. Clone the repository:

### \`\`\`bash

git clone \<repository-url\>  
cd cvm-credit-api  
\`\`\`

2\. Create environment file:  
\`\`\`bash  
cp .env.example .env

# Edit .env with your configuration

# \`\`\`

# 

# 3\. Start the API (SQLite backend):

\`\`\`bash  
docker-compose up \-d  
\`\`\`

4\. Start with PostgreSQL:  
\`\`\`bash  
docker-compose \--profile with-db up \-d  
\`\`\`

5\. Start with Redis caching:  
\`\`\`bash  
docker-compose \--profile with-cache up \-d  
\`\`\`

6\. Start with all services (PostgreSQL \+ Redis \+ Nginx):  
\`\`\`bash  
docker-compose \--profile with-db \--profile with-cache \--profile with-nginx up \-d  
\`\`\`

7\. Access the API:  
\- API: http://localhost:8000  
\- Swagger UI: http://localhost:8000/docs  
\- ReDoc: http://localhost:8000/redoc  
\- Health Check: http://localhost:8000/health

Local Development

### 1\. Install dependencies:

### \`\`\`bash

pip install \-r requirements.txt  
\`\`\`

2\. Run the application:  
\`\`\`bash  
uvicorn main:app \--reload \--host 0.0.0.0 \--port 8000  
\`\`\`

API Endpoints

## Health & Status

## 

### \#\#\#\# GET /health

### Health check endpoint

Response:  
\`\`\`json  
{  
  "statu**s": "heal**thy",  
  "timestamp": "2024-01-15T10:30:00Z",  
  "version": "1.0.0"  
}  
\`\`\`

\#\#\#\# GET /  
Root endpoint with API information

Response:  
\`\`\`json  
{  
  "messa**ge": "CVM** Credit Market API",  
  "version": "1.0.0",  
  "docs": "/docs",  
  "endpoints": \["/credit-operations", "/statistics", "/health"\]  
}  
\`\`\`

Credit Operations

### \#\#\#\# GET /credit-operations

Retrieve credit operations with filtering and pagination

Query Parameters:  
\- \`skip\` (**int, optional): N**umber of records to skip (default: 0\)  
\- \`limit\` (int, optional): Maximum records to return (default: 100, max: 1000\)  
\- \`issuer\` (str, optional): Filter by issuer name  
\- \`type\` (str, optional): Filter by operation type  
\- \`start\_date\` (date, optional): Filter operations from this date (YYYY-MM-DD)  
\- \`end\_date\` (date, optional): Filter operations until this date (YYYY-MM-DD)  
\- \`min\_amount\` (float, optional): Minimum operation amount  
\- \`max\_amount\` (float, optional): Maximum operation amount  
\- \`status\` (str, optional): Filter by status (active, matured, cancelled)

Example Request:  
\`\`\`bash  
cur**l "http://localh**ost:8000/credit-operations?limit=10\&issuer=Petrobras\&min\_amount=1000000"  
\`\`\`

Example Response:  
\`\`\`json  
{  
  **"total": 150,**  
  "skip": 0,  
  "limit": 10,  
  "data": \[  
    {  
      "id": "12345",  
      "issuer": "Petrobras S.A.",  
      "type": "debenture",  
      "amount": 5000000.00,  
      "issue\_date": "2023-06-15",  
      "maturity\_date": "2028-06-15",  
      "interest\_rate": 8.5,  
      "status": "active",  
      "series": "1",  
      "isin\_code": "BRPETRACNOR1"  
    }  
  \]  
}  
\`\`\`

\#\#\#\# GET /credit-operations/{operation\_id}  
Get details of a specific credit operation

Path Parameters:  
\- \`operatio**n\_id\` (str): Uni**que identifier of the operation

Example Request:  
\`\`\`bash  
cur**l "http://localh**ost:8000/credit-operations/12345"  
\`\`\`

Example Response:  
\`\`\`json  
{  
  **"id": "12345",**  
  "issuer": "Petrobras S.A.",  
  "type": "debenture",  
  "amount": 5000000.00,  
  "issue\_date": "2023-06-15",  
  "maturity\_date": "2028-06-15",  
  "interest\_rate": 8.5,  
  "status": "active",  
  "series": "1",  
  "isin\_code": "BRPETRACNOR1",  
  "guarantees": \["real\_estate", "fiduciary"\],  
  "payment\_schedule": \[\],  
  "metadata": {}  
}  
\`\`\`

Issuers

\#\#\#\# GET /issuers

### List all issuers with their aggregated data

Query Parameters:  
\- \`skip\` (**int, optional): P**agination offset (default: 0\)  
\- \`limit\` (int, optional): Results per page (default: 50\)  
\- \`sort\_by\` (str, optional): Sort field (name, total\_issued, operations\_count)  
\- \`order\` (str, optional): Sort order (asc, desc)

Example Request:  
\`\`\`bash  
cur**l "http://localh**ost:8000/issuers?limit=20\&sort\_by=total\_issued\&order=desc"  
\`\`\`

Example Response:  
\`\`\`json  
{  
  **"total": 500,**  
  "data": \[  
    {  
      "name": "Petrobras S.A.",  
      "cnpj": "33.000.167/0001-01",  
      "total\_issued": 15000000000.00,  
      "operations\_count": 25,  
      "active\_operations": 18,  
      "average\_rate": 7.8,  
      "sectors": \["energy", "oil\_gas"\]  
    }  
  \]  
}  
\`\`\`

\#\#\#\# GET /issuers/{issuer\_id}  
Get detailed information about a specific issuer

Example Request:  
\`\`\`bash  
cur**l "http://localh**ost:8000/issuers/33.000.167%2F0001-01"  
\`\`\`

Statistics

### \#\#\#\# GET /statistics

### Get market statistics and analytics

Query Parameters:  
\- \`period\` **(str, optional):** Time period (day, week, month, year, all)  
\- \`metric\` (str, optional): Specific metric (volume, count, rate)

Example Request:  
\`\`\`bash  
cur**l "http://localh**ost:8000/statistics?period=month"  
\`\`\`

Example Response:  
\`\`\`json  
{  
  **"period": "mont**h",  
  "start\_date": "2024-01-01",  
  "end\_date": "2024-01-31",  
  "total\_operations": 450,  
  "total\_volume": 25000000000.00,  
  "average\_amount": 55555555.56,  
  "average\_interest\_rate": 8.2,  
  "operations\_by\_type": {  
    "debenture": 320,  
    "cra": 80,  
    "cri": 50  
  },  
  "volume\_by\_type": {  
    "debenture": 18000000000.00,  
    "cra": 5000000000.00,  
    "cri": 2000000000.00  
  },  
  "top\_issuers": \[  
    {  
      "name": "Petrobras S.A.",  
      "operations": 12,  
      "volume": 3000000000.00  
    }  
  \]  
}  
\`\`\`

\#\#\#\# GET /statistics/time-series  
Get time-series data for market trends

Query Parameters:  
\- \`start\_d**ate\` (date): Star**t date (YYYY-MM-DD)  
\- \`end\_date\` (date): End date (YYYY-MM-DD)  
\- \`granularity\` (str): Time granularity (day, week, month)  
\- \`metrics\` (list\[str\]): Metrics to include (volume, count, rate)

Example Request:  
\`\`\`bash  
cur**l "http://localh**ost:8000/statistics/time-series?start\_date=2024-01-01\&end\_date=2024-03-31\&granularity=month"  
\`\`\`

Example Response:  
\`\`\`json  
{  
  **"granularity":** "month",  
  "metrics": \["volume", "count"\],  
  "data": \[  
    {  
      "period": "2024-01",  
      "volume": 25000000000.00,  
      "count": 450  
    },  
    {  
      "period": "2024-02",  
      "volume": 28000000000.00,  
      "count": 480  
    }  
  \]  
}  
\`\`\`

Search

\#\#\#\# GET /search

### Full-text search across all operations

Query Parameters:  
\- \`q\` (str**, required): Sear**ch query  
\- \`fields\` (list\[str\], optional): Fields to search (issuer, type, isin\_code)  
\- \`limit\` (int, optional): Results limit (default: 50\)

Example Request:  
\`\`\`bash  
cur**l "http://localh**ost:8000/search?q=Petrobras\&fields=issuer\&limit=10"  
\`\`\`

Export

\#\#\#\# GET /export

### Export data in various formats

Query Parameters:  
\- \`format\` **(str): Export fo**rmat (csv, json, xlsx)  
\- \`filters\` (str, optional): JSON-encoded filter criteria  
\- All credit-operations filters are supported

Example Request:  
\`\`\`bash  
cur**l "http://localh**ost:8000/export?format=csv\&issuer=Petrobras" \-o export.csv  
\`\`\`

Configuration

## Environment Variables

## 

### See \`.env.example\` for all available configuration options.

Key Variables:

\- \`ENVIRONME**NT\`: Runtime e**nvironment (development, production)  
\- \`API\_PORT\`: API server port (default: 8000\)  
\- \`DATABASE\_URL\`: Database connection string  
\- \`REDIS\_URL\`: Redis connection string (optional)  
\- \`LOG\_LEVEL\`: Logging level (DEBUG, INFO, WARNING, ERROR)  
\- \`MAX\_WORKERS\`: Number of Uvicorn workers  
\- \`CACHE\_TTL\`: Cache time-to-live in seconds  
\- \`RATE\_LIMIT\_REQUESTS\`: Max requests per window  
\- \`RATE\_LIMIT\_WINDOW\`: Rate limit window in seconds

Database Configuration

### SQLite (Default):

### \`\`\`env

### DAT**ABASE\_URL=sqlite:**///./data/cvm\_credit.db

\`\`\`

PostgreSQL:  
\`\`\`env  
DATABASE\_**URL=postgre**sql://cvmuser:cvmpassword@postgres:5432/cvmcredit  
\`\`\`

Redis Configuration

\`\`\`env

### REDIS\_URL=redis://:redispassword@redis:6379/0

CACHE\_TTL=3600  
\`\`\`

Docker Commands

## Build Image

## \`\`\`bash

### docker build \-t cvm-credit-api:latest .

\`\`\`

Run Container  
\`\`\`bash

### docker run \-d \-p 8000:8000 \--name cvm-api cvm-credit-api:latest

\`\`\`

View Logs  
\`\`\`bash

### docker-compose logs \-f cvm-credit-api

\`\`\`

Stop Services  
\`\`\`bash

### docker-compose down

\`\`\`

Rebuild and Restart  
\`\`\`bash

### docker-compose up \-d \--build

\`\`\`

### Execute Commands in Container

### \`\`\`bash

### docker-compose exec cvm-credit-api bash

\`\`\`

Monitoring

Health Checks

### The API includes built-in health checks:

\`\`\`bash  
curl http://localhost:8000/health  
\`\`\`

Logs

### Access logs are available in:

\- Docker: \`docker-compose logs \-f\`  
\- Local: \`./logs/\` directory

Metrics

### Enable Prometheus metrics:

\`\`\`env  
ENABLE\_METRICS=true  
METRICS\_PORT=9090  
\`\`\`

Access metrics at: \`http://localhost:9090/metrics\`

Performance Tuning

## Scaling Workers

## 

### Adjust the number of Uvicorn workers:

\`\`\`env  
MAX\_WORKERS=8  
\`\`\`

Or in docker-compose:  
\`\`\`bash  
CMD \["uvicorn", "main:app", "--workers", "8", ...\]  
\`\`\`

Database Connection Pooling

### 

### \`\`\`env

### DB\_POOL\_SIZE=10

### DB\_MAX\_OVERFLOW=20

DB\_POOL\_TIMEOUT=30  
\`\`\`

Redis Caching

### Enable Redis for improved performance:

\`\`\`bash  
docker-compose \--profile with-cache up \-d  
\`\`\`

Security

Rate Limiting

### Configure rate limits:

### \`\`\`env

RATE\_LIMIT\_ENABLED=true  
RATE\_LIMIT\_REQUESTS=100  
RATE\_LIMIT\_WINDOW=60  
\`\`\`

CORS Configuration

### Set allowed origins:

### \`\`\`env

CORS\_ORIGINS=https://yourdomain.com,https://app.yourdomain.com  
\`\`\`

API Keys (Optional)

\`\`\`env

### API\_KEYS=key1,key2,key3

\`\`\`

Use in requests:  
\`\`\`bash  
curl \-H "X-API-Key: key1" http://localhost:8000/credit-operations  
\`\`\`

Backup and Maintenance

## Database Backup (SQLite)

## 

### \`\`\`bash

### docker-compose exec cvm-credit-api sqlite3 /app/data/cvm\_credit.db ".backup '/app/data/backup.db'"

\`\`\`

### Database Backup (PostgreSQL)

### 

### \`\`\`bash

### docker-compose exec postgres pg\_dump \-U cvmuser cvmcredit \> backup.sql

\`\`\`

Data Refresh

### Manual data refresh:

### \`\`\`bash

curl \-X POST http://localhost:8000/admin/refresh-data  
\`\`\`

Automatic refresh (configure in .env):  
\`\`\`env  
AUTO\_REFRESH\_DATA=true  
REFRESH\_CRON\_SCHEDULE=0 2 \* \* \*  
\`\`\`

Troubleshooting

## Container Won't Start

## 

### 1\. Check logs:

### \`\`\`bash

### docker-compose logs cvm-credit-api

\`\`\`

2\. Verify environment variables:  
\`\`\`bash  
docker-compose config  
\`\`\`

3\. Check port conflicts:  
\`\`\`bash  
lsof \-i :8000  
\`\`\`

Database Connection Issues

### 1\. Verify DATABASE\_URL is correct

2\. Check database service health:  
\`\`\`bash  
docker-compose ps  
\`\`\`

3\. Test database connection:  
\`\`\`bash  
docker-compose exec postgres psql \-U cvmuser \-d cvmcredit  
\`\`\`

Performance Issues

### 1\. Enable Redis caching

### 2\. Increase worker count

3\. Check database indexes  
4\. Monitor resource usage:  
\`\`\`bash  
docker stats  
\`\`\`

Development

Running Tests

## \`\`\`bash

### pytest tests/ \-v

### \`\`\`

Code Formatting

\`\`\`bash

### black .

### flake8 .

### mypy .

\`\`\`

Pre-commit Hooks

\`\`\`bash

### pre-commit install

pre-commit run \--all-files  
\`\`\`

API Versioning

## The API supports versioning through URL prefixes:

\- v1: \`http://localhost:8000/api/v1/credit-operations\`  
\- v2: \`http://localhost:8000/api/v2/credit-operations\`

Contributing

## 1\. Fork the repository

## 2\. Create a feature branch

3\. Make your changes  
4\. Add tests  
5\. Submit a pull request

License

## MIT License \- see LICENSE file for details

Support

## For issues and questions:

## \- GitHub Issues: \<repository-url\>/issues

\- Documentation: http://localhost:8000/docs  
\- Email: support@example.com

Changelog

## Version 1.0.0 (2024-01-15)

### \- Initial release

### \- Complete REST API implementation

\- Docker containerization  
\- PostgreSQL and Redis support  
\- Comprehensive documentation  
\- Rate limiting and caching  
\- Health checks and monitoring  
\`\`\`

\---

.env.example

\`\`\`

## Application Configuration

# ENVIRONMENT=production

# API\_TITLE=CVM Credit Market API

API\_VERSION=1.0.0  
API\_PORT=8000

Logging Configuration

# LOG\_LEVEL=INFO

# 

# Database Configuration (Optional \- defaults to SQLite)

# Uncomment and configure for PostgreSQL

# DATABASE\_URL=postgresql://cvmuser:cvmpassword@postgres:5432/cvmcredit

# DATABASE\_URL=sqlite:///./data/cvm\_credit.db

# PostgreSQL Configuration (if using PostgreSQL profile)

# POSTGRES\_USER=cvmuser

# POSTGRES\_PASSWORD=cvmpassword

POSTGRES\_DB=cvmcredit  
POSTGRES\_PORT=5432

# Redis Configuration (Optional \- for caching)

# Uncomment to enable Redis caching

# REDIS\_URL=redis://:redispassword@redis:6379/0

# REDIS\_URL=

# REDIS\_PASSWORD=redispassword

REDIS\_PORT=6379

Cache Configuration

# CACHE\_TTL=3600

# 

# Worker Configuration

# MAX\_WORKERS=4

# 

# CORS Configuration

# Use comma-separated list or \* for all origins

# CORS\_ORIGINS=\*

# CORS\_ORIGINS=http://localhost:3000,https://yourdomain.com

# 

# Rate Limiting Configuration

# RATE\_LIMIT\_ENABLED=true

# RATE\_LIMIT\_REQUESTS=100

RATE\_LIMIT\_WINDOW=60

# Nginx Configuration (if using nginx profile)

# NGINX\_PORT=80

# NGINX\_SSL\_PORT=443

# CVM Data Source Configuration

# CVM\_BASE\_URL=https://dados.cvm.gov.br/dataset

CVM\_DATASET\_ID=fi-cda  
CVM\_UPDATE\_INTERVAL=3600

Security Configuration

# Generate a secure secret key for production

# Example: openssl rand \-hex 32

# SECRET\_KEY=your-secret-key-here-change-in-production

ALGORITHM=HS256  
ACCESS\_TOKEN\_EXPIRE\_MINUTES=30

# API Keys (Optional \- for authentication)

# Comma-separated list of valid API keys

# API\_KEYS=key1,key2,key3

# API\_KEYS=

# 

# Monitoring Configuration (Optional)

# ENABLE\_METRICS=true

# METRICS\_PORT=9090

Performance Tuning

# DB\_POOL\_SIZE=5

# DB\_MAX\_OVERFLOW=10

DB\_POOL\_TIMEOUT=30

Data Refresh Configuration

# AUTO\_REFRESH\_DATA=true

# REFRESH\_CRON\_SCHEDULE=0 2 \* \* \*

Backup Configuration

# BACKUP\_ENABLED=false

# BACKUP\_PATH=./backups

BACKUP\_RETENTION\_DAYS=7

Feature Flags

# ENABLE\_SWAGGER\_UI=true

# ENABLE\_REDOC=true

ENABLE\_API\_VERSIONING=true

External Services

# SENTRY\_DSN=

# DATADOG\_API\_KEY=

Timezone

# TZ=America/Sao\_Paulo

# \`\`\`

# 

# \---

\*Generated: February 2026\*  
