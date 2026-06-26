#!/usr/bin/env python3
"""Provision the temporary Xcode 27-compatible AXe payload for Omnigent proofs."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

DEFAULT_AXE_REPO_URL = "https://github.com/jkaunert/AXe.git"
DEFAULT_AXE_REF = "9051a6e13fdd8e0789f734a11fc1e71f48def916"
DEFAULT_CACHE_ROOT = Path.home() / ".cache" / "omnigent" / "axe"
DEFAULT_CODESIGN_IDENTITY = "-"
OMNIGENT_AXE_ENV_VAR = "OMNIGENT_XCODEBUILDMCP_AXE_PATH"
SHARED_SIMULATORKIT_MARKER = b"../SharedFrameworks/SimulatorKit.framework"
LEGACY_SIMULATORKIT_MARKER = b"Library/PrivateFrameworks/SimulatorKit.framework"


@dataclass(frozen=True)
class ProvisionedAXe:
    """Verified AXe payload installed in the Omnigent cache."""

    axe_path: Path
    payload_dir: Path
    fbcontrolcore_binary: Path
    ref: str

    def as_json(self) -> str:
        """Return a stable JSON summary for automation."""
        return json.dumps(
            {
                "axePath": str(self.axe_path),
                "payloadDir": str(self.payload_dir),
                "fbcontrolcoreBinary": str(self.fbcontrolcore_binary),
                "ref": self.ref,
                "env": {OMNIGENT_AXE_ENV_VAR: str(self.axe_path)},
            },
            indent=2,
            sort_keys=True,
        )


class ProvisioningError(RuntimeError):
    """The AXe payload could not be provisioned or verified."""


def ref_slug(ref: str) -> str:
    """Return a path-safe slug for a git ref."""
    return "".join(char if char.isalnum() or char in "._-" else "-" for char in ref)[:40]


def payload_dir_for(cache_root: Path, ref: str) -> Path:
    """Return the deterministic payload directory for a pinned AXe ref."""
    return cache_root.expanduser() / "payloads" / ref_slug(ref)


def source_dir_for(cache_root: Path, ref: str) -> Path:
    """Return the deterministic source checkout directory for a pinned AXe ref."""
    return cache_root.expanduser() / "sources" / ref_slug(ref)


def _is_executable(path: Path) -> bool:
    return bool(path.stat().st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))


def find_fbcontrolcore_binary(payload_dir: Path) -> Path:
    """Find the FBControlCore framework binary inside a staged AXe payload."""
    framework_dir = payload_dir / "Frameworks" / "FBControlCore.framework"
    candidates = (
        framework_dir / "Versions" / "A" / "FBControlCore",
        framework_dir / "FBControlCore",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    for candidate in framework_dir.rglob("FBControlCore"):
        if candidate.is_file():
            return candidate
    raise ProvisioningError(
        f"AXe payload does not include FBControlCore.framework binary under {framework_dir}"
    )


def verify_payload(payload_dir: Path, *, ref: str) -> ProvisionedAXe:
    """Verify that a payload can be used as an Xcode 27-compatible AXe install."""
    payload_dir = payload_dir.expanduser()
    axe_path = payload_dir / "axe"
    if not axe_path.is_file():
        raise ProvisioningError(f"AXe executable not found: {axe_path}")
    if not _is_executable(axe_path):
        raise ProvisioningError(f"AXe executable is not executable: {axe_path}")
    if not (payload_dir / "Frameworks").is_dir():
        raise ProvisioningError(f"AXe payload missing Frameworks directory: {payload_dir}")
    fbcontrolcore_binary = find_fbcontrolcore_binary(payload_dir)
    framework_bytes = fbcontrolcore_binary.read_bytes()
    if SHARED_SIMULATORKIT_MARKER not in framework_bytes:
        raise ProvisioningError(
            "FBControlCore does not contain the Xcode 27 SharedFrameworks "
            "SimulatorKit fallback marker"
        )
    if LEGACY_SIMULATORKIT_MARKER not in framework_bytes:
        raise ProvisioningError(
            "FBControlCore does not contain the legacy SimulatorKit fallback marker"
        )
    return ProvisionedAXe(
        axe_path=axe_path,
        payload_dir=payload_dir,
        fbcontrolcore_binary=fbcontrolcore_binary,
        ref=ref,
    )


def copy_payload_from_binary(source_binary: Path, destination_payload_dir: Path) -> None:
    """Copy a built AXe runtime payload into the deterministic cache directory."""
    source_binary = source_binary.expanduser()
    if not source_binary.is_file():
        raise ProvisioningError(f"Source AXe binary not found: {source_binary}")
    source_payload_dir = source_binary.parent
    if source_binary.name != "axe":
        raise ProvisioningError(f"Source AXe binary must be named 'axe': {source_binary}")

    required_entries = ("axe", "Frameworks")
    missing = [entry for entry in required_entries if not (source_payload_dir / entry).exists()]
    if missing:
        raise ProvisioningError(
            f"Source AXe payload is missing required entries: {', '.join(missing)}"
        )

    destination_payload_dir = destination_payload_dir.expanduser()
    tmp_dir = destination_payload_dir.with_name(destination_payload_dir.name + ".tmp")
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir)
    tmp_dir.mkdir(parents=True)
    try:
        for entry in ("axe", "Frameworks", "AXe_AXe.bundle"):
            source = source_payload_dir / entry
            if not source.exists():
                continue
            destination = tmp_dir / entry
            if source.is_dir():
                shutil.copytree(source, destination, symlinks=True)
            else:
                shutil.copy2(source, destination)
        if destination_payload_dir.exists():
            shutil.rmtree(destination_payload_dir)
        tmp_dir.replace(destination_payload_dir)
    finally:
        if tmp_dir.exists():
            shutil.rmtree(tmp_dir)


def run_checked(command: list[str], *, cwd: Path, env: dict[str, str]) -> None:
    """Run one provisioning command with readable failures."""
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        check=False,
        text=True,
    )
    if completed.returncode != 0:
        raise ProvisioningError(f"Command exited {completed.returncode}: {' '.join(command)}")


def ensure_source_checkout(
    *,
    source_dir: Path,
    repo_url: str,
    ref: str,
    force: bool,
) -> None:
    """Clone or refresh the pinned AXe source checkout."""
    if source_dir.exists() and force:
        shutil.rmtree(source_dir)
    if not source_dir.exists():
        source_dir.parent.mkdir(parents=True, exist_ok=True)
        run_checked(
            ["git", "clone", repo_url, str(source_dir)],
            cwd=source_dir.parent,
            env=os.environ.copy(),
        )
    else:
        run_checked(
            ["git", "fetch", "--all", "--tags", "--prune"], cwd=source_dir, env=os.environ.copy()
        )
    run_checked(["git", "checkout", "--force", ref], cwd=source_dir, env=os.environ.copy())


def build_source_payload(
    *,
    source_dir: Path,
    codesign_identity: str | None,
) -> Path:
    """Build AXe's runtime payload from the source checkout and return axe path."""
    env = os.environ.copy()
    if codesign_identity:
        env["AXE_CODESIGN_IDENTITY"] = codesign_identity
    run_checked(["./scripts/build.sh", "dev"], cwd=source_dir, env=env)
    run_checked(["./scripts/build.sh", "executable"], cwd=source_dir, env=env)
    return source_dir / "build_products" / "axe"


