"""Tests for ``scripts/provision_stock_codex.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
import tarfile
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "provision_stock_codex.py"


def _load_module() -> Any:
    spec = importlib.util.spec_from_file_location(
        "scripts_provision_stock_codex",
        _SCRIPT_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_MOD = _load_module()


def _write_codex_binary(path: Path, *, version: str = "codex-cli 0.142.2") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""#!/bin/sh
if [ "${{1:-}}" = "--version" ]; then
  cat <<'EOF'
{version}
EOF
  exit 0
fi
printf 'fake codex\\n'
""",
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        return


def _serve_directory(directory: Path) -> tuple[ThreadingHTTPServer, str]:
    handler = partial(_QuietHandler, directory=str(directory))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    return server, f"http://{host}:{port}"


def _write_codex_tarball(
    archive_path: Path,
    *,
    member_name: str = "codex-aarch64-apple-darwin",
    version: str = "codex-cli 0.142.2",
) -> Path:
    source_binary = _write_codex_binary(
        archive_path.parent / "archive-source" / member_name,
        version=version,
    )
    with tarfile.open(archive_path, "w:gz") as archive:
        archive.add(source_binary, arcname=member_name)
    return archive_path


def test_provision_stock_codex_copies_source_to_version_cache(tmp_path: Path) -> None:
    source_binary = _write_codex_binary(tmp_path / "source" / "codex")
    cache_root = tmp_path / "cache"

    provisioned = _MOD.provision_stock_codex(
        cache_root=cache_root,
        source_binary=source_binary,
        expected_sha256=None,
        force=False,
        allow_fork_codex=False,
    )

    expected_payload_dir = cache_root / "0.142.2"
    assert provisioned.payload_dir == expected_payload_dir
    assert provisioned.codex_path == expected_payload_dir / "codex"
    assert provisioned.manifest_path == expected_payload_dir / _MOD.MANIFEST_NAME
    assert provisioned.version == "codex-cli 0.142.2"
    assert provisioned.sha256 == _MOD.sha256_file(source_binary)
    assert provisioned.as_dict()["env"] == {
        _MOD.OMNIGENT_STOCK_CODEX_PATH_ENV: str(expected_payload_dir / "codex")
    }


def test_provision_stock_codex_expected_sha_mismatch_fails(tmp_path: Path) -> None:
    source_binary = _write_codex_binary(tmp_path / "source" / "codex")

    with pytest.raises(_MOD.ProvisioningError, match="Source Codex sha256 mismatch"):
        _MOD.provision_stock_codex(
            cache_root=tmp_path / "cache",
            source_binary=source_binary,
            expected_sha256="0" * 64,
            force=False,
            allow_fork_codex=False,
        )


def test_provision_stock_codex_reuses_verified_existing_payload(tmp_path: Path) -> None:
    source_binary = _write_codex_binary(tmp_path / "source" / "codex")
    cache_root = tmp_path / "cache"

    first = _MOD.provision_stock_codex(
        cache_root=cache_root,
        source_binary=source_binary,
        expected_sha256=None,
        force=False,
        allow_fork_codex=False,
    )
    second = _MOD.provision_stock_codex(
        cache_root=cache_root,
        source_binary=source_binary,
        expected_sha256=None,
        force=False,
        allow_fork_codex=False,
    )

    assert second.codex_path == first.codex_path
    assert second.sha256 == first.sha256


def test_provision_stock_codex_existing_mismatch_requires_force(tmp_path: Path) -> None:
    source_binary = _write_codex_binary(tmp_path / "source" / "codex")
    cache_root = tmp_path / "cache"
    provisioned = _MOD.provision_stock_codex(
        cache_root=cache_root,
        source_binary=source_binary,
        expected_sha256=None,
        force=False,
        allow_fork_codex=False,
    )
    _write_codex_binary(provisioned.codex_path, version="codex-cli 0.142.2")
    with provisioned.codex_path.open("a", encoding="utf-8") as handle:
        handle.write("# tampered\n")

    with pytest.raises(_MOD.ProvisioningError, match="Rerun with --force"):
        _MOD.provision_stock_codex(
            cache_root=cache_root,
            source_binary=source_binary,
            expected_sha256=None,
            force=False,
            allow_fork_codex=False,
        )


