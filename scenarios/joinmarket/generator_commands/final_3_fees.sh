#!/bin/bash

OUT_DIR="scenarios/joinmarket/experiments/final_2_fees"

# Quantile values (rounded to single significant digit where appropriate)
# Wallet BTC amounts (converted from satoshis): 0.009, 0.09, 0.5, 2, 10, 200
WALLET_BTC_QUANTILES="0.01,0.1,0.5,2,10,200"
# Taker BTC amounts (suitable for tumbler operations): 0.1, 0.2, 0.5, 1, 2, 3
TAKER_BTC_QUANTILES="0.1,0.2,0.5,1.0,2.0,3.0"
# Absolute fees (satoshis): 60, 200, 700, 2000, 3000, 6000
ABSOLUTE_FEE_QUANTILES="60,200,700,2000,3000,6000"
# Relative fees: 0, 0.0001, 0.0002, 0.0005, 0.002, 0.004
RELATIVE_FEE_QUANTILES="0,0.0001,0.0002,0.0005,0.002,0.004"

# Stagger 8 tumblers starting every 5 blocks to avoid broadcast conflicts
TUMBLER_DELAYS="0,5,10,15,20,25,30,35"

# 1. UTXO COUNT 1
python manager.py genscen-joinmarket  \
  --name "makers_9_1_rel_0_quantiles_staggered" \
  --maker-count 160 \
  --relative-makers 0 \
  --tumbler-taker-count 8 \
  --taker-count 0 \
  --block-count 1000 \
  --tumbler-makercountrange "9,1" \
  --tumbler-stage1-timelambda-increase 2 \
  --tumbler-taker-delays "$TUMBLER_DELAYS" \
  --wallet-min-utxos 10 \
  --wallet-max-utxos 10 \
  --use-quantiles \
  --wallet-btc-quantiles "$WALLET_BTC_QUANTILES" \
  --taker-btc-quantiles "$TAKER_BTC_QUANTILES" \
  --fee-absolute-quantiles "$ABSOLUTE_FEE_QUANTILES" \
  --fee-relative-quantiles "$RELATIVE_FEE_QUANTILES" \
  --out-dir "$OUT_DIR"

# 1. UTXO COUNT 1
python manager.py genscen-joinmarket  \
  --name "makers_9_1_rel_40_quantiles_staggered" \
  --maker-count 160 \
  --relative-makers 40 \
  --tumbler-taker-count 8 \
  --taker-count 0 \
  --block-count 1000 \
  --tumbler-makercountrange "9,1" \
  --tumbler-stage1-timelambda-increase 2 \
  --tumbler-taker-delays "$TUMBLER_DELAYS" \
  --wallet-min-utxos 10 \
  --wallet-max-utxos 10 \
  --use-quantiles \
  --wallet-btc-quantiles "$WALLET_BTC_QUANTILES" \
  --taker-btc-quantiles "$TAKER_BTC_QUANTILES" \
  --fee-absolute-quantiles "$ABSOLUTE_FEE_QUANTILES" \
  --fee-relative-quantiles "$RELATIVE_FEE_QUANTILES" \
  --out-dir "$OUT_DIR"



# 1. UTXO COUNT 1
python manager.py genscen-joinmarket  \
  --name "makers_9_1_rel_80_quantiles_staggered" \
  --maker-count 160 \
  --relative-makers 80 \
  --tumbler-taker-count 8 \
  --taker-count 0 \
  --block-count 1000 \
  --tumbler-makercountrange "9,1" \
  --tumbler-stage1-timelambda-increase 2 \
  --tumbler-taker-delays "$TUMBLER_DELAYS" \
  --wallet-min-utxos 10 \
  --wallet-max-utxos 10 \
  --use-quantiles \
  --wallet-btc-quantiles "$WALLET_BTC_QUANTILES" \
  --taker-btc-quantiles "$TAKER_BTC_QUANTILES" \
  --fee-absolute-quantiles "$ABSOLUTE_FEE_QUANTILES" \
  --fee-relative-quantiles "$RELATIVE_FEE_QUANTILES" \
  --out-dir "$OUT_DIR"



# 1. UTXO COUNT 1
python manager.py genscen-joinmarket  \
  --name "makers_9_1_rel_120_quantiles_staggered" \
  --maker-count 160 \
  --relative-makers 120 \
  --tumbler-taker-count 8 \
  --taker-count 0 \
  --block-count 1000 \
  --tumbler-makercountrange "9,1" \
  --tumbler-stage1-timelambda-increase 2 \
  --tumbler-taker-delays "$TUMBLER_DELAYS" \
  --wallet-min-utxos 10 \
  --wallet-max-utxos 10 \
  --use-quantiles \
  --wallet-btc-quantiles "$WALLET_BTC_QUANTILES" \
  --taker-btc-quantiles "$TAKER_BTC_QUANTILES" \
  --fee-absolute-quantiles "$ABSOLUTE_FEE_QUANTILES" \
  --fee-relative-quantiles "$RELATIVE_FEE_QUANTILES" \
  --out-dir "$OUT_DIR"


# 1. UTXO COUNT 1
python manager.py genscen-joinmarket  \
  --name "makers_9_1_rel_160_quantiles_staggered" \
  --maker-count 160 \
  --relative-makers 160 \
  --tumbler-taker-count 8 \
  --taker-count 0 \
  --block-count 1000 \
  --tumbler-makercountrange "9,1" \
  --tumbler-stage1-timelambda-increase 2 \
  --tumbler-taker-delays "$TUMBLER_DELAYS" \
  --wallet-min-utxos 10 \
  --wallet-max-utxos 10 \
  --use-quantiles \
  --wallet-btc-quantiles "$WALLET_BTC_QUANTILES" \
  --taker-btc-quantiles "$TAKER_BTC_QUANTILES" \
  --fee-absolute-quantiles "$ABSOLUTE_FEE_QUANTILES" \
  --fee-relative-quantiles "$RELATIVE_FEE_QUANTILES" \
  --out-dir "$OUT_DIR"


echo ""
echo "Generated all scenarios with staggered tumbler starts in $OUT_DIR"
echo "Tumbler delays: $TUMBLER_DELAYS (blocks)"
echo "This spreads out 8 tumblers over 35 blocks to reduce broadcast conflicts"
