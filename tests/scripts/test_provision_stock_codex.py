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


def _official_archive_url(
    *,
    version_slug: str = "0.143.0",
    archive_executable: str = "codex-aarch64-apple-darwin",
) -> str:
    return (
        "https://github.com/openai/codex/releases/download/"
        f"rust-v{version_slug}/{archive_executable}.tar.gz"
    )


def _write_official_channel_manifest(
    path: Path,
    *,
    version: str = "codex-cli 0.143.0",
    archive_sha: str = "b" * 64,
    archive_executable: str = "codex-aarch64-apple-darwin",
    url: str | None = None,
) -> Path:
    version_slug = _MOD.version_slug(version)
    path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "kind": _MOD.CHANNEL_MANIFEST_KIND,
                "latest": version_slug,
                "artifacts": [
                    {
                        "version": version,
                        "platform": _MOD.current_channel_platform(),
                        "url": url
                        or _official_archive_url(
                            version_slug=version_slug,
                            archive_executable=archive_executable,
                        ),
                        "sha256": archive_sha,
                        "archiveFormat": "tar.gz",
                        "archiveExecutable": archive_executable,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


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


def test_official_openai_github_channel_policy_accepts_release_archive() -> None:
    artifact = _MOD.StockCodexChannelArtifact(
        version="codex-cli 0.142.2",
        platform=_MOD.current_channel_platform(),
        source=(
            "https://github.com/openai/codex/releases/download/"
            "rust-v0.142.2/codex-aarch64-apple-darwin.tar.gz"
        ),
        source_field="url",
        sha256="a" * 64,
        archive_format="tar.gz",
        archive_executable="codex-aarch64-apple-darwin",
    )

    _MOD.validate_channel_artifact_policy(
        artifact,
        policy_name=_MOD.OFFICIAL_OPENAI_GITHUB_CHANNEL_POLICY,
    )


def test_official_openai_github_channel_policy_rejects_non_official_url() -> None:
    artifact = _MOD.StockCodexChannelArtifact(
        version="codex-cli 0.142.2",
        platform=_MOD.current_channel_platform(),
        source="https://example.com/openai/codex/releases/download/codex.tar.gz",
        source_field="url",
        sha256="a" * 64,
        archive_format="tar.gz",
        archive_executable="codex-aarch64-apple-darwin",
    )

    with pytest.raises(_MOD.ProvisioningError, match="violates"):
        _MOD.validate_channel_artifact_policy(
            artifact,
            policy_name=_MOD.OFFICIAL_OPENAI_GITHUB_CHANNEL_POLICY,
        )


def test_official_openai_github_channel_policy_rejects_archive_name_mismatch() -> None:
    artifact = _MOD.StockCodexChannelArtifact(
        version="codex-cli 0.142.2",
        platform=_MOD.current_channel_platform(),
        source=(
            "https://github.com/openai/codex/releases/download/"
            "rust-v0.142.2/not-the-declared-executable.tar.gz"
        ),
        source_field="url",
        sha256="a" * 64,
        archive_format="tar.gz",
        archive_executable="codex-aarch64-apple-darwin",
    )

    with pytest.raises(_MOD.ProvisioningError, match="archive filename"):
        _MOD.validate_channel_artifact_policy(
            artifact,
            policy_name=_MOD.OFFICIAL_OPENAI_GITHUB_CHANNEL_POLICY,
        )


def test_official_openai_github_channel_policy_rejects_nested_release_path() -> None:
    artifact = _MOD.StockCodexChannelArtifact(
        version="codex-cli 0.142.2",
        platform=_MOD.current_channel_platform(),
        source=(
            "https://github.com/openai/codex/releases/download/"
            "rust-v0.142.2/nested/codex-aarch64-apple-darwin.tar.gz"
        ),
        source_field="url",
        sha256="a" * 64,
        archive_format="tar.gz",
        archive_executable="codex-aarch64-apple-darwin",
    )

    with pytest.raises(_MOD.ProvisioningError, match="URL path"):
        _MOD.validate_channel_artifact_policy(
            artifact,
            policy_name=_MOD.OFFICIAL_OPENAI_GITHUB_CHANNEL_POLICY,
        )


def test_remote_channel_reuses_existing_matching_payload_without_download(
    tmp_path: Path,
) -> None:
    source_binary = _write_codex_binary(tmp_path / "source" / "codex")
    source_sha = _MOD.sha256_file(source_binary)
    archive_sha = "b" * 64
    release_url = (
        "https://github.com/openai/codex/releases/download/"
        "rust-v0.142.2/codex-aarch64-apple-darwin.tar.gz"
    )
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
                        "url": release_url,
                        "sha256": archive_sha,
                        "archiveFormat": "tar.gz",
                        "archiveExecutable": "codex-aarch64-apple-darwin",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    artifact = _MOD.select_channel_artifact(
        channel_manifest=channel_manifest,
        requested_version=None,
        requested_platform=None,
    )
    cache_root = tmp_path / "cache"
    payload_dir = cache_root / "0.142.2"
    _MOD.copy_codex_payload(
        source_binary=source_binary,
        destination_payload_dir=payload_dir,
        version="codex-cli 0.142.2",
        digest=source_sha,
        source_kind="channel",
        manifest_source_path=release_url,
        manifest_source_realpath=release_url,
        channel_manifest_path=channel_manifest,
        channel_artifact=artifact,
    )

    provisioned = _MOD.provision_stock_codex_from_channel(
        cache_root=cache_root,
        channel_manifest=channel_manifest,
        channel_version=None,
        channel_platform=None,
        expected_sha256=archive_sha,
        force=False,
        allow_fork_codex=False,
        allow_remote_channel_download=False,
        channel_policy=_MOD.OFFICIAL_OPENAI_GITHUB_CHANNEL_POLICY,
    )

    assert provisioned.payload_dir == payload_dir
    assert provisioned.sha256 == source_sha
    assert provisioned.channel_artifact == artifact.as_manifest_dict()


def test_local_channel_reuse_requires_payload_sha_to_match_artifact_sha(
    tmp_path: Path,
) -> None:
    source_binary = _write_codex_binary(tmp_path / "artifacts" / "codex")
    wrong_binary = _write_codex_binary(
        tmp_path / "wrong" / "codex",
        version="codex-cli 0.142.2",
    )
    with wrong_binary.open("a", encoding="utf-8") as handle:
        handle.write("# different payload\n")
    source_sha = _MOD.sha256_file(source_binary)
    wrong_sha = _MOD.sha256_file(wrong_binary)
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
                        "path": str(source_binary),
                        "sha256": source_sha,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    artifact = _MOD.select_channel_artifact(
        channel_manifest=channel_manifest,
        requested_version=None,
        requested_platform=None,
    )
    cache_root = tmp_path / "cache"
    _MOD.copy_codex_payload(
        source_binary=wrong_binary,
        destination_payload_dir=cache_root / "0.142.2",
        version="codex-cli 0.142.2",
        digest=wrong_sha,
        source_kind="channel",
        manifest_source_path=str(source_binary),
        manifest_source_realpath=str(source_binary.resolve()),
        channel_manifest_path=channel_manifest,
        channel_artifact=artifact,
    )

    with pytest.raises(_MOD.ProvisioningError, match="sha256 mismatch"):
        _MOD.provision_stock_codex_from_channel(
            cache_root=cache_root,
            channel_manifest=channel_manifest,
            channel_version=None,
            channel_platform=None,
            expected_sha256=source_sha,
            force=False,
            allow_fork_codex=False,
            allow_remote_channel_download=False,
        )


def test_official_channel_policy_rejects_before_cache_mutation(tmp_path: Path) -> None:
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
                        "url": "https://example.com/codex.tar.gz",
                        "sha256": "b" * 64,
                        "archiveFormat": "tar.gz",
                        "archiveExecutable": "codex-aarch64-apple-darwin",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    cache_root = tmp_path / "cache"

    with pytest.raises(_MOD.ProvisioningError, match="violates"):
        _MOD.provision_stock_codex_from_channel(
            cache_root=cache_root,
            channel_manifest=channel_manifest,
            channel_version=None,
            channel_platform=None,
            expected_sha256=None,
            force=False,
            allow_fork_codex=False,
            allow_remote_channel_download=True,
            channel_policy=_MOD.OFFICIAL_OPENAI_GITHUB_CHANNEL_POLICY,
        )

    assert not cache_root.exists()


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


def test_main_rejects_channel_policy_without_channel_manifest(
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = _MOD.main(["--channel-policy", _MOD.OFFICIAL_OPENAI_GITHUB_CHANNEL_POLICY])

    assert rc == 1
    assert "--channel-policy requires --channel-manifest" in capsys.readouterr().err


def test_plan_stock_codex_update_reports_stage_required_without_mutation(
    tmp_path: Path,
) -> None:
    current_codex = _write_codex_binary(tmp_path / "current" / "codex")
    cache_root = tmp_path / "cache"
    channel_manifest = _write_official_channel_manifest(tmp_path / "channel.json")

    plan = _MOD.plan_stock_codex_update(
        cache_root=cache_root,
        channel_manifest=channel_manifest,
        channel_version=None,
        channel_platform=None,
        channel_policy=_MOD.OFFICIAL_OPENAI_GITHUB_CHANNEL_POLICY,
        expected_sha256=None,
        current_codex=current_codex,
        launcher_manifest=None,
        stage_update=False,
        force=False,
        allow_fork_codex=False,
        allow_remote_channel_download=False,
    )

    data = plan.as_dict()
    assert plan.action == "stage-required"
    assert data["mutatesFilesystem"] is False
    assert data["target"]["state"] == "absent"
    assert data["selected"]["versionComparison"] == "newer"
    assert data["promotion"]["required"] is True
    assert data["promotion"]["ready"] is False
    assert data["promotion"]["env"] == {}
    assert data["rollback"]["codexPath"] == str(current_codex.resolve())
    assert not cache_root.exists()


def test_plan_stock_codex_update_resolves_current_from_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current_codex = _write_codex_binary(tmp_path / "current" / "codex")
    monkeypatch.setenv(_MOD.OMNIGENT_STOCK_CODEX_PATH_ENV, str(current_codex))
    channel_manifest = _write_official_channel_manifest(tmp_path / "channel.json")

    plan = _MOD.plan_stock_codex_update(
        cache_root=tmp_path / "cache",
        channel_manifest=channel_manifest,
        channel_version=None,
        channel_platform=None,
        channel_policy=_MOD.OFFICIAL_OPENAI_GITHUB_CHANNEL_POLICY,
        expected_sha256=None,
        current_codex=None,
        launcher_manifest=None,
        stage_update=False,
        force=False,
        allow_fork_codex=False,
        allow_remote_channel_download=False,
    )

    assert plan.current_codex_path == current_codex.resolve()
    assert plan.rollback_codex_path == current_codex.resolve()


def test_plan_stock_codex_update_reports_stage_ready_with_preverified_payload(
    tmp_path: Path,
) -> None:
    current_codex = _write_codex_binary(tmp_path / "current" / "codex")
    target_codex = _write_codex_binary(
        tmp_path / "target-source" / "codex",
        version="codex-cli 0.143.0",
    )
    channel_manifest = _write_official_channel_manifest(tmp_path / "channel.json")
    artifact = _MOD.select_channel_artifact(
        channel_manifest=channel_manifest,
        requested_version=None,
        requested_platform=None,
    )
    cache_root = tmp_path / "cache"
    target_payload_dir = cache_root / "0.143.0"
    _MOD.copy_codex_payload(
        source_binary=target_codex,
        destination_payload_dir=target_payload_dir,
        version="codex-cli 0.143.0",
        digest=_MOD.sha256_file(target_codex),
        source_kind="channel",
        manifest_source_path=artifact.source,
        manifest_source_realpath=artifact.source,
        channel_manifest_path=channel_manifest,
        channel_artifact=artifact,
    )
    launcher_manifest = tmp_path / "launcher.json"
    launcher_manifest.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "pinnedCodexPath": str(current_codex),
                "env": {_MOD.OMNIGENT_STOCK_CODEX_PATH_ENV: str(current_codex)},
            }
        ),
        encoding="utf-8",
    )

    plan = _MOD.plan_stock_codex_update(
        cache_root=cache_root,
        channel_manifest=channel_manifest,
        channel_version=None,
        channel_platform=None,
        channel_policy=_MOD.OFFICIAL_OPENAI_GITHUB_CHANNEL_POLICY,
        expected_sha256=None,
        current_codex=None,
        launcher_manifest=launcher_manifest,
        stage_update=True,
        force=False,
        allow_fork_codex=False,
        allow_remote_channel_download=False,
    )

    data = plan.as_dict()
    assert plan.action == "stage-ready"
    assert data["mutatesFilesystem"] is False
    assert data["target"]["state"] == "ready"
    assert data["target"]["codexPath"] == str(target_payload_dir / "codex")
    assert data["promotion"]["required"] is True
    assert data["promotion"]["ready"] is True
    assert data["promotion"]["env"] == {
        _MOD.OMNIGENT_STOCK_CODEX_PATH_ENV: str(target_payload_dir / "codex")
    }
    assert data["promotion"]["launcherManifest"] == {
        "manifestPath": str(launcher_manifest),
        "field": "pinnedCodexPath",
        "from": str(current_codex.resolve()),
        "to": str(target_payload_dir / "codex"),
        "updateRequired": True,
        "ready": True,
    }
    assert data["rollback"]["codexPath"] == str(current_codex.resolve())


