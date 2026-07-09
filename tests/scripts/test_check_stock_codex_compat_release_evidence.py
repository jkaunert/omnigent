"""Tests for ``scripts/check_stock_codex_compat_release_evidence.py``."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "check_stock_codex_compat_release_evidence.py"


def _load_module() -> Any:
    spec = importlib.util.spec_from_file_location(
        "scripts_check_stock_codex_compat_release_evidence",
        _SCRIPT_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_MOD = _load_module()


def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    return path


def _write_package(path: Path, payload: bytes = b"release package") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _ready_evidence(package_sha256: str) -> dict[str, Any]:
    return {
        "kind": _MOD.EVIDENCE_KIND,
        "schemaVersion": _MOD.EVIDENCE_SCHEMA_VERSION,
        "proof": _MOD.PROOF_NAME,
        "createdAt": "2026-07-08T23:00:00+00:00",
        "command": ["python", "scripts/prove_stock_codex_replacement.py"],
        "exitCode": 0,
        "underlyingExitCode": 0,
        "releaseCriteriaFailures": [],
        "status": "replacement-ready",
        "missingPrerequisites": [],
        "packagePath": "/tmp/compat.pkg",
        "packageSha256": package_sha256,
        "stockCodexPath": "/tmp/codex",
        "stockCodexVersion": "codex-cli 0.143.0",
        "stockCodexSha256": "stock-sha",
        "caskVersion": "0.143.0",
        "caskUrl": "https://github.com/openai/codex/releases/download/rust-v0.143.0/codex-aarch64-apple-darwin.tar.gz",
        "caskSha256": "cask-sha",
        "channelPolicy": _MOD.OFFICIAL_CHANNEL_POLICY,
        "tartName": "omnigent-clean",
        "sshTarget": None,
        "authPath": "/tmp/auth.json",
        "authSource": "stock-default-home",
        "authAvailable": True,
        "stepOrder": list(_MOD.EXPECTED_RELEASE_STEPS),
        "stepStatuses": dict.fromkeys(_MOD.EXPECTED_RELEASE_STEPS, "replacement-ready"),
        "stepMissingPrerequisites": {},
        "blockedStep": None,
        "tartStartedCount": len(_MOD.EXPECTED_RELEASE_STEPS),
        "tartStoppedCount": len(_MOD.EXPECTED_RELEASE_STEPS),
        "hostStockCodexUploadedAny": False,
        "stepDetails": {
            "remote-acquisition": {
                "status": "replacement-ready",
                "remoteStatus": "replacement-ready",
                "hostStockCodexUploaded": False,
                "tartStarted": True,
                "tartStopped": True,
                "threadId": None,
                "scheduledAction": None,
            },
            "auth-onboarding": {
                "status": "replacement-ready",
                "remoteStatus": "replacement-ready",
                "hostStockCodexUploaded": False,
                "tartStarted": True,
                "tartStopped": True,
                "threadId": None,
                "scheduledAction": None,
            },
            "auth-persistence": {
                "status": "replacement-ready",
                "remoteStatus": "replacement-ready",
                "hostStockCodexUploaded": False,
                "tartStarted": True,
                "tartStopped": True,
                "threadId": "thread-auth",
                "scheduledAction": None,
            },
            "update-agent": {
                "status": "replacement-ready",
                "remoteStatus": "replacement-ready",
                "hostStockCodexUploaded": False,
                "tartStarted": True,
                "tartStopped": True,
                "threadId": None,
                "scheduledAction": "up-to-date",
            },
            "live": {
                "status": "replacement-ready",
                "remoteStatus": "replacement-ready",
                "hostStockCodexUploaded": False,
                "tartStarted": True,
                "tartStopped": True,
                "threadId": "thread-live",
                "scheduledAction": None,
            },
        },
        "fields": {"status": "replacement-ready"},
    }


def _direct_ready_evidence(package_sha256: str) -> dict[str, Any]:
    evidence = _ready_evidence(package_sha256)
    evidence["targetMode"] = "direct-ssh"
    evidence["tartName"] = None
    evidence["sshTarget"] = "omnigent-clean@10.0.0.10"
    evidence["tartStartedCount"] = 0
    evidence["tartStoppedCount"] = 0
    for detail in evidence["stepDetails"].values():
        detail["tartStarted"] = False
        detail["tartStopped"] = False
    return evidence


def test_release_evidence_checker_accepts_ready_artifact(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pkg_path = _write_package(tmp_path / "compat.pkg")
    evidence_path = _write_json(
        tmp_path / "release-evidence.json",
        _ready_evidence(_sha256(pkg_path)),
    )

    exit_code = _MOD.main(
        [
            "--pkg-path",
            str(pkg_path),
            "--evidence-output",
            str(evidence_path),
        ]
    )

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "release_evidence_status=replacement-ready" in output
    assert f"release_evidence_package_sha256={_sha256(pkg_path)}" in output
    assert "release_evidence_channel_policy=official-openai-github-release" in output


def test_release_evidence_checker_accepts_direct_ssh_ready_artifact(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pkg_path = _write_package(tmp_path / "compat.pkg")
    evidence_path = _write_json(
        tmp_path / "direct-release-evidence.json",
        _direct_ready_evidence(_sha256(pkg_path)),
    )

    exit_code = _MOD.main(
        [
            "--pkg-path",
            str(pkg_path),
            "--evidence-output",
            str(evidence_path),
        ]
    )

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "release_evidence_status=replacement-ready" in output
    assert "release_evidence_target_mode=direct-ssh" in output


def test_release_evidence_checker_uses_environment_defaults(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pkg_path = _write_package(tmp_path / "compat.pkg")
    evidence_path = _write_json(
        tmp_path / "release-evidence.json",
        _ready_evidence(_sha256(pkg_path)),
    )
    monkeypatch.setenv(_MOD.ENV_PKG_PATH, str(pkg_path))
    monkeypatch.setenv(_MOD.ENV_EVIDENCE_OUTPUT, str(evidence_path))

    assert _MOD.main([]) == 0


def test_release_evidence_checker_rejects_package_sha_mismatch(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pkg_path = _write_package(tmp_path / "compat.pkg")
    evidence_path = _write_json(
        tmp_path / "release-evidence.json",
        _ready_evidence("wrong-sha"),
    )

    exit_code = _MOD.main(
        [
            "--pkg-path",
            str(pkg_path),
            "--evidence-output",
            str(evidence_path),
        ]
    )

    assert exit_code == 1
    assert "does not match" in capsys.readouterr().err


def test_release_evidence_checker_rejects_missing_schema_field(tmp_path: Path) -> None:
    pkg_path = _write_package(tmp_path / "compat.pkg")
    evidence = _ready_evidence(_sha256(pkg_path))
    evidence.pop("releaseCriteriaFailures")

    failures = _MOD.validate_release_evidence(
        evidence,
        pkg_path=pkg_path,
        package_sha256=_sha256(pkg_path),
    )

    assert "releaseCriteriaFailures is missing" in failures


def test_release_evidence_checker_rejects_non_official_channel(tmp_path: Path) -> None:
    pkg_path = _write_package(tmp_path / "compat.pkg")
    evidence = _ready_evidence(_sha256(pkg_path))
    evidence["channelPolicy"] = "local-file"
    evidence["caskUrl"] = "https://example.test/codex.tgz"

    failures = _MOD.validate_release_evidence(
        evidence,
        pkg_path=pkg_path,
        package_sha256=_sha256(pkg_path),
    )

    assert "channelPolicy='local-file'" in failures
    assert "caskUrl='https://example.test/codex.tgz'" in failures


def test_release_evidence_checker_rejects_failed_step(tmp_path: Path) -> None:
    pkg_path = _write_package(tmp_path / "compat.pkg")
    evidence = _ready_evidence(_sha256(pkg_path))
    evidence["stepStatuses"]["live"] = "blocked"
    evidence["stepDetails"]["live"]["remoteStatus"] = "blocked"

    failures = _MOD.validate_release_evidence(
        evidence,
        pkg_path=pkg_path,
        package_sha256=_sha256(pkg_path),
    )

    assert "stepStatuses[live]='blocked'" in failures
    assert "stepDetails[live][remoteStatus]='blocked'" in failures


def test_release_evidence_checker_rejects_tart_mismatch(tmp_path: Path) -> None:
    pkg_path = _write_package(tmp_path / "compat.pkg")
    evidence = _ready_evidence(_sha256(pkg_path))
    evidence["tartStoppedCount"] = 4

    failures = _MOD.validate_release_evidence(
        evidence,
        pkg_path=pkg_path,
        package_sha256=_sha256(pkg_path),
    )

    assert "tart counts differ: started=5 stopped=4" in failures


def test_release_evidence_checker_rejects_direct_ssh_tart_activity(
    tmp_path: Path,
) -> None:
    pkg_path = _write_package(tmp_path / "compat.pkg")
    evidence = _direct_ready_evidence(_sha256(pkg_path))
    evidence["tartStartedCount"] = 1
    evidence["stepDetails"]["live"]["tartStarted"] = True

    failures = _MOD.validate_release_evidence(
        evidence,
        pkg_path=pkg_path,
        package_sha256=_sha256(pkg_path),
    )

    assert "tart counts differ: started=1 stopped=0" in failures
    assert "tartStartedCount=1" in failures
    assert "stepDetails[live][tartStarted]=True" in failures


def test_release_evidence_checker_rejects_host_stock_upload(tmp_path: Path) -> None:
    pkg_path = _write_package(tmp_path / "compat.pkg")
    evidence = _ready_evidence(_sha256(pkg_path))
    evidence["hostStockCodexUploadedAny"] = True
    evidence["stepDetails"]["live"]["hostStockCodexUploaded"] = True

    failures = _MOD.validate_release_evidence(
        evidence,
        pkg_path=pkg_path,
        package_sha256=_sha256(pkg_path),
    )

    assert "hostStockCodexUploadedAny=True" in failures
    assert "stepDetails[live][hostStockCodexUploaded]=True" in failures


def test_release_evidence_checker_rejects_invalid_json(tmp_path: Path) -> None:
    evidence_path = tmp_path / "release-evidence.json"
    evidence_path.write_text("{", encoding="utf-8")

    with pytest.raises(SystemExit, match="not valid JSON"):
        _MOD.load_evidence(evidence_path)
