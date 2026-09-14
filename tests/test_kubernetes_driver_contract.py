"""Kubernetes driver contracts that keep a shared namespace usable."""

import base64
import io
import subprocess
import tarfile
from concurrent.futures import ThreadPoolExecutor
from threading import Event, RLock
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from kubernetes.client.exceptions import ApiException

from manager.driver.kubernetes import MANAGED_BY_LABEL, MANAGED_BY_VALUE, KubernetesDriver
from manager.exceptions import KubernetesResourceQuotaError, StartupError


def driver(**overrides: object) -> KubernetesDriver:
    instance = object.__new__(KubernetesDriver)
    instance.client = Mock()
    instance.client.read_namespaced_pod_status.return_value = running_pod()
    instance._exec_lock = RLock()  # pylint: disable=protected-access
    instance._namespace = "coinjoin"  # pylint: disable=protected-access
    instance.reuse_namespace = True
    instance.pull_secret_path = None
    instance.in_cluster = False
    instance.run_id = None
    for key, value in overrides.items():
        setattr(instance, key, value)
    return instance


def test_pods_and_services_are_labelled_with_the_run() -> None:
    manifest = driver(run_id="run-42").build_pod_manifest(
        "btc-node", "btc-node:latest", {}, {18443: 18443}, 1.0, 512
    )

    assert manifest["metadata"]["labels"] == {
        "app": "btc-node",
        MANAGED_BY_LABEL: MANAGED_BY_VALUE,
        "coinjoin.run-id": "run-42",
    }


def test_a_host_path_is_mounted_and_a_command_overrides_the_entrypoint() -> None:
    manifest = driver().build_pod_manifest(
        "btc-node",
        "btc-node:latest",
        {},
        {18443: 18443},
        1.0,
        512,
        volumes={"/data/btc": {"bind": "/home/bitcoin/data", "mode": "rw"}},
        command=["./run.sh", "-prune=0"],
    )

    container = manifest["spec"]["containers"][0]
    assert manifest["spec"]["volumes"] == [
        {"name": "host-volume-0", "hostPath": {"path": "/data/btc", "type": "DirectoryOrCreate"}}
    ]
    assert container["volumeMounts"] == [
        {"name": "host-volume-0", "mountPath": "/home/bitcoin/data", "readOnly": False}
    ]
    assert container["command"] == ["./run.sh", "-prune=0"]


def test_cleanup_only_touches_resources_this_emulator_created() -> None:
    instance = driver()
    instance.client.list_namespaced_pod.return_value = SimpleNamespace(
        items=[SimpleNamespace(metadata=SimpleNamespace(name="btc-node"))]
    )
    instance.client.list_namespaced_service.return_value = SimpleNamespace(items=[])

    instance.cleanup()

    selector = f"{MANAGED_BY_LABEL}={MANAGED_BY_VALUE}"
    assert instance.client.list_namespaced_pod.call_args.kwargs["label_selector"] == selector
    assert instance.client.list_namespaced_service.call_args.kwargs["label_selector"] == selector
    instance.client.delete_namespaced_pod.assert_called_once_with(
        name="btc-node", namespace="coinjoin"
    )


def test_a_quota_rejection_is_reported_as_a_quota_error() -> None:
    instance = driver()
    rejection = ApiException(status=403)
    rejection.body = 'pods "btc-node" is forbidden: exceeded quota: cpu'
    instance.client.create_namespaced_pod.side_effect = rejection

    with pytest.raises(KubernetesResourceQuotaError):
        instance.run("btc-node", "btc-node:latest", ports={18443: 18443}, cpu=1.0, memory=512)


def test_a_pod_that_terminates_before_it_gets_an_ip_fails_the_run() -> None:
    instance = driver()
    instance.client.read_namespaced_pod_status.return_value = SimpleNamespace(
        status=SimpleNamespace(pod_ip=None, phase="Failed", reason="Evicted", message="no memory")
    )

    with pytest.raises(StartupError, match="terminal phase Failed"):
        instance._wait_for_pod_ip("btc-node")  # pylint: disable=protected-access


