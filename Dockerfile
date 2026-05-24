# Použijeme Python 3.11 podle tvých požadavků
FROM python:3.11-slim

# Instalace gitu (potřeba pro některé závislosti)
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Nejdříve kopírujeme requirements pro využití Docker cache
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Kopírování zbytku repozitáře
COPY . .

# Výchozí příkaz, který spustí scénář
#  CMD ["python", "manager.py", "run", "--scenario", "scenarios/defaultCoinJoin.json", "--btcFolder", "/home/bitcoin/data"]
CMD ["sh", "-c", "python manager.py clean && python manager.py run --control-ip dind"]