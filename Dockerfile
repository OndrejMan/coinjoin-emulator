# Použijeme Python 3.11 podle tvých požadavků
FROM python:3.11-slim

# Instalace gitu a uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

WORKDIR /app
ENV VIRTUAL_ENV=/app/.venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# Nejdříve kopírujeme metadata závislostí pro využití Docker cache
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-cache

# Kopírování zbytku repozitáře
COPY . .

# Local source trees can contain owner-only files (for example after a
# restrictive umask). Kubernetes-backed runs execute the manager as a
# non-root user, so normalize runtime readability inside the image.
RUN chmod -R a+rX /app

# Výchozí příkaz, který spustí scénář
#  CMD ["python", "manager.py", "run", "--scenario", "scenarios/defaultCoinJoin.json", "--btcFolder", "/home/bitcoin/data"]
CMD ["sh", "-c", "uv run python manager.py clean && uv run python manager.py run --control-ip dind"]
