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
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse

from omnigent.inner.codex_executor import OMNIGENT_STOCK_CODEX_PATH_ENV

DEFAULT_CACHE_ROOT = Path.home() / ".local" / "omnigent" / "codex-stock"
MANIFEST_NAME = "manifest.json"
STOCK_CODEX_MANIFEST_KIND = "omnigent-stock-codex"
CHANNEL_MANIFEST_KIND = "omnigent-stock-codex-channel"


@dataclass(frozen=True)
class StockCodexChannelArtifact:
    """One candidate stock Codex artifact from a channel manifest."""

    version: str
    sha256: str
    source: str
    source_field: str
    platform: str | None

    @property
    def version_slug(self) -> str:
        """Return a filesystem-safe slug for this artifact's version."""
        return version_slug(self.version)

    def as_manifest_dict(self) -> dict[str, object]:
        """Return channel artifact provenance for an installed payload manifest."""
        data: dict[str, object] = {
            "version": self.version,
            "versionSlug": self.version_slug,
            "sha256": self.sha256,
            self.source_field: self.source,
        }
        if self.platform is not None:
            data["platform"] = self.platform
        return data


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
    source_kind: str | None = None
    channel_manifest_path: Path | None = None
    channel_artifact: dict[str, object] | None = None

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
            "sourceKind": self.source_kind,
            "channelManifestPath": (
                str(self.channel_manifest_path) if self.channel_manifest_path is not None else None
            ),
            "channelArtifact": self.channel_artifact,
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


def current_channel_platform() -> str:
    """Return the stock-Codex channel platform key for this host."""
    system = platform.system().lower()
    if system == "darwin":
        system = "macos"
    machine = platform.machine().lower()
    if machine in {"aarch64", "arm64"}:
        machine = "arm64"
    elif machine in {"x86_64", "amd64"}:
        machine = "x64"
    return f"{system}-{machine}"


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
    expected_source_kind: str | None = None,
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
    source_kind = manifest.get("sourceKind")
    if source_kind is not None and not isinstance(source_kind, str):
        raise ProvisioningError(f"Provisioned Codex source kind is invalid: {source_kind!r}")
    if expected_source_kind is not None and source_kind != expected_source_kind:
        raise ProvisioningError(
            "Provisioned Codex source kind mismatch: "
            f"expected={expected_source_kind!r} actual={source_kind!r}"
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
    channel_manifest_path = manifest.get("channelManifestPath")
    channel_artifact = manifest.get("channelArtifact")
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
        source_kind=source_kind,
        channel_manifest_path=Path(channel_manifest_path)
        if isinstance(channel_manifest_path, str) and channel_manifest_path
        else None,
        channel_artifact=channel_artifact if isinstance(channel_artifact, dict) else None,
    )


def copy_codex_payload(
    *,
    source_binary: Path,
    destination_payload_dir: Path,
    version: str,
    digest: str,
    source_kind: str = "source-binary",
    manifest_source_path: Path | None = None,
    manifest_source_realpath: Path | None = None,
    channel_manifest_path: Path | None = None,
    channel_artifact: StockCodexChannelArtifact | None = None,
) -> None:
    """Copy a Codex binary plus provenance manifest into the cache."""
    destination_payload_dir = destination_payload_dir.expanduser()
    manifest_source_path = manifest_source_path or source_binary
    manifest_source_realpath = manifest_source_realpath or source_binary.resolve()
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
            "kind": STOCK_CODEX_MANIFEST_KIND,
            "sourceKind": source_kind,
            "version": version,
            "versionSlug": version_slug(version),
            "sha256": digest,
            "sourcePath": str(manifest_source_path),
            "sourceRealpath": str(manifest_source_realpath),
            "installedAt": datetime.now(timezone.utc).isoformat(),
            "platform": platform.platform(),
            "env": {OMNIGENT_STOCK_CODEX_PATH_ENV: str(destination_payload_dir / "codex")},
        }
        if channel_manifest_path is not None:
            manifest["channelManifestPath"] = str(channel_manifest_path)
        if channel_artifact is not None:
            manifest["channelArtifact"] = channel_artifact.as_manifest_dict()
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


