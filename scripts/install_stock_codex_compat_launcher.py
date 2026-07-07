#!/usr/bin/env python3
"""Install or remove the stock-Codex compatibility launcher."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from omnigent.adapters.apple_docs_cli import (
    build_fetch_apple_docs_stock_codex_bridge_adapter_spec,
)
from omnigent.adapters.stock_codex_compat import (
    StockCodexCompatAdapterPackage,
    write_stock_codex_compat_adapter_package,
)
from omnigent.inner.codex_executor import (
    OMNIGENT_CODEX_LAUNCHER_MANIFEST_PREFIX,
    OMNIGENT_MANAGED_CODEX_LAUNCHER_MARKER,
    OMNIGENT_STOCK_CODEX_PATH_ENV,
    _find_codex_cli,
)
from omnigent.stock_codex_compat_wrapper import (
    ADAPTER_BIN_ENV,
    ADAPTER_BRIDGE_DIR_ENV,
    ADAPTER_MANIFEST_ENV,
    ROUTE_PREFIX_ENV,
    STOCK_CODEX_PATH_ENV,
    AdapterPackage,
    validate_adapter_manifest,
)

PROBE_ARG = "--omnigent-stock-codex-compat-launcher-probe"
PROBE_SENTINEL = "OMNIGENT_STOCK_CODEX_COMPAT_LAUNCHER_OK"
MANIFEST_KIND = "omnigent-stock-codex-compat-launcher"
COMPAT_LAUNCHER_MARKER = "omnigent-stock-codex-compat-launcher"
WRAPPER_ENTRYPOINT = "omnigent-stock-codex-wrapper"
DEFAULT_ROUTE_PREFIX = (
    "Routing: orchestrator-led\n\n"
    "Activated skills\n"
    "- `apple-appdev-workflow:apple-app-orchestrator`"
)
DEFAULT_LAUNCHER_PATH = Path.home() / ".local" / "bin" / "omnigent-stock-codex-compat"
DEFAULT_MANIFEST_PATH = (
    Path.home() / ".local" / "omnigent" / "launchers" / "stock-codex-compat.json"
)
DEFAULT_ADAPTER_BRIDGE_DIR = (
    Path.home() / ".local" / "omnigent" / "stock-codex-compat" / "adapter-bridge"
)
DEFAULT_ADAPTER_PACKAGE_DIR = (
    Path.home() / ".local" / "omnigent" / "stock-codex-compat" / "adapter-package"
)


@dataclass(frozen=True)
class CompatLauncherInstallResult:
    """Result of a compatibility launcher install or removal."""

    action: str
    launcher_path: Path
    manifest_path: Path
    pinned_codex_path: Path | None
    adapter_bin: Path | None
    adapter_manifest: Path | None
    adapter_bridge_dir: Path | None
    backup_path: Path | None
    rollback_command: str | None


@dataclass(frozen=True)
class CompatLauncherDoctorResult:
    """Non-mutating compatibility launcher install diagnosis."""

    action: str
    install_allowed: bool
    install_blocker: str | None
    launcher_path: Path
    manifest_path: Path
    repo_root: Path
    uvx_path: Path
    pinned_codex_path: Path
    pinned_codex_version: str
    route_prefix: str
    adapter_bin: Path
    adapter_manifest: Path
    adapter_bridge_dir: Path
    adapter_tool_names: tuple[str, ...]
    existing_target_state: str
    existing_target_managed: bool
    existing_target_is_symlink: bool
    existing_target_realpath: Path | None
    existing_manifest_kind: str | None
    existing_manifest_pinned_codex_path: Path | None
    selected_command_path: Path | None
    target_selected_on_path: bool
    launcher_parent_on_path: bool
    launcher_parent_exists: bool
    nearest_existing_parent: Path
    nearest_existing_parent_writable: bool
    backup_existing_requested: bool
    force_requested: bool
    would_backup_existing: bool
    backup_path: Path | None
    rollback_command: str
    install_command: str
    mutates_filesystem: bool = False


@dataclass(frozen=True)
class CompatAdapterPackageInstallResult:
    """Result of installing or reusing the persistent compatibility adapter package."""

    action: str
    adapter_package_dir: Path
    adapter_bin: Path
    adapter_manifest: Path
    adapter_tool_names: tuple[str, ...]
    mutates_filesystem: bool


class CompatLauncherInstallError(RuntimeError):
    """The compatibility launcher could not be installed or removed."""


def codex_version(path: Path) -> str:
    try:
        completed = subprocess.run(
            [str(path), "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception as exc:
        raise CompatLauncherInstallError(f"Could not run {path} --version: {exc}") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise CompatLauncherInstallError(
            f"{path} --version exited {completed.returncode}: {detail or 'no output'}"
        )
    version = (completed.stdout or completed.stderr).strip()
    if not version:
        raise CompatLauncherInstallError(f"{path} --version produced no output")
    return version


def is_executable_file(path: Path) -> bool:
    return path.is_file() and os.access(path, os.X_OK)


def is_managed_launcher(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    return (
        OMNIGENT_MANAGED_CODEX_LAUNCHER_MARKER in text
        and COMPAT_LAUNCHER_MARKER in text
    )


def backup_path_for(launcher_path: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    candidate = launcher_path.with_name(f"{launcher_path.name}.omnigent-backup-{stamp}")
    index = 1
    while candidate.exists() or candidate.is_symlink():
        candidate = launcher_path.with_name(
            f"{launcher_path.name}.omnigent-backup-{stamp}.{index}"
        )
        index += 1
    return candidate


def nearest_existing_parent(path: Path) -> Path:
    """Return the nearest existing parent for a path without creating directories."""
    current = path.expanduser()
    while not current.exists() and current.parent != current:
        current = current.parent
    return current if current.exists() else current.parent


def path_contains_directory(path_value: str, directory: Path) -> bool:
    """Return whether PATH contains a directory, resolving entries best-effort."""
    directory_resolved = directory.expanduser().resolve()
    for raw_part in path_value.split(os.pathsep):
        if not raw_part:
            continue
        try:
            if Path(raw_part).expanduser().resolve() == directory_resolved:
                return True
        except OSError:
            if Path(raw_part).expanduser() == directory:
                return True
    return False


def default_adapter_bin(adapter_package_dir: Path) -> Path:
    """Return the default adapter bin path for a package root."""
    return adapter_package_dir.expanduser() / "bin"


def default_adapter_manifest(adapter_package_dir: Path) -> Path:
    """Return the default adapter manifest path for a package root."""
    return adapter_package_dir.expanduser() / "adapter-manifest.json"


def validate_adapter_package_or_error(
    adapter_manifest: Path,
    adapter_bin: Path | None,
) -> AdapterPackage:
    """Validate an adapter package and convert wrapper CLI exits to install errors."""
    try:
        return validate_adapter_manifest(adapter_manifest, adapter_bin)
    except SystemExit as exc:
        detail = str(exc) or "adapter package validation failed"
        raise CompatLauncherInstallError(detail) from exc


def materialize_default_adapter_package(
    adapter_package_dir: Path,
    *,
    force: bool,
) -> CompatAdapterPackageInstallResult:
    """Install or reuse the default persistent compatibility adapter package."""
    adapter_package_dir = adapter_package_dir.expanduser()
    adapter_bin = default_adapter_bin(adapter_package_dir)
    adapter_manifest = default_adapter_manifest(adapter_package_dir)
    if adapter_package_dir.exists() and not adapter_package_dir.is_dir():
        raise CompatLauncherInstallError(
            f"Adapter package path exists and is not a directory: {adapter_package_dir}"
        )

    if adapter_manifest.exists() and adapter_bin.is_dir() and not force:
        adapter_package = validate_adapter_package_or_error(adapter_manifest, adapter_bin)
        return CompatAdapterPackageInstallResult(
            action="adapter-package-reused",
            adapter_package_dir=adapter_package_dir,
            adapter_bin=adapter_package.adapter_bin,
            adapter_manifest=adapter_package.manifest_path,
            adapter_tool_names=adapter_package.tool_names,
            mutates_filesystem=False,
        )

    if adapter_package_dir.exists():
        if not force and any(adapter_package_dir.iterdir()):
            raise CompatLauncherInstallError(
                "Adapter package exists but is incomplete or invalid. "
                f"Rerun with --force to replace it: {adapter_package_dir}"
            )
        shutil.rmtree(adapter_package_dir)

    package: StockCodexCompatAdapterPackage = write_stock_codex_compat_adapter_package(
        adapter_package_dir,
        (build_fetch_apple_docs_stock_codex_bridge_adapter_spec(),),
    )
    validated = validate_adapter_package_or_error(package.manifest_path, package.adapter_bin)
    return CompatAdapterPackageInstallResult(
        action="adapter-package-installed",
        adapter_package_dir=package.root,
        adapter_bin=validated.adapter_bin,
        adapter_manifest=validated.manifest_path,
        adapter_tool_names=validated.tool_names,
        mutates_filesystem=True,
    )


def resolve_adapter_paths(
    *,
    adapter_bin: Path | None,
    adapter_manifest: Path | None,
    adapter_package_dir: Path,
) -> tuple[Path, Path]:
    """Resolve explicit adapter paths or the default persistent package paths."""
    if (adapter_bin is None) != (adapter_manifest is None):
        raise CompatLauncherInstallError(
            "--adapter-bin and --adapter-manifest must be supplied together."
        )
    if adapter_bin is not None and adapter_manifest is not None:
        return adapter_bin.expanduser(), adapter_manifest.expanduser()
    return (
        default_adapter_bin(adapter_package_dir),
        default_adapter_manifest(adapter_package_dir),
    )


def install_command(
    repo_root: Path,
    *,
    launcher_path: Path,
    manifest_path: Path,
    pinned_codex_path: Path,
    route_prefix: str,
    adapter_bin: Path,
    adapter_manifest: Path,
    adapter_bridge_dir: Path,
    backup_existing: bool,
    force: bool,
    require_path_selected: bool,
) -> str:
    parts = [
        "uvx",
        "--from",
        str(repo_root),
        "python",
        str(repo_root / "scripts" / "install_stock_codex_compat_launcher.py"),
        "--install",
        "--launcher-path",
        str(launcher_path),
        "--manifest-path",
        str(manifest_path),
        "--pinned-codex-path",
        str(pinned_codex_path),
        "--route-prefix",
        route_prefix,
        "--adapter-bin",
        str(adapter_bin),
        "--adapter-manifest",
        str(adapter_manifest),
        "--adapter-bridge-dir",
        str(adapter_bridge_dir),
    ]
    if backup_existing:
        parts.append("--backup-existing")
    if force:
        parts.append("--force")
    if require_path_selected:
        parts.append("--require-path-selected")
    return " ".join(shlex.quote(part) for part in parts)


def write_launcher(
    launcher_path: Path,
    *,
    manifest_path: Path,
    repo_root: Path,
    uvx_path: Path,
    pinned_codex_path: Path,
    pinned_codex_version: str,
    route_prefix: str,
    adapter_bin: Path,
    adapter_manifest: Path,
    adapter_bridge_dir: Path,
) -> None:
    launcher_path.write_text(
        f"""#!/bin/sh
