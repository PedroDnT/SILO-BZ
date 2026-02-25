FROM python:3.12-slim

WORKDIR /app

COPY docs/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY docs/ ./docs/

EXPOSE 8080

CMD ["uvicorn", "docs.docs_server:app", "--host", "0.0.0.0", "--port", "8080"]
