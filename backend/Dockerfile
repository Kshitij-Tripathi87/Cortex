FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy application code first: an editable install needs the `app` package
# present or setuptools fails with "package directory 'app' does not exist".
# (Copying only pyproject.toml before `pip install -e` broke every build.)
COPY . .

# Install Python dependencies
RUN pip install --no-cache-dir -e ".[dev]"

# Stopping. On SIGTERM (docker stop, a Kubernetes rollout) uvicorn stops
# accepting connections and lets the requests in flight finish. Live streams
# (the realtime feed every signed-in page keeps open) never finish on their
# own, so the wait is bounded: after this many seconds whatever is still open
# is closed and the application shuts down cleanly. Keep it below the
# orchestrator's kill timeout (Docker: 10 s by default; Kubernetes: 30 s).
# uvicorn reads its command-line options from UVICORN_* variables, so this
# also applies where the command is overridden (compose, Kubernetes).
ENV UVICORN_TIMEOUT_GRACEFUL_SHUTDOWN=8

# Expose port
EXPOSE 8000

# Default command (override in docker-compose)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]