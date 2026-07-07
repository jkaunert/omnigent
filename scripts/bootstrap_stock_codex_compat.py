#!/usr/bin/env python3
"""Bootstrap the per-user stock-Codex compatibility runtime.

This script is the second stage of ``bootstrap_stock_codex_compat.sh``. The
shell stage copies the machine-installed runtime into a user-writable runtime
root, then invokes this script through ``uvx --from <staged-runtime>`` so source
build metadata is written under the user's profile rather than under
``/Library``.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

DEFAULT_ROUTE_PREFIX = (
    "Routing: orchestrator-led\n\n"
    "Activated skills\n"
    "- `apple-appdev-workflow:apple-app-orchestrator`"
)
DEFAULT_USER_RUNTIME_ROOT = (
    Path.home() / ".local" / "omnigent" / "stock-codex-compat" / "runtime"
)
DEFAULT_CACHE_ROOT = Path.home() / ".local" / "omnigent" / "codex-stock"
DEFAULT_LAUNCHER_PATH = Path.home() / ".local" / "bin" / "omnigent-stock-codex-compat"
DEFAULT_MANIFEST_PATH = (
    Path.home() / ".local" / "omnigent" / "launchers" / "stock-codex-compat.json"
)
DEFAULT_ADAPTER_PACKAGE_DIR = (
    Path.home() / ".local" / "omnigent" / "stock-codex-compat" / "adapter-package"
)
DEFAULT_ADAPTER_BRIDGE_DIR = (
    Path.home() / ".local" / "omnigent" / "stock-codex-compat" / "adapter-bridge"
)


class BootstrapError(RuntimeError):
    """The per-user compatibility bootstrap failed."""


def _run_json(command: list[str], *, timeout: float = 600.0) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if completed.returncode != 0:
        raise BootstrapError(
            "Command failed.\n"
            f"command={shlex.join(command)}\n"
            f"exit={completed.returncode}\n"
            f"stdout={completed.stdout}\n"
            f"stderr={completed.stderr}"
        )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise BootstrapError(
            "Command did not emit JSON.\n"
            f"command={shlex.join(command)}\n"
            f"stdout={completed.stdout}\n"
            f"stderr={completed.stderr}"
        ) from exc
    if not isinstance(payload, dict):
        raise BootstrapError(f"Command JSON was not an object: {payload!r}")
    return payload


def _resolve_uvx(path: Path | None) -> Path:
    raw = path or shutil.which("uvx")
    if raw is None:
        raise BootstrapError("Could not find uvx on PATH; pass --uvx-path")
    uvx_path = Path(raw).expanduser()
    if not uvx_path.is_file() or not os.access(uvx_path, os.X_OK):
        raise BootstrapError(f"uvx is not executable: {uvx_path}")
    return uvx_path.resolve()


def _require_file(path: Path, label: str) -> Path:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise BootstrapError(f"{label} missing: {resolved}")
    return resolved


def _require_runtime(staged_runtime_root: Path) -> Path:
    staged_runtime_root = staged_runtime_root.expanduser().resolve()
    required = (
        (staged_runtime_root / "pyproject.toml", "staged runtime pyproject"),
        (
            staged_runtime_root / "scripts" / "provision_stock_codex.py",
            "stock Codex provisioner",
        ),
        (
            staged_runtime_root / "scripts" / "install_stock_codex_compat_launcher.py",
            "compat launcher installer",
        ),
        (
            staged_runtime_root / "omnigent" / "stock_codex_compat_wrapper.py",
            "stock Codex wrapper",
        ),
    )
    for path, label in required:
        _require_file(path, label)
    return staged_runtime_root


def bootstrap(args: argparse.Namespace) -> dict[str, Any]:
    staged_runtime_root = _require_runtime(
        args.staged_runtime_root or args.user_runtime_root or DEFAULT_USER_RUNTIME_ROOT
    )
    uvx_path = _resolve_uvx(args.uvx_path)
    cache_root = args.cache_root.expanduser().resolve()
    launcher_path = args.launcher_path.expanduser()
    manifest_path = args.manifest_path.expanduser()
    adapter_package_dir = args.adapter_package_dir.expanduser()
    adapter_bridge_dir = args.adapter_bridge_dir.expanduser()
    channel_manifest = _require_file(args.channel_manifest, "channel manifest")
    provisioner = staged_runtime_root / "scripts" / "provision_stock_codex.py"
    installer = staged_runtime_root / "scripts" / "install_stock_codex_compat_launcher.py"

    provision_command = [
        str(uvx_path),
        "--from",
        str(staged_runtime_root),
        "python",
        str(provisioner),
        "--cache-root",
        str(cache_root),
        "--channel-manifest",
        str(channel_manifest),
        "--expected-sha256",
        args.expected_sha256,
        "--json",
    ]
    if args.allow_remote_channel_download:
        provision_command.append("--allow-remote-channel-download")
    provision = _run_json(provision_command, timeout=args.provision_timeout)
    codex_raw = provision.get("codexPath")
    if not isinstance(codex_raw, str) or not codex_raw:
        raise BootstrapError("stock Codex provisioner JSON did not contain codexPath")
    provisioned_codex = Path(codex_raw).expanduser()
    if not provisioned_codex.is_file() or not os.access(provisioned_codex, os.X_OK):
        raise BootstrapError(f"provisioned stock Codex is not executable: {provisioned_codex}")

    adapter_package = _run_json(
        [
            str(uvx_path),
            "--from",
            str(staged_runtime_root),
            "python",
            str(installer),
            "--install-adapter-package",
            "--adapter-package-dir",
            str(adapter_package_dir),
            "--json",
        ],
        timeout=args.bootstrap_timeout,
    )

    install_command = [
        str(uvx_path),
        "--from",
        str(staged_runtime_root),
        "python",
        str(installer),
        "--install",
        "--launcher-path",
        str(launcher_path),
        "--manifest-path",
        str(manifest_path),
        "--pinned-codex-path",
        str(provisioned_codex),
        "--repo-root",
        str(staged_runtime_root),
        "--uvx-path",
        str(uvx_path),
        "--route-prefix",
        args.route_prefix,
        "--adapter-package-dir",
        str(adapter_package_dir),
        "--adapter-bridge-dir",
        str(adapter_bridge_dir),
        "--json",
    ]
    if args.force:
        install_command.append("--force")
    if args.backup_existing:
        install_command.append("--backup-existing")
    if args.require_path_selected:
        install_command.append("--require-path-selected")
    install = _run_json(install_command, timeout=args.bootstrap_timeout)

    doctor_command = [
        str(uvx_path),
        "--from",
        str(staged_runtime_root),
        "python",
        str(installer),
        "--doctor",
        "--launcher-path",
        str(launcher_path),
        "--manifest-path",
        str(manifest_path),
        "--pinned-codex-path",
        str(provisioned_codex),
        "--repo-root",
        str(staged_runtime_root),
        "--uvx-path",
        str(uvx_path),
        "--route-prefix",
        args.route_prefix,
        "--adapter-package-dir",
        str(adapter_package_dir),
        "--adapter-bridge-dir",
        str(adapter_bridge_dir),
        "--force",
        "--json",
    ]
    if args.require_path_selected:
        doctor_command.append("--require-path-selected")
    doctor = _run_json(doctor_command, timeout=args.bootstrap_timeout)

    return {
        "action": "bootstrapped",
        "sourceRuntimeRoot": str(args.source_runtime_root)
        if args.source_runtime_root is not None
        else None,
        "stagedRuntimeRoot": str(staged_runtime_root),
        "cacheRoot": str(cache_root),
        "provisionedCodexPath": str(provisioned_codex),
        "launcherPath": str(launcher_path),
        "manifestPath": str(manifest_path),
        "adapterPackageDir": str(adapter_package_dir),
        "adapterBridgeDir": str(adapter_bridge_dir),
        "uvxPath": str(uvx_path),
        "provision": provision,
        "adapterPackage": adapter_package,
        "install": install,
        "doctor": doctor,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Bootstrap the per-user stock-Codex compatibility launcher."
    )
    parser.add_argument("--source-runtime-root", type=Path, default=None)
    parser.add_argument("--user-runtime-root", type=Path, default=DEFAULT_USER_RUNTIME_ROOT)
    parser.add_argument("--staged-runtime-root", type=Path, default=None)
    parser.add_argument("--no-stage-refresh", action="store_true")
    parser.add_argument("--uvx-path", type=Path, default=None)
    parser.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE_ROOT)
    parser.add_argument("--channel-manifest", type=Path, required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--allow-remote-channel-download", action="store_true")
    parser.add_argument("--launcher-path", type=Path, default=DEFAULT_LAUNCHER_PATH)
    parser.add_argument("--manifest-path", type=Path, default=DEFAULT_MANIFEST_PATH)
    parser.add_argument("--adapter-package-dir", type=Path, default=DEFAULT_ADAPTER_PACKAGE_DIR)
    parser.add_argument("--adapter-bridge-dir", type=Path, default=DEFAULT_ADAPTER_BRIDGE_DIR)
    parser.add_argument("--route-prefix", default=DEFAULT_ROUTE_PREFIX)
    parser.add_argument("--backup-existing", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--require-path-selected", action="store_true")
    parser.add_argument("--provision-timeout", type=float, default=900.0)
    parser.add_argument("--bootstrap-timeout", type=float, default=900.0)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = bootstrap(args)
    except BootstrapError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print("omnigent_stock_codex_compat_bootstrap_status=bootstrapped")
        print(f"omnigent_stock_codex_compat_bootstrap_runtime={result['stagedRuntimeRoot']}")
        print(
            "omnigent_stock_codex_compat_bootstrap_codex="
            f"{result['provisionedCodexPath']}"
        )
        print(f"omnigent_stock_codex_compat_bootstrap_launcher={result['launcherPath']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
