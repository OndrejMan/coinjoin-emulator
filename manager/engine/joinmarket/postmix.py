"""Postmix spends of a JoinMarket wallet: coinjoin outputs leave the pool one mixdepth at a time.

A JoinMarket coin carries no anonymity score, so a coin counts as mixed when the
transaction that created it is a confirmed CoinJoin of the run. JoinMarket never
merges mixdepths, so a spend pays from a single mixdepth: jmwalletd's direct-send
sweeps every coin of the mixdepth that is not frozen, so the other coins are frozen
for the sweep and the spend leaves no change.
"""

import time
from collections.abc import Callable, Collection
from typing import NotRequired, Protocol, TypedDict

STOP_TIMEOUT_SECONDS = 30
STOP_POLL_SECONDS = 2


class JoinMarketCoin(TypedDict):
    """One coin of jmwalletd's ``utxos`` listing, as far as a postmix spend reads it."""

    utxo: str  # "txid:index"
    value: int
    mixdepth: int
    confirmations: NotRequired[int]
    frozen: NotRequired[bool]


class TransactionInput(TypedDict):
    outpoint: str  # "txid:index"


class TransactionInfo(TypedDict, total=False):
    """The ``txinfo`` jmwalletd's direct-send answers with."""

    txid: str
    inputs: list[TransactionInput]


class SweptCoin(TypedDict):
    txid: str
    index: int
    amount: int
    mixdepth: int


class Sweep(TypedDict):
    txid: str | None
    amount_sats: int
    coins: list[SweptCoin]


class JoinMarketWallet(Protocol):
    """The jmwalletd calls a postmix spend needs."""

    name: str
    type: str

    def session(self) -> dict[str, object] | None:
        """Return jmwalletd's service state, None when it did not answer."""

    def stop_maker(self) -> object:
        """Stop the yield generator."""

    def list_utxos(self) -> dict[str, list[JoinMarketCoin]]:
        """Return the wallet's coins under ``utxos``."""

    def freeze_utxo(self, utxo: str, freeze: bool) -> object:
        """Freeze or unfreeze one ``txid:index`` coin."""

    def sweep_mixdepth(self, destination: str, mixdepth: int) -> TransactionInfo:
        """Pay every coin of ``mixdepth`` that is not frozen to ``destination``."""


def _outpoint(coin: JoinMarketCoin) -> tuple[str, int]:
    txid, index = coin["utxo"].split(":")
    return txid, int(index)


def _value(coin: JoinMarketCoin) -> int:
    return coin["value"]


def _select_by_amount(candidates: list[JoinMarketCoin], value: int) -> tuple[list[JoinMarketCoin], int]:
    """Take coins that keep the amount above ``value`` small, as Wasabi's ``amount`` selection does."""
    remaining = sorted(candidates, key=_value)
    selected: list[JoinMarketCoin] = []
    total = 0
    while remaining and total < value:
        covering = [coin for coin in remaining if _value(coin) >= value - total]
        coin = covering[0] if covering else remaining[-1]
        remaining.remove(coin)
        selected.append(coin)
        total += _value(coin)
    return selected, total


