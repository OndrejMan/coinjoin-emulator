from abc import ABC, abstractmethod
from multiprocessing.pool import ThreadPool

from manager.exceptions import CoinjoinEmulatorError

MANAGED_LABEL = "coinjoin-emulator.managed"
NAMESPACE_LABEL = "coinjoin-emulator.namespace"
RUN_ID_LABEL = "coinjoin-emulator.run-id"
PRESERVED_CONTAINER_PREFIX = "coinjoin-stale-"
STOPPED_CONTAINER_STATES = frozenset({"created", "dead", "exited", "stopped"})


def managed_labels(namespace: str, run_id: str | None = None) -> dict[str, str]:
    """Return ownership labels for resources created by one emulator run."""
    labels = {
        MANAGED_LABEL: "true",
        NAMESPACE_LABEL: namespace,
    }
    if run_id:
        labels[RUN_ID_LABEL] = run_id
    return labels


def managed_label_filters(namespace: str, run_id: str | None = None) -> list[str]:
    """Return runtime label filters scoped like :func:`managed_labels`."""
    return [f"{key}={value}" for key, value in managed_labels(namespace, run_id).items()]


def preserve_stopped_container(container, inspection: dict, name: str, namespace: str) -> None:
    """Free a reused name without discarding a previous run's container evidence."""
    labels = inspection.get("Config", {}).get("Labels")
    expected = managed_labels(namespace)
    if not isinstance(labels, dict) or any(labels.get(key) != value for key, value in expected.items()):
        raise CoinjoinEmulatorError(
            f"Refusing to replace container {name}: it is not owned by emulator namespace {namespace!r}"
        )
    state = inspection.get("State")
    status = state.get("Status") if isinstance(state, dict) else None
    if status not in STOPPED_CONTAINER_STATES:
        raise CoinjoinEmulatorError(
            f"Refusing to replace container {name}: state is {status or 'unknown'}; "
            "stop it explicitly before starting another run"
        )
    container_id = inspection.get("Id")
    if not isinstance(container_id, str) or not container_id:
        raise CoinjoinEmulatorError(f"Refusing to replace container {name}: container ID is unavailable")
    preserved_name = f"{PRESERVED_CONTAINER_PREFIX}{container_id}"
    container.rename(preserved_name)
    print(f"- preserved stopped container {name} as {preserved_name}")

# The Wasabi backend, coordinator and clients bind fixed ports inside the
# default ephemeral range, where the kernel can hand the same port to an
# outgoing connection first and make the bind fail.
RESERVED_PORT_RANGE = "37127-37260"
RESERVED_PORTS_SYSCTL = "net.ipv4.ip_local_reserved_ports"


class Driver(ABC):
    @abstractmethod
    def has_image(self, name):
        pass

    @abstractmethod
    def build(self, name, path, build_args=None):
        pass

    @abstractmethod
    def pull(self, name):
        pass

    @abstractmethod
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
        pass

    def container_state(self, _name):  # pylint: disable=useless-return
        """Return a human-readable container state, if available."""
        return None

    @abstractmethod
    def stop(self, name):
        pass

    def stop_many(self, names):
        with ThreadPool() as p:
            p.map(lambda x: self.stop(x), names)

    @abstractmethod
    def pause(self, name):
        """Freeze every process of the container so its filesystem stops changing."""

    @abstractmethod
    def unpause(self, name):
        """Resume a container frozen by :meth:`pause`."""

    @abstractmethod
    def download(self, name, src_path, dst_path):
        pass

    @abstractmethod
    def peek(self, name, path):
        pass

    @abstractmethod
    def logs(self, name):
        """Return the container's combined stdout and stderr."""

    def upload(self, name, src_path, dst_path):
        pass

    def get_pod_resource_usage(self, name):
        """Return memory usage for a running container, or None when unknown.

        The engine samples this during a run; a driver that cannot report usage
        answers None instead of raising, so the sampling degrades to a no-op
        rather than logging a failure on every check.
        """
        return None

    @abstractmethod
    def cleanup(self, image_prefix=""):
        pass

    def cleanup_all(self, image_prefix=""):
        """Explicit clean command; drivers may give normal run cleanup a narrower scope."""
        self.cleanup(image_prefix)
