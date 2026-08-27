"""Local TCP listeners that bridge into cluster pods over the Kubernetes API."""

import select
import socket
import threading
from time import sleep
from typing import Protocol

from kubernetes import client
from kubernetes.stream import portforward

from manager import log_output as log

PORT_FORWARD_ATTEMPTS = 3
PORT_FORWARD_RETRY_DELAY_SECONDS = 0.25


class SocketLike(Protocol):
    def recv(self, size: int) -> bytes: ...
    def sendall(self, data: bytes) -> None: ...
    def fileno(self) -> int: ...


class PortForwardServer:
    def __init__(self, kube_client: client.CoreV1Api, namespace: str, pod_name: str, remote_port: int) -> None:
        self.kube_client = kube_client
        self.namespace = namespace
        self.pod_name = pod_name
        self.remote_port = remote_port
        self.closed = threading.Event()
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen()
        self.local_port = int(self.listener.getsockname()[1])
        self.thread = threading.Thread(
            name=f"kubernetes-port-forward-{pod_name}-{remote_port}",
            target=self.serve,
            daemon=True,
        )

    def start(self) -> None:
        self.thread.start()

    def close(self) -> None:
        self.closed.set()
        try:
            self.listener.close()
        except OSError:
            pass

    def serve(self) -> None:
        while not self.closed.is_set():
            try:
                client_socket, _ = self.listener.accept()
            except OSError:
                return
            threading.Thread(
                name=f"kubernetes-port-forward-connection-{self.pod_name}-{self.remote_port}",
                target=self.handle_connection,
                args=(client_socket,),
                daemon=True,
            ).start()

    def handle_connection(self, client_socket: socket.socket) -> None:
        forward = None
        try:
            for attempt in range(PORT_FORWARD_ATTEMPTS):
                try:
                    forward = portforward(
                        self.kube_client.connect_get_namespaced_pod_portforward,
                        self.pod_name,
                        self.namespace,
                        ports=str(self.remote_port),
                    )
                    break
                except Exception as error:  # pylint: disable=broad-exception-caught
                    log.debug(
                        f"- port-forward {self.pod_name}:{self.remote_port} failed "
                        f"({attempt + 1}/{PORT_FORWARD_ATTEMPTS}): {error}"
                    )
                    if attempt + 1 >= PORT_FORWARD_ATTEMPTS:
                        raise
                    sleep(PORT_FORWARD_RETRY_DELAY_SECONDS)
            if forward is None:
                return
            upstream_socket = forward.socket(self.remote_port)
            self.bridge(client_socket, upstream_socket)
        except Exception as error:  # pylint: disable=broad-exception-caught # pragma: no cover - defensive logging around background thread
            log.debug(f"- port-forward {self.pod_name}:{self.remote_port} failed: {error}")
        finally:
            try:
                client_socket.close()
            except OSError:
                pass
            if forward is not None:
                forward.close()

    def bridge(self, client_socket: SocketLike, upstream_socket: SocketLike) -> None:
        sockets = [client_socket, upstream_socket]
        while not self.closed.is_set():
            try:
                readable, _, _ = select.select(sockets, [], [], 0.5)
            except OSError:
                return
            for source in readable:
                target = upstream_socket if source is client_socket else client_socket
                try:
                    data = source.recv(65536)
                    if not data:
                        return
                    target.sendall(data)
                except OSError:
                    return
