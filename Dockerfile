ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.12.1
FROM ${UV_IMAGE} AS uv

FROM python:3.11

ARG TARGETARCH=amd64

RUN apt-get update && apt-get install -y \
    curl \
    wget \
    git \
    && rm -rf /var/lib/apt/lists/*

RUN curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/${TARGETARCH}/kubectl" \
    && chmod +x kubectl \
    && mv kubectl /usr/local/bin/

WORKDIR /app

COPY --from=uv /uv /uvx /bin/

ENV VIRTUAL_ENV=/app/.venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# Locked dependency metadata first, so the layer is cached across source changes.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . .

RUN chmod -R a+rX /app

RUN mkdir /app/logs && chown -R 1000:1000 /app/logs

ENV PYTHONPATH=/app
ENV IN_CLUSTER=true

CMD ["python", "-u", "manager.py", "--help"]
