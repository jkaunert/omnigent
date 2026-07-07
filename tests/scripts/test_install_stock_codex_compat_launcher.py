"""Tests for ``scripts/install_stock_codex_compat_launcher.py``."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from omnigent.adapters.apple_docs_cli import (
    build_fetch_apple_docs_stock_codex_bridge_adapter_spec,
)
from omnigent.adapters.stock_codex_compat import (
    write_stock_codex_compat_adapter_package,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "install_stock_codex_compat_launcher.py"


def _load_module() -> Any:
    spec = importlib.util.spec_from_file_location(
        "scripts_install_stock_codex_compat_launcher",
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
  cat <<'EOF'
{version}
EOF
  exit 0
fi
printf 'fake stock codex\\n'
""",
    )


def _write_uvx(path: Path) -> Path:
    return _write_executable(
        path,
        """#!/bin/sh
printf 'fake_uvx_args='
for arg in "$@"; do
  printf '<%s>' "$arg"
done
printf '\\n'
""",
    )


def _write_adapter_package(tmp_path: Path) -> Any:
    return write_stock_codex_compat_adapter_package(
        tmp_path / "adapter-package",
        (build_fetch_apple_docs_stock_codex_bridge_adapter_spec(),),
    )


def test_install_adapter_package_writes_and_reuses_default_package(
    tmp_path: Path,
) -> None:
    package_dir = tmp_path / "stock-codex-compat" / "adapter-package"

    installed = _MOD.materialize_default_adapter_package(package_dir, force=False)
    reused = _MOD.materialize_default_adapter_package(package_dir, force=False)

    assert installed.action == "adapter-package-installed"
    assert installed.mutates_filesystem is True
    assert installed.adapter_package_dir == package_dir
    assert installed.adapter_bin == (package_dir / "bin").resolve()
    assert installed.adapter_manifest == (package_dir / "adapter-manifest.json").resolve()
    assert installed.adapter_tool_names == ("fetch_apple_docs",)
    assert (package_dir / "bin" / "fetch_apple_docs").is_file()
    assert (package_dir / "adapter-manifest.json").is_file()
    assert reused.action == "adapter-package-reused"
    assert reused.mutates_filesystem is False
    assert reused.adapter_bin == installed.adapter_bin
    assert reused.adapter_manifest == installed.adapter_manifest
    assert reused.adapter_tool_names == installed.adapter_tool_names


