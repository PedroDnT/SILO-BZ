# B3 CALC API

A FastAPI service for accessing B3 CALC (Brazilian Stock Exchange Fixed Income Calculator) data including debentures, CRAs, CRIs, and financial indexes.

## Features

- **Price Calculations**: Get real-time price calculations for fixed income securities
- **Security Listings**: Browse available debentures, CRAs, and CRIs
- **Financial Indexes**: Access current values for CDI, IPCA, SELIC, and other Brazilian indexes
- **Market Data**: General market data and status information
- **Caching**: 30-minute TTL caching for improved performance
- **Auto-detection**: Automatic security type detection from code format

## API Endpoints

### Core Endpoints

- `GET /api/v1/prices/{symbol}` - Get price data for a security
- `GET /api/v1/indexes` - Get current financial indexes
- `GET /api/v1/market-data` - Get general market data
- `GET /api/v1/securities/{security_type}` - List securities by type

### Utility Endpoints

- `GET /health` - Health check
- `GET /api/v1/` - Available endpoints

## Security Types

- **debentures**: Corporate bonds (e.g., VALE12)
- **cra**: Agribusiness receivables certificates (e.g., 22A0001234-11)
- **cri**: Real estate receivables certificates (e.g., 22A0001111-20)

## Usage Examples

### Get Price for a Debenture
```bash
curl "http://localhost:8001/api/v1/prices/VALE12"
```

### Get Price with Specific Settlement Date
```bash
curl "http://localhost:8001/api/v1/prices/VALE12?settlement_date=2024-01-15"
```

### List Debentures
```bash
curl "http://localhost:8001/api/v1/securities/debentures?page=1&page_size=50"
```

### Search Securities
```bash
curl "http://localhost:8001/api/v1/securities/debentures?search=vale"
```

### Get Financial Indexes
```bash
curl "http://localhost:8001/api/v1/indexes"
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
uvicorn src.b3_calc_api:app --host 0.0.0.0 --port 8001 --reload
```

## Configuration

The API can be configured via environment variables:

- `B3_CALC_BASE_URL`: B3 CALC API base URL (default: https://calculadorarendafixa.com.br/webservice)
- `CACHE_TTL_SECONDS`: Cache TTL in seconds (default: 1800)
- `DEFAULT_PAGE_SIZE`: Default page size for listings (default: 100)
- `MAX_PAGE_SIZE`: Maximum page size (default: 1000)

## Data Sources

- **Primary**: B3 CALC webservice API
- **Fallback**: Sample data for demonstration when API is unavailable

## Caching

- Price data: 30 minutes TTL
- Security lists: 30 minutes TTL
- Index data: 30 minutes TTL

## Error Handling

The API provides comprehensive error handling with appropriate HTTP status codes:

- `400`: Bad request (invalid parameters)
- `404`: Security not found
- `422`: Validation error
- `500`: Internal server error
- `503`: Service unavailable

## Development

### Project Structure
```
b3_calc_api/
├── main.py          # FastAPI application
├── config.py        # Configuration
├── models.py        # Pydantic models
├── services.py      # Business logic
└── requirements.txt # Dependencies
```

### Testing
```bash
pytest tests/ -v
```

### Linting
```bash
black .
isort .
flake8 .
mypy .
```

## Docker

Build and run with Docker:
```bash
docker build -t b3-calc-api .
docker run -p 8001:8001 b3-calc-api
```

## API Documentation

When running, visit `http://localhost:8001/docs` for interactive API documentation.</content>
<parameter name="filePath">/Users/pedrotodescan/Downloads/codebase/src/b3_calc_api/README.md