import os
import tarfile
import time
from functools import cached_property
from io import BytesIO
from typing import Protocol, cast

import docker

from . import Driver


class DockerNetwork(Protocol):
    id: str


class DockerDriver(Driver):
    def __init__(self, namespace: str = "coinjoin") -> None:
        self.client: docker.DockerClient = docker.from_env()
        self._namespace = namespace

    @cached_property
    def network(self) -> DockerNetwork:
        return cast(DockerNetwork, self.client.networks.create(self._namespace, driver="bridge"))

    def has_image(self, name: str) -> bool:
        try:
            self.client.images.get(name)
            return True
        except docker.errors.ImageNotFound:
            return False

    def build(self, name: str, path: str) -> None:
        self.client.images.build(path=path, tag=name, rm=True, nocache=True)

    def pull(self, name: str) -> None:
        self.client.images.pull(name)

    def _remove_existing_container(self, name: str) -> bool:
        try:
            old_container = self.client.containers.get(name)
            old_container.remove(force=True)
            return True
        except docker.errors.NotFound:
            return False

    @staticmethod
    def _is_name_conflict(error: object) -> bool:
        explanation = getattr(error, "explanation", "") or str(error)
        return "container name" in explanation and "already in use" in explanation

    def run(
        self,
        name: str,
        image: str,
        env: dict[str, str | None] | None = None,
        ports: dict[int, int] | None = None,
        skip_ip: bool = False,
        cpu: float = 0.1,
        memory: int = 768,
        volumes: dict[str, dict[str, str]] | None = None,
        command: list[str] | None = None,
    ) -> tuple[str, dict[int, int]]:
        self._remove_existing_container(name)
        docker_ports = {
            f"{container_port}/tcp": host_port
            for container_port, host_port in (ports or {}).items()
        }

        for attempt in range(2):
            try:
                self.client.containers.run(
                    image,
                    detach=True,
                    auto_remove=False,
                    name=name,
                    hostname=name,
                    network=self.network.id,
                    ports=docker_ports,
                    environment={
                        key: value
                        for key, value in (env or {}).items()
                        if value is not None
                    },
                    volumes=volumes,
                    command=command,
                )
                break
            except docker.errors.APIError as error:
                if attempt == 0 and self._is_name_conflict(error):
                    print(f"- removing stale container {name} after Docker name conflict")
                    self._remove_existing_container(name)
                    time.sleep(0.5)
                    continue
                raise
        return name, ports or {}

    def stop(self, name: str) -> None:
        try:
            container = self.client.containers.get(name)
            container.stop()
            container.remove(force=True)
            print(f"- stopped {name}")
        except docker.errors.NotFound:
            pass

    def download(self, name: str, src_path: str, dst_path: str) -> None:
        try:
            stream, _ = self.client.containers.get(name).get_archive(src_path)

            fo = BytesIO()
            for d in stream:
                fo.write(d)
            fo.seek(0)
            with tarfile.open(fileobj=fo) as tar:
                tar.extractall(dst_path)
        except (docker.errors.APIError, docker.errors.NotFound, tarfile.TarError, OSError):
            pass

    def peek(self, name: str, path: str) -> str:
        stream, _ = self.client.containers.get(name).get_archive(path)

        fo = BytesIO()
        for d in stream:
            fo.write(d)
        fo.seek(0)
        with tarfile.open(fileobj=fo) as tar:
            extracted = tar.extractfile(os.path.basename(path))
            if extracted is None:
                raise FileNotFoundError(path)
            return extracted.read().decode()

    def logs(self, name: str) -> str:
        return self.client.containers.get(name).logs(stdout=True, stderr=True).decode()

    def upload(self, name: str, src_path: str, dst_path: str) -> None:
        fo = BytesIO()
        with tarfile.open(fileobj=fo, mode="w") as tar:
            tar.add(src_path, os.path.basename(dst_path))
        fo.seek(0)
        self.client.containers.get(name).put_archive(os.path.dirname(dst_path), fo)

    def cleanup(self, image_prefix: str = "") -> None:
        containers = []
        for container in self.client.containers.list(all=True):
            if any(
                x in container.attrs["Config"]["Image"]
                for x in (
                    "irc-server",
                    "btc-node",
                    "wasabi-backend",
                    "wasabi-client",
                    "wasabi-client-distributor",
                    "wasabi-coordinator",
                    "joinmarket-client-server",
                )
            ):
                containers.append(container)

        self.stop_many(str(container.name) for container in containers)
        networks = self.client.networks.list(self._namespace)
        if networks:
            for network in networks:
                network.remove()