def test_plan_stock_codex_update_reports_up_to_date_without_promotion(
    tmp_path: Path,
) -> None:
    target_codex = _write_codex_binary(
        tmp_path / "target-source" / "codex",
        version="codex-cli 0.143.0",
    )
    channel_manifest = _write_official_channel_manifest(tmp_path / "channel.json")
    artifact = _MOD.select_channel_artifact(
        channel_manifest=channel_manifest,
        requested_version=None,
        requested_platform=None,
    )
    cache_root = tmp_path / "cache"
    target_payload_dir = cache_root / "0.143.0"
    _MOD.copy_codex_payload(
        source_binary=target_codex,
        destination_payload_dir=target_payload_dir,
        version="codex-cli 0.143.0",
        digest=_MOD.sha256_file(target_codex),
        source_kind="channel",
        manifest_source_path=artifact.source,
        manifest_source_realpath=artifact.source,
        channel_manifest_path=channel_manifest,
        channel_artifact=artifact,
    )

    plan = _MOD.plan_stock_codex_update(
        cache_root=cache_root,
        channel_manifest=channel_manifest,
        channel_version=None,
        channel_platform=None,
        channel_policy=_MOD.OFFICIAL_OPENAI_GITHUB_CHANNEL_POLICY,
        expected_sha256=None,
        current_codex=target_payload_dir / "codex",
        launcher_manifest=None,
        stage_update=False,
        force=False,
        allow_fork_codex=False,
        allow_remote_channel_download=False,
    )

    data = plan.as_dict()
    assert plan.action == "up-to-date"
    assert data["mutatesFilesystem"] is False
    assert data["promotion"] == {
        "required": False,
        "ready": True,
        "env": {},
        "launcherManifest": None,
    }
    assert data["rollback"]["codexPath"] == str((target_payload_dir / "codex").resolve())


