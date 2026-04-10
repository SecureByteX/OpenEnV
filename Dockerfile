FROM python:3.11-slim

LABEL maintainer="openenv-code-review"
LABEL org.opencontainers.image.title="CodeReview OpenEnv"
LABEL org.opencontainers.image.description="OpenEnv environment for AI code review agents"
LABEL org.opencontainers.image.version="1.0.0"

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies (cached layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all application code
COPY server/      ./server/
COPY tasks/       ./tasks/
COPY graders/     ./graders/
COPY tests/       ./tests/
COPY static/      ./static/
COPY openenv.yaml .

# Ensure __init__ files exist
RUN touch server/__init__.py tasks/__init__.py graders/__init__.py tests/__init__.py

# Run tests at build time — build fails if tests fail
RUN PYTHONPATH=/app python -m pytest tests/ -v --tb=short -q \
    && echo "All tests passed."

# Non-root user for HuggingFace Spaces security
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

EXPOSE 7860

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD curl -f http://localhost:7860/health || exit 1

CMD ["uvicorn", "server.app:app", "--host", "0.0.0.0", "--port", "7860", "--workers", "1", "--log-level", "info"]
