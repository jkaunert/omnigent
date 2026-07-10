#!/usr/bin/env python3
"""Prove public GitHub package acquisition and clean-Mac installation."""

from __future__ import annotations

import argparse
import importlib.util
import shlex
import shutil
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import ModuleType

REMOTE_SCRIPT = r"""#!/bin/bash
set -euo pipefail

package_url="$1"
expected_sha256="$2"
expected_identifier="$3"
expected_version="$4"
install_prefix="/Library/Application Support/Omnigent/stock-codex-compat"
launcher="$HOME/.local/bin/omnigent-stock-codex-compat"
launcher_manifest="$HOME/.local/omnigent/launchers/stock-codex-compat.json"
adapter_root="$HOME/.local/omnigent/stock-codex-compat/adapter-package"
stock_cache="$HOME/.local/omnigent/codex-stock"
launch_agent="$HOME/Library/LaunchAgents/ai.omnigent.stock-codex-compat.update.plist"
clean_marker="$HOME/.omnigent-stock-codex-compat-clean-user-ok"

fail() {
  printf 'published_release_remote_error=%s\n' "$1" >&2
  exit 1
}

[ -f "$clean_marker" ] || fail "disposable marker is missing"
command -v curl >/dev/null 2>&1 || fail "curl is missing"
command -v shasum >/dev/null 2>&1 || fail "shasum is missing"
command -v pkgutil >/dev/null 2>&1 || fail "pkgutil is missing"
command -v xcrun >/dev/null 2>&1 || fail "xcrun is missing"
command -v spctl >/dev/null 2>&1 || fail "spctl is missing"
sudo -n true >/dev/null 2>&1 || fail "noninteractive sudo is unavailable"

assert_clean() {
  pkgutil --pkg-info "$expected_identifier" >/dev/null 2>&1 && \
    fail "package receipt already exists"
  [ ! -e "$install_prefix" ] || fail "package payload already exists"
  [ ! -e "$launcher" ] || fail "launcher already exists"
  [ ! -e "$launcher_manifest" ] || fail "launcher manifest already exists"
  [ ! -e "$adapter_root" ] || fail "adapter root already exists"
  [ ! -e "$stock_cache" ] || fail "stock cache already exists"
  [ ! -e "$launch_agent" ] || fail "LaunchAgent already exists"
}

assert_clean
work_dir="$(mktemp -d /tmp/omnigent-published-release.XXXXXX)"
package_path="$work_dir/omnigent-stock-codex-compat.pkg"
cleanup_allowed=false

cleanup() {
  if [ "$cleanup_allowed" = true ]; then
    sudo -n rm -rf "$install_prefix" >/dev/null 2>&1 || true
    if pkgutil --pkg-info "$expected_identifier" >/dev/null 2>&1; then
      sudo -n /usr/sbin/pkgutil --forget "$expected_identifier" >/dev/null 2>&1 || true
    fi
  fi
  rm -rf "$work_dir"
}
trap cleanup EXIT

curl --fail --location --silent --show-error \
  --proto '=https' --tlsv1.2 \
  --output "$package_path" "$package_url"
actual_sha256="$(shasum -a 256 "$package_path" | awk '{print $1}')"
[ "$actual_sha256" = "$expected_sha256" ] || fail "downloaded package SHA-256 mismatch"

signature_output="$(pkgutil --check-signature "$package_path" 2>&1)"
printf '%s\n' "$signature_output" | grep -F 'Developer ID Installer:' >/dev/null || \
  fail "Developer ID Installer signature is missing"
xcrun stapler validate "$package_path" >/dev/null 2>&1 || fail "staple validation failed"
gatekeeper_output="$(spctl -a -vv -t install "$package_path" 2>&1)"
printf '%s\n' "$gatekeeper_output" | grep -F 'source=Notarized Developer ID' >/dev/null || \
  fail "Gatekeeper did not accept a notarized Developer ID package"

cleanup_allowed=true
sudo -n /usr/sbin/installer -pkg "$package_path" -target / >/dev/null
receipt_output="$(pkgutil --pkg-info "$expected_identifier")"
receipt_version="$(printf '%s\n' "$receipt_output" | awk -F': ' '$1 == "version" {print $2}')"
[ "$receipt_version" = "$expected_version" ] || fail "installed receipt version mismatch"
[ -f "$install_prefix/pkg-manifest.json" ] || fail "installed package manifest is missing"
[ -f "$install_prefix/runtime/scripts/bootstrap_stock_codex_compat.sh" ] || \
  fail "installed bootstrapper is missing"
manifest_version="$(plutil -extract packageVersion raw "$install_prefix/pkg-manifest.json")"
[ "$manifest_version" = "$expected_version" ] || fail "installed manifest version mismatch"

sudo -n rm -rf "$install_prefix"
sudo -n /usr/sbin/pkgutil --forget "$expected_identifier" >/dev/null
cleanup_allowed=false
rm -rf "$work_dir"
trap - EXIT
assert_clean

printf 'published_release_remote_status=replacement-ready\n'
printf 'published_release_remote_package_url=%s\n' "$package_url"
printf 'published_release_remote_package_sha256=%s\n' "$actual_sha256"
printf 'published_release_remote_package_identifier=%s\n' "$expected_identifier"
printf 'published_release_remote_package_version=%s\n' "$receipt_version"
printf 'published_release_remote_package_uploaded=false\n'
printf 'published_release_remote_auth_uploaded=false\n'
printf 'published_release_remote_cleanup=complete\n'
"""


class PublishedReleaseProofError(RuntimeError):
    """The published release did not satisfy the clean-machine gate."""