def test_main_prints_shell_env_for_source_binary(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source_binary = _write_codex_binary(tmp_path / "source" / "codex")
    cache_root = tmp_path / "cache"

    rc = _MOD.main(
        [
            "--source-binary",
            str(source_binary),
            "--cache-root",
            str(cache_root),
            "--print-shell-env",
        ]
    )

    expected_codex_path = cache_root / "0.142.2" / "codex"
    assert rc == 0
    assert capsys.readouterr().out.strip() == (
        f"export {_MOD.OMNIGENT_STOCK_CODEX_PATH_ENV}='{expected_codex_path}'"
    )


def test_resolve_source_codex_rejects_codex_fork_path(tmp_path: Path) -> None:
    source_binary = _write_codex_binary(tmp_path / ".codex-fork" / "bin" / "codex")

    with pytest.raises(_MOD.ProvisioningError, match="Codex-fork binary"):
        _MOD.resolve_source_codex(source_binary, allow_fork_codex=False)

    assert _MOD.resolve_source_codex(source_binary, allow_fork_codex=True) == source_binary


def test_provision_stock_codex_from_channel_manifest(tmp_path: Path) -> None:
    source_binary = _write_codex_binary(tmp_path / "artifacts" / "codex")
    source_sha = _MOD.sha256_file(source_binary)
    channel_manifest = tmp_path / "channel.json"
    channel_manifest.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "kind": _MOD.CHANNEL_MANIFEST_KIND,
                "latest": "0.142.2",
                "artifacts": [
                    {
                        "version": "codex-cli 0.142.2",
                        "platform": _MOD.current_channel_platform(),
                        "path": "artifacts/codex",
                        "sha256": source_sha,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    provisioned = _MOD.provision_stock_codex_from_channel(
        cache_root=tmp_path / "cache",
        channel_manifest=channel_manifest,
        channel_version=None,
        channel_platform=None,
        expected_sha256=source_sha,
        force=False,
        allow_fork_codex=False,
        allow_remote_channel_download=False,
    )

    assert provisioned.version == "codex-cli 0.142.2"
    assert provisioned.source_kind == "channel"
    assert provisioned.channel_manifest_path == channel_manifest
    assert provisioned.channel_artifact == {
        "path": "artifacts/codex",
        "platform": _MOD.current_channel_platform(),
        "sha256": source_sha,
        "version": "codex-cli 0.142.2",
        "versionSlug": "0.142.2",
    }
    manifest = json.loads(provisioned.manifest_path.read_text(encoding="utf-8"))
    assert manifest["sourceKind"] == "channel"
    assert manifest["sourcePath"] == str(source_binary)
    assert manifest["sourceRealpath"] == str(source_binary.resolve())
    assert manifest["channelManifestPath"] == str(channel_manifest)


def test_channel_manifest_requires_opt_in_for_remote_urls(tmp_path: Path) -> None:
    channel_manifest = tmp_path / "channel.json"
    channel_manifest.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "kind": _MOD.CHANNEL_MANIFEST_KIND,
                "latest": "codex-cli 0.142.2",
                "artifacts": [
                    {
                        "version": "codex-cli 0.142.2",
                        "platform": _MOD.current_channel_platform(),
                        "url": "https://example.invalid/codex",
                        "sha256": "0" * 64,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(_MOD.ProvisioningError, match="allow-remote-channel-download"):
        _MOD.provision_stock_codex_from_channel(
            cache_root=tmp_path / "cache",
            channel_manifest=channel_manifest,
            channel_version=None,
            channel_platform=None,
            expected_sha256=None,
            force=False,
            allow_fork_codex=False,
            allow_remote_channel_download=False,
        )


def test_provision_stock_codex_from_remote_archive_channel_manifest(tmp_path: Path) -> None:
    archive_path = _write_codex_tarball(tmp_path / "codex.tar.gz")
    archive_sha = _MOD.sha256_file(archive_path)
    server, base_url = _serve_directory(tmp_path)
    try:
        channel_manifest = tmp_path / "channel.json"
        channel_manifest.write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "kind": _MOD.CHANNEL_MANIFEST_KIND,
                    "latest": "0.142.2",
                    "artifacts": [
                        {
                            "version": "codex-cli 0.142.2",
                            "platform": _MOD.current_channel_platform(),
                            "url": f"{base_url}/codex.tar.gz",
                            "sha256": archive_sha,
                            "archiveFormat": "tar.gz",
                            "archiveExecutable": "codex-aarch64-apple-darwin",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        provisioned = _MOD.provision_stock_codex_from_channel(
            cache_root=tmp_path / "cache",
            channel_manifest=channel_manifest,
            channel_version=None,
            channel_platform=None,
            expected_sha256=archive_sha,
            force=False,
            allow_fork_codex=False,
            allow_remote_channel_download=True,
        )
    finally:
        server.shutdown()
        server.server_close()

    assert provisioned.version == "codex-cli 0.142.2"
    assert provisioned.source_kind == "channel"
    assert provisioned.sha256 == _MOD.sha256_file(provisioned.codex_path)
    assert provisioned.channel_artifact == {
        "archiveExecutable": "codex-aarch64-apple-darwin",
        "archiveFormat": "tar.gz",
        "platform": _MOD.current_channel_platform(),
        "sha256": archive_sha,
        "url": f"{base_url}/codex.tar.gz",
        "version": "codex-cli 0.142.2",
        "versionSlug": "0.142.2",
    }
    manifest = json.loads(provisioned.manifest_path.read_text(encoding="utf-8"))
    assert manifest["sourcePath"] == f"{base_url}/codex.tar.gz"
    assert manifest["sourceRealpath"] == f"{base_url}/codex.tar.gz"
    assert manifest["channelArtifact"]["sha256"] == archive_sha
    assert manifest["sha256"] == provisioned.sha256


def test_channel_manifest_sha_mismatch_fails_before_install(tmp_path: Path) -> None:
    source_binary = _write_codex_binary(tmp_path / "artifacts" / "codex")
    channel_manifest = tmp_path / "channel.json"
    channel_manifest.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "kind": _MOD.CHANNEL_MANIFEST_KIND,
                "latest": "codex-cli 0.142.2",
                "artifacts": [
                    {
                        "version": "codex-cli 0.142.2",
                        "platform": _MOD.current_channel_platform(),
                        "path": str(source_binary),
                        "sha256": "0" * 64,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(_MOD.ProvisioningError, match="Channel artifact sha256 mismatch"):
        _MOD.provision_stock_codex_from_channel(
            cache_root=tmp_path / "cache",
            channel_manifest=channel_manifest,
            channel_version=None,
            channel_platform=None,
            expected_sha256=None,
            force=False,
            allow_fork_codex=False,
            allow_remote_channel_download=False,
        )
    assert not (tmp_path / "cache").exists()


def test_channel_manifest_requires_unambiguous_latest(tmp_path: Path) -> None:
    first = _write_codex_binary(tmp_path / "artifacts" / "codex-1")
    second = _write_codex_binary(
        tmp_path / "artifacts" / "codex-2",
        version="codex-cli 0.143.0",
    )
    channel_manifest = tmp_path / "channel.json"
    channel_manifest.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "kind": _MOD.CHANNEL_MANIFEST_KIND,
                "artifacts": [
                    {
                        "version": "codex-cli 0.142.2",
                        "platform": _MOD.current_channel_platform(),
                        "path": str(first),
                        "sha256": _MOD.sha256_file(first),
                    },
                    {
                        "version": "codex-cli 0.143.0",
                        "platform": _MOD.current_channel_platform(),
                        "path": str(second),
                        "sha256": _MOD.sha256_file(second),
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(_MOD.ProvisioningError, match="multiple platform-matching"):
        _MOD.select_channel_artifact(
            channel_manifest=channel_manifest,
            requested_version=None,
            requested_platform=None,
        )

    selected = _MOD.select_channel_artifact(
        channel_manifest=channel_manifest,
        requested_version="0.143.0",
        requested_platform=None,
    )
    assert selected.version == "codex-cli 0.143.0"


def test_main_rejects_channel_options_without_channel_manifest(
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = _MOD.main(["--channel-version", "0.142.2"])

    assert rc == 1
    assert "--channel-version and --channel-platform require --channel-manifest" in (
        capsys.readouterr().err
    )


def test_main_rejects_remote_download_flag_without_channel_manifest(
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = _MOD.main(["--allow-remote-channel-download"])

    assert rc == 1
    assert "--allow-remote-channel-download requires --channel-manifest" in (
        capsys.readouterr().err
    )
