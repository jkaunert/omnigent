#!/usr/bin/env python3
"""Build a portable stock-Codex compatibility runtime bundle."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import tarfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

BUNDLE_KIND = "omnigent-stock-codex-compat-bundle"
BUNDLE_SCHEMA_VERSION = 1
BUNDLE_ROOT_NAME = "omnigent-stock-codex-compat-bundle"
BUNDLE_MANIFEST_NAME = "bundle-manifest.json"
RUNTIME_ROOT_NAME = "runtime"
INSTALLER_RELATIVE_PATH = "scripts/install_stock_codex_compat_launcher.py"
PROVISIONER_RELATIVE_PATH = "scripts/provision_stock_codex.py"
UPDATER_RELATIVE_PATH = "scripts/update_stock_codex_compat.py"
BOOTSTRAP_SHELL_RELATIVE_PATH = "scripts/bootstrap_stock_codex_compat.sh"
BOOTSTRAP_PYTHON_RELATIVE_PATH = "scripts/bootstrap_stock_codex_compat.py"
WRAPPER_ENTRYPOINT = "omnigent-stock-codex-wrapper"
DEFAULT_LAUNCHER_COMMAND = "omnigent-stock-codex-compat"

RUNTIME_TOP_LEVEL_FILES = (
    "pyproject.toml",
    "uv.lock",
    "README.md",
    "LICENSE",
)
RUNTIME_DIRECTORIES = (
    "omnigent",
    "sdks",
)
EXCLUDED_DIRECTORY_NAMES = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "venv",
}
EXCLUDED_FILE_SUFFIXES = {
    ".pyc",
    ".pyo",
}


@dataclass(frozen=True)
class StockCodexCompatBundleBuildResult:
    """Result of building a stock-Codex compatibility bundle archive."""

    bundle_path: Path
    sha256: str
    source_root: Path
    bundle_root_name: str
    runtime_root: str
    installer: str
    manifest_name: str
    included_file_count: int
    created_at: str

    def as_dict(self) -> dict[str, object]:
        return {
            "kind": BUNDLE_KIND,
            "schemaVersion": BUNDLE_SCHEMA_VERSION,
            "bundlePath": str(self.bundle_path),
            "sha256": self.sha256,
            "sourceRoot": str(self.source_root),
            "bundleRootName": self.bundle_root_name,
            "runtimeRoot": self.runtime_root,
            "installer": self.installer,
            "manifestName": self.manifest_name,
            "includedFileCount": self.included_file_count,
            "createdAt": self.created_at,
        }


class BundleBuildError(RuntimeError):
    """The stock-Codex compatibility bundle could not be built."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_excluded(path: Path) -> bool:
    if any(part in EXCLUDED_DIRECTORY_NAMES for part in path.parts):
        return True
    return path.suffix in EXCLUDED_FILE_SUFFIXES


def _iter_files_under(root: Path) -> list[Path]:
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and not path.is_symlink() and not _is_excluded(path)
    )


def iter_runtime_sources(repo_root: Path) -> list[tuple[Path, Path]]:
    """Return ``(source_path, runtime_relative_path)`` entries for the bundle."""
    repo_root = repo_root.expanduser().resolve()
    required_paths = [
        repo_root / "pyproject.toml",
        repo_root / "omnigent",
        repo_root / INSTALLER_RELATIVE_PATH,
        repo_root / PROVISIONER_RELATIVE_PATH,
        repo_root / UPDATER_RELATIVE_PATH,
        repo_root / BOOTSTRAP_SHELL_RELATIVE_PATH,
        repo_root / BOOTSTRAP_PYTHON_RELATIVE_PATH,
    ]
    missing = [str(path) for path in required_paths if not path.exists()]
    if missing:
        raise BundleBuildError(
            "Repo root is missing required bundle inputs: " + ", ".join(missing)
        )

    entries: list[tuple[Path, Path]] = []
    seen: set[Path] = set()

    def add_path(path: Path, relative: Path) -> None:
        resolved = path.resolve()
        if resolved in seen:
            return
        seen.add(resolved)
        entries.append((resolved, relative))

    for name in RUNTIME_TOP_LEVEL_FILES:
        path = repo_root / name
        if path.is_file() and not path.is_symlink():
            add_path(path, Path(name))

    for directory_name in RUNTIME_DIRECTORIES:
        directory = repo_root / directory_name
        if not directory.exists():
            continue
        if not directory.is_dir():
            raise BundleBuildError(f"Runtime input is not a directory: {directory}")
        for path in _iter_files_under(directory):
            add_path(path, path.relative_to(repo_root))

    installer_path = repo_root / INSTALLER_RELATIVE_PATH
    add_path(installer_path, Path(INSTALLER_RELATIVE_PATH))
    provisioner_path = repo_root / PROVISIONER_RELATIVE_PATH
    add_path(provisioner_path, Path(PROVISIONER_RELATIVE_PATH))
    updater_path = repo_root / UPDATER_RELATIVE_PATH
    add_path(updater_path, Path(UPDATER_RELATIVE_PATH))
    bootstrap_shell_path = repo_root / BOOTSTRAP_SHELL_RELATIVE_PATH
    add_path(bootstrap_shell_path, Path(BOOTSTRAP_SHELL_RELATIVE_PATH))
    bootstrap_python_path = repo_root / BOOTSTRAP_PYTHON_RELATIVE_PATH
    add_path(bootstrap_python_path, Path(BOOTSTRAP_PYTHON_RELATIVE_PATH))
    return sorted(entries, key=lambda item: item[1].as_posix())


