# BACEN Data API

FastAPI service exposing Banco Central do Brasil (BCB) public data via [python-bcb](https://github.com/wilsonfreitas/python-bcb).

## Quick start

```bash
uvicorn src.bacen_api.main:app --host 0.0.0.0 --port 8002 --reload
```

Swagger UI: http://localhost:8002/docs

---

## Endpoints

### SGS – Time Series

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/bacen/sgs/well-known` | List well-known series codes |
| GET | `/api/v1/bacen/sgs/{series_code}` | Single series (e.g. `433` = IPCA) |
| GET | `/api/v1/bacen/sgs/multi?codes=IPCA:433,CDI:12` | Multiple series, aligned by date |

**Query parameters** for single/multi: `start`, `end` (ISO dates), `last` (last N observations).

Popular SGS codes:

| Label | Code |
|-------|------|
| SELIC meta | 432 |
| SELIC diária | 11 |
| CDI | 12 |
| IPCA | 433 |
| IGP-M | 189 |
| USD/BRL | 1 |
| EUR/BRL | 21619 |

### PTAX – Exchange Rates

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/bacen/ptax/dolar?date=YYYY-MM-DD` | USD/BRL rate for a specific date |
| GET | `/api/v1/bacen/ptax/dolar/periodo?start=&end=` | USD/BRL daily rates for a range |
| GET | `/api/v1/bacen/ptax/moeda/{moeda}?date=` | Any currency/BRL for a date |
| GET | `/api/v1/bacen/ptax/moeda/{moeda}/periodo?start=&end=` | Any currency/BRL range |
| GET | `/api/v1/bacen/ptax/moedas` | List all available PTAX currencies |

### Expectativas – Focus Market Expectations

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/bacen/expectativas` | List available expectation endpoints |
| GET | `/api/v1/bacen/expectativas/{endpoint_name}` | Query Focus data |

Available `endpoint_name` values:
- `ExpectativasMercadoAnuais`
- `ExpectativasMercadoMensais`
- `ExpectativasMercadoTrimestrais`
- `ExpectativasMercadoSelic`
- `ExpectativasMercadoTop5Anuais`
- `ExpectativasMercadoTop5Mensais`
- `ExpectativasMercadoInflacao12Meses`
- `InstituicoesCreditoras`

Query parameters: `indicador` (e.g. `IPCA`, `Selic`), `start` (ISO date), `limit`.

### TaxaJuros – Interest Rates

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/bacen/taxas_juros/{endpoint_name}?limit=` | Interest-rate data (e.g. `TaxasJurosMercadoImobiliario`) |

---

## Configuration

| Env var | Default | Description |
|---------|---------|-------------|
| `BACEN_API_HOST` | `0.0.0.0` | Bind host |
| `BACEN_API_PORT` | `8002` | Bind port |
| `LOG_LEVEL` | `info` | Uvicorn log level |

---

## Docker

```bash
docker build -f src/bacen_api/Dockerfile -t bacen-api .
docker run -p 8002:8002 bacen-api
```

Or with Compose:

```bash
docker compose up bacen_api
```