# {OMNIGENT_MANAGED_CODEX_LAUNCHER_MARKER}
# {COMPAT_LAUNCHER_MARKER}
{OMNIGENT_CODEX_LAUNCHER_MANIFEST_PREFIX} {manifest_path}
set -eu

PINNED_CODEX_PATH={shlex.quote(str(pinned_codex_path))}
PINNED_CODEX_VERSION={shlex.quote(pinned_codex_version)}
UVX_PATH={shlex.quote(str(uvx_path))}
REPO_ROOT={shlex.quote(str(repo_root))}
ROUTE_PREFIX={shlex.quote(route_prefix)}
ADAPTER_BIN={shlex.quote(str(adapter_bin))}
ADAPTER_MANIFEST={shlex.quote(str(adapter_manifest))}
ADAPTER_BRIDGE_DIR={shlex.quote(str(adapter_bridge_dir))}
PROBE_ARG={shlex.quote(PROBE_ARG)}
PROBE_SENTINEL={shlex.quote(PROBE_SENTINEL)}

if [ "${{1:-}}" = "$PROBE_ARG" ]; then
  printf '%s\\n' "$PROBE_SENTINEL"
  printf 'launcher_path=%s\\n' "$0"
  printf 'pinned_env=%s=%s\\n' "{OMNIGENT_STOCK_CODEX_PATH_ENV}" "$PINNED_CODEX_PATH"
  printf 'pinned_codex_version=%s\\n' "$PINNED_CODEX_VERSION"
  printf 'route_prefix=%s\\n' "$ROUTE_PREFIX"
  printf 'adapter_bin=%s\\n' "$ADAPTER_BIN"
  printf 'adapter_manifest=%s\\n' "$ADAPTER_MANIFEST"
  printf 'adapter_bridge_dir=%s\\n' "$ADAPTER_BRIDGE_DIR"
  printf 'delegate=%s --from %s {WRAPPER_ENTRYPOINT}\\n' "$UVX_PATH" "$REPO_ROOT"
  exit 0