def _add_bytes(
    archive: tarfile.TarFile,
    *,
    arcname: str,
    data: bytes,
    mode: int = 0o644,
) -> None:
    info = tarfile.TarInfo(arcname)
    info.size = len(data)
    info.mode = mode
    info.mtime = 0
    info.uid = 0
    info.gid = 0
    info.uname = "root"
    info.gname = "root"
    archive.addfile(info, io.BytesIO(data))


def _add_file(archive: tarfile.TarFile, *, source: Path, arcname: str) -> None:
    info = archive.gettarinfo(str(source), arcname=arcname)
    info.mtime = 0
    info.uid = 0
    info.gid = 0
    info.uname = "root"
    info.gname = "root"
    with source.open("rb") as handle:
        archive.addfile(info, handle)


def build_stock_codex_compat_bundle(
    *,
    repo_root: Path,
    output_path: Path,
    force: bool = False,
) -> StockCodexCompatBundleBuildResult:
    """Build a tar.gz bundle containing the runtime needed by the compat launcher."""
    repo_root = repo_root.expanduser().resolve()
    output_path = output_path.expanduser()
    if output_path.exists() and not force:
        raise BundleBuildError(f"Bundle already exists; rerun with --force: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    runtime_sources = iter_runtime_sources(repo_root)
    created_at = datetime.now(timezone.utc).isoformat()
    manifest = {
        "kind": BUNDLE_KIND,
        "schemaVersion": BUNDLE_SCHEMA_VERSION,
        "createdAt": created_at,
        "sourceRoot": str(repo_root),
        "bundleRootName": BUNDLE_ROOT_NAME,
        "runtimeRoot": RUNTIME_ROOT_NAME,
        "installer": f"{RUNTIME_ROOT_NAME}/{INSTALLER_RELATIVE_PATH}",
        "stockCodexProvisioner": f"{RUNTIME_ROOT_NAME}/{PROVISIONER_RELATIVE_PATH}",
        "stockCodexUpdater": f"{RUNTIME_ROOT_NAME}/{UPDATER_RELATIVE_PATH}",
        "userBootstrapper": f"{RUNTIME_ROOT_NAME}/{BOOTSTRAP_SHELL_RELATIVE_PATH}",
        "userBootstrapperPython": f"{RUNTIME_ROOT_NAME}/{BOOTSTRAP_PYTHON_RELATIVE_PATH}",
        "wrapperEntrypoint": WRAPPER_ENTRYPOINT,
        "defaultLauncherCommand": DEFAULT_LAUNCHER_COMMAND,
        "includedFileCount": len(runtime_sources),
        "contract": {
            "launcher": "separate-managed-compatibility-command",
            "stockCodex": "external-pinned-payload",
            "mutationBoundary": "user-home-defaults-only-at-install-time",
        },
    }

    with tarfile.open(output_path, "w:gz") as archive:
        _add_bytes(
            archive,
            arcname=f"{BUNDLE_ROOT_NAME}/{BUNDLE_MANIFEST_NAME}",
            data=(json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode(
                "utf-8"
            ),
        )
        for source, relative in runtime_sources:
            _add_file(
                archive,
                source=source,
                arcname=(
                    f"{BUNDLE_ROOT_NAME}/{RUNTIME_ROOT_NAME}/"
                    f"{relative.as_posix()}"
                ),
            )

    return StockCodexCompatBundleBuildResult(
        bundle_path=output_path.resolve(),
        sha256=sha256_file(output_path),
        source_root=repo_root,
        bundle_root_name=BUNDLE_ROOT_NAME,
        runtime_root=RUNTIME_ROOT_NAME,
        installer=f"{RUNTIME_ROOT_NAME}/{INSTALLER_RELATIVE_PATH}",
        manifest_name=BUNDLE_MANIFEST_NAME,
        included_file_count=len(runtime_sources),
        created_at=created_at,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build the stock-Codex compatibility runtime bundle."
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
        help="Output .tar.gz path. Defaults to dist/stock-codex-compat bundle.",
    )
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def print_result(
    result: StockCodexCompatBundleBuildResult,
    *,
    as_json: bool,
) -> None:
    if as_json:
        print(json.dumps(result.as_dict(), indent=2, sort_keys=True))
        return
    print(f"stock_codex_compat_bundle_path={result.bundle_path}")
    print(f"stock_codex_compat_bundle_sha256={result.sha256}")
    print(f"stock_codex_compat_bundle_source_root={result.source_root}")
    print(f"stock_codex_compat_bundle_runtime_root={result.runtime_root}")
    print(f"stock_codex_compat_bundle_installer={result.installer}")
    print(f"stock_codex_compat_bundle_file_count={result.included_file_count}")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    output_path = args.output
    if output_path is None:
        output_path = (
            args.repo_root
            / "dist"
            / "omnigent-stock-codex-compat-bundle.tar.gz"
        )
    try:
        result = build_stock_codex_compat_bundle(
            repo_root=args.repo_root,
            output_path=output_path,
            force=args.force,
        )
    except BundleBuildError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print_result(result, as_json=args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
