FROM python:3.12-slim AS base

WORKDIR /app

# Install dependencies
COPY src/bacen_api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY src/ ./src/

# Expose port
EXPOSE 8002

CMD ["uvicorn", "src.bacen_api.main:app", "--host", "0.0.0.0", "--port", "8002"]
