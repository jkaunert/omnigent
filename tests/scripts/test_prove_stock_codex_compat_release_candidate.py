"""Tests for ``scripts/prove_stock_codex_compat_release_candidate.py``."""

from __future__ import annotations

import importlib.util
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
