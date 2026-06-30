#!/usr/bin/env python3
# ruff: noqa: E402, I001
"""Read-only health checks for the persistent Omnigent ``codex`` launcher."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from install_omnigent_codex_launcher import (
    DEFAULT_MANIFEST_PATH,
    LauncherInstallError,
    MANIFEST_KIND,
    PROBE_ARG,
    PROBE_SENTINEL,
    codex_version,
    is_executable_file,
    is_managed_launcher,
    read_manifest,
    rollback_command,
)
from omnigent.inner.codex_executor import (
    OMNIGENT_CODEX_LAUNCHER_MANIFEST_PREFIX,
    OMNIGENT_STOCK_CODEX_PATH_ENV,
    _find_codex_cli,
)


@dataclass(frozen=True)
class DoctorCheck:
    """One launcher doctor assertion."""

    name: str
    status: str
    detail: str


@dataclass(frozen=True)
class LauncherDoctorResult:
    """Aggregate result for the read-only launcher doctor."""

    status: str
    launcher_path: Path
    selected_codex_path: str | None
    manifest_path: Path
    pinned_codex_path: Path | None
    pinned_codex_version: str | None
    backup_path: Path | None
    rollback_command: str | None
    checks: list[DoctorCheck]


def _default_launcher_path() -> Path:
    raw = shutil.which("codex")
    return Path(raw).expanduser() if raw else Path.home() / ".local" / "bin" / "codex"


def _path_from_manifest_value(value: object) -> Path | None:
    if not isinstance(value, str) or not value:
        return None
    return Path(value).expanduser()


def _manifest_path_from_launcher(launcher_path: Path) -> Path | None:
    try:
        with launcher_path.open("rb") as handle:
            text = handle.read(4096).decode("utf-8", errors="ignore")
    except OSError:
        return None
    for line in text.splitlines()[:10]:
        if line.startswith(OMNIGENT_CODEX_LAUNCHER_MANIFEST_PREFIX):
            raw = line.removeprefix(OMNIGENT_CODEX_LAUNCHER_MANIFEST_PREFIX).strip()
            return Path(raw).expanduser() if raw else None
    return None


def _run_probe(launcher_path: Path) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            [str(launcher_path), PROBE_ARG],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None


def _run_launcher_version(launcher_path: Path) -> str | None:
    try:
        completed = subprocess.run(
            [str(launcher_path), "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    version = (completed.stdout or completed.stderr).strip()
    return version or None


def _append_check(
    checks: list[DoctorCheck],
    *,
    name: str,
    ok: bool,
    ok_detail: str,
    failure_detail: str,
) -> None:
    checks.append(
        DoctorCheck(
            name=name,
            status="ok" if ok else "failed",
            detail=ok_detail if ok else failure_detail,
        )
    )


def _check_selected_launcher(
    checks: list[DoctorCheck],
    *,
    selected: str | None,
    launcher_path: Path,
    require_path_selected: bool,
) -> None:
    if selected is None:
        _append_check(
            checks,
            name="codex_path_selected",
            ok=False,
            ok_detail="codex found on PATH",
            failure_detail="codex was not found on PATH",
        )
        return
    _append_check(
        checks,
        name="codex_path_selected",
        ok=True,
        ok_detail=f"codex resolves to {selected}",
        failure_detail="codex was not found on PATH",
    )
    if require_path_selected:
        _append_check(
            checks,
            name="launcher_is_selected_codex",
            ok=selected == str(launcher_path),
            ok_detail=f"selected codex is {launcher_path}",
            failure_detail=f"expected selected codex {launcher_path}, got {selected}",
        )


def _check_launcher_file(
    checks: list[DoctorCheck],
    *,
    launcher_path: Path,
    manifest_path: Path,
) -> None:
    _append_check(
        checks,
        name="launcher_exists",
        ok=launcher_path.is_file(),
        ok_detail=f"launcher exists at {launcher_path}",
        failure_detail=f"launcher missing at {launcher_path}",
    )
    _append_check(
        checks,
        name="launcher_executable",
        ok=is_executable_file(launcher_path),
        ok_detail="launcher is executable",
        failure_detail="launcher is missing or not executable",
    )
    _append_check(
        checks,
        name="launcher_managed_marker",
        ok=is_managed_launcher(launcher_path),
        ok_detail="launcher carries the Omnigent managed marker",
        failure_detail="launcher is not marked as Omnigent managed",
    )
    embedded_manifest = _manifest_path_from_launcher(launcher_path)
    _append_check(
        checks,
        name="launcher_manifest_pointer",
        ok=embedded_manifest == manifest_path,
        ok_detail=f"launcher points at manifest {manifest_path}",
        failure_detail=(
            f"launcher manifest pointer mismatch: expected {manifest_path}, "
            f"got {embedded_manifest}"
        ),
    )


def _check_manifest(
    checks: list[DoctorCheck],
    *,
    manifest: dict[str, object],
    launcher_path: Path,
    manifest_path: Path,
) -> tuple[Path | None, str | None, Path | None, Path | None, Path | None]:
    _append_check(
        checks,
        name="manifest_exists",
        ok=manifest_path.is_file() and bool(manifest),
        ok_detail=f"manifest exists at {manifest_path}",
        failure_detail=f"manifest missing or unreadable at {manifest_path}",
    )
    _append_check(
        checks,
        name="manifest_kind",
        ok=manifest.get("kind") == MANIFEST_KIND,
        ok_detail=f"manifest kind is {MANIFEST_KIND}",
        failure_detail=f"manifest kind mismatch: {manifest.get('kind')!r}",
    )
    _append_check(
        checks,
        name="manifest_launcher_path",
        ok=manifest.get("launcherPath") == str(launcher_path),
        ok_detail=f"manifest records launcher {launcher_path}",
        failure_detail=(
            f"manifest launcher mismatch: expected {launcher_path}, "
            f"got {manifest.get('launcherPath')!r}"
        ),
    )
    _append_check(
        checks,
        name="manifest_manifest_path",
        ok=manifest.get("manifestPath") == str(manifest_path),
        ok_detail=f"manifest records itself at {manifest_path}",
        failure_detail=(
            f"manifest self-path mismatch: expected {manifest_path}, "
            f"got {manifest.get('manifestPath')!r}"
        ),
    )
    pinned_codex_path = _path_from_manifest_value(manifest.get("pinnedCodexPath"))
    pinned_version_raw = manifest.get("pinnedCodexVersion")
    pinned_codex_version = (
        pinned_version_raw if isinstance(pinned_version_raw, str) and pinned_version_raw else None
    )
    backup_path = _path_from_manifest_value(manifest.get("backupPath"))
    repo_root = _path_from_manifest_value(manifest.get("repoRoot"))
    uvx_path = _path_from_manifest_value(manifest.get("uvxPath"))
    _append_check(
        checks,
        name="manifest_pinned_codex_path",
        ok=pinned_codex_path is not None,
        ok_detail=f"manifest records pinned Codex {pinned_codex_path}",
        failure_detail="manifest does not record a pinned Codex path",
    )
    _append_check(
        checks,
        name="manifest_pinned_codex_version",
        ok=pinned_codex_version is not None,
        ok_detail=f"manifest records pinned version {pinned_codex_version}",
        failure_detail="manifest does not record a pinned Codex version",
    )
    env = manifest.get("env")
    env_pinned = env.get(OMNIGENT_STOCK_CODEX_PATH_ENV) if isinstance(env, dict) else None
    _append_check(
        checks,
        name="manifest_pinned_env",
        ok=pinned_codex_path is not None and env_pinned == str(pinned_codex_path),
        ok_detail=f"manifest env pins {OMNIGENT_STOCK_CODEX_PATH_ENV}={env_pinned}",
        failure_detail=(
            f"manifest env mismatch for {OMNIGENT_STOCK_CODEX_PATH_ENV}: {env_pinned!r}"
        ),
    )
    _append_check(
        checks,
        name="manifest_repo_root",
        ok=repo_root is not None and repo_root.is_dir(),
        ok_detail=f"repo root exists at {repo_root}",
        failure_detail=f"repo root missing or invalid: {repo_root}",
    )
    _append_check(
        checks,
        name="manifest_uvx_path",
        ok=uvx_path is not None and is_executable_file(uvx_path),
        ok_detail=f"uvx exists at {uvx_path}",
        failure_detail=f"uvx path missing or not executable: {uvx_path}",
    )
    if backup_path is None:
        checks.append(
            DoctorCheck(
                name="manifest_backup_path",
                status="ok",
                detail="manifest records no backup path",
            )
        )
    else:
        _append_check(
            checks,
            name="manifest_backup_path",
            ok=backup_path.exists() or backup_path.is_symlink(),
            ok_detail=f"backup exists at {backup_path}",
            failure_detail=f"manifest backup is missing: {backup_path}",
        )
    return pinned_codex_path, pinned_codex_version, backup_path, repo_root, uvx_path


def _check_pinned_codex(
    checks: list[DoctorCheck],
    *,
    pinned_codex_path: Path | None,
    pinned_codex_version: str | None,
    expected_version: str | None,
) -> None:
    _append_check(
        checks,
        name="pinned_codex_executable",
        ok=pinned_codex_path is not None and is_executable_file(pinned_codex_path),
        ok_detail=f"pinned Codex is executable at {pinned_codex_path}",
        failure_detail=f"pinned Codex is missing or not executable: {pinned_codex_path}",
    )
    actual_version: str | None = None
    if pinned_codex_path is not None and is_executable_file(pinned_codex_path):
        try:
            actual_version = codex_version(pinned_codex_path)
        except LauncherInstallError as exc:
            actual_version = None
            checks.append(
                DoctorCheck(
                    name="pinned_codex_version_probe",
                    status="failed",
                    detail=f"pinned Codex version probe failed: {exc}",
                )
            )
    if actual_version is not None:
        _append_check(
            checks,
            name="pinned_codex_version_probe",
            ok=actual_version == pinned_codex_version,
            ok_detail=f"pinned Codex reports {actual_version}",
            failure_detail=(
                f"pinned Codex version mismatch: expected {pinned_codex_version!r}, "
                f"got {actual_version!r}"
            ),
        )
    if expected_version is not None:
        _append_check(
            checks,
            name="pinned_codex_expected_version",
            ok=actual_version == expected_version,
            ok_detail=f"pinned Codex matches expected version {expected_version}",
            failure_detail=(
                f"expected pinned Codex version {expected_version!r}, got {actual_version!r}"
            ),
        )


def _check_launcher_delegation(
    checks: list[DoctorCheck],
    *,
    launcher_path: Path,
    pinned_codex_path: Path | None,
    pinned_codex_version: str | None,
    repo_root: Path | None,
    uvx_path: Path | None,
) -> None:
    probe = _run_probe(launcher_path)
    probe_output = ""
    probe_ok = False
    if probe is not None:
        probe_output = (probe.stdout or "") + (probe.stderr or "")
        probe_ok = probe.returncode == 0 and PROBE_SENTINEL in probe_output
    _append_check(
        checks,
        name="launcher_probe",
        ok=probe_ok,
        ok_detail=f"launcher probe returned {PROBE_SENTINEL}",
        failure_detail=f"launcher probe failed: {probe_output.strip() or probe}",
    )
    if pinned_codex_path is not None:
        expected_env = f"pinned_env={OMNIGENT_STOCK_CODEX_PATH_ENV}={pinned_codex_path}"
        _append_check(
            checks,
            name="launcher_probe_pinned_env",
            ok=expected_env in probe_output,
            ok_detail=f"probe reports {expected_env}",
            failure_detail=f"probe missing {expected_env}",
        )
    if pinned_codex_version is not None:
        expected_version = f"pinned_codex_version={pinned_codex_version}"
        _append_check(
            checks,
            name="launcher_probe_pinned_version",
            ok=expected_version in probe_output,
            ok_detail=f"probe reports {expected_version}",
            failure_detail=f"probe missing {expected_version}",
        )
    if repo_root is not None and uvx_path is not None:
        expected_delegate = f"delegate={uvx_path} --from {repo_root} omnigent codex"
        _append_check(
            checks,
            name="launcher_probe_delegate",
            ok=expected_delegate in probe_output,
            ok_detail=f"probe reports {expected_delegate}",
            failure_detail=f"probe missing {expected_delegate}",
        )
    version = _run_launcher_version(launcher_path)
    _append_check(
        checks,
        name="launcher_version_delegates_to_pinned",
        ok=version == pinned_codex_version,
        ok_detail=f"launcher --version returned {version}",
        failure_detail=(
            f"launcher --version mismatch: expected {pinned_codex_version!r}, got {version!r}"
        ),
    )


def _check_omnigent_resolver(
    checks: list[DoctorCheck],
    *,
    selected: str | None,
    launcher_path: Path,
    pinned_codex_path: Path | None,
) -> None:
    if selected != str(launcher_path):
        checks.append(
            DoctorCheck(
                name="omnigent_resolver_managed_launcher",
                status="failed",
                detail="cannot prove resolver mapping because launcher is not selected on PATH",
            )
        )
        return
    previous_env = os.environ.pop(OMNIGENT_STOCK_CODEX_PATH_ENV, None)
    try:
        resolved = _find_codex_cli()
    finally:
        if previous_env is not None:
            os.environ[OMNIGENT_STOCK_CODEX_PATH_ENV] = previous_env
    _append_check(
        checks,
        name="omnigent_resolver_managed_launcher",
        ok=pinned_codex_path is not None and resolved == str(pinned_codex_path),
        ok_detail=f"Omnigent resolver maps launcher to {resolved}",
        failure_detail=(
            f"Omnigent resolver mismatch: expected {pinned_codex_path}, got {resolved}"
        ),
    )


def run_doctor(
    *,
    launcher_path: Path,
    manifest_path: Path,
    require_path_selected: bool,
    expected_version: str | None = None,
) -> LauncherDoctorResult:
    """Run the read-only launcher doctor."""

    launcher_path = launcher_path.expanduser()
    manifest_path = manifest_path.expanduser()
    selected = shutil.which("codex")
    checks: list[DoctorCheck] = []
    _check_selected_launcher(
        checks,
        selected=selected,
        launcher_path=launcher_path,
        require_path_selected=require_path_selected,
    )
    _check_launcher_file(checks, launcher_path=launcher_path, manifest_path=manifest_path)
    manifest = read_manifest(manifest_path)
    (
        pinned_codex_path,
        pinned_codex_version,
        backup_path,
        repo_root,
        uvx_path,
    ) = _check_manifest(
        checks,
        manifest=manifest,
        launcher_path=launcher_path,
        manifest_path=manifest_path,
    )
    _check_pinned_codex(
        checks,
        pinned_codex_path=pinned_codex_path,
        pinned_codex_version=pinned_codex_version,
        expected_version=expected_version,
    )
    _check_launcher_delegation(
        checks,
        launcher_path=launcher_path,
        pinned_codex_path=pinned_codex_path,
        pinned_codex_version=pinned_codex_version,
        repo_root=repo_root,
        uvx_path=uvx_path,
    )
    _check_omnigent_resolver(
        checks,
        selected=selected,
        launcher_path=launcher_path,
        pinned_codex_path=pinned_codex_path,
    )
    rollback = (
        rollback_command(repo_root, launcher_path, manifest_path)
        if repo_root is not None
        else None
    )
    status = "ok" if all(check.status == "ok" for check in checks) else "failed"
    return LauncherDoctorResult(
        status=status,
        launcher_path=launcher_path,
        selected_codex_path=selected,
        manifest_path=manifest_path,
        pinned_codex_path=pinned_codex_path,
        pinned_codex_version=pinned_codex_version,
        backup_path=backup_path,
        rollback_command=rollback,
        checks=checks,
    )


def result_dict(result: LauncherDoctorResult) -> dict[str, Any]:
    return {
        "status": result.status,
        "launcherPath": str(result.launcher_path),
        "selectedCodexPath": result.selected_codex_path,
        "manifestPath": str(result.manifest_path),
        "pinnedCodexPath": str(result.pinned_codex_path)
        if result.pinned_codex_path is not None
        else None,
        "pinnedCodexVersion": result.pinned_codex_version,
        "backupPath": str(result.backup_path) if result.backup_path is not None else None,
        "rollbackCommand": result.rollback_command,
        "checks": [
            {"name": check.name, "status": check.status, "detail": check.detail}
            for check in result.checks
        ],
    }


def print_result(result: LauncherDoctorResult, *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result_dict(result), indent=2, sort_keys=True))
        return
    print(f"doctor_status={result.status}")
    print(f"launcher_path={result.launcher_path}")
    print(f"selected_codex_path={result.selected_codex_path}")
    print(f"launcher_manifest={result.manifest_path}")
    if result.pinned_codex_path is not None:
        print(f"launcher_pinned_codex_path={result.pinned_codex_path}")
    if result.pinned_codex_version is not None:
        print(f"launcher_pinned_codex_version={result.pinned_codex_version}")
    if result.backup_path is not None:
        print(f"launcher_backup_path={result.backup_path}")
    if result.rollback_command is not None:
        print(f"launcher_rollback_command={result.rollback_command}")
    for check in result.checks:
        print(f"check_{check.name}={check.status}: {check.detail}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only doctor for the persistent Omnigent codex launcher."
    )
    parser.add_argument("--launcher-path", type=Path, default=None)
    parser.add_argument("--manifest-path", type=Path, default=DEFAULT_MANIFEST_PATH)
    parser.add_argument("--expected-version", default=None)
    parser.add_argument(
        "--no-require-path-selected",
        action="store_true",
        help="Inspect the launcher even if it is not the selected codex on PATH.",
    )
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = run_doctor(
        launcher_path=args.launcher_path or _default_launcher_path(),
        manifest_path=args.manifest_path,
        require_path_selected=not args.no_require_path_selected,
        expected_version=args.expected_version,
    )
    print_result(result, as_json=args.json)
    return 0 if result.status == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
