#!/bin/bash

OUT_DIR="scenarios/joinmarket/experiments/experiments_3_maker_increas_fees_adjusted_with_bonds"

# Fidelity Bond Parameters (50% of makers)
BOND_ARGS="--enable-fidelity-bonds --bond-percentage-makers 0.9 --bond-min-amount 25000 --bond-max-amount 100000 --bond-min-locktime-months 6 --bond-max-locktime-months 18"

# 1. BASELINE: [9,1] makers, 10 UTXOs with fidelity bonds
python manager.py genscen-joinmarket  \
  --name "baseline_makers_9_1_utxos_10_bonds" \
  --maker-count 160 \
  --relative-makers 80 \
  --tumbler-taker-count 8 \
  --taker-count 0 \
  --block-count 1000 \
  --tumbler-makercountrange "9,1" \
  --tumbler-stage1-timelambda-increase 2 \
  --wallet-min-utxos 2 \
  --wallet-max-utxos 2 \
  --wallet-min-total-btc 4.0 \
  --wallet-max-total-btc 6.0 \
  --maker-min-absolute-fee 1000 \
  --maker-max-absolute-fee 6000 \
  --maker-min-relative-fee 0.0001 \
  --maker-max-relative-fee 0.0040 \
  $BOND_ARGS \
  --out-dir "$OUT_DIR"

# 2. MAKER RANGE [5,1]: 4-6 makers with fidelity bonds
python manager.py genscen-joinmarket  \
  --name "makers_5_1_utxos_10_bonds" \
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
  $BOND_ARGS \
  --out-dir "$OUT_DIR"

# 3. MAKER RANGE [7,1]: 6-8 makers with fidelity bonds
python manager.py genscen-joinmarket  \
  --name "makers_7_1_utxos_10_bonds" \
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
  $BOND_ARGS \
  --out-dir "$OUT_DIR"

# 4. MAKER RANGE [9,3]: 6-12 makers (high variance) with fidelity bonds
python manager.py genscen-joinmarket  \
  --name "makers_9_3_utxos_10_bonds" \
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
  $BOND_ARGS \
  --out-dir "$OUT_DIR"

# 5. MAKER RANGE [11,1]: 10-12 makers with fidelity bonds
python manager.py genscen-joinmarket  \
  --name "makers_11_1_utxos_10_bonds" \
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
  $BOND_ARGS \
  --out-dir "$OUT_DIR"

# 6. MAKER RANGE [13,2]: 11-15 makers with fidelity bonds
python manager.py genscen-joinmarket  \
  --name "makers_13_2_utxos_10_bonds" \
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
  $BOND_ARGS \
  --out-dir "$OUT_DIR"

# 7. UTXO COUNT 3 with fidelity bonds
python manager.py genscen-joinmarket  \
  --name "makers_9_1_utxos_3_bonds" \
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
  $BOND_ARGS \
  --out-dir "$OUT_DIR"

# 8. UTXO COUNT 5 with fidelity bonds
python manager.py genscen-joinmarket  \
  --name "makers_9_1_utxos_5_bonds" \
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
  $BOND_ARGS \
  --out-dir "$OUT_DIR"

# 9. UTXO COUNT 15 with fidelity bonds
python manager.py genscen-joinmarket  \
  --name "makers_9_1_utxos_15_bonds" \
  --maker-count 160 \
  --relative-makers 80 \
  --tumbler-taker-count 8 \
  --taker-count 0 \
  --block-count 1000 \
  --tumbler-makercountrange "9,1" \
  --tumbler-stage1-timelambda-increase 2 \
  --wallet-min-utxos 15 \
  --wallet-max-utxos 15 \
  --wallet-min-total-btc 4.0 \
  --wallet-max-total-btc 6.0 \
  --maker-min-absolute-fee 1000 \
  --maker-max-absolute-fee 6000 \
  --maker-min-relative-fee 0.0001 \
  --maker-max-relative-fee 0.001 \
  $BOND_ARGS \
  --out-dir "$OUT_DIR"

echo "Generated all scenarios with fidelity bonds (50% of makers) in $OUT_DIR"
echo "Bond configuration:"
echo "  - 50% of makers will have fidelity bonds"
echo "  - Bond amounts: 25,000 - 100,000 satoshis"
echo "  - Bond lock times: 6 - 18 months (YYYY-MM format)"