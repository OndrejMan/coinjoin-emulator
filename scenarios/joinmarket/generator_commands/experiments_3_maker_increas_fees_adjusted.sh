#!/bin/bash

OUT_DIR="scenarios/joinmarket/experiments/experiments_3_maker_increas_fees_adjusted"

# 1. BASELINE: [9,1] makers, 10 UTXOs
python manager.py genscen-joinmarket  \
  --name "baseline_makers_9_1_utxos_10" \
  --maker-count 160 \
  --relative-makers 80 \
  --tumbler-taker-count 8 \
  --taker-count 0 \
  --block-count 1000 \
  --tumbler-makercountrange "9,1" \
  --tumbler-stage1-timelambda-increase 2 \
  --wallet-min-utxos 10 \
  --wallet-max-utxos 10 \
  --wallet-min-total-btc 4.0 \
  --wallet-max-total-btc 6.0 \
  --maker-min-absolute-fee 1000 \
  --maker-max-absolute-fee 6000 \
  --maker-min-relative-fee 0.0001 \
  --maker-max-relative-fee 0.0040 \
  --out-dir "$OUT_DIR"

# 2. MAKER RANGE [5,1]: 4-6 makers
python manager.py genscen-joinmarket  \
  --name "makers_5_1_utxos_10" \
  --maker-count 160 \
  --relative-makers 80 \
  --tumbler-taker-count 8 \
  --taker-count 0 \
  --block-count 1000 \
  --tumbler-makercountrange "5,1" \
  --tumbler-stage1-timelambda-increase 2 \
  --wallet-min-utxos 10 \
  --wallet-max-utxos 10 \
  --wallet-min-total-btc 4.0 \
  --wallet-max-total-btc 6.0 \
  --maker-min-absolute-fee 1000 \
  --maker-max-absolute-fee 6000 \
  --maker-min-relative-fee 0.0001 \
  --maker-max-relative-fee 0.001 \
  --out-dir "$OUT_DIR"

# 3. MAKER RANGE [7,1]: 6-8 makers
python manager.py genscen-joinmarket  \
  --name "makers_7_1_utxos_10" \
  --maker-count 160 \
  --relative-makers 80 \
  --tumbler-taker-count 8 \
  --taker-count 0 \
  --block-count 1000 \
  --tumbler-makercountrange "7,1" \
  --tumbler-stage1-timelambda-increase 2 \
  --wallet-min-utxos 10 \
  --wallet-max-utxos 10 \
  --wallet-min-total-btc 4.0 \
  --wallet-max-total-btc 6.0 \
  --maker-min-absolute-fee 1000 \
  --maker-max-absolute-fee 6000 \
  --maker-min-relative-fee 0.0001 \
  --maker-max-relative-fee 0.001 \
  --out-dir "$OUT_DIR"

# 4. MAKER RANGE [9,3]: 6-12 makers (high variance)
python manager.py gensmincen-joinmarket  \
  --name "makers_9_3_utxos_10" \
  --maker-count 160 \
  --relative-makers 80 \
  --tumbler-taker-count 8 \
  --taker-count 0 \
  --block-count 1000 \
  --tumbler-makercountrange "9,3" \
  --tumbler-stage1-timelambda-increase 2 \
  --wallet-min-utxos 10 \
  --wallet-max-utxos 10 \
  --wallet-min-total-btc 4.0 \
  --wallet-max-total-btc 6.0 \
  --maker-min-absolute-fee 1000 \
  --maker-max-absolute-fee 6000 \
  --maker-min-relative-fee 0.0001 \
  --maker-max-relative-fee 0.001 \
  --out-dir "$OUT_DIR"

# 5. MAKER RANGE [11,1]: 10-12 makers
python manager.py genscen-joinmarket  \
  --name "makers_11_1_utxos_10" \
  --maker-count 160 \
  --relative-makers 80 \
  --tumbler-taker-count 8 \
  --taker-count 0 \
  --block-count 1000 \
  --tumbler-makercountrange "11,1" \
  --tumbler-stage1-timelambda-increase 2 \
  --wallet-min-utxos 10 \
  --wallet-max-utxos 10 \
  --wallet-min-total-btc 4.0 \
  --wallet-max-total-btc 6.0 \
  --maker-min-absolute-fee 1000 \
  --maker-max-absolute-fee 6000 \
  --maker-min-relative-fee 0.0001 \
  --maker-max-relative-fee 0.001 \
  --out-dir "$OUT_DIR"

# 6. MAKER RANGE [13,2]: 11-15 makers
python manager.py genscen-joinmarket  \
  --name "makers_13_2_utxos_10" \
  --maker-count 160 \
  --relative-makers 80 \
  --tumbler-taker-count 8 \
  --taker-count 0 \
  --block-count 1000 \
  --tumbler-makercountrange "13,2" \
  --tumbler-stage1-timelambda-increase 2 \
  --wallet-min-utxos 10 \
  --wallet-max-utxos 10 \
  --wallet-min-total-btc 4.0 \
  --wallet-max-total-btc 6.0 \
  --maker-min-absolute-fee 1000 \
  --maker-max-absolute-fee 6000 \
  --maker-min-relative-fee 0.0001 \
  --maker-max-relative-fee 0.001 \
  --out-dir "$OUT_DIR"

# 7. UTXO COUNT 3
python manager.py genscen-joinmarket  \
  --name "makers_9_1_utxos_3" \
  --maker-count 160 \
  --relative-makers 80 \
  --tumbler-taker-count 8 \
  --taker-count 0 \
  --block-count 1000 \
  --tumbler-makercountrange "9,1" \
  --tumbler-stage1-timelambda-increase 2 \
  --wallet-min-utxos 3 \
  --wallet-max-utxos 3 \
  --wallet-min-total-btc 4.0 \
  --wallet-max-total-btc 6.0 \
  --maker-min-absolute-fee 1000 \
  --maker-max-absolute-fee 6000 \
  --maker-min-relative-fee 0.0001 \
  --maker-max-relative-fee 0.001 \
  --out-dir "$OUT_DIR"

# 8. UTXO COUNT 5
python manager.py genscen-joinmarket  \
  --name "makers_9_1_utxos_5" \
  --maker-count 160 \
  --relative-makers 80 \
  --tumbler-taker-count 8 \
  --taker-count 0 \
  --block-count 1000 \
  --tumbler-makercountrange "9,1" \
  --tumbler-stage1-timelambda-increase 2 \
  --wallet-min-utxos 5 \
  --wallet-max-utxos 5 \
  --wallet-min-total-btc 4.0 \
  --wallet-max-total-btc 6.0 \
  --maker-min-absolute-fee 1000 \
  --maker-max-absolute-fee 6000 \
  --maker-min-relative-fee 0.0001 \
  --maker-max-relative-fee 0.001 \
  --out-dir "$OUT_DIR"

# 9. UTXO COUNT 15
python manager.py genscen-joinmarket  \
  --name "makers_9_1_utxos_15" \
  --maker-count 160 \
  --relative-makers 80 \
  --tumbler-taker-count 8 \
  --tumbler-stage1-timelambda-increase 2 \
  --taker-count 0 \
  --block-count 1000 \
  --tumbler-makercountrange "9,1" \
  --wallet-min-utxos 15 \
  --wallet-max-utxos 15 \
  --wallet-min-total-btc 4.0 \
  --wallet-max-total-btc 6.0 \
  --maker-min-absolute-fee 1000 \
  --maker-max-absolute-fee 6000 \
  --maker-min-relative-fee 0.0001 \
  --maker-max-relative-fee 0.001 \
  --out-dir "$OUT_DIR"