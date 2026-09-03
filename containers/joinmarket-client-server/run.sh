#!/bin/bash
set -uo pipefail

MODE=${MODE:-walletd}

if [ "${MODE}" = "obwatch" ]; then
  sed -i "s/^blockchain_source = .*/blockchain_source = no-blockchain/" \
    /home/joinmarket/.joinmarket/joinmarket.cfg
  socat TCP-LISTEN:62601,fork,reuseaddr TCP:127.0.0.1:62602 &
  python3 /jm/clientserver/scripts/obwatch/ob-watcher.py -p 62602 \
    2>&1 | tee -a /home/joinmarket/obwatch.log
  exit "${PIPESTATUS[0]}"
fi

JM_RPC_WALLET_FILE=${JM_RPC_WALLET_FILE:-jm_wallet}
sed -i "s/^rpc_wallet_file = .*/rpc_wallet_file = ${JM_RPC_WALLET_FILE}/" \
  /home/joinmarket/.joinmarket/joinmarket.cfg
: > /home/joinmarket/jmwalletd.log
echo "Using Bitcoin Core RPC wallet ${JM_RPC_WALLET_FILE}" | tee -a /home/joinmarket/jmwalletd.log

# jmwalletd only listens on loopback, so expose it through socat.
socat TCP-LISTEN:28183,fork,reuseaddr TCP:127.0.0.1:28182 &

# Bitcoin Core wallet loading can race container startup. Retain the failed
# attempts in the application log and retry without restarting the container.
attempt=1
max_attempts=30
while [ "${attempt}" -le "${max_attempts}" ]; do
  python3 /usr/local/bin/jmwalletd_entrypoint.py --port 28182 \
    2>&1 | tee -a /home/joinmarket/jmwalletd.log
  status=${PIPESTATUS[0]}
  if [ "${attempt}" -eq "${max_attempts}" ]; then
    break
  fi
  echo "jmwalletd exited with status ${status}; retry ${attempt}/${max_attempts} in 2 seconds" \
    | tee -a /home/joinmarket/jmwalletd.log
  attempt=$((attempt + 1))
  sleep 2
done

echo "jmwalletd failed after ${max_attempts} attempts" | tee -a /home/joinmarket/jmwalletd.log
if [ "${status}" -eq 0 ]; then
  exit 1
fi
exit "${status}"
