"""Tests for ``scripts/update_stock_codex_compat.py``."""

from __future__ import annotations

import importlib.util
import json
import plistlib
import subprocess
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "update_stock_codex_compat.py"


def _load_module() -> Any:
    spec = importlib.util.spec_from_file_location(
        "scripts_update_stock_codex_compat",
        _SCRIPT_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_MOD = _load_module()


def _write_file(path: Path, text: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _write_runtime(root: Path) -> Path:
    _write_file(root / "pyproject.toml", "[project]\nname = 'omnigent-test'\n")
    _write_file(root / "scripts" / "provision_stock_codex.py", "#!/usr/bin/env python3\n")
    _write_file(root / "scripts" / "update_stock_codex_compat.py", "#!/usr/bin/env python3\n")
    return root


def _write_uvx(path: Path) -> Path:
    _write_file(path, "#!/bin/sh\nexit 0\n")
    path.chmod(0o755)
    return path


def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    _write_file(path, json.dumps(payload) + "\n")
    return path


def test_update_writes_launch_agent_and_promotes_ready_target(
    tmp_path: Path,
    monkeypatch: Any,
    capsys: Any,
) -> None:
    runtime_root = _write_runtime(tmp_path / "runtime")
    uvx_path = _write_uvx(tmp_path / "bin" / "uvx")
    cache_root = tmp_path / "home" / ".local" / "omnigent" / "codex-stock"
    current_codex = tmp_path / "current" / "codex"
    _write_file(current_codex, "#!/bin/sh\nexit 0\n")
    current_codex.chmod(0o755)
    target_codex = cache_root / "0.143.0" / "codex"
    launcher_manifest = _write_json(
        tmp_path / "home" / ".local" / "omnigent" / "launchers" / "stock-codex-compat.json",
        {
            "schemaVersion": 1,
            "kind": "omnigent-stock-codex-compat-launcher",
            "pinnedCodexPath": str(current_codex),
            "env": {"OMNIGENT_STOCK_CODEX_PATH": str(current_codex)},
        },
    )
    channel_manifest = _write_json(
        tmp_path / "channel.json",
        {
            "schemaVersion": 1,
            "kind": "omnigent-stock-codex-channel",
            "latest": "0.143.0",
            "artifacts": [],
        },
    )
    launch_agent_path = tmp_path / "home" / "Library" / "LaunchAgents" / "agent.plist"
    rollback_metadata = tmp_path / "home" / ".local" / "omnigent" / "launchers" / "rollback.json"
    calls: list[list[str]] = []

    def fake_run(
        cmd: list[str],
        *,
        check: bool = False,
        capture_output: bool = False,
        text: bool = False,
        timeout: float | None = None,
    ) -> subprocess.CompletedProcess[str]:
        del check, capture_output, text, timeout
        calls.append(cmd)
        if "--promote-update" in cmd:
            payload = {
                "kind": "omnigent-stock-codex-update-promotion",
                "schemaVersion": 1,
                "action": "promoted",
                "mutatesFilesystem": True,
                "launcherManifest": {
                    "manifestPath": str(launcher_manifest),
                    "field": "pinnedCodexPath",
                    "from": str(current_codex),
                    "to": str(target_codex),
                    "env": {"OMNIGENT_STOCK_CODEX_PATH": str(target_codex)},
                },
                "rollback": {
                    "metadataPath": str(rollback_metadata),
                    "codexPath": str(current_codex),
                    "payloadRetention": "versioned-cache-keeps-previous-payload",
                },
            }
        else:
            payload = {
                "kind": "omnigent-stock-codex-update-plan",
                "schemaVersion": 1,
                "action": "staged",
                "mutatesFilesystem": True,
                "promotion": {
                    "required": True,
                    "ready": True,
                    "launcherManifest": {
                        "manifestPath": str(launcher_manifest),
                        "field": "pinnedCodexPath",
                        "from": str(current_codex),
                        "to": str(target_codex),
                        "updateRequired": True,
                        "ready": True,
                    },
                },
                "target": {
                    "state": "ready",
                    "payloadDir": str(target_codex.parent),
                    "codexPath": str(target_codex),
                    "error": None,
                },
            }
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(_MOD.subprocess, "run", fake_run)

    exit_code = _MOD.main(
        [
            "--runtime-root",
            str(runtime_root),
            "--uvx-path",
            str(uvx_path),
            "--cache-root",
            str(cache_root),
            "--channel-manifest",
            str(channel_manifest),
            "--expected-sha256",
            "a" * 64,
            "--launcher-manifest",
            str(launcher_manifest),
            "--rollback-metadata",
            str(rollback_metadata),
            "--allow-remote-channel-download",
            "--write-launch-agent",
            "--run-now",
            "--launch-agent-path",
            str(launch_agent_path),
            "--start-interval",
            "3600",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    plist = plistlib.loads(launch_agent_path.read_bytes())

    assert exit_code == 0
    assert payload["kind"] == _MOD.UPDATE_KIND
    assert payload["action"] == "promoted"
    assert payload["mutatesFilesystem"] is True
    assert payload["launchAgent"]["written"] is True
    assert payload["launchAgent"]["startInterval"] == 3600
    assert plist["Label"] == _MOD.DEFAULT_LAUNCH_AGENT_LABEL
    assert plist["RunAtLoad"] is True
    assert plist["StartInterval"] == 3600
    program_arguments = plist["ProgramArguments"]
    assert program_arguments[:4] == [str(uvx_path), "--from", str(runtime_root), "python"]
    assert program_arguments[4] == str(runtime_root / "scripts" / "update_stock_codex_compat.py")
    assert "--write-launch-agent" not in program_arguments
    assert "--run-now" not in program_arguments
    assert "--current-codex" not in program_arguments
    assert "--allow-remote-channel-download" in program_arguments
    assert len(calls) == 2
    assert "--allow-remote-channel-download" in calls[0]
    assert "--promote-update" not in calls[0]
    assert "--promote-update" in calls[1]
    assert "--allow-remote-channel-download" not in calls[1]
    assert "--current-codex" not in calls[0]
    assert "--current-codex" not in calls[1]


def test_update_skips_promotion_when_plan_is_up_to_date(
    tmp_path: Path,
    monkeypatch: Any,
    capsys: Any,
) -> None:
    runtime_root = _write_runtime(tmp_path / "runtime")
    uvx_path = _write_uvx(tmp_path / "bin" / "uvx")
    cache_root = tmp_path / "cache"
    codex_path = cache_root / "0.143.0" / "codex"
    launcher_manifest = _write_json(
        tmp_path / "launcher.json",
        {
            "schemaVersion": 1,
            "kind": "omnigent-stock-codex-compat-launcher",
            "pinnedCodexPath": str(codex_path),
            "env": {"OMNIGENT_STOCK_CODEX_PATH": str(codex_path)},
        },
    )
    channel_manifest = _write_json(
        tmp_path / "channel.json",
        {"schemaVersion": 1, "kind": "omnigent-stock-codex-channel", "artifacts": []},
    )
    calls: list[list[str]] = []

    def fake_run(
        cmd: list[str],
        *,
        check: bool = False,
        capture_output: bool = False,
        text: bool = False,
        timeout: float | None = None,
    ) -> subprocess.CompletedProcess[str]:
        del check, capture_output, text, timeout
        calls.append(cmd)
        payload = {
            "kind": "omnigent-stock-codex-update-plan",
            "schemaVersion": 1,
            "action": "up-to-date",
            "mutatesFilesystem": False,
            "promotion": {"required": False, "ready": True},
        }
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(_MOD.subprocess, "run", fake_run)

    exit_code = _MOD.main(
        [
            "--runtime-root",
            str(runtime_root),
            "--uvx-path",
            str(uvx_path),
            "--cache-root",
            str(cache_root),
            "--channel-manifest",
            str(channel_manifest),
            "--launcher-manifest",
            str(launcher_manifest),
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["action"] == "up-to-date"
    assert payload["mutatesFilesystem"] is False
    assert payload["launchAgent"]["written"] is False
    assert payload["promotion"] is None
    assert len(calls) == 1