class JoinMarketPostmixWallet:
    """Adapts a JoinMarket client to the postmix schedule's ``SpendingClient``."""

    def __init__(self, client: JoinMarketWallet, coinjoin_txids: Callable[[], Collection[str]]):
        self.client = client
        self.name = client.name
        self.coinjoin_txids = coinjoin_txids

    def stop_coinjoin(self) -> None:
        """Stop the maker and wait until jmwalletd is idle; a taker's running coinjoin is not cut short.

        jmwalletd freezes and sends only while no maker or taker runs. A maker
        serves offers all the time, so it is stopped (the engine restarts it on
        its next update); a taker is left to finish and the spend retried.
        """
        if self.client.type == "maker":
            self.client.stop_maker()
        deadline = time.monotonic() + STOP_TIMEOUT_SECONDS
        while True:
            state = self.client.session()
            if state is None:
                raise RuntimeError(f"{self.name} did not report its service state")
            if not state.get("maker_running") and not state.get("coinjoin_in_process"):
                return
            if self.client.type != "maker":
                raise RuntimeError(f"{self.name} is in a coinjoin")
            if time.monotonic() >= deadline:
                raise RuntimeError(f"{self.name} maker did not stop within {STOP_TIMEOUT_SECONDS} s")
            time.sleep(STOP_POLL_SECONDS)

    def check_mixed_coins(
        self,
        value: int | None = None,
        min_anon_score: float | None = None,
        unspent: Callable[[str, int], bool] | None = None,
    ) -> None:
        """Raise like ``send_mixed_coins`` when no mixdepth's mixed coins cover ``value`` yet."""
        del min_anon_score  # JoinMarket coins have no anonymity score
        self._select(self._coins(), value, unspent)

    def send_mixed_coins(
        self,
        destination: str,
        value: int | None = None,
        min_anon_score: float | None = None,
        unspent: Callable[[str, int], bool] | None = None,
        coin_selection: str = "amount",
    ) -> dict[str, object]:
        """Sweep mixed coins to ``destination``: one mixdepth covering ``value``, or every mixdepth when None.

        The whole selection is paid out with the fee subtracted, so no change
        output re-enters the wallet as fresh liquidity.
        """
        del min_anon_score  # JoinMarket coins have no anonymity score
        if coin_selection != "amount":
            raise ValueError(f"unsupported JoinMarket coin selection: {coin_selection}")
        coins = self._coins()
        by_mixdepth = self._select(coins, value, unspent)
        transactions = [
            self._sweep(coins, selected, destination, mixdepth) for mixdepth, selected in sorted(by_mixdepth.items())
        ]
        return {
            "txid": transactions[0]["txid"],
            "txids": [transaction["txid"] for transaction in transactions],
            "amount_sats": sum(transaction["amount_sats"] for transaction in transactions),
            "coins": [coin for transaction in transactions for coin in transaction["coins"]],
        }

    def _coins(self) -> list[JoinMarketCoin]:
        return list(self.client.list_utxos().get("utxos") or [])

    def _select(
        self,
        coins: list[JoinMarketCoin],
        value: int | None,
        unspent: Callable[[str, int], bool] | None,
    ) -> dict[int, list[JoinMarketCoin]]:
        """Confirmed, unfrozen coinjoin outputs by mixdepth: all of them, or the one mixdepth that covers ``value``
        with the least overshoot."""
        coinjoins = set(self.coinjoin_txids())
        by_mixdepth: dict[int, list[JoinMarketCoin]] = {}
        for coin in coins:
            txid, index = _outpoint(coin)
            if (
                coin.get("confirmations", 0) > 0
                and not coin.get("frozen")
                and txid in coinjoins
                and (unspent is None or unspent(txid, index))
            ):
                by_mixdepth.setdefault(coin["mixdepth"], []).append(coin)
        if value is None:
            if not by_mixdepth:
                raise RuntimeError(f"{self.name} has no mixed coins")
            return by_mixdepth
        covering = [
            (total, mixdepth, selected)
            for mixdepth, candidates in by_mixdepth.items()
            for selected, total in [_select_by_amount(candidates, value)]
            if total >= value
        ]
        if not covering:
            best = max((sum(map(_value, candidates)) for candidates in by_mixdepth.values()), default=0)
            raise RuntimeError(
                f"{self.name} has at most {best} sats of mixed coins in one mixdepth, {value} sats requested"
            )
        _, mixdepth, selected = min(covering, key=lambda item: (item[0], item[1]))
        return {mixdepth: selected}

    def _sweep(
        self,
        coins: list[JoinMarketCoin],
        selected: list[JoinMarketCoin],
        destination: str,
        mixdepth: int,
    ) -> Sweep:
        """Sweep ``selected`` out of ``mixdepth`` with every other coin there frozen, then unfreeze them.

        The record lists the inputs the transaction actually spent; once it is
        broadcast, a mismatch is not an error that a retry could undo.
        """
        chosen = {coin["utxo"] for coin in selected}
        frozen = [
            coin["utxo"]
            for coin in coins
            if coin.get("mixdepth") == mixdepth and coin["utxo"] not in chosen and not coin.get("frozen")
        ]
        try:
            for utxo in frozen:
                self.client.freeze_utxo(utxo, True)
            txinfo = self.client.sweep_mixdepth(destination, mixdepth)
        finally:
            for utxo in frozen:
                self.client.freeze_utxo(utxo, False)
        spent = {item["outpoint"] for item in txinfo.get("inputs", [])}
        swept = [coin for coin in coins if coin["utxo"] in spent]
        if spent != chosen:
            print(f"- {self.name} swept {sorted(spent)} instead of {sorted(chosen)}")
        return {
            "txid": txinfo.get("txid"),
            "amount_sats": sum(map(_value, swept)),
            "coins": [
                {"txid": txid, "index": index, "amount": _value(coin), "mixdepth": mixdepth}
                for coin in swept
                for txid, index in [_outpoint(coin)]
            ],
        }
