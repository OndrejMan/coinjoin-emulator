import os
import tarfile
from io import BytesIO

import podman

from manager.exceptions import CoinjoinEmulatorError

from . import Driver


class PodmanDriver(Driver):
    def __init__(self):
        self.client = podman.PodmanClient()

    def has_image(self, name):
        try:
            self.client.images.get(name)
            return True
        except podman.errors.ImageNotFound:
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
        container = self.client.containers.run(
            image,
            detach=True,
            auto_remove=True,
            name=name,
            hostname=name,
            ports=ports or {},
            environment=env or {},
        )
        container_ip = container.network_settings["IPAddress"]
        port_mapping = container.ports
        return container_ip, port_mapping, None

    def stop(self, name):
        try:
            self.client.containers.get(name).stop(ignore=True)
            print(f"- stopped {name}")
        except podman.errors.NotFound:
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

            print("- stored backend logs")
        except Exception:
            print("- could not store backend logs")

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
        if not self.client.containers.get(name).put_archive(
            os.path.dirname(dst_path), fo.read()
        ):
            raise CoinjoinEmulatorError(f"Failed to copy {src_path} to {name}:{dst_path}")

    def cleanup(self, image_prefix=""):
        containers = []
        for container in self.client.containers.list():
            if any(
                x in container.attrs.get("Image", "")
                for x in ("irc-server", "btc-node", "wasabi-backend", "wasabi-client", "joinmarket-client-server")
            ):
                containers.append(container)
                
        self.stop_many(map(lambda x: x.name, containers))
