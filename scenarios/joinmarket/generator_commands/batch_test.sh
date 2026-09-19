#!/bin/bash

# Batch test scenarios: 1 tumbler, 2 makers, 10 blocks each

# 1. Basic scenario with 2 makers, 5 UTXOs
python manager.py genscen-joinmarket \
  --name "batch_test_1_60_blocks" \
  --maker-count 2 \
  --relative-makers 2 \
  --tumbler-taker-count 1 \
  --taker-count 0 \
  --block-count 60 \
  --tumbler-makercountrange "2,0" \
  --wallet-min-utxos 5 \
  --wallet-max-utxos 5 \
  --wallet-min-total-btc 4.0 \
  --wallet-max-total-btc 6.0 \
  --maker-min-absolute-fee 5000 \
  --maker-max-absolute-fee 20000 \
  --maker-min-relative-fee 0.002 \
  --maker-max-relative-fee 0.002 \
  --out-dir "scenarios/joinmarket/experiments/batch_test"

# 2. Scenario with 3 UTXOs
python manager.py genscen-joinmarket \
  --name "batch_test_2_30_blocks" \
  --maker-count 2 \
  --relative-makers 2 \
  --tumbler-taker-count 1 \
  --taker-count 0 \
  --block-count 30 \
  --tumbler-makercountrange "2,0" \
  --wallet-min-utxos 3 \
  --wallet-max-utxos 3 \
  --wallet-min-total-btc 4.0 \
  --wallet-max-total-btc 6.0 \
  --maker-min-absolute-fee 5000 \
  --maker-max-absolute-fee 20000 \
  --maker-min-relative-fee 0.002 \
  --maker-max-relative-fee 0.002 \
  --out-dir "scenarios/joinmarket/experiments/batch_test"

# 3. Scenario with 8 UTXOs
python manager.py genscen-joinmarket \
  --name "batch_test_3_100_blocks" \
  --maker-count 2 \
  --relative-makers 2 \
  --tumbler-taker-count 1 \
  --taker-count 0 \
  --block-count 100 \
  --tumbler-makercountrange "2,0" \
  --wallet-min-utxos 8 \
  --wallet-max-utxos 8 \
  --wallet-min-total-btc 4.0 \
  --wallet-max-total-btc 6.0 \
  --maker-min-absolute-fee 5000 \
  --maker-max-absolute-fee 20000 \
  --maker-min-relative-fee 0.002 \
  --maker-max-relative-fee 0.002 \
  --out-dir "scenarios/joinmarket/experiments/batch_test"

# 4. Scenario with higher BTC amounts
python manager.py genscen-joinmarket \
  --name "batch_test_4_60_blocks" \
  --maker-count 2 \
  --relative-makers 2 \
  --tumbler-taker-count 1 \
  --taker-count 0 \
  --block-count 60 \
  --tumbler-makercountrange "2,0" \
  --wallet-min-utxos 5 \
  --wallet-max-utxos 5 \
  --wallet-min-total-btc 8.0 \
  --wallet-max-total-btc 10.0 \
  --maker-min-absolute-fee 5000 \
  --maker-max-absolute-fee 20000 \
  --maker-min-relative-fee 0.002 \
  --maker-max-relative-fee 0.002 \
  --out-dir "scenarios/joinmarket/experiments/batch_test"

# 5. Scenario with lower BTC amounts
python manager.py genscen-joinmarket \
  --name "batch_test_5_30_blocks" \
  --maker-count 2 \
  --relative-makers 2 \
  --tumbler-taker-count 1 \
  --taker-count 0 \
  --block-count 30 \
  --tumbler-makercountrange "2,0" \
  --wallet-min-utxos 5 \
  --wallet-max-utxos 5 \
  --wallet-min-total-btc 2.0 \
  --wallet-max-total-btc 3.0 \
  --maker-min-absolute-fee 5000 \
  --maker-max-absolute-fee 20000 \
  --maker-min-relative-fee 0.002 \
  --maker-max-relative-fee 0.002 \
  --out-dir "scenarios/joinmarket/experiments/batch_test"

