FROM python:3.11-slim

WORKDIR /app

# Dependencies first for better layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Persistent data lives here (SQLite DB, watchlist, company cache).
# Mount a volume at /app/data in production.
ENV HOST=0.0.0.0 \
    PORT=5000

EXPOSE 5000

CMD ["gunicorn", "-w", "2", "-b", "0.0.0.0:5000", "app:app"]
