#!/usr/bin/env python3
"""Install or remove the persistent Omnigent ``codex`` launcher shim."""

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

from omnigent.inner.codex_executor import (
    OMNIGENT_CODEX_LAUNCHER_MANIFEST_PREFIX,
    OMNIGENT_MANAGED_CODEX_LAUNCHER_MARKER,
    OMNIGENT_STOCK_CODEX_PATH_ENV,
    _find_codex_cli,
)

PROBE_ARG = "--omnigent-launcher-probe"
PROBE_SENTINEL = "OMNIGENT_CODEX_PERSISTENT_LAUNCHER_OK"
MANIFEST_KIND = "omnigent-codex-launcher"
DEFAULT_MANIFEST_PATH = Path.home() / ".local" / "omnigent" / "launchers" / "codex.json"


@dataclass(frozen=True)
class LauncherInstallResult:
    """Result of a persistent launcher install or removal."""

    action: str
    launcher_path: Path
    manifest_path: Path
    pinned_codex_path: Path | None
    backup_path: Path | None
    rollback_command: str | None


class LauncherInstallError(RuntimeError):
    """The persistent Omnigent launcher could not be installed or removed."""


def _default_launcher_path() -> Path:
    raw = shutil.which("codex")
    return Path(raw).expanduser() if raw else Path.home() / ".local" / "bin" / "codex"


def _default_pinned_codex_path() -> Path | None:
    configured = os.environ.get(OMNIGENT_STOCK_CODEX_PATH_ENV, "").strip()
    if configured:
        return Path(configured).expanduser()
    cache_root = Path.home() / ".local" / "omnigent" / "codex-stock"
    if not cache_root.is_dir():
        return None
    candidates = sorted(
        path / "codex" for path in cache_root.iterdir() if (path / "codex").is_file()
    )
    return candidates[-1] if candidates else None


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
        raise LauncherInstallError(f"Could not run {path} --version: {exc}") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise LauncherInstallError(
            f"{path} --version exited {completed.returncode}: {detail or 'no output'}"
        )
    version = (completed.stdout or completed.stderr).strip()
    if not version:
        raise LauncherInstallError(f"{path} --version produced no output")
    return version


def is_executable_file(path: Path) -> bool:
    return path.is_file() and os.access(path, os.X_OK)