def provision_axe(
    *,
    cache_root: Path,
    ref: str,
    repo_url: str,
    source_binary: Path | None,
    force: bool,
    no_build: bool,
    codesign_identity: str | None,
) -> ProvisionedAXe:
    """Provision or reuse a verified AXe payload."""
    payload_dir = payload_dir_for(cache_root, ref)
    if payload_dir.exists() and not force:
        return verify_payload(payload_dir, ref=ref)

    if source_binary is not None:
        copy_payload_from_binary(source_binary, payload_dir)
        return verify_payload(payload_dir, ref=ref)

    if no_build:
        raise ProvisioningError(
            f"No verified AXe payload at {payload_dir}; rerun with --source-binary or allow build"
        )

    source_dir = source_dir_for(cache_root, ref)
    ensure_source_checkout(
        source_dir=source_dir,
        repo_url=repo_url,
        ref=ref,
        force=force,
    )
    built_binary = build_source_payload(
        source_dir=source_dir,
        codesign_identity=codesign_identity,
    )
    copy_payload_from_binary(built_binary, payload_dir)
    return verify_payload(payload_dir, ref=ref)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Provision an Xcode 27-compatible AXe binary for Omnigent proofs."
    )
    parser.add_argument("--repo-url", default=DEFAULT_AXE_REPO_URL)
    parser.add_argument("--ref", default=DEFAULT_AXE_REF)
    parser.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE_ROOT)
    parser.add_argument(
        "--source-binary",
        type=Path,
        default=None,
        help="Existing built AXe binary whose sibling Frameworks directory should be cached.",
    )
    parser.add_argument(
        "--codesign-identity",
        default=os.environ.get("AXE_CODESIGN_IDENTITY", DEFAULT_CODESIGN_IDENTITY),
        help="Signing identity for source builds; defaults to ad hoc signing '-'.",
    )
    parser.add_argument("--force", action="store_true", help="Replace any cached payload.")
    parser.add_argument(
        "--no-build",
        action="store_true",
        help="Fail instead of cloning/building when no verified cache exists.",
    )
    output = parser.add_mutually_exclusive_group()
    output.add_argument(
        "--print-path",
        action="store_true",
        help="Print only the provisioned AXe executable path.",
    )
    output.add_argument(
        "--print-shell-env",
        action="store_true",
        help=f"Print only an export line for {OMNIGENT_AXE_ENV_VAR}.",
    )
    output.add_argument("--json", action="store_true", help="Print a JSON summary.")
    return parser.parse_args(argv)


def shell_quote(value: str) -> str:
    """Quote a value for POSIX shell export output."""
    return "'" + value.replace("'", "'\\''") + "'"


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        provisioned = provision_axe(
            cache_root=args.cache_root,
            ref=args.ref,
            repo_url=args.repo_url,
            source_binary=args.source_binary,
            force=args.force,
            no_build=args.no_build,
            codesign_identity=args.codesign_identity,
        )
    except ProvisioningError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.print_path:
        print(provisioned.axe_path)
    elif args.print_shell_env:
        print(f"export {OMNIGENT_AXE_ENV_VAR}={shell_quote(str(provisioned.axe_path))}")
    elif args.json:
        print(provisioned.as_json())
    else:
        print(f"axe_payload={provisioned.payload_dir}")
        print(f"axe_path={provisioned.axe_path}")
        print(f"fbcontrolcore_binary={provisioned.fbcontrolcore_binary}")
        print(f"axe_ref={provisioned.ref}")
        print(f"{OMNIGENT_AXE_ENV_VAR}={provisioned.axe_path}")
        print(f"export {OMNIGENT_AXE_ENV_VAR}={shell_quote(str(provisioned.axe_path))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