def test_waiting_for_a_pod_ip_has_a_deadline() -> None:
    instance = driver()
    instance.client.read_namespaced_pod_status.return_value = SimpleNamespace(
        status=SimpleNamespace(pod_ip=None, phase="Pending", reason=None, message=None)
    )

    with patch("manager.driver.kubernetes.time.monotonic", side_effect=[0.0, 10_000.0]):
        with pytest.raises(TimeoutError, match="did not receive an IP"):
            instance._wait_for_pod_ip("btc-node")  # pylint: disable=protected-access


def running_pod() -> SimpleNamespace:
    return SimpleNamespace(
        spec=SimpleNamespace(node_name="node-1"), status=SimpleNamespace(phase="Running")
    )


class FakeStream:
    """Exec output delivered in text chunks, followed by a closed connection."""

    def __init__(self, stdout: str = "", stderr: str = "", chunks=()) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.chunks = iter(chunks)
        self.open = True

    def is_open(self) -> bool:
        return self.open

    def update(self, timeout: int) -> None:
        if not self.stdout and not self.stderr:
            self.stdout = next(self.chunks, "")
            self.open = bool(self.stdout)

    def peek_stdout(self) -> bool:
        return bool(self.stdout)

    def read_stdout(self) -> str:
        stdout, self.stdout = self.stdout, ""
        return stdout

    def peek_stderr(self) -> bool:
        return bool(self.stderr)

    def read_stderr(self) -> str:
        stderr, self.stderr = self.stderr, ""
        return stderr

    def close(self) -> None:
        self.open = False


def test_download_preserves_binary_files_across_text_chunks(tmp_path) -> None:
    instance = driver()
    source = tmp_path / "directory with 'quotes'" / "logs"
    source.mkdir(parents=True)
    contents = bytes(range(256))
    (source / "binary.dat").write_bytes(contents)

    def run_command(api, name, namespace, command, **kwargs):
        result = subprocess.run(command, capture_output=True, text=True, check=True, timeout=2)
        return FakeStream(chunks=[result.stdout[i:i + 73] for i in range(0, len(result.stdout), 73)])

    with patch("manager.driver.kubernetes.stream", side_effect=run_command):
        instance.download("jcs-000", str(source) + "/", str(tmp_path / "dst"))

    assert (tmp_path / "dst/logs/binary.dat").read_bytes() == contents


def test_download_rejects_invalid_base64(tmp_path) -> None:
    with patch("manager.driver.kubernetes.stream", return_value=FakeStream(stdout="broken!")):
        with pytest.raises(RuntimeError, match="invalid base64"):
            driver().download("jcs-000", "/logs/", str(tmp_path))


def archive() -> str:
    payload = io.BytesIO()
    contents = b"hello"
    with tarfile.open(fileobj=payload, mode="w") as tar:
        entry = tarfile.TarInfo("logs/run.log")
        entry.size = len(contents)
        tar.addfile(entry, io.BytesIO(contents))
    return base64.b64encode(payload.getvalue()).decode("ascii")


@pytest.mark.parametrize("warning", [
    "tar: logs/run.log: file changed as we read it",
    "tar: logs/rpc.sock: socket ignored",
    "tar: Removing leading `/' from member names",
    "tar: Removing leading `/' from hard link targets",
])
def test_download_keeps_an_archive_with_a_benign_tar_warning(tmp_path, warning) -> None:
    response = FakeStream(stdout=archive(), stderr=warning + "\n")
    with patch("manager.driver.kubernetes.stream", return_value=response):
        driver().download("jcs-000", "/logs/", str(tmp_path))

    assert (tmp_path / "logs/run.log").read_text() == "hello"


def test_download_reports_tar_errors_even_with_a_valid_archive(tmp_path) -> None:
    diagnostics = "tar: logs/run.log: file changed as we read it\ntar: logs: Cannot open\n"
    with patch("manager.driver.kubernetes.stream", return_value=FakeStream(stdout=archive(), stderr=diagnostics)):
        with pytest.raises(RuntimeError, match="Cannot open"):
            driver().download("jcs-000", "/logs/", str(tmp_path))

    assert not (tmp_path / "logs").exists()


