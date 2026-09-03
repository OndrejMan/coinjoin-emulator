import subprocess
from functools import cached_property

from manager.exceptions import CoinjoinEmulatorError

from . import Driver


class PodmanDriver(Driver):
    """Drive Podman through its CLI, so no Docker daemon has to be reachable."""

    def __init__(self, namespace: str = "coinjoin") -> None:
        self._namespace = namespace

    def _run(self, args: list[str], *, quiet: bool = False, capture: bool = False):
        return subprocess.run(
            ["podman", *args],
            check=True,
            stdout=subprocess.DEVNULL if quiet else None,
            stderr=subprocess.DEVNULL if quiet else None,
            capture_output=capture,
            text=capture,
        )

    @staticmethod
    def _exists(args: list[str]) -> bool:
        """Run a podman `... exists` probe, which answers with its exit code."""
        result = subprocess.run(
            ["podman", *args], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        if result.returncode not in (0, 1):
            result.check_returncode()
        return result.returncode == 0

    @cached_property
    def network(self) -> str:
        if not self._exists(["network", "exists", self._namespace]):
            self._run(["network", "create", self._namespace])
        return self._namespace

    def has_image(self, name: str) -> bool:
        return self._exists(["image", "exists", name])

    def build(self, name: str, path: str) -> None:
        self._run(["build", "--rm", "--no-cache", "-t", name, path])

    def pull(self, name: str) -> None:
        self._run(["pull", name])

    def run(self, name, image, env=None, ports=None, cpu=None, memory=None, **kwargs):
        del cpu, memory
        self._remove_container(name)

        command = ["run", "-d", "--name", name, "--hostname", name, "--network", self.network]
        for container_port, host_port in (ports or {}).items():
            command.extend(["-p", f"{host_port}:{container_port}"])
        for key, value in (env or {}).items():
            command.extend(["-e", f"{key}={value}"])
        for host_path, mount in (kwargs.get("volumes") or {}).items():
            command.extend(["-v", f"{host_path}:{mount['bind']}:{mount.get('mode', 'rw')}"])
        command.append(image)
        command.extend(kwargs.get("command") or [])
        self._run(command)

        inspect = self._run(
            ["inspect", "--format", "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}", name],
            capture=True,
        )
        container_ip = inspect.stdout.strip()
        if not container_ip:
            raise CoinjoinEmulatorError(f"Podman container {name} has no network address")
        return container_ip, dict(ports or {}), None

    def stop(self, name: str) -> None:
        if self._exists(["container", "exists", name]):
            self._run(["stop", name], quiet=True)
            print(f"- stopped {name}")
        self._remove_container(name)

    def _remove_container(self, name: str) -> None:
        self._run(["rm", "--force", "--ignore", name], quiet=True)

    def download(self, name: str, src_path: str, dst_path: str) -> None:
        try:
            self._run(["cp", f"{name}:{src_path}", dst_path], capture=True)
        except subprocess.CalledProcessError as error:
            details = (error.stderr or "").strip() or (error.stdout or "").strip()
            message = f"Failed to copy {name}:{src_path} to {dst_path}"
            raise CoinjoinEmulatorError(f"{message}: {details}" if details else message) from error

    def peek(self, name: str, path: str) -> str:
        return self._run(["exec", name, "cat", path], capture=True).stdout

    def upload(self, name: str, src_path: str, dst_path: str) -> None:
        self._run(["cp", src_path, f"{name}:{dst_path}"])

    def cleanup(self, image_prefix: str = "") -> None:
        del image_prefix
        try:
            listing = self._run(["ps", "-a", "--format", "{{.Names}}\t{{.Image}}"], capture=True)
        except subprocess.CalledProcessError:
            return

        containers = []
        for line in listing.stdout.splitlines():
            name, _, image = line.partition("\t")
            if any(
                marker in image
                for marker in (
                    "irc-server",
                    "btc-node",
                    "wasabi-backend",
                    "wasabi-client",
                    "wasabi-coordinator",
                    "joinmarket-client-server",
                )
            ):
                containers.append(name)

        self.stop_many(containers)
        subprocess.run(
            ["podman", "network", "rm", self._namespace],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
