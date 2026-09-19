"""Wasabi round accounting for the split backend architecture."""

from types import SimpleNamespace
from unittest.mock import Mock, call, patch

from manager.engine.configuration import ScenarioConfig, WalletConfig, WasabiConfig
from manager.engine.wasabi_engine import WasabiEngine, successful_broadcast_txids
from manager.wasabi_backend_factory import BackendArchitecture


def split_engine() -> WasabiEngine:
    engine = object.__new__(WasabiEngine)
    engine.backend_architecture = BackendArchitecture.SPLIT
    engine.driver = Mock()
    return engine


def test_successful_broadcast_txids_are_deduplicated_across_logs() -> None:
    txid_a, txid_b = "a" * 64, "B" * 64

    assert successful_broadcast_txids(
        [
            f"Successfully broadcasted coinjoin transaction: {txid_a}",
            "\n".join(
                [
                    f"Successfully broadcasted coinjoin transaction: {txid_a}",
                    f"Successfully broadcast coinjoin: {txid_b}",
                ]
            ),
        ]
    ) == {txid_a, txid_b.lower()}


def test_only_successfully_broadcast_transactions_count_as_rounds() -> None:
    engine = split_engine()
    txid_a, txid_b = "a" * 64, "b" * 64
    engine.driver.peek.return_value = "\n".join(
        [
            f"Successfully broadcasted coinjoin transaction: {txid_a}",
            f"Successfully broadcasted coinjoin transaction: {txid_a}",
            f"Successfully broadcasted coinjoin transaction: {txid_b}",
        ]
    )

    assert engine._get_current_round() == 2  # pylint: disable=protected-access


def test_the_run_stops_clients_before_settlement_after_the_round_limit() -> None:
    engine = split_engine()
    client = SimpleNamespace(stop=(0, 0), delay=(0, 0), skip_rounds=frozenset())
    lifecycle = Mock()
    engine.clients = [client]
    engine.start_coinjoin = lifecycle.start
    engine.stop_coinjoin = lifecycle.stop
    engine.node = Mock()
    engine.node.get_block_count.return_value = 100
    engine.node.mine_block = lifecycle.mine
    engine.scenario = ScenarioConfig("test", 1, 0, "test", [WalletConfig(funds=[1])])
    engine.current_round = 0
    engine.current_block = 0
    engine._get_current_round = Mock(return_value=1)  # pylint: disable=protected-access
    engine.update_invoice_payments = Mock()

    with patch("manager.engine.wasabi_engine.sleep"):
        engine.run_engine()

    engine._get_current_round.assert_called_once_with()  # pylint: disable=protected-access
    assert lifecycle.method_calls == [call.stop(client), call.mine(3)]


def test_wallet_skips_only_the_configured_rounds() -> None:
    engine = split_engine()
    skipping = SimpleNamespace(stop=(0, 0), delay=(0, 0), skip_rounds=frozenset({2}))
    participating = SimpleNamespace(stop=(0, 0), delay=(0, 0), skip_rounds=frozenset())
    engine.clients = [skipping, participating]
    engine.scenario = ScenarioConfig("test", 10, 0, "test", [WalletConfig(funds=[1])])
    engine.current_round = 2
    engine.current_block = 0
    engine.start_coinjoin = Mock()
    engine.stop_coinjoin = Mock()

    engine.update_coinjoins()

    engine.start_coinjoin.assert_called_once_with(participating)
    engine.stop_coinjoin.assert_called_once_with(skipping)


def test_start_client_preserves_configured_skip_rounds() -> None:
    engine = split_engine()
    engine.args = SimpleNamespace(
        image_prefix="",
        btc_node_ip="",
        wasabi_backend_ip="",
        proxy="",
        in_cluster=False,
        control_ip="localhost",
    )
    engine.node = SimpleNamespace(internal_ip="btc-node")
    engine.backend = SimpleNamespace(internal_ip="wasabi-backend")
    engine.coordinator = SimpleNamespace(internal_ip="wasabi-coordinator")
    engine.scenario = ScenarioConfig("test", 10, 0, "2.6.0", [])
    engine.driver.run.return_value = ("client-ip", {37128: 37132}, None)
    client = Mock(name="wasabi-client-000")
    client.name = "wasabi-client-000"
    client.wait_wallet.return_value = True
    engine.init_wasabi_client = Mock(return_value=client)  # type: ignore[method-assign]
    wallet = WalletConfig(funds=[1], wasabi=WasabiConfig(skip_rounds=[1, 3]))

    with patch("manager.engine.wasabi_engine.sleep"):
        assert engine.start_client(0, wallet) is client

    assert engine.init_wasabi_client.call_args.args[-1] == [1, 3]
