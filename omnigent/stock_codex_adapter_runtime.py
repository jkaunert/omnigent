"""Runtime assembly for stock-Codex adapter bridge services."""

from __future__ import annotations

import json
import shutil
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

from omnigent.adapters.apple_docs_cli import (
    DEFAULT_APPLE_DOCS_CLI_POLICY,
    AppleDocsCliAdapterPolicy,
    build_fetch_apple_docs_stock_codex_bridge_handler,
)
from omnigent.adapters.xcodebuild_cli import (
    DEFAULT_XCODEBUILD_CLI_POLICY,
    XcodeBuildCliAdapterPolicy,
    build_xcodebuildmcp_simulator_build_run_stock_codex_bridge_handler,
)
from omnigent.stock_codex_adapter_bridge import (
    AdapterBridgeHandler,
    FileBridgeAdapterService,
)

APPLE_DOCS_BRIDGE_HANDLER_TIMEOUT_SECONDS = 120
APPLE_DOCS_BRIDGE_CAPABILITY = "apple-docs"
XCODEBUILD_BRIDGE_CAPABILITY = "xcodebuildmcp-simulator-build-run"
SUPPORTED_STOCK_CODEX_BRIDGE_CAPABILITIES = (
    APPLE_DOCS_BRIDGE_CAPABILITY,
    XCODEBUILD_BRIDGE_CAPABILITY,
)


def build_stock_codex_adapter_bridge_service(
    bridge_dir: Path,
    *,
    adapter_manifest: Path | None,
    thread_name: str = "omnigent-stock-codex-adapter-runtime-bridge",
) -> FileBridgeAdapterService:
    """Build the runtime file-bridge service for a stock-Codex adapter package."""
    return FileBridgeAdapterService(
        bridge_dir,
        build_stock_codex_adapter_bridge_handlers(adapter_manifest=adapter_manifest),
        thread_name=thread_name,
    )


def build_stock_codex_adapter_bridge_handlers(
    *,
    adapter_manifest: Path | None,
    apple_docs_policy: AppleDocsCliAdapterPolicy | None = None,
    xcodebuild_policy: XcodeBuildCliAdapterPolicy | None = None,
) -> dict[str, AdapterBridgeHandler]:
    """Build wrapper-side bridge handlers for supported adapter manifest entries."""
    if adapter_manifest is None:
        return {}

    handlers: dict[str, AdapterBridgeHandler] = {}
    for tool in _read_manifest_tools(adapter_manifest):
        name = tool.get("name")
        capability = tool.get("capability")
        if not isinstance(name, str) or not isinstance(capability, str):
            continue
        if capability == APPLE_DOCS_BRIDGE_CAPABILITY:
            handlers[name] = build_fetch_apple_docs_stock_codex_bridge_handler(
                apple_docs_policy or _default_apple_docs_bridge_policy()
            )
        elif capability == XCODEBUILD_BRIDGE_CAPABILITY:
            handlers[name] = (
                build_xcodebuildmcp_simulator_build_run_stock_codex_bridge_handler(
                    xcodebuild_policy or DEFAULT_XCODEBUILD_CLI_POLICY
                )
            )
    return handlers


def _default_apple_docs_bridge_policy() -> AppleDocsCliAdapterPolicy:
    """Prefer a locally installed Sosumi CLI, while keeping npx as the fallback."""
    sosumi_cli_path = shutil.which("sosumi")
    command_prefix = (
        (sosumi_cli_path, "fetch")
        if sosumi_cli_path is not None
        else DEFAULT_APPLE_DOCS_CLI_POLICY.command_prefix
    )
    return replace(
        DEFAULT_APPLE_DOCS_CLI_POLICY,
        command_prefix=command_prefix,
        timeout_seconds=APPLE_DOCS_BRIDGE_HANDLER_TIMEOUT_SECONDS,
    )


def _read_manifest_tools(adapter_manifest: Path) -> list[Mapping[str, Any]]:
    payload = json.loads(adapter_manifest.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return []
    tools = payload.get("tools")
    if not isinstance(tools, list):
        return []
    return [tool for tool in tools if isinstance(tool, Mapping)]
