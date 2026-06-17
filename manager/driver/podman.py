import subprocess
from functools import cached_property

from . import Driver


class PodmanDriver(Driver):
    def __init__(self, namespace: str = "coinjoin") -> None:
        self._namespace = namespace

    def _run(
        self,
        args: list[str],
        *,
        stdout: int | None = None,
        stderr: int | None = None,
        capture_output: bool = False,
        text: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["podman", *args],
            check=True,
            stdout=stdout,
            stderr=stderr,
            capture_output=capture_output,
            text=text,
        )

    @cached_property
    def network(self) -> str:
        exists = subprocess.run(
            ["podman", "network", "exists", self._namespace],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if exists.returncode not in (0, 1):
            exists.check_returncode()
        if exists.returncode != 0:
            self._run(["network", "create", self._namespace])
        return self._namespace

    def has_image(self, name: str) -> bool:
        result = subprocess.run(
            ["podman", "image", "exists", name],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if result.returncode not in (0, 1):
            result.check_returncode()
        return result.returncode == 0

    def build(self, name: str, path: str) -> None:
        self._run(["build", "--rm", "--no-cache", "-t", name, path])

    def pull(self, name: str) -> None:
        self._run(["pull", name])

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
    ) -> tuple[str, dict[int, int]]:
        command = [
            "run",
            "-d",
            "--rm",
            "--name",
            name,
            "--hostname",
            name,
            "--network",
            self.network,
        ]

        for container_port, host_port in (ports or {}).items():
            command.extend(["-p", f"{host_port}:{container_port}"])

        for key, value in (env or {}).items():
            if value is not None:
                command.extend(["-e", f"{key}={value}"])

        for host_path, mount in (volumes or {}).items():
            bind_path = mount["bind"]
            mode = mount.get("mode", "rw")
            command.extend(["-v", f"{host_path}:{bind_path}:{mode}"])

        command.append(image)
        self._run(command)
        return name, ports or {}

    def stop(self, name: str) -> None:
        exists = subprocess.run(
            ["podman", "container", "exists", name],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if exists.returncode not in (0, 1):
            exists.check_returncode()
        if exists.returncode == 0:
            self._run(["stop", name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print(f"- stopped {name}")

    def download(self, name: str, src_path: str, dst_path: str) -> None:
        try:
            self._run(["cp", f"{name}:{src_path}", dst_path])
        except subprocess.CalledProcessError:
            pass

    def peek(self, name: str, path: str) -> str:
        result = self._run(["exec", name, "cat", path], capture_output=True, text=True)
        return result.stdout

    def logs(self, name: str) -> str:
        result = self._run(["logs", name], capture_output=True, text=True)
        return result.stdout + result.stderr

    def upload(self, name: str, src_path: str, dst_path: str) -> None:
        self._run(["cp", src_path, f"{name}:{dst_path}"])

    def cleanup(self, image_prefix: str = "") -> None:
        try:
            result = subprocess.run(
                ["podman", "ps", "--format", "{{.Names}}\t{{.Image}}"],
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError:
            return

        containers = []
        for line in result.stdout.splitlines():
            try:
                name, image = line.split("\t", maxsplit=1)
            except ValueError:
                continue
            if any(
                marker in image
                for marker in (
                    "irc-server",
                    "btc-node",
                    "wasabi-backend",
                    "wasabi-client",
                    "wasabi-client-distributor",
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
