FROM python:3.12-slim AS base

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Runtime stage
FROM base AS runtime

EXPOSE 8001

CMD ["uvicorn", "src.b3_calc_api.main:app", "--host", "0.0.0.0", "--port", "8001"]
