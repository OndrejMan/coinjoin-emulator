"""Kubernetes ownership, storage, and startup-failure contracts."""

import base64
import tarfile
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock, patch

import pytest
from kubernetes.client.exceptions import ApiException

from manager.driver import RESERVED_PORT_RANGE, RESERVED_PORTS_SYSCTL
from manager.driver.kubernetes import MANAGED_BY_LABEL, MANAGED_BY_VALUE, KubernetesDriver
from manager.exceptions import KubernetesResourceQuotaError, StartupError


def driver() -> KubernetesDriver:
    runtime = object.__new__(KubernetesDriver)
    runtime.client = Mock()
    runtime.client.read_namespaced_pod_status.return_value = SimpleNamespace(
        spec=SimpleNamespace(node_name="node-1"),
        status=SimpleNamespace(phase="Running"),
    )
    runtime._namespace = "coinjoin"  # pylint: disable=protected-access
    runtime.reuse_namespace = True
    runtime.pull_secret_path = None
    runtime.in_cluster = True
    runtime.run_id = "run-123"
    return runtime


def test_manifest_labels_resources_and_mounts_for_one_run() -> None:
    runtime = driver()

    manifest = runtime.build_pod_manifest(
        "btc-node",
        "example/btc:exact",
        {},
        {18443: 18443},
        2.0,
        2048,
        volumes={"/data/run": {"bind": "/home/bitcoin/data", "mode": "rw"}},
        command=["./run.sh", "-blocksxor=0"],
    )

    metadata = manifest["metadata"]
    spec = manifest["spec"]
    assert isinstance(metadata, dict) and isinstance(spec, dict)
    assert metadata["labels"] == {
        "app": "btc-node",
        MANAGED_BY_LABEL: MANAGED_BY_VALUE,
        "coinjoin.run-id": "run-123",
    }
    container = spec["containers"][0]
    assert container["command"] == ["./run.sh", "-blocksxor=0"]
    assert container["volumeMounts"][0]["mountPath"] == "/home/bitcoin/data"
    assert spec["volumes"][0]["hostPath"]["path"] == "/data/run"
    assert spec["securityContext"] == {
        "sysctls": [{"name": RESERVED_PORTS_SYSCTL, "value": RESERVED_PORT_RANGE}]
    }


def test_sysctl_api_rejection_retries_without_the_reserved_range() -> None:
    runtime = driver()
    api = cast(Mock, runtime.client)
    rejection = ApiException()
    rejection.status = 422
    rejection.body = "forbidden sysctl"
    api.create_namespaced_pod.side_effect = [rejection, None]
    api.read_namespaced_pod_status.return_value = SimpleNamespace(
        status=SimpleNamespace(pod_ip="10.42.0.10", phase="Running")
    )

    runtime.run("btc-node", "example/btc", ports={})

    assert api.create_namespaced_pod.call_count == 2
    retried_manifest = api.create_namespaced_pod.call_args.kwargs["body"]
    assert "securityContext" not in retried_manifest["spec"]


def test_terminal_pod_phase_fails_instead_of_waiting_forever() -> None:
    runtime = driver()
    api = cast(Mock, runtime.client)
    api.read_namespaced_pod_status.return_value = SimpleNamespace(
        status=SimpleNamespace(pod_ip=None, phase="Failed")
    )

    with pytest.raises(StartupError, match="terminal phase Failed"):
        runtime.run("broken", "example/broken", ports={})


def test_quota_rejection_is_actionable() -> None:
    runtime = driver()
    api = cast(Mock, runtime.client)
    quota_error = ApiException()
    quota_error.status = 403
    quota_error.body = "exceeded quota: requested limits.cpu=2"
    api.create_namespaced_pod.side_effect = quota_error

    with pytest.raises(KubernetesResourceQuotaError, match="quota rejected pod"):
        runtime.run("btc-node", "example/btc", ports={})


def test_cleanup_selects_only_managed_resources() -> None:
    runtime = driver()
    api = cast(Mock, runtime.client)
    api.list_namespaced_pod.return_value = SimpleNamespace(items=[])
    api.list_namespaced_service.return_value = SimpleNamespace(items=[])

    runtime.cleanup()

    selector = f"{MANAGED_BY_LABEL}={MANAGED_BY_VALUE}"
    api.list_namespaced_pod.assert_called_once_with(
        namespace="coinjoin", label_selector=selector
    )
    api.list_namespaced_service.assert_called_once_with(
        namespace="coinjoin", label_selector=selector
    )


class ClosedExecResponse:
    returncode = 0

    def is_open(self) -> bool:
        return False

    def close(self) -> None:
        return None


class DownloadExecResponse:
    returncode = 0

    def __init__(self, stdout: str, stderr: str = "") -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.open = True

    def is_open(self) -> bool:
        return self.open

    def update(self, timeout: int) -> None:
        del timeout
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
        return None


def test_upload_uses_chunked_base64_commands(tmp_path: Path) -> None:
    runtime = driver()
    source = tmp_path / "scenario.json"
    source.write_text('{"name": "scenario"}', encoding="utf-8")

    with patch("manager.driver.kubernetes.stream", side_effect=lambda *args, **kwargs: ClosedExecResponse()) as run:
        runtime.upload("manager", str(source), "/work/scenario.json")

    commands = [call.kwargs["command"] for call in run.call_args_list]
    assert commands[0][:3] == ["sh", "-c", 'printf "%s" "$1" > "$2"']
    assert commands[-1][2].startswith("base64 -d")


