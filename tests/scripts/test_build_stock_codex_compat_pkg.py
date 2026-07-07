"""Tests for ``scripts/build_stock_codex_compat_pkg.py``."""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "build_stock_codex_compat_pkg.py"


def _load_module() -> Any:
    spec = importlib.util.spec_from_file_location(
        "scripts_build_stock_codex_compat_pkg",
        _SCRIPT_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_MOD = _load_module()


def _require_pkg_tools() -> None:
    if shutil.which("pkgbuild") is None or shutil.which("pkgutil") is None:
        pytest.skip("macOS pkgbuild/pkgutil are required for pkg structure tests")


def _write_file(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _write_minimal_repo(repo_root: Path) -> None:
    _write_file(
        repo_root / "pyproject.toml",
        "[project]\nname = 'omnigent-test'\nversion = '1.2.3'\n",
    )
    _write_file(repo_root / "README.md", "# test\n")
    _write_file(repo_root / "LICENSE", "test\n")
    _write_file(repo_root / "omnigent" / "__init__.py", "")
    _write_file(repo_root / "omnigent" / "stock_codex_compat_wrapper.py", "")
    _write_file(
        repo_root / "scripts" / "install_stock_codex_compat_launcher.py",
        "#!/usr/bin/env python3\n",
    )
    _write_file(
        repo_root / "scripts" / "provision_stock_codex.py",
        "#!/usr/bin/env python3\n",
    )


def test_build_stock_codex_compat_pkg_contains_unsigned_runtime_contract(
    tmp_path: Path,
) -> None:
    _require_pkg_tools()
    repo_root = tmp_path / "repo"
    _write_minimal_repo(repo_root)
    output_path = tmp_path / "out" / "omnigent-stock-codex-compat.pkg"

    result = _MOD.build_stock_codex_compat_pkg(
        repo_root=repo_root,
        output_path=output_path,
    )

    required_payload = _MOD.required_payload_files_for(_MOD.DEFAULT_INSTALL_PREFIX)
    assert result.package_path == output_path.resolve()
    assert len(result.package_sha256) == 64
    assert len(result.source_bundle_sha256) == 64
    assert result.package_identifier == _MOD.DEFAULT_PACKAGE_IDENTIFIER
    assert result.package_version == "1.2.3"
    assert result.install_location == "/"
    assert result.install_prefix == _MOD.DEFAULT_INSTALL_PREFIX
    assert result.runtime_root == _MOD.DEFAULT_INSTALL_PREFIX / "runtime"
    assert result.inspection.signature_status == "no signature"
    assert result.inspection.signed is False
    assert set(result.inspection.archive_entries) >= {"Bom", "PackageInfo", "Payload", "Scripts"}
    assert "postinstall" in result.inspection.script_names
    for payload_file in required_payload:
        assert payload_file in result.inspection.payload_files
    assert result.inspection.pkg_manifest["contract"] == {
        "auth": "not-packaged",
        "package": "unsigned-flat-pkg-structure",
        "runtime": "machine-level-runtime-only",
        "stockCodex": "external-pinned-payload",
        "stockCodexProvisioning": "deferred-to-installed-runtime-command",
        "userBootstrap": "deferred-to-installed-runtime-command",
    }
    assert result.inspection.bundle_manifest["sourceRoot"] == "<omitted-from-pkg>"
    assert str(repo_root) not in json.dumps(result.inspection.pkg_manifest)
    assert str(repo_root) not in json.dumps(result.inspection.bundle_manifest)


def test_build_stock_codex_compat_pkg_cli_outputs_compact_json(
    tmp_path: Path,
    capsys: Any,
) -> None:
    _require_pkg_tools()
    repo_root = tmp_path / "repo"
    _write_minimal_repo(repo_root)
    output_path = tmp_path / "omnigent-stock-codex-compat.pkg"

    exit_code = _MOD.main(
        [
            "--repo-root",
            str(repo_root),
            "--output",
            str(output_path),
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["kind"] == _MOD.PKG_KIND
    assert payload["packagePath"] == str(output_path.resolve())
    assert payload["packageIdentifier"] == _MOD.DEFAULT_PACKAGE_IDENTIFIER
    assert payload["packageVersion"] == "1.2.3"
    assert payload["inspection"]["signed"] is False
    assert payload["inspection"]["allRequiredPayloadFilesPresent"] is True
    assert "payloadFiles" not in payload["inspection"]


def test_pkgbuild_command_includes_developer_id_signing_args(tmp_path: Path) -> None:
    output_path = tmp_path / "signed.pkg"
    keychain_path = tmp_path / "signing.keychain-db"

    command = _MOD._pkgbuild_command(
        pkgbuild="/usr/bin/pkgbuild",
        payload_root=tmp_path / "payload",
        scripts_root=tmp_path / "scripts",
        package_identifier="ai.omnigent.stock-codex-compat",
        package_version="1.2.3",
        output_path=output_path,
        sign_identity="Developer ID Installer: Example, Inc. (ABCDE12345)",
        signing_keychain=keychain_path,
    )

    assert command[-1] == str(output_path)
    assert command[command.index("--sign") + 1] == (
        "Developer ID Installer: Example, Inc. (ABCDE12345)"
    )
    assert command[command.index("--keychain") + 1] == str(keychain_path)
    assert "--timestamp" in command