fi

if [ "${{1:-}}" = "--version" ]; then
  exec "$PINNED_CODEX_PATH" --version
fi

if [ ! -x "$PINNED_CODEX_PATH" ]; then
  printf 'omnigent_stock_codex_compat_launcher_error=pinned codex missing: %s\\n' \\
    "$PINNED_CODEX_PATH" >&2
  exit 127
fi
if [ ! -x "$UVX_PATH" ]; then
  printf 'omnigent_stock_codex_compat_launcher_error=uvx missing: %s\\n' "$UVX_PATH" >&2
  exit 127
fi
if [ ! -d "$ADAPTER_BIN" ]; then
  printf 'omnigent_stock_codex_compat_launcher_error=adapter bin missing: %s\\n' \\
    "$ADAPTER_BIN" >&2
  exit 72
fi
if [ ! -f "$ADAPTER_MANIFEST" ]; then
  printf 'omnigent_stock_codex_compat_launcher_error=adapter manifest missing: %s\\n' \\
    "$ADAPTER_MANIFEST" >&2
  exit 72
fi

{OMNIGENT_STOCK_CODEX_PATH_ENV}="$PINNED_CODEX_PATH"
{STOCK_CODEX_PATH_ENV}="$PINNED_CODEX_PATH"
{ROUTE_PREFIX_ENV}="$ROUTE_PREFIX"
{ADAPTER_BIN_ENV}="$ADAPTER_BIN"
{ADAPTER_MANIFEST_ENV}="$ADAPTER_MANIFEST"
{ADAPTER_BRIDGE_DIR_ENV}="$ADAPTER_BRIDGE_DIR"
export {OMNIGENT_STOCK_CODEX_PATH_ENV}
export {STOCK_CODEX_PATH_ENV}
export {ROUTE_PREFIX_ENV}
export {ADAPTER_BIN_ENV}
export {ADAPTER_MANIFEST_ENV}
export {ADAPTER_BRIDGE_DIR_ENV}

exec "$UVX_PATH" --from "$REPO_ROOT" {WRAPPER_ENTRYPOINT} \\
  --stock-codex-path "$PINNED_CODEX_PATH" \\
  --route-prefix "$ROUTE_PREFIX" \\
  --adapter-bin "$ADAPTER_BIN" \\
  --adapter-manifest "$ADAPTER_MANIFEST" \\
  --adapter-bridge-dir "$ADAPTER_BRIDGE_DIR" \\
  -- "$@"