def test_download_rejects_empty_output(tmp_path) -> None:
    with patch("manager.driver.kubernetes.stream", return_value=FakeStream()):
        with pytest.raises(RuntimeError, match="empty archive"):
            driver().download("jcs-000", "/logs/", str(tmp_path))


def test_download_timeout_closes_the_connection(tmp_path) -> None:
    response = FakeStream()
    with patch("manager.driver.kubernetes.stream", return_value=response):
        with patch("manager.driver.kubernetes.time.monotonic", side_effect=[0.0, 10_000.0]):
            with pytest.raises(TimeoutError, match="Timed out downloading"):
                driver().download("jcs-000", "/logs/", str(tmp_path))

    assert not response.is_open()


def test_download_closes_the_connection_on_a_read_error(tmp_path) -> None:
    response = FakeStream()
    with patch.object(response, "update", side_effect=OSError("connection lost")):
        with patch("manager.driver.kubernetes.stream", return_value=response):
            with pytest.raises(OSError, match="connection lost"):
                driver().download("jcs-000", "/logs/", str(tmp_path))

    assert not response.is_open()


def test_exec_opens_connections_serially_but_keeps_streams_independent() -> None:
    instance = driver()
    opening_first = Event()
    attempting_second = Event()
    opening_second = Event()
    release_first = Event()

    def open_stream(api, name, namespace, **kwargs):
        if name == "first":
            opening_first.set()
            assert release_first.wait(2)
        else:
            opening_second.set()
        return FakeStream()

    def open_second():
        attempting_second.set()
        return instance._exec_stream("second", ["cat", "/logs"], "read logs")

    with patch("manager.driver.kubernetes.stream", side_effect=open_stream):
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(instance._exec_stream, "first", ["cat", "/logs"], "read logs")
            try:
                assert opening_first.wait(2)
                second = pool.submit(open_second)
                assert attempting_second.wait(2)
                assert not opening_second.wait(0.05)
            finally:
                release_first.set()
            first_stream = first.result(timeout=2)
            second_stream = second.result(timeout=2)

    assert opening_second.is_set()
    assert first_stream is not second_stream
    assert first_stream.is_open() and second_stream.is_open()


def test_exec_api_failure_includes_pod_and_action() -> None:
    instance = driver()
    with patch("manager.driver.kubernetes.stream", side_effect=ApiException(status=404)):
        with pytest.raises(RuntimeError, match="could not read logs on pod missing"):
            instance._exec_stream("missing", ["cat", "/logs"], "read logs")

    with patch("manager.driver.kubernetes.stream", return_value=FakeStream()):
        with ThreadPoolExecutor(max_workers=1) as pool:
            response = pool.submit(instance._exec_stream, "next", ["cat", "/logs"], "read logs").result(timeout=2)
    assert response.is_open()


@pytest.mark.parametrize("method", ["download", "peek"])
@pytest.mark.parametrize("node,phase,message", [
    (None, "Pending", "not scheduled"),
    ("node-1", "Pending", "phase Pending"),
    ("node-1", "Failed", "phase Failed"),
    ("node-1", "Succeeded", "phase Succeeded"),
])
def test_reading_an_unavailable_pod_is_rejected_before_exec(tmp_path, method, node, phase, message) -> None:
    instance = driver()
    instance.client.read_namespaced_pod_status.return_value = SimpleNamespace(
        spec=SimpleNamespace(node_name=node), status=SimpleNamespace(phase=phase)
    )
    arguments = ("jcs-000", "/logs/", str(tmp_path)) if method == "download" else ("jcs-000", "/logs/run.log")
    with patch("manager.driver.kubernetes.stream") as open_stream:
        with pytest.raises(RuntimeError, match=message):
            getattr(instance, method)(*arguments)

    open_stream.assert_not_called()
