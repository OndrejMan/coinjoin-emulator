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

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV VIRTUAL_ENV=/app/.venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# Dependency metadata first, so the layer is cached across source changes.
COPY pyproject.toml requirements.txt ./
RUN uv venv && uv pip install -r requirements.txt

COPY . .
RUN mkdir /app/logs && chown -R 1000:1000 /app/logs

ENV PYTHONPATH=/app
ENV IN_CLUSTER=true

CMD ["python", "-u", "manager.py", "--help"]
