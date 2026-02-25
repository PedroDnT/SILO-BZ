# CVM Credit Market API

A FastAPI service for accessing Brazilian CVM (Comissão de Valores Mobiliários) credit market data, including FIDC, FIP, FIAGRO, and SECURIT entities.

## Features

- **Entity Support**: Data for FIDC, FIP, FIAGRO, and SECURIT.
- **Document Types**: Access to cadastral, monthly, quarterly, and annual documents.
- **Automated Fetching**: Downloads data directly from CVM's Open Data Portal.
- **CSV/ZIP Parsing**: Handles in-memory parsing of CVM's semicolon-delimited CSV files.
- **Pagination**: Configurable pagination for large datasets.

## API Endpoints

### Core Endpoints

- `GET /api/v1/cvm/{entity}/{doc_type}` - Get data for a specific entity and document type.
- `GET /api/v1/cvm/fidc/cadastral` - Get cadastral data for FIDC funds.
- `GET /api/v1/cvm/fip/cadastral` - Get cadastral data for FIP funds.

### Query Parameters

- `year`: Optional year for historical data.
- `month`: Optional month for historical data.
- `page`: Page number (default: 1).
- `page_size`: Results per page (default: 100).

## Usage Examples

### Get FIDC Cadastral Data
```bash
curl "http://localhost:8000/api/v1/cvm/fidc/cadastral?page=1&page_size=10"
```

### Get Monthly Information for FIDC (Dec 2023)
```bash
curl "http://localhost:8000/api/v1/cvm/fidc/mensal?year=2023&month=12"
```

## Installation

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Run the API:
```bash
# Navigate to the workspace root
# Run using uvicorn pointing to the module
uvicorn src.cvm_api.main:app --host 0.0.0.0 --port 8000 --reload
```

## Configuration

The API configuration is managed in `config.py`. Key settings:

- `CVM_BASE_URL`: https://dados.cvm.gov.br/dados
- `DEFAULT_PAGE_SIZE`: 100
- `ENCODING`: latin-1
- `CSV_SEPARATOR`: ;

## Docker

Build and run with Docker:
```bash
docker build -t cvm-api -f src/cvm_api/Dockerfile .
docker run -p 8000:8000 cvm-api
```

## API Documentation

When running, visit `http://localhost:8000/docs` for interactive OpenAPI documentation.
