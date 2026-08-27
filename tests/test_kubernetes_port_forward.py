import socket
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast
from unittest import TestCase
from unittest.mock import Mock, patch

from tests.kubernetes_helpers import load_kubernetes_symbols

if TYPE_CHECKING:
    from kubernetes.client import CoreV1Api as CoreV1ApiClass


class PortForwardServerTest(TestCase):
    def test_port_forward_retries_transient_handshake_failure(self) -> None:
        _, PortForwardServer = load_kubernetes_symbols()

        class FakeForward:
            closed = False

            def socket(self, remote_port: int) -> object:
                return {"remote_port": remote_port}

            def close(self) -> None:
                self.closed = True

        fake_kube_client = cast(
            "CoreV1ApiClass",
            SimpleNamespace(connect_get_namespaced_pod_portforward=object()),
        )
        server = PortForwardServer(fake_kube_client, "coinjoin-test", "wasabi-client-005", 37128)
        self.addCleanup(server.close)
        client_socket = Mock(spec=socket.socket)
        fake_forward = FakeForward()
        bridge_calls: list[tuple[object, object]] = []

        def bridge(client_socket_obj: object, upstream_socket: object) -> None:
            bridge_calls.append((client_socket_obj, upstream_socket))

        with (
            patch.object(server, "bridge", side_effect=bridge),
            patch(
                "manager.driver.kubernetes_port_forward.portforward",
                side_effect=[RuntimeError("Handshake status 502 Bad Gateway"), fake_forward],
            ) as portforward,
            patch("manager.driver.kubernetes_port_forward.sleep"),
        ):
            server.handle_connection(cast(socket.socket, client_socket))

        self.assertEqual(portforward.call_count, 2)
        self.assertEqual(bridge_calls, [(client_socket, {"remote_port": 37128})])
        client_socket.close.assert_called_once_with()
        self.assertTrue(fake_forward.closed)
