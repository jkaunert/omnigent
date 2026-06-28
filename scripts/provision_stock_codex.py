#!/usr/bin/env python3
"""Provision a pinned stock Codex binary for Omnigent launchers."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import stat
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from omnigent.inner.codex_executor import OMNIGENT_STOCK_CODEX_PATH_ENV

DEFAULT_CACHE_ROOT = Path.home() / ".local" / "omnigent" / "codex-stock"
MANIFEST_NAME = "manifest.json"


@dataclass(frozen=True)
class ProvisionedStockCodex:
    """Verified stock Codex payload installed in the Omnigent cache."""

    codex_path: Path
    payload_dir: Path
    manifest_path: Path
    version: str
    version_slug: str
    sha256: str
    source_path: Path | None
    source_realpath: Path | None

    def as_dict(self) -> dict[str, object]:
        """Return a stable JSON-ready summary for automation."""
        return {
            "codexPath": str(self.codex_path),
            "payloadDir": str(self.payload_dir),
            "manifestPath": str(self.manifest_path),
            "version": self.version,
            "versionSlug": self.version_slug,
            "sha256": self.sha256,
            "sourcePath": str(self.source_path) if self.source_path is not None else None,
            "sourceRealpath": (
                str(self.source_realpath) if self.source_realpath is not None else None
            ),
            "env": {OMNIGENT_STOCK_CODEX_PATH_ENV: str(self.codex_path)},
        }

    def as_json(self) -> str:
        """Return a stable JSON summary for automation."""
        return json.dumps(self.as_dict(), indent=2, sort_keys=True)


class ProvisioningError(RuntimeError):
    """The stock Codex payload could not be provisioned or verified."""


def _is_executable(path: Path) -> bool:
    return bool(path.stat().st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))


def shell_quote(value: str) -> str:
    """Quote a value for POSIX shell export output."""
    return "'" + value.replace("'", "'\\''") + "'"


def sha256_file(path: Path) -> str:
    """Return the SHA-256 digest for a file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def codex_version(path: Path) -> str:
    """Return ``codex --version`` output for a candidate binary."""
    try:
        completed = subprocess.run(
            [str(path), "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception as exc:
        raise ProvisioningError(f"Could not run {path} --version: {exc}") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise ProvisioningError(
            f"{path} --version exited {completed.returncode}: {detail or 'no output'}"
        )
    version = (completed.stdout or completed.stderr).strip()
    if not version:
        raise ProvisioningError(f"{path} --version produced no output")
    return version


def version_slug(version: str) -> str:
    """Return a filesystem-safe version slug from ``codex --version`` output."""
    import re

    match = re.search(r"(\d+(?:\.\d+)+(?:[-.A-Za-z0-9]+)?)", version)
    if match is not None:
        return match.group(1)
    return "unknown"


def payload_dir_for(cache_root: Path, version: str) -> Path:
    """Return the deterministic payload directory for a Codex version."""
    return cache_root.expanduser() / version_slug(version)


def resolve_source_codex(
    source_binary: Path | None,
    *,
    allow_fork_codex: bool,
) -> Path:
    """Resolve and validate the stock Codex source binary."""
    raw = str(source_binary.expanduser()) if source_binary is not None else shutil.which("codex")
    if not raw:
        raise ProvisioningError("Could not find codex on PATH; pass --source-binary.")
    path = Path(raw).expanduser()
    if not path.is_file():
        raise ProvisioningError(f"Codex source binary not found: {path}")
    if not _is_executable(path):
        raise ProvisioningError(f"Codex source binary is not executable: {path}")
    realpath = path.resolve()
    if not allow_fork_codex and ".codex-fork" in realpath.parts:
        raise ProvisioningError(
            f"Refusing to provision Codex-fork binary as stock Codex: {realpath}"
        )
    return path


def verify_payload(
    payload_dir: Path,
    *,
    expected_sha256: str | None = None,
) -> ProvisionedStockCodex:
    """Verify an installed stock Codex payload and manifest."""
    payload_dir = payload_dir.expanduser()
    codex_path = payload_dir / "codex"
    manifest_path = payload_dir / MANIFEST_NAME
    if not codex_path.is_file():
        raise ProvisioningError(f"Provisioned Codex binary not found: {codex_path}")
    if not _is_executable(codex_path):
        raise ProvisioningError(f"Provisioned Codex binary is not executable: {codex_path}")
    if not manifest_path.is_file():
        raise ProvisioningError(f"Provisioned Codex manifest not found: {manifest_path}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ProvisioningError(
            f"Provisioned Codex manifest is invalid JSON: {manifest_path}"
        ) from exc
    if not isinstance(manifest, dict):
        raise ProvisioningError(f"Provisioned Codex manifest is not an object: {manifest_path}")
    digest = sha256_file(codex_path)
    manifest_sha = manifest.get("sha256")
    if manifest_sha != digest:
        raise ProvisioningError(
            f"Provisioned Codex sha256 mismatch: manifest={manifest_sha!r} actual={digest}"
        )
    if expected_sha256 is not None and digest.lower() != expected_sha256.lower():
        raise ProvisioningError(
            f"Provisioned Codex sha256 mismatch: expected={expected_sha256} actual={digest}"
        )
    version = codex_version(codex_path)
    manifest_version = manifest.get("version")
    if manifest_version != version:
        raise ProvisioningError(
            f"Provisioned Codex version mismatch: manifest={manifest_version!r} actual={version!r}"
        )
    slug = str(manifest.get("versionSlug") or version_slug(version))
    source_path = manifest.get("sourcePath")
    source_realpath = manifest.get("sourceRealpath")
    return ProvisionedStockCodex(
        codex_path=codex_path,
        payload_dir=payload_dir,
        manifest_path=manifest_path,
        version=version,
        version_slug=slug,
        sha256=digest,
        source_path=Path(source_path) if isinstance(source_path, str) and source_path else None,
        source_realpath=Path(source_realpath)
        if isinstance(source_realpath, str) and source_realpath
        else None,
    )


def copy_codex_payload(
    *,
    source_binary: Path,
    destination_payload_dir: Path,
    version: str,
    digest: str,
) -> None:
    """Copy a Codex binary plus provenance manifest into the cache."""
    destination_payload_dir = destination_payload_dir.expanduser()
    tmp_dir = destination_payload_dir.with_name(destination_payload_dir.name + ".tmp")
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir)
    tmp_dir.mkdir(parents=True)
    try:
        codex_path = tmp_dir / "codex"
        shutil.copy2(source_binary.resolve(), codex_path)
        codex_path.chmod(0o755)
        manifest = {
            "schemaVersion": 1,
            "kind": "omnigent-stock-codex",
            "version": version,
            "versionSlug": version_slug(version),
            "sha256": digest,
            "sourcePath": str(source_binary),
            "sourceRealpath": str(source_binary.resolve()),
            "installedAt": datetime.now(timezone.utc).isoformat(),
            "platform": platform.platform(),
            "env": {OMNIGENT_STOCK_CODEX_PATH_ENV: str(destination_payload_dir / "codex")},
        }
        (tmp_dir / MANIFEST_NAME).write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        if destination_payload_dir.exists():
            shutil.rmtree(destination_payload_dir)
        tmp_dir.replace(destination_payload_dir)
    finally:
        if tmp_dir.exists():
            shutil.rmtree(tmp_dir)


def provision_stock_codex(
    *,
    cache_root: Path,
    source_binary: Path | None,
    expected_sha256: str | None,
    force: bool,
    allow_fork_codex: bool,
) -> ProvisionedStockCodex:
    """Provision or reuse a verified pinned stock Codex payload."""
    source = resolve_source_codex(source_binary, allow_fork_codex=allow_fork_codex)
    source_realpath = source.resolve()
    digest = sha256_file(source_realpath)
    if expected_sha256 is not None and digest.lower() != expected_sha256.lower():
        raise ProvisioningError(
            f"Source Codex sha256 mismatch: expected={expected_sha256} actual={digest}"
        )
    version = codex_version(source_realpath)
    payload_dir = payload_dir_for(cache_root, version)
    if payload_dir.exists() and not force:
        try:
            return verify_payload(payload_dir, expected_sha256=digest)
        except ProvisioningError as exc:
            raise ProvisioningError(
                f"Existing pinned Codex payload is stale or mismatched: {exc}. "
                "Rerun with --force to replace it."
            ) from exc
    copy_codex_payload(
        source_binary=source,
        destination_payload_dir=payload_dir,
        version=version,
        digest=digest,
    )
    return verify_payload(payload_dir, expected_sha256=digest)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Provision a pinned stock Codex binary for Omnigent launchers."
    )
    parser.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE_ROOT)
    parser.add_argument(
        "--source-binary",
        type=Path,
        default=None,
        help="Stock Codex binary to pin. Defaults to the first codex on PATH.",
    )
    parser.add_argument(
        "--expected-sha256",
        default=None,
        help="Optional expected SHA-256 for the source binary.",
    )
    parser.add_argument("--force", action="store_true", help="Replace any cached payload.")
    parser.add_argument(
        "--allow-fork-codex",
        action="store_true",
        help="Allow a .codex-fork source binary for diagnostics. Not a stock proof.",
    )
    output = parser.add_mutually_exclusive_group()
    output.add_argument(
        "--print-path",
        action="store_true",
        help="Print only the provisioned Codex executable path.",
    )
    output.add_argument(
        "--print-shell-env",
        action="store_true",
        help=f"Print only an export line for {OMNIGENT_STOCK_CODEX_PATH_ENV}.",
    )
    output.add_argument("--json", action="store_true", help="Print a JSON summary.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        provisioned = provision_stock_codex(
            cache_root=args.cache_root,
            source_binary=args.source_binary,
            expected_sha256=args.expected_sha256,
            force=args.force,
            allow_fork_codex=args.allow_fork_codex,
        )
    except ProvisioningError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.print_path:
        print(provisioned.codex_path)
    elif args.print_shell_env:
        print(f"export {OMNIGENT_STOCK_CODEX_PATH_ENV}={shell_quote(str(provisioned.codex_path))}")
    elif args.json:
        print(provisioned.as_json())
    else:
        print(f"stock_codex_payload={provisioned.payload_dir}")
        print(f"stock_codex_path={provisioned.codex_path}")
        print(f"stock_codex_version={provisioned.version}")
        print(f"stock_codex_sha256={provisioned.sha256}")
        print(f"stock_codex_manifest={provisioned.manifest_path}")
        print(f"{OMNIGENT_STOCK_CODEX_PATH_ENV}={provisioned.codex_path}")
        print(f"export {OMNIGENT_STOCK_CODEX_PATH_ENV}={shell_quote(str(provisioned.codex_path))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
