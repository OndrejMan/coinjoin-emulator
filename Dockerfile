# Použijeme Python 3.11 podle tvých požadavků
FROM python:3.11-slim

# Instalace gitu a uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Nejdříve kopírujeme metadata závislostí pro využití Docker cache
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-cache

# Kopírování zbytku repozitáře
COPY . .

# Výchozí příkaz, který spustí scénář
#  CMD ["python", "manager.py", "run", "--scenario", "scenarios/defaultCoinJoin.json", "--btcFolder", "/home/bitcoin/data"]
CMD ["sh", "-c", "uv run python manager.py clean && uv run python manager.py run --control-ip dind"]
