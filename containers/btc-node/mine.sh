#!/bin/sh

# Wait for bitcoind to answer; an empty reply used to leave BLOCK_COUNT unset,
# which skipped the whole initialisation and left the node without a wallet.
BLOCK_COUNT=""
while [ -z "$BLOCK_COUNT" ] || [ "$BLOCK_COUNT" = "null" ]
do
    sleep 1
    BLOCK_COUNT=$(curl -s -u user:password --data-binary '{"jsonrpc": "2.0", "method": "getblockcount", "params": []}' -H 'content-type: text/plain;' http://localhost:18443 | jq ".result")
done

if [ "$BLOCK_COUNT" -lt 1001 ]
then
    curl -s -u user:password --data-binary '{"jsonrpc": "2.0", "method": "createwallet", "params": ["wallet"]}' -H 'content-type: text/plain;' http://localhost:18443 > /dev/null

    # Mine first 1001 blocks
    ADDR=$(curl -s -u user:password --data-binary '{"jsonrpc": "2.0", "method": "getnewaddress", "params": ["wallet"]}' -H 'content-type: text/plain;' http://localhost:18443 | jq -r '.result')
    curl -s -u user:password --data-binary "{\"jsonrpc\": \"2.0\", \"method\": \"generatetoaddress\", \"params\": [1001, \"$ADDR\"]}" -H 'content-type: text/plain;' http://localhost:18443 > /dev/null

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
    ADDR=$(curl -s -u user:password --data-binary '{"jsonrpc": "2.0", "method": "getnewaddress", "params": ["wallet"]}' -H 'content-type: text/plain;' http://localhost:18443/wallet/wallet | jq -r '.result')
    curl -s -u user:password --data-binary "{\"jsonrpc\": \"2.0\", \"method\": \"generatetoaddress\", \"params\": [1, \"$ADDR\"]}" -H 'content-type: text/plain;' http://localhost:18443> /dev/null
done
