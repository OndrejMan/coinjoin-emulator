#!/bin/bash
set -o pipefail

# Starts the RPC server on 28183
: > /home/joinmarket/jmwalletd.log
while true
do
    python3 /jm/clientserver/scripts/jmwalletd.py 2>&1 | tee -a /home/joinmarket/jmwalletd.log
    status=${PIPESTATUS[0]}
    echo "jmwalletd exited with status ${status}; retrying in 2 seconds" | tee -a /home/joinmarket/jmwalletd.log
    sleep 2
done
