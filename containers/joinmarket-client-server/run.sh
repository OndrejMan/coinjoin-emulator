#!/bin/bash
set -o pipefail

JM_RPC_WALLET_FILE="${JM_RPC_WALLET_FILE:-jm_wallet}"
sed -i "s/^rpc_wallet_file = .*/rpc_wallet_file = ${JM_RPC_WALLET_FILE}/" /home/joinmarket/.joinmarket/joinmarket.cfg
: > /home/joinmarket/jmwalletd.log
echo "Using Bitcoin Core RPC wallet ${JM_RPC_WALLET_FILE}" | tee -a /home/joinmarket/jmwalletd.log

# Starts the RPC server on 28183
while true
do
    python3 /jm/clientserver/scripts/jmwalletd.py 2>&1 | tee -a /home/joinmarket/jmwalletd.log
    status=${PIPESTATUS[0]}
    echo "jmwalletd exited with status ${status}; retrying in 2 seconds" | tee -a /home/joinmarket/jmwalletd.log
    sleep 2
done
