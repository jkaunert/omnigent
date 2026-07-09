"""Tests for ``scripts/prove_stock_codex_replacement.py``."""

from __future__ import annotations

import importlib.util
import json
import os
import plistlib
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from omnigent import stock_codex_compat_wrapper
from omnigent.adapters.apple_docs_cli import (
    APPLE_DOCS_CLI_URL,
    build_fetch_apple_docs_stock_codex_bridge_adapter_spec,
)
from omnigent.adapters.stock_codex_compat import (
    write_stock_codex_compat_adapter_package,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "prove_stock_codex_replacement.py"


def _load_module() -> Any:
    spec = importlib.util.spec_from_file_location(
        "scripts_prove_stock_codex_replacement",
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


def _write_live_codex_binary(path: Path, *, version: str = "codex-cli 0.142.2") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""#!/bin/sh
if [ "${{1:-}}" = "--version" ]; then
  cat <<'EOF'
{version}
EOF
  exit 0
fi
if [ "${{1:-}}" = "features" ] && [ "${{2:-}}" = "list" ]; then
  cat <<'EOF'
route_selection stable true
model_context_protocol experimental false
EOF
  exit 0
fi
if [ "${{1:-}}" = "exec" ]; then
  cat <<'EOF'
{{"type":"thread.started","thread_id":"thread-stock-codex-compat-pkg-runtime"}}
{{"type":"item.completed","item":{{"type":"agent_message","text":"{_MOD.STOCK_CODEX_COMPAT_LIVE_SENTINEL}"}}}}
EOF
  exit 0
fi
printf 'unexpected fake codex args:' >&2
for arg in "$@"; do
  printf ' <%s>' "$arg" >&2
done
printf '\\n' >&2
exit 64
""",
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


def _write_auth(codex_home: Path, payload: object) -> Path:
    codex_home.mkdir(parents=True, exist_ok=True)
    auth_path = codex_home / "auth.json"
    auth_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    return auth_path


def _write_uvx_binary(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        """#!/bin/sh
printf 'fake uvx\\n'
""",
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


def _write_installer_uvx_binary(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""#!/bin/sh
if [ "${{1:-}}" = "--from" ]; then
  shift 2
fi
if [ "${{1:-}}" = "python" ]; then
  shift
  script="${{1:-}}"
  runtime_root="$(dirname "$(dirname "$script")")"
  PYTHONPATH="$runtime_root${{PYTHONPATH:+:$PYTHONPATH}}" \\
    exec {sys.executable!r} "$@"
fi
printf 'unexpected fake installer uvx args:' >&2
for arg in "$@"; do
  printf ' <%s>' "$arg" >&2
done
printf '\\n' >&2
exit 64
""",
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


def _write_wrapper_uvx_binary(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""#!/bin/sh
if [ "${{1:-}}" = "--from" ]; then
  shift 2
fi
if [ "${{1:-}}" = "omnigent-stock-codex-wrapper" ]; then
  shift
  PYTHONPATH={str(_REPO_ROOT)!r}${{PYTHONPATH:+:$PYTHONPATH}} \\
    exec {sys.executable!r} -m omnigent.stock_codex_compat_wrapper "$@"
fi
printf 'unexpected fake uvx args:' >&2
for arg in "$@"; do
  printf ' <%s>' "$arg" >&2
done
printf '\\n' >&2
exit 64
""",
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


def _write_plugin_bundle(path: Path) -> Path:
    plugin_manifest = path / ".codex-plugin" / "plugin.json"
    plugin_manifest.parent.mkdir(parents=True, exist_ok=True)
    plugin_manifest.write_text(
        json.dumps(
            {
                "name": "apple-appdev-workflow",
                "version": "0.1.1",
                "description": "Apple workflow proof fixture",
                "skills": "./skills/",
                "mcpServers": "./.mcp.json",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    skill = path / "skills" / "apple-app-orchestrator" / "SKILL.md"
    skill.parent.mkdir(parents=True, exist_ok=True)
    skill.write_text("# Apple App Orchestrator\n", encoding="utf-8")
    (path / ".mcp.json").write_text(
        json.dumps({"mcpServers": {}}) + "\n",
        encoding="utf-8",
    )
    return path


def test_clean_auth_onboarding_proof_classifies_clean_and_synthetic_auth(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_home = tmp_path / "real-home"
    real_codex_home = tmp_path / "real-codex-home"
    real_auth_path = _write_auth(
        real_codex_home,
        {"auth_mode": "api", "OPENAI_API_KEY": "sk-real-proof-fixture"},
    )
    stock_codex = _write_codex_binary(tmp_path / "bin" / "codex")
    monkeypatch.setenv("HOME", str(real_home))
    monkeypatch.setenv("CODEX_HOME", str(real_codex_home))

    proof = _MOD.run_clean_auth_onboarding_proof(stock_codex)

    assert proof.stock_codex_path == stock_codex.resolve()
    assert proof.stock_codex_version == "codex-cli 0.142.2"
    assert proof.real_auth_path == real_auth_path
    assert proof.real_auth_source == "explicit-CODEX_HOME"
    assert proof.real_auth_available is True
    assert proof.clean_unavailable_reason == "needs-auth"
    assert proof.synthetic_available_reason is None


def test_clean_auth_onboarding_proof_ignores_inherited_codex_fork_home(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_home = tmp_path / "real-home"
    stock_auth_path = _write_auth(
        real_home / ".codex",
        {"auth_mode": "api", "OPENAI_API_KEY": "sk-stock-proof-fixture"},
    )
    fork_auth_path = _write_auth(
        real_home / ".codex-fork",
        {"auth_mode": "api", "OPENAI_API_KEY": "sk-fork-proof-fixture"},
    )
    stock_codex = _write_codex_binary(tmp_path / "bin" / "codex")
    monkeypatch.setenv("HOME", str(real_home))
    monkeypatch.setenv("CODEX_HOME", str(fork_auth_path.parent))

    proof = _MOD.run_clean_auth_onboarding_proof(stock_codex)

    assert proof.real_auth_path == stock_auth_path
    assert proof.real_auth_path != fork_auth_path
    assert proof.real_auth_source == "stock-default-home"
    assert proof.real_auth_available is True


def test_clean_auth_onboarding_proof_requires_real_auth(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stock_codex = _write_codex_binary(tmp_path / "bin" / "codex")
    real_home = tmp_path / "real-home"
    real_codex_home = tmp_path / "real-codex-home"
    real_codex_home.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(real_home))
    monkeypatch.setenv("CODEX_HOME", str(real_codex_home))

    with pytest.raises(SystemExit) as excinfo:
        _MOD.run_clean_auth_onboarding_proof(stock_codex)

    assert "Current real Codex auth source is not available" in str(excinfo.value)


def test_stock_codex_production_channel_policy_proof_reuses_and_rejects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host_home = tmp_path / "host-home"
    stock_codex = _write_codex_binary(tmp_path / "bin" / "codex")
    monkeypatch.setenv("HOME", str(host_home))

    proof = _MOD.run_stock_codex_production_channel_policy_proof(stock_codex)

    assert proof.source_codex_path == stock_codex.resolve()
    assert proof.source_codex_version == "codex-cli 0.142.2"
    assert proof.policy_name == "official-openai-github-release"
    assert proof.policy_manifest_path.name == "stock-codex-channel-policy.json"
    assert proof.official_channel_manifest_path.name == "official-channel.json"
    assert proof.official_archive_url.startswith(
        "https://github.com/openai/codex/releases/download/"
    )
    assert proof.official_archive_url.endswith(".tar.gz")
    assert len(proof.official_archive_sha256) == 64
    assert proof.cache_root == proof.clean_home / ".local" / "omnigent" / "codex-stock"
    assert proof.payload_dir == proof.cache_root / "0.142.2"
    assert proof.provisioned_codex_path == proof.payload_dir / "codex"
    assert proof.provisioned_version == "codex-cli 0.142.2"
    assert proof.provisioned_sha256 == proof.source_codex_sha256
    assert proof.provisioned_source_kind == "channel"
    assert proof.provisioned_channel_artifact["url"] == proof.official_archive_url
    assert proof.provisioned_channel_artifact["sha256"] == proof.official_archive_sha256
    assert proof.omnigent_resolved_codex_path == proof.provisioned_codex_path
    assert proof.offline_reuse_without_remote_download is True
    assert proof.rejected_channel_manifest_path.name == "rejected-channel.json"
    assert "violates" in proof.rejected_error
    assert proof.rejected_cache_mutated is False
    assert proof.host_cache_root == host_home / ".local" / "omnigent" / "codex-stock"
    assert proof.host_cache_referenced is False


def test_stock_codex_update_acquisition_proof_stages_and_reuses_remote(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host_home = tmp_path / "host-home"
    stock_codex = _write_codex_binary(
        tmp_path / "bin" / "codex",
        version="codex-cli 0.142.5",
    )
    cask_url = (
        "https://github.com/openai/codex/releases/download/"
        "rust-v0.143.0/codex-aarch64-apple-darwin.tar.gz"
    )
    cask_sha = "a" * 64
    channel = _MOD._GitHubLatestStableCodexChannel(
        tag_name="rust-v0.143.0",
        version_slug="0.143.0",
        selected_version="codex-cli 0.143.0",
        release_name="0.143.0",
        release_html_url="https://github.com/openai/codex/releases/tag/rust-v0.143.0",
        published_at="2026-07-08T01:31:10Z",
        asset_name="codex-aarch64-apple-darwin.tar.gz",
        asset_url=cask_url,
        asset_digest=f"sha256:{cask_sha}",
        asset_sha256=cask_sha,
        archive_executable="codex-aarch64-apple-darwin",
    )
    expected_artifact = {
        "archiveExecutable": "codex-aarch64-apple-darwin",
        "archiveFormat": "tar.gz",
        "sha256": cask_sha,
        "url": cask_url,
        "version": "codex-cli 0.143.0",
        "versionSlug": "0.143.0",
    }
    monkeypatch.setenv("HOME", str(host_home))
    monkeypatch.setattr(_MOD, "_github_latest_stable_codex_channel", lambda: channel)
    monkeypatch.setattr(
        _MOD,
        "_read_homebrew_codex_cask",
        lambda: (_ for _ in ()).throw(AssertionError("Homebrew should not be read")),
    )

    def fake_run(
        cmd: list[str],
        *,
        check: bool = False,
        capture_output: bool = False,
        text: bool = False,
        env: dict[str, str] | None = None,
        cwd: Path | None = None,
        timeout: float | None = None,
    ) -> subprocess.CompletedProcess[str]:
        del check, capture_output, text, env, cwd, timeout
        if len(cmd) >= 2 and cmd[1:] == ["--version"]:
            version = "codex-cli 0.143.0" if "0.143.0" in cmd[0] else "codex-cli 0.142.5"
            return subprocess.CompletedProcess(cmd, 0, stdout=f"{version}\n", stderr="")
        if len(cmd) >= 2 and Path(cmd[1]).name == "provision_stock_codex.py":
            args = cmd[2:]
            cache_root = Path(args[args.index("--cache-root") + 1])
            allow_remote = "--allow-remote-channel-download" in args
            target_dir = cache_root / "0.143.0"
            target_path = target_dir / "codex"
            if not allow_remote and not target_path.exists():
                return subprocess.CompletedProcess(
                    cmd,
                    1,
                    stdout="",
                    stderr="error: Remote channel downloads require "
                    "--allow-remote-channel-download.\n",
                )
            mutates = False
            action = "stage-ready"
            if allow_remote:
                _write_codex_binary(target_path, version="codex-cli 0.143.0")
                mutates = True
                action = "staged"
                manifest = {
                    "schemaVersion": 1,
                    "kind": "omnigent-stock-codex",
                    "sourceKind": "channel",
                    "version": "codex-cli 0.143.0",
                    "versionSlug": "0.143.0",
                    "sha256": _MOD.sha256_file(target_path),
                    "sourcePath": cask_url,
                    "sourceRealpath": cask_url,
                    "channelArtifact": expected_artifact,
                }
                (target_dir / "manifest.json").write_text(
                    json.dumps(manifest) + "\n",
                    encoding="utf-8",
                )
            sha = _MOD.sha256_file(target_path)
            plan = {
                "kind": "omnigent-stock-codex-update-plan",
                "schemaVersion": 1,
                "action": action,
                "mutatesFilesystem": mutates,
                "target": {
                    "state": "ready",
                    "payloadDir": str(target_dir),
                    "codexPath": str(target_path),
                    "error": None,
                },
                "promotion": {
                    "required": True,
                    "ready": True,
                    "env": {_MOD.OMNIGENT_STOCK_CODEX_PATH_ENV: str(target_path)},
                    "launcherManifest": {
                        "updateRequired": True,
                        "ready": True,
                    },
                },
                "rollback": {
                    "codexPath": str(tmp_path / "current" / "codex"),
                    "payloadRetention": "versioned-cache-keeps-previous-payload",
                },
                "stagedPayload": {
                    "codexPath": str(target_path),
                    "payloadDir": str(target_dir),
                    "manifestPath": str(target_dir / "manifest.json"),
                    "version": "codex-cli 0.143.0",
                    "versionSlug": "0.143.0",
                    "sha256": sha,
                    "sourcePath": cask_url,
                    "sourceRealpath": cask_url,
                    "sourceKind": "channel",
                    "channelArtifact": expected_artifact,
                },
            }
            current_arg = args[args.index("--current-codex") + 1]
            plan["rollback"]["codexPath"] = current_arg
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(plan), stderr="")
        raise AssertionError(f"unexpected subprocess command: {cmd!r}")

    monkeypatch.setattr(_MOD.subprocess, "run", fake_run)

    proof = _MOD.run_stock_codex_update_acquisition_proof(stock_codex)

    assert proof.source_codex_path == stock_codex.resolve()
    assert proof.source_codex_version == "codex-cli 0.142.5"
    assert proof.policy_name == "official-openai-github-release"
    assert proof.github_release_tag == "rust-v0.143.0"
    assert proof.github_asset_digest == f"sha256:{cask_sha}"
    assert proof.github_asset_sha256 == cask_sha
    assert proof.cask_version == "0.143.0"
    assert proof.cask_url == cask_url
    assert proof.acquisition_action == "staged"
    assert proof.acquisition_mutates_filesystem is True
    assert proof.acquisition_promotion_required is True
    assert proof.acquisition_promotion_ready is True
    assert proof.acquisition_launcher_update_required is True
    assert proof.acquired_version == "codex-cli 0.143.0"
    assert proof.acquired_source_kind == "channel"
    assert proof.acquired_channel_artifact == expected_artifact
    assert proof.reuse_action == "stage-ready"
    assert proof.reuse_mutates_filesystem is False
    assert proof.reuse_without_remote_download is True
    assert "allow-remote-channel-download" in proof.blocked_without_remote_error
    assert proof.blocked_without_remote_cache_mutated is False
    assert proof.host_cache_root == host_home / ".local" / "omnigent" / "codex-stock"
    assert proof.host_cache_referenced_by_plans is False


def test_github_latest_stable_channel_uses_release_asset_digest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        _MOD,
        "_stock_codex_archive_executable_name",
        lambda: "codex-aarch64-apple-darwin",
    )
    release = {
        "tag_name": "rust-v0.143.0",
        "name": "0.143.0",
        "html_url": "https://github.com/openai/codex/releases/tag/rust-v0.143.0",
        "published_at": "2026-07-08T01:31:10Z",
        "draft": False,
        "prerelease": False,
        "assets": [
            {
                "name": "codex-aarch64-apple-darwin.tar.gz",
                "browser_download_url": (
                    "https://github.com/openai/codex/releases/download/"
                    "rust-v0.143.0/codex-aarch64-apple-darwin.tar.gz"
                ),
                "digest": "sha256:" + ("B" * 64),
            },
        ],
    }

    channel = _MOD._github_latest_stable_codex_channel_from_release(release)

    assert channel.tag_name == "rust-v0.143.0"
    assert channel.version_slug == "0.143.0"
    assert channel.selected_version == "codex-cli 0.143.0"
    assert channel.asset_name == "codex-aarch64-apple-darwin.tar.gz"
    assert channel.asset_digest == "sha256:" + ("b" * 64)
    assert channel.asset_sha256 == "b" * 64
    assert channel.archive_executable == "codex-aarch64-apple-darwin"


def test_github_latest_stable_channel_rejects_prerelease(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        _MOD,
        "_stock_codex_archive_executable_name",
        lambda: "codex-aarch64-apple-darwin",
    )
    release = {
        "tag_name": "rust-v0.143.1-alpha.1",
        "name": "0.143.1-alpha.1",
        "html_url": "https://github.com/openai/codex/releases/tag/rust-v0.143.1-alpha.1",
        "published_at": "2026-07-08T03:00:00Z",
        "draft": False,
        "prerelease": True,
        "assets": [],
    }

    with pytest.raises(SystemExit, match="stable numeric tag"):
        _MOD._github_latest_stable_codex_channel_from_release(release)


def test_official_stock_codex_remote_channel_uses_github_latest_stable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asset_sha = "d" * 64
    asset_url = (
        "https://github.com/openai/codex/releases/download/"
        "rust-v0.143.0/codex-aarch64-apple-darwin.tar.gz"
    )
    channel = _MOD._GitHubLatestStableCodexChannel(
        tag_name="rust-v0.143.0",
        version_slug="0.143.0",
        selected_version="codex-cli 0.143.0",
        release_name="0.143.0",
        release_html_url="https://github.com/openai/codex/releases/tag/rust-v0.143.0",
        published_at="2026-07-08T01:31:10Z",
        asset_name="codex-aarch64-apple-darwin.tar.gz",
        asset_url=asset_url,
        asset_digest=f"sha256:{asset_sha}",
        asset_sha256=asset_sha,
        archive_executable="codex-aarch64-apple-darwin",
    )
    monkeypatch.setattr(_MOD, "_github_latest_stable_codex_channel", lambda: channel)
    monkeypatch.setattr(
        _MOD,
        "_read_homebrew_codex_cask",
        lambda: (_ for _ in ()).throw(AssertionError("Homebrew should not be read")),
    )

    remote = _MOD._official_stock_codex_remote_channel()

    assert remote.policy_name == "official-openai-github-release"
    assert remote.source_name == "github-latest-stable-release"
    assert remote.cask_tap == "github-releases/latest"
    assert remote.cask_version == "0.143.0"
    assert remote.cask_url == asset_url
    assert remote.cask_sha256 == asset_sha
    assert remote.selected_version == "codex-cli 0.143.0"
    assert remote.archive_executable == "codex-aarch64-apple-darwin"
    assert remote.github_release_tag == "rust-v0.143.0"
    assert remote.github_release_url == (
        "https://github.com/openai/codex/releases/tag/rust-v0.143.0"
    )
    assert remote.github_asset_digest == f"sha256:{asset_sha}"


def test_stock_codex_github_latest_stable_acquisition_proof_uses_asset_digest_and_live_route(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host_home = tmp_path / "host-home"
    stock_codex = _write_codex_binary(
        tmp_path / "bin" / "codex",
        version="codex-cli 0.142.5",
    )
    agent_dir = tmp_path / "agent"
    agent_dir.mkdir()
    asset_url = (
        "https://github.com/openai/codex/releases/download/"
        "rust-v0.143.0/codex-aarch64-apple-darwin.tar.gz"
    )
    asset_sha = "c" * 64
    expected_artifact = {
        "archiveExecutable": "codex-aarch64-apple-darwin",
        "archiveFormat": "tar.gz",
        "sha256": asset_sha,
        "url": asset_url,
        "version": "codex-cli 0.143.0",
        "versionSlug": "0.143.0",
    }
    channel = _MOD._GitHubLatestStableCodexChannel(
        tag_name="rust-v0.143.0",
        version_slug="0.143.0",
        selected_version="codex-cli 0.143.0",
        release_name="0.143.0",
        release_html_url="https://github.com/openai/codex/releases/tag/rust-v0.143.0",
        published_at="2026-07-08T01:31:10Z",
        asset_name="codex-aarch64-apple-darwin.tar.gz",
        asset_url=asset_url,
        asset_digest=f"sha256:{asset_sha}",
        asset_sha256=asset_sha,
        archive_executable="codex-aarch64-apple-darwin",
    )
    monkeypatch.setenv("HOME", str(host_home))
    monkeypatch.setattr(_MOD, "_github_latest_stable_codex_channel", lambda: channel)

    def fake_run(
        cmd: list[str],
        *,
        check: bool = False,
        capture_output: bool = False,
        text: bool = False,
        env: dict[str, str] | None = None,
        cwd: Path | None = None,
        timeout: float | None = None,
    ) -> subprocess.CompletedProcess[str]:
        del check, capture_output, text, env, cwd, timeout
        if len(cmd) >= 2 and cmd[1:] == ["--version"]:
            version = "codex-cli 0.143.0" if "0.143.0" in cmd[0] else "codex-cli 0.142.5"
            return subprocess.CompletedProcess(cmd, 0, stdout=f"{version}\n", stderr="")
        if len(cmd) >= 2 and Path(cmd[1]).name == "provision_stock_codex.py":
            args = cmd[2:]
            cache_root = Path(args[args.index("--cache-root") + 1])
            channel_manifest = Path(args[args.index("--channel-manifest") + 1])
            manifest_payload = json.loads(channel_manifest.read_text(encoding="utf-8"))
            assert manifest_payload["latest"] == "0.143.0"
            assert manifest_payload["artifacts"] == [
                {
                    "archiveExecutable": "codex-aarch64-apple-darwin",
                    "archiveFormat": "tar.gz",
                    "sha256": asset_sha,
                    "url": asset_url,
                    "version": "codex-cli 0.143.0",
                }
            ]
            assert args[args.index("--expected-sha256") + 1] == asset_sha
            allow_remote = "--allow-remote-channel-download" in args
            target_dir = cache_root / "0.143.0"
            target_path = target_dir / "codex"
            if not allow_remote and not target_path.exists():
                return subprocess.CompletedProcess(
                    cmd,
                    1,
                    stdout="",
                    stderr="error: Remote channel downloads require "
                    "--allow-remote-channel-download.\n",
                )
            mutates = False
            action = "stage-ready"
            if allow_remote:
                _write_codex_binary(target_path, version="codex-cli 0.143.0")
                mutates = True
                action = "staged"
                manifest = {
                    "schemaVersion": 1,
                    "kind": "omnigent-stock-codex",
                    "sourceKind": "channel",
                    "version": "codex-cli 0.143.0",
                    "versionSlug": "0.143.0",
                    "sha256": _MOD.sha256_file(target_path),
                    "sourcePath": asset_url,
                    "sourceRealpath": asset_url,
                    "channelArtifact": expected_artifact,
                }
                (target_dir / "manifest.json").write_text(
                    json.dumps(manifest) + "\n",
                    encoding="utf-8",
                )
            sha = _MOD.sha256_file(target_path)
            current_arg = args[args.index("--current-codex") + 1]
            plan = {
                "kind": "omnigent-stock-codex-update-plan",
                "schemaVersion": 1,
                "action": action,
                "mutatesFilesystem": mutates,
                "target": {
                    "state": "ready",
                    "payloadDir": str(target_dir),
                    "codexPath": str(target_path),
                    "error": None,
                },
                "promotion": {
                    "required": True,
                    "ready": True,
                    "env": {_MOD.OMNIGENT_STOCK_CODEX_PATH_ENV: str(target_path)},
                    "launcherManifest": {
                        "updateRequired": True,
                        "ready": True,
                    },
                },
                "rollback": {
                    "codexPath": current_arg,
                    "payloadRetention": "versioned-cache-keeps-previous-payload",
                },
                "stagedPayload": {
                    "codexPath": str(target_path),
                    "payloadDir": str(target_dir),
                    "manifestPath": str(target_dir / "manifest.json"),
                    "version": "codex-cli 0.143.0",
                    "versionSlug": "0.143.0",
                    "sha256": sha,
                    "sourcePath": asset_url,
                    "sourceRealpath": asset_url,
                    "sourceKind": "channel",
                    "channelArtifact": expected_artifact,
                },
            }
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(plan), stderr="")
        raise AssertionError(f"unexpected subprocess command: {cmd!r}")

    live_codex_paths: list[Path] = []

    def fake_run_live_proof_step(
        label: str,
        *,
        timeout_seconds: float,
        action: Any,
    ) -> str:
        assert label == "github-latest-stable-graph"
        assert timeout_seconds == 12
        return action()

    def fake_run_live_runner_proof(agent_dir_arg: Path, codex_path_arg: Path) -> str:
        assert agent_dir_arg == agent_dir
        assert "0.143.0" in str(codex_path_arg)
        live_codex_paths.append(codex_path_arg)
        return _MOD.EXPECTED_ROUTE + "\n\nGRAPH_OK"

    monkeypatch.setattr(_MOD.subprocess, "run", fake_run)
    monkeypatch.setattr(_MOD, "run_live_proof_step", fake_run_live_proof_step)
    monkeypatch.setattr(_MOD, "run_live_runner_proof", fake_run_live_runner_proof)

    proof = _MOD.run_stock_codex_github_latest_stable_acquisition_proof(
        stock_codex,
        agent_dir=agent_dir,
        live_timeout_seconds=12,
    )

    assert proof.source_codex_path == stock_codex.resolve()
    assert proof.source_codex_version == "codex-cli 0.142.5"
    assert proof.policy_name == "official-openai-github-release"
    assert proof.github_release_tag == "rust-v0.143.0"
    assert proof.github_asset_digest == f"sha256:{asset_sha}"
    assert proof.github_asset_sha256 == asset_sha
    assert proof.github_asset_url == asset_url
    assert proof.acquisition_action == "staged"
    assert proof.acquisition_mutates_filesystem is True
    assert proof.acquisition_promotion_required is True
    assert proof.acquisition_promotion_ready is True
    assert proof.acquisition_launcher_update_required is True
    assert proof.acquired_version == "codex-cli 0.143.0"
    assert proof.acquired_source_kind == "channel"
    assert proof.acquired_channel_artifact == expected_artifact
    assert proof.reuse_action == "stage-ready"
    assert proof.reuse_mutates_filesystem is False
    assert proof.reuse_without_remote_download is True
    assert "allow-remote-channel-download" in proof.blocked_without_remote_error
    assert proof.blocked_without_remote_cache_mutated is False
    assert proof.omnigent_resolved_codex_path == proof.acquired_codex_path
    assert proof.live_route_prefix_present is True
    assert proof.live_graph_ok is True
    assert live_codex_paths == [proof.acquired_codex_path]
    assert proof.host_cache_root == host_home / ".local" / "omnigent" / "codex-stock"
    assert proof.host_cache_referenced_by_plans is False


def test_stock_codex_compat_proof_installs_plugin_and_bridge(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_bundle = _write_plugin_bundle(tmp_path / "source-plugin")
    stock_codex = _write_codex_binary(tmp_path / "bin" / "codex")

    def fake_run(
        cmd: list[str],
        *,
        check: bool = False,
        capture_output: bool = False,
        text: bool = False,
        timeout: float | None = None,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        del check, capture_output, text, timeout
        args = cmd[1:]
        if args == ["--version"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="codex-cli 0.142.2\n", stderr="")
        assert env is not None
        codex_home = Path(env["CODEX_HOME"])
        root = codex_home.parent
        marketplace_root = root / "local-apple-workflow-marketplace"
        installed_path = (
            codex_home
            / "plugins"
            / "cache"
            / "LocalAppleWorkflow"
            / "apple-appdev-workflow"
            / "0.1.1"
        )
        if args == ["plugin", "marketplace", "add", str(marketplace_root), "--json"]:
            codex_home.mkdir(parents=True, exist_ok=True)
            (codex_home / "config.toml").write_text(
                "[marketplaces.LocalAppleWorkflow]\n"
                f"source = {json.dumps(str(marketplace_root))}\n"
                'source_type = "local"\n',
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(
                cmd,
                0,
                stdout=json.dumps(
                    {
                        "marketplaceName": "LocalAppleWorkflow",
                        "installedRoot": str(marketplace_root),
                        "alreadyAdded": False,
                    }
                ),
                stderr="",
            )
        if args == ["plugin", "add", "apple-appdev-workflow@LocalAppleWorkflow", "--json"]:
            installed_path.mkdir(parents=True)
            with (codex_home / "config.toml").open("a", encoding="utf-8") as handle:
                handle.write('\n[plugins."apple-appdev-workflow@LocalAppleWorkflow"]\n')
                handle.write("enabled = true\n")
            return subprocess.CompletedProcess(
                cmd,
                0,
                stdout=json.dumps(
                    {
                        "pluginId": "apple-appdev-workflow@LocalAppleWorkflow",
                        "installedPath": str(installed_path),
                    }
                ),
                stderr="",
            )
        if args == ["plugin", "marketplace", "list", "--json"]:
            return subprocess.CompletedProcess(
                cmd,
                0,
                stdout=json.dumps(
                    {
                        "marketplaces": [
                            {
                                "name": "LocalAppleWorkflow",
                                "root": str(marketplace_root),
                            }
                        ]
                    }
                ),
                stderr="",
            )
        if args == ["plugin", "list", "--json"]:
            return subprocess.CompletedProcess(
                cmd,
                0,
                stdout=json.dumps(
                    {
                        "installed": [
                            {
                                "pluginId": "apple-appdev-workflow@LocalAppleWorkflow",
                                "enabled": True,
                            }
                        ],
                        "available": [],
                    }
                ),
                stderr="",
            )
        if args == ["mcp", "list", "--json"]:
            return subprocess.CompletedProcess(
                cmd,
                0,
                stdout=json.dumps([{"name": "memory"}, {"name": "omnigent"}]),
                stderr="",
            )
        if args == ["mcp", "get", "omnigent", "--json"]:
            bridge_dir = root / "omnigent-bridge"
            return subprocess.CompletedProcess(
                cmd,
                0,
                stdout=json.dumps(
                    {
                        "name": "omnigent",
                        "transport": {
                            "command": sys.executable,
                            "args": [
                                "-I",
                                "-m",
                                "omnigent.claude_native_bridge",
                                "serve-mcp",
                                "--bridge-dir",
                                str(bridge_dir),
                            ],
                        },
                    }
                ),
                stderr="",
            )
        raise AssertionError(f"unexpected fake codex command: {args!r}")

    monkeypatch.setattr(_MOD.subprocess, "run", fake_run)

    proof = _MOD.run_stock_codex_compat_proof(source_bundle, stock_codex)

    assert proof.stock_codex_path == stock_codex.resolve()
    assert proof.stock_codex_version == "codex-cli 0.142.2"
    assert proof.marketplace_name == "LocalAppleWorkflow"
    assert proof.plugin_id == "apple-appdev-workflow@LocalAppleWorkflow"
    assert proof.installed_plugin_path.name == "0.1.1"
    assert proof.hook_events == ("PostToolUse", "PreToolUse", "UserPromptSubmit")
    assert "omnigent" in proof.mcp_servers
    assert "omnigent.claude_native_bridge" in proof.mcp_omnigent_args
    assert proof.codex_home.name == "codex-home"
    assert "omnigent-stock-codex-compat" in str(proof.codex_home)


def test_stock_codex_compat_live_event_parser_reads_route_and_sentinel() -> None:
    agent_message = f"{_MOD.EXPECTED_ROUTE}\n\n{_MOD.STOCK_CODEX_COMPAT_LIVE_SENTINEL}"
    stdout = "\n".join(
        [
            json.dumps({"type": "thread.started", "thread_id": "thread-123"}),
            json.dumps({"type": "turn.started"}),
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {
                        "type": "agent_message",
                        "text": agent_message,
                    },
                }
            ),
        ]
    )

    events = _MOD._parse_stock_codex_exec_jsonl(stdout)
    thread_id, first_agent_message = _MOD._validate_stock_codex_compat_live_events(events)

    assert thread_id == "thread-123"
    assert first_agent_message.startswith(_MOD.EXPECTED_ROUTE)
    assert _MOD.STOCK_CODEX_COMPAT_LIVE_SENTINEL in first_agent_message


def test_stock_codex_compat_live_event_parser_requires_sentinel() -> None:
    stdout = "\n".join(
        [
            json.dumps({"type": "thread.started", "thread_id": "thread-123"}),
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {
                        "type": "agent_message",
                        "text": _MOD.EXPECTED_ROUTE,
                    },
                }
            ),
        ]
    )

    events = _MOD._parse_stock_codex_exec_jsonl(stdout)

    with pytest.raises(SystemExit, match="did not return the expected sentinel"):
        _MOD._validate_stock_codex_compat_live_events(events)


def test_stock_codex_compat_wrapper_prefixes_first_agent_message_jsonl(
    tmp_path: Path,
) -> None:
    stock_codex = tmp_path / "bin" / "codex"
    stock_codex.parent.mkdir(parents=True)
    stock_stdout = "\n".join(
        [
            json.dumps({"type": "thread.started", "thread_id": "thread-wrapper"}),
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {
                        "type": "agent_message",
                        "text": _MOD.STOCK_CODEX_COMPAT_LIVE_SENTINEL,
                    },
                }
            ),
        ]
    )
    stock_codex.write_text(
        "#!/bin/sh\n"
        "cat <<'EOF'\n"
        f"{stock_stdout}\n"
        "EOF\n",
        encoding="utf-8",
    )
    stock_codex.chmod(0o755)
    evidence_path = tmp_path / "wrapper-evidence.json"

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "omnigent.stock_codex_compat_wrapper",
            "--stock-codex-path",
            str(stock_codex),
            "--route-prefix",
            _MOD.EXPECTED_ROUTE,
            "--evidence-path",
            str(evidence_path),
            "--",
            "exec",
            "--json",
            "prompt",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    events = _MOD._parse_stock_codex_exec_jsonl(completed.stdout)
    thread_id, first_agent_message = _MOD._validate_stock_codex_compat_live_events(events)
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))

    assert thread_id == "thread-wrapper"
    assert first_agent_message.startswith(_MOD.EXPECTED_ROUTE)
    assert _MOD.STOCK_CODEX_COMPAT_LIVE_SENTINEL in first_agent_message
    assert evidence["routeInjected"] is True
    assert evidence["routePresentAfter"] is True
    assert evidence["firstAgentMessageBefore"] == _MOD.STOCK_CODEX_COMPAT_LIVE_SENTINEL


def test_stock_codex_compat_wrapper_prefix_function_preserves_existing_route() -> None:
    agent_message = f"{_MOD.EXPECTED_ROUTE}\n\n{_MOD.STOCK_CODEX_COMPAT_LIVE_SENTINEL}"
    stdout = "\n".join(
        [
            json.dumps({"type": "thread.started", "thread_id": "thread-wrapper"}),
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {
                        "type": "agent_message",
                        "text": agent_message,
                    },
                }
            ),
        ]
    )

    transformed, evidence = stock_codex_compat_wrapper.prefix_first_agent_message(
        stdout,
        route_prefix=_MOD.EXPECTED_ROUTE,
        stock_codex_path="/tmp/codex",
    )
    events = _MOD._parse_stock_codex_exec_jsonl(transformed)
    _thread_id, first_agent_message = _MOD._validate_stock_codex_compat_live_events(events)

    assert first_agent_message == agent_message
    assert evidence.routeInjected is False
    assert evidence.routePresentAfter is True
    assert evidence.firstAgentMessageBefore == agent_message


def test_stock_codex_compat_wrapper_prepends_adapter_bin_to_path(
    tmp_path: Path,
) -> None:
    stock_codex = tmp_path / "bin" / "codex"
    adapter_package = tmp_path / "adapter-package"
    adapter_bin = adapter_package / "bin"
    adapter_bridge_dir = tmp_path / "adapter-bridge"
    stock_codex.parent.mkdir(parents=True)
    adapter_bin.mkdir(parents=True)
    adapter_bridge_dir.mkdir()
    _MOD._write_stock_codex_compat_adapter_probe(adapter_bin)
    adapter_manifest = _MOD._write_stock_codex_compat_adapter_manifest(
        adapter_package,
        adapter_bin,
    )
    stock_codex.write_text(
        "#!/bin/sh\n"
        "if [ \"${PATH%%:*}\" = \"$EXPECTED_ADAPTER_BIN\" ] && "
        "[ \"$OMNIGENT_STOCK_CODEX_COMPAT_ADAPTER_BRIDGE_DIR\" = "
        "\"$EXPECTED_ADAPTER_BRIDGE_DIR\" ]; then\n"
        "  text=ADAPTER_BIN_AND_BRIDGE_ON_PATH\n"
        "else\n"
        "  text=ADAPTER_BIN_OR_BRIDGE_MISSING\n"
        "fi\n"
        "printf '%s\\n' '{\"type\":\"thread.started\",\"thread_id\":\"thread-adapter-bin\"}'\n"
        "printf '%s\\n' "
        "'{\"type\":\"item.completed\",\"item\":{\"type\":\"agent_message\",\"text\":\"'\"$text\"'\"}}'\n",
        encoding="utf-8",
    )
    stock_codex.chmod(0o755)
    evidence_path = tmp_path / "wrapper-evidence.json"
    env = os.environ.copy()
    env["EXPECTED_ADAPTER_BIN"] = str(adapter_bin)
    env["EXPECTED_ADAPTER_BRIDGE_DIR"] = str(adapter_bridge_dir.resolve())

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "omnigent.stock_codex_compat_wrapper",
            "--stock-codex-path",
            str(stock_codex),
            "--route-prefix",
            _MOD.EXPECTED_ROUTE,
            "--evidence-path",
            str(evidence_path),
            "--adapter-bin",
            str(adapter_bin),
            "--adapter-manifest",
            str(adapter_manifest),
            "--adapter-bridge-dir",
            str(adapter_bridge_dir),
            "--",
            "exec",
            "--json",
            "prompt",
        ],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )

    events = _MOD._parse_stock_codex_exec_jsonl(completed.stdout)
    thread_id, first_agent_message = _MOD._validate_stock_codex_agent_message(
        events,
        expected_sentinel="ADAPTER_BIN_AND_BRIDGE_ON_PATH",
        proof_name="test",
    )
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))

    assert thread_id == "thread-adapter-bin"
    assert first_agent_message.startswith(_MOD.EXPECTED_ROUTE)
    assert evidence["adapterBin"] == str(adapter_bin.resolve())
    assert evidence["adapterManifest"] == str(adapter_manifest.resolve())
    assert evidence["adapterBridgeDir"] == str(adapter_bridge_dir.resolve())
    assert evidence["adapterToolNames"] == [_MOD.STOCK_CODEX_COMPAT_ADAPTER_COMMAND_NAME]


def test_stock_codex_compat_wrapper_starts_file_bridge_runtime_for_manifest(
    tmp_path: Path,
) -> None:
    fake_bin = tmp_path / "fake-bin"
    fake_sosumi = fake_bin / "sosumi"
    stock_codex = tmp_path / "stock-codex"
    adapter_bridge_dir = tmp_path / "adapter-bridge"
    adapter_package = write_stock_codex_compat_adapter_package(
        tmp_path / "adapter-package",
        (build_fetch_apple_docs_stock_codex_bridge_adapter_spec(),),
    )
    fake_bin.mkdir()
    fake_sosumi.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" != \"fetch\" ] || "
        "[ \"$2\" != \"https://developer.apple.com/documentation/swift/string\" ]; then\n"
        "  echo unexpected sosumi arguments >&2\n"
        "  exit 66\n"
        "fi\n"
        "cat <<'EOF'\n"
        "---\n"
        "title: String\n"
        "source: https://developer.apple.com/documentation/swift/string\n"
        "timestamp: 2026-07-04T12:00:00.000Z\n"
        "---\n"
        "EOF\n",
        encoding="utf-8",
    )
    fake_sosumi.chmod(0o755)
    stock_codex.write_text(
        "#!/usr/bin/env python3\n"
        "import json\n"
        "import subprocess\n"
        "command = \"fetch_apple_docs --url https://developer.apple.com/documentation/swift/string\"\n"
        "completed = subprocess.run(\n"
        "    [\"/bin/zsh\", \"-lc\", command],\n"
        "    check=False,\n"
        "    capture_output=True,\n"
        "    text=True,\n"
        ")\n"
        "output = completed.stdout + completed.stderr\n"
        "print(json.dumps({\n"
        "    \"type\": \"thread.started\",\n"
        "    \"thread_id\": \"thread-bridge-runtime\",\n"
        "}))\n"
        "print(json.dumps({\n"
        "    \"type\": \"item.completed\",\n"
        "    \"item\": {\n"
        "        \"type\": \"command_execution\",\n"
        "        \"command\": \"/bin/zsh -lc '\" + command + \"'\",\n"
        "        \"aggregated_output\": output,\n"
        "        \"exit_code\": completed.returncode,\n"
        "        \"status\": \"completed\",\n"
        "    },\n"
        "}))\n"
        "sentinel = (\n"
        "    \"WRAPPER_RUNTIME_BRIDGE_OK\"\n"
        "    if \"title: String\" in output\n"
        "    else \"WRAPPER_RUNTIME_BRIDGE_FAILED\"\n"
        ")\n"
        "print(json.dumps({\n"
        "    \"type\": \"item.completed\",\n"
        "    \"item\": {\"type\": \"agent_message\", \"text\": sentinel},\n"
        "}))\n"
        "raise SystemExit(completed.returncode)\n",
        encoding="utf-8",
    )
    stock_codex.chmod(0o755)
    evidence_path = tmp_path / "wrapper-evidence.json"
    env = {
        **os.environ,
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
    }

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "omnigent.stock_codex_compat_wrapper",
            "--stock-codex-path",
            str(stock_codex),
            "--route-prefix",
            _MOD.EXPECTED_ROUTE,
            "--evidence-path",
            str(evidence_path),
            "--adapter-bin",
            str(adapter_package.adapter_bin),
            "--adapter-manifest",
            str(adapter_package.manifest_path),
            "--adapter-bridge-dir",
            str(adapter_bridge_dir),
            "--",
            "exec",
            "--json",
            "prompt",
        ],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )

    events = _MOD._parse_stock_codex_exec_jsonl(completed.stdout)
    thread_id, first_agent_message = _MOD._validate_stock_codex_agent_message(
        events,
        expected_sentinel="WRAPPER_RUNTIME_BRIDGE_OK",
        proof_name="test",
    )
    command_item = _MOD._validate_stock_codex_adapter_command_execution_events(
        events,
        command_name="fetch_apple_docs",
        command_argument=APPLE_DOCS_CLI_URL,
        output_sentinel="title: String",
    )
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))

    assert thread_id == "thread-bridge-runtime"
    assert first_agent_message.startswith(_MOD.EXPECTED_ROUTE)
    assert "source: https://developer.apple.com/documentation/swift/string" in str(
        command_item["aggregated_output"]
    )
    assert (adapter_bridge_dir / "requests").is_dir()
    assert (adapter_bridge_dir / "responses").is_dir()
    assert evidence["adapterBridgeDir"] == str(adapter_bridge_dir.resolve())
    assert evidence["adapterToolNames"] == ["fetch_apple_docs"]


def test_stock_codex_bridge_diagnostics_validator_preserves_failure_payload() -> None:
    output = "\n".join(
        [
            "Error: url must be an https://developer.apple.com documentation URL",
            _MOD.STOCK_CODEX_COMPAT_BRIDGE_DIAGNOSTIC_PREFIX
            + json.dumps(
                {
                    "source": "omnigent-stock-codex-file-bridge",
                    "status": "error",
                    "exitCode": 64,
                    "diagnostics": {
                        "bridge": "stock-codex-file-bridge",
                        "requestId": "request-123",
                        "tool": "fetch_apple_docs",
                        "startedAt": "2026-07-07T00:00:00Z",
                        "completedAt": "2026-07-07T00:00:01Z",
                        "durationMs": 12.5,
                    },
                },
                sort_keys=True,
            ),
        ]
    )
    events = [
        {
            "type": "item.completed",
            "item": {
                "type": "command_execution",
                "command": (
                    "/bin/zsh -lc 'fetch_apple_docs --url "
                    "https://example.com/documentation/swift/string'"
                ),
                "aggregated_output": output,
                "exit_code": 64,
                "status": "failed",
            },
        }
    ]

    command_item, diagnostic = (
        _MOD._validate_stock_codex_adapter_diagnostic_command_execution_events(
            events,
            command_name="fetch_apple_docs",
            command_argument="https://example.com/documentation/swift/string",
            expected_exit_code=64,
        )
    )

    assert command_item["exit_code"] == 64
    assert diagnostic["diagnostics"]["requestId"] == "request-123"
    assert diagnostic["diagnostics"]["tool"] == "fetch_apple_docs"


def test_stock_codex_compat_wrapper_rejects_missing_adapter_executable(
    tmp_path: Path,
) -> None:
    adapter_package = tmp_path / "adapter-package"
    adapter_bin = adapter_package / "bin"
    adapter_bin.mkdir(parents=True)
    adapter_manifest = _MOD._write_stock_codex_compat_adapter_manifest(
        adapter_package,
        adapter_bin,
    )

    with pytest.raises(SystemExit, match="command is not executable"):
        stock_codex_compat_wrapper.validate_adapter_manifest(
            adapter_manifest,
            adapter_bin,
        )


def test_stock_codex_compat_wrapper_rejects_open_adapter_schema(
    tmp_path: Path,
) -> None:
    adapter_package = tmp_path / "adapter-package"
    adapter_bin = adapter_package / "bin"
    adapter_bin.mkdir(parents=True)
    _MOD._write_stock_codex_compat_adapter_probe(adapter_bin)
    adapter_manifest = _MOD._write_stock_codex_compat_adapter_manifest(
        adapter_package,
        adapter_bin,
    )
    payload = json.loads(adapter_manifest.read_text(encoding="utf-8"))
    payload["tools"][0]["parameters"]["additionalProperties"] = True
    adapter_manifest.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    with pytest.raises(SystemExit, match="additionalProperties=false"):
        stock_codex_compat_wrapper.validate_adapter_manifest(
            adapter_manifest,
            adapter_bin,
        )


def test_stock_codex_compat_wrapper_validates_multi_tool_adapter_manifest(
    tmp_path: Path,
) -> None:
    adapter_package = tmp_path / "adapter-package"
    adapter_bin = adapter_package / "bin"
    adapter_bin.mkdir(parents=True)
    tool_specs = _MOD._stock_codex_compat_adapter_arbitration_tool_specs()
    for spec in tool_specs:
        _MOD._write_stock_codex_compat_adapter_command(adapter_bin, spec)
    adapter_manifest = _MOD._write_stock_codex_compat_adapter_manifest(
        adapter_package,
        adapter_bin,
        tool_specs=tool_specs,
    )

    package = stock_codex_compat_wrapper.validate_adapter_manifest(
        adapter_manifest,
        adapter_bin,
    )

    assert package.tool_names == tuple(spec.name for spec in tool_specs)


def test_stock_codex_command_execution_parser_requires_sentinel_output() -> None:
    stdout = "\n".join(
        [
            json.dumps({"type": "thread.started", "thread_id": "thread-wrapper"}),
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {
                        "id": "item_2",
                        "type": "command_execution",
                        "command": "/bin/zsh -lc 'cat tool-proof.txt'",
                        "aggregated_output": f"{_MOD.TOOL_SENTINEL}\n",
                        "exit_code": 0,
                        "status": "completed",
                    },
                }
            ),
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {
                        "type": "agent_message",
                        "text": (
                            f"{_MOD.EXPECTED_ROUTE}\n\n"
                            f"{_MOD.STOCK_CODEX_COMPAT_WRAPPER_TOOL_SENTINEL}"
                        ),
                    },
                }
            ),
        ]
    )

    events = _MOD._parse_stock_codex_exec_jsonl(stdout)
    thread_id, first_agent_message = _MOD._validate_stock_codex_agent_message(
        events,
        expected_sentinel=_MOD.STOCK_CODEX_COMPAT_WRAPPER_TOOL_SENTINEL,
        proof_name="test",
    )
    command_item = _MOD._validate_stock_codex_command_execution_events(events)

    assert thread_id == "thread-wrapper"
    assert first_agent_message.startswith(_MOD.EXPECTED_ROUTE)
    assert command_item["aggregated_output"] == f"{_MOD.TOOL_SENTINEL}\n"


def test_stock_codex_adapter_command_parser_requires_sentinel_output() -> None:
    adapter_output = json.dumps(
        {
            "source": "omnigent-wrapper-adapter",
            "sentinel": _MOD.STOCK_CODEX_COMPAT_ADAPTER_OUTPUT_SENTINEL,
            "message": _MOD.STOCK_CODEX_COMPAT_ADAPTER_COMMAND_ARGUMENT,
        }
    )
    stdout = "\n".join(
        [
            json.dumps({"type": "thread.started", "thread_id": "thread-adapter"}),
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {
                        "id": "item_adapter",
                        "type": "command_execution",
                        "command": (
                            "/bin/zsh -lc 'omnigent-wrapper-adapter-probe "
                            "--message stock-codex-wrapper-adapter-proof'"
                        ),
                        "aggregated_output": f"{adapter_output}\n",
                        "exit_code": 0,
                        "status": "completed",
                    },
                }
            ),
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {
                        "type": "agent_message",
                        "text": (
                            f"{_MOD.EXPECTED_ROUTE}\n\n"
                            f"{_MOD.STOCK_CODEX_COMPAT_WRAPPER_ADAPTER_TOOL_SENTINEL}"
                        ),
                    },
                }
            ),
        ]
    )

    events = _MOD._parse_stock_codex_exec_jsonl(stdout)
    thread_id, first_agent_message = _MOD._validate_stock_codex_agent_message(
        events,
        expected_sentinel=_MOD.STOCK_CODEX_COMPAT_WRAPPER_ADAPTER_TOOL_SENTINEL,
        proof_name="test",
    )
    command_item = _MOD._validate_stock_codex_adapter_command_execution_events(events)

    assert thread_id == "thread-adapter"
    assert first_agent_message.startswith(_MOD.EXPECTED_ROUTE)
    assert _MOD.STOCK_CODEX_COMPAT_ADAPTER_OUTPUT_SENTINEL in command_item["aggregated_output"]


def test_stock_codex_adapter_command_parser_rejects_forbidden_adapter() -> None:
    selected_spec, rejected_spec = _MOD._stock_codex_compat_adapter_arbitration_tool_specs()
    output = json.dumps(
        {
            "source": "omnigent-wrapper-adapter",
            "tool": selected_spec.name,
            "capability": selected_spec.capability,
            "sentinel": selected_spec.output_sentinel,
            "message": selected_spec.argument,
            "unexpected": rejected_spec.output_sentinel,
        }
    )
    stdout = "\n".join(
        [
            json.dumps({"type": "thread.started", "thread_id": "thread-adapter"}),
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {
                        "id": "item_adapter",
                        "type": "command_execution",
                        "command": (
                            f"/bin/zsh -lc '{selected_spec.name} "
                            f"--message {selected_spec.argument}'"
                        ),
                        "aggregated_output": f"{output}\n",
                        "exit_code": 0,
                        "status": "completed",
                    },
                }
            ),
        ]
    )
    events = _MOD._parse_stock_codex_exec_jsonl(stdout)

    with pytest.raises(SystemExit, match="rejected adapter sentinel"):
        _MOD._validate_stock_codex_adapter_command_execution_events(
            events,
            command_name=selected_spec.name,
            command_argument=selected_spec.argument,
            output_sentinel=selected_spec.output_sentinel,
            forbidden_command_names=(rejected_spec.name,),
            forbidden_output_sentinels=(rejected_spec.output_sentinel,),
        )


def test_stock_codex_omnigent_relay_tool_parser_requires_executor_and_jsonl_output() -> None:
    stdout = "\n".join(
        [
            json.dumps({"type": "thread.started", "thread_id": "thread-relay"}),
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {
                        "id": "item_call",
                        "type": "mcp_tool_call",
                        "name": f"mcp__omnigent__{_MOD.STOCK_CODEX_COMPAT_RELAY_TOOL_NAME}",
                        "arguments": {
                            "message": _MOD.STOCK_CODEX_COMPAT_RELAY_TOOL_ARGUMENT
                        },
                    },
                }
            ),
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {
                        "id": "item_output",
                        "type": "mcp_tool_result",
                        "call_id": "item_call",
                        "content": [
                            {
                                "type": "text",
                                "text": json.dumps(
                                    {
                                        "sentinel": (
                                            _MOD.STOCK_CODEX_COMPAT_RELAY_TOOL_OUTPUT_SENTINEL
                                        )
                                    }
                                ),
                            }
                        ],
                    },
                }
            ),
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {
                        "type": "agent_message",
                        "text": (
                            f"{_MOD.EXPECTED_ROUTE}\n\n"
                            f"{_MOD.STOCK_CODEX_COMPAT_WRAPPER_RELAY_TOOL_SENTINEL}"
                        ),
                    },
                }
            ),
        ]
    )

    events = _MOD._parse_stock_codex_exec_jsonl(stdout)
    thread_id, first_agent_message = _MOD._validate_stock_codex_agent_message(
        events,
        expected_sentinel=_MOD.STOCK_CODEX_COMPAT_WRAPPER_RELAY_TOOL_SENTINEL,
        proof_name="test",
    )
    evidence = _MOD._validate_stock_codex_omnigent_relay_tool_events(
        events,
        tool_name=_MOD.STOCK_CODEX_COMPAT_RELAY_TOOL_NAME,
        output_sentinel=_MOD.STOCK_CODEX_COMPAT_RELAY_TOOL_OUTPUT_SENTINEL,
        executor_calls=[
            {
                "name": _MOD.STOCK_CODEX_COMPAT_RELAY_TOOL_NAME,
                "arguments": {"message": _MOD.STOCK_CODEX_COMPAT_RELAY_TOOL_ARGUMENT},
            }
        ],
    )

    assert thread_id == "thread-relay"
    assert first_agent_message.startswith(_MOD.EXPECTED_ROUTE)
    assert evidence["arguments"] == {"message": _MOD.STOCK_CODEX_COMPAT_RELAY_TOOL_ARGUMENT}
    assert evidence["event_types"] == ("mcp_tool_call", "mcp_tool_result")
    assert _MOD.STOCK_CODEX_COMPAT_RELAY_TOOL_OUTPUT_SENTINEL in evidence["output_preview"]


def test_app_bundle_entrypoint_proof_builds_probeable_temporary_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stock_codex = _write_codex_binary(tmp_path / "bin" / "codex")
    uvx = _write_uvx_binary(tmp_path / "tools" / "uvx")
    monkeypatch.setenv(
        "PATH",
        f"{uvx.parent}{os.pathsep}{os.environ.get('PATH', '')}",
    )

    proof = _MOD.run_app_bundle_entrypoint_proof(stock_codex)

    assert proof.app_bundle_path.name == "Omnigent Codex.app"
    assert proof.executable_path.name == "omnigent-codex"
    assert proof.info_plist_path.name == "Info.plist"
    assert proof.bundle_identifier == "ai.omnigent.codex"
    assert proof.bundle_executable == "omnigent-codex"
    assert proof.stock_codex_path == stock_codex.resolve()
    assert proof.stock_codex_version == "codex-cli 0.142.2"
    assert proof.uvx_path == uvx.resolve()
    assert _MOD.APP_BUNDLE_ENTRYPOINT_SENTINEL in proof.probe_output
    assert (
        f"pinned_env={_MOD.OMNIGENT_STOCK_CODEX_PATH_ENV}={stock_codex.resolve()}"
        in proof.probe_output
    )
    assert f"delegates_to={uvx.resolve()} --from {_REPO_ROOT} omnigent codex" in proof.probe_output


def test_app_bundle_entrypoint_proof_requires_uvx(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stock_codex = _write_codex_binary(tmp_path / "bin" / "codex")
    empty_path = tmp_path / "empty-path"
    empty_path.mkdir()
    monkeypatch.setenv("PATH", str(empty_path))

    with pytest.raises(SystemExit) as excinfo:
        _MOD.run_app_bundle_entrypoint_proof(stock_codex)

    assert "Could not find uvx on PATH" in str(excinfo.value)


def test_stock_codex_compat_launcher_activation_proof_runs_wrapper_bridge(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uvx = _write_wrapper_uvx_binary(tmp_path / "tools" / "uvx")
    monkeypatch.setenv(
        "PATH",
        f"{uvx.parent}{os.pathsep}{os.environ.get('PATH', '')}",
    )
    monkeypatch.delenv(_MOD.OMNIGENT_STOCK_CODEX_PATH_ENV, raising=False)

    proof = _MOD.run_stock_codex_compat_launcher_activation_proof(timeout_seconds=30)

    assert proof.launcher_path.name == "codex"
    assert proof.manifest_path.name == "launcher-manifest.json"
    assert proof.stock_codex_path.name == "codex"
    assert proof.stock_codex_version == "codex-cli 0.142.2"
    assert proof.uvx_path == uvx.resolve()
    assert proof.resolved_codex_path == proof.stock_codex_path.resolve()
    assert proof.adapter_tool_names == ("fetch_apple_docs",)
    assert proof.sandbox == "workspace-write"
    assert proof.thread_id == "thread-stock-codex-compat-launcher"
    assert proof.route_injected is True
    assert proof.first_agent_message.startswith(_MOD.EXPECTED_ROUTE)
    assert _MOD.STOCK_CODEX_COMPAT_LAUNCHER_ACTIVATION_SENTINEL in (
        proof.first_agent_message
    )
    assert "title: String" in proof.command_output
    assert "source: https://developer.apple.com/documentation/swift/string" in (
        proof.command_output
    )
    assert _MOD.APPLE_DOCS_CLI_TOOL in proof.command
    assert proof.uninstall_action == "uninstalled"
    assert not proof.launcher_path.exists()
    assert not proof.manifest_path.exists()


def test_stock_codex_compat_launcher_doctor_proof_is_non_mutating(
    tmp_path: Path,
) -> None:
    stock_codex = _write_codex_binary(tmp_path / "stock" / "codex")
    uvx = _write_uvx_binary(tmp_path / "tools" / "uvx")
    launcher_path = tmp_path / "bin" / "omnigent-stock-codex-compat"
    manifest_path = tmp_path / "manifest.json"

    proof = _MOD.run_stock_codex_compat_launcher_doctor_proof(
        stock_codex,
        launcher_path=launcher_path,
        manifest_path=manifest_path,
        uvx_path=uvx,
    )

    assert proof.stock_codex_path == stock_codex.resolve()
    assert proof.stock_codex_version == "codex-cli 0.142.2"
    assert proof.launcher_path == launcher_path
    assert proof.manifest_path == manifest_path
    assert proof.uvx_path == uvx.resolve()
    assert proof.adapter_tool_names == ("fetch_apple_docs",)
    assert proof.adapter_package_dir.name == "adapter-package"
    assert proof.install_allowed is True
    assert proof.install_blocker is None
    assert proof.existing_target_state == "absent"
    assert proof.mutates_filesystem is False
    assert "--install" in proof.install_command
    assert "--uninstall" in proof.rollback_command
    assert not launcher_path.exists()
    assert not manifest_path.exists()


def test_stock_codex_compat_clean_install_proof_uses_clean_home_defaults(
    tmp_path: Path,
) -> None:
    stock_codex = _write_codex_binary(tmp_path / "stock" / "codex")
    uvx = _write_uvx_binary(tmp_path / "tools" / "uvx")

    proof = _MOD.run_stock_codex_compat_clean_install_proof(
        stock_codex,
        uvx_path=uvx,
    )

    assert proof.stock_codex_path == stock_codex.resolve()
    assert proof.stock_codex_version == "codex-cli 0.142.2"
    assert proof.clean_home.name == "home"
    assert proof.clean_bin_dir == proof.clean_home / ".local" / "bin"
    assert proof.launcher_path == proof.clean_bin_dir / "omnigent-stock-codex-compat"
    assert proof.manifest_path == (
        proof.clean_home / ".local" / "omnigent" / "launchers" / "stock-codex-compat.json"
    )
    assert proof.adapter_package_dir == (
        proof.clean_home
        / ".local"
        / "omnigent"
        / "stock-codex-compat"
        / "adapter-package"
    )
    assert proof.adapter_bin == proof.adapter_package_dir / "bin"
    assert proof.adapter_manifest == proof.adapter_package_dir / "adapter-manifest.json"
    assert proof.adapter_tool_names == ("fetch_apple_docs",)
    assert proof.uvx_path == uvx.resolve()
    assert proof.selected_command_path == proof.launcher_path
    assert proof.version_output == "codex-cli 0.142.2"
    assert "OMNIGENT_STOCK_CODEX_COMPAT_LAUNCHER_OK" in proof.probe_output
    assert proof.adapter_package_action == "adapter-package-installed"
    assert proof.install_action == "installed"
    assert proof.rollback_action == "uninstalled"
    assert proof.doctor_install_allowed is True
    assert proof.doctor_existing_target_state == "managed"
    assert proof.doctor_existing_target_managed is True
    assert proof.doctor_target_selected_on_path is True
    assert proof.doctor_mutates_filesystem is False
    assert proof.launcher_removed_after_rollback is True
    assert proof.manifest_removed_after_rollback is True
    assert not proof.launcher_path.exists()
    assert not proof.manifest_path.exists()


def test_stock_codex_compat_bundle_install_proof_uses_extracted_runtime(
    tmp_path: Path,
) -> None:
    stock_codex = _write_codex_binary(tmp_path / "stock" / "codex")
    uvx = _write_uvx_binary(tmp_path / "tools" / "uvx")

    proof = _MOD.run_stock_codex_compat_bundle_install_proof(
        stock_codex,
        uvx_path=uvx,
    )

    assert proof.stock_codex_path == stock_codex.resolve()
    assert proof.stock_codex_version == "codex-cli 0.142.2"
    assert len(proof.bundle_sha256) == 64
    assert proof.extracted_bundle_root.name == "omnigent-stock-codex-compat-bundle"
    assert proof.extracted_runtime_root.name == "runtime"
    assert proof.installer_script_path == (
        proof.extracted_runtime_root
        / "scripts"
        / "install_stock_codex_compat_launcher.py"
    )
    assert proof.clean_home.name == "home"
    assert proof.clean_bin_dir == proof.clean_home / ".local" / "bin"
    assert proof.launcher_path == proof.clean_bin_dir / "omnigent-stock-codex-compat"
    assert proof.manifest_path == (
        proof.clean_home / ".local" / "omnigent" / "launchers" / "stock-codex-compat.json"
    )
    assert proof.adapter_package_dir == (
        proof.clean_home
        / ".local"
        / "omnigent"
        / "stock-codex-compat"
        / "adapter-package"
    )
    assert proof.adapter_bin == proof.adapter_package_dir / "bin"
    assert proof.adapter_manifest == proof.adapter_package_dir / "adapter-manifest.json"
    assert proof.adapter_tool_names == ("fetch_apple_docs",)
    assert proof.uvx_path == uvx.resolve()
    assert proof.selected_command_path == proof.launcher_path
    assert proof.launcher_manifest_repo_root == proof.extracted_runtime_root
    assert proof.version_output == "codex-cli 0.142.2"
    assert "OMNIGENT_STOCK_CODEX_COMPAT_LAUNCHER_OK" in proof.probe_output
    assert str(proof.extracted_runtime_root) in proof.probe_output
    assert proof.adapter_package_action == "adapter-package-installed"
    assert proof.install_action == "installed"
    assert proof.rollback_action == "uninstalled"
    assert proof.doctor_install_allowed is True
    assert proof.doctor_existing_target_state == "managed"
    assert proof.doctor_existing_target_managed is True
    assert proof.doctor_target_selected_on_path is True
    assert proof.doctor_mutates_filesystem is False
    assert proof.launcher_removed_after_rollback is True
    assert proof.manifest_removed_after_rollback is True
    assert not proof.bundle_path.exists()
    assert not proof.extracted_runtime_root.exists()
    assert not proof.launcher_path.exists()
    assert not proof.manifest_path.exists()


def test_stock_codex_compat_pkg_structure_proof_builds_unsigned_pkg() -> None:
    if shutil.which("pkgbuild") is None or shutil.which("pkgutil") is None:
        pytest.skip("macOS pkgbuild/pkgutil are required for pkg structure tests")

    proof = _MOD.run_stock_codex_compat_pkg_structure_proof()

    assert len(proof.package_sha256) == 64
    assert len(proof.source_bundle_sha256) == 64
    assert proof.package_identifier == "ai.omnigent.stock-codex-compat"
    assert proof.package_version == "0.3.0.dev0"
    assert proof.install_location == "/"
    assert proof.install_prefix == Path(
        "/Library/Application Support/Omnigent/stock-codex-compat"
    )
    assert proof.runtime_root == proof.install_prefix / "runtime"
    assert proof.payload_file_count > 0
    assert all(proof.required_payload_files.values())
    assert "postinstall" in proof.script_names
    assert set(proof.archive_entries) >= {"Bom", "PackageInfo", "Payload", "Scripts"}
    assert proof.signature_status == "no signature"
    assert proof.signed is False
    assert proof.pkg_contract["runtime"] == "machine-level-runtime-only"
    assert proof.pkg_contract["userBootstrap"] == "deferred-to-installed-runtime-command"
    assert proof.bundle_source_root == "<omitted-from-pkg>"


def test_stock_codex_compat_pkg_runtime_live_proof_uses_expanded_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if shutil.which("pkgbuild") is None or shutil.which("pkgutil") is None:
        pytest.skip("macOS pkgbuild/pkgutil are required for pkg runtime tests")

    source_bundle = _write_plugin_bundle(tmp_path / "source-plugin")
    stock_codex = _write_live_codex_binary(tmp_path / "stock" / "codex")
    uvx = _write_wrapper_uvx_binary(tmp_path / "tools" / "uvx")
    auth_path = _write_auth(
        tmp_path / "real-codex-home",
        {"auth_mode": "api", "OPENAI_API_KEY": "sk-test-proof-fixture"},
    )
    monkeypatch.setenv("PATH", f"{uvx.parent}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setattr(
        _MOD,
        "_stock_replacement_auth_source",
        lambda: (auth_path, "test-fixture"),
    )
    monkeypatch.setattr(
        _MOD.codex_native,
        "_codex_auth_json_has_available_credential",
        lambda path: path == auth_path,
    )

    def fake_run_stock_codex_json(
        stock_codex_path: Path,
        args: list[str],
        *,
        env: dict[str, str],
        timeout: float = 30.0,
    ) -> dict[str, Any] | list[dict[str, Any]]:
        del stock_codex_path, env, timeout
        if args[:3] == ["plugin", "marketplace", "add"]:
            return {"ok": True}
        if args == ["plugin", "add", _MOD.STOCK_CODEX_COMPAT_PLUGIN_ID, "--json"]:
            return {"ok": True}
        if args == ["plugin", "list", "--json"]:
            return {
                "installed": [
                    {"pluginId": _MOD.STOCK_CODEX_COMPAT_PLUGIN_ID, "enabled": True}
                ]
            }
        if args == ["plugin", "marketplace", "list", "--json"]:
            return {"marketplaces": [{"name": _MOD.STOCK_CODEX_COMPAT_MARKETPLACE}]}
        if args == ["mcp", "list", "--json"]:
            return [{"name": "omnigent"}, {"name": "memory"}]
        if args == ["mcp", "get", "omnigent", "--json"]:
            return {"name": "omnigent", "transport": {"command": "python", "args": []}}
        raise AssertionError(f"unexpected stock codex JSON args: {args!r}")

    monkeypatch.setattr(_MOD, "_run_stock_codex_json", fake_run_stock_codex_json)
    monkeypatch.setattr(
        _MOD,
        "_validate_stock_codex_compat_plugin_state",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        _MOD,
        "_validate_stock_codex_compat_bridge",
        lambda **kwargs: (
            ("PostToolUse", "PreToolUse", "UserPromptSubmit"),
            ("memory", "omnigent"),
            "python",
            (),
        ),
    )

    proof = _MOD.run_stock_codex_compat_pkg_runtime_live_proof(
        source_bundle,
        stock_codex,
        workspace_root=_REPO_ROOT,
        timeout_seconds=30,
    )

    assert proof.stock_codex_path == stock_codex.resolve()
    assert proof.stock_codex_version == "codex-cli 0.142.2"
    assert proof.package_identifier == "ai.omnigent.stock-codex-compat"
    assert len(proof.package_sha256) == 64
    assert proof.packaged_runtime_root == (
        Path("/Library/Application Support/Omnigent/stock-codex-compat/runtime")
    )
    assert proof.expanded_runtime_root.name == "runtime"
    assert proof.expanded_runtime_root != _REPO_ROOT
    assert proof.uvx_path == uvx.resolve()
    assert proof.wrapper_command[:4] == (
        str(uvx.resolve()),
        "--from",
        str(proof.expanded_runtime_root),
        "omnigent-stock-codex-wrapper",
    )
    assert "exec" in proof.wrapper_command
    assert "--enable" in proof.wrapper_command
    assert proof.enabled_features == ("route_selection", "model_context_protocol")
    assert proof.thread_id == "thread-stock-codex-compat-pkg-runtime"
    assert proof.route_injected is True
    assert proof.first_agent_message_before_wrapper == _MOD.STOCK_CODEX_COMPAT_LIVE_SENTINEL
    assert proof.first_agent_message.startswith(_MOD.EXPECTED_ROUTE)
    assert _MOD.STOCK_CODEX_COMPAT_LIVE_SENTINEL in proof.first_agent_message


def test_stock_codex_compat_pkg_user_bootstrap_proof_uses_installed_runtime(
    tmp_path: Path,
) -> None:
    if shutil.which("pkgbuild") is None or shutil.which("pkgutil") is None:
        pytest.skip("macOS pkgbuild/pkgutil are required for pkg bootstrap tests")

    stock_codex = _write_codex_binary(tmp_path / "stock" / "codex")
    uvx = _write_installer_uvx_binary(tmp_path / "tools" / "uvx")

    proof = _MOD.run_stock_codex_compat_pkg_user_bootstrap_proof(
        stock_codex,
        uvx_path=uvx,
    )

    assert proof.stock_codex_path == stock_codex.resolve()
    assert proof.stock_codex_version == "codex-cli 0.142.2"
    assert proof.package_identifier == "ai.omnigent.stock-codex-compat"
    assert len(proof.package_sha256) == 64
    assert proof.install_root.name == "installed-root"
    assert proof.installed_prefix == (
        proof.install_root / "Library" / "Application Support" / "Omnigent" / "stock-codex-compat"
    )
    assert proof.installed_runtime_root == proof.installed_prefix / "runtime"
    assert proof.installer_script_path == (
        proof.installed_runtime_root
        / "scripts"
        / "install_stock_codex_compat_launcher.py"
    )
    assert proof.pkg_manifest_path == proof.installed_prefix / "pkg-manifest.json"
    assert proof.bundle_manifest_path == proof.installed_prefix / "bundle-manifest.json"
    assert proof.clean_home.name == "home"
    assert proof.clean_bin_dir == proof.clean_home / ".local" / "bin"
    assert proof.launcher_path == proof.clean_bin_dir / "omnigent-stock-codex-compat"
    assert proof.manifest_path == (
        proof.clean_home / ".local" / "omnigent" / "launchers" / "stock-codex-compat.json"
    )
    assert proof.adapter_package_dir == (
        proof.clean_home
        / ".local"
        / "omnigent"
        / "stock-codex-compat"
        / "adapter-package"
    )
    assert proof.adapter_bin == proof.adapter_package_dir / "bin"
    assert proof.adapter_manifest == proof.adapter_package_dir / "adapter-manifest.json"
    assert proof.adapter_bridge_dir == (
        proof.clean_home / ".local" / "omnigent" / "stock-codex-compat" / "adapter-bridge"
    )
    assert proof.adapter_tool_names == ("fetch_apple_docs",)
    assert proof.uvx_path == uvx.resolve()
    assert proof.selected_command_path == proof.launcher_path
    assert proof.launcher_manifest_repo_root == proof.installed_runtime_root
    assert proof.launcher_manifest_wrapper_entrypoint == "omnigent-stock-codex-wrapper"
    assert proof.launcher_manifest_adapter_tool_names == ("fetch_apple_docs",)
    assert proof.version_output == "codex-cli 0.142.2"
    assert "OMNIGENT_STOCK_CODEX_COMPAT_LAUNCHER_OK" in proof.probe_output
    assert str(proof.installed_runtime_root) in proof.probe_output
    assert proof.adapter_package_action == "adapter-package-installed"
    assert proof.install_action == "installed"
    assert proof.update_action == "installed"
    assert str(proof.installed_runtime_root) in proof.rollback_command
    assert proof.rollback_action == "uninstalled"
    assert proof.doctor_install_allowed is True
    assert proof.doctor_existing_target_state == "managed"
    assert proof.doctor_existing_target_managed is True
    assert proof.doctor_target_selected_on_path is True
    assert proof.doctor_mutates_filesystem is False
    assert proof.adapter_package_exists_after_install is True
    assert proof.launcher_removed_after_rollback is True
    assert proof.manifest_removed_after_rollback is True
    assert not proof.launcher_path.exists()
    assert not proof.manifest_path.exists()


def test_stock_codex_compat_pkg_clean_provision_proof_uses_installed_runtime(
    tmp_path: Path,
) -> None:
    if shutil.which("pkgbuild") is None or shutil.which("pkgutil") is None:
        pytest.skip("macOS pkgbuild/pkgutil are required for pkg provisioning tests")

    stock_codex = _write_codex_binary(tmp_path / "stock" / "codex")

    proof = _MOD.run_stock_codex_compat_pkg_clean_provision_proof(stock_codex)

    assert proof.stock_codex_path == stock_codex.resolve()
    assert proof.stock_codex_version == "codex-cli 0.142.2"
    assert len(proof.stock_codex_sha256) == 64
    assert proof.package_identifier == "ai.omnigent.stock-codex-compat"
    assert len(proof.package_sha256) == 64
    assert proof.install_root.name == "installed-root"
    assert proof.installed_prefix == (
        proof.install_root / "Library" / "Application Support" / "Omnigent" / "stock-codex-compat"
    )
    assert proof.installed_runtime_root == proof.installed_prefix / "runtime"
    assert proof.provisioner_script_path == (
        proof.installed_runtime_root / "scripts" / "provision_stock_codex.py"
    )
    assert proof.pkg_manifest_path == proof.installed_prefix / "pkg-manifest.json"
    assert proof.bundle_manifest_path == proof.installed_prefix / "bundle-manifest.json"
    assert proof.clean_home.name == "home"
    assert proof.clean_cache_root == (
        proof.clean_home / ".local" / "omnigent" / "codex-stock"
    )
    assert proof.channel_manifest_path.name == "channel.json"
    assert proof.channel_artifact_path == (
        proof.channel_manifest_path.parent / "artifacts" / "codex"
    )
    assert proof.payload_dir == proof.clean_cache_root / "0.142.2"
    assert proof.provisioned_codex_path == proof.payload_dir / "codex"
    assert proof.provisioned_manifest_path == proof.payload_dir / "manifest.json"
    assert proof.provisioned_version == "codex-cli 0.142.2"
    assert proof.provisioned_sha256 == proof.stock_codex_sha256
    assert proof.provisioned_source_kind == "channel"
    assert proof.provisioned_env_path == proof.provisioned_codex_path
    assert proof.omnigent_resolved_codex_path == proof.provisioned_codex_path
    assert proof.reuse_payload_dir == proof.payload_dir
    assert proof.reuse_provisioned_codex_path == proof.provisioned_codex_path
    assert proof.host_cache_referenced is False


def test_stock_codex_compat_pkg_update_acquisition_proof_uses_installed_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host_home = tmp_path / "host-home"
    stock_codex = _write_codex_binary(
        tmp_path / "stock" / "codex",
        version="codex-cli 0.142.5",
    )
    cask_url = (
        "https://github.com/openai/codex/releases/download/"
        "rust-v0.143.0/codex-aarch64-apple-darwin.tar.gz"
    )
    cask_sha = "a" * 64
    channel = _MOD._GitHubLatestStableCodexChannel(
        tag_name="rust-v0.143.0",
        version_slug="0.143.0",
        selected_version="codex-cli 0.143.0",
        release_name="0.143.0",
        release_html_url="https://github.com/openai/codex/releases/tag/rust-v0.143.0",
        published_at="2026-07-08T01:31:10Z",
        asset_name="codex-aarch64-apple-darwin.tar.gz",
        asset_url=cask_url,
        asset_digest=f"sha256:{cask_sha}",
        asset_sha256=cask_sha,
        archive_executable="codex-aarch64-apple-darwin",
    )
    expected_artifact = {
        "archiveExecutable": "codex-aarch64-apple-darwin",
        "archiveFormat": "tar.gz",
        "sha256": cask_sha,
        "url": cask_url,
        "version": "codex-cli 0.143.0",
        "versionSlug": "0.143.0",
    }
    monkeypatch.setenv("HOME", str(host_home))
    monkeypatch.setattr(_MOD, "_github_latest_stable_codex_channel", lambda: channel)
    monkeypatch.setattr(
        _MOD,
        "_read_homebrew_codex_cask",
        lambda: (_ for _ in ()).throw(AssertionError("Homebrew should not be read")),
    )

    package_path = tmp_path / "artifacts" / "omnigent-stock-codex-compat.pkg"
    package_path.parent.mkdir(parents=True)
    package_path.write_bytes(b"fake-pkg")
    install_prefix = Path("/Library/Application Support/Omnigent/stock-codex-compat")
    package_proof = _MOD.StockCodexCompatPkgStructureProof(
        package_path=package_path,
        package_sha256=_MOD.sha256_file(package_path),
        source_bundle_sha256="b" * 64,
        package_identifier="ai.omnigent.stock-codex-compat",
        package_version="0.3.0.dev0",
        install_location="/",
        install_prefix=install_prefix,
        runtime_root=install_prefix / "runtime",
        payload_file_count=1,
        required_payload_files={"runtime/scripts/provision_stock_codex.py": True},
        script_names=("postinstall",),
        archive_entries=("Bom", "PackageInfo", "Payload", "Scripts"),
        signature_status="no signature",
        signed=False,
        pkg_manifest_path=install_prefix / "pkg-manifest.json",
        bundle_manifest_path=install_prefix / "bundle-manifest.json",
        pkg_contract={
            "runtime": "machine-level-runtime-only",
            "userBootstrap": "deferred-to-installed-runtime-command",
            "stockCodexProvisioning": "deferred-to-installed-runtime-command",
        },
        bundle_source_root="<omitted-from-pkg>",
    )

    monkeypatch.setattr(
        _MOD,
        "_run_stock_codex_compat_pkg_builder_cli_json",
        lambda *_args, **_kwargs: {"kind": "fake-pkg-builder-payload"},
    )
    monkeypatch.setattr(
        _MOD,
        "_validate_stock_codex_compat_pkg_builder_payload",
        lambda *_args, **_kwargs: package_proof,
    )

    def fake_expand(package_path_arg: Path, expand_dir: Path) -> Path:
        assert package_path_arg == package_path
        payload_root = expand_dir / "Payload"
        payload_root.mkdir(parents=True)
        return payload_root

    def fake_stage(
        *,
        payload_root: Path,
        install_root: Path,
        packaged_runtime_root: Path,
        source_repo_root: Path,
    ) -> Path:
        del payload_root, packaged_runtime_root, source_repo_root
        installed_prefix = install_root / install_prefix.relative_to("/")
        runtime_root = installed_prefix / "runtime"
        (runtime_root / "scripts").mkdir(parents=True)
        (runtime_root / "scripts" / "provision_stock_codex.py").write_text(
            "#!/usr/bin/env python3\n",
            encoding="utf-8",
        )
        pkg_manifest = {
            "contract": {
                "runtime": "machine-level-runtime-only",
                "userBootstrap": "deferred-to-installed-runtime-command",
                "stockCodexProvisioning": "deferred-to-installed-runtime-command",
            },
            "stockCodexProvisioner": str(
                package_proof.runtime_root / "scripts" / "provision_stock_codex.py"
            ),
        }
        bundle_manifest = {"sourceRoot": "<omitted-from-pkg>"}
        (installed_prefix / "pkg-manifest.json").write_text(
            json.dumps(pkg_manifest) + "\n",
            encoding="utf-8",
        )
        (installed_prefix / "bundle-manifest.json").write_text(
            json.dumps(bundle_manifest) + "\n",
            encoding="utf-8",
        )
        return runtime_root

    monkeypatch.setattr(_MOD, "_expand_stock_codex_compat_pkg", fake_expand)
    monkeypatch.setattr(_MOD, "_stage_stock_codex_compat_pkg_install_root", fake_stage)

    def fake_run(
        cmd: list[str],
        *,
        check: bool = False,
        capture_output: bool = False,
        text: bool = False,
        env: dict[str, str] | None = None,
        cwd: Path | None = None,
        timeout: float | None = None,
    ) -> subprocess.CompletedProcess[str]:
        del check, capture_output, text, env, cwd, timeout
        if len(cmd) >= 2 and cmd[1:] == ["--version"]:
            version = "codex-cli 0.143.0" if "0.143.0" in cmd[0] else "codex-cli 0.142.5"
            return subprocess.CompletedProcess(cmd, 0, stdout=f"{version}\n", stderr="")
        if len(cmd) >= 2 and Path(cmd[1]).name == "provision_stock_codex.py":
            args = cmd[2:]
            cache_root = Path(args[args.index("--cache-root") + 1])
            allow_remote = "--allow-remote-channel-download" in args
            target_dir = cache_root / "0.143.0"
            target_path = target_dir / "codex"
            if not allow_remote and not target_path.exists():
                return subprocess.CompletedProcess(
                    cmd,
                    1,
                    stdout="",
                    stderr="error: Remote channel downloads require "
                    "--allow-remote-channel-download.\n",
                )
            mutates = False
            action = "stage-ready"
            if allow_remote:
                _write_codex_binary(target_path, version="codex-cli 0.143.0")
                mutates = True
                action = "staged"
                manifest = {
                    "schemaVersion": 1,
                    "kind": "omnigent-stock-codex",
                    "sourceKind": "channel",
                    "version": "codex-cli 0.143.0",
                    "versionSlug": "0.143.0",
                    "sha256": _MOD.sha256_file(target_path),
                    "sourcePath": cask_url,
                    "sourceRealpath": cask_url,
                    "channelArtifact": expected_artifact,
                }
                (target_dir / "manifest.json").write_text(
                    json.dumps(manifest) + "\n",
                    encoding="utf-8",
                )
            sha = _MOD.sha256_file(target_path)
            current_arg = args[args.index("--current-codex") + 1]
            plan = {
                "kind": "omnigent-stock-codex-update-plan",
                "schemaVersion": 1,
                "action": action,
                "mutatesFilesystem": mutates,
                "target": {
                    "state": "ready",
                    "payloadDir": str(target_dir),
                    "codexPath": str(target_path),
                    "error": None,
                },
                "promotion": {
                    "required": True,
                    "ready": True,
                    "env": {_MOD.OMNIGENT_STOCK_CODEX_PATH_ENV: str(target_path)},
                    "launcherManifest": {
                        "updateRequired": True,
                        "ready": True,
                    },
                },
                "rollback": {
                    "codexPath": current_arg,
                    "payloadRetention": "versioned-cache-keeps-previous-payload",
                },
                "stagedPayload": {
                    "codexPath": str(target_path),
                    "payloadDir": str(target_dir),
                    "manifestPath": str(target_dir / "manifest.json"),
                    "version": "codex-cli 0.143.0",
                    "versionSlug": "0.143.0",
                    "sha256": sha,
                    "sourcePath": cask_url,
                    "sourceRealpath": cask_url,
                    "sourceKind": "channel",
                    "channelArtifact": expected_artifact,
                },
            }
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(plan), stderr="")
        raise AssertionError(f"unexpected subprocess command: {cmd!r}")

    monkeypatch.setattr(_MOD.subprocess, "run", fake_run)

    proof = _MOD.run_stock_codex_compat_pkg_update_acquisition_proof(stock_codex)

    assert proof.stock_codex_path == stock_codex.resolve()
    assert proof.stock_codex_version == "codex-cli 0.142.5"
    assert proof.package_identifier == "ai.omnigent.stock-codex-compat"
    assert proof.installed_runtime_root == proof.installed_prefix / "runtime"
    assert proof.provisioner_script_path == (
        proof.installed_runtime_root / "scripts" / "provision_stock_codex.py"
    )
    assert proof.policy_name == "official-openai-github-release"
    assert proof.github_release_tag == "rust-v0.143.0"
    assert proof.github_asset_digest == f"sha256:{cask_sha}"
    assert proof.github_asset_sha256 == cask_sha
    assert proof.cask_version == "0.143.0"
    assert proof.cask_url == cask_url
    assert proof.acquisition_action == "staged"
    assert proof.acquisition_mutates_filesystem is True
    assert proof.acquisition_promotion_required is True
    assert proof.acquisition_promotion_ready is True
    assert proof.acquisition_launcher_update_required is True
    assert proof.acquired_version == "codex-cli 0.143.0"
    assert proof.acquired_source_kind == "channel"
    assert proof.acquired_channel_artifact == expected_artifact
    assert proof.acquired_codex_path == proof.clean_cache_root / "0.143.0" / "codex"
    assert proof.reuse_action == "stage-ready"
    assert proof.reuse_mutates_filesystem is False
    assert proof.reuse_without_remote_download is True
    assert "allow-remote-channel-download" in proof.blocked_without_remote_error
    assert proof.blocked_without_remote_cache_mutated is False
    assert proof.omnigent_resolved_codex_path == proof.acquired_codex_path
    assert proof.host_cache_root == host_home / ".local" / "omnigent" / "codex-stock"
    assert proof.host_cache_referenced_by_plans is False


def test_stock_codex_compat_pkg_update_promotion_proof_promotes_and_rolls_back(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host_home = tmp_path / "host-home"
    stock_codex = _write_codex_binary(
        tmp_path / "stock" / "codex",
        version="codex-cli 0.142.5",
    )
    cask_url = (
        "https://github.com/openai/codex/releases/download/"
        "rust-v0.143.0/codex-aarch64-apple-darwin.tar.gz"
    )
    cask_sha = "b" * 64
    channel = _MOD._GitHubLatestStableCodexChannel(
        tag_name="rust-v0.143.0",
        version_slug="0.143.0",
        selected_version="codex-cli 0.143.0",
        release_name="0.143.0",
        release_html_url="https://github.com/openai/codex/releases/tag/rust-v0.143.0",
        published_at="2026-07-08T01:31:10Z",
        asset_name="codex-aarch64-apple-darwin.tar.gz",
        asset_url=cask_url,
        asset_digest=f"sha256:{cask_sha}",
        asset_sha256=cask_sha,
        archive_executable="codex-aarch64-apple-darwin",
    )
    expected_artifact = {
        "archiveExecutable": "codex-aarch64-apple-darwin",
        "archiveFormat": "tar.gz",
        "sha256": cask_sha,
        "url": cask_url,
        "version": "codex-cli 0.143.0",
        "versionSlug": "0.143.0",
    }
    monkeypatch.setenv("HOME", str(host_home))
    monkeypatch.setattr(_MOD, "_github_latest_stable_codex_channel", lambda: channel)
    monkeypatch.setattr(
        _MOD,
        "_read_homebrew_codex_cask",
        lambda: (_ for _ in ()).throw(AssertionError("Homebrew should not be read")),
    )

    package_path = tmp_path / "artifacts" / "omnigent-stock-codex-compat.pkg"
    package_path.parent.mkdir(parents=True)
    package_path.write_bytes(b"fake-pkg")
    install_prefix = Path("/Library/Application Support/Omnigent/stock-codex-compat")
    package_proof = _MOD.StockCodexCompatPkgStructureProof(
        package_path=package_path,
        package_sha256=_MOD.sha256_file(package_path),
        source_bundle_sha256="c" * 64,
        package_identifier="ai.omnigent.stock-codex-compat",
        package_version="0.3.0.dev0",
        install_location="/",
        install_prefix=install_prefix,
        runtime_root=install_prefix / "runtime",
        payload_file_count=1,
        required_payload_files={"runtime/scripts/provision_stock_codex.py": True},
        script_names=("postinstall",),
        archive_entries=("Bom", "PackageInfo", "Payload", "Scripts"),
        signature_status="no signature",
        signed=False,
        pkg_manifest_path=install_prefix / "pkg-manifest.json",
        bundle_manifest_path=install_prefix / "bundle-manifest.json",
        pkg_contract={
            "runtime": "machine-level-runtime-only",
            "userBootstrap": "deferred-to-installed-runtime-command",
            "stockCodexProvisioning": "deferred-to-installed-runtime-command",
        },
        bundle_source_root="<omitted-from-pkg>",
    )

    monkeypatch.setattr(
        _MOD,
        "_run_stock_codex_compat_pkg_builder_cli_json",
        lambda *_args, **_kwargs: {"kind": "fake-pkg-builder-payload"},
    )
    monkeypatch.setattr(
        _MOD,
        "_validate_stock_codex_compat_pkg_builder_payload",
        lambda *_args, **_kwargs: package_proof,
    )

    def fake_expand(package_path_arg: Path, expand_dir: Path) -> Path:
        assert package_path_arg == package_path
        payload_root = expand_dir / "Payload"
        payload_root.mkdir(parents=True)
        return payload_root

    def fake_stage(
        *,
        payload_root: Path,
        install_root: Path,
        packaged_runtime_root: Path,
        source_repo_root: Path,
    ) -> Path:
        del payload_root, packaged_runtime_root, source_repo_root
        installed_prefix = install_root / install_prefix.relative_to("/")
        runtime_root = installed_prefix / "runtime"
        (runtime_root / "scripts").mkdir(parents=True)
        (runtime_root / "scripts" / "provision_stock_codex.py").write_text(
            "#!/usr/bin/env python3\n",
            encoding="utf-8",
        )
        pkg_manifest = {
            "contract": {
                "runtime": "machine-level-runtime-only",
                "userBootstrap": "deferred-to-installed-runtime-command",
                "stockCodexProvisioning": "deferred-to-installed-runtime-command",
            },
            "stockCodexProvisioner": str(
                package_proof.runtime_root / "scripts" / "provision_stock_codex.py"
            ),
        }
        bundle_manifest = {"sourceRoot": "<omitted-from-pkg>"}
        (installed_prefix / "pkg-manifest.json").write_text(
            json.dumps(pkg_manifest) + "\n",
            encoding="utf-8",
        )
        (installed_prefix / "bundle-manifest.json").write_text(
            json.dumps(bundle_manifest) + "\n",
            encoding="utf-8",
        )
        return runtime_root

    monkeypatch.setattr(_MOD, "_expand_stock_codex_compat_pkg", fake_expand)
    monkeypatch.setattr(_MOD, "_stage_stock_codex_compat_pkg_install_root", fake_stage)

    def fake_run(
        cmd: list[str],
        *,
        check: bool = False,
        capture_output: bool = False,
        text: bool = False,
        env: dict[str, str] | None = None,
        cwd: Path | None = None,
        timeout: float | None = None,
    ) -> subprocess.CompletedProcess[str]:
        del check, capture_output, text, env, cwd, timeout
        if len(cmd) >= 2 and cmd[1:] == ["--version"]:
            version = "codex-cli 0.143.0" if "0.143.0" in cmd[0] else "codex-cli 0.142.5"
            return subprocess.CompletedProcess(cmd, 0, stdout=f"{version}\n", stderr="")
        if len(cmd) >= 2 and Path(cmd[1]).name == "provision_stock_codex.py":
            args = cmd[2:]
            if "--rollback-update" in args:
                rollback_metadata_path = Path(args[args.index("--rollback-update") + 1])
                rollback_metadata = json.loads(
                    rollback_metadata_path.read_text(encoding="utf-8")
                )
                launcher_manifest_path = Path(str(rollback_metadata["launcherManifestPath"]))
                previous = Path(str(rollback_metadata["from"])).resolve()
                promoted = Path(str(rollback_metadata["to"])).resolve()
                launcher_manifest = json.loads(
                    launcher_manifest_path.read_text(encoding="utf-8")
                )
                assert Path(str(launcher_manifest["pinnedCodexPath"])).resolve() == promoted
                launcher_manifest["pinnedCodexPath"] = str(previous)
                launcher_manifest["env"][_MOD.OMNIGENT_STOCK_CODEX_PATH_ENV] = str(previous)
                launcher_manifest_path.write_text(
                    json.dumps(launcher_manifest) + "\n",
                    encoding="utf-8",
                )
                result = {
                    "kind": "omnigent-stock-codex-update-rollback",
                    "schemaVersion": 1,
                    "action": "rolled-back",
                    "mutatesFilesystem": True,
                    "rollbackMetadataPath": str(rollback_metadata_path),
                    "launcherManifest": {
                        "manifestPath": str(launcher_manifest_path),
                        "field": "pinnedCodexPath",
                        "from": str(promoted),
                        "to": str(previous),
                        "env": {_MOD.OMNIGENT_STOCK_CODEX_PATH_ENV: str(previous)},
                    },
                }
                return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(result), stderr="")
            cache_root = Path(args[args.index("--cache-root") + 1])
            launcher_manifest_path = Path(args[args.index("--launcher-manifest") + 1])
            allow_remote = "--allow-remote-channel-download" in args
            promote_update = "--promote-update" in args
            target_dir = cache_root / "0.143.0"
            target_path = target_dir / "codex"
            if not allow_remote and not target_path.exists():
                return subprocess.CompletedProcess(
                    cmd,
                    1,
                    stdout="",
                    stderr="error: Remote channel downloads require "
                    "--allow-remote-channel-download.\n",
                )
            mutates = False
            if allow_remote:
                _write_codex_binary(target_path, version="codex-cli 0.143.0")
                mutates = True
                action = "staged"
            else:
                launcher_manifest = json.loads(launcher_manifest_path.read_text(encoding="utf-8"))
                pinned_path = Path(str(launcher_manifest["pinnedCodexPath"])).resolve()
                action = "up-to-date" if pinned_path == target_path.resolve() else "stage-ready"

            manifest = {
                "schemaVersion": 1,
                "kind": "omnigent-stock-codex",
                "sourceKind": "channel",
                "version": "codex-cli 0.143.0",
                "versionSlug": "0.143.0",
                "sha256": _MOD.sha256_file(target_path),
                "sourcePath": cask_url,
                "sourceRealpath": cask_url,
                "channelArtifact": expected_artifact,
            }
            (target_dir / "manifest.json").write_text(
                json.dumps(manifest) + "\n",
                encoding="utf-8",
            )
            sha = _MOD.sha256_file(target_path)
            launcher_manifest = json.loads(launcher_manifest_path.read_text(encoding="utf-8"))
            pinned_path = Path(str(launcher_manifest["pinnedCodexPath"])).resolve()
            promotion_required = pinned_path != target_path.resolve()
            current_arg = (
                args[args.index("--current-codex") + 1]
                if "--current-codex" in args
                else str(pinned_path)
            )
            plan = {
                "kind": "omnigent-stock-codex-update-plan",
                "schemaVersion": 1,
                "action": action,
                "mutatesFilesystem": mutates,
                "target": {
                    "state": "ready",
                    "payloadDir": str(target_dir),
                    "codexPath": str(target_path),
                    "error": None,
                },
                "promotion": {
                    "required": promotion_required,
                    "ready": True,
                    "env": (
                        {_MOD.OMNIGENT_STOCK_CODEX_PATH_ENV: str(target_path)}
                        if promotion_required
                        else {}
                    ),
                    "launcherManifest": {
                        "manifestPath": str(launcher_manifest_path),
                        "field": "pinnedCodexPath",
                        "from": str(pinned_path),
                        "to": str(target_path),
                        "updateRequired": promotion_required,
                        "ready": True,
                    },
                },
                "rollback": {
                    "codexPath": current_arg,
                    "payloadRetention": "versioned-cache-keeps-previous-payload",
                },
                "stagedPayload": {
                    "codexPath": str(target_path),
                    "payloadDir": str(target_dir),
                    "manifestPath": str(target_dir / "manifest.json"),
                    "version": "codex-cli 0.143.0",
                    "versionSlug": "0.143.0",
                    "sha256": sha,
                    "sourcePath": cask_url,
                    "sourceRealpath": cask_url,
                    "sourceKind": "channel",
                    "channelArtifact": expected_artifact,
                },
            }
            if promote_update:
                rollback_metadata_path = Path(args[args.index("--rollback-metadata") + 1])
                assert action == "stage-ready"
                rollback_metadata = {
                    "schemaVersion": 1,
                    "kind": "omnigent-stock-codex-update-rollback",
                    "launcherManifestPath": str(launcher_manifest_path),
                    "field": "pinnedCodexPath",
                    "envKey": _MOD.OMNIGENT_STOCK_CODEX_PATH_ENV,
                    "from": str(pinned_path),
                    "to": str(target_path.resolve()),
                }
                rollback_metadata_path.write_text(
                    json.dumps(rollback_metadata) + "\n",
                    encoding="utf-8",
                )
                launcher_manifest["pinnedCodexPath"] = str(target_path.resolve())
                launcher_manifest["env"][_MOD.OMNIGENT_STOCK_CODEX_PATH_ENV] = str(
                    target_path.resolve()
                )
                launcher_manifest_path.write_text(
                    json.dumps(launcher_manifest) + "\n",
                    encoding="utf-8",
                )
                result = {
                    "kind": "omnigent-stock-codex-update-promotion",
                    "schemaVersion": 1,
                    "action": "promoted",
                    "mutatesFilesystem": True,
                    "plan": plan,
                    "launcherManifest": {
                        "manifestPath": str(launcher_manifest_path),
                        "field": "pinnedCodexPath",
                        "from": str(pinned_path),
                        "to": str(target_path.resolve()),
                        "env": {
                            _MOD.OMNIGENT_STOCK_CODEX_PATH_ENV: str(target_path.resolve())
                        },
                    },
                    "rollback": {
                        "metadataPath": str(rollback_metadata_path),
                        "codexPath": str(pinned_path),
                        "payloadRetention": "versioned-cache-keeps-previous-payload",
                    },
                }
                return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(result), stderr="")
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(plan), stderr="")
        raise AssertionError(f"unexpected subprocess command: {cmd!r}")

    monkeypatch.setattr(_MOD.subprocess, "run", fake_run)

    proof = _MOD.run_stock_codex_compat_pkg_update_promotion_proof(stock_codex)

    assert proof.stock_codex_path == stock_codex.resolve()
    assert proof.stock_codex_version == "codex-cli 0.142.5"
    assert proof.package_identifier == "ai.omnigent.stock-codex-compat"
    assert proof.installed_runtime_root == proof.installed_prefix / "runtime"
    assert proof.provisioner_script_path == (
        proof.installed_runtime_root / "scripts" / "provision_stock_codex.py"
    )
    assert proof.policy_name == "official-openai-github-release"
    assert proof.github_release_tag == "rust-v0.143.0"
    assert proof.github_release_name == "0.143.0"
    assert proof.github_release_url == (
        "https://github.com/openai/codex/releases/tag/rust-v0.143.0"
    )
    assert proof.github_published_at == "2026-07-08T01:31:10Z"
    assert proof.github_asset_name == "codex-aarch64-apple-darwin.tar.gz"
    assert proof.github_asset_url == cask_url
    assert proof.github_asset_digest == f"sha256:{cask_sha}"
    assert proof.github_asset_sha256 == cask_sha
    assert proof.cask_token == "codex"
    assert proof.cask_tap == "github-releases/latest"
    assert proof.cask_homepage == "https://github.com/openai/codex"
    assert proof.cask_version == "0.143.0"
    assert proof.cask_url == cask_url
    assert proof.cask_sha256 == cask_sha
    assert proof.acquisition_action == "staged"
    assert proof.acquisition_mutates_filesystem is True
    assert proof.acquisition_promotion_required is True
    assert proof.acquisition_promotion_ready is True
    assert proof.acquisition_launcher_update_required is True
    assert proof.acquired_version == "codex-cli 0.143.0"
    assert proof.acquired_source_kind == "channel"
    assert proof.acquired_codex_path == proof.clean_cache_root / "0.143.0" / "codex"
    assert proof.promotion_command_action == "promoted"
    assert proof.promotion_command_mutates_filesystem is True
    assert proof.promoted_codex_path == proof.acquired_codex_path
    assert proof.promoted_env_path == proof.acquired_codex_path
    assert proof.promoted_metadata_to_path == proof.acquired_codex_path
    assert proof.post_promotion_action == "up-to-date"
    assert proof.post_promotion_mutates_filesystem is False
    assert proof.post_promotion_required is False
    assert proof.rollback_command_action == "rolled-back"
    assert proof.rollback_command_mutates_filesystem is True
    assert proof.rollback_codex_path == proof.current_codex_path
    assert proof.rollback_env_path == proof.current_codex_path
    assert proof.rollback_plan_action == "stage-ready"
    assert proof.rollback_plan_mutates_filesystem is False
    assert proof.rollback_plan_promotion_required is True
    assert proof.omnigent_resolved_promoted_codex_path == proof.acquired_codex_path
    assert proof.omnigent_resolved_rollback_codex_path == proof.current_codex_path
    assert proof.host_cache_root == host_home / ".local" / "omnigent" / "codex-stock"
    assert proof.host_cache_referenced_by_plans is False


def test_stock_codex_compat_pkg_update_agent_proof_writes_schedule_and_runs_update(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host_home = tmp_path / "host-home"
    stock_codex = _write_codex_binary(
        tmp_path / "stock" / "codex",
        version="codex-cli 0.142.5",
    )
    uvx_path = _write_uvx_binary(tmp_path / "bin" / "uvx")
    cask_url = (
        "https://github.com/openai/codex/releases/download/"
        "rust-v0.143.0/codex-aarch64-apple-darwin.tar.gz"
    )
    cask_sha = "a" * 64
    channel = _MOD._GitHubLatestStableCodexChannel(
        tag_name="rust-v0.143.0",
        version_slug="0.143.0",
        selected_version="codex-cli 0.143.0",
        release_name="0.143.0",
        release_html_url="https://github.com/openai/codex/releases/tag/rust-v0.143.0",
        published_at="2026-07-08T01:31:10Z",
        asset_name="codex-aarch64-apple-darwin.tar.gz",
        asset_url=cask_url,
        asset_digest=f"sha256:{cask_sha}",
        asset_sha256=cask_sha,
        archive_executable="codex-aarch64-apple-darwin",
    )
    monkeypatch.setenv("HOME", str(host_home))
    monkeypatch.setattr(_MOD, "_github_latest_stable_codex_channel", lambda: channel)
    monkeypatch.setattr(
        _MOD,
        "_read_homebrew_codex_cask",
        lambda: (_ for _ in ()).throw(AssertionError("Homebrew should not be read")),
    )
    monkeypatch.setattr(
        _MOD.shutil,
        "which",
        lambda name: str(uvx_path) if name == "uvx" else None,
    )

    package_path = tmp_path / "artifacts" / "omnigent-stock-codex-compat.pkg"
    package_path.parent.mkdir(parents=True)
    package_path.write_bytes(b"fake-pkg")
    install_prefix = Path("/Library/Application Support/Omnigent/stock-codex-compat")
    package_proof = _MOD.StockCodexCompatPkgStructureProof(
        package_path=package_path,
        package_sha256=_MOD.sha256_file(package_path),
        source_bundle_sha256="b" * 64,
        package_identifier="ai.omnigent.stock-codex-compat",
        package_version="0.3.0.dev0",
        install_location="/",
        install_prefix=install_prefix,
        runtime_root=install_prefix / "runtime",
        payload_file_count=1,
        required_payload_files={"runtime/scripts/update_stock_codex_compat.py": True},
        script_names=("postinstall",),
        archive_entries=("Bom", "PackageInfo", "Payload", "Scripts"),
        signature_status="no signature",
        signed=False,
        pkg_manifest_path=install_prefix / "pkg-manifest.json",
        bundle_manifest_path=install_prefix / "bundle-manifest.json",
        pkg_contract={
            "runtime": "machine-level-runtime-only",
            "userBootstrap": "deferred-to-installed-runtime-command",
            "stockCodexProvisioning": "deferred-to-installed-runtime-command",
            "stockCodexUpdates": "deferred-to-installed-runtime-command",
        },
        bundle_source_root="<omitted-from-pkg>",
    )
    monkeypatch.setattr(
        _MOD,
        "_run_stock_codex_compat_pkg_builder_cli_json",
        lambda *_args, **_kwargs: {"kind": "fake-pkg-builder-payload"},
    )
    monkeypatch.setattr(
        _MOD,
        "_validate_stock_codex_compat_pkg_builder_payload",
        lambda *_args, **_kwargs: package_proof,
    )

    def fake_expand(package_path_arg: Path, expand_dir: Path) -> Path:
        assert package_path_arg == package_path
        payload_root = expand_dir / "Payload"
        payload_root.mkdir(parents=True)
        return payload_root

    def fake_stage(
        *,
        payload_root: Path,
        install_root: Path,
        packaged_runtime_root: Path,
        source_repo_root: Path,
    ) -> Path:
        del payload_root, packaged_runtime_root, source_repo_root
        installed_prefix = install_root / install_prefix.relative_to("/")
        runtime_root = installed_prefix / "runtime"
        (runtime_root / "scripts").mkdir(parents=True)
        (runtime_root / "scripts" / "provision_stock_codex.py").write_text(
            "#!/usr/bin/env python3\n",
            encoding="utf-8",
        )
        (runtime_root / "scripts" / "update_stock_codex_compat.py").write_text(
            "#!/usr/bin/env python3\n",
            encoding="utf-8",
        )
        pkg_manifest = {
            "contract": {
                "runtime": "machine-level-runtime-only",
                "userBootstrap": "deferred-to-installed-runtime-command",
                "stockCodexProvisioning": "deferred-to-installed-runtime-command",
                "stockCodexUpdates": "deferred-to-installed-runtime-command",
            },
            "stockCodexUpdater": str(
                package_proof.runtime_root / "scripts" / "update_stock_codex_compat.py"
            ),
        }
        bundle_manifest = {"sourceRoot": "<omitted-from-pkg>"}
        (installed_prefix / "pkg-manifest.json").write_text(
            json.dumps(pkg_manifest) + "\n",
            encoding="utf-8",
        )
        (installed_prefix / "bundle-manifest.json").write_text(
            json.dumps(bundle_manifest) + "\n",
            encoding="utf-8",
        )
        return runtime_root

    monkeypatch.setattr(_MOD, "_expand_stock_codex_compat_pkg", fake_expand)
    monkeypatch.setattr(_MOD, "_stage_stock_codex_compat_pkg_install_root", fake_stage)

    def fake_run(
        cmd: list[str],
        *,
        check: bool = False,
        capture_output: bool = False,
        text: bool = False,
        env: dict[str, str] | None = None,
        cwd: Path | None = None,
        timeout: float | None = None,
    ) -> subprocess.CompletedProcess[str]:
        del check, capture_output, text, env, cwd, timeout
        if len(cmd) >= 2 and cmd[1:] == ["--version"]:
            version = "codex-cli 0.143.0" if "0.143.0" in cmd[0] else "codex-cli 0.142.5"
            return subprocess.CompletedProcess(cmd, 0, stdout=f"{version}\n", stderr="")
        if len(cmd) >= 2 and Path(cmd[1]).name == "update_stock_codex_compat.py":
            args = cmd[2:]
            runtime_root = Path(args[args.index("--runtime-root") + 1])
            cache_root = Path(args[args.index("--cache-root") + 1])
            channel_manifest = Path(args[args.index("--channel-manifest") + 1])
            launcher_manifest_path = Path(args[args.index("--launcher-manifest") + 1])
            rollback_metadata_path = Path(args[args.index("--rollback-metadata") + 1])
            target_path = cache_root / "0.143.0" / "codex"
            program_arguments = [
                str(uvx_path),
                "--from",
                str(runtime_root),
                "python",
                str(runtime_root / "scripts" / "update_stock_codex_compat.py"),
                "--runtime-root",
                str(runtime_root),
                "--uvx-path",
                str(uvx_path),
                "--cache-root",
                str(cache_root),
                "--channel-manifest",
                str(channel_manifest),
                "--channel-policy",
                "official-openai-github-release",
                "--launcher-manifest",
                str(launcher_manifest_path),
                "--rollback-metadata",
                str(rollback_metadata_path),
                "--json",
                "--expected-sha256",
                cask_sha,
                "--allow-remote-channel-download",
            ]
            launch_agent = {
                "kind": "omnigent-stock-codex-compat-update-launch-agent",
                "label": "ai.omnigent.stock-codex-compat.update",
                "path": str(
                    Path(args[args.index("--launch-agent-path") + 1])
                    if "--launch-agent-path" in args
                    else tmp_path / "agent.plist"
                ),
                "written": "--write-launch-agent" in args,
                "mutatesFilesystem": "--write-launch-agent" in args,
                "runAtLoad": True,
                "startInterval": 86400,
                "programArguments": program_arguments,
                "standardOutPath": str(tmp_path / "update.out.log"),
                "standardErrorPath": str(tmp_path / "update.err.log"),
            }
            if launch_agent["written"]:
                launch_agent_path = Path(str(launch_agent["path"]))
                launch_agent_path.parent.mkdir(parents=True)
                with launch_agent_path.open("wb") as handle:
                    plistlib.dump(
                        {
                            "Label": launch_agent["label"],
                            "ProgramArguments": program_arguments,
                            "RunAtLoad": True,
                            "StartInterval": 86400,
                            "StandardOutPath": launch_agent["standardOutPath"],
                            "StandardErrorPath": launch_agent["standardErrorPath"],
                        },
                        handle,
                        sort_keys=True,
                    )
            if "--run-now" not in args and "--write-launch-agent" not in args:
                result = {
                    "kind": "omnigent-stock-codex-compat-update",
                    "schemaVersion": 1,
                    "action": "up-to-date",
                    "mutatesFilesystem": False,
                    "launchAgent": launch_agent,
                    "plan": {
                        "kind": "omnigent-stock-codex-update-plan",
                        "schemaVersion": 1,
                        "action": "up-to-date",
                        "mutatesFilesystem": False,
                        "promotion": {"required": False, "ready": True},
                    },
                    "promotion": None,
                }
                return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(result), stderr="")

            _write_codex_binary(target_path, version="codex-cli 0.143.0")
            launcher_manifest = json.loads(
                launcher_manifest_path.read_text(encoding="utf-8")
            )
            previous = Path(str(launcher_manifest["pinnedCodexPath"])).resolve()
            launcher_manifest["pinnedCodexPath"] = str(target_path.resolve())
            launcher_manifest["env"][_MOD.OMNIGENT_STOCK_CODEX_PATH_ENV] = str(
                target_path.resolve()
            )
            launcher_manifest_path.write_text(
                json.dumps(launcher_manifest) + "\n",
                encoding="utf-8",
            )
            rollback_metadata = {
                "schemaVersion": 1,
                "kind": "omnigent-stock-codex-update-rollback",
                "launcherManifestPath": str(launcher_manifest_path),
                "from": str(previous),
                "to": str(target_path.resolve()),
            }
            rollback_metadata_path.write_text(
                json.dumps(rollback_metadata) + "\n",
                encoding="utf-8",
            )
            result = {
                "kind": "omnigent-stock-codex-compat-update",
                "schemaVersion": 1,
                "action": "promoted",
                "mutatesFilesystem": True,
                "launchAgent": launch_agent,
                "plan": {
                    "kind": "omnigent-stock-codex-update-plan",
                    "schemaVersion": 1,
                    "action": "staged",
                    "mutatesFilesystem": True,
                    "promotion": {"required": True, "ready": True},
                },
                "promotion": {
                    "kind": "omnigent-stock-codex-update-promotion",
                    "schemaVersion": 1,
                    "action": "promoted",
                    "mutatesFilesystem": True,
                    "launcherManifest": {
                        "manifestPath": str(launcher_manifest_path),
                        "field": "pinnedCodexPath",
                        "from": str(previous),
                        "to": str(target_path.resolve()),
                        "env": {
                            _MOD.OMNIGENT_STOCK_CODEX_PATH_ENV: str(target_path.resolve())
                        },
                    },
                    "rollback": {
                        "metadataPath": str(rollback_metadata_path),
                        "codexPath": str(previous),
                        "payloadRetention": "versioned-cache-keeps-previous-payload",
                    },
                },
            }
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(result), stderr="")
        raise AssertionError(f"unexpected subprocess command: {cmd!r}")

    monkeypatch.setattr(_MOD.subprocess, "run", fake_run)

    proof = _MOD.run_stock_codex_compat_pkg_update_agent_proof(stock_codex)

    assert proof.stock_codex_path == stock_codex.resolve()
    assert proof.stock_codex_version == "codex-cli 0.142.5"
    assert proof.package_identifier == "ai.omnigent.stock-codex-compat"
    assert proof.installed_runtime_root == proof.installed_prefix / "runtime"
    assert proof.updater_script_path == (
        proof.installed_runtime_root / "scripts" / "update_stock_codex_compat.py"
    )
    assert proof.policy_name == "official-openai-github-release"
    assert proof.github_release_tag == "rust-v0.143.0"
    assert proof.github_release_name == "0.143.0"
    assert proof.github_release_url == (
        "https://github.com/openai/codex/releases/tag/rust-v0.143.0"
    )
    assert proof.github_published_at == "2026-07-08T01:31:10Z"
    assert proof.github_asset_name == "codex-aarch64-apple-darwin.tar.gz"
    assert proof.github_asset_url == cask_url
    assert proof.github_asset_digest == f"sha256:{cask_sha}"
    assert proof.github_asset_sha256 == cask_sha
    assert proof.cask_token == "codex"
    assert proof.cask_tap == "github-releases/latest"
    assert proof.cask_homepage == "https://github.com/openai/codex"
    assert proof.cask_version == "0.143.0"
    assert proof.cask_url == cask_url
    assert proof.cask_sha256 == cask_sha
    assert proof.update_action == "promoted"
    assert proof.update_mutates_filesystem is True
    assert proof.plan_action == "staged"
    assert proof.plan_mutates_filesystem is True
    assert proof.promotion_action == "promoted"
    assert proof.promotion_mutates_filesystem is True
    assert proof.promoted_codex_path == proof.clean_cache_root / "0.143.0" / "codex"
    assert proof.promoted_env_path == proof.promoted_codex_path
    assert proof.post_update_action == "up-to-date"
    assert proof.post_update_mutates_filesystem is False
    assert proof.post_update_required is False
    assert proof.launch_agent_label == "ai.omnigent.stock-codex-compat.update"
    assert proof.launch_agent_start_interval == 86400
    assert proof.launch_agent_run_at_load is True
    assert proof.launch_agent_program_arguments[:5] == (
        str(uvx_path),
        "--from",
        str(proof.installed_runtime_root),
        "python",
        str(proof.updater_script_path),
    )
    assert "--current-codex" not in proof.launch_agent_program_arguments
    assert "--write-launch-agent" not in proof.launch_agent_program_arguments
    assert "--run-now" not in proof.launch_agent_program_arguments
    assert "--uvx-path" in proof.launch_agent_program_arguments
    assert "--allow-remote-channel-download" in proof.launch_agent_program_arguments
    assert proof.host_cache_root == host_home / ".local" / "omnigent" / "codex-stock"
    assert proof.host_cache_referenced_by_plans is False


def test_stock_codex_compat_pkg_clean_auth_proof_uses_installed_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if shutil.which("pkgbuild") is None or shutil.which("pkgutil") is None:
        pytest.skip("macOS pkgbuild/pkgutil are required for pkg clean-auth tests")

    stock_codex = _write_codex_binary(tmp_path / "stock" / "codex")
    real_home = tmp_path / "real-home"
    real_codex_home = tmp_path / "real-codex-home"
    real_auth_path = _write_auth(
        real_codex_home,
        {"auth_mode": "api", "OPENAI_API_KEY": "sk-real-proof-fixture"},
    )
    monkeypatch.setenv("HOME", str(real_home))
    monkeypatch.setenv("CODEX_HOME", str(real_codex_home))

    proof = _MOD.run_stock_codex_compat_pkg_clean_auth_proof(stock_codex)

    assert proof.stock_codex_path == stock_codex.resolve()
    assert proof.stock_codex_version == "codex-cli 0.142.2"
    assert proof.provisioned_version == "codex-cli 0.142.2"
    assert proof.package_identifier == "ai.omnigent.stock-codex-compat"
    assert len(proof.package_sha256) == 64
    assert proof.installed_runtime_root == proof.installed_prefix / "runtime"
    assert proof.provisioner_script_path == (
        proof.installed_runtime_root / "scripts" / "provision_stock_codex.py"
    )
    assert proof.installer_script_path == (
        proof.installed_runtime_root / "scripts" / "install_stock_codex_compat_launcher.py"
    )
    assert proof.clean_bin_dir == proof.clean_home / ".local" / "bin"
    assert proof.clean_cache_root == (
        proof.clean_home / ".local" / "omnigent" / "codex-stock"
    )
    assert proof.provisioned_codex_path == proof.clean_cache_root / "0.142.2" / "codex"
    assert proof.launcher_path == proof.clean_bin_dir / "omnigent-stock-codex-compat"
    assert proof.manifest_path == (
        proof.clean_home / ".local" / "omnigent" / "launchers" / "stock-codex-compat.json"
    )
    assert proof.selected_command_path == proof.launcher_path
    assert proof.launcher_version_output == "codex-cli 0.142.2"
    assert "OMNIGENT_STOCK_CODEX_COMPAT_LAUNCHER_OK" in proof.launcher_probe_output
    assert str(proof.installed_runtime_root) in proof.launcher_probe_output
    assert str(proof.provisioned_codex_path) in proof.launcher_probe_output
    assert proof.launcher_manifest_repo_root == proof.installed_runtime_root
    assert proof.adapter_package_action == "adapter-package-installed"
    assert proof.adapter_bin == proof.adapter_package_dir / "bin"
    assert proof.adapter_manifest == proof.adapter_package_dir / "adapter-manifest.json"
    assert proof.adapter_bridge_dir == (
        proof.clean_home / ".local" / "omnigent" / "stock-codex-compat" / "adapter-bridge"
    )
    assert proof.adapter_tool_names == ("fetch_apple_docs",)
    assert proof.install_action == "installed"
    assert proof.doctor_install_allowed is True
    assert proof.doctor_existing_target_state == "managed"
    assert proof.doctor_target_selected_on_path is True
    assert proof.doctor_mutates_filesystem is False
    assert proof.real_auth_path == real_auth_path
    assert proof.real_auth_source == "explicit-CODEX_HOME"
    assert proof.real_auth_available is True
    assert proof.real_auth_classifier_path == real_auth_path.resolve()
    assert proof.real_auth_unavailable_reason is None
    assert proof.clean_auth_classifier_path == proof.clean_codex_home / "auth.json"
    assert proof.clean_unavailable_reason == "needs-auth"
    assert proof.synthetic_auth_classifier_path == (
        proof.synthetic_codex_home / "auth.json"
    )
    assert proof.synthetic_available_reason is None
    assert proof.credential_material_leaked is False
    assert str(proof.clean_codex_home) in proof.onboarding_command
    assert str(proof.launcher_path) in proof.onboarding_command
    assert str(proof.provisioned_codex_path) not in proof.onboarding_command


def test_stock_codex_compat_pkg_signed_notarized_blocks_when_prereqs_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_prerequisites(**kwargs: object) -> Any:
        assert kwargs["sign_identity"] is None
        return _MOD.StockCodexCompatPkgSigningPrerequisites(
            status="blocked",
            missing_prerequisites=("set OMNIGENT_PKG_SIGN_IDENTITY",),
            tool_paths={
                "pkgbuild": None,
                "pkgutil": "/usr/sbin/pkgutil",
                "xcrun": "/usr/bin/xcrun",
                "spctl": "/usr/sbin/spctl",
                "notarytool": "/usr/bin/notarytool",
                "stapler": "/usr/bin/stapler",
            },
            sign_identity=None,
            sign_identity_source="missing",
            signing_keychain=None,
            developer_id_installer_identities=(),
            developer_id_application_identities=(
                "Developer ID Application: Example (ABCDE12345)",
            ),
            notarytool_profile=None,
        )

    monkeypatch.setattr(
        _MOD,
        "_stock_codex_compat_pkg_signing_prerequisites",
        fake_prerequisites,
    )

    proof = _MOD.run_stock_codex_compat_pkg_signed_notarized_proof(
        sign_identity=None,
        signing_keychain=None,
        notarytool_profile=None,
    )

    assert proof.status == "blocked"
    assert proof.missing_prerequisites == ("set OMNIGENT_PKG_SIGN_IDENTITY",)
    assert proof.developer_id_application_identities == (
        "Developer ID Application: Example (ABCDE12345)",
    )
    assert proof.package_path is None
    assert proof.signed is None


def test_stock_codex_compat_pkg_signing_prereqs_explain_application_identity_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tool_paths = {
        "pkgbuild": "/usr/bin/pkgbuild",
        "pkgutil": "/usr/sbin/pkgutil",
        "xcrun": "/usr/bin/xcrun",
        "spctl": "/usr/sbin/spctl",
    }
    monkeypatch.setattr(_MOD.shutil, "which", lambda name: tool_paths.get(name))
    monkeypatch.setattr(
        _MOD,
        "_xcrun_find_tool",
        lambda _xcrun_path, tool_name: f"/usr/bin/{tool_name}",
    )
    monkeypatch.setattr(
        _MOD,
        "_developer_id_installer_identities",
        lambda *, signing_keychain: (),
    )
    monkeypatch.setattr(
        _MOD,
        "_developer_id_application_identities",
        lambda *, signing_keychain: (
            "Developer ID Application: Example (ABCDE12345)",
        ),
    )

    prerequisites = _MOD._stock_codex_compat_pkg_signing_prerequisites(
        sign_identity=None,
        signing_keychain=None,
        notarytool_profile=None,
    )

    assert prerequisites.status == "blocked"
    assert prerequisites.developer_id_installer_identities == ()
    assert prerequisites.developer_id_application_identities == (
        "Developer ID Application: Example (ABCDE12345)",
    )
    assert (
        "Developer ID Application identity is present, but a Developer ID "
        "Installer identity is required for .pkg signing"
    ) in prerequisites.missing_prerequisites


def test_stock_codex_compat_pkg_signed_notarized_runs_distribution_checks(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured_build_args: list[str] = []
    distribution_commands: list[list[str]] = []
    output_path = tmp_path / "dist" / "signed-notarized.pkg"
    initial_package_sha = ""

    def fake_prerequisites(**kwargs: object) -> Any:
        assert kwargs["sign_identity"] == "Developer ID Installer: Example (ABCDE12345)"
        assert kwargs["notarytool_profile"] == "omnigent-notary"
        return _MOD.StockCodexCompatPkgSigningPrerequisites(
            status="ready",
            missing_prerequisites=(),
            tool_paths={
                "pkgbuild": "/usr/bin/pkgbuild",
                "pkgutil": "/usr/sbin/pkgutil",
                "xcrun": "/usr/bin/xcrun",
                "spctl": "/usr/sbin/spctl",
                "notarytool": "/usr/bin/notarytool",
                "stapler": "/usr/bin/stapler",
            },
            sign_identity="Developer ID Installer: Example (ABCDE12345)",
            sign_identity_source="explicit",
            signing_keychain=None,
            developer_id_installer_identities=(
                "Developer ID Installer: Example (ABCDE12345)",
            ),
            developer_id_application_identities=(),
            notarytool_profile="omnigent-notary",
        )

    def fake_builder(args: list[str], *, repo_root: Path) -> dict[str, Any]:
        nonlocal initial_package_sha
        del repo_root
        captured_build_args.extend(args)
        output_path = Path(args[args.index("--output") + 1])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"signed pkg fixture")
        package_sha = _MOD.sha256_file(output_path)
        initial_package_sha = package_sha
        return {
            "kind": "omnigent-stock-codex-compat-pkg",
            "packagePath": str(output_path),
            "packageSha256": package_sha,
            "sourceBundleSha256": "a" * 64,
            "packageIdentifier": "ai.omnigent.stock-codex-compat",
            "packageVersion": "1.2.3",
            "installLocation": "/",
            "installPrefix": "/Library/Application Support/Omnigent/stock-codex-compat",
            "runtimeRoot": (
                "/Library/Application Support/Omnigent/stock-codex-compat/runtime"
            ),
            "inspection": {
                "signed": True,
                "signatureStatus": "signed by a certificate trusted by macOS",
                "allRequiredPayloadFilesPresent": True,
                "requiredPayloadFiles": {
                    (
                        "Library/Application Support/Omnigent/"
                        "stock-codex-compat/pkg-manifest.json"
                    ): True,
                },
                "scriptNames": ["postinstall"],
                "archiveEntries": ["Bom", "PackageInfo", "Payload", "Scripts"],
                "pkgManifestPath": str(output_path.parent / "pkg-manifest.json"),
                "bundleManifestPath": str(output_path.parent / "bundle-manifest.json"),
                "payloadFileCount": 42,
                "pkgManifest": {
                    "contract": {
                        "runtime": "machine-level-runtime-only",
                        "userBootstrap": "deferred-to-installed-runtime-command",
                    },
                },
                "bundleManifest": {"sourceRoot": "<omitted-from-pkg>"},
            },
        }

    def fake_distribution_command(
        command: list[str],
        *,
        timeout: float,
    ) -> subprocess.CompletedProcess[str]:
        assert timeout > 0
        distribution_commands.append(command)
        if command[1:3] == ["notarytool", "submit"]:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout='{"id":"notary-submission-1","status":"In Progress"}',
                stderr="",
            )
        if command[1:3] == ["notarytool", "wait"]:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout='{"id":"notary-submission-1","status":"Accepted"}',
                stderr="",
            )
        if command[1:3] == ["stapler", "staple"]:
            package = Path(command[-1])
            package.write_bytes(package.read_bytes() + b"\nstapled")
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    monkeypatch.setattr(
        _MOD,
        "_stock_codex_compat_pkg_signing_prerequisites",
        fake_prerequisites,
    )
    monkeypatch.setattr(_MOD, "_run_stock_codex_compat_pkg_builder_cli_json", fake_builder)
    monkeypatch.setattr(_MOD, "_run_pkg_distribution_command", fake_distribution_command)

    proof = _MOD.run_stock_codex_compat_pkg_signed_notarized_proof(
        sign_identity="Developer ID Installer: Example (ABCDE12345)",
        signing_keychain=None,
        notarytool_profile="omnigent-notary",
        package_output_path=output_path,
    )

    assert proof.status == "replacement-ready"
    assert proof.package_path == output_path.resolve()
    assert output_path.is_file()
    assert proof.package_sha256 == _MOD.sha256_file(output_path)
    assert proof.package_sha256 != initial_package_sha
    assert proof.signed is True
    assert proof.signature_status == "signed by a certificate trusted by macOS"
    assert proof.notary_submission_id == "notary-submission-1"
    assert proof.notary_status == "Accepted"
    assert captured_build_args[captured_build_args.index("--sign-identity") + 1] == (
        "Developer ID Installer: Example (ABCDE12345)"
    )
    assert captured_build_args[captured_build_args.index("--output") + 1] == str(
        output_path.resolve()
    )
    assert distribution_commands[0][1:3] == ["notarytool", "submit"]
    assert "--wait" not in distribution_commands[0]
    assert distribution_commands[0][-2:] == ["--output-format", "json"]
    assert distribution_commands[1][1:3] == ["notarytool", "wait"]
    assert "notary-submission-1" in distribution_commands[1]
    assert distribution_commands[2][1:3] == ["stapler", "staple"]
    assert distribution_commands[3][1:3] == ["stapler", "validate"]
    assert distribution_commands[4][:5] == ["/usr/sbin/spctl", "-a", "-vv", "-t", "install"]


def test_stock_codex_compat_pkg_installer_lifecycle_blocks_without_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    stock_codex = _write_codex_binary(tmp_path / "stock" / "codex")

    def fake_prerequisites(**kwargs: object) -> Any:
        assert kwargs["sign_identity"] == "Developer ID Installer: Example (ABCDE12345)"
        return _MOD.StockCodexCompatPkgSigningPrerequisites(
            status="ready",
            missing_prerequisites=(),
            tool_paths={
                "pkgbuild": "/usr/bin/pkgbuild",
                "pkgutil": "/usr/sbin/pkgutil",
                "xcrun": "/usr/bin/xcrun",
                "spctl": "/usr/sbin/spctl",
                "notarytool": "/usr/bin/notarytool",
                "stapler": "/usr/bin/stapler",
            },
            sign_identity="Developer ID Installer: Example (ABCDE12345)",
            sign_identity_source="explicit",
            signing_keychain=None,
            developer_id_installer_identities=(
                "Developer ID Installer: Example (ABCDE12345)",
            ),
            developer_id_application_identities=(),
            notarytool_profile="omnigent-notary",
        )

    def fake_which(name: str) -> str | None:
        return {
            "installer": "/usr/sbin/installer",
            "hdiutil": "/usr/bin/hdiutil",
            "uvx": str(_write_uvx_binary(tmp_path / "tools" / "uvx")),
        }.get(name)

    def fail_build(**kwargs: object) -> Any:
        raise AssertionError(f"build should not run without root: {kwargs!r}")

    monkeypatch.setattr(
        _MOD,
        "_stock_codex_compat_pkg_signing_prerequisites",
        fake_prerequisites,
    )
    monkeypatch.setattr(_MOD.shutil, "which", fake_which)
    monkeypatch.setattr(_MOD, "_effective_user_is_root", lambda: False)
    monkeypatch.setattr(_MOD, "_build_signed_notarized_stock_codex_compat_pkg", fail_build)

    proof = _MOD.run_stock_codex_compat_pkg_installer_lifecycle_proof(
        stock_codex,
        sign_identity="Developer ID Installer: Example (ABCDE12345)",
        signing_keychain=None,
        notarytool_profile="omnigent-notary",
    )

    assert proof.status == "blocked"
    assert proof.package_path is None
    assert (
        "installer lifecycle requires root privileges for /usr/sbin/installer; "
        "run from an admin-authenticated root shell"
    ) in proof.missing_prerequisites


def test_stock_codex_compat_pkg_installer_lifecycle_prebuilt_blocks_after_validation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    stock_codex = _write_codex_binary(tmp_path / "stock" / "codex")
    package_path = tmp_path / "artifacts" / "prebuilt.pkg"
    package_path.parent.mkdir()
    package_path.write_bytes(b"prebuilt signed pkg")
    structure = _MOD.StockCodexCompatPkgStructureProof(
        package_path=package_path.resolve(),
        package_sha256=_MOD.sha256_file(package_path),
        source_bundle_sha256="a" * 64,
        package_identifier="ai.omnigent.stock-codex-compat",
        package_version="1.2.3",
        install_location="/",
        install_prefix=Path("/Library/Application Support/Omnigent/stock-codex-compat"),
        runtime_root=Path(
            "/Library/Application Support/Omnigent/stock-codex-compat/runtime"
        ),
        payload_file_count=6,
        required_payload_files={
            "Library/Application Support/Omnigent/stock-codex-compat/pkg-manifest.json": True,
        },
        script_names=("postinstall",),
        archive_entries=("Bom", "PackageInfo", "Payload", "Scripts"),
        signature_status="signed by a developer certificate issued by Apple",
        signed=True,
        pkg_manifest_path=tmp_path / "expanded" / "pkg-manifest.json",
        bundle_manifest_path=tmp_path / "expanded" / "bundle-manifest.json",
        pkg_contract={"runtime": "machine-level-runtime-only"},
        bundle_source_root="<omitted-from-pkg>",
    )
    distribution_commands: list[list[str]] = []

    def fake_which(name: str, path: str | None = None) -> str | None:
        if path is not None:
            for entry in path.split(os.pathsep):
                candidate = Path(entry) / name
                if candidate.is_file() and os.access(candidate, os.X_OK):
                    return str(candidate)
            return None
        return {
            "pkgutil": "/usr/sbin/pkgutil",
            "xcrun": "/usr/bin/xcrun",
            "spctl": "/usr/sbin/spctl",
            "installer": "/usr/sbin/installer",
            "hdiutil": "/usr/bin/hdiutil",
            "uvx": str(_write_uvx_binary(tmp_path / "tools" / "uvx")),
        }.get(name)

    def fake_inspect(
        package_path_arg: Path,
        *,
        expand_dir: Path,
        source_repo_root: Path,
        expect_signed: bool,
    ) -> Any:
        assert package_path_arg == package_path.resolve()
        assert expand_dir.name == "prebuilt-pkg-expanded"
        assert source_repo_root == _REPO_ROOT
        assert expect_signed is True
        return structure

    def fake_distribution_command(
        command: list[str],
        *,
        timeout: float,
    ) -> subprocess.CompletedProcess[str]:
        assert timeout > 0
        distribution_commands.append(command)
        if command[1:3] == ["stapler", "validate"]:
            return subprocess.CompletedProcess(command, 0, stdout="staple ok", stderr="")
        if command[:5] == ["/usr/sbin/spctl", "-a", "-vv", "-t", "install"]:
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="accepted")
        raise AssertionError(f"unexpected distribution command: {command!r}")

    def fail_prerequisites(**kwargs: object) -> Any:
        raise AssertionError(f"signing prerequisites should not run: {kwargs!r}")

    def fail_build(**kwargs: object) -> Any:
        raise AssertionError(f"build should not run for prebuilt package: {kwargs!r}")

    monkeypatch.setattr(
        _MOD,
        "_stock_codex_compat_pkg_signing_prerequisites",
        fail_prerequisites,
    )
    monkeypatch.setattr(_MOD.shutil, "which", fake_which)
    monkeypatch.setattr(_MOD, "_xcrun_find_tool", lambda _xcrun, tool: f"/usr/bin/{tool}")
    monkeypatch.setattr(_MOD, "_effective_user_is_root", lambda: False)
    monkeypatch.setattr(_MOD, "_inspect_stock_codex_compat_pkg_file", fake_inspect)
    monkeypatch.setattr(_MOD, "_run_pkg_distribution_command", fake_distribution_command)
    monkeypatch.setattr(_MOD, "_build_signed_notarized_stock_codex_compat_pkg", fail_build)

    proof = _MOD.run_stock_codex_compat_pkg_installer_lifecycle_proof(
        stock_codex,
        sign_identity=None,
        signing_keychain=None,
        notarytool_profile=None,
        package_path=package_path,
    )

    assert proof.status == "blocked"
    assert proof.sign_identity_source == "prebuilt-package"
    assert proof.package_path == package_path.resolve()
    assert proof.package_sha256 == structure.package_sha256
    assert proof.package_identifier == "ai.omnigent.stock-codex-compat"
    assert proof.notary_submission_id == "prebuilt-package"
    assert proof.notary_status == "prebuilt-staple-validated"
    assert proof.gatekeeper_output_preview == "accepted"
    assert (
        "installer lifecycle requires root privileges for /usr/sbin/installer; "
        "run from an admin-authenticated root shell"
    ) in proof.missing_prerequisites
    assert distribution_commands[0][1:3] == ["stapler", "validate"]
    assert distribution_commands[1][:5] == ["/usr/sbin/spctl", "-a", "-vv", "-t", "install"]


def test_stock_codex_compat_pkg_installer_lifecycle_uses_mounted_target(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    stock_codex = _write_codex_binary(tmp_path / "stock" / "codex")
    package_path = tmp_path / "artifacts" / "omnigent-stock-codex-compat.pkg"
    package_path.parent.mkdir()
    package_path.write_bytes(b"signed-notarized-pkg")
    install_prefix = Path("/Library/Application Support/Omnigent/stock-codex-compat")
    runtime_root = install_prefix / "runtime"
    required_payload_files = {
        "Library/Application Support/Omnigent/stock-codex-compat/pkg-manifest.json": True,
        "Library/Application Support/Omnigent/stock-codex-compat/bundle-manifest.json": True,
        (
            "Library/Application Support/Omnigent/stock-codex-compat/runtime/"
            "pyproject.toml"
        ): True,
        (
            "Library/Application Support/Omnigent/stock-codex-compat/runtime/"
            "scripts/install_stock_codex_compat_launcher.py"
        ): True,
        (
            "Library/Application Support/Omnigent/stock-codex-compat/runtime/"
            "scripts/provision_stock_codex.py"
        ): True,
        (
            "Library/Application Support/Omnigent/stock-codex-compat/runtime/"
            "omnigent/stock_codex_compat_wrapper.py"
        ): True,
    }
    structure = _MOD.StockCodexCompatPkgStructureProof(
        package_path=package_path,
        package_sha256=_MOD.sha256_file(package_path),
        source_bundle_sha256="a" * 64,
        package_identifier="ai.omnigent.stock-codex-compat",
        package_version="1.2.3",
        install_location="/",
        install_prefix=install_prefix,
        runtime_root=runtime_root,
        payload_file_count=len(required_payload_files),
        required_payload_files=required_payload_files,
        script_names=("postinstall",),
        archive_entries=("Bom", "PackageInfo", "Payload", "Scripts"),
        signature_status="signed by a certificate trusted by macOS",
        signed=True,
        pkg_manifest_path=tmp_path / "expanded" / "pkg-manifest.json",
        bundle_manifest_path=tmp_path / "expanded" / "bundle-manifest.json",
        pkg_contract={"runtime": "machine-level-runtime-only"},
        bundle_source_root="<omitted-from-pkg>",
    )
    receipt_present = True
    mounted_target = tmp_path / "mounted-target"
    lifecycle_commands: list[list[str]] = []
    installer_cli_calls: list[list[str]] = []

    def fake_prerequisites(**kwargs: object) -> Any:
        assert kwargs["sign_identity"] == "Developer ID Installer: Example (ABCDE12345)"
        return _MOD.StockCodexCompatPkgSigningPrerequisites(
            status="ready",
            missing_prerequisites=(),
            tool_paths={
                "pkgbuild": "/usr/bin/pkgbuild",
                "pkgutil": "/usr/sbin/pkgutil",
                "xcrun": "/usr/bin/xcrun",
                "spctl": "/usr/sbin/spctl",
                "notarytool": "/usr/bin/notarytool",
                "stapler": "/usr/bin/stapler",
            },
            sign_identity="Developer ID Installer: Example (ABCDE12345)",
            sign_identity_source="explicit",
            signing_keychain=None,
            developer_id_installer_identities=(
                "Developer ID Installer: Example (ABCDE12345)",
            ),
            developer_id_application_identities=(),
            notarytool_profile="omnigent-notary",
        )

    def fake_which(name: str) -> str | None:
        return {
            "installer": "/usr/sbin/installer",
            "hdiutil": "/usr/bin/hdiutil",
            "uvx": str(_write_uvx_binary(tmp_path / "tools" / "uvx")),
        }.get(name)

    def fake_signed_pkg(**kwargs: object) -> Any:
        assert kwargs["root"]
        return _MOD._SignedNotarizedStockCodexCompatPkg(
            structure=structure,
            notary_submission_id="notary-1",
            notary_status="Accepted",
            notary_output_preview='{"status":"Accepted"}',
            staple_output_preview="stapled",
            stapler_validate_output_preview="validated",
            gatekeeper_output_preview="accepted",
        )

    def fake_create_volume(**kwargs: object) -> tuple[Path, Path, str]:
        assert kwargs["hdiutil_path"] == "/usr/bin/hdiutil"
        mounted_target.mkdir()
        return tmp_path / "target.dmg", mounted_target, "/dev/disk999"

    def write_installed_payload() -> None:
        installed_prefix = mounted_target / install_prefix.relative_to("/")
        installed_runtime = mounted_target / runtime_root.relative_to("/")
        (installed_runtime / "scripts").mkdir(parents=True)
        (installed_runtime / "omnigent").mkdir()
        (installed_runtime / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
        (installed_runtime / "scripts" / "install_stock_codex_compat_launcher.py").write_text(
            "#!/usr/bin/env python3\n",
            encoding="utf-8",
        )
        (installed_runtime / "scripts" / "provision_stock_codex.py").write_text(
            "#!/usr/bin/env python3\n",
            encoding="utf-8",
        )
        (installed_runtime / "omnigent" / "stock_codex_compat_wrapper.py").write_text(
            "",
            encoding="utf-8",
        )
        (installed_prefix / "pkg-manifest.json").write_text(
            json.dumps(
                {
                    "contract": {"runtime": "machine-level-runtime-only"},
                    "packageIdentifier": "ai.omnigent.stock-codex-compat",
                    "packageVersion": "1.2.3",
                }
            )
            + "\n",
            encoding="utf-8",
        )
        (installed_prefix / "bundle-manifest.json").write_text(
            json.dumps({"sourceRoot": "<omitted-from-pkg>"}) + "\n",
            encoding="utf-8",
        )

    def fake_lifecycle_command(
        command: list[str],
        *,
        timeout: float,
        failure_label: str,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        nonlocal receipt_present
        assert timeout > 0
        assert failure_label
        lifecycle_commands.append(command)
        if command[0] == "/usr/sbin/installer":
            assert command[command.index("-target") + 1] == str(mounted_target)
            write_installed_payload()
            return subprocess.CompletedProcess(command, 0, stdout="installer ok", stderr="")
        if command[:3] == ["/usr/sbin/pkgutil", "--volume", str(mounted_target)]:
            if command[3] == "--pkg-info":
                if receipt_present:
                    return subprocess.CompletedProcess(
                        command,
                        0,
                        stdout=(
                            "package-id: ai.omnigent.stock-codex-compat\n"
                            "version: 1.2.3\n"
                        ),
                        stderr="",
                    )
                return subprocess.CompletedProcess(command, 1, stdout="", stderr="not found")
            if command[3] == "--files":
                return subprocess.CompletedProcess(
                    command,
                    0,
                    stdout="\n".join(required_payload_files) + "\n",
                    stderr="",
                )
            if command[3] == "--forget":
                receipt_present = False
                return subprocess.CompletedProcess(command, 0, stdout="Forgot package", stderr="")
        raise AssertionError(f"unexpected lifecycle command: {command!r}, check={check}")

    def fake_installer_cli_json(
        args: list[str],
        *,
        env: dict[str, str],
        repo_root: Path,
        script_path: Path,
    ) -> dict[str, Any]:
        assert script_path == repo_root / "scripts" / "install_stock_codex_compat_launcher.py"
        assert env["HOME"]
        assert env.get("CODEX_HOME") is None
        installer_cli_calls.append(args)
        if args[0] == "--install-adapter-package":
            adapter_package_dir = (
                Path(env["HOME"])
                / ".local"
                / "omnigent"
                / "stock-codex-compat"
                / "adapter-package"
            )
            return {
                "action": "adapter-package-installed",
                "adapterPackageDir": str(adapter_package_dir),
                "adapterBin": str(adapter_package_dir / "bin"),
                "adapterManifest": str(adapter_package_dir / "adapter-manifest.json"),
                "adapterToolNames": ["fetch_apple_docs"],
                "mutatesFilesystem": True,
            }
        assert args[0] == "--doctor"
        assert Path(args[args.index("--repo-root") + 1]) == repo_root
        return {"installAllowed": True, "mutatesFilesystem": False}

    monkeypatch.setattr(
        _MOD,
        "_stock_codex_compat_pkg_signing_prerequisites",
        fake_prerequisites,
    )
    monkeypatch.setattr(_MOD.shutil, "which", fake_which)
    monkeypatch.setattr(_MOD, "_effective_user_is_root", lambda: True)
    monkeypatch.setattr(_MOD, "_build_signed_notarized_stock_codex_compat_pkg", fake_signed_pkg)
    monkeypatch.setattr(
        _MOD,
        "_create_stock_codex_compat_pkg_target_volume",
        fake_create_volume,
    )
    monkeypatch.setattr(
        _MOD,
        "_detach_stock_codex_compat_pkg_target_volume",
        lambda **kwargs: kwargs["target_device"] == "/dev/disk999",
    )
    monkeypatch.setattr(_MOD, "_run_pkg_lifecycle_command", fake_lifecycle_command)
    monkeypatch.setattr(
        _MOD,
        "_run_stock_codex_compat_installer_cli_json",
        fake_installer_cli_json,
    )

    proof = _MOD.run_stock_codex_compat_pkg_installer_lifecycle_proof(
        stock_codex,
        sign_identity="Developer ID Installer: Example (ABCDE12345)",
        signing_keychain=None,
        notarytool_profile="omnigent-notary",
    )

    assert proof.status == "replacement-ready"
    assert proof.target_mountpoint == mounted_target
    assert proof.installed_runtime_root == mounted_target / runtime_root.relative_to("/")
    assert proof.receipt_package_id == "ai.omnigent.stock-codex-compat"
    assert proof.receipt_version == "1.2.3"
    assert proof.receipt_required_payload_files_present == required_payload_files
    assert proof.adapter_package_dir is not None
    assert proof.adapter_package_dir.is_absolute()
    assert proof.adapter_package_dir.parts[-4:] == (
        ".local",
        "omnigent",
        "stock-codex-compat",
        "adapter-package",
    )
    assert proof.adapter_package_action == "adapter-package-installed"
    assert proof.adapter_package_mutates_filesystem is True
    assert proof.doctor_install_allowed is True
    assert proof.doctor_mutates_filesystem is False
    assert proof.cleanup_payload_removed is True
    assert proof.cleanup_receipt_forgotten is True
    assert proof.cleanup_receipt_absent is True
    assert proof.target_detached is True
    assert installer_cli_calls[0][0] == "--install-adapter-package"
    assert installer_cli_calls[1][0] == "--doctor"
    assert lifecycle_commands[0][0] == "/usr/sbin/installer"


def test_stock_codex_compat_pkg_clean_user_canary_uses_installed_pkg_runtime(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    stock_codex = _write_codex_binary(tmp_path / "stock" / "codex")
    stock_version = _MOD.codex_version(stock_codex)
    stock_sha256 = _MOD.sha256_file(stock_codex)
    package_path = tmp_path / "artifacts" / "omnigent-stock-codex-compat.pkg"
    package_path.parent.mkdir()
    package_path.write_bytes(b"signed-notarized-pkg")
    install_prefix = Path("/Library/Application Support/Omnigent/stock-codex-compat")
    runtime_root = install_prefix / "runtime"
    required_payload_files = {
        "Library/Application Support/Omnigent/stock-codex-compat/pkg-manifest.json": True,
        "Library/Application Support/Omnigent/stock-codex-compat/bundle-manifest.json": True,
        (
            "Library/Application Support/Omnigent/stock-codex-compat/runtime/"
            "pyproject.toml"
        ): True,
        (
            "Library/Application Support/Omnigent/stock-codex-compat/runtime/"
            "scripts/install_stock_codex_compat_launcher.py"
        ): True,
        (
            "Library/Application Support/Omnigent/stock-codex-compat/runtime/"
            "scripts/provision_stock_codex.py"
        ): True,
        (
            "Library/Application Support/Omnigent/stock-codex-compat/runtime/"
            "omnigent/stock_codex_compat_wrapper.py"
        ): True,
    }
    structure = _MOD.StockCodexCompatPkgStructureProof(
        package_path=package_path.resolve(),
        package_sha256=_MOD.sha256_file(package_path),
        source_bundle_sha256="b" * 64,
        package_identifier="ai.omnigent.stock-codex-compat",
        package_version="1.2.3",
        install_location="/",
        install_prefix=install_prefix,
        runtime_root=runtime_root,
        payload_file_count=len(required_payload_files),
        required_payload_files=required_payload_files,
        script_names=("postinstall",),
        archive_entries=("Bom", "PackageInfo", "Payload", "Scripts"),
        signature_status="signed by a certificate trusted by macOS",
        signed=True,
        pkg_manifest_path=tmp_path / "expanded" / "pkg-manifest.json",
        bundle_manifest_path=tmp_path / "expanded" / "bundle-manifest.json",
        pkg_contract={"runtime": "machine-level-runtime-only"},
        bundle_source_root="<omitted-from-pkg>",
    )
    receipt_present = True
    mounted_target = tmp_path / "mounted-target"
    lifecycle_commands: list[list[str]] = []
    provisioner_commands: list[list[str]] = []
    installer_cli_calls: list[list[str]] = []

    def fake_which(name: str, path: str | None = None) -> str | None:
        if path is not None:
            for entry in path.split(os.pathsep):
                candidate = Path(entry) / name
                if candidate.is_file() and os.access(candidate, os.X_OK):
                    return str(candidate)
            return None
        return {
            "pkgutil": "/usr/sbin/pkgutil",
            "xcrun": "/usr/bin/xcrun",
            "spctl": "/usr/sbin/spctl",
            "installer": "/usr/sbin/installer",
            "hdiutil": "/usr/bin/hdiutil",
            "uvx": str(_write_uvx_binary(tmp_path / "tools" / "uvx")),
        }.get(name)

    def fake_signed_pkg(**kwargs: object) -> Any:
        assert kwargs["package_path"] == package_path.resolve()
        assert kwargs["source_repo_root"] == _REPO_ROOT
        return _MOD._SignedNotarizedStockCodexCompatPkg(
            structure=structure,
            notary_submission_id="prebuilt-package",
            notary_status="prebuilt-staple-validated",
            notary_output_preview="prebuilt",
            staple_output_preview="prebuilt",
            stapler_validate_output_preview="validated",
            gatekeeper_output_preview="accepted",
        )

    def fake_create_volume(**kwargs: object) -> tuple[Path, Path, str]:
        assert kwargs["hdiutil_path"] == "/usr/bin/hdiutil"
        mounted_target.mkdir()
        return tmp_path / "target.dmg", mounted_target, "/dev/disk999"

    def write_installed_payload() -> None:
        installed_prefix = mounted_target / install_prefix.relative_to("/")
        installed_runtime = mounted_target / runtime_root.relative_to("/")
        (installed_runtime / "scripts").mkdir(parents=True)
        (installed_runtime / "omnigent").mkdir()
        (installed_runtime / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
        (installed_runtime / "scripts" / "install_stock_codex_compat_launcher.py").write_text(
            "#!/usr/bin/env python3\n",
            encoding="utf-8",
        )
        (installed_runtime / "scripts" / "provision_stock_codex.py").write_text(
            "#!/usr/bin/env python3\n",
            encoding="utf-8",
        )
        (installed_runtime / "omnigent" / "stock_codex_compat_wrapper.py").write_text(
            "",
            encoding="utf-8",
        )
        (installed_prefix / "pkg-manifest.json").write_text(
            json.dumps(
                {
                    "contract": {"runtime": "machine-level-runtime-only"},
                    "packageIdentifier": "ai.omnigent.stock-codex-compat",
                    "packageVersion": "1.2.3",
                }
            )
            + "\n",
            encoding="utf-8",
        )
        (installed_prefix / "bundle-manifest.json").write_text(
            json.dumps({"sourceRoot": "<omitted-from-pkg>"}) + "\n",
            encoding="utf-8",
        )

    def fake_lifecycle_command(
        command: list[str],
        *,
        timeout: float,
        failure_label: str,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        nonlocal receipt_present
        assert timeout > 0
        assert failure_label
        lifecycle_commands.append(command)
        if command[0] == "/usr/sbin/installer":
            assert command[command.index("-target") + 1] == str(mounted_target)
            write_installed_payload()
            return subprocess.CompletedProcess(command, 0, stdout="installer ok", stderr="")
        if command[:3] == ["/usr/sbin/pkgutil", "--volume", str(mounted_target)]:
            if command[3] == "--pkg-info":
                if receipt_present:
                    return subprocess.CompletedProcess(
                        command,
                        0,
                        stdout=(
                            "package-id: ai.omnigent.stock-codex-compat\n"
                            "version: 1.2.3\n"
                        ),
                        stderr="",
                    )
                return subprocess.CompletedProcess(command, 1, stdout="", stderr="not found")
            if command[3] == "--files":
                return subprocess.CompletedProcess(
                    command,
                    0,
                    stdout="\n".join(required_payload_files) + "\n",
                    stderr="",
                )
            if command[3] == "--forget":
                receipt_present = False
                return subprocess.CompletedProcess(command, 0, stdout="Forgot package", stderr="")
        raise AssertionError(f"unexpected lifecycle command: {command!r}, check={check}")

    def fake_provisioner_json(
        command: list[str],
        *,
        env: dict[str, str],
        cwd: Path,
        failure_label: str,
        timeout: float = 60,
        run_as_user: str | None = None,
        sudo_path: str | None = None,
    ) -> dict[str, Any]:
        assert run_as_user is None
        assert sudo_path is None
        assert failure_label
        assert timeout > 0
        assert cwd == mounted_target / runtime_root.relative_to("/")
        assert env["HOME"]
        provisioner_commands.append(command)
        cache_root = Path(command[command.index("--cache-root") + 1])
        expected_sha = command[command.index("--expected-sha256") + 1]
        assert expected_sha == stock_sha256
        payload_dir = cache_root / "0.142.2"
        codex_path = _write_codex_binary(payload_dir / "codex", version=stock_version)
        manifest_path = payload_dir / "manifest.json"
        manifest_path.write_text(
            json.dumps({"kind": "omnigent-stock-codex", "sourceKind": "channel"})
            + "\n",
            encoding="utf-8",
        )
        return {
            "action": "installed",
            "codexPath": str(codex_path),
            "payloadDir": str(payload_dir),
            "manifestPath": str(manifest_path),
            "version": stock_version,
            "sha256": _MOD.sha256_file(codex_path),
            "sourceKind": "channel",
            "env": {_MOD.OMNIGENT_STOCK_CODEX_PATH_ENV: str(codex_path)},
        }

    def fake_installer_cli_json(
        args: list[str],
        *,
        env: dict[str, str],
        repo_root: Path,
        script_path: Path,
        run_as_user: str | None = None,
        sudo_path: str | None = None,
    ) -> dict[str, Any]:
        assert run_as_user is None
        assert sudo_path is None
        assert repo_root == mounted_target / runtime_root.relative_to("/")
        assert script_path == repo_root / "scripts" / "install_stock_codex_compat_launcher.py"
        installer_cli_calls.append(args)
        home = Path(env["HOME"])
        adapter_package_dir = (
            home / ".local" / "omnigent" / "stock-codex-compat" / "adapter-package"
        )
        if args[0] == "--install-adapter-package":
            adapter_bin = adapter_package_dir / "bin"
            adapter_bin.mkdir(parents=True)
            adapter_manifest = adapter_package_dir / "adapter-manifest.json"
            adapter_manifest.write_text(
                json.dumps({"tools": [{"name": "fetch_apple_docs"}]}) + "\n",
                encoding="utf-8",
            )
            return {
                "action": "adapter-package-installed",
                "adapterPackageDir": str(adapter_package_dir),
                "adapterBin": str(adapter_bin),
                "adapterManifest": str(adapter_manifest),
                "adapterToolNames": ["fetch_apple_docs"],
                "mutatesFilesystem": True,
            }
        if args[0] == "--install":
            pinned_codex = Path(args[args.index("--pinned-codex-path") + 1])
            launcher_path = home / ".local" / "bin" / "omnigent-stock-codex-compat"
            manifest_path = (
                home / ".local" / "omnigent" / "launchers" / "stock-codex-compat.json"
            )
            launcher_path.parent.mkdir(parents=True)
            manifest_path.parent.mkdir(parents=True)
            launcher_path.write_text(
                "#!/bin/sh\n"
                "if [ \"${1:-}\" = \"--version\" ]; then\n"
                f"  exec {shlex.quote(str(pinned_codex))} --version\n"
                "fi\n"
                "if [ \"${1:-}\" = \"--omnigent-stock-codex-compat-launcher-probe\" ]; then\n"
                "  cat <<'EOF'\n"
                "OMNIGENT_STOCK_CODEX_COMPAT_LAUNCHER_OK\n"
                f"runtime={repo_root}\n"
                f"codex={pinned_codex}\n"
                "EOF\n"
                "  exit 0\n"
                "fi\n"
                "exit 64\n",
                encoding="utf-8",
            )
            launcher_path.chmod(0o755)
            manifest_path.write_text(
                json.dumps(
                    {
                        "repoRoot": str(repo_root),
                        "pinnedCodexPath": str(pinned_codex),
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            rollback_command = (
                "printf 'compat_launcher_action=uninstalled\\n'; "
                f"rm -f {shlex.quote(str(launcher_path))} "
                f"{shlex.quote(str(manifest_path))}; "
                f"# {repo_root}"
            )
            return {
                "action": "installed",
                "rollbackCommand": rollback_command,
                "mutatesFilesystem": True,
            }
        assert args[0] == "--doctor"
        return {
            "installAllowed": True,
            "existingTargetState": "managed",
            "targetSelectedOnPath": True,
            "mutatesFilesystem": False,
        }

    def fake_auth_classifier(**kwargs: object) -> tuple[Path, str | None, str]:
        codex_home = kwargs["codex_home"]
        assert isinstance(codex_home, Path)
        return codex_home / "auth.json", "needs-auth", '{"unavailableReason":"needs-auth"}\n'

    monkeypatch.setattr(_MOD.shutil, "which", fake_which)
    monkeypatch.setattr(_MOD, "_xcrun_find_tool", lambda _xcrun, tool: f"/usr/bin/{tool}")
    monkeypatch.setattr(_MOD, "_effective_user_is_root", lambda: True)
    monkeypatch.setattr(
        _MOD,
        "_validate_prebuilt_signed_notarized_stock_codex_compat_pkg",
        fake_signed_pkg,
    )
    monkeypatch.setattr(
        _MOD,
        "_create_stock_codex_compat_pkg_target_volume",
        fake_create_volume,
    )
    monkeypatch.setattr(
        _MOD,
        "_detach_stock_codex_compat_pkg_target_volume",
        lambda **kwargs: kwargs["target_device"] == "/dev/disk999",
    )
    monkeypatch.setattr(_MOD, "_run_pkg_lifecycle_command", fake_lifecycle_command)
    monkeypatch.setattr(_MOD, "_run_stock_codex_provisioner_json", fake_provisioner_json)
    monkeypatch.setattr(
        _MOD,
        "_run_stock_codex_compat_installer_cli_json",
        fake_installer_cli_json,
    )
    monkeypatch.setattr(_MOD, "_run_installed_runtime_auth_classifier", fake_auth_classifier)

    proof = _MOD.run_stock_codex_compat_pkg_clean_user_canary_proof(
        stock_codex,
        package_path=package_path,
    )

    assert proof.status == "replacement-ready"
    assert proof.installed_runtime_root == mounted_target / runtime_root.relative_to("/")
    assert proof.receipt_package_id == "ai.omnigent.stock-codex-compat"
    assert proof.provisioned_codex_path is not None
    assert proof.clean_cache_root is not None
    assert proof.provisioned_codex_path.is_relative_to(proof.clean_cache_root)
    assert proof.provisioned_version == stock_version
    assert proof.adapter_package_action == "adapter-package-installed"
    assert proof.adapter_package_exists_after_install is True
    assert proof.install_action == "installed"
    assert proof.version_output == stock_version
    assert proof.doctor_install_allowed is True
    assert proof.doctor_existing_target_state == "managed"
    assert proof.doctor_target_selected_on_path is True
    assert proof.doctor_mutates_filesystem is False
    assert proof.clean_unavailable_reason == "needs-auth"
    assert proof.launcher_removed_after_rollback is True
    assert proof.manifest_removed_after_rollback is True
    assert proof.cleanup_payload_removed is True
    assert proof.cleanup_receipt_forgotten is True
    assert proof.cleanup_receipt_absent is True
    assert proof.target_detached is True
    assert provisioner_commands
    assert installer_cli_calls[0][0] == "--install-adapter-package"
    assert installer_cli_calls[1][0] == "--install"
    assert installer_cli_calls[2][0] == "--doctor"
    assert lifecycle_commands[0][0] == "/usr/sbin/installer"


def test_stock_codex_compat_pkg_external_clean_user_requires_marked_home(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    stock_codex = _write_codex_binary(tmp_path / "stock" / "codex")
    package_path = tmp_path / "artifacts" / "omnigent-stock-codex-compat.pkg"
    package_path.parent.mkdir()
    package_path.write_bytes(b"signed-notarized-pkg")
    clean_home = tmp_path / "external-home"
    clean_home.mkdir()

    def fake_which(name: str, path: str | None = None) -> str | None:
        if path is not None:
            return None
        return {
            "pkgutil": "/usr/sbin/pkgutil",
            "xcrun": "/usr/bin/xcrun",
            "spctl": "/usr/sbin/spctl",
            "installer": "/usr/sbin/installer",
            "hdiutil": "/usr/bin/hdiutil",
            "uvx": str(_write_uvx_binary(tmp_path / "tools" / "uvx")),
        }.get(name)

    monkeypatch.setattr(_MOD.shutil, "which", fake_which)
    monkeypatch.setattr(_MOD, "_xcrun_find_tool", lambda _xcrun, tool: f"/usr/bin/{tool}")

    proof = _MOD.run_stock_codex_compat_pkg_external_clean_user_proof(
        stock_codex,
        package_path=package_path,
        clean_user_home=clean_home,
    )

    assert proof.status == "blocked"
    assert proof.clean_user_home == clean_home.resolve()
    assert proof.clean_user_marker_path == (
        clean_home.resolve() / _MOD.EXTERNAL_CLEAN_USER_MARKER_NAME
    )
    assert any("not marked disposable" in item for item in proof.missing_prerequisites)


def test_stock_codex_compat_pkg_external_clean_user_resolves_account_home(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    stock_codex = _write_codex_binary(tmp_path / "stock" / "codex")
    package_path = tmp_path / "artifacts" / "omnigent-stock-codex-compat.pkg"
    package_path.parent.mkdir()
    package_path.write_bytes(b"signed-notarized-pkg")
    clean_home = tmp_path / "external-account-home"
    clean_home.mkdir()
    home_stat = clean_home.stat()

    def fake_which(name: str, path: str | None = None) -> str | None:
        if path is not None:
            return None
        return {
            "pkgutil": "/usr/sbin/pkgutil",
            "xcrun": "/usr/bin/xcrun",
            "spctl": "/usr/sbin/spctl",
            "installer": "/usr/sbin/installer",
            "hdiutil": "/usr/bin/hdiutil",
            "sudo": "/usr/bin/sudo",
            "uvx": str(_write_uvx_binary(tmp_path / "tools" / "uvx")),
        }.get(name)

    monkeypatch.setattr(_MOD.shutil, "which", fake_which)
    monkeypatch.setattr(_MOD, "_xcrun_find_tool", lambda _xcrun, tool: f"/usr/bin/{tool}")
    monkeypatch.setattr(
        _MOD,
        "_lookup_external_clean_user_account",
        lambda name: _MOD._ExternalCleanUserAccount(
            name=name,
            uid=home_stat.st_uid or 501,
            gid=home_stat.st_gid,
            home=clean_home.resolve(),
        ),
    )

    proof = _MOD.run_stock_codex_compat_pkg_external_clean_user_proof(
        stock_codex,
        package_path=package_path,
        clean_user_home=None,
        clean_user_name="omnigent-clean",
    )

    assert proof.status == "blocked"
    assert proof.clean_user_name == "omnigent-clean"
    assert proof.clean_user_home == clean_home.resolve()
    assert proof.clean_user_marker_path == (
        clean_home.resolve() / _MOD.EXTERNAL_CLEAN_USER_MARKER_NAME
    )
    assert any("not marked disposable" in item for item in proof.missing_prerequisites)


def test_external_clean_user_command_wraps_sudo_with_clean_env() -> None:
    command, env = _MOD._external_clean_user_command(
        ["/bin/echo", "ok"],
        env={
            "HOME": "/Users/omnigent-clean",
            "TMPDIR": "/Users/omnigent-clean/.tmp",
            "PATH": "/Users/omnigent-clean/.local/bin:/usr/bin:/bin",
            "PYTHONPATH": "/runtime",
            "CODEX_HOME": "/Users/omnigent-clean/.codex-proof",
            "UV_CACHE_DIR": "/Users/omnigent-clean/.proof/uv-cache",
            "XDG_CACHE_HOME": "/Users/omnigent-clean/.proof/xdg-cache",
            "SECRET_TOKEN": "must-not-leak",
        },
        run_as_user="omnigent-clean",
        sudo_path="/usr/bin/sudo",
    )

    assert command[:5] == [
        "/usr/bin/sudo",
        "-u",
        "omnigent-clean",
        "/usr/bin/env",
        "-i",
    ]
    assert "HOME=/Users/omnigent-clean" in command
    assert "PATH=/Users/omnigent-clean/.local/bin:/usr/bin:/bin" in command
    assert "PYTHONPATH=/runtime" in command
    assert "SECRET_TOKEN=must-not-leak" not in command
    assert command[-2:] == ["/bin/echo", "ok"]
    assert env == {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin"}


def test_stock_codex_compat_pkg_clean_vm_requires_target(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    stock_codex = _write_codex_binary(tmp_path / "stock" / "codex")
    package_path = tmp_path / "artifacts" / "omnigent-stock-codex-compat.pkg"
    package_path.parent.mkdir()
    package_path.write_bytes(b"signed-notarized-pkg")

    def fake_which(name: str, path: str | None = None) -> str | None:
        if path is not None:
            return None
        return {
            "ssh": "/usr/bin/ssh",
            "scp": "/usr/bin/scp",
            "tart": "/usr/local/bin/tart",
        }.get(name)

    monkeypatch.setattr(_MOD.shutil, "which", fake_which)

    proof = _MOD.run_stock_codex_compat_pkg_clean_vm_proof(
        stock_codex,
        package_path=package_path,
        clean_vm_ssh_target=None,
        clean_vm_tart_name=None,
        clean_vm_ssh_identity=None,
        clean_vm_ssh_user=None,
        clean_vm_ssh_port=22,
        clean_vm_start_tart=False,
    )

    assert proof.status == "blocked"
    assert proof.package_path == package_path.resolve()
    assert proof.package_sha256 == _MOD.sha256_file(package_path)
    assert any("--clean-vm-ssh-target" in item for item in proof.missing_prerequisites)


def test_stock_codex_compat_pkg_clean_vm_blocks_missing_tart_vm(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    stock_codex = _write_codex_binary(tmp_path / "stock" / "codex")
    package_path = tmp_path / "artifacts" / "omnigent-stock-codex-compat.pkg"
    package_path.parent.mkdir()
    package_path.write_bytes(b"signed-notarized-pkg")

    def fake_which(name: str, path: str | None = None) -> str | None:
        if path is not None:
            return None
        return {
            "ssh": "/usr/bin/ssh",
            "scp": "/usr/bin/scp",
            "tart": "/usr/local/bin/tart",
        }.get(name)

    monkeypatch.setattr(_MOD.shutil, "which", fake_which)
    monkeypatch.setattr(_MOD, "_tart_vm_names", lambda _tart_path: set())

    proof = _MOD.run_stock_codex_compat_pkg_clean_vm_proof(
        stock_codex,
        package_path=package_path,
        clean_vm_ssh_target=None,
        clean_vm_tart_name="omnigent-clean",
        clean_vm_ssh_identity=None,
        clean_vm_ssh_user="admin",
        clean_vm_ssh_port=22,
        clean_vm_start_tart=False,
    )

    assert proof.status == "blocked"
    assert proof.tart_name == "omnigent-clean"
    assert proof.ssh_user == "admin"
    assert any("Tart VM does not exist" in item for item in proof.missing_prerequisites)


def test_clean_vm_remote_script_requires_marker_and_noninteractive_sudo() -> None:
    script = _MOD._clean_vm_remote_script_text()

    assert ".omnigent-stock-codex-compat-clean-user-ok" in script
    assert 'export PATH="$HOME/.local/bin:$PATH"' in script
    assert (
        'installed_bootstrapper="$runtime_root/scripts/bootstrap_stock_codex_compat.sh"'
        in script
    )
    assert '"$installed_bootstrapper"' in script
    assert '--user-runtime-root "$user_runtime_root"' in script
    assert '--cache-root "$clean_cache_root"' in script
    assert "sed -E 's/^[^0-9]*([0-9]+(\\.[0-9]+)+" in script
    assert 'export OMNIGENT_STOCK_CODEX_PATH="$provisioned_codex"' in script
    assert 'probe_output="$("$selected" --omnigent-stock-codex-compat-launcher-probe)"' in script
    assert 'fail "launcher probe sentinel missing"' in script
    assert '| grep -q "OMNIGENT_STOCK_CODEX_COMPAT_LAUNCHER_OK"' not in script
    assert "sudo -n true" in script
    assert "sudo -n installer -pkg" in script
    assert "sudo -n pkgutil --forget" in script
    assert "stock_codex_compat_pkg_clean_vm_status=replacement-ready" in script
    assert "--uninstall" in script
    assert "--expected-sha256" in script


def test_clean_vm_remote_acquisition_script_uses_url_backed_channel() -> None:
    script = _MOD._clean_vm_remote_acquisition_script_text()

    assert ".omnigent-stock-codex-compat-clean-user-ok" in script
    assert "remote acquisition channel manifest lacks url" in script
    assert "remote acquisition channel manifest must not contain path-backed artifacts" in script
    assert "stock_codex_artifact" not in script
    assert "--allow-remote-channel-download" in script
    assert '--channel-policy "$channel_policy"' in script
    assert "--expected-sha256 \"$expected_channel_sha\"" in script
    assert "remote-acquired stock Codex missing" in script
    assert "remoteAcquisitionUrl" in script
    assert "live_auth_json" in script
    assert "STOCK_CODEX_COMPAT_LIVE_OK" in script
    assert "stock_codex_compat_pkg_clean_vm_live_status=replacement-ready" in script
    assert "stock_codex_compat_pkg_clean_vm_remote_acquisition_status=replacement-ready" in script
    assert 'proof_mode="${9:-}"' in script
    assert "auth-onboarding" in script
    assert "stock_codex_compat_pkg_clean_vm_auth_onboarding_status=replacement-ready" in script
    assert "auth onboarding proof must not receive uploaded auth json" in script
    assert "commandExecuted" in script
    assert "authUploaded" in script
    assert "auth-persistence" in script
    assert "STOCK_CODEX_COMPAT_AUTH_PERSISTENCE_OK" in script
    assert "stock_codex_compat_pkg_clean_vm_auth_persistence_status=replacement-ready" in script
    assert "auth persistence proof requires proof-scoped auth json" in script
    assert "browserLoginAutomated" in script
    assert "--write-launch-agent" in script
    assert 'launchctl bootstrap "$launch_domain" "$launch_agent_path"' in script
    assert 'launchctl kickstart -k "$launch_domain/$launch_agent_label"' in script
    assert 'launchctl bootout "$launch_domain/$launch_agent_label"' in script
    assert "stock_codex_compat_pkg_clean_vm_update_agent_status=replacement-ready" in script


def test_clean_vm_preflight_cleanup_requires_marker_and_proof_owned_paths() -> None:
    command = _MOD._clean_vm_preflight_cleanup_command()

    assert command.startswith("/bin/bash -lc ")
    assert ".omnigent-stock-codex-compat-clean-user-ok" in command
    assert "sudo -n true" in command
    assert 'pkg_id="ai.omnigent.stock-codex-compat"' in command
    assert "/Library/Application Support/Omnigent/stock-codex-compat" in command
    assert "$HOME/.local/bin/omnigent-stock-codex-compat" in command
    assert "$HOME/.local/omnigent/stock-codex-compat" in command
    assert "$HOME/.local/omnigent/codex-stock" in command
    assert "$HOME/.codex-omnigent-clean-user-canary" in command
    assert "$HOME/.omnigent-stock-codex-compat-clean-vm-proof" in command
    assert (
        "$HOME/.omnigent-stock-codex-compat-clean-vm-remote-acquisition-proof"
        in command
    )
    assert "adapter root remained after preflight cleanup" in command
    assert "stock Codex cache root remained after preflight cleanup" in command
    assert "sudo -n pkgutil --forget" in command
    assert "stock_codex_compat_pkg_clean_vm_preflight_cleanup=completed" in command


def test_nontart_clean_machine_preflight_script_is_inspection_only() -> None:
    script = _MOD._nontart_clean_machine_preflight_script_text()

    assert "stock_codex_compat_pkg_nontart_clean_machine_preflight_" in script
    assert ".omnigent-stock-codex-compat-clean-user-ok" in script
    assert "sudo -n true" in script
    assert "command -v uvx" in script
    assert 'pkg_id="ai.omnigent.stock-codex-compat"' in script
    assert "/Library/Application Support/Omnigent/stock-codex-compat" in script
    assert "$HOME/.local/bin/omnigent-stock-codex-compat" in script
    assert "$HOME/.local/omnigent/launchers/stock-codex-compat.json" in script
    assert "$HOME/.local/omnigent/stock-codex-compat" in script
    assert "$HOME/.local/omnigent/codex-stock" in script
    assert "$HOME/Library/LaunchAgents/ai.omnigent.stock-codex-compat.update.plist" in script
    assert 'pkgutil --check-signature "$pkg_path"' in script
    assert 'xcrun stapler validate "$pkg_path"' in script
    assert 'spctl -a -vv -t install "$pkg_path"' in script
    assert "installer -pkg" not in script
    assert "pkgutil --forget" not in script
    assert "rm -rf" not in script


def test_stock_codex_compat_pkg_nontart_clean_machine_preflight_blocks_without_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    package_path = tmp_path / "artifacts" / "omnigent-stock-codex-compat.pkg"
    package_path.parent.mkdir()
    package_path.write_bytes(b"signed-notarized-pkg")

    def fake_which(name: str, path: str | None = None) -> str | None:
        if path is not None:
            return None
        return {"ssh": "/usr/bin/ssh", "scp": "/usr/bin/scp"}.get(name)

    monkeypatch.setattr(_MOD.shutil, "which", fake_which)

    proof = _MOD.run_stock_codex_compat_pkg_nontart_clean_machine_preflight_proof(
        package_path=package_path,
        release_evidence_path=tmp_path / "missing-release-evidence.json",
        clean_vm_ssh_target="admin@192.0.2.10",
        clean_vm_ssh_identity=None,
        clean_vm_ssh_port=22,
    )

    assert proof.status == "blocked"
    assert proof.package_path == package_path.resolve()
    assert proof.package_sha256 == _MOD.sha256_file(package_path)
    assert proof.release_evidence_path == (tmp_path / "missing-release-evidence.json").resolve()
    assert any("missing clean-VM release evidence" in item for item in proof.missing_prerequisites)


def _write_stock_codex_compat_release_evidence(
    path: Path,
    *,
    package_path: Path,
    package_sha256: str,
    selected_version: str = "codex-cli 0.143.0",
) -> Path:
    selected_launcher = "/Users/admin/.local/bin/omnigent-stock-codex-compat"
    selected_codex = "/Users/admin/.local/omnigent/codex-stock/0.143.0/codex"
    evidence: dict[str, Any] = {
        "kind": "omnigent-stock-codex-compat-release-candidate-evidence",
        "schemaVersion": 1,
        "proof": "stock-codex-compat-pkg-clean-vm-release",
        "command": ["prove"],
        "exitCode": 0,
        "underlyingExitCode": 0,
        "releaseCriteriaFailures": [],
        "status": "replacement-ready",
        "missingPrerequisites": [],
        "packagePath": str(package_path),
        "packageSha256": package_sha256,
        "stockCodexPath": "/Users/admin/.local/omnigent/codex-stock/0.142.5/codex",
        "stockCodexVersion": "codex-cli 0.142.5",
        "stockCodexSha256": "a" * 64,
        "caskVersion": "0.143.0",
        "caskUrl": (
            "https://github.com/openai/codex/releases/download/"
            "rust-v0.143.0/codex-aarch64-apple-darwin.tar.gz"
        ),
        "caskSha256": "b" * 64,
        "channelPolicy": "official-openai-github-release",
        "targetMode": "direct-ssh",
        "sshTarget": "admin@192.0.2.10",
        "authPath": "/Users/admin/.codex/auth.json",
        "authSource": "stock-default-home",
        "authAvailable": True,
        "stepOrder": [
            "remote-acquisition",
            "auth-onboarding",
            "auth-persistence",
            "update-agent",
            "live",
        ],
        "stepStatuses": {
            "remote-acquisition": "replacement-ready",
            "auth-onboarding": "replacement-ready",
            "auth-persistence": "replacement-ready",
            "update-agent": "replacement-ready",
            "live": "replacement-ready",
        },
        "stepMissingPrerequisites": {
            "remote-acquisition": [],
            "auth-onboarding": [],
            "auth-persistence": [],
            "update-agent": [],
            "live": [],
        },
        "blockedStep": None,
        "tartStartedCount": 0,
        "tartStoppedCount": 0,
        "hostStockCodexUploadedAny": False,
        "stepDetails": {
            "remote-acquisition": {
                "status": "replacement-ready",
                "remoteStatus": "replacement-ready",
                "hostStockCodexUploaded": False,
                "tartStarted": False,
                "tartStopped": False,
                "selectedCommandPath": None,
                "selectedCommandVersion": None,
                "selectedCodexPath": None,
                "selectedCodexVersion": None,
                "threadId": None,
                "scheduledAction": None,
            },
            "auth-onboarding": {
                "status": "replacement-ready",
                "remoteStatus": "replacement-ready",
                "hostStockCodexUploaded": False,
                "tartStarted": False,
                "tartStopped": False,
                "selectedCommandPath": selected_launcher,
                "selectedCommandVersion": selected_version,
                "selectedCodexPath": None,
                "selectedCodexVersion": None,
                "threadId": None,
                "scheduledAction": None,
            },
            "auth-persistence": {
                "status": "replacement-ready",
                "remoteStatus": "replacement-ready",
                "hostStockCodexUploaded": False,
                "tartStarted": False,
                "tartStopped": False,
                "selectedCommandPath": selected_launcher,
                "selectedCommandVersion": selected_version,
                "selectedCodexPath": None,
                "selectedCodexVersion": None,
                "threadId": "thread-auth",
                "scheduledAction": None,
            },
            "update-agent": {
                "status": "replacement-ready",
                "remoteStatus": "replacement-ready",
                "hostStockCodexUploaded": False,
                "tartStarted": False,
                "tartStopped": False,
                "selectedCommandPath": None,
                "selectedCommandVersion": None,
                "selectedCodexPath": selected_codex,
                "selectedCodexVersion": selected_version,
                "threadId": None,
                "scheduledAction": "up-to-date",
            },
            "live": {
                "status": "replacement-ready",
                "remoteStatus": "replacement-ready",
                "hostStockCodexUploaded": False,
                "tartStarted": False,
                "tartStopped": False,
                "selectedCommandPath": selected_launcher,
                "selectedCommandVersion": selected_version,
                "selectedCodexPath": None,
                "selectedCodexVersion": None,
                "threadId": "thread-live",
                "scheduledAction": None,
            },
        },
        "fields": [],
    }
    path.write_text(json.dumps(evidence) + "\n", encoding="utf-8")
    return path


def _nontart_preflight_proof(
    *,
    status: str = "replacement-ready",
    missing_prerequisites: tuple[str, ...] = (),
    package_path: Path | None = None,
    package_sha256: str | None = "pkg-sha",
    release_evidence_path: Path | None = None,
    release_evidence_status: str | None = "verified",
) -> Any:
    return _MOD.StockCodexCompatPkgNonTartCleanMachinePreflightProof(
        status=status,
        missing_prerequisites=missing_prerequisites,
        tool_paths={"ssh": "/usr/bin/ssh", "scp": "/usr/bin/scp"},
        package_path=package_path,
        package_sha256=package_sha256,
        release_evidence_path=release_evidence_path,
        release_evidence_status=release_evidence_status,
        release_evidence_output_preview="verified\n",
        ssh_target="admin@192.0.2.10",
        ssh_identity=None,
        ssh_port=22,
        remote_work_dir=None,
        remote_status=status,
        remote_output_preview="",
        remote_user="admin",
        remote_home="/Users/admin",
        macos_version="26.5.1",
        arch="arm64",
        uvx_path="/Users/admin/.local/bin/uvx",
        uv_path="/Users/admin/.local/bin/uv",
        sudo_noninteractive=True,
        disposable_marker_present=True,
        package_receipt_present=False,
        package_payload_present=False,
        launcher_present=False,
        launcher_manifest_present=False,
        adapter_root_present=False,
        stock_cache_present=False,
        launch_agent_present=False,
        remote_package_sha256=package_sha256,
        signature_status="accepted",
        staple_status="accepted",
        gatekeeper_status="accepted",
    )


def test_stock_codex_compat_pkg_nontart_clean_machine_preflight_blocks_stale_selected_version(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    package_path = tmp_path / "artifacts" / "omnigent-stock-codex-compat.pkg"
    package_path.parent.mkdir()
    package_path.write_bytes(b"signed-notarized-pkg")
    evidence_path = _write_stock_codex_compat_release_evidence(
        tmp_path / "release-evidence.json",
        package_path=package_path.resolve(),
        package_sha256=_MOD.sha256_file(package_path),
        selected_version="codex-cli 0.142.5",
    )

    def fake_which(name: str, path: str | None = None) -> str | None:
        if path is not None:
            return None
        return {"ssh": "/usr/bin/ssh", "scp": "/usr/bin/scp"}.get(name)

    monkeypatch.setattr(_MOD.shutil, "which", fake_which)
    monkeypatch.setattr(
        _MOD,
        "_wait_for_clean_vm_ssh",
        lambda **_kwargs: pytest.fail("preflight should block before SSH readiness"),
    )
    monkeypatch.setattr(
        _MOD,
        "_copy_clean_vm_file",
        lambda **_kwargs: pytest.fail("preflight should block before uploading artifacts"),
    )
    monkeypatch.setattr(
        _MOD,
        "_run_clean_vm_ssh_command",
        lambda *_args, **_kwargs: pytest.fail("preflight should block before remote commands"),
    )

    proof = _MOD.run_stock_codex_compat_pkg_nontart_clean_machine_preflight_proof(
        package_path=package_path,
        release_evidence_path=evidence_path,
        clean_vm_ssh_target="admin@192.0.2.10",
        clean_vm_ssh_identity=None,
        clean_vm_ssh_port=22,
    )

    assert proof.status == "blocked"
    assert proof.remote_status == "not-started"
    assert proof.release_evidence_status == "blocked"
    assert any(
        item == "release evidence verifier did not pass"
        for item in proof.missing_prerequisites
    )
    assert "selectedCommandVersion]='codex-cli 0.142.5'" in str(
        proof.release_evidence_output_preview
    )
    assert "selectedCodexVersion]='codex-cli 0.142.5'" in str(
        proof.release_evidence_output_preview
    )


def test_stock_codex_compat_pkg_nontart_clean_machine_install_blocks_before_install(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    package_path = tmp_path / "compat.pkg"
    evidence_path = tmp_path / "release-evidence.json"

    monkeypatch.setattr(
        _MOD,
        "run_stock_codex_compat_pkg_nontart_clean_machine_preflight_proof",
        lambda **_kwargs: _nontart_preflight_proof(
            status="blocked",
            missing_prerequisites=("release evidence verifier did not pass",),
            package_path=package_path,
            release_evidence_path=evidence_path,
            release_evidence_status="blocked",
        ),
    )
    monkeypatch.setattr(
        _MOD,
        "run_stock_codex_compat_pkg_clean_vm_remote_acquisition_proof",
        lambda *_args, **_kwargs: pytest.fail("install should not run after blocked preflight"),
    )

    proof = _MOD.run_stock_codex_compat_pkg_nontart_clean_machine_install_proof(
        tmp_path / "codex",
        package_path=package_path,
        release_evidence_path=evidence_path,
        clean_vm_ssh_target="admin@192.0.2.10",
        clean_vm_ssh_identity=None,
        clean_vm_ssh_port=22,
    )

    assert proof.status == "blocked"
    assert proof.install is None
    assert proof.preflight.release_evidence_status == "blocked"
    assert "non-Tart clean-machine preflight did not pass" in proof.missing_prerequisites


def test_stock_codex_compat_pkg_nontart_clean_machine_install_runs_direct_remote_acquisition(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    stock_codex = tmp_path / "codex"
    package_path = tmp_path / "compat.pkg"
    evidence_path = tmp_path / "release-evidence.json"
    preflight = _nontart_preflight_proof(
        package_path=package_path,
        release_evidence_path=evidence_path,
    )
    captured_install_kwargs: dict[str, object] = {}

    def fake_remote_acquisition(
        stock_codex_path: Path,
        **kwargs: object,
    ) -> Any:
        captured_install_kwargs.update(kwargs)
        return _MOD.StockCodexCompatPkgCleanVmProof(
            status="replacement-ready",
            missing_prerequisites=(),
            tool_paths={"ssh": "/usr/bin/ssh", "scp": "/usr/bin/scp"},
            stock_codex_path=stock_codex_path,
            stock_codex_version="codex-cli 0.142.5",
            stock_codex_sha256="a" * 64,
            package_path=package_path,
            package_sha256="pkg-sha",
            tart_name=None,
            ssh_target="admin@192.0.2.10",
            ssh_identity=None,
            ssh_user=None,
            ssh_port=22,
            tart_ip=None,
            remote_work_dir="/tmp/proof",
            remote_status="replacement-ready",
            remote_output_preview="remote ok",
            tart_started=False,
            tart_stopped=False,
            proof_variant="official-remote-channel-acquisition",
            cask_version="0.143.0",
            cask_url=(
                "https://github.com/openai/codex/releases/download/"
                "rust-v0.143.0/codex-aarch64-apple-darwin.tar.gz"
            ),
            cask_sha256="b" * 64,
            channel_policy="official-openai-github-release",
            host_stock_codex_uploaded=False,
        )

    monkeypatch.setattr(
        _MOD,
        "run_stock_codex_compat_pkg_nontart_clean_machine_preflight_proof",
        lambda **_kwargs: preflight,
    )
    monkeypatch.setattr(
        _MOD,
        "run_stock_codex_compat_pkg_clean_vm_remote_acquisition_proof",
        fake_remote_acquisition,
    )

    proof = _MOD.run_stock_codex_compat_pkg_nontart_clean_machine_install_proof(
        stock_codex,
        package_path=package_path,
        release_evidence_path=evidence_path,
        clean_vm_ssh_target="admin@192.0.2.10",
        clean_vm_ssh_identity=None,
        clean_vm_ssh_port=22,
    )

    assert proof.status == "replacement-ready"
    assert captured_install_kwargs["clean_vm_tart_name"] is None
    assert captured_install_kwargs["clean_vm_ssh_user"] is None
    assert captured_install_kwargs["clean_vm_start_tart"] is False
    assert captured_install_kwargs["clean_vm_ssh_target"] == "admin@192.0.2.10"

    _MOD.print_stock_codex_compat_pkg_nontart_clean_machine_install_proof(proof)
    output = capsys.readouterr().out
    assert (
        "stock_codex_compat_pkg_nontart_clean_machine_install_status=replacement-ready"
        in output
    )
    assert "release-evidence and clean-target preflight checks" in output
    assert "host_stock_codex_uploaded=False" in output


def test_stock_codex_compat_pkg_nontart_clean_machine_preflight_reports_upload_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    package_path = tmp_path / "artifacts" / "omnigent-stock-codex-compat.pkg"
    package_path.parent.mkdir()
    package_path.write_bytes(b"signed-notarized-pkg")
    evidence_path = tmp_path / "release-evidence.json"
    evidence_path.write_text('{"status": "replacement-ready"}\n', encoding="utf-8")
    cleanup_commands: list[str] = []

    def fake_which(name: str, path: str | None = None) -> str | None:
        if path is not None:
            return None
        return {"ssh": "/usr/bin/ssh", "scp": "/usr/bin/scp"}.get(name)

    def fake_verifier(
        *,
        package_path: Path,
        release_evidence_path: Path,
    ) -> subprocess.CompletedProcess[str]:
        del package_path, release_evidence_path
        return subprocess.CompletedProcess(["verify"], 0, stdout="verified\n", stderr="")

    def fake_copy_clean_vm_file(
        *,
        scp_path: str,
        ssh_target: str,
        ssh_port: int,
        ssh_identity: Path | None,
        source: Path,
        remote_destination: str,
        timeout: float,
    ) -> subprocess.CompletedProcess[str]:
        del scp_path, ssh_target, ssh_port, ssh_identity, source, remote_destination, timeout
        return subprocess.CompletedProcess(
            ["scp"],
            1,
            stdout="",
            stderr="subsystem request failed\n",
        )

    def fake_run_clean_vm_ssh_command(
        remote_command: str,
        *,
        ssh_path: str,
        ssh_target: str,
        ssh_port: int,
        ssh_identity: Path | None,
        timeout: float,
    ) -> subprocess.CompletedProcess[str]:
        del ssh_path, ssh_target, ssh_port, ssh_identity, timeout
        if remote_command.startswith("/usr/bin/mktemp"):
            return subprocess.CompletedProcess(
                ["ssh"],
                0,
                stdout="/tmp/omnigent-stock-codex-compat-nontart-preflight.upload\n",
                stderr="",
            )
        if remote_command.startswith("rm -rf "):
            cleanup_commands.append(remote_command)
            return subprocess.CompletedProcess(["ssh"], 0, stdout="", stderr="")
        raise AssertionError(f"unexpected remote command: {remote_command}")

    monkeypatch.setattr(_MOD.shutil, "which", fake_which)
    monkeypatch.setattr(
        _MOD,
        "_run_stock_codex_compat_release_evidence_verifier",
        fake_verifier,
    )
    monkeypatch.setattr(
        _MOD,
        "_wait_for_clean_vm_ssh",
        lambda **_kwargs: subprocess.CompletedProcess(["ssh"], 0, stdout="", stderr=""),
    )
    monkeypatch.setattr(_MOD, "_copy_clean_vm_file", fake_copy_clean_vm_file)
    monkeypatch.setattr(_MOD, "_run_clean_vm_ssh_command", fake_run_clean_vm_ssh_command)

    proof = _MOD.run_stock_codex_compat_pkg_nontart_clean_machine_preflight_proof(
        package_path=package_path,
        release_evidence_path=evidence_path,
        clean_vm_ssh_target="admin@192.0.2.10",
        clean_vm_ssh_identity=None,
        clean_vm_ssh_port=22,
    )

    assert proof.status == "blocked"
    assert proof.remote_status == "upload-failed"
    assert "subsystem request failed" in str(proof.remote_output_preview)
    assert cleanup_commands == [
        "rm -rf /tmp/omnigent-stock-codex-compat-nontart-preflight.upload"
    ]


def test_stock_codex_compat_pkg_nontart_clean_machine_preflight_rejects_unsafe_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    package_path = tmp_path / "artifacts" / "omnigent-stock-codex-compat.pkg"
    package_path.parent.mkdir()
    package_path.write_bytes(b"signed-notarized-pkg")
    evidence_path = tmp_path / "release-evidence.json"
    evidence_path.write_text('{"status": "replacement-ready"}\n', encoding="utf-8")
    package_sha = _MOD.sha256_file(package_path)
    expected_package_path = package_path.resolve()
    uploads: list[tuple[Path, str]] = []
    remote_commands: list[str] = []

    def fake_which(name: str, path: str | None = None) -> str | None:
        if path is not None:
            return None
        return {"ssh": "/usr/bin/ssh", "scp": "/usr/bin/scp"}.get(name)

    def fake_verifier(
        *,
        package_path: Path,
        release_evidence_path: Path,
    ) -> subprocess.CompletedProcess[str]:
        assert package_path == expected_package_path
        assert release_evidence_path == evidence_path.resolve()
        return subprocess.CompletedProcess(["verify"], 0, stdout="verified\n", stderr="")

    def fake_copy_clean_vm_file(
        *,
        scp_path: str,
        ssh_target: str,
        ssh_port: int,
        ssh_identity: Path | None,
        source: Path,
        remote_destination: str,
        timeout: float,
    ) -> subprocess.CompletedProcess[str]:
        del scp_path, ssh_target, ssh_port, ssh_identity, timeout
        uploads.append((source, remote_destination))
        return subprocess.CompletedProcess(["scp"], 0, stdout="", stderr="")

    def fake_run_clean_vm_ssh_command(
        remote_command: str,
        *,
        ssh_path: str,
        ssh_target: str,
        ssh_port: int,
        ssh_identity: Path | None,
        timeout: float,
    ) -> subprocess.CompletedProcess[str]:
        del ssh_path, ssh_target, ssh_port, ssh_identity, timeout
        remote_commands.append(remote_command)
        if remote_command.startswith("/usr/bin/mktemp"):
            return subprocess.CompletedProcess(
                ["ssh"],
                0,
                stdout="/tmp/omnigent-stock-codex-compat-nontart-preflight.test\n",
                stderr="",
            )
        if remote_command.startswith("chmod +x "):
            return subprocess.CompletedProcess(["ssh"], 0, stdout="", stderr="")
        if remote_command.startswith("/bin/bash "):
            prefix = "stock_codex_compat_pkg_nontart_clean_machine_preflight"
            return subprocess.CompletedProcess(
                ["ssh"],
                0,
                stdout=(
                    f"{prefix}_status=inspected\n"
                    f"{prefix}_user=admin\n"
                    f"{prefix}_home=/Users/admin\n"
                    f"{prefix}_macos_version=26.0\n"
                    f"{prefix}_arch=arm64\n"
                    f"{prefix}_uvx_path=/Users/admin/.local/bin/uvx\n"
                    f"{prefix}_uv_path=/Users/admin/.local/bin/uv\n"
                    f"{prefix}_sudo_noninteractive=true\n"
                    f"{prefix}_disposable_marker_present=false\n"
                    f"{prefix}_package_receipt_present=false\n"
                    f"{prefix}_package_payload_present=false\n"
                    f"{prefix}_launcher_present=true\n"
                    f"{prefix}_launcher_manifest_present=false\n"
                    f"{prefix}_adapter_root_present=false\n"
                    f"{prefix}_stock_cache_present=false\n"
                    f"{prefix}_launch_agent_present=false\n"
                    f"{prefix}_remote_package_sha256={package_sha}\n"
                    f"{prefix}_package_sha_match=true\n"
                    f"{prefix}_signature_status=accepted\n"
                    f"{prefix}_staple_status=accepted\n"
                    f"{prefix}_gatekeeper_status=accepted\n"
                ),
                stderr="",
            )
        if remote_command.startswith("rm -rf "):
            return subprocess.CompletedProcess(["ssh"], 0, stdout="", stderr="")
        raise AssertionError(f"unexpected remote command: {remote_command}")

    monkeypatch.setattr(_MOD.shutil, "which", fake_which)
    monkeypatch.setattr(
        _MOD,
        "_run_stock_codex_compat_release_evidence_verifier",
        fake_verifier,
    )
    monkeypatch.setattr(
        _MOD,
        "_wait_for_clean_vm_ssh",
        lambda **_kwargs: subprocess.CompletedProcess(["ssh"], 0, stdout="", stderr=""),
    )
    monkeypatch.setattr(_MOD, "_copy_clean_vm_file", fake_copy_clean_vm_file)
    monkeypatch.setattr(_MOD, "_run_clean_vm_ssh_command", fake_run_clean_vm_ssh_command)

    proof = _MOD.run_stock_codex_compat_pkg_nontart_clean_machine_preflight_proof(
        package_path=package_path,
        release_evidence_path=evidence_path,
        clean_vm_ssh_target="admin@192.0.2.10",
        clean_vm_ssh_identity=None,
        clean_vm_ssh_port=22,
    )

    assert proof.status == "unsafe-target"
    assert proof.remote_status == "unsafe-target"
    assert proof.release_evidence_status == "verified"
    assert proof.launcher_present is True
    assert proof.disposable_marker_present is False
    assert any("not marked disposable" in item for item in proof.missing_prerequisites)
    assert [source.name for source, _destination in uploads] == [
        "omnigent-stock-codex-compat.pkg",
        "nontart_clean_machine_preflight.sh",
    ]
    assert not any("installer -pkg" in command for command in remote_commands)
    assert not any("pkgutil --forget" in command for command in remote_commands)


def test_stock_codex_compat_pkg_nontart_clean_machine_preflight_ready(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    package_path = tmp_path / "artifacts" / "omnigent-stock-codex-compat.pkg"
    package_path.parent.mkdir()
    package_path.write_bytes(b"signed-notarized-pkg")
    evidence_path = tmp_path / "release-evidence.json"
    evidence_path.write_text('{"status": "replacement-ready"}\n', encoding="utf-8")
    identity = tmp_path / "id_ed25519"
    identity.write_text("identity\n", encoding="utf-8")
    package_sha = _MOD.sha256_file(package_path)
    expected_package_path = package_path.resolve()
    remote_commands: list[str] = []

    def fake_which(name: str, path: str | None = None) -> str | None:
        if path is not None:
            return None
        return {"ssh": "/usr/bin/ssh", "scp": "/usr/bin/scp"}.get(name)

    def fake_verifier(
        *,
        package_path: Path,
        release_evidence_path: Path,
    ) -> subprocess.CompletedProcess[str]:
        assert package_path == expected_package_path
        assert release_evidence_path == evidence_path.resolve()
        return subprocess.CompletedProcess(["verify"], 0, stdout="verified\n", stderr="")

    def fake_copy_clean_vm_file(
        *,
        scp_path: str,
        ssh_target: str,
        ssh_port: int,
        ssh_identity: Path | None,
        source: Path,
        remote_destination: str,
        timeout: float,
    ) -> subprocess.CompletedProcess[str]:
        del scp_path, ssh_target, ssh_port, ssh_identity, source, remote_destination, timeout
        return subprocess.CompletedProcess(["scp"], 0, stdout="", stderr="")

    def fake_run_clean_vm_ssh_command(
        remote_command: str,
        *,
        ssh_path: str,
        ssh_target: str,
        ssh_port: int,
        ssh_identity: Path | None,
        timeout: float,
    ) -> subprocess.CompletedProcess[str]:
        del ssh_path, ssh_target, ssh_port, ssh_identity, timeout
        remote_commands.append(remote_command)
        if remote_command.startswith("/usr/bin/mktemp"):
            return subprocess.CompletedProcess(
                ["ssh"],
                0,
                stdout="/tmp/omnigent-stock-codex-compat-nontart-preflight.ready\n",
                stderr="",
            )
        if remote_command.startswith("chmod +x "):
            return subprocess.CompletedProcess(["ssh"], 0, stdout="", stderr="")
        if remote_command.startswith("/bin/bash "):
            prefix = "stock_codex_compat_pkg_nontart_clean_machine_preflight"
            return subprocess.CompletedProcess(
                ["ssh"],
                0,
                stdout=(
                    f"{prefix}_status=inspected\n"
                    f"{prefix}_user=admin\n"
                    f"{prefix}_home=/Users/admin\n"
                    f"{prefix}_macos_version=26.0\n"
                    f"{prefix}_arch=arm64\n"
                    f"{prefix}_uvx_path=/Users/admin/.local/bin/uvx\n"
                    f"{prefix}_uv_path=/Users/admin/.local/bin/uv\n"
                    f"{prefix}_sudo_noninteractive=true\n"
                    f"{prefix}_disposable_marker_present=true\n"
                    f"{prefix}_package_receipt_present=false\n"
                    f"{prefix}_package_payload_present=false\n"
                    f"{prefix}_launcher_present=false\n"
                    f"{prefix}_launcher_manifest_present=false\n"
                    f"{prefix}_adapter_root_present=false\n"
                    f"{prefix}_stock_cache_present=false\n"
                    f"{prefix}_launch_agent_present=false\n"
                    f"{prefix}_remote_package_sha256={package_sha}\n"
                    f"{prefix}_package_sha_match=true\n"
                    f"{prefix}_signature_status=accepted\n"
                    f"{prefix}_staple_status=accepted\n"
                    f"{prefix}_gatekeeper_status=accepted\n"
                ),
                stderr="",
            )
        if remote_command.startswith("rm -rf "):
            return subprocess.CompletedProcess(["ssh"], 0, stdout="", stderr="")
        raise AssertionError(f"unexpected remote command: {remote_command}")

    monkeypatch.setattr(_MOD.shutil, "which", fake_which)
    monkeypatch.setattr(
        _MOD,
        "_run_stock_codex_compat_release_evidence_verifier",
        fake_verifier,
    )
    monkeypatch.setattr(
        _MOD,
        "_wait_for_clean_vm_ssh",
        lambda **_kwargs: subprocess.CompletedProcess(["ssh"], 0, stdout="", stderr=""),
    )
    monkeypatch.setattr(_MOD, "_copy_clean_vm_file", fake_copy_clean_vm_file)
    monkeypatch.setattr(_MOD, "_run_clean_vm_ssh_command", fake_run_clean_vm_ssh_command)

    proof = _MOD.run_stock_codex_compat_pkg_nontart_clean_machine_preflight_proof(
        package_path=package_path,
        release_evidence_path=evidence_path,
        clean_vm_ssh_target="admin@192.0.2.10",
        clean_vm_ssh_identity=identity,
        clean_vm_ssh_port=2222,
    )

    assert proof.status == "replacement-ready"
    assert proof.remote_status == "replacement-ready"
    assert proof.ssh_identity == identity.resolve()
    assert proof.ssh_port == 2222
    assert proof.remote_package_sha256 == package_sha
    assert proof.signature_status == "accepted"
    assert proof.staple_status == "accepted"
    assert proof.gatekeeper_status == "accepted"
    assert any(command.startswith("rm -rf ") for command in remote_commands)

    _MOD.print_stock_codex_compat_pkg_nontart_clean_machine_preflight_proof(proof)
    output = capsys.readouterr().out
    assert (
        "stock_codex_compat_pkg_nontart_clean_machine_preflight_status=replacement-ready"
        in output
    )
    assert (
        "stock_codex_compat_pkg_nontart_clean_machine_preflight_"
        "release_evidence_status=verified"
        in output
    )
    assert "ASSERTION: the signed/notarized package and release evidence are consistent" in output


def test_stock_codex_compat_pkg_clean_vm_remote_acquisition_does_not_upload_stock_binary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    stock_codex = _write_codex_binary(
        tmp_path / "stock" / "codex",
        version="codex-cli 0.142.5",
    )
    package_path = tmp_path / "artifacts" / "omnigent-stock-codex-compat.pkg"
    package_path.parent.mkdir()
    package_path.write_bytes(b"signed-notarized-pkg")
    remote_channel = _MOD._OfficialStockCodexRemoteChannel(
        policy_name="official-openai-github-release",
        cask_token="codex",
        cask_tap="homebrew/cask",
        cask_homepage="https://github.com/openai/codex",
        cask_version="0.143.0",
        cask_url=(
            "https://github.com/openai/codex/releases/download/"
            "rust-v0.143.0/codex-aarch64-apple-darwin.tar.gz"
        ),
        cask_sha256="c" * 64,
        selected_version="codex-cli 0.143.0",
        archive_executable="codex-aarch64-apple-darwin",
    )
    uploads: list[tuple[Path, str]] = []
    uploaded_channel: dict[str, object] = {}
    remote_commands: list[str] = []

    def fake_which(name: str, path: str | None = None) -> str | None:
        if path is not None:
            return None
        return {
            "ssh": "/usr/bin/ssh",
            "scp": "/usr/bin/scp",
            "tart": "/usr/local/bin/tart",
        }.get(name)

    def fake_copy_clean_vm_file(
        *,
        scp_path: str,
        ssh_target: str,
        ssh_port: int,
        ssh_identity: Path | None,
        source: Path,
        remote_destination: str,
        timeout: float,
    ) -> subprocess.CompletedProcess[str]:
        del scp_path, ssh_target, ssh_port, ssh_identity, timeout
        uploads.append((source, remote_destination))
        if source.name == "channel.json":
            uploaded_channel.update(json.loads(source.read_text(encoding="utf-8")))
        return subprocess.CompletedProcess(["scp"], 0, stdout="", stderr="")

    def fake_run_clean_vm_ssh_command(
        remote_command: str,
        *,
        ssh_path: str,
        ssh_target: str,
        ssh_port: int,
        ssh_identity: Path | None,
        timeout: float,
    ) -> subprocess.CompletedProcess[str]:
        del ssh_path, ssh_target, ssh_port, ssh_identity, timeout
        remote_commands.append(remote_command)
        if remote_command.startswith("/usr/bin/mktemp"):
            return subprocess.CompletedProcess(
                ["ssh"],
                0,
                stdout="/tmp/omnigent-stock-codex-compat-clean-vm.test\n",
                stderr="",
            )
        if remote_command.startswith("chmod "):
            return subprocess.CompletedProcess(["ssh"], 0, stdout="", stderr="")
        if remote_command.startswith("/bin/bash "):
            return subprocess.CompletedProcess(
                ["ssh"],
                0,
                stdout=(
                    "stock_codex_compat_pkg_clean_vm_remote_acquisition_status="
                    "replacement-ready\n"
                ),
                stderr="",
            )
        if remote_command.startswith("rm -rf "):
            return subprocess.CompletedProcess(["ssh"], 0, stdout="", stderr="")
        raise AssertionError(f"unexpected remote command: {remote_command}")

    monkeypatch.setattr(_MOD.shutil, "which", fake_which)
    monkeypatch.setattr(
        _MOD,
        "_official_stock_codex_remote_channel",
        lambda: remote_channel,
    )
    monkeypatch.setattr(
        _MOD,
        "_wait_for_clean_vm_ssh",
        lambda **_kwargs: subprocess.CompletedProcess(["ssh"], 0, stdout="", stderr=""),
    )
    monkeypatch.setattr(_MOD, "_copy_clean_vm_file", fake_copy_clean_vm_file)
    monkeypatch.setattr(_MOD, "_run_clean_vm_ssh_command", fake_run_clean_vm_ssh_command)

    proof = _MOD.run_stock_codex_compat_pkg_clean_vm_remote_acquisition_proof(
        stock_codex,
        package_path=package_path,
        clean_vm_ssh_target="admin@192.0.2.10",
        clean_vm_tart_name=None,
        clean_vm_ssh_identity=None,
        clean_vm_ssh_user=None,
        clean_vm_ssh_port=22,
        clean_vm_start_tart=False,
    )

    uploaded_sources = [source for source, _destination in uploads]
    assert proof.status == "replacement-ready"
    assert proof.proof_variant == "official-remote-channel-acquisition"
    assert proof.cask_version == "0.143.0"
    assert proof.cask_url == remote_channel.cask_url
    assert proof.host_stock_codex_uploaded is False
    assert stock_codex.resolve() not in [source.resolve() for source in uploaded_sources]
    assert [source.name for source in uploaded_sources] == [
        "omnigent-stock-codex-compat.pkg",
        "channel.json",
        "clean_vm_proof.sh",
    ]
    artifacts = uploaded_channel["artifacts"]
    assert isinstance(artifacts, list)
    assert artifacts[0]["url"] == remote_channel.cask_url
    assert artifacts[0]["sha256"] == remote_channel.cask_sha256
    assert "path" not in artifacts[0]
    bash_commands = [command for command in remote_commands if command.startswith("/bin/bash ")]
    assert len(bash_commands) == 1
    assert "codex-aarch64-apple-darwin.tar.gz" in bash_commands[0]
    assert str(stock_codex) not in bash_commands[0]


def test_stock_codex_compat_pkg_clean_vm_start_tart_preflights_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    stock_codex = _write_codex_binary(
        tmp_path / "stock" / "codex",
        version="codex-cli 0.142.5",
    )
    package_path = tmp_path / "artifacts" / "omnigent-stock-codex-compat.pkg"
    package_path.parent.mkdir()
    package_path.write_bytes(b"signed-notarized-pkg")
    remote_channel = _MOD._OfficialStockCodexRemoteChannel(
        policy_name="official-openai-github-release",
        cask_token="codex",
        cask_tap="github-releases/latest",
        cask_homepage="https://github.com/openai/codex",
        cask_version="0.143.0",
        cask_url=(
            "https://github.com/openai/codex/releases/download/"
            "rust-v0.143.0/codex-aarch64-apple-darwin.tar.gz"
        ),
        cask_sha256="c" * 64,
        selected_version="codex-cli 0.143.0",
        archive_executable="codex-aarch64-apple-darwin",
    )
    uploads: list[tuple[Path, str]] = []
    remote_commands: list[str] = []

    def fake_which(name: str, path: str | None = None) -> str | None:
        if path is not None:
            return None
        return {
            "ssh": "/usr/bin/ssh",
            "scp": "/usr/bin/scp",
            "tart": "/usr/bin/true",
        }.get(name)

    def fake_copy_clean_vm_file(
        *,
        scp_path: str,
        ssh_target: str,
        ssh_port: int,
        ssh_identity: Path | None,
        source: Path,
        remote_destination: str,
        timeout: float,
    ) -> subprocess.CompletedProcess[str]:
        del scp_path, ssh_target, ssh_port, ssh_identity, timeout
        uploads.append((source, remote_destination))
        return subprocess.CompletedProcess(["scp"], 0, stdout="", stderr="")

    def fake_run_clean_vm_ssh_command(
        remote_command: str,
        *,
        ssh_path: str,
        ssh_target: str,
        ssh_port: int,
        ssh_identity: Path | None,
        timeout: float,
    ) -> subprocess.CompletedProcess[str]:
        del ssh_path, ssh_target, ssh_port, ssh_identity, timeout
        remote_commands.append(remote_command)
        if "stock_codex_compat_pkg_clean_vm_preflight_cleanup=completed" in remote_command:
            return subprocess.CompletedProcess(
                ["ssh"],
                0,
                stdout="stock_codex_compat_pkg_clean_vm_preflight_cleanup=completed\n",
                stderr="",
            )
        if remote_command.startswith("/usr/bin/mktemp"):
            return subprocess.CompletedProcess(
                ["ssh"],
                0,
                stdout="/tmp/omnigent-stock-codex-compat-clean-vm.test\n",
                stderr="",
            )
        if remote_command.startswith("chmod "):
            return subprocess.CompletedProcess(["ssh"], 0, stdout="", stderr="")
        if remote_command.startswith("/bin/bash "):
            return subprocess.CompletedProcess(
                ["ssh"],
                0,
                stdout=(
                    "stock_codex_compat_pkg_clean_vm_remote_acquisition_status="
                    "replacement-ready\n"
                ),
                stderr="",
            )
        if remote_command.startswith("rm -rf "):
            return subprocess.CompletedProcess(["ssh"], 0, stdout="", stderr="")
        raise AssertionError(f"unexpected remote command: {remote_command}")

    monkeypatch.setattr(_MOD.shutil, "which", fake_which)
    monkeypatch.setattr(
        _MOD,
        "_official_stock_codex_remote_channel",
        lambda: remote_channel,
    )
    monkeypatch.setattr(
        _MOD,
        "_resolve_clean_vm_ssh_target",
        lambda **_kwargs: ("admin@192.0.2.10", "192.0.2.10", True, ()),
    )
    monkeypatch.setattr(
        _MOD,
        "_wait_for_clean_vm_ssh",
        lambda **_kwargs: subprocess.CompletedProcess(["ssh"], 0, stdout="", stderr=""),
    )
    monkeypatch.setattr(_MOD, "_copy_clean_vm_file", fake_copy_clean_vm_file)
    monkeypatch.setattr(_MOD, "_run_clean_vm_ssh_command", fake_run_clean_vm_ssh_command)

    proof = _MOD.run_stock_codex_compat_pkg_clean_vm_remote_acquisition_proof(
        stock_codex,
        package_path=package_path,
        clean_vm_ssh_target=None,
        clean_vm_tart_name="omnigent-clean",
        clean_vm_ssh_identity=None,
        clean_vm_ssh_user="admin",
        clean_vm_ssh_port=22,
        clean_vm_start_tart=True,
    )

    assert proof.status == "replacement-ready"
    assert proof.tart_started is True
    assert proof.tart_stopped is True
    assert proof.tart_ip == "192.0.2.10"
    assert "stock_codex_compat_pkg_clean_vm_preflight_cleanup=completed" in (
        remote_commands[0]
    )
    assert remote_commands[1].startswith("/usr/bin/mktemp")
    assert [source.name for source, _destination in uploads] == [
        "omnigent-stock-codex-compat.pkg",
        "channel.json",
        "clean_vm_proof.sh",
    ]


def test_stock_codex_compat_pkg_clean_vm_release_runs_steps_in_order(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    stock_codex = _write_codex_binary(
        tmp_path / "stock" / "codex",
        version="codex-cli 0.142.5",
    )
    package_path = tmp_path / "artifacts" / "omnigent-stock-codex-compat.pkg"
    package_path.parent.mkdir()
    package_path.write_bytes(b"signed-notarized-pkg")
    auth_path = tmp_path / "auth" / "auth.json"
    auth_path.parent.mkdir()
    auth_path.write_text('{"tokens": {"refresh_token": "redacted-fixture"}}\n')
    identity = tmp_path / "id_ed25519"
    identity.write_text("identity\n")
    remote_channel = _MOD._OfficialStockCodexRemoteChannel(
        policy_name="official-openai-github-release",
        cask_token="codex",
        cask_tap="github-releases/latest",
        cask_homepage="https://github.com/openai/codex",
        cask_version="0.143.0",
        cask_url=(
            "https://github.com/openai/codex/releases/download/"
            "rust-v0.143.0/codex-aarch64-apple-darwin.tar.gz"
        ),
        cask_sha256="c" * 64,
        selected_version="codex-cli 0.143.0",
        archive_executable="codex-aarch64-apple-darwin",
    )
    calls: list[dict[str, object]] = []

    def fake_which(name: str, path: str | None = None) -> str | None:
        if path is not None:
            return None
        return {
            "ssh": "/usr/bin/ssh",
            "scp": "/usr/bin/scp",
            "tart": "/usr/local/bin/tart",
        }.get(name)

    def fake_clean_vm_proof(
        stock_codex_path: Path,
        *,
        package_path: Path | None,
        clean_vm_ssh_target: str | None,
        clean_vm_tart_name: str | None,
        clean_vm_ssh_identity: Path | None,
        clean_vm_ssh_user: str | None,
        clean_vm_ssh_port: int,
        clean_vm_start_tart: bool,
        remote_channel: object | None = None,
        live_auth_path: Path | None = None,
        live_auth_source: str | None = None,
        update_agent: bool = False,
        auth_onboarding: bool = False,
        auth_persistence: bool = False,
        auth_persistence_auth_path: Path | None = None,
        auth_persistence_auth_source: str | None = None,
    ) -> object:
        if auth_onboarding:
            step_name = "auth-onboarding"
        elif auth_persistence:
            step_name = "auth-persistence"
        elif update_agent:
            step_name = "update-agent"
        elif live_auth_path is not None:
            step_name = "live"
        else:
            step_name = "remote-acquisition"
        calls.append(
            {
                "step": step_name,
                "package_path": package_path,
                "clean_vm_start_tart": clean_vm_start_tart,
                "remote_channel": remote_channel,
                "live_auth_path": live_auth_path,
                "live_auth_source": live_auth_source,
                "auth_persistence_auth_path": auth_persistence_auth_path,
                "auth_persistence_auth_source": auth_persistence_auth_source,
            }
        )
        return _MOD.StockCodexCompatPkgCleanVmProof(
            status="replacement-ready",
            missing_prerequisites=(),
            tool_paths={"ssh": "/usr/bin/ssh", "scp": "/usr/bin/scp"},
            stock_codex_path=stock_codex_path,
            stock_codex_version="codex-cli 0.142.5",
            stock_codex_sha256=_MOD.sha256_file(stock_codex_path),
            package_path=package_path,
            package_sha256=_MOD.sha256_file(package_path),
            tart_name=clean_vm_tart_name,
            ssh_target=clean_vm_ssh_target,
            ssh_identity=clean_vm_ssh_identity,
            ssh_user=clean_vm_ssh_user,
            ssh_port=clean_vm_ssh_port,
            tart_ip="192.0.2.10",
            remote_work_dir=f"/tmp/{step_name}",
            remote_status="replacement-ready",
            remote_output_preview=step_name,
            tart_started=clean_vm_start_tart,
            tart_stopped=clean_vm_start_tart,
            proof_variant=f"official-remote-channel-{step_name}",
            cask_version=remote_channel.cask_version,
            cask_url=remote_channel.cask_url,
            cask_sha256=remote_channel.cask_sha256,
            channel_policy=remote_channel.policy_name,
            host_stock_codex_uploaded=False,
            live_auth_path=live_auth_path,
            live_auth_source=live_auth_source,
            live_auth_uploaded=live_auth_path is not None,
            live_selected_command_path=(
                Path("/Users/admin/.local/bin/omnigent-stock-codex-compat")
                if step_name == "live"
                else None
            ),
            live_selected_command_version=(
                remote_channel.selected_version if step_name == "live" else None
            ),
            live_thread_id="019f-release-live" if step_name == "live" else None,
            update_agent_requested=update_agent,
            update_agent_scheduled_action=(
                "up-to-date" if step_name == "update-agent" else None
            ),
            update_agent_selected_codex_path=(
                Path("/Users/admin/.local/omnigent/codex-stock/0.143.0/codex")
                if step_name == "update-agent"
                else None
            ),
            update_agent_selected_codex_version=(
                remote_channel.selected_version
                if step_name == "update-agent"
                else None
            ),
            auth_onboarding_requested=auth_onboarding,
            auth_onboarding_launcher_path=(
                Path("/Users/admin/.local/bin/omnigent-stock-codex-compat")
                if step_name == "auth-onboarding"
                else None
            ),
            auth_onboarding_selected_command_version=(
                remote_channel.selected_version
                if step_name == "auth-onboarding"
                else None
            ),
            auth_onboarding_auth_uploaded=False if auth_onboarding else None,
            auth_persistence_requested=auth_persistence,
            auth_persistence_auth_source=auth_persistence_auth_source,
            auth_persistence_auth_uploaded=auth_persistence,
            auth_persistence_selected_command_path=(
                Path("/Users/admin/.local/bin/omnigent-stock-codex-compat")
                if step_name == "auth-persistence"
                else None
            ),
            auth_persistence_selected_command_version=(
                remote_channel.selected_version
                if step_name == "auth-persistence"
                else None
            ),
            auth_persistence_thread_id=(
                "019f-release-auth-persistence"
                if step_name == "auth-persistence"
                else None
            ),
    )

    monkeypatch.setattr(_MOD.shutil, "which", fake_which)
    monkeypatch.setattr(_MOD, "_official_stock_codex_remote_channel", lambda: remote_channel)
    monkeypatch.setattr(
        _MOD,
        "_stock_replacement_auth_source",
        lambda: (auth_path, "stock-default-home"),
    )
    monkeypatch.setattr(
        _MOD.codex_native,
        "_codex_auth_json_has_available_credential",
        lambda _path: True,
    )
    monkeypatch.setattr(
        _MOD,
        "run_stock_codex_compat_pkg_clean_vm_proof",
        fake_clean_vm_proof,
    )

    proof = _MOD.run_stock_codex_compat_pkg_clean_vm_release_proof(
        stock_codex,
        package_path=package_path,
        clean_vm_ssh_target=None,
        clean_vm_tart_name="omnigent-clean",
        clean_vm_ssh_identity=identity,
        clean_vm_ssh_user="admin",
        clean_vm_ssh_port=22,
        clean_vm_start_tart=True,
    )

    assert proof.status == "replacement-ready"
    assert proof.blocked_step is None
    assert proof.step_order == _MOD.CLEAN_VM_RELEASE_STEP_ORDER
    assert proof.step_statuses == {
        "remote-acquisition": "replacement-ready",
        "auth-onboarding": "replacement-ready",
        "auth-persistence": "replacement-ready",
        "update-agent": "replacement-ready",
        "live": "replacement-ready",
    }
    assert proof.package_path == package_path.resolve()
    assert proof.package_sha256 == _MOD.sha256_file(package_path)
    assert proof.auth_path == auth_path.resolve()
    assert proof.auth_source == "stock-default-home"
    assert proof.cask_version == "0.143.0"
    assert proof.tart_started_count == 5
    assert proof.tart_stopped_count == 5
    assert proof.host_stock_codex_uploaded_any is False
    assert [call["step"] for call in calls] == list(_MOD.CLEAN_VM_RELEASE_STEP_ORDER)
    assert all(call["package_path"] == package_path.resolve() for call in calls)
    assert all(call["clean_vm_start_tart"] is True for call in calls)
    assert all(call["remote_channel"] is remote_channel for call in calls)
    assert calls[2]["auth_persistence_auth_path"] == auth_path.resolve()
    assert calls[2]["auth_persistence_auth_source"] == "stock-default-home"
    assert calls[4]["live_auth_path"] == auth_path.resolve()
    assert calls[4]["live_auth_source"] == "stock-default-home"

    _MOD.print_stock_codex_compat_pkg_clean_vm_release_proof(proof)
    output = capsys.readouterr().out
    assert "stock_codex_compat_pkg_clean_vm_release_status=replacement-ready" in output
    assert '"live": "replacement-ready"' in output
    assert '"selectedCommandVersion": "codex-cli 0.143.0"' in output
    assert '"selectedCodexVersion": "codex-cli 0.143.0"' in output
    assert "stock_codex_compat_pkg_clean_vm_release_tart_stopped_count=5" in output


def test_stock_codex_compat_pkg_clean_vm_release_fails_fast_on_blocked_step(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    stock_codex = _write_codex_binary(tmp_path / "stock" / "codex")
    package_path = tmp_path / "artifacts" / "omnigent-stock-codex-compat.pkg"
    package_path.parent.mkdir()
    package_path.write_bytes(b"signed-notarized-pkg")
    auth_path = tmp_path / "auth" / "auth.json"
    auth_path.parent.mkdir()
    auth_path.write_text('{"tokens": {"refresh_token": "redacted-fixture"}}\n')
    remote_channel = _MOD._OfficialStockCodexRemoteChannel(
        policy_name="official-openai-github-release",
        cask_token="codex",
        cask_tap="github-releases/latest",
        cask_homepage="https://github.com/openai/codex",
        cask_version="0.143.0",
        cask_url=(
            "https://github.com/openai/codex/releases/download/"
            "rust-v0.143.0/codex-aarch64-apple-darwin.tar.gz"
        ),
        cask_sha256="c" * 64,
        selected_version="codex-cli 0.143.0",
        archive_executable="codex-aarch64-apple-darwin",
    )
    calls: list[str] = []

    def fake_clean_vm_proof(
        stock_codex_path: Path,
        *,
        package_path: Path | None,
        clean_vm_ssh_target: str | None,
        clean_vm_tart_name: str | None,
        clean_vm_ssh_identity: Path | None,
        clean_vm_ssh_user: str | None,
        clean_vm_ssh_port: int,
        clean_vm_start_tart: bool,
        remote_channel: object | None = None,
        auth_onboarding: bool = False,
        **_kwargs: object,
    ) -> object:
        del remote_channel
        step_name = "auth-onboarding" if auth_onboarding else "remote-acquisition"
        calls.append(step_name)
        status = "blocked" if auth_onboarding else "replacement-ready"
        missing = (
            ("clean VM auth-onboarding proof omitted parseable evidence",)
            if auth_onboarding
            else ()
        )
        return _MOD.StockCodexCompatPkgCleanVmProof(
            status=status,
            missing_prerequisites=missing,
            tool_paths={"ssh": "/usr/bin/ssh", "scp": "/usr/bin/scp"},
            stock_codex_path=stock_codex_path,
            stock_codex_version="codex-cli 0.142.2",
            stock_codex_sha256=_MOD.sha256_file(stock_codex_path),
            package_path=package_path,
            package_sha256=_MOD.sha256_file(package_path),
            tart_name=clean_vm_tart_name,
            ssh_target=clean_vm_ssh_target,
            ssh_identity=clean_vm_ssh_identity,
            ssh_user=clean_vm_ssh_user,
            ssh_port=clean_vm_ssh_port,
            tart_ip="192.0.2.10",
            remote_work_dir=f"/tmp/{step_name}",
            remote_status=status,
            remote_output_preview=step_name,
            tart_started=clean_vm_start_tart,
            tart_stopped=clean_vm_start_tart,
            proof_variant=f"official-remote-channel-{step_name}",
            host_stock_codex_uploaded=False,
        )

    monkeypatch.setattr(
        _MOD.shutil,
        "which",
        lambda name, path=None: f"/usr/bin/{name}" if path is None else None,
    )
    monkeypatch.setattr(_MOD, "_official_stock_codex_remote_channel", lambda: remote_channel)
    monkeypatch.setattr(
        _MOD,
        "_stock_replacement_auth_source",
        lambda: (auth_path, "stock-default-home"),
    )
    monkeypatch.setattr(
        _MOD.codex_native,
        "_codex_auth_json_has_available_credential",
        lambda _path: True,
    )
    monkeypatch.setattr(
        _MOD,
        "run_stock_codex_compat_pkg_clean_vm_proof",
        fake_clean_vm_proof,
    )

    proof = _MOD.run_stock_codex_compat_pkg_clean_vm_release_proof(
        stock_codex,
        package_path=package_path,
        clean_vm_ssh_target="admin@192.0.2.10",
        clean_vm_tart_name=None,
        clean_vm_ssh_identity=None,
        clean_vm_ssh_user=None,
        clean_vm_ssh_port=22,
        clean_vm_start_tart=False,
    )

    assert proof.status == "blocked"
    assert proof.blocked_step == "auth-onboarding"
    assert calls == ["remote-acquisition", "auth-onboarding"]
    assert "auth-persistence" not in proof.step_statuses
    assert proof.step_statuses == {
        "remote-acquisition": "replacement-ready",
        "auth-onboarding": "blocked",
    }
    assert "clean VM release step failed: auth-onboarding" in proof.missing_prerequisites
    assert proof.step_missing_prerequisites == {
        "auth-onboarding": (
            "clean VM auth-onboarding proof omitted parseable evidence",
        )
    }


def test_stock_codex_compat_pkg_clean_vm_release_blocks_if_tart_step_does_not_stop(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    stock_codex = _write_codex_binary(tmp_path / "stock" / "codex")
    package_path = tmp_path / "artifacts" / "omnigent-stock-codex-compat.pkg"
    package_path.parent.mkdir()
    package_path.write_bytes(b"signed-notarized-pkg")
    auth_path = tmp_path / "auth" / "auth.json"
    auth_path.parent.mkdir()
    auth_path.write_text('{"tokens": {"refresh_token": "redacted-fixture"}}\n')
    remote_channel = _MOD._OfficialStockCodexRemoteChannel(
        policy_name="official-openai-github-release",
        cask_token="codex",
        cask_tap="github-releases/latest",
        cask_homepage="https://github.com/openai/codex",
        cask_version="0.143.0",
        cask_url=(
            "https://github.com/openai/codex/releases/download/"
            "rust-v0.143.0/codex-aarch64-apple-darwin.tar.gz"
        ),
        cask_sha256="c" * 64,
        selected_version="codex-cli 0.143.0",
        archive_executable="codex-aarch64-apple-darwin",
    )
    calls = 0

    def fake_clean_vm_proof(
        stock_codex_path: Path,
        *,
        package_path: Path | None,
        clean_vm_tart_name: str | None,
        clean_vm_ssh_port: int,
        clean_vm_start_tart: bool,
        **_kwargs: object,
    ) -> object:
        nonlocal calls
        calls += 1
        return _MOD.StockCodexCompatPkgCleanVmProof(
            status="replacement-ready",
            missing_prerequisites=(),
            tool_paths={"ssh": "/usr/bin/ssh", "scp": "/usr/bin/scp"},
            stock_codex_path=stock_codex_path,
            stock_codex_version="codex-cli 0.142.2",
            stock_codex_sha256=_MOD.sha256_file(stock_codex_path),
            package_path=package_path,
            package_sha256=_MOD.sha256_file(package_path),
            tart_name=clean_vm_tart_name,
            ssh_target=None,
            ssh_identity=None,
            ssh_user="admin",
            ssh_port=clean_vm_ssh_port,
            tart_ip="192.0.2.10",
            remote_work_dir="/tmp/remote-acquisition",
            remote_status="replacement-ready",
            remote_output_preview="remote-acquisition",
            tart_started=clean_vm_start_tart,
            tart_stopped=False,
            proof_variant="official-remote-channel-acquisition",
            host_stock_codex_uploaded=False,
        )

    monkeypatch.setattr(
        _MOD.shutil,
        "which",
        lambda name, path=None: f"/usr/bin/{name}" if path is None else None,
    )
    monkeypatch.setattr(_MOD, "_official_stock_codex_remote_channel", lambda: remote_channel)
    monkeypatch.setattr(
        _MOD,
        "_stock_replacement_auth_source",
        lambda: (auth_path, "stock-default-home"),
    )
    monkeypatch.setattr(
        _MOD.codex_native,
        "_codex_auth_json_has_available_credential",
        lambda _path: True,
    )
    monkeypatch.setattr(
        _MOD,
        "run_stock_codex_compat_pkg_clean_vm_proof",
        fake_clean_vm_proof,
    )

    proof = _MOD.run_stock_codex_compat_pkg_clean_vm_release_proof(
        stock_codex,
        package_path=package_path,
        clean_vm_ssh_target=None,
        clean_vm_tart_name="omnigent-clean",
        clean_vm_ssh_identity=None,
        clean_vm_ssh_user="admin",
        clean_vm_ssh_port=22,
        clean_vm_start_tart=True,
    )

    assert proof.status == "blocked"
    assert proof.blocked_step == "remote-acquisition"
    assert calls == 1
    assert proof.tart_started_count == 1
    assert proof.tart_stopped_count == 0
    assert "clean VM release step did not stop Tart VM: remote-acquisition" in (
        proof.missing_prerequisites
    )


def test_stock_codex_compat_pkg_clean_vm_release_blocks_if_tart_step_does_not_start(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    stock_codex = _write_codex_binary(tmp_path / "stock" / "codex")
    package_path = tmp_path / "artifacts" / "omnigent-stock-codex-compat.pkg"
    package_path.parent.mkdir()
    package_path.write_bytes(b"signed-notarized-pkg")
    auth_path = tmp_path / "auth" / "auth.json"
    auth_path.parent.mkdir()
    auth_path.write_text('{"tokens": {"refresh_token": "redacted-fixture"}}\n')
    remote_channel = _MOD._OfficialStockCodexRemoteChannel(
        policy_name="official-openai-github-release",
        cask_token="codex",
        cask_tap="github-releases/latest",
        cask_homepage="https://github.com/openai/codex",
        cask_version="0.143.0",
        cask_url=(
            "https://github.com/openai/codex/releases/download/"
            "rust-v0.143.0/codex-aarch64-apple-darwin.tar.gz"
        ),
        cask_sha256="c" * 64,
        selected_version="codex-cli 0.143.0",
        archive_executable="codex-aarch64-apple-darwin",
    )
    calls = 0

    def fake_clean_vm_proof(
        stock_codex_path: Path,
        *,
        package_path: Path | None,
        clean_vm_tart_name: str | None,
        clean_vm_ssh_port: int,
        **_kwargs: object,
    ) -> object:
        nonlocal calls
        calls += 1
        return _MOD.StockCodexCompatPkgCleanVmProof(
            status="replacement-ready",
            missing_prerequisites=(),
            tool_paths={"ssh": "/usr/bin/ssh", "scp": "/usr/bin/scp"},
            stock_codex_path=stock_codex_path,
            stock_codex_version="codex-cli 0.142.2",
            stock_codex_sha256=_MOD.sha256_file(stock_codex_path),
            package_path=package_path,
            package_sha256=_MOD.sha256_file(package_path),
            tart_name=clean_vm_tart_name,
            ssh_target=None,
            ssh_identity=None,
            ssh_user="admin",
            ssh_port=clean_vm_ssh_port,
            tart_ip=None,
            remote_work_dir="/tmp/remote-acquisition",
            remote_status="replacement-ready",
            remote_output_preview="remote-acquisition",
            tart_started=False,
            tart_stopped=False,
            proof_variant="official-remote-channel-acquisition",
            host_stock_codex_uploaded=False,
        )

    monkeypatch.setattr(
        _MOD.shutil,
        "which",
        lambda name, path=None: f"/usr/bin/{name}" if path is None else None,
    )
    monkeypatch.setattr(_MOD, "_official_stock_codex_remote_channel", lambda: remote_channel)
    monkeypatch.setattr(
        _MOD,
        "_stock_replacement_auth_source",
        lambda: (auth_path, "stock-default-home"),
    )
    monkeypatch.setattr(
        _MOD.codex_native,
        "_codex_auth_json_has_available_credential",
        lambda _path: True,
    )
    monkeypatch.setattr(
        _MOD,
        "run_stock_codex_compat_pkg_clean_vm_proof",
        fake_clean_vm_proof,
    )

    proof = _MOD.run_stock_codex_compat_pkg_clean_vm_release_proof(
        stock_codex,
        package_path=package_path,
        clean_vm_ssh_target=None,
        clean_vm_tart_name="omnigent-clean",
        clean_vm_ssh_identity=None,
        clean_vm_ssh_user="admin",
        clean_vm_ssh_port=22,
        clean_vm_start_tart=True,
    )

    assert proof.status == "blocked"
    assert proof.blocked_step == "remote-acquisition"
    assert calls == 1
    assert proof.tart_started_count == 0
    assert proof.tart_stopped_count == 0
    assert "clean VM release step did not start Tart VM: remote-acquisition" in (
        proof.missing_prerequisites
    )


def test_stock_codex_compat_pkg_clean_vm_update_agent_loads_launchd_without_stock_binary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    stock_codex = _write_codex_binary(
        tmp_path / "stock" / "codex",
        version="codex-cli 0.142.5",
    )
    package_path = tmp_path / "artifacts" / "omnigent-stock-codex-compat.pkg"
    package_path.parent.mkdir()
    package_path.write_bytes(b"signed-notarized-pkg")
    remote_channel = _MOD._OfficialStockCodexRemoteChannel(
        policy_name="official-openai-github-release",
        cask_token="codex",
        cask_tap="homebrew/cask",
        cask_homepage="https://github.com/openai/codex",
        cask_version="0.143.0",
        cask_url=(
            "https://github.com/openai/codex/releases/download/"
            "rust-v0.143.0/codex-aarch64-apple-darwin.tar.gz"
        ),
        cask_sha256="e" * 64,
        selected_version="codex-cli 0.143.0",
        archive_executable="codex-aarch64-apple-darwin",
    )
    uploads: list[tuple[Path, str]] = []
    uploaded_channel: dict[str, object] = {}
    remote_commands: list[str] = []

    def fake_which(name: str, path: str | None = None) -> str | None:
        if path is not None:
            return None
        return {
            "ssh": "/usr/bin/ssh",
            "scp": "/usr/bin/scp",
            "tart": "/usr/local/bin/tart",
        }.get(name)

    def fake_copy_clean_vm_file(
        *,
        scp_path: str,
        ssh_target: str,
        ssh_port: int,
        ssh_identity: Path | None,
        source: Path,
        remote_destination: str,
        timeout: float,
    ) -> subprocess.CompletedProcess[str]:
        del scp_path, ssh_target, ssh_port, ssh_identity, timeout
        uploads.append((source, remote_destination))
        if source.name == "channel.json":
            uploaded_channel.update(json.loads(source.read_text(encoding="utf-8")))
        return subprocess.CompletedProcess(["scp"], 0, stdout="", stderr="")

    def fake_run_clean_vm_ssh_command(
        remote_command: str,
        *,
        ssh_path: str,
        ssh_target: str,
        ssh_port: int,
        ssh_identity: Path | None,
        timeout: float,
    ) -> subprocess.CompletedProcess[str]:
        del ssh_path, ssh_target, ssh_port, ssh_identity, timeout
        remote_commands.append(remote_command)
        if remote_command.startswith("/usr/bin/mktemp"):
            return subprocess.CompletedProcess(
                ["ssh"],
                0,
                stdout="/tmp/omnigent-stock-codex-compat-clean-vm-update-agent.test\n",
                stderr="",
            )
        if remote_command.startswith("chmod "):
            return subprocess.CompletedProcess(["ssh"], 0, stdout="", stderr="")
        if remote_command.startswith("/bin/bash "):
            update_agent_evidence = {
                "directAction": "up-to-date",
                "hostCacheReferenced": False,
                "kind": "omnigent-clean-vm-update-agent-evidence",
                "launchAgentLabel": "ai.omnigent.stock-codex-compat.update",
                "launchAgentPath": (
                    "/Users/admin/Library/LaunchAgents/"
                    "ai.omnigent.stock-codex-compat.update.plist"
                ),
                "launchDomain": "user/501",
                "launchctlBootout": "unloaded",
                "launchctlBootstrap": "loaded",
                "launchctlKickstart": "completed",
                "scheduledAction": "up-to-date",
                "selectedCodexPath": "/Users/admin/.local/omnigent/codex-stock/0.143.0/codex",
                "selectedCodexVersion": "codex-cli 0.143.0",
            }
            return subprocess.CompletedProcess(
                ["ssh"],
                0,
                stdout=(
                    json.dumps(update_agent_evidence, sort_keys=True)
                    + "\n"
                    "stock_codex_compat_pkg_clean_vm_update_agent_status="
                    "replacement-ready\n"
                ),
                stderr="",
            )
        if remote_command.startswith("rm -rf "):
            return subprocess.CompletedProcess(["ssh"], 0, stdout="", stderr="")
        raise AssertionError(f"unexpected remote command: {remote_command}")

    monkeypatch.setattr(_MOD.shutil, "which", fake_which)
    monkeypatch.setattr(
        _MOD,
        "_official_stock_codex_remote_channel",
        lambda: remote_channel,
    )
    monkeypatch.setattr(
        _MOD,
        "_wait_for_clean_vm_ssh",
        lambda **_kwargs: subprocess.CompletedProcess(["ssh"], 0, stdout="", stderr=""),
    )
    monkeypatch.setattr(_MOD, "_copy_clean_vm_file", fake_copy_clean_vm_file)
    monkeypatch.setattr(_MOD, "_run_clean_vm_ssh_command", fake_run_clean_vm_ssh_command)

    proof = _MOD.run_stock_codex_compat_pkg_clean_vm_update_agent_proof(
        stock_codex,
        package_path=package_path,
        clean_vm_ssh_target="admin@192.0.2.10",
        clean_vm_tart_name=None,
        clean_vm_ssh_identity=None,
        clean_vm_ssh_user=None,
        clean_vm_ssh_port=22,
        clean_vm_start_tart=False,
    )

    uploaded_sources = [source for source, _destination in uploads]
    assert proof.status == "replacement-ready"
    assert proof.proof_variant == "official-remote-channel-update-agent"
    assert proof.update_agent_requested is True
    assert proof.host_stock_codex_uploaded is False
    assert proof.update_agent_launch_agent_label == "ai.omnigent.stock-codex-compat.update"
    assert proof.update_agent_launch_domain == "user/501"
    assert proof.update_agent_launchctl_bootstrap == "loaded"
    assert proof.update_agent_launchctl_kickstart == "completed"
    assert proof.update_agent_launchctl_bootout == "unloaded"
    assert proof.update_agent_direct_action == "up-to-date"
    assert proof.update_agent_scheduled_action == "up-to-date"
    assert proof.update_agent_selected_codex_path == Path(
        "/Users/admin/.local/omnigent/codex-stock/0.143.0/codex"
    )
    assert proof.update_agent_selected_codex_version == "codex-cli 0.143.0"
    assert proof.update_agent_host_cache_referenced is False
    assert stock_codex.resolve() not in [source.resolve() for source in uploaded_sources]
    assert [source.name for source in uploaded_sources] == [
        "omnigent-stock-codex-compat.pkg",
        "channel.json",
        "clean_vm_proof.sh",
    ]
    artifacts = uploaded_channel["artifacts"]
    assert isinstance(artifacts, list)
    assert artifacts[0]["url"] == remote_channel.cask_url
    assert artifacts[0]["sha256"] == remote_channel.cask_sha256
    assert "path" not in artifacts[0]
    bash_commands = [command for command in remote_commands if command.startswith("/bin/bash ")]
    assert len(bash_commands) == 1
    assert bash_commands[0].endswith("'' update-agent")
    assert str(stock_codex) not in bash_commands[0]


def test_stock_codex_compat_pkg_clean_vm_auth_onboarding_guides_login_without_auth_upload(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    stock_codex = _write_codex_binary(
        tmp_path / "stock" / "codex",
        version="codex-cli 0.142.5",
    )
    package_path = tmp_path / "artifacts" / "omnigent-stock-codex-compat.pkg"
    package_path.parent.mkdir()
    package_path.write_bytes(b"signed-notarized-pkg")
    remote_channel = _MOD._OfficialStockCodexRemoteChannel(
        policy_name="official-openai-github-release",
        cask_token="codex",
        cask_tap="homebrew/cask",
        cask_homepage="https://github.com/openai/codex",
        cask_version="0.143.0",
        cask_url=(
            "https://github.com/openai/codex/releases/download/"
            "rust-v0.143.0/codex-aarch64-apple-darwin.tar.gz"
        ),
        cask_sha256="f" * 64,
        selected_version="codex-cli 0.143.0",
        archive_executable="codex-aarch64-apple-darwin",
    )
    uploads: list[tuple[Path, str]] = []
    uploaded_channel: dict[str, object] = {}
    remote_commands: list[str] = []

    def fake_which(name: str, path: str | None = None) -> str | None:
        if path is not None:
            return None
        return {
            "ssh": "/usr/bin/ssh",
            "scp": "/usr/bin/scp",
            "tart": "/usr/local/bin/tart",
        }.get(name)

    def fake_copy_clean_vm_file(
        *,
        scp_path: str,
        ssh_target: str,
        ssh_port: int,
        ssh_identity: Path | None,
        source: Path,
        remote_destination: str,
        timeout: float,
    ) -> subprocess.CompletedProcess[str]:
        del scp_path, ssh_target, ssh_port, ssh_identity, timeout
        uploads.append((source, remote_destination))
        if source.name == "channel.json":
            uploaded_channel.update(json.loads(source.read_text(encoding="utf-8")))
        return subprocess.CompletedProcess(["scp"], 0, stdout="", stderr="")

    def fake_run_clean_vm_ssh_command(
        remote_command: str,
        *,
        ssh_path: str,
        ssh_target: str,
        ssh_port: int,
        ssh_identity: Path | None,
        timeout: float,
    ) -> subprocess.CompletedProcess[str]:
        del ssh_path, ssh_target, ssh_port, ssh_identity, timeout
        remote_commands.append(remote_command)
        if remote_command.startswith("/usr/bin/mktemp"):
            return subprocess.CompletedProcess(
                ["ssh"],
                0,
                stdout="/tmp/omnigent-stock-codex-compat-clean-vm-auth.test\n",
                stderr="",
            )
        if remote_command.startswith("chmod "):
            return subprocess.CompletedProcess(["ssh"], 0, stdout="", stderr="")
        if remote_command.startswith("/bin/bash "):
            codex_home = (
                "/Users/admin/.omnigent-stock-codex-compat-clean-vm-remote-"
                "acquisition-proof/auth-onboarding-codex-home"
            )
            launcher_path = "/Users/admin/.local/bin/omnigent-stock-codex-compat"
            auth_onboarding_evidence = {
                "authPath": f"{codex_home}/auth.json",
                "authUploaded": False,
                "codexHome": codex_home,
                "commandExecuted": False,
                "commandSurface": "installed-compat-launcher",
                "kind": "omnigent-clean-vm-auth-onboarding-evidence",
                "launcherPath": launcher_path,
                "onboardingCommand": f"CODEX_HOME={codex_home} {launcher_path} login",
                "selectedCommandVersion": "codex-cli 0.143.0",
                "unavailableReason": "needs-auth",
            }
            return subprocess.CompletedProcess(
                ["ssh"],
                0,
                stdout=(
                    json.dumps(auth_onboarding_evidence, sort_keys=True)
                    + "\n"
                    "stock_codex_compat_pkg_clean_vm_auth_onboarding_status="
                    "replacement-ready\n"
                ),
                stderr="",
            )
        if remote_command.startswith("rm -rf "):
            return subprocess.CompletedProcess(["ssh"], 0, stdout="", stderr="")
        raise AssertionError(f"unexpected remote command: {remote_command}")

    monkeypatch.setattr(_MOD.shutil, "which", fake_which)
    monkeypatch.setattr(
        _MOD,
        "_official_stock_codex_remote_channel",
        lambda: remote_channel,
    )
    monkeypatch.setattr(
        _MOD,
        "_wait_for_clean_vm_ssh",
        lambda **_kwargs: subprocess.CompletedProcess(["ssh"], 0, stdout="", stderr=""),
    )
    monkeypatch.setattr(_MOD, "_copy_clean_vm_file", fake_copy_clean_vm_file)
    monkeypatch.setattr(_MOD, "_run_clean_vm_ssh_command", fake_run_clean_vm_ssh_command)

    proof = _MOD.run_stock_codex_compat_pkg_clean_vm_auth_onboarding_proof(
        stock_codex,
        package_path=package_path,
        clean_vm_ssh_target="admin@192.0.2.10",
        clean_vm_tart_name=None,
        clean_vm_ssh_identity=None,
        clean_vm_ssh_user=None,
        clean_vm_ssh_port=22,
        clean_vm_start_tart=False,
    )

    uploaded_sources = [source for source, _destination in uploads]
    assert proof.status == "replacement-ready"
    assert proof.proof_variant == "official-remote-channel-auth-onboarding"
    assert proof.auth_onboarding_requested is True
    assert proof.host_stock_codex_uploaded is False
    assert proof.auth_onboarding_launcher_path == Path(
        "/Users/admin/.local/bin/omnigent-stock-codex-compat"
    )
    assert proof.auth_onboarding_codex_home == Path(
        "/Users/admin/.omnigent-stock-codex-compat-clean-vm-remote-acquisition-proof"
        "/auth-onboarding-codex-home"
    )
    assert proof.auth_onboarding_auth_path == proof.auth_onboarding_codex_home / "auth.json"
    assert proof.auth_onboarding_unavailable_reason == "needs-auth"
    assert proof.auth_onboarding_command == (
        "CODEX_HOME="
        "/Users/admin/.omnigent-stock-codex-compat-clean-vm-remote-acquisition-proof"
        "/auth-onboarding-codex-home "
        "/Users/admin/.local/bin/omnigent-stock-codex-compat login"
    )
    assert proof.auth_onboarding_selected_command_version == "codex-cli 0.143.0"
    assert proof.auth_onboarding_command_executed is False
    assert proof.auth_onboarding_auth_uploaded is False
    assert stock_codex.resolve() not in [source.resolve() for source in uploaded_sources]
    assert [source.name for source in uploaded_sources] == [
        "omnigent-stock-codex-compat.pkg",
        "channel.json",
        "clean_vm_proof.sh",
    ]
    artifacts = uploaded_channel["artifacts"]
    assert isinstance(artifacts, list)
    assert artifacts[0]["url"] == remote_channel.cask_url
    assert artifacts[0]["sha256"] == remote_channel.cask_sha256
    assert "path" not in artifacts[0]
    bash_commands = [command for command in remote_commands if command.startswith("/bin/bash ")]
    assert len(bash_commands) == 1
    assert bash_commands[0].endswith("'' auth-onboarding")
    assert str(stock_codex) not in bash_commands[0]


def test_stock_codex_compat_pkg_clean_vm_auth_persistence_uploads_auth_not_stock_binary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    stock_codex = _write_codex_binary(
        tmp_path / "stock" / "codex",
        version="codex-cli 0.142.5",
    )
    package_path = tmp_path / "artifacts" / "omnigent-stock-codex-compat.pkg"
    package_path.parent.mkdir()
    package_path.write_bytes(b"signed-notarized-pkg")
    auth_path = tmp_path / "auth" / "auth.json"
    auth_path.parent.mkdir()
    auth_path.write_text('{"tokens": {"refresh_token": "redacted-fixture"}}\n', encoding="utf-8")
    remote_channel = _MOD._OfficialStockCodexRemoteChannel(
        policy_name="official-openai-github-release",
        cask_token="codex",
        cask_tap="homebrew/cask",
        cask_homepage="https://github.com/openai/codex",
        cask_version="0.143.0",
        cask_url=(
            "https://github.com/openai/codex/releases/download/"
            "rust-v0.143.0/codex-aarch64-apple-darwin.tar.gz"
        ),
        cask_sha256="a" * 64,
        selected_version="codex-cli 0.143.0",
        archive_executable="codex-aarch64-apple-darwin",
    )
    uploads: list[tuple[Path, str]] = []
    uploaded_channel: dict[str, object] = {}
    remote_commands: list[str] = []

    def fake_which(name: str, path: str | None = None) -> str | None:
        if path is not None:
            return None
        return {
            "ssh": "/usr/bin/ssh",
            "scp": "/usr/bin/scp",
            "tart": "/usr/local/bin/tart",
        }.get(name)

    def fake_copy_clean_vm_file(
        *,
        scp_path: str,
        ssh_target: str,
        ssh_port: int,
        ssh_identity: Path | None,
        source: Path,
        remote_destination: str,
        timeout: float,
    ) -> subprocess.CompletedProcess[str]:
        del scp_path, ssh_target, ssh_port, ssh_identity, timeout
        uploads.append((source, remote_destination))
        if source.name == "channel.json":
            uploaded_channel.update(json.loads(source.read_text(encoding="utf-8")))
        return subprocess.CompletedProcess(["scp"], 0, stdout="", stderr="")

    def fake_run_clean_vm_ssh_command(
        remote_command: str,
        *,
        ssh_path: str,
        ssh_target: str,
        ssh_port: int,
        ssh_identity: Path | None,
        timeout: float,
    ) -> subprocess.CompletedProcess[str]:
        del ssh_path, ssh_target, ssh_port, ssh_identity, timeout
        remote_commands.append(remote_command)
        if remote_command.startswith("/usr/bin/mktemp"):
            return subprocess.CompletedProcess(
                ["ssh"],
                0,
                stdout="/tmp/omnigent-stock-codex-compat-clean-vm-auth-persist.test\n",
                stderr="",
            )
        if remote_command.startswith("chmod "):
            return subprocess.CompletedProcess(["ssh"], 0, stdout="", stderr="")
        if remote_command.startswith("/bin/bash "):
            codex_home = (
                "/Users/admin/.omnigent-stock-codex-compat-clean-vm-remote-"
                "acquisition-proof/auth-onboarding-codex-home"
            )
            launcher_path = "/Users/admin/.local/bin/omnigent-stock-codex-compat"
            auth_persistence_evidence = {
                "authPath": f"{codex_home}/auth.json",
                "authPersistedAfterLive": True,
                "authUploaded": True,
                "browserLoginAutomated": False,
                "codexHome": codex_home,
                "commandSurface": "installed-compat-launcher",
                "eventCount": 8,
                "firstAgentMessagePreview": (
                    "Routing: orchestrator-led\n\n"
                    "STOCK_CODEX_COMPAT_AUTH_PERSISTENCE_OK"
                ),
                "kind": "omnigent-clean-vm-auth-persistence-evidence",
                "launcherPath": launcher_path,
                "loginCommandExecuted": False,
                "postUnavailableReason": None,
                "preUnavailableReason": "needs-auth",
                "selectedCommandPath": launcher_path,
                "selectedCommandVersion": "codex-cli 0.143.0",
                "threadId": "019f-auth-persistence-proof",
                "workingDirectory": (
                    "/Users/admin/.local/omnigent/stock-codex-compat/runtime"
                ),
            }
            return subprocess.CompletedProcess(
                ["ssh"],
                0,
                stdout=(
                    json.dumps(auth_persistence_evidence, sort_keys=True)
                    + "\n"
                    "stock_codex_compat_pkg_clean_vm_auth_persistence_status="
                    "replacement-ready\n"
                ),
                stderr="",
            )
        if remote_command.startswith("rm -rf "):
            return subprocess.CompletedProcess(["ssh"], 0, stdout="", stderr="")
        raise AssertionError(f"unexpected remote command: {remote_command}")

    monkeypatch.setattr(_MOD.shutil, "which", fake_which)
    monkeypatch.setattr(
        _MOD,
        "_official_stock_codex_remote_channel",
        lambda: remote_channel,
    )
    monkeypatch.setattr(
        _MOD,
        "_stock_replacement_auth_source",
        lambda: (auth_path, "stock-default-home"),
    )
    monkeypatch.setattr(
        _MOD.codex_native,
        "_codex_auth_json_has_available_credential",
        lambda _path: True,
    )
    monkeypatch.setattr(
        _MOD,
        "_wait_for_clean_vm_ssh",
        lambda **_kwargs: subprocess.CompletedProcess(["ssh"], 0, stdout="", stderr=""),
    )
    monkeypatch.setattr(_MOD, "_copy_clean_vm_file", fake_copy_clean_vm_file)
    monkeypatch.setattr(_MOD, "_run_clean_vm_ssh_command", fake_run_clean_vm_ssh_command)

    proof = _MOD.run_stock_codex_compat_pkg_clean_vm_auth_persistence_proof(
        stock_codex,
        package_path=package_path,
        clean_vm_ssh_target="admin@192.0.2.10",
        clean_vm_tart_name=None,
        clean_vm_ssh_identity=None,
        clean_vm_ssh_user=None,
        clean_vm_ssh_port=22,
        clean_vm_start_tart=False,
    )

    uploaded_sources = [source for source, _destination in uploads]
    assert proof.status == "replacement-ready"
    assert proof.proof_variant == "official-remote-channel-auth-persistence"
    assert proof.auth_persistence_requested is True
    assert proof.auth_persistence_auth_source == "stock-default-home"
    assert proof.auth_persistence_auth_uploaded is True
    assert proof.host_stock_codex_uploaded is False
    assert proof.auth_persistence_launcher_path == Path(
        "/Users/admin/.local/bin/omnigent-stock-codex-compat"
    )
    assert proof.auth_persistence_selected_command_path == proof.auth_persistence_launcher_path
    assert proof.auth_persistence_selected_command_version == "codex-cli 0.143.0"
    assert proof.auth_persistence_codex_home == Path(
        "/Users/admin/.omnigent-stock-codex-compat-clean-vm-remote-acquisition-proof"
        "/auth-onboarding-codex-home"
    )
    assert proof.auth_persistence_auth_path == proof.auth_persistence_codex_home / "auth.json"
    assert proof.auth_persistence_pre_unavailable_reason == "needs-auth"
    assert proof.auth_persistence_post_unavailable_reason is None
    assert proof.auth_persistence_login_command_executed is False
    assert proof.auth_persistence_browser_login_automated is False
    assert proof.auth_persistence_auth_persisted_after_live is True
    assert proof.auth_persistence_thread_id == "019f-auth-persistence-proof"
    assert proof.auth_persistence_event_count == 8
    assert "STOCK_CODEX_COMPAT_AUTH_PERSISTENCE_OK" in (
        proof.auth_persistence_agent_message_preview or ""
    )
    assert auth_path.resolve() in [source.resolve() for source in uploaded_sources]
    assert stock_codex.resolve() not in [source.resolve() for source in uploaded_sources]
    assert [source.name for source in uploaded_sources] == [
        "omnigent-stock-codex-compat.pkg",
        "channel.json",
        "clean_vm_proof.sh",
        "auth.json",
    ]
    artifacts = uploaded_channel["artifacts"]
    assert isinstance(artifacts, list)
    assert artifacts[0]["url"] == remote_channel.cask_url
    assert artifacts[0]["sha256"] == remote_channel.cask_sha256
    assert "path" not in artifacts[0]
    bash_commands = [command for command in remote_commands if command.startswith("/bin/bash ")]
    assert len(bash_commands) == 1
    assert bash_commands[0].endswith("/auth.json auth-persistence")
    assert str(stock_codex) not in bash_commands[0]


def test_stock_codex_compat_pkg_clean_vm_live_uploads_auth_but_not_stock_binary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    stock_codex = _write_codex_binary(
        tmp_path / "stock" / "codex",
        version="codex-cli 0.142.5",
    )
    package_path = tmp_path / "artifacts" / "omnigent-stock-codex-compat.pkg"
    package_path.parent.mkdir()
    package_path.write_bytes(b"signed-notarized-pkg")
    auth_path = tmp_path / "auth" / "auth.json"
    auth_path.parent.mkdir()
    auth_path.write_text('{"tokens": "redacted-fixture"}\n', encoding="utf-8")
    remote_channel = _MOD._OfficialStockCodexRemoteChannel(
        policy_name="official-openai-github-release",
        cask_token="codex",
        cask_tap="homebrew/cask",
        cask_homepage="https://github.com/openai/codex",
        cask_version="0.143.0",
        cask_url=(
            "https://github.com/openai/codex/releases/download/"
            "rust-v0.143.0/codex-aarch64-apple-darwin.tar.gz"
        ),
        cask_sha256="d" * 64,
        selected_version="codex-cli 0.143.0",
        archive_executable="codex-aarch64-apple-darwin",
    )
    uploads: list[tuple[Path, str]] = []
    remote_commands: list[str] = []

    def fake_which(name: str, path: str | None = None) -> str | None:
        if path is not None:
            return None
        return {
            "ssh": "/usr/bin/ssh",
            "scp": "/usr/bin/scp",
            "tart": "/usr/local/bin/tart",
        }.get(name)

    def fake_copy_clean_vm_file(
        *,
        scp_path: str,
        ssh_target: str,
        ssh_port: int,
        ssh_identity: Path | None,
        source: Path,
        remote_destination: str,
        timeout: float,
    ) -> subprocess.CompletedProcess[str]:
        del scp_path, ssh_target, ssh_port, ssh_identity, timeout
        uploads.append((source, remote_destination))
        return subprocess.CompletedProcess(["scp"], 0, stdout="", stderr="")

    def fake_run_clean_vm_ssh_command(
        remote_command: str,
        *,
        ssh_path: str,
        ssh_target: str,
        ssh_port: int,
        ssh_identity: Path | None,
        timeout: float,
    ) -> subprocess.CompletedProcess[str]:
        del ssh_path, ssh_target, ssh_port, ssh_identity, timeout
        remote_commands.append(remote_command)
        if remote_command.startswith("/usr/bin/mktemp"):
            return subprocess.CompletedProcess(
                ["ssh"],
                0,
                stdout="/tmp/omnigent-stock-codex-compat-clean-vm-live.test\n",
                stderr="",
            )
        if remote_command.startswith("chmod "):
            return subprocess.CompletedProcess(["ssh"], 0, stdout="", stderr="")
        if remote_command.startswith("/bin/bash "):
            live_evidence = {
                "codexHome": (
                    "/Users/admin/.omnigent-stock-codex-compat-clean-vm-remote-"
                    "acquisition-proof/live-codex-home"
                ),
                "commandSurface": "installed-compat-launcher",
                "eventCount": 7,
                "firstAgentMessagePreview": (
                    "Routing: orchestrator-led\n\nSTOCK_CODEX_COMPAT_LIVE_OK"
                ),
                "launcherPath": "/Users/admin/.local/bin/omnigent-stock-codex-compat",
                "selectedCommandPath": (
                    "/Users/admin/.local/bin/omnigent-stock-codex-compat"
                ),
                "selectedCommandVersion": "codex-cli 0.143.0",
                "threadId": "019f-live-proof",
                "workingDirectory": (
                    "/Users/admin/.local/omnigent/stock-codex-compat/runtime"
                ),
            }
            return subprocess.CompletedProcess(
                ["ssh"],
                0,
                stdout=(
                    json.dumps(live_evidence, sort_keys=True)
                    + "\n"
                    "stock_codex_compat_pkg_clean_vm_live_status="
                    "replacement-ready\n"
                ),
                stderr="",
            )
        if remote_command.startswith("rm -rf "):
            return subprocess.CompletedProcess(["ssh"], 0, stdout="", stderr="")
        raise AssertionError(f"unexpected remote command: {remote_command}")

    monkeypatch.setattr(_MOD.shutil, "which", fake_which)
    monkeypatch.setattr(
        _MOD,
        "_official_stock_codex_remote_channel",
        lambda: remote_channel,
    )
    monkeypatch.setattr(
        _MOD,
        "_stock_replacement_auth_source",
        lambda: (auth_path, "stock-default-home"),
    )
    monkeypatch.setattr(
        _MOD.codex_native,
        "_codex_auth_json_has_available_credential",
        lambda _path: True,
    )
    monkeypatch.setattr(
        _MOD,
        "_wait_for_clean_vm_ssh",
        lambda **_kwargs: subprocess.CompletedProcess(["ssh"], 0, stdout="", stderr=""),
    )
    monkeypatch.setattr(_MOD, "_copy_clean_vm_file", fake_copy_clean_vm_file)
    monkeypatch.setattr(_MOD, "_run_clean_vm_ssh_command", fake_run_clean_vm_ssh_command)

    proof = _MOD.run_stock_codex_compat_pkg_clean_vm_live_proof(
        stock_codex,
        package_path=package_path,
        clean_vm_ssh_target="admin@192.0.2.10",
        clean_vm_tart_name=None,
        clean_vm_ssh_identity=None,
        clean_vm_ssh_user=None,
        clean_vm_ssh_port=22,
        clean_vm_start_tart=False,
    )

    uploaded_sources = [source for source, _destination in uploads]
    assert proof.status == "replacement-ready"
    assert proof.proof_variant == "official-remote-channel-live-model"
    assert proof.live_auth_path == auth_path.resolve()
    assert proof.live_auth_source == "stock-default-home"
    assert proof.live_auth_uploaded is True
    assert proof.live_model_turn_requested is True
    assert proof.live_launcher_path == Path(
        "/Users/admin/.local/bin/omnigent-stock-codex-compat"
    )
    assert proof.live_selected_command_path == proof.live_launcher_path
    assert proof.live_selected_command_version == "codex-cli 0.143.0"
    assert proof.live_codex_home == Path(
        "/Users/admin/.omnigent-stock-codex-compat-clean-vm-remote-acquisition-proof"
        "/live-codex-home"
    )
    assert proof.live_working_directory == Path(
        "/Users/admin/.local/omnigent/stock-codex-compat/runtime"
    )
    assert proof.live_thread_id == "019f-live-proof"
    assert proof.live_event_count == 7
    assert proof.live_agent_message_preview.startswith("Routing: orchestrator-led")
    assert auth_path.resolve() in [source.resolve() for source in uploaded_sources]
    assert stock_codex.resolve() not in [source.resolve() for source in uploaded_sources]
    assert [source.name for source in uploaded_sources] == [
        "omnigent-stock-codex-compat.pkg",
        "channel.json",
        "clean_vm_proof.sh",
        "auth.json",
    ]
    bash_commands = [command for command in remote_commands if command.startswith("/bin/bash ")]
    assert len(bash_commands) == 1
    assert bash_commands[0].endswith("/auth.json")
    assert str(stock_codex) not in bash_commands[0]


def test_clean_vm_live_output_evidence_requires_installed_launcher_surface() -> None:
    output = (
        json.dumps(
            {
                "codexHome": "/Users/admin/proof/live-codex-home",
                "commandSurface": "raw-stock-codex",
                "eventCount": 7,
                "firstAgentMessagePreview": (
                    "Routing: orchestrator-led\n\nSTOCK_CODEX_COMPAT_LIVE_OK"
                ),
                "launcherPath": "/Users/admin/.local/bin/omnigent-stock-codex-compat",
                "selectedCommandPath": "/Users/admin/.local/bin/omnigent-stock-codex-compat",
                "selectedCommandVersion": "codex-cli 0.143.0",
                "threadId": "019f-live-proof",
                "workingDirectory": "/Users/admin/.local/omnigent/stock-codex-compat/runtime",
            },
            sort_keys=True,
        )
        + "\n"
        + "stock_codex_compat_pkg_clean_vm_live_status=replacement-ready\n"
    )

    assert _MOD._parse_clean_vm_live_output_evidence(output) is None


def test_clean_vm_update_agent_output_evidence_requires_launchctl_completion() -> None:
    output = (
        json.dumps(
            {
                "directAction": "up-to-date",
                "hostCacheReferenced": False,
                "kind": "omnigent-clean-vm-update-agent-evidence",
                "launchAgentLabel": "ai.omnigent.stock-codex-compat.update",
                "launchAgentPath": (
                    "/Users/admin/Library/LaunchAgents/"
                    "ai.omnigent.stock-codex-compat.update.plist"
                ),
                "launchDomain": "user/501",
                "launchctlBootout": "unloaded",
                "launchctlBootstrap": "loaded",
                "launchctlKickstart": "not-run",
                "scheduledAction": "up-to-date",
                "selectedCodexPath": "/Users/admin/.local/omnigent/codex-stock/0.143.0/codex",
                "selectedCodexVersion": "codex-cli 0.143.0",
            },
            sort_keys=True,
        )
        + "\n"
        + "stock_codex_compat_pkg_clean_vm_update_agent_status=replacement-ready\n"
    )

    assert _MOD._parse_clean_vm_update_agent_output_evidence(output) is None


def test_clean_vm_auth_onboarding_output_evidence_requires_no_login_execution() -> None:
    codex_home = (
        "/Users/admin/.omnigent-stock-codex-compat-clean-vm-remote-acquisition-proof/"
        "auth-onboarding-codex-home"
    )
    launcher_path = "/Users/admin/.local/bin/omnigent-stock-codex-compat"
    output = (
        json.dumps(
            {
                "authPath": f"{codex_home}/auth.json",
                "authUploaded": False,
                "codexHome": codex_home,
                "commandExecuted": True,
                "commandSurface": "installed-compat-launcher",
                "kind": "omnigent-clean-vm-auth-onboarding-evidence",
                "launcherPath": launcher_path,
                "onboardingCommand": f"CODEX_HOME={codex_home} {launcher_path} login",
                "selectedCommandVersion": "codex-cli 0.143.0",
                "unavailableReason": "needs-auth",
            },
            sort_keys=True,
        )
        + "\n"
        + "stock_codex_compat_pkg_clean_vm_auth_onboarding_status=replacement-ready\n"
    )

    assert _MOD._parse_clean_vm_auth_onboarding_output_evidence(output) is None


def test_clean_vm_auth_onboarding_output_evidence_requires_installed_launcher_path() -> None:
    codex_home = (
        "/Users/admin/.omnigent-stock-codex-compat-clean-vm-remote-acquisition-proof/"
        "auth-onboarding-codex-home"
    )
    launcher_path = "/tmp/omnigent-stock-codex-compat"
    output = (
        json.dumps(
            {
                "authPath": f"{codex_home}/auth.json",
                "authUploaded": False,
                "codexHome": codex_home,
                "commandExecuted": False,
                "commandSurface": "installed-compat-launcher",
                "kind": "omnigent-clean-vm-auth-onboarding-evidence",
                "launcherPath": launcher_path,
                "onboardingCommand": f"CODEX_HOME={codex_home} {launcher_path} login",
                "selectedCommandVersion": "codex-cli 0.143.0",
                "unavailableReason": "needs-auth",
            },
            sort_keys=True,
        )
        + "\n"
        + "stock_codex_compat_pkg_clean_vm_auth_onboarding_status=replacement-ready\n"
    )

    assert _MOD._parse_clean_vm_auth_onboarding_output_evidence(output) is None


def test_clean_vm_auth_persistence_output_evidence_rejects_automated_browser_login() -> None:
    codex_home = (
        "/Users/admin/.omnigent-stock-codex-compat-clean-vm-remote-acquisition-proof/"
        "auth-onboarding-codex-home"
    )
    launcher_path = "/Users/admin/.local/bin/omnigent-stock-codex-compat"
    output = (
        json.dumps(
            {
                "authPath": f"{codex_home}/auth.json",
                "authPersistedAfterLive": True,
                "authUploaded": True,
                "browserLoginAutomated": True,
                "codexHome": codex_home,
                "commandSurface": "installed-compat-launcher",
                "eventCount": 8,
                "firstAgentMessagePreview": (
                    "Routing: orchestrator-led\n\n"
                    "STOCK_CODEX_COMPAT_AUTH_PERSISTENCE_OK"
                ),
                "kind": "omnigent-clean-vm-auth-persistence-evidence",
                "launcherPath": launcher_path,
                "loginCommandExecuted": False,
                "postUnavailableReason": None,
                "preUnavailableReason": "needs-auth",
                "selectedCommandPath": launcher_path,
                "selectedCommandVersion": "codex-cli 0.143.0",
                "threadId": "019f-auth-persistence-proof",
                "workingDirectory": (
                    "/Users/admin/.local/omnigent/stock-codex-compat/runtime"
                ),
            },
            sort_keys=True,
        )
        + "\n"
        + "stock_codex_compat_pkg_clean_vm_auth_persistence_status=replacement-ready\n"
    )

    assert _MOD._parse_clean_vm_auth_persistence_output_evidence(output) is None


def test_clean_vm_ssh_command_avoids_persistent_known_hosts() -> None:
    command = _MOD._clean_vm_ssh_base_command(
        ssh_path="/usr/bin/ssh",
        ssh_target="admin@192.0.2.10",
        ssh_port=2222,
        ssh_identity=Path("/tmp/test-key"),
    )

    assert command[:3] == ["/usr/bin/ssh", "-p", "2222"]
    assert "BatchMode=yes" in command
    assert "StrictHostKeyChecking=no" in command
    assert "UserKnownHostsFile=/dev/null" in command
    assert "ConnectTimeout=10" in command
    assert command[command.index("-i") + 1] == "/tmp/test-key"
    assert command[-1] == "admin@192.0.2.10"


def test_clean_vm_bootstrap_script_installs_uvx_without_shell_profile_mutation() -> None:
    script = _MOD._clean_vm_bootstrap_script_text()

    assert ".omnigent-stock-codex-compat-clean-user-ok" in script
    assert "refusing unexpected guest HOME" in script
    assert "grep -qxF \"$ssh_public_key\"" in script
    assert "sudo -n true" in script
    assert "systemsetup -setremotelogin on" in script
    assert "--clean-vm-bootstrap-install-uv was not supplied" in script
    assert "export INSTALLER_NO_MODIFY_PATH=1" in script
    assert "curl -LsSf \"$uv_installer_url\" | sh" in script
    assert "stock_codex_compat_clean_vm_bootstrap_status=replacement-ready" in script
    assert "stock_codex_compat_clean_vm_bootstrap_uvx_path" in script


def test_stock_codex_compat_pkg_clean_vm_bootstrap_blocks_existing_target(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    identity = tmp_path / "id_ed25519"
    identity.write_text("private-key\n", encoding="utf-8")

    def fake_which(name: str, path: str | None = None) -> str | None:
        if path is not None:
            return None
        return {
            "ssh": "/usr/bin/ssh",
            "ssh-keygen": "/usr/bin/ssh-keygen",
            "tart": "/usr/local/bin/tart",
        }.get(name)

    monkeypatch.setattr(_MOD.shutil, "which", fake_which)
    monkeypatch.setattr(
        _MOD,
        "_ssh_public_key_for_identity",
        lambda **_kwargs: "ssh-ed25519 AAAATEST clean-vm",
    )
    monkeypatch.setattr(
        _MOD,
        "_tart_vm_names",
        lambda _tart_path: {"ghcr.io/cirruslabs/macos-tahoe-base:latest", "target-vm"},
    )

    proof = _MOD.run_stock_codex_compat_pkg_clean_vm_bootstrap_proof(
        clean_vm_source_tart_name="ghcr.io/cirruslabs/macos-tahoe-base:latest",
        clean_vm_tart_name="target-vm",
        clean_vm_ssh_identity=identity,
        clean_vm_ssh_user="admin",
        clean_vm_ssh_port=22,
        clean_vm_bootstrap_install_uv=True,
    )

    assert proof.status == "blocked"
    assert any("target already exists" in item for item in proof.missing_prerequisites)
    assert proof.tart_clone_completed is False


def test_stock_codex_compat_pkg_clean_vm_bootstrap_clones_and_verifies_ssh(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    identity = tmp_path / "id_ed25519"
    identity.write_text("private-key\n", encoding="utf-8")
    run_calls: list[list[str]] = []
    popen_calls: list[list[str]] = []
    source_vm = "ghcr.io/cirruslabs/macos-tahoe-base:latest"
    target_vm = "omnigent-clean-bootstrap-test"

    class FakePopen:
        def __init__(self, args: list[str], **_kwargs: object) -> None:
            popen_calls.append(args)

    def fake_which(name: str, path: str | None = None) -> str | None:
        if path is not None:
            return None
        return {
            "ssh": "/usr/bin/ssh",
            "ssh-keygen": "/usr/bin/ssh-keygen",
            "tart": "/usr/local/bin/tart",
        }.get(name)

    def fake_run(
        args: list[str],
        *,
        check: bool = False,
        capture_output: bool = False,
        text: bool = False,
        timeout: float | None = None,
        input: str | None = None,
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        del check, capture_output, text, timeout
        run_calls.append(args)
        if args[:3] == ["/usr/bin/ssh-keygen", "-y", "-f"]:
            return subprocess.CompletedProcess(
                args,
                0,
                stdout="ssh-ed25519 AAAATEST key\n",
                stderr="",
            )
        if args == ["/usr/local/bin/tart", "clone", source_vm, target_vm]:
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        if args == ["/usr/local/bin/tart", "set", target_vm, "--random-mac"]:
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        if args == ["/usr/local/bin/tart", "ip", target_vm, "--wait", "180"]:
            return subprocess.CompletedProcess(args, 0, stdout="192.0.2.20\n", stderr="")
        if args == ["/usr/local/bin/tart", "exec", target_vm, "/usr/bin/true"]:
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        if args[:5] == ["/usr/local/bin/tart", "exec", "-i", target_vm, "/bin/bash"]:
            assert input is not None
            assert "INSTALLER_NO_MODIFY_PATH=1" in input
            assert args[-3:] == [
                "ssh-ed25519 AAAATEST key",
                "1",
                _MOD.UV_STANDALONE_INSTALLER_URL,
            ]
            return subprocess.CompletedProcess(
                args,
                0,
                stdout=(
                    "stock_codex_compat_clean_vm_bootstrap_status=replacement-ready\n"
                    "stock_codex_compat_clean_vm_bootstrap_marker_path="
                    "/Users/admin/.omnigent-stock-codex-compat-clean-user-ok\n"
                    "stock_codex_compat_clean_vm_bootstrap_uvx_path="
                    "/Users/admin/.local/bin/uvx\n"
                    "stock_codex_compat_clean_vm_bootstrap_sudo_noninteractive=true\n"
                ),
                stderr="",
            )
        if args == ["/usr/local/bin/tart", "stop", target_vm, "--timeout", "30"]:
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        raise AssertionError(f"unexpected subprocess.run args: {args}")

    def fake_run_clean_vm_ssh_command(
        remote_command: str,
        *,
        ssh_path: str,
        ssh_target: str,
        ssh_port: int,
        ssh_identity: Path | None,
        timeout: float,
    ) -> subprocess.CompletedProcess[str]:
        del remote_command, ssh_path, ssh_target, ssh_port, ssh_identity, timeout
        return subprocess.CompletedProcess(
            ["ssh"],
            0,
            stdout=(
                "stock_codex_compat_clean_vm_bootstrap_ssh_ready=true\n"
                "stock_codex_compat_clean_vm_bootstrap_sudo_noninteractive=true\n"
                "stock_codex_compat_clean_vm_bootstrap_marker_path="
                "/Users/admin/.omnigent-stock-codex-compat-clean-user-ok\n"
                "stock_codex_compat_clean_vm_bootstrap_uvx_path="
                "/Users/admin/.local/bin/uvx\n"
            ),
            stderr="",
        )

    monkeypatch.setattr(_MOD.shutil, "which", fake_which)
    monkeypatch.setattr(_MOD, "_tart_vm_names", lambda _tart_path: {source_vm})
    monkeypatch.setattr(_MOD.subprocess, "run", fake_run)
    monkeypatch.setattr(_MOD.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(
        _MOD,
        "_wait_for_clean_vm_ssh",
        lambda **_kwargs: subprocess.CompletedProcess(["ssh"], 0, stdout="", stderr=""),
    )
    monkeypatch.setattr(_MOD, "_run_clean_vm_ssh_command", fake_run_clean_vm_ssh_command)

    proof = _MOD.run_stock_codex_compat_pkg_clean_vm_bootstrap_proof(
        clean_vm_source_tart_name=source_vm,
        clean_vm_tart_name=target_vm,
        clean_vm_ssh_identity=identity,
        clean_vm_ssh_user="admin",
        clean_vm_ssh_port=22,
        clean_vm_bootstrap_install_uv=True,
    )

    assert proof.status == "replacement-ready"
    assert proof.source_tart_name == source_vm
    assert proof.target_tart_name == target_vm
    assert proof.tart_clone_completed is True
    assert proof.tart_random_mac_completed is True
    assert proof.tart_started is True
    assert proof.tart_stopped is True
    assert proof.tart_ip == "192.0.2.20"
    assert proof.ssh_target == "admin@192.0.2.20"
    assert proof.ssh_ready is True
    assert proof.sudo_noninteractive is True
    assert proof.uvx_path == "/Users/admin/.local/bin/uvx"
    assert proof.clean_marker_path == (
        "/Users/admin/.omnigent-stock-codex-compat-clean-user-ok"
    )
    assert popen_calls == [["/usr/local/bin/tart", "run", "--no-graphics", target_vm]]
    assert [call[:2] for call in run_calls].count(["/usr/local/bin/tart", "stop"]) == 1


def test_stock_codex_compat_pkg_external_clean_user_uses_marked_home(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    stock_codex = _write_codex_binary(tmp_path / "stock" / "codex")
    stock_version = _MOD.codex_version(stock_codex)
    stock_sha256 = _MOD.sha256_file(stock_codex)
    package_path = tmp_path / "artifacts" / "omnigent-stock-codex-compat.pkg"
    package_path.parent.mkdir()
    package_path.write_bytes(b"signed-notarized-pkg")
    clean_home = tmp_path / "external-home"
    clean_home.mkdir()
    marker_path = clean_home / _MOD.EXTERNAL_CLEAN_USER_MARKER_NAME
    marker_path.write_text("disposable\n", encoding="utf-8")
    install_prefix = Path("/Library/Application Support/Omnigent/stock-codex-compat")
    runtime_root = install_prefix / "runtime"
    required_payload_files = {
        "Library/Application Support/Omnigent/stock-codex-compat/pkg-manifest.json": True,
        "Library/Application Support/Omnigent/stock-codex-compat/bundle-manifest.json": True,
        (
            "Library/Application Support/Omnigent/stock-codex-compat/runtime/"
            "pyproject.toml"
        ): True,
        (
            "Library/Application Support/Omnigent/stock-codex-compat/runtime/"
            "scripts/install_stock_codex_compat_launcher.py"
        ): True,
        (
            "Library/Application Support/Omnigent/stock-codex-compat/runtime/"
            "scripts/provision_stock_codex.py"
        ): True,
        (
            "Library/Application Support/Omnigent/stock-codex-compat/runtime/"
            "omnigent/stock_codex_compat_wrapper.py"
        ): True,
    }
    structure = _MOD.StockCodexCompatPkgStructureProof(
        package_path=package_path.resolve(),
        package_sha256=_MOD.sha256_file(package_path),
        source_bundle_sha256="c" * 64,
        package_identifier="ai.omnigent.stock-codex-compat",
        package_version="1.2.3",
        install_location="/",
        install_prefix=install_prefix,
        runtime_root=runtime_root,
        payload_file_count=len(required_payload_files),
        required_payload_files=required_payload_files,
        script_names=("postinstall",),
        archive_entries=("Bom", "PackageInfo", "Payload", "Scripts"),
        signature_status="signed by a certificate trusted by macOS",
        signed=True,
        pkg_manifest_path=tmp_path / "expanded" / "pkg-manifest.json",
        bundle_manifest_path=tmp_path / "expanded" / "bundle-manifest.json",
        pkg_contract={"runtime": "machine-level-runtime-only"},
        bundle_source_root="<omitted-from-pkg>",
    )
    receipt_present = True
    mounted_target = tmp_path / "mounted-target"
    lifecycle_commands: list[list[str]] = []
    provisioner_commands: list[list[str]] = []
    installer_cli_calls: list[list[str]] = []

    def fake_which(name: str, path: str | None = None) -> str | None:
        if path is not None:
            for entry in path.split(os.pathsep):
                candidate = Path(entry) / name
                if candidate.is_file() and os.access(candidate, os.X_OK):
                    return str(candidate)
            return None
        return {
            "pkgutil": "/usr/sbin/pkgutil",
            "xcrun": "/usr/bin/xcrun",
            "spctl": "/usr/sbin/spctl",
            "installer": "/usr/sbin/installer",
            "hdiutil": "/usr/bin/hdiutil",
            "uvx": str(_write_uvx_binary(tmp_path / "tools" / "uvx")),
        }.get(name)

    def fake_signed_pkg(**kwargs: object) -> Any:
        assert kwargs["package_path"] == package_path.resolve()
        assert kwargs["source_repo_root"] == _REPO_ROOT
        return _MOD._SignedNotarizedStockCodexCompatPkg(
            structure=structure,
            notary_submission_id="prebuilt-package",
            notary_status="prebuilt-staple-validated",
            notary_output_preview="prebuilt",
            staple_output_preview="prebuilt",
            stapler_validate_output_preview="validated",
            gatekeeper_output_preview="accepted",
        )

    def fake_create_volume(**kwargs: object) -> tuple[Path, Path, str]:
        assert kwargs["hdiutil_path"] == "/usr/bin/hdiutil"
        mounted_target.mkdir()
        return tmp_path / "target.dmg", mounted_target, "/dev/disk999"

    def write_installed_payload() -> None:
        installed_prefix = mounted_target / install_prefix.relative_to("/")
        installed_runtime = mounted_target / runtime_root.relative_to("/")
        (installed_runtime / "scripts").mkdir(parents=True)
        (installed_runtime / "omnigent").mkdir()
        (installed_runtime / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
        (installed_runtime / "scripts" / "install_stock_codex_compat_launcher.py").write_text(
            "#!/usr/bin/env python3\n",
            encoding="utf-8",
        )
        (installed_runtime / "scripts" / "provision_stock_codex.py").write_text(
            "#!/usr/bin/env python3\n",
            encoding="utf-8",
        )
        (installed_runtime / "omnigent" / "stock_codex_compat_wrapper.py").write_text(
            "",
            encoding="utf-8",
        )
        (installed_prefix / "pkg-manifest.json").write_text(
            json.dumps(
                {
                    "contract": {"runtime": "machine-level-runtime-only"},
                    "packageIdentifier": "ai.omnigent.stock-codex-compat",
                    "packageVersion": "1.2.3",
                }
            )
            + "\n",
            encoding="utf-8",
        )
        (installed_prefix / "bundle-manifest.json").write_text(
            json.dumps({"sourceRoot": "<omitted-from-pkg>"}) + "\n",
            encoding="utf-8",
        )

    def fake_lifecycle_command(
        command: list[str],
        *,
        timeout: float,
        failure_label: str,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        nonlocal receipt_present
        assert timeout > 0
        assert failure_label
        lifecycle_commands.append(command)
        if command[0] == "/usr/sbin/installer":
            assert command[command.index("-target") + 1] == str(mounted_target)
            write_installed_payload()
            return subprocess.CompletedProcess(command, 0, stdout="installer ok", stderr="")
        if command[:3] == ["/usr/sbin/pkgutil", "--volume", str(mounted_target)]:
            if command[3] == "--pkg-info":
                if receipt_present:
                    return subprocess.CompletedProcess(
                        command,
                        0,
                        stdout=(
                            "package-id: ai.omnigent.stock-codex-compat\n"
                            "version: 1.2.3\n"
                        ),
                        stderr="",
                    )
                return subprocess.CompletedProcess(command, 1, stdout="", stderr="not found")
            if command[3] == "--files":
                return subprocess.CompletedProcess(
                    command,
                    0,
                    stdout="\n".join(required_payload_files) + "\n",
                    stderr="",
                )
            if command[3] == "--forget":
                receipt_present = False
                return subprocess.CompletedProcess(command, 0, stdout="Forgot package", stderr="")
        raise AssertionError(f"unexpected lifecycle command: {command!r}, check={check}")

    def fake_provisioner_json(
        command: list[str],
        *,
        env: dict[str, str],
        cwd: Path,
        failure_label: str,
        timeout: float = 60,
        run_as_user: str | None = None,
        sudo_path: str | None = None,
    ) -> dict[str, Any]:
        assert run_as_user is None
        assert sudo_path is None
        assert failure_label
        assert timeout > 0
        assert cwd == mounted_target / runtime_root.relative_to("/")
        assert Path(env["HOME"]) == clean_home.resolve()
        proof_root = clean_home.resolve() / _MOD.EXTERNAL_CLEAN_USER_PROOF_ROOT_NAME
        assert Path(env["CODEX_HOME"]) == (
            clean_home.resolve() / ".codex-omnigent-clean-user-canary"
        )
        assert Path(env["UV_CACHE_DIR"]) == proof_root / "uv-cache"
        assert Path(env["UV_TOOL_DIR"]) == proof_root / "uv-tools"
        assert Path(env["UV_PYTHON_INSTALL_DIR"]) == proof_root / "uv-python"
        assert Path(env["XDG_CACHE_HOME"]) == proof_root / "xdg-cache"
        assert Path(env["XDG_DATA_HOME"]) == proof_root / "xdg-data"
        provisioner_commands.append(command)
        cache_root = Path(command[command.index("--cache-root") + 1])
        expected_sha = command[command.index("--expected-sha256") + 1]
        assert cache_root == clean_home.resolve() / ".local" / "omnigent" / "codex-stock"
        assert expected_sha == stock_sha256
        payload_dir = cache_root / "0.142.2"
        codex_path = _write_codex_binary(payload_dir / "codex", version=stock_version)
        manifest_path = payload_dir / "manifest.json"
        manifest_path.write_text(
            json.dumps({"kind": "omnigent-stock-codex", "sourceKind": "channel"})
            + "\n",
            encoding="utf-8",
        )
        return {
            "action": "installed",
            "codexPath": str(codex_path),
            "payloadDir": str(payload_dir),
            "manifestPath": str(manifest_path),
            "version": stock_version,
            "sha256": _MOD.sha256_file(codex_path),
            "sourceKind": "channel",
            "env": {_MOD.OMNIGENT_STOCK_CODEX_PATH_ENV: str(codex_path)},
        }

    def fake_installer_cli_json(
        args: list[str],
        *,
        env: dict[str, str],
        repo_root: Path,
        script_path: Path,
        run_as_user: str | None = None,
        sudo_path: str | None = None,
    ) -> dict[str, Any]:
        assert run_as_user is None
        assert sudo_path is None
        assert repo_root == mounted_target / runtime_root.relative_to("/")
        assert script_path == repo_root / "scripts" / "install_stock_codex_compat_launcher.py"
        assert Path(env["HOME"]) == clean_home.resolve()
        assert Path(env["CODEX_HOME"]) == (
            clean_home.resolve() / ".codex-omnigent-clean-user-canary"
        )
        installer_cli_calls.append(args)
        adapter_package_dir = (
            clean_home.resolve()
            / ".local"
            / "omnigent"
            / "stock-codex-compat"
            / "adapter-package"
        )
        if args[0] == "--install-adapter-package":
            adapter_bin = adapter_package_dir / "bin"
            adapter_bin.mkdir(parents=True)
            adapter_manifest = adapter_package_dir / "adapter-manifest.json"
            adapter_manifest.write_text(
                json.dumps({"tools": [{"name": "fetch_apple_docs"}]}) + "\n",
                encoding="utf-8",
            )
            return {
                "action": "adapter-package-installed",
                "adapterPackageDir": str(adapter_package_dir),
                "adapterBin": str(adapter_bin),
                "adapterManifest": str(adapter_manifest),
                "adapterToolNames": ["fetch_apple_docs"],
                "mutatesFilesystem": True,
            }
        if args[0] == "--install":
            pinned_codex = Path(args[args.index("--pinned-codex-path") + 1])
            launcher_path = clean_home.resolve() / ".local" / "bin" / (
                "omnigent-stock-codex-compat"
            )
            manifest_path = (
                clean_home.resolve()
                / ".local"
                / "omnigent"
                / "launchers"
                / "stock-codex-compat.json"
            )
            launcher_path.parent.mkdir(parents=True)
            manifest_path.parent.mkdir(parents=True)
            launcher_path.write_text(
                "#!/bin/sh\n"
                "if [ \"${1:-}\" = \"--version\" ]; then\n"
                f"  exec {shlex.quote(str(pinned_codex))} --version\n"
                "fi\n"
                "if [ \"${1:-}\" = \"--omnigent-stock-codex-compat-launcher-probe\" ]; then\n"
                "  cat <<'EOF'\n"
                "OMNIGENT_STOCK_CODEX_COMPAT_LAUNCHER_OK\n"
                f"runtime={repo_root}\n"
                f"codex={pinned_codex}\n"
                "EOF\n"
                "  exit 0\n"
                "fi\n"
                "exit 64\n",
                encoding="utf-8",
            )
            launcher_path.chmod(0o755)
            manifest_path.write_text(
                json.dumps(
                    {
                        "repoRoot": str(repo_root),
                        "pinnedCodexPath": str(pinned_codex),
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            rollback_command = (
                "printf 'compat_launcher_action=uninstalled\\n'; "
                f"rm -f {shlex.quote(str(launcher_path))} "
                f"{shlex.quote(str(manifest_path))}; "
                f"# {repo_root}"
            )
            return {
                "action": "installed",
                "rollbackCommand": rollback_command,
                "mutatesFilesystem": True,
            }
        assert args[0] == "--doctor"
        return {
            "installAllowed": True,
            "existingTargetState": "managed",
            "targetSelectedOnPath": True,
            "mutatesFilesystem": False,
        }

    def fake_auth_classifier(**kwargs: object) -> tuple[Path, str | None, str]:
        home = kwargs["home"]
        codex_home = kwargs["codex_home"]
        assert home == clean_home.resolve()
        assert isinstance(codex_home, Path)
        return codex_home / "auth.json", "needs-auth", '{"unavailableReason":"needs-auth"}\n'

    monkeypatch.setattr(_MOD.shutil, "which", fake_which)
    monkeypatch.setattr(_MOD, "_xcrun_find_tool", lambda _xcrun, tool: f"/usr/bin/{tool}")
    monkeypatch.setattr(_MOD, "_effective_user_is_root", lambda: True)
    monkeypatch.setattr(
        _MOD,
        "_validate_prebuilt_signed_notarized_stock_codex_compat_pkg",
        fake_signed_pkg,
    )
    monkeypatch.setattr(
        _MOD,
        "_create_stock_codex_compat_pkg_target_volume",
        fake_create_volume,
    )
    monkeypatch.setattr(
        _MOD,
        "_detach_stock_codex_compat_pkg_target_volume",
        lambda **kwargs: kwargs["target_device"] == "/dev/disk999",
    )
    monkeypatch.setattr(_MOD, "_run_pkg_lifecycle_command", fake_lifecycle_command)
    monkeypatch.setattr(_MOD, "_run_stock_codex_provisioner_json", fake_provisioner_json)
    monkeypatch.setattr(
        _MOD,
        "_run_stock_codex_compat_installer_cli_json",
        fake_installer_cli_json,
    )
    monkeypatch.setattr(_MOD, "_run_installed_runtime_auth_classifier", fake_auth_classifier)

    proof = _MOD.run_stock_codex_compat_pkg_external_clean_user_proof(
        stock_codex,
        package_path=package_path,
        clean_user_home=clean_home,
    )

    assert proof.status == "replacement-ready"
    assert proof.clean_user_home == clean_home.resolve()
    assert proof.clean_user_marker_path == marker_path.resolve()
    assert proof.receipt_package_id == "ai.omnigent.stock-codex-compat"
    assert proof.provisioned_codex_path is not None
    assert proof.clean_cache_root == clean_home.resolve() / ".local" / "omnigent" / (
        "codex-stock"
    )
    assert proof.provisioned_codex_path.is_relative_to(proof.clean_cache_root)
    assert proof.provisioned_version == stock_version
    assert proof.adapter_package_action == "adapter-package-installed"
    assert proof.adapter_package_exists_after_install is True
    assert proof.install_action == "installed"
    assert proof.version_output == stock_version
    assert proof.doctor_install_allowed is True
    assert proof.doctor_existing_target_state == "managed"
    assert proof.doctor_target_selected_on_path is True
    assert proof.doctor_mutates_filesystem is False
    assert proof.clean_unavailable_reason == "needs-auth"
    assert proof.launcher_removed_after_rollback is True
    assert proof.manifest_removed_after_rollback is True
    assert proof.cleanup_user_state_removed is True
    assert proof.cleanup_payload_removed is True
    assert proof.cleanup_receipt_forgotten is True
    assert proof.cleanup_receipt_absent is True
    assert proof.target_detached is True
    assert marker_path.is_file()
    assert sorted(path.relative_to(clean_home) for path in clean_home.rglob("*")) == [
        Path(_MOD.EXTERNAL_CLEAN_USER_MARKER_NAME)
    ]
    assert not any(
        path.exists() or path.is_symlink()
        for path in _MOD._external_clean_user_guard_paths(clean_home.resolve())
    )
    assert provisioner_commands
    assert installer_cli_calls[0][0] == "--install-adapter-package"
    assert installer_cli_calls[1][0] == "--install"
    assert installer_cli_calls[2][0] == "--doctor"
    assert lifecycle_commands[0][0] == "/usr/sbin/installer"