def read_channel_manifest(channel_manifest: Path) -> dict[str, object]:
    """Read and validate a stock Codex channel manifest."""
    channel_manifest = channel_manifest.expanduser()
    try:
        data = json.loads(channel_manifest.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ProvisioningError(f"Could not read channel manifest: {channel_manifest}") from exc
    except json.JSONDecodeError as exc:
        raise ProvisioningError(f"Channel manifest is invalid JSON: {channel_manifest}") from exc
    if not isinstance(data, dict):
        raise ProvisioningError(f"Channel manifest is not an object: {channel_manifest}")
    if data.get("kind") != CHANNEL_MANIFEST_KIND:
        raise ProvisioningError(
            f"Channel manifest kind mismatch: expected={CHANNEL_MANIFEST_KIND!r} "
            f"actual={data.get('kind')!r}"
        )
    artifacts = data.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise ProvisioningError("Channel manifest must contain a non-empty artifacts list")
    return data


def _channel_artifact_from_dict(
    raw: object,
    *,
    index: int,
) -> StockCodexChannelArtifact:
    if not isinstance(raw, dict):
        raise ProvisioningError(f"Channel artifact {index} is not an object")
    version = raw.get("version")
    if not isinstance(version, str) or not version:
        raise ProvisioningError(f"Channel artifact {index} is missing version")
    digest = raw.get("sha256")
    if not isinstance(digest, str) or len(digest) != 64:
        raise ProvisioningError(f"Channel artifact {index} has invalid sha256")
    url = raw.get("url")
    path = raw.get("path")
    if isinstance(url, str) and url:
        source = url
        source_field = "url"
    elif isinstance(path, str) and path:
        source = path
        source_field = "path"
    else:
        raise ProvisioningError(f"Channel artifact {index} must include url or path")
    artifact_platform = raw.get("platform")
    if artifact_platform is not None and not isinstance(artifact_platform, str):
        raise ProvisioningError(f"Channel artifact {index} has invalid platform")
    return StockCodexChannelArtifact(
        version=version,
        sha256=digest.lower(),
        source=source,
        source_field=source_field,
        platform=artifact_platform,
    )


def _artifact_matches_platform(
    artifact: StockCodexChannelArtifact,
    *,
    requested_platform: str,
) -> bool:
    return requested_platform == "any" or artifact.platform in {None, requested_platform}


def _artifact_matches_version(
    artifact: StockCodexChannelArtifact,
    *,
    requested_version: str,
) -> bool:
    return requested_version in {artifact.version, artifact.version_slug}


def select_channel_artifact(
    *,
    channel_manifest: Path,
    requested_version: str | None,
    requested_platform: str | None,
) -> StockCodexChannelArtifact:
    """Select one artifact from a channel manifest without network access."""
    data = read_channel_manifest(channel_manifest)
    platform_key = requested_platform or current_channel_platform()
    artifacts = [
        _channel_artifact_from_dict(raw, index=index)
        for index, raw in enumerate(data["artifacts"])
    ]
    platform_matches = [
        artifact
        for artifact in artifacts
        if _artifact_matches_platform(artifact, requested_platform=platform_key)
    ]
    if not platform_matches:
        raise ProvisioningError(f"Channel manifest has no artifact for platform {platform_key!r}")
    version_selector = requested_version
    if version_selector is None:
        latest = data.get("latest")
        if isinstance(latest, str) and latest:
            version_selector = latest
    if version_selector is not None:
        matches = [
            artifact
            for artifact in platform_matches
            if _artifact_matches_version(artifact, requested_version=version_selector)
        ]
        if not matches:
            raise ProvisioningError(
                f"Channel manifest has no artifact for version {version_selector!r} "
                f"and platform {platform_key!r}"
            )
        if len(matches) > 1:
            raise ProvisioningError(
                f"Channel manifest has multiple artifacts for version {version_selector!r} "
                f"and platform {platform_key!r}"
            )
        return matches[0]
    if len(platform_matches) == 1:
        return platform_matches[0]
    raise ProvisioningError(
        "Channel manifest has multiple platform-matching artifacts; set latest "
        "or pass --channel-version"
    )


def resolve_channel_artifact_path(
    artifact: StockCodexChannelArtifact,
    *,
    channel_manifest: Path,
) -> Path:
    """Resolve a local file artifact from a channel manifest."""
    parsed = urlparse(artifact.source)
    if artifact.source_field == "path" or not parsed.scheme:
        path = Path(artifact.source).expanduser()
        if not path.is_absolute():
            path = channel_manifest.expanduser().parent / path
        return path
    if parsed.scheme == "file":
        if parsed.netloc not in {"", "localhost"}:
            raise ProvisioningError(
                f"Unsupported file URL host for channel artifact: {artifact.source}"
            )
        return Path(unquote(parsed.path)).expanduser()
    if parsed.scheme in {"http", "https"}:
        raise ProvisioningError(
            "Remote channel downloads are not implemented in this bounded proof slice; "
            "use a local path or file:// artifact."
        )
    raise ProvisioningError(f"Unsupported channel artifact URL: {artifact.source}")


def stage_channel_artifact(
    artifact: StockCodexChannelArtifact,
    *,
    channel_manifest: Path,
    stage_dir: Path,
    allow_fork_codex: bool,
) -> tuple[Path, Path, Path, str, str]:
    """Copy a selected channel artifact into a temporary verified staging path."""
    source_path = resolve_channel_artifact_path(
        artifact,
        channel_manifest=channel_manifest,
    )
    if not source_path.is_file():
        raise ProvisioningError(f"Channel artifact not found: {source_path}")
    source_realpath = source_path.resolve()
    if not allow_fork_codex and ".codex-fork" in source_realpath.parts:
        raise ProvisioningError(
            f"Refusing to provision Codex-fork binary from channel: {source_realpath}"
        )
    source_digest = sha256_file(source_realpath)
    if source_digest.lower() != artifact.sha256.lower():
        raise ProvisioningError(
            f"Channel artifact sha256 mismatch: expected={artifact.sha256} actual={source_digest}"
        )
    stage_dir.mkdir(parents=True, exist_ok=True)
    staged_path = stage_dir / "codex"
    shutil.copy2(source_realpath, staged_path)
    staged_path.chmod(0o755)
    staged_digest = sha256_file(staged_path)
    if staged_digest.lower() != artifact.sha256.lower():
        raise ProvisioningError(
            f"Staged channel artifact sha256 mismatch: expected={artifact.sha256} "
            f"actual={staged_digest}"
        )
    staged_version = codex_version(staged_path)
    if staged_version != artifact.version:
        raise ProvisioningError(
            f"Channel artifact version mismatch: expected={artifact.version!r} "
            f"actual={staged_version!r}"
        )
    return staged_path, source_path, source_realpath, staged_digest, staged_version


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


def provision_stock_codex_from_channel(
    *,
    cache_root: Path,
    channel_manifest: Path,
    channel_version: str | None,
    channel_platform: str | None,
    expected_sha256: str | None,
    force: bool,
    allow_fork_codex: bool,
) -> ProvisionedStockCodex:
    """Provision or reuse a verified stock Codex payload from a channel manifest."""
    channel_manifest = channel_manifest.expanduser()
    artifact = select_channel_artifact(
        channel_manifest=channel_manifest,
        requested_version=channel_version,
        requested_platform=channel_platform,
    )
    if expected_sha256 is not None and artifact.sha256.lower() != expected_sha256.lower():
        raise ProvisioningError(
            f"Channel artifact sha256 mismatch: expected={expected_sha256} "
            f"actual={artifact.sha256}"
        )
    with tempfile.TemporaryDirectory(prefix="omnigent-stock-codex-channel-") as temp_root:
        staged_path, source_path, source_realpath, digest, version = stage_channel_artifact(
            artifact,
            channel_manifest=channel_manifest,
            stage_dir=Path(temp_root),
            allow_fork_codex=allow_fork_codex,
        )
        payload_dir = payload_dir_for(cache_root, version)
        if payload_dir.exists() and not force:
            try:
                return verify_payload(
                    payload_dir,
                    expected_sha256=digest,
                    expected_source_kind="channel",
                )
            except ProvisioningError as exc:
                raise ProvisioningError(
                    f"Existing channel-managed Codex payload is stale or mismatched: {exc}. "
                    "Rerun with --force to replace it."
                ) from exc
        copy_codex_payload(
            source_binary=staged_path,
            destination_payload_dir=payload_dir,
            version=version,
            digest=digest,
            source_kind="channel",
            manifest_source_path=source_path,
            manifest_source_realpath=source_realpath,
            channel_manifest_path=channel_manifest,
            channel_artifact=artifact,
        )
        return verify_payload(
            payload_dir,
            expected_sha256=digest,
            expected_source_kind="channel",
        )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Provision a pinned stock Codex binary for Omnigent launchers."
    )
    parser.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE_ROOT)
    source = parser.add_mutually_exclusive_group()
    source.add_argument(
        "--source-binary",
        type=Path,
        default=None,
        help="Stock Codex binary to pin. Defaults to the first codex on PATH.",
    )
    source.add_argument(
        "--channel-manifest",
        type=Path,
        default=None,
        help="Local stock-Codex channel manifest to select and verify an artifact.",
    )
    parser.add_argument(
        "--channel-version",
        default=None,
        help="Version or version slug to select from --channel-manifest.",
    )
    parser.add_argument(
        "--channel-platform",
        default=None,
        help=(
            "Platform key to select from --channel-manifest. Defaults to this host, "
            f"{current_channel_platform()!r}. Use 'any' for platform-agnostic fixtures."
        ),
    )
    parser.add_argument(
        "--expected-sha256",
        default=None,
        help="Optional expected SHA-256 for the source binary or selected channel artifact.",
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
        if args.channel_manifest is not None:
            provisioned = provision_stock_codex_from_channel(
                cache_root=args.cache_root,
                channel_manifest=args.channel_manifest,
                channel_version=args.channel_version,
                channel_platform=args.channel_platform,
                expected_sha256=args.expected_sha256,
                force=args.force,
                allow_fork_codex=args.allow_fork_codex,
            )
        else:
            if args.channel_version is not None or args.channel_platform is not None:
                raise ProvisioningError(
                    "--channel-version and --channel-platform require --channel-manifest"
                )
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
