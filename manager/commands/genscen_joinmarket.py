#!/usr/bin/env python3
"""
JoinMarket Configuration Generator
Generates customizable JoinMarket simulation configurations with takers and makers
"""

import json
import random
from typing import List, Dict, Any, Tuple, Optional
from dataclasses import dataclass, field
from enum import Enum
import argparse
import os
import sys
import numpy

class OfferType(Enum):
    ABSOLUTE = "sw0absoffer"
    RELATIVE = "sw0reloffer"


@dataclass
class FeeConfig:
    """Configuration for maker fees"""
    min_absolute: int = 1000  # satoshis
    max_absolute: int = 5000  # satoshis
    min_relative: float = 0.0001  # 0.01%
    max_relative: float = 0.004  # 0.4%


@dataclass
class WalletConfig:
    """Configuration for wallet generation"""
    min_utxos: int = 9
    max_utxos: int = 11
    min_total_btc: float = 1.0
    max_total_btc: float = 10.0
    min_utxo_size: int = 100000  # satoshis


@dataclass
class TumblerOptions:
    """Default tumbler options for takers"""
    addrcount: int = 3
    minmakercount: int = 4
    makercountrange: List[int] = field(default_factory=lambda: [9, 1])
    mixdepthcount: int = 4
    mintxcount: int = 2
    txcountparams: List[int] = field(default_factory=lambda: [2, 1])
    timelambda: int = 60
    stage1_timelambda_increase: int = 3
    liquiditywait: int = 60
    waittime: int = 20
    mixdepthsrc: int = 0
    restart: bool = True
    schedulefile: str = "TUMBLE.schedule"
    mincjamount: int = 100000
    amtmixdepths: int = 4
    rounding_chance: float = 0.25
    rounding_sigfig_weights: List[int] = field(default_factory=lambda: [55, 15, 25, 65, 40])