def _load_publication_module() -> ModuleType:
    path = Path(__file__).with_name("publish_stock_codex_compat_release.py")
    spec = importlib.util.spec_from_file_location(
        "omnigent_stock_codex_compat_publication_for_clean_proof",
        path,
    )
    if spec is None or spec.loader is None:
        raise PublishedReleaseProofError(f"could not load publication verifier: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_PUBLICATION = _load_publication_module()


def _mapping(value: object, *, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise PublishedReleaseProofError(f"{label} is missing or invalid")
    return value


def _string(mapping: Mapping[str, object], key: str, *, label: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value:
        raise PublishedReleaseProofError(f"{label} omitted {key}")
    return value


def _parse_markers(stdout: str) -> dict[str, str]:
    markers: dict[str, str] = {}
    for line in stdout.splitlines():
        if not line.startswith("published_release_remote_") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        markers[key] = value
    return markers


def _run_remote(
    *,
    ssh: str,
    target: str,
    identity: Path | None,
    port: int,
    package_url: str,
    package_sha256: str,
    package_identifier: str,
    package_version: str,
) -> subprocess.CompletedProcess[str]:
    command = [
        ssh,
        "-p",
        str(port),
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
        "-o",
        "ConnectTimeout=10",
        "-o",
        "LogLevel=ERROR",
    ]
    if identity is not None:
        command.extend(["-i", str(identity)])
    command.extend(
        [
            target,
            "/bin/bash",
            "-s",
            "--",
            package_url,
            package_sha256,
            package_identifier,
            package_version,
        ]
    )
    try:
        return subprocess.run(
            command,
            input=REMOTE_SCRIPT,
            check=False,
            capture_output=True,
            text=True,
            timeout=900,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise PublishedReleaseProofError(
            f"clean-target published release proof could not execute: {shlex.join(command)}"
        ) from exc


def prove_published_release(args: argparse.Namespace) -> dict[str, object]:
    record_path = args.publication_record.expanduser().resolve()
    publication = _PUBLICATION.verify_publication(record_path)
    artifacts = _mapping(publication.get("artifacts"), label="publication artifacts")
    package = _mapping(artifacts.get("package"), label="package publication artifact")
    package_url = _string(package, "url", label="package publication artifact")
    package_sha256 = _string(package, "sha256", label="package publication artifact")
    package_identifier = _string(publication, "packageIdentifier", label="publication record")
    package_version = _string(publication, "packageVersion", label="publication record")
    if not args.ssh_target or "@" not in args.ssh_target:
        raise PublishedReleaseProofError("--ssh-target must include user@host")
    ssh = args.ssh or shutil.which("ssh")
    if not ssh:
        raise PublishedReleaseProofError("ssh is required")
    identity = args.ssh_identity
    if identity is not None:
        identity = identity.expanduser().resolve()
        if not identity.is_file():
            raise PublishedReleaseProofError(f"SSH identity is missing: {identity}")
    completed = _run_remote(
        ssh=ssh,
        target=args.ssh_target,
        identity=identity,
        port=args.ssh_port,
        package_url=package_url,
        package_sha256=package_sha256,
        package_identifier=package_identifier,
        package_version=package_version,
    )
    if completed.returncode != 0:
        raise PublishedReleaseProofError(
            f"clean-target published release proof failed with exit {completed.returncode}.\n"
            f"stdout={completed.stdout}\nstderr={completed.stderr}"
        )
    markers = _parse_markers(completed.stdout)
    expected = {
        "published_release_remote_status": "replacement-ready",
        "published_release_remote_package_url": package_url,
        "published_release_remote_package_sha256": package_sha256,
        "published_release_remote_package_identifier": package_identifier,
        "published_release_remote_package_version": package_version,
        "published_release_remote_package_uploaded": "false",
        "published_release_remote_auth_uploaded": "false",
        "published_release_remote_cleanup": "complete",
    }
    for key, value in expected.items():
        if markers.get(key) != value:
            raise PublishedReleaseProofError(
                f"clean-target proof marker mismatch: {key}={markers.get(key)!r}"
            )
    return {
        "status": "replacement-ready",
        "publicationRecord": str(record_path),
        "repository": publication.get("repository"),
        "tag": publication.get("tag"),
        "releaseUrl": publication.get("releaseUrl"),
        "packageUrl": package_url,
        "packageSha256": package_sha256,
        "packageIdentifier": package_identifier,
        "packageVersion": package_version,
        "sshTarget": args.ssh_target,
        "packageUploaded": False,
        "authUploaded": False,
        "cleanup": "complete",
        "remoteOutput": completed.stdout,
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Verify a public compatibility release and install its package from "
            "the public asset URL on a disposable clean Mac."
        )
    )
    parser.add_argument("--publication-record", type=Path, required=True)
    parser.add_argument("--ssh-target", required=True)
    parser.add_argument("--ssh-identity", type=Path)
    parser.add_argument("--ssh-port", type=int, default=22)
    parser.add_argument("--ssh", default=None)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        proof = prove_published_release(args)
    except PublishedReleaseProofError as exc:
        print(f"published_release_error={exc}", file=sys.stderr)
        return 1
    print("published_release_status=replacement-ready")
    print(f"published_release_repository={proof['repository']}")
    print(f"published_release_tag={proof['tag']}")
    print(f"published_release_url={proof['releaseUrl']}")
    print(f"published_release_package_url={proof['packageUrl']}")
    print(f"published_release_package_sha256={proof['packageSha256']}")
    print(f"published_release_package_version={proof['packageVersion']}")
    print("published_release_package_uploaded=False")
    print("published_release_auth_uploaded=False")
    print("published_release_cleanup=complete")
    print(
        "ASSERTION: the public GitHub release assets verify without credentials, "
        "and a disposable clean Mac can download, validate, install, inspect, "
        "and remove the signed/notarized package without host package or auth upload"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
