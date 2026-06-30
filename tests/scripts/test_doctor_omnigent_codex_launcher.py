"""Tests for ``scripts/doctor_omnigent_codex_launcher.py``."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DOCTOR_SCRIPT_PATH = _REPO_ROOT / "scripts" / "doctor_omnigent_codex_launcher.py"
_INSTALL_SCRIPT_PATH = _REPO_ROOT / "scripts" / "install_omnigent_codex_launcher.py"


def _load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_INSTALLER = _load_module(
    "scripts_install_omnigent_codex_launcher_for_doctor_tests",
    _INSTALL_SCRIPT_PATH,
)
_DOCTOR = _load_module(
    "scripts_doctor_omnigent_codex_launcher",
    _DOCTOR_SCRIPT_PATH,
)


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


def _install_managed_launcher(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    backup_existing: bool = False,
    require_path_selected: bool = True,
) -> tuple[Path, Path, Path]:
    launcher_path = tmp_path / "bin" / "codex"
    manifest_path = tmp_path / "manifest.json"
    pinned_codex_path = _write_codex(tmp_path / "stock" / "codex")
    uvx_path = _write_executable(tmp_path / "bin" / "uvx", "#!/bin/sh\nexit 0\n")
    if backup_existing:
        _write_executable(launcher_path, "#!/bin/sh\necho old\n")
    monkeypatch.setenv("PATH", f"{launcher_path.parent}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.delenv("OMNIGENT_STOCK_CODEX_PATH", raising=False)

    _INSTALLER.install_launcher(
        launcher_path=launcher_path,
        manifest_path=manifest_path,
        repo_root=_REPO_ROOT,
        uvx_path=uvx_path,
        pinned_codex_path=pinned_codex_path,
        backup_existing=backup_existing,
        force=False,
        require_path_selected=require_path_selected,
        validate=True,
    )
    return launcher_path, manifest_path, pinned_codex_path.resolve()


def test_doctor_passes_for_managed_launcher(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    launcher_path, manifest_path, pinned_codex_path = _install_managed_launcher(
        tmp_path,
        monkeypatch,
    )

    result = _DOCTOR.run_doctor(
        launcher_path=launcher_path,
        manifest_path=manifest_path,
        require_path_selected=True,
        expected_version="codex-cli 0.142.2",
    )

    assert result.status == "ok"
    assert result.pinned_codex_path == pinned_codex_path
    checks = {check.name: check.status for check in result.checks}
    assert checks["launcher_probe"] == "ok"
    assert checks["omnigent_resolver_managed_launcher"] == "ok"
    assert checks["pinned_codex_expected_version"] == "ok"


def test_doctor_fails_when_launcher_is_not_selected_codex(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    launcher_path, manifest_path, _ = _install_managed_launcher(
        tmp_path,
        monkeypatch,
        require_path_selected=False,
    )
    shadow_bin = tmp_path / "shadow-bin"
    _write_executable(shadow_bin / "codex", "#!/bin/sh\nexit 0\n")
    monkeypatch.setenv("PATH", str(shadow_bin))

    result = _DOCTOR.run_doctor(
        launcher_path=launcher_path,
        manifest_path=manifest_path,
        require_path_selected=True,
    )

    assert result.status == "failed"
    checks = {check.name: check for check in result.checks}
    assert checks["launcher_is_selected_codex"].status == "failed"
    assert str(launcher_path) in checks["launcher_is_selected_codex"].detail
    assert checks["omnigent_resolver_managed_launcher"].status == "failed"


def test_doctor_fails_when_recorded_backup_is_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    launcher_path, manifest_path, _ = _install_managed_launcher(
        tmp_path,
        monkeypatch,
        backup_existing=True,
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    backup_path = Path(manifest["backupPath"])
    backup_path.unlink()

    result = _DOCTOR.run_doctor(
        launcher_path=launcher_path,
        manifest_path=manifest_path,
        require_path_selected=True,
    )

    assert result.status == "failed"
    checks = {check.name: check for check in result.checks}
    assert checks["manifest_backup_path"].status == "failed"
    assert str(backup_path) in checks["manifest_backup_path"].detail


def test_main_json_reports_failure_without_repair(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    launcher_path = _write_executable(tmp_path / "bin" / "codex", "#!/bin/sh\nexit 0\n")
    manifest_path = tmp_path / "missing.json"

    rc = _DOCTOR.main(
        [
            "--launcher-path",
            str(launcher_path),
            "--manifest-path",
            str(manifest_path),
            "--no-require-path-selected",
            "--json",
        ]
    )

    assert rc == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "failed"
    assert launcher_path.exists()
    assert not manifest_path.exists()