""",
        encoding="utf-8",
    )
    launcher_path.chmod(0o755)


def write_manifest(
    manifest_path: Path,
    *,
    launcher_path: Path,
    repo_root: Path,
    uvx_path: Path,
    pinned_codex_path: Path,
    pinned_codex_version: str,
    route_prefix: str,
    adapter_bin: Path,
    adapter_manifest: Path,
    adapter_bridge_dir: Path,
    adapter_tool_names: tuple[str, ...],
    backup_path: Path | None,
) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schemaVersion": 1,
        "kind": MANIFEST_KIND,
        "launcherPath": str(launcher_path),
        "manifestPath": str(manifest_path),
        "repoRoot": str(repo_root),
        "uvxPath": str(uvx_path),
        "wrapperEntrypoint": WRAPPER_ENTRYPOINT,
        "pinnedCodexPath": str(pinned_codex_path),
        "pinnedCodexVersion": pinned_codex_version,
        "routePrefix": route_prefix,
        "adapterBin": str(adapter_bin),
        "adapterManifest": str(adapter_manifest),
        "adapterBridgeDir": str(adapter_bridge_dir),
        "adapterToolNames": list(adapter_tool_names),
        "backupPath": str(backup_path) if backup_path is not None else None,
        "installedAt": datetime.now(timezone.utc).isoformat(),
        "env": {
            OMNIGENT_STOCK_CODEX_PATH_ENV: str(pinned_codex_path),
            STOCK_CODEX_PATH_ENV: str(pinned_codex_path),
            ROUTE_PREFIX_ENV: route_prefix,
            ADAPTER_BIN_ENV: str(adapter_bin),
            ADAPTER_MANIFEST_ENV: str(adapter_manifest),
            ADAPTER_BRIDGE_DIR_ENV: str(adapter_bridge_dir),
        },
        "probeArg": PROBE_ARG,
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def doctor_launcher(
    *,
    launcher_path: Path,
    manifest_path: Path,
    repo_root: Path,
    uvx_path: Path,
    pinned_codex_path: Path,
    route_prefix: str,
    adapter_bin: Path,
    adapter_manifest: Path,
    adapter_bridge_dir: Path,
    backup_existing: bool,
    force: bool,
    require_path_selected: bool,
) -> CompatLauncherDoctorResult:
    """Validate a compatibility launcher install plan without mutating files."""
    launcher_path = launcher_path.expanduser()
    manifest_path = manifest_path.expanduser()
    repo_root = repo_root.expanduser().resolve()
    uvx_path = uvx_path.expanduser().resolve()
    pinned_codex_path = pinned_codex_path.expanduser().resolve()
    adapter_bin = adapter_bin.expanduser().resolve()
    adapter_manifest = adapter_manifest.expanduser().resolve()
    adapter_bridge_dir = adapter_bridge_dir.expanduser().resolve()
    if not repo_root.is_dir():
        raise CompatLauncherInstallError(f"Repo root not found: {repo_root}")
    if not is_executable_file(uvx_path):
        raise CompatLauncherInstallError(f"uvx binary is not executable: {uvx_path}")
    if not is_executable_file(pinned_codex_path):
        raise CompatLauncherInstallError(
            f"Pinned Codex binary is not executable: {pinned_codex_path}"
        )
    adapter_package = validate_adapter_package_or_error(adapter_manifest, adapter_bin)
    adapter_bin = adapter_package.adapter_bin
    adapter_manifest = adapter_package.manifest_path
    pinned_codex_version = codex_version(pinned_codex_path)

    existing = launcher_path.exists() or launcher_path.is_symlink()
    existing_managed = existing and is_managed_launcher(launcher_path)
    existing_state = "absent"
    install_blocker: str | None = None
    would_backup_existing = False
    backup_path: Path | None = None
    if existing and existing_managed:
        existing_state = "managed"
        if not force:
            install_blocker = "requires-force-for-managed-target"
    elif existing:
        existing_state = "unmanaged"
        if backup_existing:
            would_backup_existing = True
            backup_path = backup_path_for(launcher_path)
        else:
            install_blocker = "requires-backup-existing-for-unmanaged-target"

    existing_manifest = read_manifest(manifest_path)
    existing_manifest_kind_raw = existing_manifest.get("kind")
    existing_manifest_kind = (
        existing_manifest_kind_raw if isinstance(existing_manifest_kind_raw, str) else None
    )
    existing_pinned_raw = existing_manifest.get("pinnedCodexPath")
    existing_manifest_pinned_codex_path = (
        Path(existing_pinned_raw).expanduser()
        if isinstance(existing_pinned_raw, str) and existing_pinned_raw
        else None
    )
    selected_raw = shutil.which(launcher_path.name)
    selected_command_path = Path(selected_raw).expanduser() if selected_raw else None
    launcher_parent = launcher_path.parent
    nearest_parent = nearest_existing_parent(launcher_parent)
    parent_on_path = path_contains_directory(os.environ.get("PATH", ""), launcher_parent)
    target_selected = selected_command_path == launcher_path
    if require_path_selected and not target_selected:
        install_blocker = "launcher-target-not-selected-on-path-after-install"

    return CompatLauncherDoctorResult(
        action="doctor",
        install_allowed=install_blocker is None,
        install_blocker=install_blocker,
        launcher_path=launcher_path,
        manifest_path=manifest_path,
        repo_root=repo_root,
        uvx_path=uvx_path,
        pinned_codex_path=pinned_codex_path,
        pinned_codex_version=pinned_codex_version,
        route_prefix=route_prefix,
        adapter_bin=adapter_bin,
        adapter_manifest=adapter_manifest,
        adapter_bridge_dir=adapter_bridge_dir,
        adapter_tool_names=adapter_package.tool_names,
        existing_target_state=existing_state,
        existing_target_managed=existing_managed,
        existing_target_is_symlink=launcher_path.is_symlink(),
        existing_target_realpath=launcher_path.resolve() if existing else None,
        existing_manifest_kind=existing_manifest_kind,
        existing_manifest_pinned_codex_path=existing_manifest_pinned_codex_path,
        selected_command_path=selected_command_path,
        target_selected_on_path=target_selected,
        launcher_parent_on_path=parent_on_path,
        launcher_parent_exists=launcher_parent.exists(),
        nearest_existing_parent=nearest_parent,
        nearest_existing_parent_writable=os.access(nearest_parent, os.W_OK),
        backup_existing_requested=backup_existing,
        force_requested=force,
        would_backup_existing=would_backup_existing,
        backup_path=backup_path,
        rollback_command=rollback_command(repo_root, launcher_path, manifest_path),
        install_command=install_command(
            repo_root,
            launcher_path=launcher_path,
            manifest_path=manifest_path,
            pinned_codex_path=pinned_codex_path,
            route_prefix=route_prefix,
            adapter_bin=adapter_bin,
            adapter_manifest=adapter_manifest,
            adapter_bridge_dir=adapter_bridge_dir,
            backup_existing=backup_existing,
            force=force,
            require_path_selected=require_path_selected,
        ),
    )


def install_launcher(
    *,
    launcher_path: Path,
    manifest_path: Path,
    repo_root: Path,
    uvx_path: Path,
    pinned_codex_path: Path,
    route_prefix: str,
    adapter_bin: Path,
    adapter_manifest: Path,
    adapter_bridge_dir: Path,
    backup_existing: bool,
    force: bool,
    require_path_selected: bool,
    validate: bool,
) -> CompatLauncherInstallResult:
    launcher_path = launcher_path.expanduser()
    manifest_path = manifest_path.expanduser()
    repo_root = repo_root.expanduser().resolve()
    uvx_path = uvx_path.expanduser().resolve()
    pinned_codex_path = pinned_codex_path.expanduser().resolve()
    adapter_bin = adapter_bin.expanduser().resolve()
    adapter_manifest = adapter_manifest.expanduser().resolve()
    adapter_bridge_dir = adapter_bridge_dir.expanduser().resolve()
    if not repo_root.is_dir():
        raise CompatLauncherInstallError(f"Repo root not found: {repo_root}")
    if not is_executable_file(uvx_path):
        raise CompatLauncherInstallError(f"uvx binary is not executable: {uvx_path}")
    if not is_executable_file(pinned_codex_path):
        raise CompatLauncherInstallError(
            f"Pinned Codex binary is not executable: {pinned_codex_path}"
        )
    adapter_package = validate_adapter_package_or_error(adapter_manifest, adapter_bin)
    adapter_bin = adapter_package.adapter_bin
    adapter_manifest = adapter_package.manifest_path
    pinned_codex_version = codex_version(pinned_codex_path)

    launcher_path.parent.mkdir(parents=True, exist_ok=True)
    existing = launcher_path.exists() or launcher_path.is_symlink()
    existing_managed = existing and is_managed_launcher(launcher_path)
    backup_path: Path | None = None
    if existing and not existing_managed:
        if not backup_existing:
            raise CompatLauncherInstallError(
                "Launcher target already exists and is not managed by Omnigent: "
                f"{launcher_path}. Rerun with --backup-existing to preserve and replace it."
            )
        backup_path = backup_path_for(launcher_path)
        launcher_path.rename(backup_path)
    elif existing_managed:
        if not force:
            raise CompatLauncherInstallError(
                f"Launcher target is already managed by Omnigent: {launcher_path}. "
                "Rerun with --force to replace it."
            )
        previous = read_manifest(manifest_path)
        backup_raw = previous.get("backupPath") if isinstance(previous, dict) else None
        backup_path = Path(backup_raw).expanduser() if isinstance(backup_raw, str) else None
        launcher_path.unlink()

    try:
        write_manifest(
            manifest_path,
            launcher_path=launcher_path,
            repo_root=repo_root,
            uvx_path=uvx_path,
            pinned_codex_path=pinned_codex_path,
            pinned_codex_version=pinned_codex_version,
            route_prefix=route_prefix,
            adapter_bin=adapter_bin,
            adapter_manifest=adapter_manifest,
            adapter_bridge_dir=adapter_bridge_dir,
            adapter_tool_names=adapter_package.tool_names,
            backup_path=backup_path,
        )
        write_launcher(
            launcher_path,
            manifest_path=manifest_path,
            repo_root=repo_root,
            uvx_path=uvx_path,
            pinned_codex_path=pinned_codex_path,
            pinned_codex_version=pinned_codex_version,
            route_prefix=route_prefix,
            adapter_bin=adapter_bin,
            adapter_manifest=adapter_manifest,
            adapter_bridge_dir=adapter_bridge_dir,
        )
        if validate:
            validate_launcher(
                launcher_path,
                pinned_codex_path=pinned_codex_path,
                pinned_codex_version=pinned_codex_version,
                require_path_selected=require_path_selected,
            )
    except Exception:
        if launcher_path.exists() or launcher_path.is_symlink():
            launcher_path.unlink()
        if backup_path is not None and (backup_path.exists() or backup_path.is_symlink()):
            backup_path.rename(launcher_path)
        raise

    return CompatLauncherInstallResult(
        action="installed",
        launcher_path=launcher_path,
        manifest_path=manifest_path,
        pinned_codex_path=pinned_codex_path,
        adapter_bin=adapter_bin,
        adapter_manifest=adapter_manifest,
        adapter_bridge_dir=adapter_bridge_dir,
        backup_path=backup_path,
        rollback_command=rollback_command(repo_root, launcher_path, manifest_path),
    )


def validate_launcher(
    launcher_path: Path,
    *,
    pinned_codex_path: Path,
    pinned_codex_version: str,
    require_path_selected: bool,
) -> None:
    probe = subprocess.run(
        [str(launcher_path), PROBE_ARG],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    probe_output = (probe.stdout or "") + (probe.stderr or "")
    if probe.returncode != 0 or PROBE_SENTINEL not in probe_output:
        raise CompatLauncherInstallError(f"Launcher probe failed:\n{probe_output}")
    version = subprocess.run(
        [str(launcher_path), "--version"],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    version_output = (version.stdout or version.stderr).strip()
    if version.returncode != 0 or version_output != pinned_codex_version:
        raise CompatLauncherInstallError(
            "Launcher --version did not delegate to the pinned Codex binary.\n"
            f"expected={pinned_codex_version!r}\nactual={version_output!r}"
        )
    if launcher_path.name == "codex" and shutil.which("codex") == str(launcher_path):
        previous_env = os.environ.pop(OMNIGENT_STOCK_CODEX_PATH_ENV, None)
        try:
            resolved = _find_codex_cli()
        finally:
            if previous_env is not None:
                os.environ[OMNIGENT_STOCK_CODEX_PATH_ENV] = previous_env
        if resolved != str(pinned_codex_path):
            raise CompatLauncherInstallError(
                "Omnigent resolver did not map the compatibility launcher to "
                "the pinned Codex binary.\n"
                f"expected={pinned_codex_path}\nactual={resolved}"
            )
    if require_path_selected:
        selected = shutil.which(launcher_path.name)
        if selected != str(launcher_path):
            raise CompatLauncherInstallError(
                "Launcher is installed but is not the selected command on PATH.\n"
                f"command={launcher_path.name}\nexpected={launcher_path}\nactual={selected}"
            )


def read_manifest(manifest_path: Path) -> dict[str, object]:
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def uninstall_launcher(
    *,
    launcher_path: Path,
    manifest_path: Path,
) -> CompatLauncherInstallResult:
    launcher_path = launcher_path.expanduser()
    manifest_path = manifest_path.expanduser()
    manifest = read_manifest(manifest_path)
    if not is_managed_launcher(launcher_path):
        raise CompatLauncherInstallError(f"Refusing to remove unmanaged launcher: {launcher_path}")
    backup_raw = manifest.get("backupPath")
    backup_path = (
        Path(backup_raw).expanduser() if isinstance(backup_raw, str) and backup_raw else None
    )
    pinned_raw = manifest.get("pinnedCodexPath")
    pinned_codex_path = (
        Path(pinned_raw).expanduser() if isinstance(pinned_raw, str) and pinned_raw else None
    )
    adapter_bin_raw = manifest.get("adapterBin")
    adapter_manifest_raw = manifest.get("adapterManifest")
    adapter_bridge_raw = manifest.get("adapterBridgeDir")
    launcher_path.unlink()
    if backup_path is not None:
        if not (backup_path.exists() or backup_path.is_symlink()):
            raise CompatLauncherInstallError(
                f"Backup path recorded in manifest is missing: {backup_path}"
            )
        backup_path.rename(launcher_path)
    if manifest_path.exists():
        manifest_path.unlink()
    return CompatLauncherInstallResult(
        action="uninstalled",
        launcher_path=launcher_path,
        manifest_path=manifest_path,
        pinned_codex_path=pinned_codex_path,
        adapter_bin=Path(adapter_bin_raw).expanduser()
        if isinstance(adapter_bin_raw, str) and adapter_bin_raw
        else None,
        adapter_manifest=Path(adapter_manifest_raw).expanduser()
        if isinstance(adapter_manifest_raw, str) and adapter_manifest_raw
        else None,
        adapter_bridge_dir=Path(adapter_bridge_raw).expanduser()
        if isinstance(adapter_bridge_raw, str) and adapter_bridge_raw
        else None,
        backup_path=backup_path,
        rollback_command=None,
    )


def rollback_command(repo_root: Path, launcher_path: Path, manifest_path: Path) -> str:
    return (
        "uvx --from "
        f"{shlex.quote(str(repo_root))} python "
        f"{shlex.quote(str(repo_root / 'scripts' / 'install_stock_codex_compat_launcher.py'))} "
        f"--uninstall --launcher-path {shlex.quote(str(launcher_path))} "
        f"--manifest-path {shlex.quote(str(manifest_path))}"
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Install or remove the stock-Codex compatibility launcher."
    )
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--install", action="store_true")
    actions.add_argument("--uninstall", action="store_true")
    actions.add_argument("--print-plan", action="store_true")
    actions.add_argument("--doctor", action="store_true")
    actions.add_argument("--install-adapter-package", action="store_true")
    parser.add_argument("--launcher-path", type=Path, default=DEFAULT_LAUNCHER_PATH)
    parser.add_argument("--manifest-path", type=Path, default=DEFAULT_MANIFEST_PATH)
    parser.add_argument("--pinned-codex-path", type=Path, default=None)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--uvx-path", type=Path, default=None)
    parser.add_argument("--route-prefix", default=DEFAULT_ROUTE_PREFIX)
    parser.add_argument("--adapter-bin", type=Path, default=None)
    parser.add_argument("--adapter-manifest", type=Path, default=None)
    parser.add_argument("--adapter-package-dir", type=Path, default=DEFAULT_ADAPTER_PACKAGE_DIR)
    parser.add_argument("--adapter-bridge-dir", type=Path, default=DEFAULT_ADAPTER_BRIDGE_DIR)
    parser.add_argument("--backup-existing", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--no-validate", action="store_true")
    parser.add_argument("--require-path-selected", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def result_dict(
    result: (
        CompatLauncherInstallResult
        | CompatLauncherDoctorResult
        | CompatAdapterPackageInstallResult
    ),
) -> dict[str, object]:
    if isinstance(result, CompatAdapterPackageInstallResult):
        return {
            "action": result.action,
            "adapterPackageDir": str(result.adapter_package_dir),
            "adapterBin": str(result.adapter_bin),
            "adapterManifest": str(result.adapter_manifest),
            "adapterToolNames": list(result.adapter_tool_names),
            "mutatesFilesystem": result.mutates_filesystem,
        }
    base: dict[str, object] = {
        "action": result.action,
        "launcherPath": str(result.launcher_path),
        "manifestPath": str(result.manifest_path),
        "pinnedCodexPath": str(result.pinned_codex_path)
        if result.pinned_codex_path is not None
        else None,
        "adapterBin": str(result.adapter_bin) if result.adapter_bin is not None else None,
        "adapterManifest": (
            str(result.adapter_manifest) if result.adapter_manifest is not None else None
        ),
        "adapterBridgeDir": (
            str(result.adapter_bridge_dir) if result.adapter_bridge_dir is not None else None
        ),
        "backupPath": str(result.backup_path) if result.backup_path is not None else None,
        "rollbackCommand": result.rollback_command,
    }
    if isinstance(result, CompatLauncherDoctorResult):
        base.update(
            {
                "installAllowed": result.install_allowed,
                "installBlocker": result.install_blocker,
                "repoRoot": str(result.repo_root),
                "uvxPath": str(result.uvx_path),
                "pinnedCodexVersion": result.pinned_codex_version,
                "routePrefix": result.route_prefix,
                "adapterToolNames": list(result.adapter_tool_names),
                "existingTargetState": result.existing_target_state,
                "existingTargetManaged": result.existing_target_managed,
                "existingTargetIsSymlink": result.existing_target_is_symlink,
                "existingTargetRealpath": str(result.existing_target_realpath)
                if result.existing_target_realpath is not None
                else None,
                "existingManifestKind": result.existing_manifest_kind,
                "existingManifestPinnedCodexPath": (
                    str(result.existing_manifest_pinned_codex_path)
                    if result.existing_manifest_pinned_codex_path is not None
                    else None
                ),
                "selectedCommandPath": str(result.selected_command_path)
                if result.selected_command_path is not None
                else None,
                "targetSelectedOnPath": result.target_selected_on_path,
                "launcherParentOnPath": result.launcher_parent_on_path,
                "launcherParentExists": result.launcher_parent_exists,
                "nearestExistingParent": str(result.nearest_existing_parent),
                "nearestExistingParentWritable": result.nearest_existing_parent_writable,
                "backupExistingRequested": result.backup_existing_requested,
                "forceRequested": result.force_requested,
                "wouldBackupExisting": result.would_backup_existing,
                "installCommand": result.install_command,
                "mutatesFilesystem": result.mutates_filesystem,
            }
        )
    return base


def print_result(
    result: (
        CompatLauncherInstallResult
        | CompatLauncherDoctorResult
        | CompatAdapterPackageInstallResult
    ),
    *,
    as_json: bool,
) -> None:
    if as_json:
        print(json.dumps(result_dict(result), indent=2, sort_keys=True))
        return
    if isinstance(result, CompatAdapterPackageInstallResult):
        print(f"compat_adapter_package_action={result.action}")
        print(f"compat_adapter_package_dir={result.adapter_package_dir}")
        print(f"compat_adapter_package_bin={result.adapter_bin}")
        print(f"compat_adapter_package_manifest={result.adapter_manifest}")
        print(f"compat_adapter_package_tools={','.join(result.adapter_tool_names)}")
        print(f"compat_adapter_package_mutates_filesystem={result.mutates_filesystem}")
        return
    print(f"compat_launcher_action={result.action}")
    if isinstance(result, CompatLauncherDoctorResult):
        print(f"compat_launcher_install_allowed={result.install_allowed}")
        if result.install_blocker is not None:
            print(f"compat_launcher_install_blocker={result.install_blocker}")
        print(f"compat_launcher_existing_target_state={result.existing_target_state}")
        print(f"compat_launcher_existing_target_managed={result.existing_target_managed}")
        print(f"compat_launcher_target_selected_on_path={result.target_selected_on_path}")
        print(f"compat_launcher_launcher_parent_on_path={result.launcher_parent_on_path}")
        print(
            "compat_launcher_nearest_existing_parent_writable="
            f"{result.nearest_existing_parent_writable}"
        )
        print(f"compat_launcher_mutates_filesystem={result.mutates_filesystem}")
    print(f"compat_launcher_path={result.launcher_path}")
    print(f"compat_launcher_manifest={result.manifest_path}")
    if result.pinned_codex_path is not None:
        print(f"compat_launcher_pinned_codex_path={result.pinned_codex_path}")
    if isinstance(result, CompatLauncherDoctorResult):
        print(f"compat_launcher_pinned_codex_version={result.pinned_codex_version}")
        print(f"compat_launcher_uvx_path={result.uvx_path}")
        print(f"compat_launcher_adapter_tools={','.join(result.adapter_tool_names)}")
    if result.adapter_bin is not None:
        print(f"compat_launcher_adapter_bin={result.adapter_bin}")
    if result.adapter_manifest is not None:
        print(f"compat_launcher_adapter_manifest={result.adapter_manifest}")
    if result.adapter_bridge_dir is not None:
        print(f"compat_launcher_adapter_bridge_dir={result.adapter_bridge_dir}")
    if result.backup_path is not None:
        print(f"compat_launcher_backup_path={result.backup_path}")
    if result.rollback_command:
        print(f"compat_launcher_rollback_command={result.rollback_command}")
    if isinstance(result, CompatLauncherDoctorResult):
        print(f"compat_launcher_install_command={result.install_command}")


def _require_install_path(value: Path | None, name: str) -> Path:
    if value is None:
        raise CompatLauncherInstallError(f"{name} is required for install or plan.")
    return value


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.install_adapter_package:
            result = materialize_default_adapter_package(
                args.adapter_package_dir,
                force=args.force,
            )
        elif args.uninstall:
            result = uninstall_launcher(
                launcher_path=args.launcher_path,
                manifest_path=args.manifest_path,
            )
        elif args.doctor:
            uvx_raw = args.uvx_path or shutil.which("uvx")
            if not uvx_raw:
                print("error: could not find uvx on PATH; pass --uvx-path", file=sys.stderr)
                return 1
            uvx_path = Path(uvx_raw).expanduser()
            adapter_bin, adapter_manifest = resolve_adapter_paths(
                adapter_bin=args.adapter_bin,
                adapter_manifest=args.adapter_manifest,
                adapter_package_dir=args.adapter_package_dir,
            )
            result = doctor_launcher(
                launcher_path=args.launcher_path,
                manifest_path=args.manifest_path,
                repo_root=args.repo_root,
                uvx_path=uvx_path,
                pinned_codex_path=_require_install_path(
                    args.pinned_codex_path,
                    "--pinned-codex-path",
                ),
                route_prefix=args.route_prefix,
                adapter_bin=adapter_bin,
                adapter_manifest=adapter_manifest,
                adapter_bridge_dir=args.adapter_bridge_dir,
                backup_existing=args.backup_existing,
                force=args.force,
                require_path_selected=args.require_path_selected,
            )
        elif args.install:
            uvx_raw = args.uvx_path or shutil.which("uvx")
            if not uvx_raw:
                print("error: could not find uvx on PATH; pass --uvx-path", file=sys.stderr)
                return 1
            uvx_path = Path(uvx_raw).expanduser()
            adapter_bin, adapter_manifest = resolve_adapter_paths(
                adapter_bin=args.adapter_bin,
                adapter_manifest=args.adapter_manifest,
                adapter_package_dir=args.adapter_package_dir,
            )
            result = install_launcher(
                launcher_path=args.launcher_path,
                manifest_path=args.manifest_path,
                repo_root=args.repo_root,
                uvx_path=uvx_path,
                pinned_codex_path=_require_install_path(
                    args.pinned_codex_path,
                    "--pinned-codex-path",
                ),
                route_prefix=args.route_prefix,
                adapter_bin=adapter_bin,
                adapter_manifest=adapter_manifest,
                adapter_bridge_dir=args.adapter_bridge_dir,
                backup_existing=args.backup_existing,
                force=args.force,
                require_path_selected=args.require_path_selected,
                validate=not args.no_validate,
            )
        else:
            pinned_codex_path = (
                args.pinned_codex_path.expanduser() if args.pinned_codex_path else None
            )
            adapter_bin, adapter_manifest = resolve_adapter_paths(
                adapter_bin=args.adapter_bin,
                adapter_manifest=args.adapter_manifest,
                adapter_package_dir=args.adapter_package_dir,
            )
            result = CompatLauncherInstallResult(
                action="plan",
                launcher_path=args.launcher_path.expanduser(),
                manifest_path=args.manifest_path.expanduser(),
                pinned_codex_path=pinned_codex_path,
                adapter_bin=adapter_bin,
                adapter_manifest=adapter_manifest,
                adapter_bridge_dir=args.adapter_bridge_dir.expanduser(),
                backup_path=None,
                rollback_command=rollback_command(
                    args.repo_root.expanduser(), args.launcher_path, args.manifest_path
                ),
            )
        print_result(result, as_json=args.json)
    except CompatLauncherInstallError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
