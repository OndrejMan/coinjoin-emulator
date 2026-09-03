import os
import tarfile
from functools import cached_property
from io import BytesIO

import docker

from . import Driver


class DockerDriver(Driver):
    def __init__(self, namespace="coinjoin"):
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

    def run(
        self,
        name,
        image,
        env=None,
        ports=None,
        cpu=None,
        memory=None,
        **kwargs
    ):
        self.client.containers.run(
            image,
            detach=True,
            # Keep the container after it exits so its artifacts and logs stay
            # readable while the run is being collected.
            auto_remove=False,
            name=name,
            hostname=name,
            network=self.network.id,
            ports=ports or {},
            environment=env or {},
            volumes=kwargs.get("volumes"),
            command=kwargs.get("command"),
        )
        # Containers on the user-defined bridge network resolve each other by
        # name. That is stable across Docker API versions, unlike the legacy
        # top-level NetworkSettings.IPAddress field, which is empty for them.
        # The requested host port mapping is also what callers must connect to.
        return name, dict(ports or {}), None

    def stop(self, name):
        try:
            container = self.client.containers.get(name)
            container.stop()
            container.remove(force=True, v=True)
            print(f"- stopped {name}")
        except docker.errors.NotFound:
            pass

    def download(self, name, src_path, dst_path):
        container = None
        paused = False
        try:
            container = self.client.containers.get(name)
            container.reload()
            if container.status == "running":
                # Docker builds the archive while reading the live filesystem;
                # a growing log otherwise invalidates the tar stream with
                # "archive/tar: write too long".
                container.pause()
                paused = True
            stream, _ = container.get_archive(src_path)

            fo = BytesIO()
            for d in stream:
                fo.write(d)
            fo.seek(0)
            with tarfile.open(fileobj=fo) as tar:
                tar.extractall(dst_path)
        except (docker.errors.APIError, docker.errors.NotFound, tarfile.TarError, OSError) as error:
            raise RuntimeError(f"Failed to download {name}:{src_path} to {dst_path}: {error}") from error
        finally:
            if paused and container is not None:
                container.unpause()

    def peek(self, name, path):
        stream, _ = self.client.containers.get(name).get_archive(path)

        fo = BytesIO()
        for d in stream:
            fo.write(d)
        fo.seek(0)
        with tarfile.open(fileobj=fo) as tar:
            return tar.extractfile(os.path.basename(path)).read().decode()

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
