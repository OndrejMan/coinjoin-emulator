#!/bin/bash
# Starts the RPC server on 28183
# python3 /jm/clientserver/scripts/jmwalletd.py > /home/joinmarket/jmwalletd.log 2>&1
# commented so the logs will show in kubernetes pod logs

# ── forward external 28183 → local-loopback 28182 ────────────
socat TCP-LISTEN:28183,fork,reuseaddr TCP:127.0.0.1:28182 &

# ── launch the wallet daemon ─────────────
#    * jmwalletd binds to 127.0.0.1 as usual
exec python3 /jm/clientserver/scripts/jmwalletd.py --port 28182 \
     >> /home/joinmarket/jmwalletd.log 2>&1
