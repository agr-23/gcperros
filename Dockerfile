# El motor como servicio de Cloud Run (infra/terraform/cloud_run.tf). En local:
#   docker run -p 8080:8080 gcperros-engine gcperros-engine-service --memory
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=8080

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir ".[service]" \
    && useradd --create-home --uid 10001 motor

# Sin privilegios: el servicio no necesita escribir nada en el disco.
USER motor
EXPOSE 8080
CMD ["gcperros-engine-service"]
