FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

# Install dependencies
COPY src/b3_calc_api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY src/ ./src/

EXPOSE 8001

CMD ["uvicorn", "src.b3_calc_api.main:app", "--host", "0.0.0.0", "--port", "8001"]