class JoinMarketConfigGenerator:
    def __init__(self):
        self.fee_config = FeeConfig()
        self.wallet_config = WalletConfig()
        self.tumbler_options = TumblerOptions()

    def generate_utxos(self, total_btc: float, num_utxos: int) -> List[int]:
        """Generate UTXO distribution for a wallet"""
        total_sats = int(total_btc * 100_000_000)

        # Ensure we have enough for minimum UTXO sizes
        min_total = num_utxos * self.wallet_config.min_utxo_size
        if total_sats < min_total:
            total_sats = min_total

        # Generate random distribution
        utxos = []
        remaining = total_sats

        for i in range(num_utxos - 1):
            # Leave enough for remaining UTXOs
            max_utxo = remaining - (num_utxos - i - 1) * self.wallet_config.min_utxo_size
            min_utxo = self.wallet_config.min_utxo_size

            if max_utxo > min_utxo:
                utxo = random.randint(min_utxo, min(max_utxo, int(total_sats * 0.3)))
            else:
                utxo = min_utxo

            utxos.append(utxo)
            remaining -= utxo

        # Add remaining amount as last UTXO
        if remaining >= self.wallet_config.min_utxo_size:
            utxos.append(remaining)
        else:
            # Adjust last UTXO to meet minimum
            utxos[-1] -= self.wallet_config.min_utxo_size - remaining
            utxos.append(self.wallet_config.min_utxo_size)

        random.shuffle(utxos)
        return utxos

    def create_taker_wallet(self, delay_blocks: int = 0) -> Dict[str, Any]:
        """Create a taker wallet configuration"""
        num_utxos = random.randint(self.wallet_config.min_utxos, self.wallet_config.max_utxos)
        total_btc = random.uniform(self.wallet_config.min_total_btc, self.wallet_config.max_total_btc)

        wallet = {
            "funds": self.generate_utxos(total_btc, num_utxos),
            "type": "taker",
            "tumbler_options": {
                "addrcount": self.tumbler_options.addrcount,
                "minmakercount": self.tumbler_options.minmakercount,
                "makercountrange": self.tumbler_options.makercountrange.copy(),
                "mixdepthcount": self.tumbler_options.mixdepthcount,
                "mintxcount": self.tumbler_options.mintxcount,
                "txcountparams": self.tumbler_options.txcountparams.copy(),
                "timelambda": self.tumbler_options.timelambda,
                "stage1_timelambda_increase": self.tumbler_options.stage1_timelambda_increase,
                "liquiditywait": self.tumbler_options.liquiditywait,
                "waittime": self.tumbler_options.waittime,
                "mixdepthsrc": self.tumbler_options.mixdepthsrc,
                "restart": self.tumbler_options.restart,
                "schedulefile": self.tumbler_options.schedulefile,
                "mincjamount": self.tumbler_options.mincjamount,
                "amtmixdepths": self.tumbler_options.amtmixdepths,
                "rounding_chance": self.tumbler_options.rounding_chance,
                "rounding_sigfig_weights": self.tumbler_options.rounding_sigfig_weights.copy()
            }
        }

        if delay_blocks > 0:
            wallet["delay_blocks"] = delay_blocks

        return wallet

    def create_maker_wallet(self, offer_type: OfferType, fee_value: Optional[float] = None) -> Dict[str, Any]:
        """Create a maker wallet configuration"""
        num_utxos = random.randint(self.wallet_config.min_utxos, self.wallet_config.max_utxos)
        total_btc = random.uniform(self.wallet_config.min_total_btc, self.wallet_config.max_total_btc)

        funds = self.generate_utxos(total_btc, num_utxos)
        total_balance = sum(funds)

        offer = {
            "txfee": 0,
            "ordertype": offer_type.value,
            "minsize": self.wallet_config.min_utxo_size,
            "maxsize": int(total_balance * 0.9)  # 90% of wallet balance
        }

        if offer_type == OfferType.ABSOLUTE:
            if fee_value is None:
                fee_value = random.randint(self.fee_config.min_absolute, self.fee_config.max_absolute)
            offer["cjfee_a"] = int(fee_value)
            offer["cjfee_r"] = 0
        else:  # RELATIVE
            if fee_value is None:
                fee_value = random.uniform(self.fee_config.min_relative, self.fee_config.max_relative)
            offer["cjfee_a"] = 0
            offer["cjfee_r"] = fee_value

        return {
            "funds": funds,
            "type": "maker",
            "offers": [offer]
        }

    def generate_config(self,
                        name: str = "JoinMarket Configuration",
                        num_takers: int = 5,
                        num_makers: int = 35,
                        taker_delays: Optional[List[int]] = None,
                        maker_fee_split: float = 0.5,  # Fraction of makers using absolute fees
                        rounds: int = 0,
                        blocks: int = 1000) -> Dict[str, Any]:
        """Generate complete configuration"""

        if taker_delays is None:
            taker_delays = [0, 10, 30, 50, 70][:num_takers]

        config = {
            "name": name,
            "default_version": "joinmarket",
            "rounds": rounds,
            "blocks": blocks,
            "wallets": []
        }

        # Create takers
        for i in range(num_takers):
            delay = taker_delays[i] if i < len(taker_delays) else 0
            config["wallets"].append(self.create_taker_wallet(delay))

        # Create makers
        num_absolute = int(num_makers * maker_fee_split)
        num_relative = num_makers - num_absolute

        # Absolute fee makers
        for i in range(num_absolute):
            config["wallets"].append(self.create_maker_wallet(OfferType.ABSOLUTE))

        # Relative fee makers with distributed fees
        if num_relative > 0:
            # Create linear distribution from max to min
            relative_fees = []
            for i in range(num_relative):
                fee = self.fee_config.max_relative - (
                        (self.fee_config.max_relative - self.fee_config.min_relative) * i / (num_relative - 1)
                )
                relative_fees.append(fee)

            for fee in relative_fees:
                config["wallets"].append(self.create_maker_wallet(OfferType.RELATIVE, fee))

        return config

    def save_config(self, config: Dict[str, Any], filename: str):
        """Save configuration to JSON file"""
        with open(filename, 'w') as f:
            json.dump(config, f, indent=2)

    def load_and_modify_config(self, filename: str) -> Dict[str, Any]:
        """Load existing configuration for modification"""
        with open(filename, 'r') as f:
            return json.load(f)


def format_name(args):
    # Use a JoinMarket-specific naming convention
    if args.name:
        return args.name
    # Example: tumbler_1_maker_30.json
    if args.tumbler_taker_count > 0:
        return f"tumbler_{args.tumbler_taker_count}_maker_{args.maker_count}.json"
    else:
        return f"taker_{args.taker_count}_maker_{args.maker_count}.json"