def is_managed_launcher(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        return OMNIGENT_MANAGED_CODEX_LAUNCHER_MARKER in path.read_text(
            encoding="utf-8",
            errors="ignore",
        )
    except OSError:
        return False


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


def write_launcher(
    launcher_path: Path,
    *,
    manifest_path: Path,
    repo_root: Path,
    uvx_path: Path,
    pinned_codex_path: Path,
    pinned_codex_version: str,
) -> None:
    quoted_pinned_codex_path = shlex.quote(str(pinned_codex_path))
    quoted_pinned_codex_version = shlex.quote(pinned_codex_version)
    quoted_uvx_path = shlex.quote(str(uvx_path))
    quoted_repo_root = shlex.quote(str(repo_root))
    quoted_probe_arg = shlex.quote(PROBE_ARG)
    quoted_probe_sentinel = shlex.quote(PROBE_SENTINEL)
    launcher_path.write_text(
        f"""#!/bin/sh
# {OMNIGENT_MANAGED_CODEX_LAUNCHER_MARKER}
{OMNIGENT_CODEX_LAUNCHER_MANIFEST_PREFIX} {manifest_path}
set -eu

PINNED_CODEX_PATH={quoted_pinned_codex_path}
PINNED_CODEX_VERSION={quoted_pinned_codex_version}
UVX_PATH={quoted_uvx_path}
REPO_ROOT={quoted_repo_root}
PROBE_ARG={quoted_probe_arg}
PROBE_SENTINEL={quoted_probe_sentinel}

if [ "${{1:-}}" = "$PROBE_ARG" ]; then
  printf '%s\\n' "$PROBE_SENTINEL"
  printf 'launcher_path=%s\\n' "$0"
  printf 'pinned_env=%s=%s\\n' "{OMNIGENT_STOCK_CODEX_PATH_ENV}" "$PINNED_CODEX_PATH"
  printf 'pinned_codex_version=%s\\n' "$PINNED_CODEX_VERSION"
  printf 'delegate=%s --from %s omnigent codex\\n' "$UVX_PATH" "$REPO_ROOT"
  exit 0
fi

if [ "${{1:-}}" = "--version" ]; then
  exec "$PINNED_CODEX_PATH" --version
fi

if [ ! -x "$PINNED_CODEX_PATH" ]; then
  printf 'omnigent_launcher_error=pinned codex missing: %s\\n' "$PINNED_CODEX_PATH" >&2
  exit 127
fi
if [ ! -x "$UVX_PATH" ]; then
  printf 'omnigent_launcher_error=uvx missing: %s\\n' "$UVX_PATH" >&2
  exit 127
fi

{OMNIGENT_STOCK_CODEX_PATH_ENV}="$PINNED_CODEX_PATH"
export {OMNIGENT_STOCK_CODEX_PATH_ENV}
exec "$UVX_PATH" --from "$REPO_ROOT" omnigent codex "$@"
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
        "pinnedCodexPath": str(pinned_codex_path),
        "pinnedCodexVersion": pinned_codex_version,
        "backupPath": str(backup_path) if backup_path is not None else None,
        "installedAt": datetime.now(timezone.utc).isoformat(),
        "env": {OMNIGENT_STOCK_CODEX_PATH_ENV: str(pinned_codex_path)},
        "probeArg": PROBE_ARG,
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def install_launcher(
    *,
    launcher_path: Path,
    manifest_path: Path,
    repo_root: Path,
    uvx_path: Path,
    pinned_codex_path: Path,
    backup_existing: bool,
    force: bool,
    require_path_selected: bool,
    validate: bool,
) -> LauncherInstallResult:
    launcher_path = launcher_path.expanduser()
    manifest_path = manifest_path.expanduser()
    repo_root = repo_root.expanduser().resolve()
    uvx_path = uvx_path.expanduser().resolve()
    pinned_codex_path = pinned_codex_path.expanduser().resolve()
    if not repo_root.is_dir():
        raise LauncherInstallError(f"Repo root not found: {repo_root}")
    if not is_executable_file(uvx_path):
        raise LauncherInstallError(f"uvx binary is not executable: {uvx_path}")
    if not is_executable_file(pinned_codex_path):
        raise LauncherInstallError(f"Pinned Codex binary is not executable: {pinned_codex_path}")
    pinned_codex_version = codex_version(pinned_codex_path)

    launcher_path.parent.mkdir(parents=True, exist_ok=True)
    existing = launcher_path.exists() or launcher_path.is_symlink()
    existing_managed = existing and is_managed_launcher(launcher_path)
    backup_path: Path | None = None
    if existing and not existing_managed:
        if not backup_existing:
            raise LauncherInstallError(
                f"Launcher target already exists and is not managed by Omnigent: {launcher_path}. "
                "Rerun with --backup-existing to preserve and replace it."
            )
        backup_path = backup_path_for(launcher_path)
        launcher_path.rename(backup_path)
    elif existing_managed:
        if not force:
            raise LauncherInstallError(
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
            backup_path=backup_path,
        )
        write_launcher(
            launcher_path,
            manifest_path=manifest_path,
            repo_root=repo_root,
            uvx_path=uvx_path,
            pinned_codex_path=pinned_codex_path,
            pinned_codex_version=pinned_codex_version,
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

    return LauncherInstallResult(
        action="installed",
        launcher_path=launcher_path,
        manifest_path=manifest_path,
        pinned_codex_path=pinned_codex_path,
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
        raise LauncherInstallError(f"Launcher probe failed:\n{probe_output}")
    version = subprocess.run(
        [str(launcher_path), "--version"],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    version_output = (version.stdout or version.stderr).strip()
    if version.returncode != 0 or version_output != pinned_codex_version:
        raise LauncherInstallError(
            "Launcher --version did not delegate to the pinned Codex binary.\n"
            f"expected={pinned_codex_version!r}\nactual={version_output!r}"
        )
    selected = shutil.which("codex")
    if selected == str(launcher_path):
        previous_env = os.environ.pop(OMNIGENT_STOCK_CODEX_PATH_ENV, None)
        try:
            resolved = _find_codex_cli()
        finally:
            if previous_env is not None:
                os.environ[OMNIGENT_STOCK_CODEX_PATH_ENV] = previous_env
        if resolved != str(pinned_codex_path):
            raise LauncherInstallError(
                "Omnigent resolver did not map the managed launcher to the pinned Codex binary.\n"
                f"expected={pinned_codex_path}\nactual={resolved}"
            )
    if require_path_selected:
        if selected != str(launcher_path):
            raise LauncherInstallError(
                "Launcher is installed but is not the selected codex on PATH.\n"
                f"expected={launcher_path}\nactual={selected}"
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
) -> LauncherInstallResult:
    launcher_path = launcher_path.expanduser()
    manifest_path = manifest_path.expanduser()
    manifest = read_manifest(manifest_path)
    if not is_managed_launcher(launcher_path):
        raise LauncherInstallError(f"Refusing to remove unmanaged launcher: {launcher_path}")
    backup_raw = manifest.get("backupPath")
    backup_path = (
        Path(backup_raw).expanduser() if isinstance(backup_raw, str) and backup_raw else None
    )
    pinned_raw = manifest.get("pinnedCodexPath")
    pinned_codex_path = (
        Path(pinned_raw).expanduser() if isinstance(pinned_raw, str) and pinned_raw else None
    )
    launcher_path.unlink()
    if backup_path is not None:
        if not (backup_path.exists() or backup_path.is_symlink()):
            raise LauncherInstallError(
                f"Backup path recorded in manifest is missing: {backup_path}"
            )
        backup_path.rename(launcher_path)
    if manifest_path.exists():
        manifest_path.unlink()
    return LauncherInstallResult(
        action="uninstalled",
        launcher_path=launcher_path,
        manifest_path=manifest_path,
        pinned_codex_path=pinned_codex_path,
        backup_path=backup_path,
        rollback_command=None,
    )


def rollback_command(repo_root: Path, launcher_path: Path, manifest_path: Path) -> str:
    return (
        "uvx --from "
        f"{shlex.quote(str(repo_root))} python "
        f"{shlex.quote(str(repo_root / 'scripts' / 'install_omnigent_codex_launcher.py'))} "
        f"--uninstall --launcher-path {shlex.quote(str(launcher_path))} "
        f"--manifest-path {shlex.quote(str(manifest_path))}"
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Install or remove the persistent Omnigent codex launcher."
    )
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--install", action="store_true")
    actions.add_argument("--uninstall", action="store_true")
    actions.add_argument("--print-plan", action="store_true")
    parser.add_argument("--launcher-path", type=Path, default=None)
    parser.add_argument("--manifest-path", type=Path, default=DEFAULT_MANIFEST_PATH)
    parser.add_argument("--pinned-codex-path", type=Path, default=None)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--uvx-path", type=Path, default=None)
    parser.add_argument("--backup-existing", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--no-validate", action="store_true")
    parser.add_argument("--require-path-selected", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def result_dict(result: LauncherInstallResult) -> dict[str, object]:
    return {
        "action": result.action,
        "launcherPath": str(result.launcher_path),
        "manifestPath": str(result.manifest_path),
        "pinnedCodexPath": str(result.pinned_codex_path)
        if result.pinned_codex_path is not None
        else None,
        "backupPath": str(result.backup_path) if result.backup_path is not None else None,
        "rollbackCommand": result.rollback_command,
    }


def print_result(result: LauncherInstallResult, *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result_dict(result), indent=2, sort_keys=True))
        return
    print(f"launcher_action={result.action}")
    print(f"launcher_path={result.launcher_path}")
    print(f"launcher_manifest={result.manifest_path}")
    if result.pinned_codex_path is not None:
        print(f"launcher_pinned_codex_path={result.pinned_codex_path}")
    if result.backup_path is not None:
        print(f"launcher_backup_path={result.backup_path}")
    if result.rollback_command:
        print(f"launcher_rollback_command={result.rollback_command}")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    launcher_path = (args.launcher_path or _default_launcher_path()).expanduser()
    uvx_raw = args.uvx_path or shutil.which("uvx")
    if not uvx_raw:
        print("error: could not find uvx on PATH; pass --uvx-path", file=sys.stderr)
        return 1
    uvx_path = Path(uvx_raw).expanduser()
    pinned_codex_path = args.pinned_codex_path or _default_pinned_codex_path()
    if pinned_codex_path is None and not args.uninstall:
        print(
            f"error: could not find pinned Codex; pass --pinned-codex-path or set "
            f"{OMNIGENT_STOCK_CODEX_PATH_ENV}",
            file=sys.stderr,
        )
        return 1
    try:
        if args.uninstall:
            result = uninstall_launcher(
                launcher_path=launcher_path,
                manifest_path=args.manifest_path,
            )
        elif args.install:
            assert pinned_codex_path is not None
            result = install_launcher(
                launcher_path=launcher_path,
                manifest_path=args.manifest_path,
                repo_root=args.repo_root,
                uvx_path=uvx_path,
                pinned_codex_path=pinned_codex_path,
                backup_existing=args.backup_existing,
                force=args.force,
                require_path_selected=args.require_path_selected,
                validate=not args.no_validate,
            )
        else:
            result = LauncherInstallResult(
                action="plan",
                launcher_path=launcher_path,
                manifest_path=args.manifest_path.expanduser(),
                pinned_codex_path=pinned_codex_path.expanduser()
                if pinned_codex_path is not None
                else None,
                backup_path=None,
                rollback_command=rollback_command(
                    args.repo_root.expanduser(), launcher_path, args.manifest_path
                ),
            )
        print_result(result, as_json=args.json)
    except LauncherInstallError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
