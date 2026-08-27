#!/bin/bash
set -o pipefail

JM_RPC_WALLET_FILE="${JM_RPC_WALLET_FILE:-jm_wallet}"
sed -i "s/^rpc_wallet_file = .*/rpc_wallet_file = ${JM_RPC_WALLET_FILE}/" /home/joinmarket/.joinmarket/joinmarket.cfg
: > /home/joinmarket/jmwalletd.log
echo "Using Bitcoin Core RPC wallet ${JM_RPC_WALLET_FILE}" | tee -a /home/joinmarket/jmwalletd.log

# Starts the RPC server on 28183
attempt=1
max_attempts=30
while [ "${attempt}" -le "${max_attempts}" ]
do
    python3 /usr/local/bin/jmwalletd_entrypoint.py 2>&1 | tee -a /home/joinmarket/jmwalletd.log
    status=${PIPESTATUS[0]}
    if [ "${attempt}" -eq "${max_attempts}" ]; then
        break
    fi
    echo "jmwalletd exited with status ${status}; retry ${attempt}/${max_attempts} in 2 seconds" | tee -a /home/joinmarket/jmwalletd.log
    attempt=$((attempt + 1))
    sleep 2
done

echo "jmwalletd failed after ${max_attempts} attempts; exiting with status ${status}" | tee -a /home/joinmarket/jmwalletd.log
if [ "${status}" -eq 0 ]; then
    exit 1
fi
exit "${status}"
