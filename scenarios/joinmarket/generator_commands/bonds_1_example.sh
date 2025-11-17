OUT_DIR="scenarios/joinmarket/experiments/experiments_3_maker_increas_fees_adjusted_with_bonds"

# Fidelity Bond Parameters (50% of makers)
BOND_ARGS="--enable-fidelity-bonds --bond-percentage-makers 0.9 --bond-min-amount 25000 --bond-max-amount 100000 --bond-min-locktime-months 6 --bond-max-locktime-months 18"

# 1. BASELINE: [9,1] makers, 10 UTXOs with fidelity bonds
python manager.py genscen-joinmarket  \
  --name "baseline_makers_9_1_utxos_10_bonds" \
  --maker-count 30 \
  --relative-makers 2 \
  --tumbler-taker-count 0 \
  --taker-count 1 \
  --block-count 1000 \
  --tumbler-makercountrange "9,1" \
  --tumbler-stage1-timelambda-increase 2 \
  --wallet-min-utxos 2 \
  --wallet-max-utxos 3 \
  --wallet-min-total-btc 4.0 \
  --wallet-max-total-btc 6.0 \
  --maker-min-absolute-fee 1000 \
  --maker-max-absolute-fee 6000 \
  --maker-min-relative-fee 0.0001 \
  --maker-max-relative-fee 0.0040 \
  $BOND_ARGS \
  --out-dir "$OUT_DIR"