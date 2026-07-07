"""Tests for ``scripts/bootstrap_stock_codex_compat.py``."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "bootstrap_stock_codex_compat.py"
_SHELL_SCRIPT_PATH = _REPO_ROOT / "scripts" / "bootstrap_stock_codex_compat.sh"


def _load_module() -> Any:
    spec = importlib.util.spec_from_file_location(
        "scripts_bootstrap_stock_codex_compat",
        _SCRIPT_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_MOD = _load_module()


def _write_file(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _write_executable(path: Path, text: str) -> Path:
    _write_file(path, text)
    path.chmod(0o755)
    return path


def _write_runtime(path: Path) -> Path:
    _write_file(path / "pyproject.toml", "[project]\nname = 'omnigent-test'\n")
    _write_file(path / "scripts" / "provision_stock_codex.py", "")
    _write_file(path / "scripts" / "install_stock_codex_compat_launcher.py", "")
    _write_file(path / "omnigent" / "stock_codex_compat_wrapper.py", "")
    return path


def _write_fake_uvx(path: Path) -> Path:
    return _write_executable(
        path,
        """#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

args = sys.argv[1:]
log_path = os.environ.get("FAKE_UVX_LOG")
if log_path:
    with open(log_path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(args) + "\\n")
script = args[args.index("python") + 1]
script_args = args[args.index("python") + 2:]

def value_after(name):
    return script_args[script_args.index(name) + 1]

if script.endswith("provision_stock_codex.py"):
    cache_root = Path(value_after("--cache-root"))
    codex_path = cache_root / "0.142.5" / "codex"
    codex_path.parent.mkdir(parents=True, exist_ok=True)
    codex_path.write_text("#!/bin/sh\\necho codex-cli 0.142.5\\n", encoding="utf-8")
    codex_path.chmod(0o755)
    print(json.dumps({
        "codexPath": str(codex_path),
        "version": "codex-cli 0.142.5",
        "versionSlug": "0.142.5",
        "sourceKind": "channel",
    }))
elif (
    script.endswith("install_stock_codex_compat_launcher.py")
    and "--install-adapter-package" in script_args
):
    package_dir = Path(value_after("--adapter-package-dir"))
    (package_dir / "bin").mkdir(parents=True, exist_ok=True)
    manifest = package_dir / "adapter-manifest.json"
    manifest.write_text("{}", encoding="utf-8")
    print(json.dumps({
        "action": "adapter-package-installed",
        "adapterPackageDir": str(package_dir),
        "adapterBin": str(package_dir / "bin"),
        "adapterManifest": str(manifest),
        "adapterToolNames": ["fetch_apple_docs"],
        "mutatesFilesystem": True,
    }))
elif script.endswith("install_stock_codex_compat_launcher.py") and "--install" in script_args:
    launcher = Path(value_after("--launcher-path"))
    manifest = Path(value_after("--manifest-path"))
    pinned = value_after("--pinned-codex-path")
    launcher.parent.mkdir(parents=True, exist_ok=True)
    launcher.write_text("#!/bin/sh\\nexec " + pinned + " \\"$@\\"\\n", encoding="utf-8")
    launcher.chmod(0o755)
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps({"pinnedCodexPath": pinned}) + "\\n", encoding="utf-8")
    print(json.dumps({
        "action": "installed",
        "launcherPath": str(launcher),
        "manifestPath": str(manifest),
        "pinnedCodexPath": pinned,
    }))
elif script.endswith("install_stock_codex_compat_launcher.py") and "--doctor" in script_args:
    print(json.dumps({
        "action": "doctor",
        "installAllowed": True,
        "existingTargetState": "managed",
        "targetSelectedOnPath": True,
        "mutatesFilesystem": False,
    }))
else:
    raise SystemExit("unexpected fake uvx invocation: " + repr(args))
""",
    )


def _write_fake_uvx_logger(path: Path) -> Path:
    return _write_executable(
        path,
        """#!/usr/bin/env python3
import json
import os
import sys

with open(os.environ["FAKE_UVX_LOG"], "w", encoding="utf-8") as handle:
    handle.write(json.dumps(sys.argv[1:]) + "\\n")
