#!/usr/bin/env python3
"""Build a macOS pkg for the stock-Codex compatibility runtime."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import tomllib

PKG_KIND = "omnigent-stock-codex-compat-pkg"
PKG_SCHEMA_VERSION = 1
DEFAULT_PACKAGE_IDENTIFIER = "ai.omnigent.stock-codex-compat"
DEFAULT_INSTALL_PREFIX = Path("/Library/Application Support/Omnigent/stock-codex-compat")
DEFAULT_OUTPUT_NAME = "omnigent-stock-codex-compat.pkg"
RUNTIME_ROOT_NAME = "runtime"
PKG_MANIFEST_NAME = "pkg-manifest.json"
BUNDLE_MANIFEST_NAME = "bundle-manifest.json"
POSTINSTALL_NAME = "postinstall"
INSTALLER_RELATIVE_PATH = "scripts/install_stock_codex_compat_launcher.py"
PROVISIONER_RELATIVE_PATH = "scripts/provision_stock_codex.py"
BOOTSTRAP_SHELL_RELATIVE_PATH = "scripts/bootstrap_stock_codex_compat.sh"
BOOTSTRAP_PYTHON_RELATIVE_PATH = "scripts/bootstrap_stock_codex_compat.py"
WRAPPER_RELATIVE_PATH = "omnigent/stock_codex_compat_wrapper.py"


def required_payload_files_for(install_prefix: Path) -> tuple[str, ...]:
    """Return the package payload files required by the compatibility contract."""
    prefix = install_prefix.relative_to("/").as_posix()
    return (
        f"{prefix}/{PKG_MANIFEST_NAME}",
        f"{prefix}/{BUNDLE_MANIFEST_NAME}",
        f"{prefix}/{RUNTIME_ROOT_NAME}/pyproject.toml",
        f"{prefix}/{RUNTIME_ROOT_NAME}/{INSTALLER_RELATIVE_PATH}",
        f"{prefix}/{RUNTIME_ROOT_NAME}/{PROVISIONER_RELATIVE_PATH}",
        f"{prefix}/{RUNTIME_ROOT_NAME}/{BOOTSTRAP_SHELL_RELATIVE_PATH}",
        f"{prefix}/{RUNTIME_ROOT_NAME}/{BOOTSTRAP_PYTHON_RELATIVE_PATH}",
        f"{prefix}/{RUNTIME_ROOT_NAME}/{WRAPPER_RELATIVE_PATH}",
    )


@dataclass(frozen=True)
class StockCodexCompatPkgInspection:
    """Inspection result for a stock-Codex compatibility pkg."""

    package_identifier: str
    package_version: str
    install_location: str
    install_prefix: Path
    runtime_root: Path
    package_info_path: Path
    pkg_manifest_path: Path
    bundle_manifest_path: Path
    postinstall_path: Path
    payload_files: tuple[str, ...]
    script_names: tuple[str, ...]
    archive_entries: tuple[str, ...]
    signature_status: str
    signed: bool
    pkg_manifest: dict[str, Any]
    bundle_manifest: dict[str, Any]

    def as_dict(self) -> dict[str, object]:
        required_payload_files = required_payload_files_for(self.install_prefix)
        required_payload_presence = {
            path: path in self.payload_files for path in required_payload_files
        }
        return {
            "packageIdentifier": self.package_identifier,
            "packageVersion": self.package_version,
            "installLocation": self.install_location,
            "installPrefix": str(self.install_prefix),
            "runtimeRoot": str(self.runtime_root),
            "packageInfoPath": str(self.package_info_path),
            "pkgManifestPath": str(self.pkg_manifest_path),
            "bundleManifestPath": str(self.bundle_manifest_path),
            "postinstallPath": str(self.postinstall_path),
            "payloadFileCount": len(self.payload_files),
            "payloadFilePreview": list(self.payload_files[:25]),
            "requiredPayloadFiles": required_payload_presence,
            "allRequiredPayloadFilesPresent": all(required_payload_presence.values()),
            "scriptNames": list(self.script_names),
            "archiveEntries": list(self.archive_entries),
            "signatureStatus": self.signature_status,
            "signed": self.signed,
            "pkgManifest": self.pkg_manifest,
            "bundleManifest": self.bundle_manifest,
        }


@dataclass(frozen=True)
class StockCodexCompatPkgBuildResult:
    """Result of building and inspecting a stock-Codex compatibility pkg."""

    package_path: Path
    package_sha256: str
    source_root: Path
    source_bundle_path: Path
    source_bundle_sha256: str
    package_identifier: str
    package_version: str
    install_location: str
    install_prefix: Path
    signing_identity: str | None
    signing_keychain: Path | None
    runtime_root: Path
    included_payload_file_count: int
    created_at: str
    inspection: StockCodexCompatPkgInspection

    def as_dict(self) -> dict[str, object]:
        return {
            "kind": PKG_KIND,
            "schemaVersion": PKG_SCHEMA_VERSION,
            "packagePath": str(self.package_path),
            "packageSha256": self.package_sha256,
            "sourceRoot": str(self.source_root),
            "sourceBundlePath": str(self.source_bundle_path),
            "sourceBundleSha256": self.source_bundle_sha256,
            "packageIdentifier": self.package_identifier,
            "packageVersion": self.package_version,
            "installLocation": self.install_location,
            "installPrefix": str(self.install_prefix),
            "signingIdentity": self.signing_identity,
            "signingKeychain": str(self.signing_keychain) if self.signing_keychain else None,
            "runtimeRoot": str(self.runtime_root),
            "includedPayloadFileCount": self.included_payload_file_count,
            "createdAt": self.created_at,
            "inspection": self.inspection.as_dict(),
        }


class PkgBuildError(RuntimeError):
    """The stock-Codex compatibility pkg could not be built or inspected."""


def _load_bundle_builder() -> Any:
    script_path = Path(__file__).with_name("build_stock_codex_compat_bundle.py")
    spec = importlib.util.spec_from_file_location(
        "omnigent_stock_codex_compat_bundle_builder",
        script_path,
    )
    if spec is None or spec.loader is None:
        raise PkgBuildError(f"Could not load bundle builder: {script_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run_checked(
    command: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    timeout: float = 120.0,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if completed.returncode != 0:
        raise PkgBuildError(
            "Command failed.\n"
            f"command={command!r}\n"
            f"exit={completed.returncode}\n"
            f"stdout={completed.stdout}\n"
            f"stderr={completed.stderr}"
        )
    return completed


def _require_tool(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise PkgBuildError(f"Required macOS packaging tool is missing: {name}")
    return path


def _read_project_version(repo_root: Path) -> str:
    pyproject_path = repo_root / "pyproject.toml"
    try:
        payload = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise PkgBuildError(f"Could not read project version from {pyproject_path}") from exc
    project = payload.get("project")
    if not isinstance(project, dict):
        raise PkgBuildError(f"pyproject.toml does not contain [project]: {pyproject_path}")
    version = project.get("version")
    if not isinstance(version, str) or not version:
        raise PkgBuildError(f"pyproject.toml does not contain project.version: {pyproject_path}")
    return version


def _safe_extract_tar_gz(archive_path: Path, destination: Path) -> None:
    destination = destination.expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive_path, "r:gz") as archive:
        for member in archive.getmembers():
            target = (destination / member.name).resolve()
            if target != destination and not str(target).startswith(f"{destination}{os.sep}"):
                raise PkgBuildError(f"Bundle contains unsafe archive member: {member.name!r}")
            if member.isdev():
                raise PkgBuildError(f"Bundle contains unsupported device member: {member.name!r}")
        archive.extractall(destination)


def _strip_xattrs(path: Path) -> None:
    xattr = shutil.which("xattr")
    if not xattr:
        return
    subprocess.run([xattr, "-cr", str(path)], check=False, capture_output=True, text=True)


def _write_postinstall(script_path: Path, *, install_prefix: Path) -> None:
    script_path.write_text(
        "#!/bin/sh\n"
        "set -eu\n"
        'target_volume="${3:-/}"\n'
        'case "$target_volume" in\n'
        '  ""|"/") target_prefix="" ;;\n'
        '  *) target_prefix="$target_volume" ;;\n'
        "esac\n"
        f"install_prefix={json.dumps(str(install_prefix))}\n"
        'runtime_root="${target_prefix}${install_prefix}/runtime"\n'
        'installer_path="${runtime_root}/scripts/install_stock_codex_compat_launcher.py"\n'
        'provisioner_path="${runtime_root}/scripts/provision_stock_codex.py"\n'
        'bootstrap_shell_path="${runtime_root}/scripts/bootstrap_stock_codex_compat.sh"\n'
        'bootstrap_python_path="${runtime_root}/scripts/bootstrap_stock_codex_compat.py"\n'
        'if [ ! -d "$runtime_root" ]; then\n'
        '  echo "Omnigent runtime root missing: $runtime_root" >&2\n'
        "  exit 1\n"
        "fi\n"
        'if [ ! -f "$installer_path" ]; then\n'
        '  echo "Omnigent compatibility installer missing: $installer_path" >&2\n'
        "  exit 1\n"
        "fi\n"
        'if [ ! -f "$provisioner_path" ]; then\n'
        '  echo "Omnigent stock Codex provisioner missing: $provisioner_path" >&2\n'
        "  exit 1\n"
        "fi\n"
        'if [ ! -f "$bootstrap_shell_path" ]; then\n'
        '  echo "Omnigent stock Codex bootstrapper missing: $bootstrap_shell_path" >&2\n'
        "  exit 1\n"
        "fi\n"
        'if [ ! -f "$bootstrap_python_path" ]; then\n'
        '  echo "Omnigent stock Codex bootstrapper missing: $bootstrap_python_path" >&2\n'
        "  exit 1\n"
        "fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    script_path.chmod(0o755)


def _normalize_payload_path(path: Path) -> str:
    return path.as_posix().lstrip("./")


def _relative_payload_files(payload_root: Path) -> tuple[str, ...]:
    entries = []
    for path in payload_root.rglob("*"):
        if path.is_dir():
            continue
        relative = _normalize_payload_path(path.relative_to(payload_root))
        if Path(relative).name.startswith("._"):
            continue
        entries.append(relative)
    return tuple(sorted(entries))


def _signature_status(package_path: Path) -> tuple[str, bool]:
    completed = subprocess.run(
        ["pkgutil", "--check-signature", str(package_path)],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    output = ((completed.stdout or "") + (completed.stderr or "")).strip()
    status = "unknown"
    for line in output.splitlines():
        stripped = line.strip()
        if stripped.startswith("Status:"):
            status = stripped.split(":", 1)[1].strip()
            break
    return status, status.lower() != "no signature"


def _archive_entries(package_path: Path) -> tuple[str, ...]:
    xar = shutil.which("xar")
    if not xar:
        return ()
    completed = subprocess.run(
        [xar, "-tf", str(package_path)],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if completed.returncode != 0:
        return ()
    return tuple(sorted(line.strip() for line in completed.stdout.splitlines() if line.strip()))


def _parse_package_info(path: Path) -> ET.Element:
    try:
        return ET.fromstring(path.read_text(encoding="utf-8"))
    except (OSError, ET.ParseError) as exc:
        raise PkgBuildError(f"Could not parse PackageInfo: {path}") from exc


def _json_file(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PkgBuildError(f"Could not read JSON file: {path}") from exc
    if not isinstance(payload, dict):
        raise PkgBuildError(f"JSON file did not contain an object: {path}")
    return payload


def inspect_stock_codex_compat_pkg(
    package_path: Path,
    *,
    expand_dir: Path,
) -> StockCodexCompatPkgInspection:
    """Expand and inspect a stock-Codex compatibility pkg without installing it."""
    package_path = package_path.expanduser().resolve()
    if not package_path.is_file():
        raise PkgBuildError(f"Package does not exist: {package_path}")
    _require_tool("pkgutil")
    if expand_dir.exists():
        shutil.rmtree(expand_dir)
    expand_dir.parent.mkdir(parents=True, exist_ok=True)
    _run_checked(
        ["pkgutil", "--expand-full", str(package_path), str(expand_dir)],
        timeout=120,
    )
    package_info_path = expand_dir / "PackageInfo"
    package_info = _parse_package_info(package_info_path)
    package_identifier = package_info.attrib.get("identifier", "")
    package_version = package_info.attrib.get("version", "")
    install_location = package_info.attrib.get("install-location", "")
    payload_root = expand_dir / "Payload"
    scripts_root = expand_dir / "Scripts"
    payload_files = _relative_payload_files(payload_root)
    script_names = tuple(
        sorted(path.name for path in scripts_root.iterdir() if path.is_file())
    ) if scripts_root.is_dir() else ()

    install_prefix = payload_root / DEFAULT_INSTALL_PREFIX.relative_to("/")
    pkg_manifest_path = install_prefix / PKG_MANIFEST_NAME
    bundle_manifest_path = install_prefix / BUNDLE_MANIFEST_NAME
    postinstall_path = scripts_root / POSTINSTALL_NAME
    pkg_manifest = _json_file(pkg_manifest_path)
    bundle_manifest = _json_file(bundle_manifest_path)
    signature_status, signed = _signature_status(package_path)

    return StockCodexCompatPkgInspection(
        package_identifier=package_identifier,
        package_version=package_version,
        install_location=install_location,
        install_prefix=DEFAULT_INSTALL_PREFIX,
        runtime_root=DEFAULT_INSTALL_PREFIX / RUNTIME_ROOT_NAME,
        package_info_path=package_info_path,
        pkg_manifest_path=pkg_manifest_path,
        bundle_manifest_path=bundle_manifest_path,
        postinstall_path=postinstall_path,
        payload_files=payload_files,
        script_names=script_names,
        archive_entries=_archive_entries(package_path),
        signature_status=signature_status,
        signed=signed,
        pkg_manifest=pkg_manifest,
        bundle_manifest=bundle_manifest,
    )


def _copy_runtime_payload(
    *,
    extracted_bundle_root: Path,
    install_prefix_root: Path,
    source_bundle_sha256: str,
    package_identifier: str,
    package_version: str,
    install_prefix: Path,
    created_at: str,
    signed_package: bool = False,
) -> None:
    runtime_source = extracted_bundle_root / RUNTIME_ROOT_NAME
    bundle_manifest_source = extracted_bundle_root / BUNDLE_MANIFEST_NAME
    if not runtime_source.is_dir():
        raise PkgBuildError(f"Extracted bundle runtime root is missing: {runtime_source}")
    if not bundle_manifest_source.is_file():
        raise PkgBuildError(f"Extracted bundle manifest is missing: {bundle_manifest_source}")
    install_prefix_root.mkdir(parents=True, exist_ok=True)
    shutil.copytree(runtime_source, install_prefix_root / RUNTIME_ROOT_NAME, symlinks=True)

    bundle_manifest = _json_file(bundle_manifest_source)
    bundle_manifest["sourceRoot"] = "<omitted-from-pkg>"
    bundle_manifest["packagedBy"] = PKG_KIND
    bundle_manifest["sourceBundleSha256"] = source_bundle_sha256
    (install_prefix_root / BUNDLE_MANIFEST_NAME).write_text(
        json.dumps(bundle_manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    contract = {
        "package": "signed-flat-pkg-structure"
        if signed_package
        else "unsigned-flat-pkg-structure",
        "runtime": "machine-level-runtime-only",
        "userBootstrap": "deferred-to-installed-runtime-command",
        "stockCodexProvisioning": "deferred-to-installed-runtime-command",
        "stockCodex": "external-pinned-payload",
        "auth": "not-packaged",
    }
    if signed_package:
        contract["signature"] = "developer-id-installer"

    pkg_manifest = {
        "kind": PKG_KIND,
        "schemaVersion": PKG_SCHEMA_VERSION,
        "createdAt": created_at,
        "packageIdentifier": package_identifier,
        "packageVersion": package_version,
        "installLocation": "/",
        "installPrefix": str(install_prefix),
        "runtimeRoot": str(install_prefix / RUNTIME_ROOT_NAME),
        "installer": str(install_prefix / RUNTIME_ROOT_NAME / INSTALLER_RELATIVE_PATH),
        "stockCodexProvisioner": str(
            install_prefix / RUNTIME_ROOT_NAME / PROVISIONER_RELATIVE_PATH
        ),
        "userBootstrapper": str(
            install_prefix / RUNTIME_ROOT_NAME / BOOTSTRAP_SHELL_RELATIVE_PATH
        ),
        "userBootstrapperPython": str(
            install_prefix / RUNTIME_ROOT_NAME / BOOTSTRAP_PYTHON_RELATIVE_PATH
        ),
        "wrapperEntrypoint": "omnigent-stock-codex-wrapper",
        "defaultLauncherCommand": "omnigent-stock-codex-compat",
        "sourceBundleSha256": source_bundle_sha256,
        "contract": contract,
    }
    (install_prefix_root / PKG_MANIFEST_NAME).write_text(
        json.dumps(pkg_manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _pkgbuild_command(
    *,
    pkgbuild: str,
    payload_root: Path,
    scripts_root: Path,
    package_identifier: str,
    package_version: str,
    output_path: Path,
    sign_identity: str | None = None,
    signing_keychain: Path | None = None,
) -> list[str]:
    """Build the pkgbuild command, including optional Developer ID signing."""
    command = [
        pkgbuild,
        "--root",
        str(payload_root),
        "--scripts",
        str(scripts_root),
        "--identifier",
        package_identifier,
        "--version",
        package_version,
        "--install-location",
        "/",
        "--ownership",
        "recommended",
    ]
    if sign_identity:
        command.extend(["--sign", sign_identity])
        if signing_keychain is not None:
            command.extend(["--keychain", str(signing_keychain)])
        command.append("--timestamp")
    command.append(str(output_path))
    return command


def build_stock_codex_compat_pkg(
    *,
    repo_root: Path,
    output_path: Path,
    force: bool = False,
    package_identifier: str = DEFAULT_PACKAGE_IDENTIFIER,
    package_version: str | None = None,
    install_prefix: Path = DEFAULT_INSTALL_PREFIX,
    sign_identity: str | None = None,
    signing_keychain: Path | None = None,
) -> StockCodexCompatPkgBuildResult:
    """Build and inspect a flat pkg from the portable runtime bundle."""
    repo_root = repo_root.expanduser().resolve()
    output_path = output_path.expanduser()
    signing_keychain = (
        signing_keychain.expanduser().resolve() if signing_keychain is not None else None
    )
    if output_path.exists() and not force:
        raise PkgBuildError(f"Package already exists; rerun with --force: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    package_version = package_version or _read_project_version(repo_root)
    pkgbuild = _require_tool("pkgbuild")
    _require_tool("pkgutil")
    created_at = datetime.now(timezone.utc).isoformat()
    bundle_builder = _load_bundle_builder()

    with tempfile.TemporaryDirectory(prefix="omnigent-stock-codex-compat-pkg-") as temp_root:
        root = Path(temp_root).resolve()
        bundle_path = root / "omnigent-stock-codex-compat-bundle.tar.gz"
        bundle_result = bundle_builder.build_stock_codex_compat_bundle(
            repo_root=repo_root,
            output_path=bundle_path,
            force=True,
        )
        source_bundle_sha256 = str(bundle_result.sha256)
        extract_root = root / "bundle-extract"
        _safe_extract_tar_gz(bundle_path, extract_root)
        extracted_bundle_root = extract_root / str(bundle_result.bundle_root_name)

        payload_root = root / "payload"
        install_prefix_root = payload_root / install_prefix.relative_to("/")
        _copy_runtime_payload(
            extracted_bundle_root=extracted_bundle_root,
            install_prefix_root=install_prefix_root,
            source_bundle_sha256=source_bundle_sha256,
            package_identifier=package_identifier,
            package_version=package_version,
            install_prefix=install_prefix,
            created_at=created_at,
            signed_package=bool(sign_identity),
        )
        scripts_root = root / "scripts"
        scripts_root.mkdir()
        _write_postinstall(scripts_root / POSTINSTALL_NAME, install_prefix=install_prefix)
        _strip_xattrs(payload_root)
        _strip_xattrs(scripts_root)

        env = os.environ.copy()
        env["COPYFILE_DISABLE"] = "1"
        _run_checked(
            _pkgbuild_command(
                pkgbuild=pkgbuild,
                payload_root=payload_root,
                scripts_root=scripts_root,
                package_identifier=package_identifier,
                package_version=package_version,
                output_path=output_path,
                sign_identity=sign_identity,
                signing_keychain=signing_keychain,
            ),
            cwd=repo_root,
            env=env,
            timeout=180,
        )
        inspection = inspect_stock_codex_compat_pkg(
            output_path,
            expand_dir=root / "pkg-expanded",
        )

    return StockCodexCompatPkgBuildResult(
        package_path=output_path.resolve(),
        package_sha256=sha256_file(output_path),
        source_root=repo_root,
        source_bundle_path=bundle_path,
        source_bundle_sha256=source_bundle_sha256,
        package_identifier=package_identifier,
        package_version=package_version,
        install_location="/",
        install_prefix=install_prefix,
        signing_identity=sign_identity,
        signing_keychain=signing_keychain,
        runtime_root=install_prefix / RUNTIME_ROOT_NAME,
        included_payload_file_count=len(inspection.payload_files),
        created_at=created_at,
        inspection=inspection,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build the stock-Codex compatibility macOS pkg."
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output .pkg path. Defaults to dist/omnigent-stock-codex-compat.pkg.",
    )
    parser.add_argument("--identifier", default=DEFAULT_PACKAGE_IDENTIFIER)
    parser.add_argument("--version", default=None)
    parser.add_argument("--install-prefix", type=Path, default=DEFAULT_INSTALL_PREFIX)
    parser.add_argument(
        "--sign-identity",
        default=None,
        help="Optional Developer ID Installer identity to sign the pkg.",
    )
    parser.add_argument(
        "--signing-keychain",
        type=Path,
        default=None,
        help="Optional keychain path containing the signing identity.",
    )
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def print_result(result: StockCodexCompatPkgBuildResult, *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result.as_dict(), indent=2, sort_keys=True))
        return
    print(f"stock_codex_compat_pkg_path={result.package_path}")
    print(f"stock_codex_compat_pkg_sha256={result.package_sha256}")
    print(f"stock_codex_compat_pkg_identifier={result.package_identifier}")
    print(f"stock_codex_compat_pkg_version={result.package_version}")
    print(f"stock_codex_compat_pkg_install_location={result.install_location}")
    print(f"stock_codex_compat_pkg_install_prefix={result.install_prefix}")
    print(f"stock_codex_compat_pkg_signing_identity={result.signing_identity}")
    print(f"stock_codex_compat_pkg_signing_keychain={result.signing_keychain}")
    print(f"stock_codex_compat_pkg_runtime_root={result.runtime_root}")
    print(f"stock_codex_compat_pkg_signature_status={result.inspection.signature_status}")
    print(f"stock_codex_compat_pkg_signed={result.inspection.signed}")
    print(f"stock_codex_compat_pkg_payload_file_count={result.included_payload_file_count}")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    output_path = args.output
    if output_path is None:
        output_path = args.repo_root / "dist" / DEFAULT_OUTPUT_NAME
    try:
        result = build_stock_codex_compat_pkg(
            repo_root=args.repo_root,
            output_path=output_path,
            force=args.force,
            package_identifier=args.identifier,
            package_version=args.version,
            install_prefix=args.install_prefix,
            sign_identity=args.sign_identity,
            signing_keychain=args.signing_keychain,
        )
    except PkgBuildError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print_result(result, as_json=args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
