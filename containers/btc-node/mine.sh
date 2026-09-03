#!/bin/sh

BLOCK_COUNT=""
INITIAL_BLOCK_COUNT="${COINJOIN_INITIAL_BLOCK_COUNT:-1001}"
BITCOIND_READY_TIMEOUT_SECONDS=60
BITCOIND_READY_DEADLINE=$(( $(date +%s) + BITCOIND_READY_TIMEOUT_SECONDS ))

while [ -z "$BLOCK_COUNT" ] || [ "$BLOCK_COUNT" = "null" ]
do
    CURRENT_TIME=$(date +%s)
    if [ "$CURRENT_TIME" -ge "$BITCOIND_READY_DEADLINE" ]
    then
        echo "Timed out waiting ${BITCOIND_READY_TIMEOUT_SECONDS}s for bitcoind RPC at localhost:18443" >&2
        exit 1
    fi
    sleep 1
    BLOCK_COUNT=$(curl --max-time 5 -s -u user:password --data-binary '{"jsonrpc": "2.0", "id": "initial-block-count", "method": "getblockcount", "params": []}' -H 'content-type: text/plain;' http://localhost:18443 | jq ".result")
done

if [ "$BLOCK_COUNT" -lt "$INITIAL_BLOCK_COUNT" ]
then
    curl -s -u user:password --data-binary '{"jsonrpc": "2.0", "id": "create-wallet", "method": "createwallet", "params": ["wallet"]}' -H 'content-type: text/plain;' http://localhost:18443 > /dev/null

    # Mine only the missing blocks for mature coinbase outputs. The default
    # provides a realistic history; a constrained integration run can use a
    # smaller explicit value to shorten Wasabi's initial filter download.
    BLOCKS_TO_MINE=$((INITIAL_BLOCK_COUNT - BLOCK_COUNT))
    ADDR=$(curl -s -u user:password --data-binary '{"jsonrpc": "2.0", "id": "initial-address", "method": "getnewaddress", "params": ["wallet"]}' -H 'content-type: text/plain;' http://localhost:18443 | jq -r '.result')
    curl -s -u user:password --data-binary "{\"jsonrpc\": \"2.0\", \"id\": \"initial-blocks\", \"method\": \"generatetoaddress\", \"params\": [$BLOCKS_TO_MINE, \"$ADDR\"]}" -H 'content-type: text/plain;' http://localhost:18443 > /dev/null

    # Build a fee history so estimatesmartfee returns an estimate; the Wasabi
    # backend refuses to start without one.
    # taken from https://bitcoin.stackexchange.com/a/107319
    cont=true
    smartfee=$(bitcoin-cli estimatesmartfee 6)
    if [[ "$smartfee" == *"\"feerate\":"* ]]; then
        cont=false
    fi
    while $cont
    do
        counterb=0
        range=$(( $RANDOM % 11 + 20 ))
        while [ $counterb -lt $range ]
        do
            power=$(( $RANDOM % 29 ))
            randfee=`echo "scale=8; 0.00001 * (1.1892 ^ $power)" | bc`
            newaddress=$(bitcoin-cli getnewaddress)
            rawtx=$(bitcoin-cli createrawtransaction "[]" "[{\"$newaddress\":0.005}]")
            fundedtx=$(bitcoin-cli fundrawtransaction "$rawtx" "{\"feeRate\": \"0$randfee\"}" | jq -r ".hex")
            signedtx=$(bitcoin-cli signrawtransactionwithwallet "$fundedtx" | jq -r ".hex")
            senttx=$(bitcoin-cli sendrawtransaction "$signedtx")
            counterb=$((counterb + 1))
            echo "Created $counterb transactions this block"
        done
        bitcoin-cli generatetoaddress 1 $ADDR
        smartfee=$(bitcoin-cli estimatesmartfee 6)
        if [[ "$smartfee" == *"\"feerate\":"* ]]; then
            cont=false
        fi
    done
    bitcoin-cli generatetoaddress 6 $ADDR
fi

# Mine new block periodically
while true
do
    sleep $(($RANDOM % 60 + 30))
    ADDR=$(curl -s -u user:password --data-binary '{"jsonrpc": "2.0", "id": "periodic-address", "method": "getnewaddress", "params": ["wallet"]}' -H 'content-type: text/plain;' http://localhost:18443/wallet/wallet | jq -r '.result')
    curl -s -u user:password --data-binary "{\"jsonrpc\": \"2.0\", \"id\": \"periodic-block\", \"method\": \"generatetoaddress\", \"params\": [1, \"$ADDR\"]}" -H 'content-type: text/plain;' http://localhost:18443> /dev/null
done
