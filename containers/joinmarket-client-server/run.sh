#!/bin/bash
# Starts the RPC server on 28183
# python3 /jm/clientserver/scripts/jmwalletd.py > /home/joinmarket/jmwalletd.log 2>&1
# commented so the logs will show in kubernetes pod logs

set -euo pipefail

MODE=${MODE:-walletd}

if [ "$MODE" = "obwatch" ]; then
  # ── Orderbook watcher mode ─────────────────────────────────────────────
  # Launch the orderbook watcher on port 62601 (to the outside, 62602 locally).
  socat TCP-LISTEN:62601,fork,reuseaddr TCP:127.0.0.1:62602 &
  python3 /jm/clientserver/scripts/obwatch/ob-watcher.py \
    --blockchain-source no-blockchain -p 62602 \
    2>&1 | tee -a /home/joinmarket/obwatch.log
  exit "${PIPESTATUS[0]}"
else
  # ── Wallet daemon mode (default) ───────────────────────────────────────
  # Select the client's Core wallet for address and transaction monitoring.
  JM_RPC_WALLET_FILE=${JM_RPC_WALLET_FILE:-jm_wallet}

  # Forward external 28183 → local-loopback 28182
  # Needed because the jmwallet.d does not allow requests from external connections
  socat TCP-LISTEN:28183,fork,reuseaddr TCP:127.0.0.1:28182 &

  # Launch the wallet daemon bound to 127.0.0.1:28182
  exec python3 /jm/clientserver/scripts/jmwalletd.py \
       --rpc-wallet-file "$JM_RPC_WALLET_FILE" --port 28182 \
       2>&1 | tee -a /home/joinmarket/jmwalletd.log
fi
