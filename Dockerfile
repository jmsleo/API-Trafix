FROM python:3.13-slim

WORKDIR /app

# Install system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev postgresql-client && \
    rm -rf /var/lib/apt/lists/*

# Copy dependency files and readme (needed by pyproject.toml)
COPY pyproject.toml uv.lock README.md ./

# Install uv and dependencies
RUN pip install --no-cache-dir uv && \
    uv sync --frozen --no-dev --no-install-project

# Copy source code
COPY src/ src/
COPY static/ static/
COPY migrations/ migrations/
COPY deploy/ deploy/

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "api_trafix.main:app", "--host", "0.0.0.0", "--port", "8000"]
