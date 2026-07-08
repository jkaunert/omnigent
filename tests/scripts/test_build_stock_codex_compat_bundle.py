"""Tests for ``scripts/build_stock_codex_compat_bundle.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
import tarfile
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "build_stock_codex_compat_bundle.py"


def _load_module() -> Any:
    spec = importlib.util.spec_from_file_location(
        "scripts_build_stock_codex_compat_bundle",
        _SCRIPT_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_MOD = _load_module()


def _write_file(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_build_stock_codex_compat_bundle_contains_runtime_contract(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    _write_file(repo_root / "pyproject.toml", "[project]\nname = 'omnigent-test'\n")
    _write_file(repo_root / "uv.lock", "")
    _write_file(repo_root / "README.md", "# test\n")
    _write_file(repo_root / "LICENSE", "test\n")
    _write_file(repo_root / "omnigent" / "__init__.py", "")
    _write_file(repo_root / "omnigent" / "stock_codex_compat_wrapper.py", "")
    _write_file(repo_root / "omnigent" / "__pycache__" / "skip.pyc", "skip")
    _write_file(repo_root / "sdks" / "python-client" / "pyproject.toml", "")
    _write_file(repo_root / "sdks" / "ui" / "pyproject.toml", "")
    _write_file(
        repo_root / "scripts" / "install_stock_codex_compat_launcher.py",
        "#!/usr/bin/env python3\n",
    )
    _write_file(
        repo_root / "scripts" / "provision_stock_codex.py",
        "#!/usr/bin/env python3\n",
    )
    _write_file(
        repo_root / "scripts" / "update_stock_codex_compat.py",
        "#!/usr/bin/env python3\n",
    )
    _write_file(
        repo_root / "scripts" / "bootstrap_stock_codex_compat.sh",
        "#!/bin/bash\n",
    )
    _write_file(
        repo_root / "scripts" / "bootstrap_stock_codex_compat.py",
        "#!/usr/bin/env python3\n",
    )
    output_path = tmp_path / "out" / "bundle.tar.gz"

    result = _MOD.build_stock_codex_compat_bundle(
        repo_root=repo_root,
        output_path=output_path,
    )

    assert result.bundle_path == output_path.resolve()
    assert len(result.sha256) == 64
    assert result.included_file_count == 13
    with tarfile.open(output_path, "r:gz") as archive:
        names = set(archive.getnames())
        manifest_member = (
            "omnigent-stock-codex-compat-bundle/bundle-manifest.json"
        )
        assert manifest_member in names
        assert (
            "omnigent-stock-codex-compat-bundle/runtime/pyproject.toml"
            in names
        )
        assert (
            "omnigent-stock-codex-compat-bundle/runtime/"
            "scripts/install_stock_codex_compat_launcher.py"
            in names
        )
        assert (
            "omnigent-stock-codex-compat-bundle/runtime/"
            "scripts/provision_stock_codex.py"
            in names
        )
        assert (
            "omnigent-stock-codex-compat-bundle/runtime/"
            "scripts/update_stock_codex_compat.py"
            in names
        )
        assert (
            "omnigent-stock-codex-compat-bundle/runtime/"
            "scripts/bootstrap_stock_codex_compat.sh"
            in names
        )
        assert (
            "omnigent-stock-codex-compat-bundle/runtime/"
            "scripts/bootstrap_stock_codex_compat.py"
            in names
        )
        assert (
            "omnigent-stock-codex-compat-bundle/runtime/"
            "omnigent/stock_codex_compat_wrapper.py"
            in names
        )
        assert (
            "omnigent-stock-codex-compat-bundle/runtime/"
            "sdks/python-client/pyproject.toml"
            in names
        )
        assert not any("__pycache__" in name for name in names)
        manifest_file = archive.extractfile(manifest_member)
        assert manifest_file is not None
        manifest = json.loads(manifest_file.read().decode("utf-8"))

    assert manifest["kind"] == _MOD.BUNDLE_KIND
    assert manifest["schemaVersion"] == _MOD.BUNDLE_SCHEMA_VERSION
    assert manifest["runtimeRoot"] == "runtime"
    assert manifest["installer"] == (
        "runtime/scripts/install_stock_codex_compat_launcher.py"
    )
    assert manifest["stockCodexProvisioner"] == "runtime/scripts/provision_stock_codex.py"
    assert manifest["stockCodexUpdater"] == "runtime/scripts/update_stock_codex_compat.py"
    assert manifest["userBootstrapper"] == (
        "runtime/scripts/bootstrap_stock_codex_compat.sh"
    )
    assert manifest["userBootstrapperPython"] == (
        "runtime/scripts/bootstrap_stock_codex_compat.py"
    )
    assert manifest["includedFileCount"] == result.included_file_count


def test_build_stock_codex_compat_bundle_cli_outputs_json(
    tmp_path: Path,
    capsys: Any,
) -> None:
    repo_root = tmp_path / "repo"
    _write_file(repo_root / "pyproject.toml", "[project]\nname = 'omnigent-test'\n")
    _write_file(repo_root / "omnigent" / "__init__.py", "")
    _write_file(
        repo_root / "scripts" / "install_stock_codex_compat_launcher.py",
        "#!/usr/bin/env python3\n",
    )
    _write_file(
        repo_root / "scripts" / "provision_stock_codex.py",
        "#!/usr/bin/env python3\n",
    )
    _write_file(
        repo_root / "scripts" / "update_stock_codex_compat.py",
        "#!/usr/bin/env python3\n",
    )
    _write_file(
        repo_root / "scripts" / "bootstrap_stock_codex_compat.sh",
        "#!/bin/bash\n",
    )
    _write_file(
        repo_root / "scripts" / "bootstrap_stock_codex_compat.py",
        "#!/usr/bin/env python3\n",
    )
    output_path = tmp_path / "bundle.tar.gz"

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
    assert payload["kind"] == _MOD.BUNDLE_KIND
    assert payload["bundlePath"] == str(output_path.resolve())
    assert payload["runtimeRoot"] == "runtime"
    assert output_path.is_file()
