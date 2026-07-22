FROM python:3.12-slim
WORKDIR /app

# Build context is portal/ (see portal/railway.json). Paths below are
# relative to portal/ so the summaries file (read by config.py as
# /app/summaries.json) is included alongside the backend package.
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./backend/
COPY summaries.json ./summaries.json

# Railway (and most PaaS) inject $PORT; fall back to 8001 for local runs.
EXPOSE 8001
CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8001}"]
