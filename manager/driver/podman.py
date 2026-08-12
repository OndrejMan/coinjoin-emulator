import os
import tarfile
from io import BytesIO
from typing import cast

import docker
import podman

from . import Driver


class PodmanDriver(Driver):
    def __init__(self) -> None:
        self.client = podman.PodmanClient()

    def has_image(self, name: str) -> bool:
        try:
            docker.from_env().images.get(name)
            return True
        except docker.errors.ImageNotFound:
            return False

    def build(self, name: str, path: str) -> None:
        docker.from_env().images.build(path=path, tag=name, rm=True, nocache=True)

    def pull(self, name: str) -> None:
        docker.from_env().images.pull(name)

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
        container = self.client.containers.run(
            image,
            detach=True,
            auto_remove=True,
            name=name,
            hostname=name,
            ports=ports or {},
            environment=env or {},
        )
        container_ip = str(container.network_settings["IPAddress"])
        port_mapping = cast(dict[int, int], container.ports)
        return container_ip, port_mapping, None

    def stop(self, name: str) -> None:
        try:
            self.client.containers.get(name).stop()
            print(f"- stopped {name}")
        except docker.errors.NotFound:
            pass

    def download(self, name: str, src_path: str, dst_path: str) -> None:
        try:
            stream, _ = docker.from_env().containers.get(name).get_archive(src_path)

            fo = BytesIO()
            for d in stream:
                fo.write(d)
            fo.seek(0)
            with tarfile.open(fileobj=fo) as tar:
                tar.extractall(dst_path)

            print("- stored backend logs")
        except Exception:
            print("- could not store backend logs")

    def peek(self, name: str, path: str) -> str:
        stream, _ = docker.from_env().containers.get(name).get_archive(path)

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
        docker.from_env().containers.get(name).put_archive(
            os.path.dirname(dst_path), fo
        )

    def cleanup(self, image_prefix: str = "") -> None:
        containers = []
        for container in docker.from_env().containers.list():
            if any(
                x in container.attrs["Config"]["Image"]
                for x in ("irc-server", "btc-node", "wasabi-backend", "wasabi-client", "joinmarket-client-server")
            ):
                containers.append(container)
                
        self.stop_many(str(container.name) for container in containers)