""",
    )


def test_shell_bootstrap_stages_runtime_before_uvx(tmp_path: Path) -> None:
    source_runtime = tmp_path / "source-runtime"
    _write_file(source_runtime / "pyproject.toml", "[project]\nname = 'shell-test'\n")
    _write_file(source_runtime / "scripts" / "bootstrap_stock_codex_compat.py", "")
    _write_file(source_runtime / "marker.txt", "copied\n")
    user_runtime = tmp_path / "home" / ".local" / "omnigent" / "runtime"
    fake_uvx = _write_fake_uvx_logger(tmp_path / "tools" / "uvx")
    log_path = tmp_path / "uvx.log"

    completed = subprocess.run(
        [
            str(_SHELL_SCRIPT_PATH),
            "--source-runtime-root",
            str(source_runtime),
            "--user-runtime-root",
            str(user_runtime),
            "--uvx-path",
            str(fake_uvx),
            "--channel-manifest",
            str(tmp_path / "channel.json"),
            "--expected-sha256",
            "0" * 64,
        ],
        check=False,
        capture_output=True,
        env={**os.environ, "FAKE_UVX_LOG": str(log_path), "HOME": str(tmp_path / "home")},
        text=True,
    )

    assert completed.returncode == 0
    assert (user_runtime / "marker.txt").read_text(encoding="utf-8") == "copied\n"
    invocation = json.loads(log_path.read_text(encoding="utf-8"))
    assert invocation[:3] == ["--from", str(user_runtime), "python"]
    assert invocation[3] == str(user_runtime / "scripts" / "bootstrap_stock_codex_compat.py")
    assert "--staged-runtime-root" in invocation
    assert invocation[invocation.index("--staged-runtime-root") + 1] == str(user_runtime)


def test_shell_bootstrap_reports_missing_source_runtime(tmp_path: Path) -> None:
    fake_uvx = _write_fake_uvx_logger(tmp_path / "tools" / "uvx")

    completed = subprocess.run(
        [
            str(_SHELL_SCRIPT_PATH),
            "--source-runtime-root",
            str(tmp_path / "missing-runtime"),
            "--user-runtime-root",
            str(tmp_path / "home" / ".local" / "omnigent" / "runtime"),
            "--uvx-path",
            str(fake_uvx),
            "--channel-manifest",
            str(tmp_path / "channel.json"),
            "--expected-sha256",
            "0" * 64,
        ],
        check=False,
        capture_output=True,
        env={
            **os.environ,
            "FAKE_UVX_LOG": str(tmp_path / "uvx.log"),
            "HOME": str(tmp_path / "home"),
        },
        text=True,
    )

    assert completed.returncode == 70
    assert (
        "omnigent_stock_codex_compat_bootstrap_error=source runtime root missing"
        in completed.stderr
    )


def test_bootstrap_uses_staged_runtime_to_provision_and_install(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    staged_runtime = _write_runtime(tmp_path / "runtime")
    fake_uvx = _write_fake_uvx(tmp_path / "tools" / "uvx")
    channel_manifest = _write_file(tmp_path / "channel.json", "{}\n")
    cache_root = tmp_path / "home" / ".local" / "omnigent" / "codex-stock"
    launcher_path = tmp_path / "home" / ".local" / "bin" / "omnigent-stock-codex-compat"
    manifest_path = (
        tmp_path
        / "home"
        / ".local"
        / "omnigent"
        / "launchers"
        / "stock-codex-compat.json"
    )
    adapter_package_dir = (
        tmp_path
        / "home"
        / ".local"
        / "omnigent"
        / "stock-codex-compat"
        / "adapter-package"
    )
    adapter_bridge_dir = (
        tmp_path
        / "home"
        / ".local"
        / "omnigent"
        / "stock-codex-compat"
        / "adapter-bridge"
    )
    log_path = tmp_path / "uvx.log"
    monkeypatch.setenv("FAKE_UVX_LOG", str(log_path))

    exit_code = _MOD.main(
        [
            "--staged-runtime-root",
            str(staged_runtime),
            "--uvx-path",
            str(fake_uvx),
            "--cache-root",
            str(cache_root),
            "--channel-manifest",
            str(channel_manifest),
            "--expected-sha256",
            "0" * 64,
            "--launcher-path",
            str(launcher_path),
            "--manifest-path",
            str(manifest_path),
            "--adapter-package-dir",
            str(adapter_package_dir),
            "--adapter-bridge-dir",
            str(adapter_bridge_dir),
            "--require-path-selected",
            "--force",
            "--json",
        ]
    )

    assert exit_code == 0
    assert launcher_path.is_file()
    assert manifest_path.is_file()
    assert (cache_root / "0.142.5" / "codex").is_file()
    invocations = [
        json.loads(line)
        for line in log_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert all(args[args.index("--from") + 1] == str(staged_runtime) for args in invocations)
    assert any(any("provision_stock_codex.py" in item for item in args) for args in invocations)
    assert any("--install-adapter-package" in args for args in invocations)
    assert any("--install" in args for args in invocations)
    assert any("--doctor" in args for args in invocations)