def random_partition(total, n):
    # Partition 'total' into 'n' positive random integers (satoshis)
    # Returns a list of n integers summing to total
    import numpy as np
    # Generate n-1 sorted random cut points between 0 and total
    cuts = np.sort(np.random.randint(1, total, n - 1)) if n > 1 else []
    parts = [cuts[0]] if cuts else [total]
    for i in range(1, len(cuts)):
        parts.append(cuts[i] - cuts[i - 1])
    if cuts:
        parts.append(total - cuts[-1])
    return parts


def prepare_distribution(distribution):
    import numpy
    dist_name = distribution.split("[")[0]
    dist_params = None
    if "[" in distribution:
        dist_params = list(map(float, distribution.split("[")[1].split("]")[0].split(",")))
    if dist_name == "uniform":
        dist_params = dist_params or [0.0, 10_000_000.0]
        return lambda x: list(map(round, numpy.random.uniform(*dist_params, x)))
    elif dist_name == "pareto":
        dist_params = dist_params or [1.16]
        return lambda x: list(map(round, numpy.random.pareto(*dist_params, x) * 1_000_000))
    elif dist_name == "lognorm":
        dist_params = dist_params or [14.1, 2.29]
        return lambda x: list(map(round, numpy.random.lognormal(*dist_params, x)))
    else:
        return None


def prepare_skip_rounds(args):
    import numpy
    if not args.skip_rounds:
        return None
    if args.skip_rounds.startswith("random"):
        if args.stop_round == 0:
            print("- cannot use random skip rounds with no stop round")
            sys.exit(1)
        fraction = 2 / 3
        if args.skip_rounds != "random":
            try:
                fraction = float(args.skip_rounds.split("[")[1].split("]")[0])
            except IndexError:
                print("- random skip rounds fraction parsing failed")
                sys.exit(1)
        print(f"- skipping {fraction * 100:.2f}% of rounds")
        return lambda _: sorted(
            map(
                int,
                numpy.random.choice(
                    range(0, args.stop_round),
                    size=int(args.stop_round * fraction),
                    replace=False,
                ),
            )
        )
    else:
        try:
            return lambda idx: (
                sorted(map(int, args.skip_rounds.split(",")))
                if idx < args.client_count // 2
                else []
            )
        except ValueError:
            print("- invalid skip rounds list")
            sys.exit(1)


def setup_parser(parser: argparse.ArgumentParser):
    parser.add_argument("--engine", type=str, default="joinmarket", help="engine type")
    parser.add_argument("--name", type=str, help="scenario name")
    parser.add_argument("--maker-count", type=int, default=30, help="number of makers")
    parser.add_argument("--taker-count", type=int, default=2, help="number of takers")
    parser.add_argument("--tumbler-taker-count", type=int, default=1, help="number of tumbler takers")
    parser.add_argument("--round-count", type=int, default=10, help="number of rounds")
    parser.add_argument("--block-count", type=int, default=0, help="number of blocks")
    parser.add_argument("--type", type=str, default="static", help="scenario type")
    parser.add_argument("--distribution", type=str, default="lognorm", help="fund distribution strategy")
    parser.add_argument("--min-utxos", type=int, default=1, help="minimum UTXOs per wallet")
    parser.add_argument("--max-utxos", type=int, default=3, help="maximum UTXOs per wallet")
    parser.add_argument("--min-total-btc", type=float, default=0.01, help="minimum total BTC per wallet")
    parser.add_argument("--max-total-btc", type=float, default=5.0, help="maximum total BTC per wallet")
    parser.add_argument("--max-coinjoin", type=int, default=400, help="maximal number of inputs to a coinjoin")
    parser.add_argument("--min-coinjoin", type=int, default=4, help="minimal number of inputs to a coinjoin")
    parser.add_argument("--stop-round", type=int, default=0, help="terminate after N coinjoin rounds, 0 for no limit")
    parser.add_argument("--stop-block", type=int, default=0, help="terminate after N blocks, 0 for no limit")
    parser.add_argument("--skip-rounds", type=str, required=False, help="skip rounds ('random[fraction]' for randomly sampled fraction of rounds, or comma-separated list of rounds to skip)")
    parser.add_argument("--force", action="store_true", help="overwrite existing files")
    parser.add_argument("--out-dir", type=str, default="scenarios/joinmarket", help="output directory")
    parser.add_argument("--distributor-version", type=str, required=False, help="version of the distibutor wallet")
    parser.add_argument("--client-version", type=str, required=False, help="version of the client wallet")
    parser.add_argument("--anon-score-target", type=int, required=False, help="default anon score target used for wallets")
    parser.add_argument("--redcoin-isolation", type=bool, required=False, help="default redcoin isolation setting used for wallets")


