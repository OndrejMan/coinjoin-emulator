"""Startup endpoints must preserve the actual clients' HTTP/TLS transport."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import Mock, mock_open, patch

import pytest

from manager.engine.configuration import WalletConfig
from manager.engine.joinmarket_engine import JoinmarketEngine
from manager.engine.wasabi_engine import WasabiEngine
from manager.wasabi_backend_factory import BackendArchitecture


@pytest.fixture
def http_service(monkeypatch):
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def reply(self, body):
            data = json.dumps(body).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            calls.append(request["method"])
            if request["method"] == "getblockcount":
                self.reply({"result": 777, "error": None})
            else:
                self.reply({"result": {"balance": 1}})

        def do_GET(self):
            calls.append(self.path)
            self.reply({"ready": True})

        def log_message(self, *_args):
            pass

    monkeypatch.setenv("NO_PROXY", "*")
    monkeypatch.setenv("no_proxy", "*")
    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        worker = threading.Thread(
            target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
        )
        worker.start()
        try:
            yield server.server_port, calls
        finally:
            server.shutdown()
            worker.join(timeout=1)


def runtime(engine_class, published_port):
    args = SimpleNamespace(
        proxy="", in_cluster=False, control_ip="127.0.0.1", image_prefix="test/",
        btc_node_image="", btc_node_ip="", btcFolder="", btc_node_arg=[],
        wasabi_backend_ip="",
    )
    driver = Mock(in_cluster=False)
    driver.run.side_effect = lambda _name, _image, ports, **_kw: (
        "pod-ip", {port: published_port for port in ports}, "secure-route.invalid"
    )
    instance = engine_class(args, driver)
    instance.node = SimpleNamespace(internal_ip="btc-node")
    instance.backend = SimpleNamespace(internal_ip="wasabi-backend")
    instance.coordinator = SimpleNamespace(internal_ip="wasabi-coordinator")
    instance.backend_architecture = BackendArchitecture.SPLIT
    return instance


@pytest.mark.parametrize("component", ["btc", "backend", "coordinator", "distributor", "client", "watcher"])
def test_http_clients_reach_the_published_service_even_when_a_tls_route_exists(component, http_service):
    port, calls = http_service
    instance = runtime(JoinmarketEngine if component == "watcher" else WasabiEngine, port)
    # Keep real client constructors and requests; bypass only expensive startup
    # readiness/wallet loops and container configuration upload.
    with (
        patch("manager.btc_node.BtcNode.wait_ready"),
        patch("manager.wasabi_backend_26.WasabiBackend26.wait_ready"),
        patch("manager.wasabi_coordinator.WasabiCoordinator.wait_ready"),
        patch("manager.wasabi_clients.wasabi_client_v26.WasabiClientV26.wait_wallet", return_value=True),
        patch("manager.engine.wasabi_engine.sleep"),
        patch("manager.engine.wasabi_engine.tempfile.NamedTemporaryFile"),
        patch("builtins.open", mock_open(read_data="{}")),
        patch("manager.wasabi_clients.joinmarket_clients.joinmarket_clients.os.makedirs"),
    ):
        if component == "btc":
            instance.start_btc_node()
            client, request = instance.node, instance.node.get_block_count
        elif component == "backend":
            instance.start_wasabi_backend()
            client, request = instance.backend, instance.backend._get_status
        elif component == "coordinator":
            instance.start_wasabi_coordinator()
            client, request = instance.coordinator, instance.coordinator._get_status
        elif component == "distributor":
            instance.start_distributor()
            client, request = instance.distributor, instance.distributor.get_balance
        elif component == "client":
            client = instance.start_client(1, WalletConfig(funds=[100000]))
            request = client.get_balance
        else:
            instance.start_orderbook_watch()
            client, request = instance.obwatch_client, instance.obwatch_client._fetch_orderbook

    # Check before connecting, so a regression cannot contact an external host.
    assert (client.host, client.port) == ("127.0.0.1", port)
    assert request()
    assert len(calls) == 1


@pytest.mark.parametrize("distributor", [False, True])
def test_joinmarket_wallet_services_keep_their_tls_routes(distributor):
    instance = runtime(JoinmarketEngine, 31000)
    instance.create_core_wallet = Mock(return_value="core-wallet")
    with (
        patch.object(instance, "init_joinmarket_clientserver") as init_distributor,
        patch("manager.engine.joinmarket_engine.JoinMarketClientServer.from_wallet") as init_client,
        patch("manager.engine.joinmarket_engine.sleep"),
    ):
        if distributor:
            instance.start_distributor()
            factory = init_distributor
        else:
            instance.start_client(1, WalletConfig(funds=[100000]))
            factory = init_client
    assert factory.call_args.kwargs["host"] == "secure-route.invalid"
    assert factory.call_args.kwargs["port"] == 443
