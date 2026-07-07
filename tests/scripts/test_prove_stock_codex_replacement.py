"""Tests for ``scripts/prove_stock_codex_replacement.py``."""

from __future__ import annotations

import importlib.util
import json
import os
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
    assert proof.clean_cache_root == (
        proof.clean_home / ".local" / "omnigent" / "codex-stock"
    )
    assert proof.provisioned_codex_path == proof.clean_cache_root / "0.142.2" / "codex"
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
    assert str(proof.provisioned_codex_path) in proof.onboarding_command


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
) -> None:
    captured_build_args: list[str] = []
    distribution_commands: list[list[str]] = []

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
        del repo_root
        captured_build_args.extend(args)
        output_path = Path(args[args.index("--output") + 1])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"signed pkg fixture")
        package_sha = _MOD.sha256_file(output_path)
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
                stdout='{"id":"notary-submission-1","status":"Accepted"}',
                stderr="",
            )
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
    )

    assert proof.status == "replacement-ready"
    assert proof.signed is True
    assert proof.signature_status == "signed by a certificate trusted by macOS"
    assert proof.notary_submission_id == "notary-submission-1"
    assert proof.notary_status == "Accepted"
    assert captured_build_args[captured_build_args.index("--sign-identity") + 1] == (
        "Developer ID Installer: Example (ABCDE12345)"
    )
    assert distribution_commands[0][1:3] == ["notarytool", "submit"]
    assert distribution_commands[0][-3:] == ["--wait", "--output-format", "json"]
    assert distribution_commands[1][1:3] == ["stapler", "staple"]
    assert distribution_commands[2][1:3] == ["stapler", "validate"]
    assert distribution_commands[3][:5] == ["/usr/sbin/spctl", "-a", "-vv", "-t", "install"]
