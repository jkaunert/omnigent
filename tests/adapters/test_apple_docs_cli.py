"""Tests for the Apple documentation CLI adapter policy."""

from __future__ import annotations

import importlib.util
import os
import subprocess
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from omnigent.adapters.apple_docs_cli import (
    APPLE_DOCS_CLI_TOOL_NAME,
    APPLE_DOCS_CLI_URL,
    SOSUMI_CLI_COMMAND,
    AppleDocsCliAdapterPolicy,
    build_fetch_apple_docs_cli_tool_source,
    build_fetch_apple_docs_stock_codex_adapter_spec,
    build_fetch_apple_docs_stock_codex_bridge_adapter_spec,
    build_fetch_apple_docs_stock_codex_bridge_handler,
    write_fetch_apple_docs_cli_tool,
)
from omnigent.adapters.stock_codex_compat import (
    build_stock_codex_compat_adapter_manifest,
    write_stock_codex_compat_adapter_package,
)


def _load_module(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location("generated_fetch_apple_docs", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_policy_installs_when_sosumi_mcp_server_is_present() -> None:
    policy = AppleDocsCliAdapterPolicy()

    decision = policy.decide_for_mcp_servers({"sosumi": {"command": "npx"}})

    assert decision.install is True
    assert "sosumi" in decision.reason
    assert "existing MCP config is unchanged" in decision.reason


def test_policy_does_not_install_when_sosumi_mcp_server_is_absent() -> None:
    policy = AppleDocsCliAdapterPolicy()

    decision = policy.decide_for_mcp_servers({"memory": {"command": "npx"}})

    assert decision.install is False
    assert "absent" in decision.reason


@pytest.mark.parametrize(
    "url",
    [
        "http://developer.apple.com/documentation/swift/string",
        "https://developer.apple.com:444/documentation/swift/string",
        "https://user:pass@developer.apple.com/documentation/swift/string",
        "https://example.com/documentation/swift/string",
        "https://developer.apple.com/search/",
    ],
)
def test_policy_rejects_urls_outside_apple_docs_surface(url: str) -> None:
    policy = AppleDocsCliAdapterPolicy()

    with pytest.raises(ValueError):
        policy.command_for_url(url)


def test_policy_builds_sosumi_cli_command_for_valid_apple_docs_url() -> None:
    policy = AppleDocsCliAdapterPolicy()

    command = policy.command_for_url(APPLE_DOCS_CLI_URL)

    assert command == [*SOSUMI_CLI_COMMAND, APPLE_DOCS_CLI_URL]


def test_generated_tool_source_names_expected_tool() -> None:
    source = build_fetch_apple_docs_cli_tool_source()

    assert f"def {APPLE_DOCS_CLI_TOOL_NAME}(url: str) -> str:" in source
    assert "developer.apple.com" in source
    assert "@nshipster/sosumi" in source


def test_generated_tool_validates_url_before_calling_cli(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tool_path = write_fetch_apple_docs_cli_tool(tmp_path)
    module = _load_module(tool_path)
    calls: list[tuple[list[str], dict[str, Any]]] = []

    def fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append((cmd, kwargs))
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout=(
                "---\n"
                "title: String\n"
                "source: https://developer.apple.com/documentation/swift/string\n"
                "timestamp: 2026-06-25T23:25:03.564Z\n"
                "---\n"
            ),
            stderr="",
        )

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    invalid_result = module.fetch_apple_docs("https://example.com/documentation/swift/string")
    valid_result = module.fetch_apple_docs(APPLE_DOCS_CLI_URL)

    assert invalid_result.startswith("Error: url must be an https://developer.apple.com")
    assert calls == [
        (
            [*SOSUMI_CLI_COMMAND, APPLE_DOCS_CLI_URL],
            {
                "check": False,
                "capture_output": True,
                "text": True,
                "timeout": 30,
            },
        )
    ]
    assert "title: String" in valid_result


def test_stock_codex_adapter_spec_uses_closed_url_schema(tmp_path: Path) -> None:
    spec = build_fetch_apple_docs_stock_codex_adapter_spec()

    manifest = build_stock_codex_compat_adapter_manifest(tmp_path / "bin", (spec,))

    assert manifest["tools"][0]["name"] == APPLE_DOCS_CLI_TOOL_NAME
    assert manifest["tools"][0]["parameters"]["required"] == ["url"]
    assert manifest["tools"][0]["parameters"]["additionalProperties"] is False
    assert manifest["tools"][0]["parameters"]["properties"]["url"]["type"] == "string"


def test_stock_codex_bridge_adapter_spec_uses_closed_url_schema(tmp_path: Path) -> None:
    spec = build_fetch_apple_docs_stock_codex_bridge_adapter_spec()

    manifest = build_stock_codex_compat_adapter_manifest(tmp_path / "bin", (spec,))

    assert manifest["tools"][0]["name"] == APPLE_DOCS_CLI_TOOL_NAME
    assert manifest["tools"][0]["parameters"]["required"] == ["url"]
    assert manifest["tools"][0]["parameters"]["additionalProperties"] is False
    assert manifest["tools"][0]["parameters"]["properties"]["url"]["type"] == "string"
    assert "OMNIGENT_STOCK_CODEX_COMPAT_ADAPTER_BRIDGE_DIR" in spec.command_source


def test_stock_codex_bridge_handler_fetches_valid_apple_docs_url(
    tmp_path: Path,
) -> None:
    fake_sosumi = tmp_path / "sosumi"
    fake_sosumi.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" != \"fetch\" ] || "
        "[ \"$2\" != \"https://developer.apple.com/documentation/swift/string\" ]; then\n"
        "  echo unexpected command >&2\n"
        "  exit 66\n"
        "fi\n"
        "cat <<'EOF'\n"
        "---\n"
        "title: String\n"
        "source: https://developer.apple.com/documentation/swift/string\n"
        "timestamp: 2026-06-25T23:25:03.564Z\n"
        "---\n"
        "EOF\n",
        encoding="utf-8",
    )
    fake_sosumi.chmod(0o755)
    policy = AppleDocsCliAdapterPolicy(
        command_prefix=(str(fake_sosumi), "fetch"),
        timeout_seconds=5,
    )
    handler = build_fetch_apple_docs_stock_codex_bridge_handler(policy)

    response = handler({"url": APPLE_DOCS_CLI_URL})

    assert response.status == "ok"
    assert response.exitCode == 0
    assert "title: String" in response.stdout
    assert f"source: {APPLE_DOCS_CLI_URL}" in response.stdout


def test_stock_codex_adapter_command_fetches_valid_apple_docs_url(
    tmp_path: Path,
) -> None:
    spec = build_fetch_apple_docs_stock_codex_adapter_spec()
    package = write_stock_codex_compat_adapter_package(tmp_path / "adapter-package", (spec,))
    fake_bin = tmp_path / "fake-bin"
    fake_npx = fake_bin / "npx"
    fake_bin.mkdir()
    fake_npx.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" != \"-y\" ] || [ \"$2\" != \"@nshipster/sosumi\" ] || "
        "[ \"$3\" != \"fetch\" ]; then\n"
        "  echo unexpected command >&2\n"
        "  exit 66\n"
        "fi\n"
        "cat <<'EOF'\n"
        "---\n"
        "title: String\n"
        "source: https://developer.apple.com/documentation/swift/string\n"
        "timestamp: 2026-06-25T23:25:03.564Z\n"
        "---\n"
        "EOF\n",
        encoding="utf-8",
    )
    fake_npx.chmod(0o755)

    completed = subprocess.run(
        [str(package.adapter_bin / APPLE_DOCS_CLI_TOOL_NAME), "--url", APPLE_DOCS_CLI_URL],
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}"},
    )

    assert "title: String" in completed.stdout
    assert f"source: {APPLE_DOCS_CLI_URL}" in completed.stdout


def test_stock_codex_adapter_command_rejects_invalid_url(tmp_path: Path) -> None:
    spec = build_fetch_apple_docs_stock_codex_adapter_spec()
    package = write_stock_codex_compat_adapter_package(tmp_path / "adapter-package", (spec,))

    completed = subprocess.run(
        [
            str(package.adapter_bin / APPLE_DOCS_CLI_TOOL_NAME),
            "--url",
            "https://example.com/documentation/swift/string",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 64
    assert "developer.apple.com" in completed.stderr
