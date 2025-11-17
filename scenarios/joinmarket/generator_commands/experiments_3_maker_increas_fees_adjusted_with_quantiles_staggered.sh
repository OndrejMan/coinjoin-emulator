#!/bin/bash

OUT_DIR="scenarios/joinmarket/experiments/experiments_3_maker_increas_fees_adjusted_quantiles_staggered"

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

# 1. BASELINE: [9,1] makers, 10 UTXOs
python manager.py genscen-joinmarket  \
  --name "baseline_makers_9_1_utxos_10_quantiles_staggered" \
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

# 2. MAKER RANGE [5,1]: 4-6 makers
python manager.py genscen-joinmarket  \
  --name "makers_5_1_utxos_10_quantiles_staggered" \
  --maker-count 160 \
  --relative-makers 80 \
  --tumbler-taker-count 8 \
  --taker-count 0 \
  --block-count 1000 \
  --tumbler-makercountrange "5,1" \
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

# 3. MAKER RANGE [7,1]: 6-8 makers
python manager.py genscen-joinmarket  \
  --name "makers_7_1_utxos_10_quantiles_staggered" \
  --maker-count 160 \
  --relative-makers 80 \
  --tumbler-taker-count 8 \
  --taker-count 0 \
  --block-count 1000 \
  --tumbler-makercountrange "7,1" \
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

# 4. MAKER RANGE [9,3]: 6-12 makers (high variance)
python manager.py genscen-joinmarket  \
  --name "makers_9_3_utxos_10_quantiles_staggered" \
  --maker-count 160 \
  --relative-makers 80 \
  --tumbler-taker-count 8 \
  --taker-count 0 \
  --block-count 1000 \
  --tumbler-makercountrange "9,3" \
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

# 5. MAKER RANGE [11,1]: 10-12 makers
python manager.py genscen-joinmarket  \
  --name "makers_11_1_utxos_10_quantiles_staggered" \
  --maker-count 160 \
  --relative-makers 80 \
  --tumbler-taker-count 8 \
  --taker-count 0 \
  --block-count 1000 \
  --tumbler-makercountrange "11,1" \
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

# 6. MAKER RANGE [13,2]: 11-15 makers
python manager.py genscen-joinmarket  \
  --name "makers_13_2_utxos_10_quantiles_staggered" \
  --maker-count 160 \
  --relative-makers 80 \
  --tumbler-taker-count 8 \
  --taker-count 0 \
  --block-count 1000 \
  --tumbler-makercountrange "13,2" \
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

# 7. UTXO COUNT 3
python manager.py genscen-joinmarket  \
  --name "makers_9_1_utxos_3_quantiles_staggered" \
  --maker-count 160 \
  --relative-makers 80 \
  --tumbler-taker-count 8 \
  --taker-count 0 \
  --block-count 1000 \
  --tumbler-makercountrange "9,1" \
  --tumbler-stage1-timelambda-increase 2 \
  --tumbler-taker-delays "$TUMBLER_DELAYS" \
  --wallet-min-utxos 3 \
  --wallet-max-utxos 3 \
  --use-quantiles \
  --wallet-btc-quantiles "$WALLET_BTC_QUANTILES" \
  --taker-btc-quantiles "$TAKER_BTC_QUANTILES" \
  --fee-absolute-quantiles "$ABSOLUTE_FEE_QUANTILES" \
  --fee-relative-quantiles "$RELATIVE_FEE_QUANTILES" \
  --out-dir "$OUT_DIR"

# 8. UTXO COUNT 5
python manager.py genscen-joinmarket  \
  --name "makers_9_1_utxos_5_quantiles_staggered" \
  --maker-count 160 \
  --relative-makers 80 \
  --tumbler-taker-count 8 \
  --taker-count 0 \
  --block-count 1000 \
  --tumbler-makercountrange "9,1" \
  --tumbler-stage1-timelambda-increase 2 \
  --tumbler-taker-delays "$TUMBLER_DELAYS" \
  --wallet-min-utxos 5 \
  --wallet-max-utxos 5 \
  --use-quantiles \
  --wallet-btc-quantiles "$WALLET_BTC_QUANTILES" \
  --taker-btc-quantiles "$TAKER_BTC_QUANTILES" \
  --fee-absolute-quantiles "$ABSOLUTE_FEE_QUANTILES" \
  --fee-relative-quantiles "$RELATIVE_FEE_QUANTILES" \
  --out-dir "$OUT_DIR"

# 9. UTXO COUNT 15
python manager.py genscen-joinmarket  \
  --name "makers_9_1_utxos_15_quantiles_staggered" \
  --maker-count 160 \
  --relative-makers 80 \
  --tumbler-taker-count 8 \
  --taker-count 0 \
  --block-count 1000 \
  --tumbler-makercountrange "9,1" \
  --tumbler-stage1-timelambda-increase 2 \
  --tumbler-taker-delays "$TUMBLER_DELAYS" \
  --wallet-min-utxos 15 \
  --wallet-max-utxos 15 \
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
