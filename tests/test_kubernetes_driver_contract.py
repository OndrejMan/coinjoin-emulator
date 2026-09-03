"""Kubernetes driver contracts that keep a shared namespace usable."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from kubernetes.client.exceptions import ApiException

from manager.driver.kubernetes import MANAGED_BY_LABEL, MANAGED_BY_VALUE, KubernetesDriver
from manager.exceptions import KubernetesResourceQuotaError, StartupError


def driver(**overrides: object) -> KubernetesDriver:
    instance = object.__new__(KubernetesDriver)
    instance.client = Mock()
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
    """A one-shot exec stream that closes once its output has been read."""

    def __init__(self, stdout: str = "", stderr: str = "") -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.open = True

    def is_open(self) -> bool:
        return self.open

    def update(self, timeout: int) -> None:
        if not self.stdout and not self.stderr:
            self.open = False

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


def archive(tmp_path) -> str:
    import base64
    import io
    import tarfile

    payload = io.BytesIO()
    source = tmp_path / "logs"
    source.mkdir(parents=True)
    (source / "run.log").write_text("hello", encoding="utf-8")
    with tarfile.open(fileobj=payload, mode="w") as tar:
        tar.add(source, arcname="logs")
    return base64.b64encode(payload.getvalue()).decode("ascii")


def test_download_decodes_the_base64_archive(tmp_path) -> None:
    instance = driver()
    instance.client.read_namespaced_pod_status.return_value = running_pod()
    encoded = archive(tmp_path / "src")
    destination = tmp_path / "dst"
    destination.mkdir()

    with patch("manager.driver.kubernetes.stream", return_value=FakeStream(stdout=encoded)):
        instance.download("jcs-000", "/home/joinmarket/logs/", str(destination))

    assert (destination / "logs" / "run.log").read_text(encoding="utf-8") == "hello"


def test_download_keeps_an_archive_that_only_warned_about_changing_files(tmp_path) -> None:
    instance = driver()
    instance.client.read_namespaced_pod_status.return_value = running_pod()
    encoded = archive(tmp_path / "src")
    destination = tmp_path / "dst"
    destination.mkdir()
    warning = "tar: logs/run.log: file changed as we read it\n"

    with patch(
        "manager.driver.kubernetes.stream", return_value=FakeStream(stdout=encoded, stderr=warning)
    ):
        instance.download("jcs-000", "/home/joinmarket/logs/", str(destination))

    assert (destination / "logs" / "run.log").is_file()


def test_download_reports_a_real_tar_error(tmp_path) -> None:
    instance = driver()
    instance.client.read_namespaced_pod_status.return_value = running_pod()

    with patch(
        "manager.driver.kubernetes.stream",
        return_value=FakeStream(stderr="tar: /home/joinmarket/logs: Cannot open: No such file\n"),
    ):
        with pytest.raises(RuntimeError, match="Cannot open"):
            instance.download("jcs-000", "/home/joinmarket/logs/", str(tmp_path))


def test_reading_from_a_pod_that_is_not_running_is_rejected(tmp_path) -> None:
    instance = driver()
    instance.client.read_namespaced_pod_status.return_value = SimpleNamespace(
        spec=SimpleNamespace(node_name="node-1"), status=SimpleNamespace(phase="Failed")
    )

    with pytest.raises(RuntimeError, match="phase Failed"):
        instance.download("jcs-000", "/logs/", str(tmp_path))


def test_upload_stages_the_archive_in_chunks_and_unpacks_it(tmp_path) -> None:
    instance = driver()
    source = tmp_path / "scenario.json"
    source.write_text("{}", encoding="utf-8")
    commands = []

    def record(api, name, namespace, command, **kwargs):
        commands.append(command)
        return FakeStream()

    with patch("manager.driver.kubernetes.stream", side_effect=record):
        instance.upload("jcs-000", str(source), "/app/scenario.json")

    assert all(command[0] == "sh" for command in commands[:-1])
    assert "base64 -d" in commands[-1][2] and "tar xf -" in commands[-1][2]


def test_upload_fails_when_the_remote_command_writes_to_stderr(tmp_path) -> None:
    instance = driver()
    source = tmp_path / "scenario.json"
    source.write_text("{}", encoding="utf-8")

    with patch(
        "manager.driver.kubernetes.stream",
        return_value=FakeStream(stderr="tar: /app: Cannot open\n"),
    ):
        with pytest.raises(RuntimeError, match="upload to jcs-000:/app/scenario.json failed"):
            instance.upload("jcs-000", str(source), "/app/scenario.json")
