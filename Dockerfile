FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy only what the server needs (avoids baking secrets/db/firmware creds into a layer).
COPY server/ ./server/
COPY config.json.example ./config.json.example

# Run as a non-root user; data/ holds the SQLite DB + config.json (a named volume
# in docker-compose, which initializes with this user's ownership).
RUN useradd --create-home --uid 10001 appuser \
 && mkdir -p /app/data \
 && chown -R appuser:appuser /app
USER appuser

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python3 -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:5000/api/openapi.json', timeout=4).status==200 else 1)" || exit 1

# Production WSGI server. Flask-SocketIO runs in 'threading' async mode, so a single
# worker with multiple threads serves the dashboard (Socket.IO falls back to HTTP
# long-polling). Keep --workers 1: extra workers would each start a duplicate MQTT
# consumer and double-insert alerts.
CMD ["gunicorn", "--chdir", "server", "--workers", "1", "--threads", "8", \
     "--bind", "0.0.0.0:5000", "--timeout", "120", "main:app"]