#!/bin/bash
# Starts the RPC server on 28183
# python3 /jm/clientserver/scripts/jmwalletd.py > /home/joinmarket/jmwalletd.log 2>&1
# commented so the logs will show in kubernetes pod logs

set -euo pipefail

MODE=${MODE:-walletd}

if [ "$MODE" = "obwatch" ]; then
  # ── Orderbook watcher mode ─────────────────────────────────────────────
 socat TCP-LISTEN:62601,fork,reuseaddr TCP:127.0.0.1:62602 &

  # Launch the orderbook watcher on port 62601 (to the outside, 62602 locally)
  # using a no-blockchain config
  # Note: ob-watcher reads JoinMarket config from the default location.
  exec python3 /jm/clientserver/scripts/obwatch/ob-watcher.py \
       -p 62602 \
       2>&1 | tee -a /home/joinmarket/obwatch.log
else
  # ── Wallet daemon mode (default) ───────────────────────────────────────
  # Forward external 28183 → local-loopback 28182
  # Needed because the jmwallet.d does not allow requests from external connections
  socat TCP-LISTEN:28183,fork,reuseaddr TCP:127.0.0.1:28182 &

  # Launch the wallet daemon bound to 127.0.0.1:28182
  exec python3 /jm/clientserver/scripts/jmwalletd.py --port 28182 \
       2>&1 | tee -a /home/joinmarket/jmwalletd.log
fi
