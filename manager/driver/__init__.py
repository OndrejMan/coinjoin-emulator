from abc import ABC, abstractmethod
from multiprocessing.pool import ThreadPool

MANAGED_LABEL = "coinjoin-emulator.managed"
NAMESPACE_LABEL = "coinjoin-emulator.namespace"
RUN_ID_LABEL = "coinjoin-emulator.run-id"


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
