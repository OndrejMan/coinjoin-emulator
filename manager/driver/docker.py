from functools import cached_property
from io import BytesIO
import os
import tarfile
import time

from docker.models.containers import Container
from . import Driver
import docker


class DockerDriver(Driver):
    def __init__(self, namespace: str = "coinjoin") -> None:
        self.client: docker.DockerClient = docker.from_env()
        self._namespace = namespace

    @cached_property
    def network(self):
        return self.client.networks.create(self._namespace, driver="bridge")

    def has_image(self, name):
        try:
            self.client.images.get(name)
            return True
        except docker.errors.ImageNotFound:
            return False

    def build(self, name, path):
        self.client.images.build(path=path, tag=name, rm=True, nocache=True)

    def pull(self, name):
        self.client.images.pull(name)

    def _remove_existing_container(self, name):
        try:
            old_container = self.client.containers.get(name)
            old_container.remove(force=True)
            return True
        except docker.errors.NotFound:
            return False

    @staticmethod
    def _is_name_conflict(error):
        explanation = getattr(error, "explanation", "") or str(error)
        return "container name" in explanation and "already in use" in explanation

    def run(
        self,
        name,
        image,
        env=None,
        ports=None,
        skip_ip=False,
        cpu=0.1,
        memory=768,
        volumes: dict | None = None
    ):
        self._remove_existing_container(name)

        for attempt in range(2):
            try:
                self.client.containers.run(
                    image,
                    detach=True,
                    auto_remove=False,
                    name=name,
                    hostname=name,
                    network=self.network.id,
                    ports=ports or {},
                    environment={
                        key: value
                        for key, value in (env or {}).items()
                        if value is not None
                    },
                    volumes=volumes,
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

    def stop(self, name):
        try:
            container = self.client.containers.get(name)
            container.stop()
            container.remove(force=True)
            print(f"- stopped {name}")
        except docker.errors.NotFound:
            pass

    def download(self, name, src_path, dst_path):
        try:
            stream, _ = self.client.containers.get(name).get_archive(src_path)

            fo = BytesIO()
            for d in stream:
                fo.write(d)
            fo.seek(0)
            with tarfile.open(fileobj=fo) as tar:
                tar.extractall(dst_path)
        except:
            pass

    def peek(self, name, path):
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

    def logs(self, name):
        return self.client.containers.get(name).logs(stdout=True, stderr=True).decode()

    def upload(self, name, src_path, dst_path):
        fo = BytesIO()
        with tarfile.open(fileobj=fo, mode="w") as tar:
            tar.add(src_path, os.path.basename(dst_path))
        fo.seek(0)
        self.client.containers.get(name).put_archive(os.path.dirname(dst_path), fo)

    def cleanup(self, image_prefix=""):
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

        self.stop_many(map(lambda x: x.name, containers))
        networks = self.client.networks.list(self._namespace)
        if networks:
            for network in networks:
                network.remove()