def test_download_uses_unwrapped_base64_and_extracts_the_archive(tmp_path: Path) -> None:
    runtime = driver()
    archive = BytesIO()
    with tarfile.open(fileobj=archive, mode="w") as tar:
        payload = b"regtest data"
        member = tarfile.TarInfo("data/marker")
        member.size = len(payload)
        tar.addfile(member, BytesIO(payload))
    response = DownloadExecResponse(base64.b64encode(archive.getvalue()).decode("ascii"))

    with patch("manager.driver.kubernetes.stream", return_value=response) as run:
        runtime.download("btc-node", "/home/bitcoin/data/", str(tmp_path))

    command = run.call_args.kwargs["command"]
    assert command[2].endswith("base64 | tr -d '\\n'")
    assert (tmp_path / "data" / "marker").read_bytes() == b"regtest data"


@pytest.mark.parametrize("phase", ["Succeeded", "Failed"])
def test_download_refuses_pods_whose_containers_have_exited(tmp_path: Path, phase: str) -> None:
    runtime = driver()
    api = cast(Mock, runtime.client)
    api.read_namespaced_pod_status.return_value = SimpleNamespace(
        spec=SimpleNamespace(node_name="node-1"),
        status=SimpleNamespace(phase=phase),
    )

    with patch(
        "manager.driver.kubernetes.stream",
        side_effect=AssertionError("download must not exec into a terminated container"),
    ):
        with pytest.raises(RuntimeError, match=f"phase {phase}"):
            runtime.download("wasabi-coordinator", "/home/wasabi", str(tmp_path))


def test_download_refuses_an_unscheduled_pod(tmp_path: Path) -> None:
    runtime = driver()
    api = cast(Mock, runtime.client)
    api.read_namespaced_pod_status.return_value = SimpleNamespace(
        spec=SimpleNamespace(node_name=None),
        status=SimpleNamespace(phase="Pending"),
    )

    with patch(
        "manager.driver.kubernetes.stream",
        side_effect=AssertionError("download must not exec into an unscheduled pod"),
    ):
        with pytest.raises(RuntimeError, match="never scheduled"):
            runtime.download("btc-node", "/home/bitcoin/data", str(tmp_path))


def test_download_keeps_archive_when_a_live_log_changes(tmp_path: Path) -> None:
    runtime = driver()
    archive = BytesIO()
    with tarfile.open(fileobj=archive, mode="w") as tar:
        payload = b"wallet log"
        member = tarfile.TarInfo("joinmarket/log.txt")
        member.size = len(payload)
        tar.addfile(member, BytesIO(payload))
    response = DownloadExecResponse(
        base64.b64encode(archive.getvalue()).decode("ascii"),
        "tar: joinmarket/log.txt: file changed as we read it\n",
    )

    with patch("manager.driver.kubernetes.stream", return_value=response):
        runtime.download("jcs-009", "/home/joinmarket", str(tmp_path))

    assert (tmp_path / "joinmarket" / "log.txt").read_bytes() == b"wallet log"


def test_download_still_fails_on_a_real_tar_error(tmp_path: Path) -> None:
    runtime = driver()
    response = DownloadExecResponse(
        "ignored",
        "tar: /home/joinmarket: Cannot open: No such file or directory\n",
    )

    with patch("manager.driver.kubernetes.stream", return_value=response):
        with pytest.raises(RuntimeError, match="Cannot open"):
            runtime.download("jcs-009", "/home/joinmarket", str(tmp_path))


def test_download_rejects_an_empty_archive_even_with_a_benign_warning(tmp_path: Path) -> None:
    runtime = driver()
    response = DownloadExecResponse(
        "",
        "tar: joinmarket/log.txt: file changed as we read it\n",
    )

    with patch("manager.driver.kubernetes.stream", return_value=response):
        with pytest.raises(RuntimeError, match="empty archive"):
            runtime.download("jcs-009", "/home/joinmarket", str(tmp_path))


def test_storage_identity_reaches_the_pod_security_context() -> None:
    runtime = driver()

    manifest = runtime.build_pod_manifest(
        "btc-node",
        "example/btc:exact",
        {},
        {18443: 18443},
        2.0,
        2048,
        1000,
        volumes={"/data/run": {"bind": "/home/bitcoin/data", "mode": "rw"}},
        group_id=2000,
    )

    spec = manifest["spec"]
    assert isinstance(spec, dict)
    security_context = spec["containers"][0]["securityContext"]
    assert security_context["runAsUser"] == 1000
    assert security_context["runAsGroup"] == 2000
    assert security_context["runAsNonRoot"] is True


def test_group_defaults_to_the_user_when_unset() -> None:
    runtime = driver()

    manifest = runtime.build_pod_manifest(
        "btc-node", "example/btc:exact", {}, {18443: 18443}, 2.0, 2048, 1000
    )

    spec = manifest["spec"]
    assert isinstance(spec, dict)
    assert spec["containers"][0]["securityContext"]["runAsGroup"] == 1000