def handler(args):
    print("Generating JoinMarket scenario...")
    scenario = {
        "name": format_name(args),
        "default_version": "joinmarket",
        "rounds": args.round_count,
        "blocks": args.block_count,
        "wallets": []
    }
    scenario["backend"] = {
        "MaxInputCountByRound": args.max_coinjoin,
        "MinInputCountByRoundMultiplier": args.min_coinjoin / args.max_coinjoin if args.max_coinjoin else 0.01
    }
    if args.distributor_version:
        scenario["distributor_version"] = args.distributor_version
    if args.client_version:
        scenario["default_version"] = args.client_version
    if args.anon_score_target:
        scenario["default_anon_score_target"] = args.anon_score_target
    if args.redcoin_isolation:
        scenario["default_redcoin_isolation"] = args.redcoin_isolation
    distribution = prepare_distribution(args.distribution)
    if not distribution:
        print("- invalid distribution")
        sys.exit(1)
    skip_rounds = prepare_skip_rounds(args)
    # Generate wallets
    import random
    SATOSHI = 100_000_000
    for idx in range(args.taker_count):
        n_utxos = random.randint(args.min_utxos, args.max_utxos)
        total_btc = random.uniform(args.min_total_btc, args.max_total_btc)
        total_sats = int(total_btc * SATOSHI)
        funds = random_partition(total_sats, n_utxos)
        wallet = {
            "funds": funds,
            "type": "taker"
        }
        if skip_rounds:
            wallet["skip_rounds"] = skip_rounds(idx)
        scenario["wallets"].append(wallet)
    for idx in range(args.tumbler_taker_count):
        n_utxos = random.randint(args.min_utxos, args.max_utxos)
        total_btc = random.uniform(args.min_total_btc, args.max_total_btc)
        total_sats = int(total_btc * SATOSHI)
        funds = random_partition(total_sats, n_utxos)
        wallet = {
            "funds": funds,
            "type": "tumbler_taker"
        }
        if skip_rounds:
            wallet["skip_rounds"] = skip_rounds(idx)
        scenario["wallets"].append(wallet)
    for idx in range(args.maker_count):
        n_utxos = random.randint(args.min_utxos, args.max_utxos)
        total_btc = random.uniform(args.min_total_btc, args.max_total_btc)
        total_sats = int(total_btc * SATOSHI)
        funds = random_partition(total_sats, n_utxos)
        wallet = {
            "funds": funds,
            "type": "maker",
            "offers": [
                {
                    "txfee": 0,
                    "ordertype": "sw0absoffer",
                    "minsize": 100000,
                    "maxsize": int(sum(funds) * 0.9),
                    "cjfee_a": random.randint(1000, 5000),
                    "cjfee_r": 0
                }
            ]
        }
        if skip_rounds:
            wallet["skip_rounds"] = skip_rounds(idx)
        scenario["wallets"].append(wallet)
    print(f"- requires {(sum(map(lambda x: sum(x['funds']), scenario['wallets'])) / 100_000_000):0.8f} BTC")
    os.makedirs(args.out_dir, exist_ok=True)
    out_path = os.path.join(args.out_dir, scenario["name"])
    if not out_path.endswith(".json"):
        out_path += ".json"
    if os.path.exists(out_path) and not args.force:
        print(f"- file {out_path} already exists")
        sys.exit(1)
    with open(out_path, "w") as f:
        json.dump(scenario, f, indent=2)
    print(f"- saved to {out_path}")


def main():
    parser = argparse.ArgumentParser(description="JoinMarket Configuration Generator")
    setup_parser(parser)
    args = parser.parse_args()
    handler(args)


if __name__ == "__main__":
    main()