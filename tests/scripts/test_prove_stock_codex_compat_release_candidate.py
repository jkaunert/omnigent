"""Tests for ``scripts/prove_stock_codex_compat_release_candidate.py``."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "prove_stock_codex_compat_release_candidate.py"


def _load_module() -> Any:
    spec = importlib.util.spec_from_file_location(
        "scripts_prove_stock_codex_compat_release_candidate",
        _SCRIPT_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_MOD = _load_module()


def _write_file(path: Path, text: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _release_ready_stdout(*, direct_ssh: bool = False) -> str:
    tart_name = "None" if direct_ssh else "omnigent-clean"
    ssh_target = "omnigent-clean@10.0.0.10" if direct_ssh else "None"
    tart_count = 0 if direct_ssh else 5
    step_tart_value = "false" if direct_ssh else "true"
    return "\n".join(
        [
            "ignored=noise",
            "stock_codex_compat_pkg_clean_vm_release_status=replacement-ready",
            "stock_codex_compat_pkg_clean_vm_release_missing_prerequisites=[]",
            "stock_codex_compat_pkg_clean_vm_release_package_path=/tmp/compat.pkg",
            "stock_codex_compat_pkg_clean_vm_release_package_sha256=pkg-sha",
            "stock_codex_compat_pkg_clean_vm_release_stock_codex_version=0.143.0",
            "stock_codex_compat_pkg_clean_vm_release_stock_codex_sha256=codex-sha",
            "stock_codex_compat_pkg_clean_vm_release_cask_version=0.143.0",
            "stock_codex_compat_pkg_clean_vm_release_cask_url=https://example.test/codex.tgz",
            "stock_codex_compat_pkg_clean_vm_release_cask_sha256=cask-sha",
            "stock_codex_compat_pkg_clean_vm_release_channel_policy=official-openai-github-release",
            f"stock_codex_compat_pkg_clean_vm_release_tart_name={tart_name}",
            f"stock_codex_compat_pkg_clean_vm_release_ssh_target={ssh_target}",
            f"stock_codex_compat_pkg_clean_vm_release_tart_started_count={tart_count}",
            f"stock_codex_compat_pkg_clean_vm_release_tart_stopped_count={tart_count}",
            (
                "stock_codex_compat_pkg_clean_vm_release_step_order="
                '["remote-acquisition","auth-onboarding","auth-persistence",'
                '"update-agent","live"]'
            ),
            (
                "stock_codex_compat_pkg_clean_vm_release_step_statuses="
                '{"auth-onboarding":"replacement-ready",'
                '"auth-persistence":"replacement-ready",'
                '"live":"replacement-ready",'
                '"remote-acquisition":"replacement-ready",'
                '"update-agent":"replacement-ready"}'
            ),
            "stock_codex_compat_pkg_clean_vm_release_step_missing_prerequisites={}",
            "stock_codex_compat_pkg_clean_vm_release_blocked_step=None",
            "stock_codex_compat_pkg_clean_vm_release_host_stock_codex_uploaded_any=False",
            (
                "stock_codex_compat_pkg_clean_vm_release_step_details="
                '{"remote-acquisition":{"status":"replacement-ready",'
                '"remoteStatus":"replacement-ready","hostStockCodexUploaded":false,'
                f'"tartStarted":{step_tart_value},"tartStopped":{step_tart_value},'
                '"threadId":null,"scheduledAction":null},'
                '"auth-onboarding":{"status":"replacement-ready",'
                '"remoteStatus":"replacement-ready","hostStockCodexUploaded":false,'
                f'"tartStarted":{step_tart_value},"tartStopped":{step_tart_value},'
                '"threadId":null,"scheduledAction":null},'
                '"auth-persistence":{"status":"replacement-ready",'
                '"remoteStatus":"replacement-ready","hostStockCodexUploaded":false,'
                f'"tartStarted":{step_tart_value},"tartStopped":{step_tart_value},'
                '"threadId":"thread-auth","scheduledAction":null},'
                '"update-agent":{"status":"replacement-ready",'
                '"remoteStatus":"replacement-ready","hostStockCodexUploaded":false,'
                f'"tartStarted":{step_tart_value},"tartStopped":{step_tart_value},'
                '"threadId":null,"scheduledAction":"up-to-date"},'
                '"live":{"status":"replacement-ready",'
                '"remoteStatus":"replacement-ready","hostStockCodexUploaded":false,'
                f'"tartStarted":{step_tart_value},"tartStopped":{step_tart_value},'
                '"threadId":"thread-live","scheduledAction":null}}'
            ),
        ]
    )


def test_release_candidate_wrapper_builds_tart_command(tmp_path: Path) -> None:
    proof_script = _write_file(tmp_path / "scripts" / "prove.py")
    pkg_path = _write_file(tmp_path / "artifacts" / "compat.pkg")

    args = _MOD.parse_args(
        [
            "--python",
            "/opt/python",
            "--proof-script",
            str(proof_script),
            "--pkg-path",
            str(pkg_path),
            "--codex-path",
            "~/stock/codex",
            "--clean-vm-tart-name",
            "omnigent-clean",
            "--clean-vm-ssh-identity",
            "~/.ssh/id_release",
        ]
    )

    command = _MOD.build_command(args)

    assert command == (
        "/opt/python",
        str(proof_script.resolve()),
        "--proof",
        "stock-codex-compat-pkg-clean-vm-release",
        "--pkg-path",
        str(pkg_path.resolve()),
        "--codex-path",
        str(Path("~/stock/codex").expanduser()),
        "--clean-vm-tart-name",
        "omnigent-clean",
        "--clean-vm-ssh-user",
        "admin",
        "--clean-vm-ssh-identity",
        str(Path("~/.ssh/id_release").expanduser()),
        "--clean-vm-start-tart",
    )


def test_release_candidate_wrapper_builds_direct_ssh_command(tmp_path: Path) -> None:
    proof_script = _write_file(tmp_path / "scripts" / "prove.py")
    pkg_path = _write_file(tmp_path / "artifacts" / "compat.pkg")

    args = _MOD.parse_args(
        [
            "--python",
            "/opt/python",
            "--proof-script",
            str(proof_script),
            "--pkg-path",
            str(pkg_path),
            "--codex-path",
            "~/stock/codex",
            "--clean-vm-ssh-target",
            "omnigent-clean@10.0.0.10",
            "--clean-vm-ssh-identity",
            "~/.ssh/id_release",
        ]
    )

    command = _MOD.build_command(args)

    assert command == (
        "/opt/python",
        str(proof_script.resolve()),
        "--proof",
        "stock-codex-compat-pkg-clean-vm-release",
        "--pkg-path",
        str(pkg_path.resolve()),
        "--codex-path",
        str(Path("~/stock/codex").expanduser()),
        "--clean-vm-ssh-target",
        "omnigent-clean@10.0.0.10",
        "--clean-vm-ssh-identity",
        str(Path("~/.ssh/id_release").expanduser()),
    )
    assert "--clean-vm-start-tart" not in command
    assert "--clean-vm-tart-name" not in command


def test_release_candidate_wrapper_uses_environment_defaults(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    proof_script = _write_file(tmp_path / "scripts" / "prove.py")
    pkg_path = _write_file(tmp_path / "artifacts" / "compat.pkg")
    monkeypatch.setenv(_MOD.ENV_PKG_PATH, str(pkg_path))
    monkeypatch.setenv(_MOD.ENV_TART_NAME, "env-clean-vm")
    monkeypatch.setenv(_MOD.ENV_SSH_USER, "release-admin")
    monkeypatch.setenv(_MOD.ENV_SSH_PORT, "2222")

    args = _MOD.parse_args(
        ["--python", "/opt/python", "--proof-script", str(proof_script)]
    )

    command = _MOD.build_command(args)

    assert "--pkg-path" in command
    assert command[command.index("--pkg-path") + 1] == str(pkg_path.resolve())
    assert command[command.index("--clean-vm-tart-name") + 1] == "env-clean-vm"
    assert command[command.index("--clean-vm-ssh-user") + 1] == "release-admin"
    assert command[command.index("--clean-vm-ssh-port") + 1] == "2222"
    assert "--clean-vm-start-tart" in command


def test_release_candidate_wrapper_rejects_ambiguous_vm_target(tmp_path: Path) -> None:
    proof_script = _write_file(tmp_path / "scripts" / "prove.py")
    pkg_path = _write_file(tmp_path / "artifacts" / "compat.pkg")
    args = _MOD.parse_args(
        [
            "--proof-script",
            str(proof_script),
            "--pkg-path",
            str(pkg_path),
            "--clean-vm-tart-name",
            "omnigent-clean",
            "--clean-vm-ssh-target",
            "admin@192.0.2.10",
        ]
    )

    with pytest.raises(SystemExit, match="either --clean-vm-tart-name"):
        _MOD.build_command(args)


def test_release_candidate_wrapper_rejects_missing_package(tmp_path: Path) -> None:
    proof_script = _write_file(tmp_path / "scripts" / "prove.py")
    args = _MOD.parse_args(
        [
            "--proof-script",
            str(proof_script),
            "--pkg-path",
            str(tmp_path / "missing.pkg"),
            "--clean-vm-tart-name",
            "omnigent-clean",
        ]
    )

    with pytest.raises(SystemExit, match="artifact is missing"):
        _MOD.build_command(args)


def test_release_candidate_wrapper_print_command_does_not_run(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    proof_script = _write_file(tmp_path / "scripts" / "prove.py")
    pkg_path = _write_file(tmp_path / "artifacts" / "compat.pkg")

    def fail_run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        raise AssertionError("subprocess.run should not be called")

    monkeypatch.setattr(_MOD.subprocess, "run", fail_run)

    exit_code = _MOD.main(
        [
            "--python",
            "/opt/python",
            "--proof-script",
            str(proof_script),
            "--pkg-path",
            str(pkg_path),
            "--clean-vm-tart-name",
            "omnigent-clean",
            "--print-command",
        ]
    )

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "stock-codex-compat-pkg-clean-vm-release" in output
    assert "--clean-vm-start-tart" in output


def test_release_candidate_wrapper_returns_underlying_exit_code(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    proof_script = _write_file(tmp_path / "scripts" / "prove.py")
    pkg_path = _write_file(tmp_path / "artifacts" / "compat.pkg")
    calls: list[tuple[tuple[str, ...], bool]] = []

    def fake_run(command: tuple[str, ...], *, check: bool) -> SimpleNamespace:
        calls.append((command, check))
        return SimpleNamespace(returncode=17)

    monkeypatch.setattr(_MOD.subprocess, "run", fake_run)

    exit_code = _MOD.main(
        [
            "--python",
            "/opt/python",
            "--proof-script",
            str(proof_script),
            "--pkg-path",
            str(pkg_path),
            "--clean-vm-tart-name",
            "omnigent-clean",
        ]
    )

    assert exit_code == 17
    assert calls
    assert calls[0][1] is False


def test_release_candidate_wrapper_writes_machine_readable_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    proof_script = _write_file(tmp_path / "scripts" / "prove.py")
    pkg_path = _write_file(tmp_path / "artifacts" / "compat.pkg")
    evidence_path = tmp_path / "artifacts" / "release-evidence.json"
    stdout = _release_ready_stdout()
    calls: list[dict[str, Any]] = []

    def fake_run(command: tuple[str, ...], **kwargs: object) -> SimpleNamespace:
        calls.append({"command": command, "kwargs": kwargs})
        return SimpleNamespace(returncode=0, stdout=stdout, stderr="stderr line\n")

    monkeypatch.setattr(_MOD.subprocess, "run", fake_run)

    exit_code = _MOD.main(
        [
            "--python",
            "/opt/python",
            "--proof-script",
            str(proof_script),
            "--pkg-path",
            str(pkg_path),
            "--clean-vm-tart-name",
            "omnigent-clean",
            "--evidence-output",
            str(evidence_path),
        ]
    )

    assert exit_code == 0
    assert calls
    assert calls[0]["kwargs"] == {"check": False, "capture_output": True, "text": True}
    captured = capsys.readouterr()
    assert "stock_codex_compat_pkg_clean_vm_release_status=replacement-ready" in captured.out
    assert "stderr line" in captured.err
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert evidence["kind"] == _MOD.EVIDENCE_KIND
    assert evidence["schemaVersion"] == _MOD.EVIDENCE_SCHEMA_VERSION
    assert evidence["proof"] == "stock-codex-compat-pkg-clean-vm-release"
    assert evidence["exitCode"] == 0
    assert evidence["underlyingExitCode"] == 0
    assert evidence["releaseCriteriaFailures"] == []
    assert evidence["status"] == "replacement-ready"
    assert evidence["missingPrerequisites"] == []
    assert evidence["packageSha256"] == "pkg-sha"
    assert evidence["stockCodexVersion"] == "0.143.0"
    assert evidence["stockCodexSha256"] == "codex-sha"
    assert evidence["caskVersion"] == "0.143.0"
    assert evidence["caskUrl"] == "https://example.test/codex.tgz"
    assert evidence["caskSha256"] == "cask-sha"
    assert evidence["channelPolicy"] == "official-openai-github-release"
    assert evidence["stepOrder"] == [
        "remote-acquisition",
        "auth-onboarding",
        "auth-persistence",
        "update-agent",
        "live",
    ]
    assert evidence["stepStatuses"]["live"] == "replacement-ready"
    assert evidence["stepMissingPrerequisites"] == {}
    assert evidence["blockedStep"] is None
    assert evidence["tartStartedCount"] == 5
    assert evidence["tartStoppedCount"] == 5
    assert evidence["hostStockCodexUploadedAny"] is False
    assert evidence["stepDetails"]["live"]["threadId"] == "thread-live"
    assert evidence["stdoutLineCount"] == stdout.count("\n") + 1
    assert evidence["stderrLineCount"] == 1
    assert evidence["fields"]["package_path"] == "/tmp/compat.pkg"


def test_release_candidate_wrapper_writes_direct_ssh_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    proof_script = _write_file(tmp_path / "scripts" / "prove.py")
    pkg_path = _write_file(tmp_path / "artifacts" / "compat.pkg")
    evidence_path = tmp_path / "artifacts" / "direct-release-evidence.json"

    def fake_run(command: tuple[str, ...], **_kwargs: object) -> SimpleNamespace:
        assert "--clean-vm-ssh-target" in command
        assert "--clean-vm-start-tart" not in command
        return SimpleNamespace(
            returncode=0,
            stdout=_release_ready_stdout(direct_ssh=True),
            stderr="",
        )

    monkeypatch.setattr(_MOD.subprocess, "run", fake_run)

    exit_code = _MOD.main(
        [
            "--python",
            "/opt/python",
            "--proof-script",
            str(proof_script),
            "--pkg-path",
            str(pkg_path),
            "--clean-vm-ssh-target",
            "omnigent-clean@10.0.0.10",
            "--evidence-output",
            str(evidence_path),
        ]
    )

    assert exit_code == 0
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert evidence["targetMode"] == "direct-ssh"
    assert evidence["tartName"] is None
    assert evidence["sshTarget"] == "omnigent-clean@10.0.0.10"
    assert evidence["tartStartedCount"] == 0
    assert evidence["tartStoppedCount"] == 0
    assert evidence["releaseCriteriaFailures"] == []
    assert evidence["stepDetails"]["live"]["tartStarted"] is False
    assert evidence["stepDetails"]["live"]["threadId"] == "thread-live"


def test_release_candidate_wrapper_rejects_direct_ssh_tart_activity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    proof_script = _write_file(tmp_path / "scripts" / "prove.py")
    pkg_path = _write_file(tmp_path / "artifacts" / "compat.pkg")
    evidence_path = tmp_path / "artifacts" / "bad-direct-release-evidence.json"
    stdout = _release_ready_stdout(direct_ssh=True).replace(
        "stock_codex_compat_pkg_clean_vm_release_tart_started_count=0",
        "stock_codex_compat_pkg_clean_vm_release_tart_started_count=1",
    )

    def fake_run(_command: tuple[str, ...], **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(returncode=0, stdout=stdout, stderr="")

    monkeypatch.setattr(_MOD.subprocess, "run", fake_run)

    exit_code = _MOD.main(
        [
            "--proof-script",
            str(proof_script),
            "--pkg-path",
            str(pkg_path),
            "--clean-vm-ssh-target",
            "omnigent-clean@10.0.0.10",
            "--evidence-output",
            str(evidence_path),
        ]
    )

    assert exit_code == 1
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert "tart counts differ: started=1 stopped=0" in evidence[
        "releaseCriteriaFailures"
    ]
    assert "tartStartedCount=1" in evidence["releaseCriteriaFailures"]


def test_release_candidate_wrapper_rejects_direct_ssh_step_tart_activity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    proof_script = _write_file(tmp_path / "scripts" / "prove.py")
    pkg_path = _write_file(tmp_path / "artifacts" / "compat.pkg")
    evidence_path = tmp_path / "artifacts" / "bad-direct-step-release-evidence.json"
    stdout = _release_ready_stdout(direct_ssh=True).replace(
        (
            '"live":{"status":"replacement-ready",'
            '"remoteStatus":"replacement-ready","hostStockCodexUploaded":false,'
            '"tartStarted":false,"tartStopped":false,'
        ),
        (
            '"live":{"status":"replacement-ready",'
            '"remoteStatus":"replacement-ready","hostStockCodexUploaded":false,'
            '"tartStarted":true,"tartStopped":false,'
        ),
    )

    def fake_run(_command: tuple[str, ...], **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(returncode=0, stdout=stdout, stderr="")

    monkeypatch.setattr(_MOD.subprocess, "run", fake_run)

    exit_code = _MOD.main(
        [
            "--proof-script",
            str(proof_script),
            "--pkg-path",
            str(pkg_path),
            "--clean-vm-ssh-target",
            "omnigent-clean@10.0.0.10",
            "--evidence-output",
            str(evidence_path),
        ]
    )

    assert exit_code == 1
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert "stepDetails[live][tartStarted]=True" in evidence[
        "releaseCriteriaFailures"
    ]


def test_release_candidate_wrapper_refuses_to_overwrite_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    proof_script = _write_file(tmp_path / "scripts" / "prove.py")
    pkg_path = _write_file(tmp_path / "artifacts" / "compat.pkg")
    evidence_path = _write_file(tmp_path / "artifacts" / "release-evidence.json", "{}")

    def fail_run(*_args: object, **_kwargs: object) -> SimpleNamespace:
        raise AssertionError("subprocess.run should not be called")

    monkeypatch.setattr(_MOD.subprocess, "run", fail_run)

    with pytest.raises(SystemExit, match="evidence output already exists"):
        _MOD.main(
            [
                "--proof-script",
                str(proof_script),
                "--pkg-path",
                str(pkg_path),
                "--clean-vm-tart-name",
                "omnigent-clean",
                "--evidence-output",
                str(evidence_path),
            ]
        )


def test_release_candidate_wrapper_force_overwrites_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    proof_script = _write_file(tmp_path / "scripts" / "prove.py")
    pkg_path = _write_file(tmp_path / "artifacts" / "compat.pkg")
    evidence_path = _write_file(tmp_path / "artifacts" / "release-evidence.json", "{}")

    def fake_run(_command: tuple[str, ...], **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            returncode=0,
            stdout=_release_ready_stdout(),
            stderr="",
        )

    monkeypatch.setattr(_MOD.subprocess, "run", fake_run)

    exit_code = _MOD.main(
        [
            "--proof-script",
            str(proof_script),
            "--pkg-path",
            str(pkg_path),
            "--clean-vm-tart-name",
            "omnigent-clean",
            "--evidence-output",
            str(evidence_path),
            "--force-evidence-output",
        ]
    )

    assert exit_code == 0
    assert json.loads(evidence_path.read_text(encoding="utf-8"))["status"] == (
        "replacement-ready"
    )


def test_release_candidate_wrapper_fails_closed_on_blocked_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    proof_script = _write_file(tmp_path / "scripts" / "prove.py")
    pkg_path = _write_file(tmp_path / "artifacts" / "compat.pkg")
    evidence_path = tmp_path / "artifacts" / "blocked-release-evidence.json"
    blocked_stdout = _release_ready_stdout().replace(
        "stock_codex_compat_pkg_clean_vm_release_status=replacement-ready",
        "stock_codex_compat_pkg_clean_vm_release_status=blocked",
    )

    def fake_run(_command: tuple[str, ...], **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(returncode=0, stdout=blocked_stdout, stderr="")

    monkeypatch.setattr(_MOD.subprocess, "run", fake_run)

    exit_code = _MOD.main(
        [
            "--proof-script",
            str(proof_script),
            "--pkg-path",
            str(pkg_path),
            "--clean-vm-tart-name",
            "omnigent-clean",
            "--evidence-output",
            str(evidence_path),
        ]
    )

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "release-candidate criteria" in captured.err
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert evidence["exitCode"] == 1
    assert evidence["underlyingExitCode"] == 0
    assert evidence["releaseCriteriaFailures"] == ["status='blocked'"]
    assert evidence["status"] == "blocked"


def test_release_candidate_wrapper_rejects_print_command_with_evidence_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    proof_script = _write_file(tmp_path / "scripts" / "prove.py")
    pkg_path = _write_file(tmp_path / "artifacts" / "compat.pkg")

    def fail_run(*_args: object, **_kwargs: object) -> SimpleNamespace:
        raise AssertionError("subprocess.run should not be called")

    monkeypatch.setattr(_MOD.subprocess, "run", fail_run)

    with pytest.raises(SystemExit, match="cannot be combined"):
        _MOD.main(
            [
                "--proof-script",
                str(proof_script),
                "--pkg-path",
                str(pkg_path),
                "--clean-vm-tart-name",
                "omnigent-clean",
                "--print-command",
                "--evidence-output",
                str(tmp_path / "release-evidence.json"),
            ]
        )