def test_plan_stock_codex_update_promotes_stale_launcher_manifest(
    tmp_path: Path,
) -> None:
    old_codex = _write_codex_binary(tmp_path / "old" / "codex")
    target_codex = _write_codex_binary(
        tmp_path / "target-source" / "codex",
        version="codex-cli 0.143.0",
    )
    channel_manifest = _write_official_channel_manifest(tmp_path / "channel.json")
    artifact = _MOD.select_channel_artifact(
        channel_manifest=channel_manifest,
        requested_version=None,
        requested_platform=None,
    )
    cache_root = tmp_path / "cache"
    target_payload_dir = cache_root / "0.143.0"
    _MOD.copy_codex_payload(
        source_binary=target_codex,
        destination_payload_dir=target_payload_dir,
        version="codex-cli 0.143.0",
        digest=_MOD.sha256_file(target_codex),
        source_kind="channel",
        manifest_source_path=artifact.source,
        manifest_source_realpath=artifact.source,
        channel_manifest_path=channel_manifest,
        channel_artifact=artifact,
    )
    launcher_manifest = tmp_path / "launcher.json"
    launcher_manifest.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "pinnedCodexPath": str(old_codex),
                "env": {_MOD.OMNIGENT_STOCK_CODEX_PATH_ENV: str(old_codex)},
            }
        ),
        encoding="utf-8",
    )

    plan = _MOD.plan_stock_codex_update(
        cache_root=cache_root,
        channel_manifest=channel_manifest,
        channel_version=None,
        channel_platform=None,
        channel_policy=_MOD.OFFICIAL_OPENAI_GITHUB_CHANNEL_POLICY,
        expected_sha256=None,
        current_codex=target_payload_dir / "codex",
        launcher_manifest=launcher_manifest,
        stage_update=False,
        force=False,
        allow_fork_codex=False,
        allow_remote_channel_download=False,
    )

    data = plan.as_dict()
    assert plan.action == "stage-ready"
    assert data["promotion"]["required"] is True
    assert data["promotion"]["ready"] is True
    assert data["promotion"]["launcherManifest"] == {
        "manifestPath": str(launcher_manifest),
        "field": "pinnedCodexPath",
        "from": str(old_codex.resolve()),
        "to": str(target_payload_dir / "codex"),
        "updateRequired": True,
        "ready": True,
    }
    assert data["rollback"]["codexPath"] == str((target_payload_dir / "codex").resolve())