# 6. Scenario with higher absolute fees
python manager.py genscen-joinmarket \
  --name "batch_test_6_100_blocks" \
  --maker-count 2 \
  --relative-makers 2 \
  --tumbler-taker-count 1 \
  --taker-count 0 \
  --block-count 100 \
  --tumbler-makercountrange "2,0" \
  --wallet-min-utxos 5 \
  --wallet-max-utxos 5 \
  --wallet-min-total-btc 4.0 \
  --wallet-max-total-btc 6.0 \
  --maker-min-absolute-fee 15000 \
  --maker-max-absolute-fee 30000 \
  --maker-min-relative-fee 0.002 \
  --maker-max-relative-fee 0.002 \
  --out-dir "scenarios/joinmarket/experiments/batch_test"

# 7. Scenario with lower absolute fees
python manager.py genscen-joinmarket \
  --name "batch_test_7_60_blocks" \
  --maker-count 2 \
  --relative-makers 2 \
  --tumbler-taker-count 1 \
  --taker-count 0 \
  --block-count 60 \
  --tumbler-makercountrange "2,0" \
  --wallet-min-utxos 5 \
  --wallet-max-utxos 5 \
  --wallet-min-total-btc 4.0 \
  --wallet-max-total-btc 6.0 \
  --maker-min-absolute-fee 1000 \
  --maker-max-absolute-fee 10000 \
  --maker-min-relative-fee 0.002 \
  --maker-max-relative-fee 0.002 \
  --out-dir "scenarios/joinmarket/experiments/batch_test"

# 8. Scenario with higher relative fees
python manager.py genscen-joinmarket \
  --name "batch_test_8_30_blocks" \
  --maker-count 2 \
  --relative-makers 2 \
  --tumbler-taker-count 1 \
  --taker-count 0 \
  --block-count 30 \
  --tumbler-makercountrange "2,0" \
  --wallet-min-utxos 5 \
  --wallet-max-utxos 5 \
  --wallet-min-total-btc 4.0 \
  --wallet-max-total-btc 6.0 \
  --maker-min-absolute-fee 5000 \
  --maker-max-absolute-fee 20000 \
  --maker-min-relative-fee 0.005 \
  --maker-max-relative-fee 0.005 \
  --out-dir "scenarios/joinmarket/experiments/batch_test"

# 9. Scenario with lower relative fees
python manager.py genscen-joinmarket \
  --name "batch_test_9_100_blocks" \
  --maker-count 2 \
  --relative-makers 2 \
  --tumbler-taker-count 1 \
  --taker-count 0 \
  --block-count 100 \
  --tumbler-makercountrange "2,0" \
  --wallet-min-utxos 5 \
  --wallet-max-utxos 5 \
  --wallet-min-total-btc 4.0 \
  --wallet-max-total-btc 6.0 \
  --maker-min-absolute-fee 5000 \
  --maker-max-absolute-fee 20000 \
  --maker-min-relative-fee 0.001 \
  --maker-max-relative-fee 0.001 \
  --out-dir "scenarios/joinmarket/experiments/batch_test"

# 10. Scenario with variable UTXO count
python manager.py genscen-joinmarket \
  --name "batch_test_10_60_blocks" \
  --maker-count 2 \
  --relative-makers 2 \
  --tumbler-taker-count 1 \
  --taker-count 0 \
  --block-count 60 \
  --tumbler-makercountrange "2,0" \
  --wallet-min-utxos 3 \
  --wallet-max-utxos 10 \
  --wallet-min-total-btc 4.0 \
  --wallet-max-total-btc 6.0 \
  --maker-min-absolute-fee 5000 \
  --maker-max-absolute-fee 20000 \
  --maker-min-relative-fee 0.002 \
  --maker-max-relative-fee 0.002 \
  --out-dir "scenarios/joinmarket/experiments/batch_test"