FROM python:3.11-slim
WORKDIR /app
COPY src/db/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
# Copy full src/ so alembic env.py can import src.db.models
COPY src/ ./src/
# alembic.ini lives at src/db/alembic.ini; run from /app so src.db.models is importable
CMD ["alembic", "-c", "src/db/alembic.ini", "upgrade", "head"]