def test_plan_stock_codex_update_reports_force_required_for_stale_payload(
    tmp_path: Path,
) -> None:
    current_codex = _write_codex_binary(tmp_path / "current" / "codex")
    target_codex = _write_codex_binary(
        tmp_path / "target-source" / "codex",
        version="codex-cli 0.143.0",
    )
    channel_manifest = _write_official_channel_manifest(tmp_path / "channel.json")
    artifact = _MOD.select_channel_artifact(
        channel_manifest=channel_manifest,
        requested_version=None,
        requested_platform=None,
    )
    stale_artifact = _MOD.StockCodexChannelArtifact(
        version=artifact.version,
        platform=artifact.platform,
        source=_official_archive_url(
            version_slug="0.143.0",
            archive_executable="codex-x86_64-apple-darwin",
        ),
        source_field="url",
        sha256=artifact.sha256,
        archive_format=artifact.archive_format,
        archive_executable="codex-x86_64-apple-darwin",
    )
    cache_root = tmp_path / "cache"
    target_payload_dir = cache_root / "0.143.0"
    _MOD.copy_codex_payload(
        source_binary=target_codex,
        destination_payload_dir=target_payload_dir,
        version="codex-cli 0.143.0",
        digest=_MOD.sha256_file(target_codex),
        source_kind="channel",
        manifest_source_path=stale_artifact.source,
        manifest_source_realpath=stale_artifact.source,
        channel_manifest_path=channel_manifest,
        channel_artifact=stale_artifact,
    )

    plan = _MOD.plan_stock_codex_update(
        cache_root=cache_root,
        channel_manifest=channel_manifest,
        channel_version=None,
        channel_platform=None,
        channel_policy=_MOD.OFFICIAL_OPENAI_GITHUB_CHANNEL_POLICY,
        expected_sha256=None,
        current_codex=current_codex,
        launcher_manifest=None,
        stage_update=False,
        force=False,
        allow_fork_codex=False,
        allow_remote_channel_download=False,
    )

    data = plan.as_dict()
    assert plan.action == "force-required"
    assert data["mutatesFilesystem"] is False
    assert data["target"]["state"] == "stale"
    assert data["promotion"]["ready"] is False
    assert data["promotion"]["env"] == {}
    assert "channel artifact mismatch" in str(data["target"]["error"])


def test_main_plan_update_requires_channel_policy(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    channel_manifest = _write_official_channel_manifest(tmp_path / "channel.json")

    rc = _MOD.main(
        [
            "--plan-update",
            "--channel-manifest",
            str(channel_manifest),
            "--json",
        ]
    )

    assert rc == 1
    assert "--plan-update requires --channel-policy" in capsys.readouterr().err


def test_main_plan_update_rejects_path_only_output(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    channel_manifest = _write_official_channel_manifest(tmp_path / "channel.json")

    rc = _MOD.main(
        [
            "--plan-update",
            "--channel-manifest",
            str(channel_manifest),
            "--channel-policy",
            _MOD.OFFICIAL_OPENAI_GITHUB_CHANNEL_POLICY,
            "--print-path",
        ]
    )

    assert rc == 1
    assert "supports default text output or --json only" in capsys.readouterr().err
