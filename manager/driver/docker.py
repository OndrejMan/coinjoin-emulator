import os
import tarfile
from collections.abc import Iterable
from functools import cached_property
from io import BytesIO
from typing import Protocol, cast

import docker

from . import RESERVED_PORT_RANGE, RESERVED_PORTS_SYSCTL, Driver


class DockerNetwork(Protocol):
    """The part of the docker network object this driver uses."""

    id: str


class DockerArchiveContainer(Protocol):
    """Docker container operations used while copying live artifacts."""

    status: str

    def reload(self) -> None: ...

    def pause(self) -> None: ...

    def unpause(self) -> None: ...

    def get_archive(self, path: str) -> tuple[Iterable[bytes], dict[str, object]]: ...


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

    def run(
        self,
        name: str,
        image: str,
        env: dict[str, str] | None = None,
        ports: dict[int, int] | None = None,
        cpu: float | None = None,
        memory: int | None = None,
        **kwargs: object,
    ) -> tuple[str, dict[int, int], object]:
        volumes = cast(dict[str, dict[str, str]] | None, kwargs.get("volumes"))
        command = cast(list[str] | None, kwargs.get("command"))
        self.client.containers.run(
            image,
            detach=True,
            auto_remove=False,
            name=name,
            hostname=name,
            network=self.network.id,
            ports=ports or {},
            environment=env or {},
            volumes=volumes,
            command=command,
            sysctls={RESERVED_PORTS_SYSCTL: RESERVED_PORT_RANGE},
        )

        # Containers on the user-defined bridge network resolve each other by
        # name.  This is stable across Docker API versions, unlike the legacy
        # top-level NetworkSettings.IPAddress field.
        return name, dict(ports or {}), None

    def stop(self, name: str) -> None:
        try:
            container = self.client.containers.get(name)
            container.stop()
            container.remove(force=True, v=True)
            print(f"- stopped {name}")
        except docker.errors.NotFound:
            pass

    def download(self, name: str, src_path: str, dst_path: str) -> None:
        container: DockerArchiveContainer | None = None
        paused = False
        try:
            container = cast(DockerArchiveContainer, self.client.containers.get(name))
            container.reload()
            if container.status == "running":
                # Docker creates the archive while reading the live filesystem.
                # A growing log can otherwise invalidate the tar stream with
                # "archive/tar: write too long".
                container.pause()
                paused = True
            stream, _ = container.get_archive(src_path)

            fo = BytesIO()
            for d in stream:
                fo.write(d)
            fo.seek(0)
            with tarfile.open(fileobj=fo) as tar:
                try:
                    tar.extractall(dst_path, filter="data")
                except TypeError:
                    tar.extractall(dst_path)
        except (docker.errors.APIError, docker.errors.NotFound, tarfile.TarError, OSError) as error:
            raise RuntimeError(
                f"Failed to download {name}:{src_path} to {dst_path}: {error}"
            ) from error
        finally:
            if paused and container is not None:
                container.unpause()

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