def test_install_adapter_package_cli_outputs_json(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    package_dir = tmp_path / "stock-codex-compat" / "adapter-package"

    exit_code = _MOD.main(
        [
            "--install-adapter-package",
            "--json",
            "--adapter-package-dir",
            str(package_dir),
        ]
    )
    output = capsys.readouterr().out
    payload = json.loads(output)

    assert exit_code == 0
    assert payload["action"] == "adapter-package-installed"
    assert payload["adapterPackageDir"] == str(package_dir)
    assert payload["adapterBin"] == str((package_dir / "bin").resolve())
    assert payload["adapterManifest"] == str(
        (package_dir / "adapter-manifest.json").resolve()
    )
    assert payload["adapterToolNames"] == ["fetch_apple_docs"]
    assert payload["mutatesFilesystem"] is True


def test_install_launcher_writes_managed_compat_shim_and_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    launcher_path = tmp_path / "bin" / "codex"
    manifest_path = tmp_path / "manifest.json"
    pinned_codex_path = _write_codex(tmp_path / "stock" / "codex")
    uvx_path = _write_uvx(tmp_path / "tools" / "uvx")
    adapter_package = _write_adapter_package(tmp_path)
    adapter_bridge_dir = tmp_path / "adapter-bridge"
    monkeypatch.setenv("PATH", f"{launcher_path.parent}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.delenv(_MOD.OMNIGENT_STOCK_CODEX_PATH_ENV, raising=False)

    result = _MOD.install_launcher(
        launcher_path=launcher_path,
        manifest_path=manifest_path,
        repo_root=_REPO_ROOT,
        uvx_path=uvx_path,
        pinned_codex_path=pinned_codex_path,
        route_prefix="ROUTE",
        adapter_bin=adapter_package.adapter_bin,
        adapter_manifest=adapter_package.manifest_path,
        adapter_bridge_dir=adapter_bridge_dir,
        backup_existing=False,
        force=False,
        require_path_selected=True,
        validate=True,
    )

    assert result.action == "installed"
    assert result.rollback_command is not None
    assert _MOD.is_managed_launcher(launcher_path)
    assert Path(_MOD._find_codex_cli()).resolve() == pinned_codex_path.resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["kind"] == _MOD.MANIFEST_KIND
    assert manifest["wrapperEntrypoint"] == _MOD.WRAPPER_ENTRYPOINT
    assert manifest["pinnedCodexPath"] == str(pinned_codex_path.resolve())
    assert manifest["routePrefix"] == "ROUTE"
    assert manifest["adapterBin"] == str(adapter_package.adapter_bin.resolve())
    assert manifest["adapterManifest"] == str(adapter_package.manifest_path.resolve())
    assert manifest["adapterBridgeDir"] == str(adapter_bridge_dir.resolve())
    assert manifest["adapterToolNames"] == ["fetch_apple_docs"]

    version = subprocess.run(
        [str(launcher_path), "--version"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert version.stdout.strip() == "codex-cli 0.142.2"
    probe = subprocess.run(
        [str(launcher_path), _MOD.PROBE_ARG],
        check=True,
        capture_output=True,
        text=True,
    )
    assert _MOD.PROBE_SENTINEL in probe.stdout
    assert f"delegate={uvx_path.resolve()} --from {_REPO_ROOT} {_MOD.WRAPPER_ENTRYPOINT}" in (
        probe.stdout
    )

    launched = subprocess.run(
        [str(launcher_path), "exec", "--json", "prompt"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert f"<--from><{_REPO_ROOT}><{_MOD.WRAPPER_ENTRYPOINT}>" in launched.stdout
    assert f"<--stock-codex-path><{pinned_codex_path.resolve()}>" in launched.stdout
    assert f"<--adapter-bin><{adapter_package.adapter_bin.resolve()}>" in launched.stdout
    assert f"<--adapter-manifest><{adapter_package.manifest_path.resolve()}>" in launched.stdout
    assert f"<--adapter-bridge-dir><{adapter_bridge_dir.resolve()}>" in launched.stdout
    assert "<--><exec><--json><prompt>" in launched.stdout


def test_install_launcher_refuses_unmanaged_existing_target(tmp_path: Path) -> None:
    launcher_path = _write_executable(tmp_path / "bin" / "codex", "#!/bin/sh\nexit 0\n")
    pinned_codex_path = _write_codex(tmp_path / "stock" / "codex")
    uvx_path = _write_uvx(tmp_path / "tools" / "uvx")
    adapter_package = _write_adapter_package(tmp_path)

    with pytest.raises(_MOD.CompatLauncherInstallError, match="not managed"):
        _MOD.install_launcher(
            launcher_path=launcher_path,
            manifest_path=tmp_path / "manifest.json",
            repo_root=_REPO_ROOT,
            uvx_path=uvx_path,
            pinned_codex_path=pinned_codex_path,
            route_prefix="ROUTE",
            adapter_bin=adapter_package.adapter_bin,
            adapter_manifest=adapter_package.manifest_path,
            adapter_bridge_dir=tmp_path / "adapter-bridge",
            backup_existing=False,
            force=False,
            require_path_selected=False,
            validate=False,
        )


def test_doctor_validates_absent_target_without_mutating(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    launcher_path = tmp_path / "bin" / "codex"
    manifest_path = tmp_path / "manifest.json"
    launcher_path.parent.mkdir()
    pinned_codex_path = _write_codex(tmp_path / "stock" / "codex")
    uvx_path = _write_uvx(tmp_path / "tools" / "uvx")
    adapter_package = _write_adapter_package(tmp_path)
    adapter_bridge_dir = tmp_path / "adapter-bridge"
    monkeypatch.setenv("PATH", f"{launcher_path.parent}{os.pathsep}{os.environ['PATH']}")

    result = _MOD.doctor_launcher(
        launcher_path=launcher_path,
        manifest_path=manifest_path,
        repo_root=_REPO_ROOT,
        uvx_path=uvx_path,
        pinned_codex_path=pinned_codex_path,
        route_prefix="ROUTE",
        adapter_bin=adapter_package.adapter_bin,
        adapter_manifest=adapter_package.manifest_path,
        adapter_bridge_dir=adapter_bridge_dir,
        backup_existing=False,
        force=False,
        require_path_selected=False,
    )

    assert result.action == "doctor"
    assert result.install_allowed is True
    assert result.install_blocker is None
    assert result.existing_target_state == "absent"
    assert result.launcher_parent_on_path is True
    assert result.target_selected_on_path is False
    assert result.mutates_filesystem is False
    assert result.pinned_codex_version == "codex-cli 0.142.2"
    assert result.adapter_tool_names == ("fetch_apple_docs",)
    assert "install_stock_codex_compat_launcher.py" in result.install_command
    assert "--install" in result.install_command
    assert "--uninstall" in result.rollback_command
    assert not launcher_path.exists()
    assert not manifest_path.exists()


def test_doctor_reports_unmanaged_target_requires_backup(tmp_path: Path) -> None:
    launcher_path = _write_executable(tmp_path / "bin" / "codex", "#!/bin/sh\nexit 0\n")
    pinned_codex_path = _write_codex(tmp_path / "stock" / "codex")
    uvx_path = _write_uvx(tmp_path / "tools" / "uvx")
    adapter_package = _write_adapter_package(tmp_path)

    blocked = _MOD.doctor_launcher(
        launcher_path=launcher_path,
        manifest_path=tmp_path / "manifest.json",
        repo_root=_REPO_ROOT,
        uvx_path=uvx_path,
        pinned_codex_path=pinned_codex_path,
        route_prefix="ROUTE",
        adapter_bin=adapter_package.adapter_bin,
        adapter_manifest=adapter_package.manifest_path,
        adapter_bridge_dir=tmp_path / "adapter-bridge",
        backup_existing=False,
        force=False,
        require_path_selected=False,
    )
    allowed = _MOD.doctor_launcher(
        launcher_path=launcher_path,
        manifest_path=tmp_path / "manifest.json",
        repo_root=_REPO_ROOT,
        uvx_path=uvx_path,
        pinned_codex_path=pinned_codex_path,
        route_prefix="ROUTE",
        adapter_bin=adapter_package.adapter_bin,
        adapter_manifest=adapter_package.manifest_path,
        adapter_bridge_dir=tmp_path / "adapter-bridge",
        backup_existing=True,
        force=False,
        require_path_selected=False,
    )

    assert blocked.install_allowed is False
    assert blocked.install_blocker == "requires-backup-existing-for-unmanaged-target"
    assert blocked.existing_target_state == "unmanaged"
    assert blocked.would_backup_existing is False
    assert allowed.install_allowed is True
    assert allowed.install_blocker is None
    assert allowed.would_backup_existing is True
    assert allowed.backup_path is not None
    assert allowed.backup_path.name.startswith("codex.omnigent-backup-")
    assert launcher_path.exists()


def test_doctor_cli_outputs_json_without_mutating(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    launcher_path = tmp_path / "bin" / "omnigent-stock-codex-compat"
    manifest_path = tmp_path / "manifest.json"
    pinned_codex_path = _write_codex(tmp_path / "stock" / "codex")
    uvx_path = _write_uvx(tmp_path / "tools" / "uvx")
    adapter_package = _write_adapter_package(tmp_path)

    exit_code = _MOD.main(
        [
            "--doctor",
            "--json",
            "--launcher-path",
            str(launcher_path),
            "--manifest-path",
            str(manifest_path),
            "--repo-root",
            str(_REPO_ROOT),
            "--uvx-path",
            str(uvx_path),
            "--pinned-codex-path",
            str(pinned_codex_path),
            "--route-prefix",
            "ROUTE",
            "--adapter-bin",
            str(adapter_package.adapter_bin),
            "--adapter-manifest",
            str(adapter_package.manifest_path),
            "--adapter-bridge-dir",
            str(tmp_path / "adapter-bridge"),
        ]
    )
    output = capsys.readouterr().out
    payload = json.loads(output)

    assert exit_code == 0
    assert payload["action"] == "doctor"
    assert payload["installAllowed"] is True
    assert payload["mutatesFilesystem"] is False
    assert payload["launcherPath"] == str(launcher_path)
    assert payload["adapterToolNames"] == ["fetch_apple_docs"]
    assert not launcher_path.exists()
    assert not manifest_path.exists()


def test_doctor_cli_uses_default_adapter_package_when_paths_omitted(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    launcher_path = tmp_path / "bin" / "omnigent-stock-codex-compat"
    manifest_path = tmp_path / "manifest.json"
    pinned_codex_path = _write_codex(tmp_path / "stock" / "codex")
    uvx_path = _write_uvx(tmp_path / "tools" / "uvx")
    package_dir = tmp_path / "stock-codex-compat" / "adapter-package"
    adapter_package = _MOD.materialize_default_adapter_package(
        package_dir,
        force=False,
    )

    exit_code = _MOD.main(
        [
            "--doctor",
            "--json",
            "--launcher-path",
            str(launcher_path),
            "--manifest-path",
            str(manifest_path),
            "--repo-root",
            str(_REPO_ROOT),
            "--uvx-path",
            str(uvx_path),
            "--pinned-codex-path",
            str(pinned_codex_path),
            "--route-prefix",
            "ROUTE",
            "--adapter-package-dir",
            str(package_dir),
            "--adapter-bridge-dir",
            str(tmp_path / "adapter-bridge"),
        ]
    )
    output = capsys.readouterr().out
    payload = json.loads(output)

    assert exit_code == 0
    assert payload["action"] == "doctor"
    assert payload["installAllowed"] is True
    assert payload["mutatesFilesystem"] is False
    assert payload["adapterBin"] == str(adapter_package.adapter_bin)
    assert payload["adapterManifest"] == str(adapter_package.adapter_manifest)
    assert payload["adapterToolNames"] == ["fetch_apple_docs"]
    assert not launcher_path.exists()
    assert not manifest_path.exists()


def test_install_launcher_backs_up_and_uninstall_restores_existing_target(
    tmp_path: Path,
) -> None:
    launcher_path = _write_executable(tmp_path / "bin" / "codex", "#!/bin/sh\necho old\n")
    pinned_codex_path = _write_codex(tmp_path / "stock" / "codex")
    uvx_path = _write_uvx(tmp_path / "tools" / "uvx")
    adapter_package = _write_adapter_package(tmp_path)
    manifest_path = tmp_path / "manifest.json"

    installed = _MOD.install_launcher(
        launcher_path=launcher_path,
        manifest_path=manifest_path,
        repo_root=_REPO_ROOT,
        uvx_path=uvx_path,
        pinned_codex_path=pinned_codex_path,
        route_prefix="ROUTE",
        adapter_bin=adapter_package.adapter_bin,
        adapter_manifest=adapter_package.manifest_path,
        adapter_bridge_dir=tmp_path / "adapter-bridge",
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

    with pytest.raises(_MOD.CompatLauncherInstallError, match="unmanaged"):
        _MOD.uninstall_launcher(
            launcher_path=launcher_path,
            manifest_path=tmp_path / "manifest.json",
        )
