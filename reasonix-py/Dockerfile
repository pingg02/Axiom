FROM python:3.12-slim

WORKDIR /app

# Install system deps
RUN apt-get update && apt-get install -y --no-install-recommends gcc && \
    rm -rf /var/lib/apt/lists/*

# Install Python deps
COPY pyproject.toml .
RUN pip install --no-cache-dir .

# Copy source
COPY reasonix/ reasonix/
COPY tests/ tests/

# Default port
EXPOSE 8080 9092

# Start both FastAPI and WebSocket server
CMD ["python", "-m", "reasonix", "serve"]
