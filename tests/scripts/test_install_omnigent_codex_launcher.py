"""Tests for ``scripts/install_omnigent_codex_launcher.py``."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "install_omnigent_codex_launcher.py"


def _load_module() -> Any:
    spec = importlib.util.spec_from_file_location(
        "scripts_install_omnigent_codex_launcher",
        _SCRIPT_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_MOD = _load_module()


def _write_executable(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)
    return path


def _write_codex(path: Path, *, version: str = "codex-cli 0.142.2") -> Path:
    return _write_executable(
        path,
        f"""#!/bin/sh
if [ "${{1:-}}" = "--version" ]; then
  printf '%s\\n' {version!r}
  exit 0
fi
printf 'fake stock codex\\n'
""",
    )


def test_install_launcher_writes_managed_shim_and_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    launcher_path = tmp_path / "bin" / "codex"
    manifest_path = tmp_path / "manifest.json"
    pinned_codex_path = _write_codex(tmp_path / "stock" / "codex")
    uvx_path = _write_executable(tmp_path / "bin" / "uvx", "#!/bin/sh\nexit 0\n")
    monkeypatch.setenv("PATH", f"{launcher_path.parent}{os.pathsep}{os.environ['PATH']}")

    result = _MOD.install_launcher(
        launcher_path=launcher_path,
        manifest_path=manifest_path,
        repo_root=_REPO_ROOT,
        uvx_path=uvx_path,
        pinned_codex_path=pinned_codex_path,
        backup_existing=False,
        force=False,
        require_path_selected=True,
        validate=True,
    )

    assert result.action == "installed"
    assert _MOD.is_managed_launcher(launcher_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["kind"] == _MOD.MANIFEST_KIND
    assert manifest["pinnedCodexPath"] == str(pinned_codex_path.resolve())
    assert (
        subprocess.run(
            [str(launcher_path), "--version"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        == "codex-cli 0.142.2"
    )
    assert (
        _MOD.PROBE_SENTINEL
        in subprocess.run(
            [str(launcher_path), _MOD.PROBE_ARG],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    )


def test_install_launcher_refuses_unmanaged_existing_target(tmp_path: Path) -> None:
    launcher_path = _write_executable(tmp_path / "bin" / "codex", "#!/bin/sh\nexit 0\n")
    pinned_codex_path = _write_codex(tmp_path / "stock" / "codex")
    uvx_path = _write_executable(tmp_path / "bin" / "uvx", "#!/bin/sh\nexit 0\n")

    with pytest.raises(_MOD.LauncherInstallError, match="not managed"):
        _MOD.install_launcher(
            launcher_path=launcher_path,
            manifest_path=tmp_path / "manifest.json",
            repo_root=_REPO_ROOT,
            uvx_path=uvx_path,
            pinned_codex_path=pinned_codex_path,
            backup_existing=False,
            force=False,
            require_path_selected=False,
            validate=False,
        )


def test_install_launcher_backs_up_and_uninstall_restores_existing_target(tmp_path: Path) -> None:
    launcher_path = _write_executable(tmp_path / "bin" / "codex", "#!/bin/sh\necho old\n")
    pinned_codex_path = _write_codex(tmp_path / "stock" / "codex")
    uvx_path = _write_executable(tmp_path / "bin" / "uvx", "#!/bin/sh\nexit 0\n")
    manifest_path = tmp_path / "manifest.json"

    installed = _MOD.install_launcher(
        launcher_path=launcher_path,
        manifest_path=manifest_path,
        repo_root=_REPO_ROOT,
        uvx_path=uvx_path,
        pinned_codex_path=pinned_codex_path,
        backup_existing=True,
        force=False,
        require_path_selected=False,
        validate=True,
    )

    assert installed.backup_path is not None
    assert installed.backup_path.exists()
    assert _MOD.is_managed_launcher(launcher_path)

    removed = _MOD.uninstall_launcher(
        launcher_path=launcher_path,
        manifest_path=manifest_path,
    )

    assert removed.action == "uninstalled"
    assert launcher_path.read_text(encoding="utf-8") == "#!/bin/sh\necho old\n"
    assert not manifest_path.exists()
    assert installed.backup_path is not None
    assert not installed.backup_path.exists()


def test_uninstall_refuses_unmanaged_target(tmp_path: Path) -> None:
    launcher_path = _write_executable(tmp_path / "bin" / "codex", "#!/bin/sh\nexit 0\n")

    with pytest.raises(_MOD.LauncherInstallError, match="unmanaged"):
        _MOD.uninstall_launcher(
            launcher_path=launcher_path,
            manifest_path=tmp_path / "manifest.json",
        )
