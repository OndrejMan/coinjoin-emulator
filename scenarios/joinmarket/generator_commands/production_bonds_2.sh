#!/bin/bash

OUT_DIR="scenarios/joinmarket/experiments/production_bonds_2"

# Fidelity Bond Parameters (50% of makers)
BOND_ARGS_1="--enable-fidelity-bonds --bond-percentage-makers 0.01 --bond-min-amount 25000 --bond-max-amount 100000 --bond-min-locktime-months 6 --bond-max-locktime-months 18"
BOND_ARGS_2="--enable-fidelity-bonds --bond-percentage-makers 0.05 --bond-min-amount 25000 --bond-max-amount 100000 --bond-min-locktime-months 6 --bond-max-locktime-months 18"
BOND_ARGS_3="--enable-fidelity-bonds --bond-percentage-makers 0.2 --bond-min-amount 25000 --bond-max-amount 100000 --bond-min-locktime-months 6 --bond-max-locktime-months 18"

# Function to run a scenario with all bond configs
run_scenario() {
  local name=$1
  shift  # Shift to get the rest of the arguments
  
  for i in {1..3}; do
    local bond_var="BOND_ARGS_$i"
    echo "Running $name with bond config $i"
    python manager.py genscen-joinmarket \
      --name "${name}_bond$i" \
      "$@" \
      ${!bond_var} \
      --out-dir "$OUT_DIR"
  done
}

# 1. BASELINE: [9,1] makers, 10 UTXOs with fidelity bonds
run_scenario "baseline_makers_9_1_utxos_10" \
  --maker-count 80 \
  --relative-makers 0 \
  --tumbler-taker-count 4 \
  --taker-count 0 \
  --block-count 500 \
  --tumbler-makercountrange "9,1" \
  --tumbler-stage1-timelambda-increase 2 \
  --wallet-min-utxos 2 \
  --wallet-max-utxos 2 \
  --wallet-min-total-btc 4.0 \
  --wallet-max-total-btc 6.0 \
  --maker-min-absolute-fee 1000 \
  --maker-max-absolute-fee 6000 \
  --maker-min-relative-fee 0.0001 \
  --maker-max-relative-fee 0.0040


echo "Generated all scenarios with fidelity bonds in $OUT_DIR"
echo "Bond configurations:"
echo "1. 10% of makers, small bonds (25,000 - 100,000 sats)"
echo "2. 50% of makers, small bonds (25,000 - 100,000 sats)"
echo "3. 10% of makers, large bonds (25,000 - 100,000,000 sats)"
echo "4. 50% of makers, large bonds (25,000 - 100,000,000 sats)"
echo "  - Bond lock times: 6 - 18 months (YYYY-MM format)"