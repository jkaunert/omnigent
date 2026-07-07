#!/usr/bin/env python3
"""Proof gate for the Omnigent stock-Codex replacement track.

This script is intentionally local/operator-facing. It does not modify the
Codex fork. It copies an Apple workflow bundle into a temporary Omnigent agent,
verifies the selected top-level skill graph is present, then can run a live
stock-Codex proof through Omnigent's normal ``run_prompt()`` session/runner path.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import plistlib
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, TypeVar
from urllib.parse import urlparse

from omnigent_client import OmnigentClient

from omnigent import codex_native, codex_native_bridge, stock_codex_compat_wrapper
from omnigent.adapters.apple_docs_cli import (
    APPLE_DOCS_CLI_URL,
    DEFAULT_APPLE_DOCS_CLI_POLICY,
    build_fetch_apple_docs_stock_codex_adapter_spec,
    build_fetch_apple_docs_stock_codex_bridge_adapter_spec,
    write_fetch_apple_docs_cli_tool,
)
from omnigent.adapters.stock_codex_compat import (
    StockCodexCompatAdapterToolSpec,
    write_stock_codex_compat_adapter_command,
    write_stock_codex_compat_adapter_manifest,
    write_stock_codex_compat_adapter_package,
)
from omnigent.adapters.xcodebuild_cli import (
    DEFAULT_XCODEBUILD_CLI_POLICY,
    OMNIGENT_XCODEBUILDMCP_AXE_PATH_ENV,
    XCODEBUILDMCP_CLI_COMMAND,
    XCODEBUILDMCP_CLI_ENV_OVERRIDES,
    XCODEBUILDMCP_CLI_SCREENSHOT_COMMAND,
    XCODEBUILDMCP_CLI_SNAPSHOT_UI_COMMAND,
    XCODEBUILDMCP_CLI_TAP_COMMAND,
    XCODEBUILDMCP_CLI_TEST_COMMAND,
    XCODEBUILDMCP_CLI_TYPE_TEXT_COMMAND,
    build_xcodebuildmcp_simulator_build_run_stock_codex_bridge_adapter_spec,
    write_xcodebuildmcp_simulator_build_run_tool,
    write_xcodebuildmcp_simulator_runtime_logs_tool,
    write_xcodebuildmcp_simulator_screenshot_tool,
    write_xcodebuildmcp_simulator_snapshot_ui_tool,
    write_xcodebuildmcp_simulator_tap_tool,
    write_xcodebuildmcp_simulator_test_tool,
    write_xcodebuildmcp_simulator_type_text_tool,
)
from omnigent.chat import (
    ChatOverrides,
    _bundle_agent,
    _canonicalize_local_agent_path,
    _cleanup_materialized_override_bundle,
    _extract_agent_name,
    _find_free_port,
    _materialize_override_bundle,
    _query_sessions_once,
    _server_auth,
    _server_headers,
    _start_local_server,
    _stop_local_server,
    _validate_agent_spec,
    _wait_for_server,
    run_prompt,
)
from omnigent.claude_native_bridge import start_tool_relay
from omnigent.codex_native_app_server import (
    _inject_mcp_server_config,
    _write_codex_policy_hooks_file,
)
from omnigent.codex_native_bridge import (
    write_mcp_bridge_config,
    write_policy_hook_config,
)
from omnigent.inner.codex_executor import (
    OMNIGENT_STOCK_CODEX_PATH_ENV,
    _find_codex_cli,
    _resolve_managed_codex_launcher,
)

PLUGIN_NAME = "apple-appdev-workflow"
SELECTED_SKILL = "apple-app-orchestrator"
SELECTED_OWNER = f"{PLUGIN_NAME}:{SELECTED_SKILL}"
EXPECTED_ROUTE = f"Routing: orchestrator-led\n\nActivated skills\n- `{SELECTED_OWNER}`"
REFERENCE_SENTINEL = "Use this shared contract for broad brigade-orchestrator lanes"
TOOL_SENTINEL = "OMNIGENT_TOOL_SENTINEL_42"
ROUTER_MATRIX_REVIEW_OWNER = f"{PLUGIN_NAME}:apple-review-orchestrator"
ROUTER_MATRIX_FOCUSED_OWNER = f"{PLUGIN_NAME}:apple-decision-stress-test"
ROUTER_MATRIX_PROMPT_SIGNAL_SENTINEL = "ROUTER_MATRIX_PROMPT_SIGNAL_OK"
ROUTER_MATRIX_XCODE_HOST_SENTINEL = "ROUTER_MATRIX_XCODE_HOST_OK"
ROUTER_MATRIX_WORKSPACE_FILE_SENTINEL = "ROUTER_MATRIX_WORKSPACE_FILE_OK"
ROUTER_MATRIX_WORKSPACE_EXTENSION_SENTINEL = "ROUTER_MATRIX_WORKSPACE_EXTENSION_OK"
ROUTER_MATRIX_DOWNSTREAM_ROUTE_SENTINEL = "ROUTER_MATRIX_DOWNSTREAM_ROUTE_OK"
ROUTER_MATRIX_FOCUSED_SUPPRESS_SENTINEL = "ROUTER_MATRIX_FOCUSED_SUPPRESS_OK"
ROUTER_MATRIX_NON_MATCHING_HOST_SENTINEL = "ROUTER_MATRIX_NON_MATCHING_HOST_OK"
APPLE_MCP_MEMORY_SERVER = "memory"
APPLE_MCP_MEMORY_TOOL = "memory__create_entities"
APPLE_MCP_MEMORY_SENTINEL = "APPLE_MCP_SENTINEL_73"
APPLE_DOCS_CLI_POLICY = DEFAULT_APPLE_DOCS_CLI_POLICY
APPLE_MCP_SOSUMI_SERVER = APPLE_DOCS_CLI_POLICY.mcp_server_name
APPLE_MCP_SOSUMI_TOOL = "sosumi__fetchAppleDocumentation"
APPLE_MCP_SOSUMI_DOC_PATH = "/documentation/swift/string"
APPLE_DOCS_CLI_TOOL = APPLE_DOCS_CLI_POLICY.tool_name
APPLE_DOCS_STOCK_COMPAT_TIMEOUT_SECONDS = 120
APPLE_DOCS_STOCK_COMPAT_BRIDGE_TIMEOUT_SECONDS = (
    APPLE_DOCS_STOCK_COMPAT_TIMEOUT_SECONDS + 30
)
APPLE_MCP_SOSUMI_SENTINELS = (
    "title: String",
    "source: https://developer.apple.com/documentation/swift/string",
)
APPLE_MCP_SOSUMI_TIMESTAMP_RE = re.compile(r"^timestamp: (?P<timestamp>\S+)$", re.MULTILINE)
APPLE_MCP_SOSUMI_SESSION_QUERY_TIMEOUT_SECONDS = 75.0
APPLE_MCP_XCODEBUILD_SERVER = "XcodeBuildMCP"
APPLE_MCP_XCODEBUILD_TOOL = "XcodeBuildMCP__discover_projs"
APPLE_MCP_XCODEBUILD_SESSION_SHOW_DEFAULTS_TOOL = "XcodeBuildMCP__session_show_defaults"
APPLE_MCP_XCODEBUILD_SESSION_SET_DEFAULTS_TOOL = "XcodeBuildMCP__session_set_defaults"
APPLE_MCP_XCODEBUILD_BUILD_SIM_TOOL = "XcodeBuildMCP__build_sim"
APPLE_MCP_XCODEBUILD_BUILD_RUN_SIM_TOOL = "XcodeBuildMCP__build_run_sim"
APPLE_MCP_XCODEBUILD_PROJECT_RELATIVE_PATH = "ap-web/ios/Omnigent.xcodeproj"
APPLE_MCP_XCODEBUILD_SCHEME = "Omnigent"
APPLE_MCP_XCODEBUILD_CONFIGURATION = "Debug"
APPLE_MCP_XCODEBUILD_PREFERRED_SIMULATORS = (
    "iPhone 17",
    "iPhone 17 Pro",
    "iPhone 16",
    "iPhone 15",
    "iPhone 14",
)
APPLE_MCP_XCODEBUILD_SENTINELS = (
    "Discovery finished. Found",
    "Projects found:",
    "Omnigent.xcodeproj",
)
APPLE_MCP_XCODEBUILD_BUILD_SENTINELS = (
    "iOS Simulator Build build succeeded",
    "scheme Omnigent",
)
APPLE_MCP_XCODEBUILD_RUN_SENTINELS = (
    "iOS simulator build and run succeeded",
    "scheme Omnigent",
    "ai.omnigent.ios",
    "is now running in the iOS Simulator",
)
XCODEBUILD_CLI_POLICY = DEFAULT_XCODEBUILD_CLI_POLICY
XCODEBUILD_CLI_TOOL = XCODEBUILD_CLI_POLICY.tool_name
XCODEBUILD_CLI_TEST_TOOL = XCODEBUILD_CLI_POLICY.test_tool_name
XCODEBUILD_CLI_SCREENSHOT_TOOL = XCODEBUILD_CLI_POLICY.screenshot_tool_name
XCODEBUILD_CLI_SNAPSHOT_UI_TOOL = XCODEBUILD_CLI_POLICY.snapshot_ui_tool_name
XCODEBUILD_CLI_RUNTIME_LOGS_TOOL = XCODEBUILD_CLI_POLICY.runtime_logs_tool_name
XCODEBUILD_CLI_TYPE_TEXT_TOOL = XCODEBUILD_CLI_POLICY.type_text_tool_name
XCODEBUILD_CLI_TAP_TOOL = XCODEBUILD_CLI_POLICY.tap_tool_name
XCODEBUILD_CLI_STOCK_COMPAT_BRIDGE_TIMEOUT_SECONDS = (
    XCODEBUILD_CLI_POLICY.timeout_seconds + 60
)
XCODEBUILD_CLI_TYPE_TEXT_PROOF_TEXT = "http://localhost:6767/gesture-proof"
XCODEBUILD_CLI_TAP_PROOF_TEXT = "http://localhost:6767/gesture-proof"
XCODEBUILD_CLI_TAP_POST_TEXT = "http://localhost:6767"
XCODEBUILD_CLI_RUN_SENTINELS = (
    "Build succeeded",
    "Build & Run complete",
    "Bundle ID: ai.omnigent.ios",
)
XCODEBUILD_CLI_TEST_SENTINELS = (
    "9 tests passed",
    "0 failed",
    "0 skipped",
)
XCODEBUILD_CLI_SCREENSHOT_SENTINELS = (
    '"buildStatus": "SUCCEEDED"',
    '"screenshotStatus": "SUCCEEDED"',
    '"bundleId": "ai.omnigent.ios"',
    '"format": "image/jpeg"',
    '"screenshotPath":',
)
XCODEBUILD_CLI_SNAPSHOT_UI_SENTINELS = (
    '"buildStatus": "SUCCEEDED"',
    '"snapshotStatus": "SUCCEEDED"',
    '"bundleId": "ai.omnigent.ios"',
    '"type": "runtime-snapshot"',
    '"count":',
    '"targets":',
)
XCODEBUILD_CLI_RUNTIME_LOGS_SENTINELS = (
    '"buildStatus": "SUCCEEDED"',
    '"launchStatus": "SUCCEEDED"',
    '"bundleId": "ai.omnigent.ios"',
    '"runtimeLogStatus": "SUCCEEDED"',
    '"osLogStatus": "SUCCEEDED"',
    '"runtimeLogExcerpt":',
    '"osLogExcerpt":',
)
XCODEBUILD_CLI_TYPE_TEXT_SENTINELS = (
    '"buildStatus": "SUCCEEDED"',
    '"typeTextStatus": "SUCCEEDED"',
    '"waitStatus": "SUCCEEDED"',
    '"bundleId": "ai.omnigent.ios"',
    '"elementRef":',
    f'"typedText": "{XCODEBUILD_CLI_TYPE_TEXT_PROOF_TEXT}"',
    f'"verifiedText": "{XCODEBUILD_CLI_TYPE_TEXT_PROOF_TEXT}"',
    '"beforeTarget":',
    '"afterTargets":',
)
XCODEBUILD_CLI_TAP_SENTINELS = (
    '"preResetBuildStatus": "SUCCEEDED"',
    '"resetStatus": "SUCCEEDED"',
    '"buildStatus": "SUCCEEDED"',
    '"typeTextStatus": "SUCCEEDED"',
    '"typedWaitStatus": "SUCCEEDED"',
    '"tapStatus": "SUCCEEDED"',
    '"settledStatus": "SUCCEEDED"',
    '"bundleId": "ai.omnigent.ios"',
    f'"typedText": "{XCODEBUILD_CLI_TAP_PROOF_TEXT}"',
    f'"postTapText": "{XCODEBUILD_CLI_TAP_POST_TEXT}"',
    '"tapTarget":',
    '"afterTapTarget":',
)
APPLE_WORKFLOW_SMOKE_SENTINEL = "APPLE_WORKFLOW_SMOKE_OK"
RELATIVE_MARKDOWN_PATH_RE = re.compile(r"`((?:\.\.?/)[^`]+)`")
PLUGIN_SKILL_REF_RE = re.compile(rf"\b{re.escape(PLUGIN_NAME)}:([A-Za-z0-9_.-]+)\b")
EXPECTED_APPLE_MCP_SERVERS = frozenset({"sosumi", "memory", "XcodeBuildMCP"})
DEFAULT_LIVE_PROOF_TIMEOUT_SECONDS = 180.0
DEFAULT_PATH_CUTOVER_FALLBACK_STEPS = (
    "Keep the Codex fork and all carries intact; this rehearsal does not authorize deletion.",
    "If default lookup fails, rerun cutover-ready with explicit --apple-bundle and --codex-path "
    "to separate default-path drift from adapter/runtime failure.",
    "If live stock-Codex execution fails, return launch/PATH selection to the previously proven "
    "Codex-fork route and keep the failed Omnigent evidence for diagnosis.",
    "If temporary cleanup is interrupted, remove only omnigent-stock-codex-proof-* temp trees "
    "after preserving any needed logs.",
)
PKG_SIGN_IDENTITY_ENV = "OMNIGENT_PKG_SIGN_IDENTITY"
PKG_SIGN_KEYCHAIN_ENV = "OMNIGENT_PKG_SIGN_KEYCHAIN"
NOTARYTOOL_PROFILE_ENV = "OMNIGENT_NOTARYTOOL_PROFILE"
LAUNCHER_ACTIVATION_SENTINEL = "OMNIGENT_CODEX_LAUNCHER_ACTIVATION_OK"
LAUNCHER_ACTIVATION_PROBE_ARG = "--omnigent-launcher-probe"
APP_BUNDLE_ENTRYPOINT_NAME = "Omnigent Codex"
APP_BUNDLE_ENTRYPOINT_IDENTIFIER = "ai.omnigent.codex"
APP_BUNDLE_ENTRYPOINT_EXECUTABLE = "omnigent-codex"
APP_BUNDLE_ENTRYPOINT_SENTINEL = "OMNIGENT_CODEX_APP_BUNDLE_ENTRYPOINT_OK"
APP_BUNDLE_ENTRYPOINT_PROBE_ARG = "--omnigent-app-bundle-probe"
STOCK_CODEX_COMPAT_MARKETPLACE = "LocalAppleWorkflow"
STOCK_CODEX_COMPAT_PLUGIN_ID = f"{PLUGIN_NAME}@{STOCK_CODEX_COMPAT_MARKETPLACE}"
STOCK_CODEX_COMPAT_AP_SERVER_URL = "http://127.0.0.1:6767"
STOCK_CODEX_COMPAT_LIVE_SENTINEL = "STOCK_CODEX_COMPAT_LIVE_OK"
STOCK_CODEX_COMPAT_WRAPPER_TOOL_SENTINEL = "STOCK_CODEX_COMPAT_WRAPPER_TOOL_OK"
STOCK_CODEX_COMPAT_WRAPPER_ADAPTER_TOOL_SENTINEL = (
    "STOCK_CODEX_COMPAT_WRAPPER_ADAPTER_TOOL_OK"
)
STOCK_CODEX_COMPAT_ADAPTER_COMMAND_NAME = "omnigent-wrapper-adapter-probe"
STOCK_CODEX_COMPAT_ADAPTER_COMMAND_ARGUMENT = "stock-codex-wrapper-adapter-proof"
STOCK_CODEX_COMPAT_ADAPTER_OUTPUT_SENTINEL = "OMNIGENT_ADAPTER_TOOL_SENTINEL_64"
STOCK_CODEX_COMPAT_WRAPPER_ADAPTER_ARBITRATION_SENTINEL = (
    "STOCK_CODEX_COMPAT_WRAPPER_ADAPTER_ARBITRATION_OK"
)
STOCK_CODEX_COMPAT_WRAPPER_APPLE_DOCS_ADAPTER_SENTINEL = (
    "STOCK_CODEX_COMPAT_WRAPPER_APPLE_DOCS_ADAPTER_OK"
)
STOCK_CODEX_COMPAT_WRAPPER_APPLE_DOCS_BRIDGE_ADAPTER_SENTINEL = (
    "STOCK_CODEX_COMPAT_WRAPPER_APPLE_DOCS_BRIDGE_ADAPTER_OK"
)
STOCK_CODEX_COMPAT_LAUNCHER_ACTIVATION_SENTINEL = (
    "STOCK_CODEX_COMPAT_LAUNCHER_ACTIVATION_OK"
)
STOCK_CODEX_COMPAT_WRAPPER_XCODEBUILD_BRIDGE_ADAPTER_SENTINEL = (
    "STOCK_CODEX_COMPAT_WRAPPER_XCODEBUILD_BRIDGE_ADAPTER_OK"
)
STOCK_CODEX_COMPAT_ADAPTER_ROUTE_COMMAND_NAME = (
    "omnigent-wrapper-route-adapter-probe"
)
STOCK_CODEX_COMPAT_ADAPTER_ROUTE_COMMAND_ARGUMENT = "route-selection-proof"
STOCK_CODEX_COMPAT_ADAPTER_ROUTE_OUTPUT_SENTINEL = (
    "OMNIGENT_ADAPTER_ARBITRATION_ROUTE_SENTINEL_88"
)
STOCK_CODEX_COMPAT_ADAPTER_RELEASE_COMMAND_NAME = (
    "omnigent-wrapper-release-adapter-probe"
)
STOCK_CODEX_COMPAT_ADAPTER_RELEASE_COMMAND_ARGUMENT = "release-notes-proof"
STOCK_CODEX_COMPAT_ADAPTER_RELEASE_OUTPUT_SENTINEL = (
    "OMNIGENT_ADAPTER_ARBITRATION_RELEASE_SENTINEL_19"
)
STOCK_CODEX_COMPAT_WRAPPER_RELAY_TOOL_SENTINEL = (
    "STOCK_CODEX_COMPAT_WRAPPER_RELAY_TOOL_OK"
)
STOCK_CODEX_COMPAT_RELAY_TOOL_NAME = "omnigent_wrapper_relay_probe"
STOCK_CODEX_COMPAT_RELAY_TOOL_ARGUMENT = "stock-codex-wrapper-relay-proof"
STOCK_CODEX_COMPAT_RELAY_TOOL_OUTPUT_SENTINEL = "OMNIGENT_RELAY_TOOL_SENTINEL_91"
STOCK_CODEX_SUPPORTED_FEATURE_STAGES = frozenset(
    {"stable", "experimental", "under development"}
)
STOCK_CODEX_FEATURES_REQUIRING_NONDEFAULT_SUPPORT = frozenset(
    {"rollout_budget", "shell_zsh_fork", "unified_exec_zsh_fork"}
)
STOCK_CODEX_COMPAT_WRAPPER_EVIDENCE_ENV = (
    stock_codex_compat_wrapper.WRAPPER_EVIDENCE_ENV
)
T = TypeVar("T")


@dataclass(frozen=True)
class GraphProof:
    """Static proof result for the selected skill's bundled graph."""

    relative_paths: dict[str, Path]
    skill_refs: dict[str, Path]


@dataclass(frozen=True)
class ToolProof:
    """Live proof result for the stock-Codex tool plane."""

    session_id: str
    call_id: str
    transcript: str


@dataclass(frozen=True)
class RouterMatrixCaseProof:
    """Live proof result for one router-selection matrix case."""

    name: str
    session_id: str
    sentinel: str
    expected_route: bool
    transcript: str


@dataclass(frozen=True)
class AppleMcpProof:
    """Live proof result for an Apple MCP-backed tool call."""

    session_id: str
    call_id: str
    transcript: str
    output_preview: str


@dataclass(frozen=True)
class XcodeBuildMcpBuildProof:
    """Live proof result for an XcodeBuildMCP build-only boundary."""

    session_id: str
    show_defaults_call_id: str
    set_defaults_call_id: str
    build_call_id: str
    transcript: str
    output_preview: str


@dataclass(frozen=True)
class XcodeBuildMcpRunProof:
    """Live proof result for an XcodeBuildMCP simulator run boundary."""

    session_id: str
    show_defaults_call_id: str
    set_defaults_call_id: str
    run_call_id: str
    transcript: str
    output_preview: str


@dataclass(frozen=True)
class AppleWorkflowSmokeProof:
    """Live proof result for a representative Apple workflow smoke."""

    session_id: str
    apple_docs_call_id: str
    xcodebuild_call_id: str
    transcript: str
    apple_docs_output_preview: str
    xcodebuild_output_preview: str


@dataclass(frozen=True)
class SessionRun:
    """Captured result from one normal Omnigent session/runner query."""

    session_id: str
    text: str
    items: list[dict[str, Any]]


@dataclass(frozen=True)
class LauncherActivationProof:
    """Non-mutating proof result for a temporary Codex launcher shim."""

    baseline_codex_path: Path
    baseline_codex_realpath: Path
    pinned_codex_path: Path
    pinned_codex_version: str
    omnigent_resolved_codex_path: Path
    activated_codex_path: Path
    restored_codex_path: Path
    shim_path: Path
    uvx_path: Path
    sanitized_path: str
    probe_output: str


@dataclass(frozen=True)
class AppBundleEntrypointProof:
    """Non-mutating proof result for a temporary macOS app-bundle entrypoint."""

    app_bundle_path: Path
    executable_path: Path
    info_plist_path: Path
    bundle_identifier: str
    bundle_executable: str
    stock_codex_path: Path
    stock_codex_version: str
    uvx_path: Path
    repo_root: Path
    probe_output: str


@dataclass(frozen=True)
class PinnedCodexProvisionProof:
    """Non-mutating proof result for a temporary pinned Codex payload."""

    source_codex_path: Path
    source_codex_realpath: Path
    source_codex_version: str
    source_codex_sha256: str
    cache_root: Path
    payload_dir: Path
    provisioned_codex_path: Path
    provisioned_manifest_path: Path
    provisioned_version: str
    provisioned_sha256: str
    omnigent_resolved_codex_path: Path


@dataclass(frozen=True)
class StockCodexChannelProof:
    """Non-mutating proof result for a file-backed stock Codex channel."""

    source_codex_path: Path
    source_codex_realpath: Path
    source_codex_version: str
    source_codex_sha256: str
    channel_manifest_path: Path
    channel_artifact_path: Path
    cache_root: Path
    payload_dir: Path
    provisioned_codex_path: Path
    provisioned_manifest_path: Path
    provisioned_version: str
    provisioned_sha256: str
    provisioned_source_kind: str
    omnigent_resolved_codex_path: Path


@dataclass(frozen=True)
class StockCodexHomebrewRemoteChannelProof:
    """Non-mutating proof result for the Homebrew/OpenAI remote Codex channel."""

    cask_token: str
    cask_tap: str
    cask_homepage: str
    cask_version: str
    cask_url: str
    cask_sha256: str
    archive_executable: str
    channel_manifest_path: Path
    cache_root: Path
    payload_dir: Path
    provisioned_codex_path: Path
    provisioned_manifest_path: Path
    provisioned_version: str
    provisioned_sha256: str
    provisioned_source_kind: str
    omnigent_resolved_codex_path: Path


@dataclass(frozen=True)
class CleanAuthOnboardingProof:
    """Non-mutating proof result for clean Codex auth onboarding boundaries."""

    stock_codex_path: Path
    stock_codex_version: str
    real_auth_path: Path
    real_auth_source: str
    real_auth_available: bool
    clean_home: Path
    clean_codex_home: Path
    clean_unavailable_reason: str | None
    synthetic_codex_home: Path
    synthetic_available_reason: str | None


@dataclass(frozen=True)
class StockCodexCompatProof:
    """Non-mutating proof result for stock Codex compatibility installation."""

    stock_codex_path: Path
    stock_codex_version: str
    source_bundle: Path
    codex_home: Path
    marketplace_root: Path
    marketplace_name: str
    plugin_id: str
    plugin_source_path: Path
    installed_plugin_path: Path
    bridge_dir: Path
    bridge_config_path: Path
    policy_hook_config_path: Path
    config_path: Path
    hooks_path: Path
    hook_events: tuple[str, ...]
    mcp_servers: tuple[str, ...]
    mcp_omnigent_command: str
    mcp_omnigent_args: tuple[str, ...]
    marketplace_list_output: dict[str, Any]
    plugin_list_output: dict[str, Any]


@dataclass(frozen=True)
class StockCodexCompatLiveProof:
    """Live proof result for a stock Codex compatibility entrypoint."""

    stock_codex_path: Path
    stock_codex_version: str
    source_bundle: Path
    codex_home: Path
    auth_path: Path
    bridge_dir: Path
    workspace_root: Path
    thread_id: str
    first_agent_message: str
    event_count: int
    mcp_servers: tuple[str, ...]
    stderr_preview: str


@dataclass(frozen=True)
class StockCodexCompatWrapperLiveProof:
    """Live proof result for an Omnigent-owned wrapper around stock Codex."""

    stock_codex_path: Path
    stock_codex_version: str
    source_bundle: Path
    wrapper_path: Path
    codex_home: Path
    auth_path: Path
    bridge_dir: Path
    workspace_root: Path
    thread_id: str
    first_agent_message: str
    first_agent_message_before_wrapper: str
    route_injected: bool
    wrapper_evidence_path: Path
    event_count: int
    mcp_servers: tuple[str, ...]
    stderr_preview: str


@dataclass(frozen=True)
class StockCodexCompatWrapperCommandToolProof:
    """Tool-use proof result for an Omnigent-owned stock Codex wrapper."""

    stock_codex_path: Path
    stock_codex_version: str
    source_bundle: Path
    wrapper_path: Path
    codex_home: Path
    auth_path: Path
    bridge_dir: Path
    workspace_root: Path
    thread_id: str
    command: str
    command_output: str
    first_agent_message: str
    first_agent_message_before_wrapper: str
    route_injected: bool
    wrapper_evidence_path: Path
    event_count: int
    mcp_servers: tuple[str, ...]
    stderr_preview: str


@dataclass(frozen=True)
class StockCodexCompatWrapperAdapterToolProof:
    """Wrapper-owned adapter proof result for stock Codex compatibility."""

    stock_codex_path: Path
    stock_codex_version: str
    source_bundle: Path
    wrapper_path: Path
    codex_home: Path
    auth_path: Path
    bridge_dir: Path
    workspace_root: Path
    adapter_bin: Path
    adapter_manifest: Path
    adapter_tool_names: tuple[str, ...]
    thread_id: str
    command: str
    command_output: str
    first_agent_message: str
    first_agent_message_before_wrapper: str
    route_injected: bool
    wrapper_evidence_path: Path
    event_count: int
    mcp_servers: tuple[str, ...]
    stderr_preview: str


@dataclass(frozen=True)
class StockCodexCompatWrapperAdapterArbitrationProof:
    """Multi-tool adapter arbitration proof result for stock Codex compatibility."""

    stock_codex_path: Path
    stock_codex_version: str
    source_bundle: Path
    wrapper_path: Path
    codex_home: Path
    auth_path: Path
    bridge_dir: Path
    workspace_root: Path
    adapter_bin: Path
    adapter_manifest: Path
    adapter_tool_names: tuple[str, ...]
    selected_tool_name: str
    rejected_tool_name: str
    thread_id: str
    command: str
    command_output: str
    first_agent_message: str
    first_agent_message_before_wrapper: str
    route_injected: bool
    wrapper_evidence_path: Path
    event_count: int
    mcp_servers: tuple[str, ...]
    stderr_preview: str


@dataclass(frozen=True)
class StockCodexCompatWrapperAppleDocsAdapterProof:
    """Real Apple docs adapter proof result for stock Codex compatibility."""

    stock_codex_path: Path
    stock_codex_version: str
    source_bundle: Path
    wrapper_path: Path
    codex_home: Path
    auth_path: Path
    bridge_dir: Path
    workspace_root: Path
    adapter_bin: Path
    adapter_manifest: Path
    adapter_tool_names: tuple[str, ...]
    docs_url: str
    thread_id: str
    command: str
    command_output: str
    first_agent_message: str
    first_agent_message_before_wrapper: str
    route_injected: bool
    wrapper_evidence_path: Path
    event_count: int
    mcp_servers: tuple[str, ...]
    stderr_preview: str


@dataclass(frozen=True)
class StockCodexCompatWrapperAppleDocsBridgeAdapterProof:
    """Apple docs adapter bridge proof result for stock Codex compatibility."""

    stock_codex_path: Path
    stock_codex_version: str
    source_bundle: Path
    wrapper_path: Path
    codex_home: Path
    auth_path: Path
    bridge_dir: Path
    workspace_root: Path
    adapter_bin: Path
    adapter_manifest: Path
    adapter_bridge_dir: Path
    adapter_tool_names: tuple[str, ...]
    docs_url: str
    sandbox: str
    thread_id: str
    command: str
    command_output: str
    first_agent_message: str
    first_agent_message_before_wrapper: str
    route_injected: bool
    wrapper_evidence_path: Path
    event_count: int
    mcp_servers: tuple[str, ...]
    stderr_preview: str


@dataclass(frozen=True)
class StockCodexCompatWrapperXcodebuildBridgeAdapterProof:
    """XcodeBuildMCP bridge adapter proof result for stock Codex compatibility."""

    stock_codex_path: Path
    stock_codex_version: str
    source_bundle: Path
    wrapper_path: Path
    codex_home: Path
    auth_path: Path
    bridge_dir: Path
    workspace_root: Path
    adapter_bin: Path
    adapter_manifest: Path
    adapter_bridge_dir: Path
    adapter_tool_names: tuple[str, ...]
    project_path: Path
    scheme: str
    configuration: str
    simulator_name: str
    derived_data_path: Path
    sandbox: str
    thread_id: str
    command: str
    command_output: str
    first_agent_message: str
    first_agent_message_before_wrapper: str
    route_injected: bool
    wrapper_evidence_path: Path
    event_count: int
    mcp_servers: tuple[str, ...]
    stderr_preview: str


@dataclass(frozen=True)
class StockCodexCompatWrapperRelayToolProof:
    """Relay-tool proof result for an Omnigent-owned stock Codex wrapper."""

    stock_codex_path: Path
    stock_codex_version: str
    source_bundle: Path
    wrapper_path: Path
    codex_home: Path
    auth_path: Path
    bridge_dir: Path
    workspace_root: Path
    thread_id: str
    relay_tool_name: str
    relay_tool_arguments: dict[str, Any]
    relay_output_preview: str
    relay_event_types: tuple[str, ...]
    enabled_features: tuple[str, ...]
    skipped_features: tuple[str, ...]
    prompt_input_mentions_relay_tool: bool
    prompt_input_preview: str
    first_agent_message: str
    first_agent_message_before_wrapper: str
    route_injected: bool
    wrapper_evidence_path: Path
    event_count: int
    mcp_servers: tuple[str, ...]
    stderr_preview: str


@dataclass(frozen=True)
class StockCodexCompatLauncherActivationProof:
    """Proof result for the persistent stock-Codex compatibility launcher."""

    stock_codex_path: Path
    stock_codex_version: str
    launcher_path: Path
    manifest_path: Path
    repo_root: Path
    uvx_path: Path
    resolved_codex_path: Path
    adapter_bin: Path
    adapter_manifest: Path
    adapter_bridge_dir: Path
    adapter_tool_names: tuple[str, ...]
    workspace_root: Path
    sandbox: str
    wrapper_evidence_path: Path
    thread_id: str
    command: str
    command_output: str
    first_agent_message: str
    first_agent_message_before_wrapper: str
    route_injected: bool
    probe_output: str
    uninstall_action: str
    event_count: int
    stderr_preview: str


@dataclass(frozen=True)
class StockCodexCompatLauncherDoctorProof:
    """Non-mutating proof result for the compatibility launcher install plan."""

    stock_codex_path: Path
    stock_codex_version: str
    launcher_path: Path
    manifest_path: Path
    repo_root: Path
    uvx_path: Path
    adapter_bin: Path
    adapter_manifest: Path
    adapter_bridge_dir: Path
    adapter_package_dir: Path
    adapter_tool_names: tuple[str, ...]
    install_allowed: bool
    install_blocker: str | None
    existing_target_state: str
    existing_target_managed: bool
    existing_target_realpath: Path | None
    selected_command_path: Path | None
    target_selected_on_path: bool
    launcher_parent_on_path: bool
    launcher_parent_exists: bool
    nearest_existing_parent: Path
    nearest_existing_parent_writable: bool
    backup_existing_requested: bool
    force_requested: bool
    would_backup_existing: bool
    backup_path: Path | None
    rollback_command: str
    install_command: str
    mutates_filesystem: bool


@dataclass(frozen=True)
class StockCodexCompatCleanInstallProof:
    """Clean-home proof result for repeatable stock-Codex compatibility install."""

    stock_codex_path: Path
    stock_codex_version: str
    clean_home: Path
    clean_bin_dir: Path
    launcher_path: Path
    manifest_path: Path
    adapter_package_dir: Path
    adapter_bin: Path
    adapter_manifest: Path
    adapter_bridge_dir: Path
    adapter_tool_names: tuple[str, ...]
    repo_root: Path
    uvx_path: Path
    selected_command_path: Path
    version_output: str
    probe_output: str
    adapter_package_action: str
    install_action: str
    rollback_action: str
    doctor_install_allowed: bool
    doctor_existing_target_state: str
    doctor_existing_target_managed: bool
    doctor_target_selected_on_path: bool
    doctor_mutates_filesystem: bool
    launcher_removed_after_rollback: bool
    manifest_removed_after_rollback: bool


@dataclass(frozen=True)
class StockCodexCompatBundleInstallProof:
    """Proof result for installing the compatibility launcher from a bundle artifact."""

    stock_codex_path: Path
    stock_codex_version: str
    bundle_path: Path
    bundle_sha256: str
    bundle_manifest_path: Path
    extracted_bundle_root: Path
    extracted_runtime_root: Path
    installer_script_path: Path
    clean_home: Path
    clean_bin_dir: Path
    launcher_path: Path
    manifest_path: Path
    adapter_package_dir: Path
    adapter_bin: Path
    adapter_manifest: Path
    adapter_bridge_dir: Path
    adapter_tool_names: tuple[str, ...]
    uvx_path: Path
    selected_command_path: Path
    launcher_manifest_repo_root: Path
    version_output: str
    probe_output: str
    adapter_package_action: str
    install_action: str
    rollback_action: str
    doctor_install_allowed: bool
    doctor_existing_target_state: str
    doctor_existing_target_managed: bool
    doctor_target_selected_on_path: bool
    doctor_mutates_filesystem: bool
    launcher_removed_after_rollback: bool
    manifest_removed_after_rollback: bool


@dataclass(frozen=True)
class StockCodexCompatPkgStructureProof:
    """Proof result for the unsigned stock-Codex compatibility pkg structure."""

    package_path: Path
    package_sha256: str
    source_bundle_sha256: str
    package_identifier: str
    package_version: str
    install_location: str
    install_prefix: Path
    runtime_root: Path
    payload_file_count: int
    required_payload_files: dict[str, bool]
    script_names: tuple[str, ...]
    archive_entries: tuple[str, ...]
    signature_status: str
    signed: bool
    pkg_manifest_path: Path
    bundle_manifest_path: Path
    pkg_contract: dict[str, Any]
    bundle_source_root: str


@dataclass(frozen=True)
class StockCodexCompatPkgRuntimeLiveProof:
    """Live proof result for an expanded pkg runtime around stock Codex."""

    stock_codex_path: Path
    stock_codex_version: str
    source_bundle: Path
    package_path: Path
    package_sha256: str
    source_bundle_sha256: str
    package_identifier: str
    package_version: str
    install_prefix: Path
    packaged_runtime_root: Path
    expanded_payload_root: Path
    expanded_runtime_root: Path
    uvx_path: Path
    wrapper_command: tuple[str, ...]
    codex_home: Path
    auth_path: Path
    bridge_dir: Path
    workspace_root: Path
    enabled_features: tuple[str, ...]
    thread_id: str
    first_agent_message: str
    first_agent_message_before_wrapper: str
    route_injected: bool
    wrapper_evidence_path: Path
    event_count: int
    mcp_servers: tuple[str, ...]
    stderr_preview: str


@dataclass(frozen=True)
class StockCodexCompatPkgUserBootstrapProof:
    """Proof result for per-user bootstrap from a pkg-installed runtime shape."""

    stock_codex_path: Path
    stock_codex_version: str
    package_path: Path
    package_sha256: str
    package_identifier: str
    package_version: str
    install_root: Path
    installed_prefix: Path
    installed_runtime_root: Path
    installer_script_path: Path
    pkg_manifest_path: Path
    bundle_manifest_path: Path
    clean_home: Path
    clean_bin_dir: Path
    launcher_path: Path
    manifest_path: Path
    adapter_package_dir: Path
    adapter_bin: Path
    adapter_manifest: Path
    adapter_bridge_dir: Path
    adapter_tool_names: tuple[str, ...]
    uvx_path: Path
    selected_command_path: Path
    launcher_manifest_repo_root: Path
    launcher_manifest_wrapper_entrypoint: str
    launcher_manifest_adapter_tool_names: tuple[str, ...]
    version_output: str
    probe_output: str
    adapter_package_action: str
    install_action: str
    update_action: str
    rollback_command: str
    rollback_action: str
    doctor_install_allowed: bool
    doctor_existing_target_state: str
    doctor_existing_target_managed: bool
    doctor_target_selected_on_path: bool
    doctor_mutates_filesystem: bool
    adapter_package_exists_after_install: bool
    launcher_removed_after_rollback: bool
    manifest_removed_after_rollback: bool


@dataclass(frozen=True)
class StockCodexCompatPkgCleanProvisionProof:
    """Proof result for clean stock-Codex provisioning from a pkg-installed runtime."""

    stock_codex_path: Path
    stock_codex_version: str
    stock_codex_sha256: str
    package_path: Path
    package_sha256: str
    package_identifier: str
    package_version: str
    install_root: Path
    installed_prefix: Path
    installed_runtime_root: Path
    provisioner_script_path: Path
    pkg_manifest_path: Path
    bundle_manifest_path: Path
    clean_home: Path
    clean_cache_root: Path
    channel_manifest_path: Path
    channel_artifact_path: Path
    payload_dir: Path
    provisioned_codex_path: Path
    provisioned_manifest_path: Path
    provisioned_version: str
    provisioned_sha256: str
    provisioned_source_kind: str
    provisioned_env_path: Path
    omnigent_resolved_codex_path: Path
    reuse_payload_dir: Path
    reuse_provisioned_codex_path: Path
    host_cache_root: Path
    host_cache_referenced: bool


@dataclass(frozen=True)
class StockCodexCompatPkgCleanAuthProof:
    """Proof result for clean auth onboarding from a pkg-installed runtime."""

    stock_codex_path: Path
    stock_codex_version: str
    stock_codex_sha256: str
    package_path: Path
    package_sha256: str
    package_identifier: str
    package_version: str
    install_root: Path
    installed_prefix: Path
    installed_runtime_root: Path
    provisioner_script_path: Path
    clean_home: Path
    clean_cache_root: Path
    provisioned_codex_path: Path
    provisioned_version: str
    real_auth_path: Path
    real_auth_source: str
    real_auth_available: bool
    real_auth_classifier_path: Path
    real_auth_unavailable_reason: str | None
    clean_codex_home: Path
    clean_auth_classifier_path: Path
    clean_unavailable_reason: str
    synthetic_codex_home: Path
    synthetic_auth_classifier_path: Path
    synthetic_available_reason: str | None
    onboarding_command: str
    credential_material_leaked: bool


@dataclass(frozen=True)
class StockCodexCompatPkgSigningPrerequisites:
    """Prerequisite classification for signed/notarized pkg validation."""

    status: str
    missing_prerequisites: tuple[str, ...]
    tool_paths: dict[str, str | None]
    sign_identity: str | None
    sign_identity_source: str
    signing_keychain: Path | None
    developer_id_installer_identities: tuple[str, ...]
    developer_id_application_identities: tuple[str, ...]
    notarytool_profile: str | None


@dataclass(frozen=True)
class StockCodexCompatPkgSignedNotarizedProof:
    """Proof result for signed, notarized, stapled pkg validation."""

    status: str
    missing_prerequisites: tuple[str, ...]
    tool_paths: dict[str, str | None]
    sign_identity: str | None
    sign_identity_source: str
    signing_keychain: Path | None
    developer_id_installer_identities: tuple[str, ...]
    developer_id_application_identities: tuple[str, ...]
    notarytool_profile: str | None
    package_path: Path | None
    package_sha256: str | None
    source_bundle_sha256: str | None
    package_identifier: str | None
    package_version: str | None
    signature_status: str | None
    signed: bool | None
    notary_submission_id: str | None
    notary_status: str | None
    notary_output_preview: str | None
    staple_output_preview: str | None
    stapler_validate_output_preview: str | None
    gatekeeper_output_preview: str | None


class LiveProofTimeoutError(Exception):
    """A single live proof step exceeded its configured wall-clock budget."""


class SessionQueryTimeoutError(Exception):
    """A sessions-API query timed out after capturing best-effort diagnostics."""


def _candidate_bundle_entries() -> list[tuple[str, Path]]:
    env_path = os.environ.get("APPLE_APPDEV_WORKFLOW_BUNDLE", "").strip()
    candidates: list[tuple[str, Path]] = []
    if env_path:
        candidates.append(("APPLE_APPDEV_WORKFLOW_BUNDLE", Path(env_path).expanduser()))
    candidates.extend(
        [
            (
                "$HOME/.codex-fork plugin cache",
                Path.home()
                / ".codex-fork/plugins/cache/LocalAppleWorkflow/apple-appdev-workflow/0.1.1",
            ),
            (
                "$HOME/.codex plugin cache",
                Path.home()
                / ".codex/plugins/cache/LocalAppleWorkflow/apple-appdev-workflow/0.1.1",
            ),
        ]
    )
    return candidates


def _candidate_bundles() -> list[Path]:
    return [path for _label, path in _candidate_bundle_entries()]


def default_bundle_selector(path: Path) -> str:
    """Return the default lookup source that selected an installed bundle."""
    resolved_path = path.expanduser().resolve()
    for label, candidate in _candidate_bundle_entries():
        if candidate.expanduser().resolve() == resolved_path:
            return label
    return "unknown default candidate"


def resolve_default_bundle() -> Path:
    """Return the first installed Apple workflow bundle candidate."""
    for _label, candidate in _candidate_bundle_entries():
        if (candidate / ".codex-plugin/plugin.json").is_file() and (
            candidate / "skills" / SELECTED_SKILL / "SKILL.md"
        ).is_file():
            return candidate
    searched = "\n".join(f"- {path}" for path in _candidate_bundles())
    raise SystemExit(
        "Could not find an Apple workflow bundle. Pass --apple-bundle or set "
        f"APPLE_APPDEV_WORKFLOW_BUNDLE. Searched:\n{searched}"
    )


def resolve_codex_path(value: str | None) -> Path:
    """Resolve the stock Codex binary path and fail closed on fork runtimes."""
    raw = value or _find_codex_cli()
    if not raw:
        raise SystemExit("Could not find codex on PATH. Pass --codex-path.")
    candidate = Path(raw).expanduser()
    managed_or_stock = _resolve_managed_codex_launcher(candidate)
    if managed_or_stock is None:
        raise SystemExit(f"Codex binary not found or managed launcher is stale: {candidate}")
    path = managed_or_stock.resolve()
    if not path.is_file():
        raise SystemExit(f"Codex binary not found: {path}")
    return path


def assert_stock_codex_path(path: Path, *, allow_fork_codex: bool) -> None:
    """Prevent accidental proofs against the existing Codex fork runtime."""
    if allow_fork_codex:
        return
    if ".codex-fork" in path.parts:
        raise SystemExit(
            f"Refusing to use Codex-fork binary for stock-Codex proof: {path}\n"
            "Pass --allow-fork-codex only for diagnostic comparisons."
        )


def codex_version(path: Path) -> str:
    """Best-effort ``codex --version`` probe."""
    try:
        completed = subprocess.run(
            [str(path), "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception as exc:  # noqa: BLE001 - version is evidence, not a hard dependency
        return f"unknown ({exc})"
    text = (completed.stdout or completed.stderr).strip()
    return text or f"unknown (exit {completed.returncode})"


def print_default_path_cutover_fallback_steps(
    *,
    source_bundle: Path,
    bundle_selector: str,
    codex_path: Path,
) -> None:
    """Emit operator fallback evidence for the default-path rehearsal."""
    print("default_path_cutover_rehearsal=selected")
    print("default_path_cutover_apple_bundle_arg=not_set")
    print("default_path_cutover_codex_path_arg=not_set")
    print(f"default_path_cutover_bundle_selector={bundle_selector}")
    print(f"default_path_cutover_bundle_source={source_bundle}")
    print("default_path_cutover_codex_selector=PATH")
    print(f"default_path_cutover_codex_path={codex_path}")
    for index, step in enumerate(DEFAULT_PATH_CUTOVER_FALLBACK_STEPS, start=1):
        print(f"default_path_cutover_fallback_step_{index}={step}")
    print(
        "ASSERTION: default-path cutover rehearsal used ambient bundle lookup "
        "and PATH-resolved stock Codex without mutating the Codex fork"
    )


def run_pinned_codex_provision_proof(source_codex_path: Path) -> PinnedCodexProvisionProof:
    """Prove the Codex provisioner installs a verified pinned payload."""
    source_codex_realpath = source_codex_path.expanduser().resolve()
    source_digest = sha256_file(source_codex_realpath)
    source_version = codex_version(source_codex_realpath)
    repo_root = Path(__file__).resolve().parents[1]
    provisioner = repo_root / "scripts" / "provision_stock_codex.py"
    with tempfile.TemporaryDirectory(prefix="omnigent-pinned-codex-provision-proof-") as temp_root:
        cache_root = Path(temp_root) / "codex-stock"
        completed = subprocess.run(
            [
                sys.executable,
                str(provisioner),
                "--cache-root",
                str(cache_root),
                "--source-binary",
                str(source_codex_path),
                "--expected-sha256",
                source_digest,
                "--json",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if completed.returncode != 0:
            raise SystemExit(
                "Pinned stock Codex provisioner failed with exit "
                f"{completed.returncode}:\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
            )
        try:
            provisioned = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise SystemExit(
                f"Pinned stock Codex provisioner did not emit JSON:\n{completed.stdout}"
            ) from exc
        if not isinstance(provisioned, dict):
            raise SystemExit(
                f"Pinned stock Codex provisioner JSON is not an object: {provisioned!r}"
            )

        provisioned_path = Path(_json_string(provisioned, "codexPath")).expanduser().resolve()
        payload_dir = Path(_json_string(provisioned, "payloadDir")).expanduser().resolve()
        manifest_path = Path(_json_string(provisioned, "manifestPath")).expanduser().resolve()
        provisioned_sha = _json_string(provisioned, "sha256")
        provisioned_version = _json_string(provisioned, "version")
        if provisioned_sha.lower() != source_digest.lower():
            raise SystemExit(
                "Pinned stock Codex provisioner copied an unexpected binary.\n"
                f"expected_sha256={source_digest}\nactual_sha256={provisioned_sha}"
            )
        if provisioned_version != source_version:
            raise SystemExit(
                "Pinned stock Codex provisioner recorded an unexpected version.\n"
                f"expected_version={source_version!r}\nactual_version={provisioned_version!r}"
            )
        if not provisioned_path.is_file() or not os.access(provisioned_path, os.X_OK):
            raise SystemExit(f"Provisioned Codex binary is not executable: {provisioned_path}")
        if not manifest_path.is_file():
            raise SystemExit(f"Provisioned Codex manifest is missing: {manifest_path}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("kind") != "omnigent-stock-codex":
            raise SystemExit(f"Provisioned Codex manifest kind mismatch: {manifest!r}")
        if manifest.get("sha256") != provisioned_sha:
            raise SystemExit(f"Provisioned Codex manifest sha mismatch: {manifest!r}")
        actual_provisioned_version = codex_version(provisioned_path)
        if actual_provisioned_version != provisioned_version:
            raise SystemExit(
                "Provisioned Codex binary reported a different version.\n"
                f"manifest_version={provisioned_version!r}\nactual_version={actual_provisioned_version!r}"
            )
        with temporary_env({OMNIGENT_STOCK_CODEX_PATH_ENV: str(provisioned_path)}):
            resolved_raw = _find_codex_cli()
        if resolved_raw is None:
            raise SystemExit(f"{OMNIGENT_STOCK_CODEX_PATH_ENV} did not resolve a Codex binary.")
        resolved_path = Path(resolved_raw).expanduser().resolve()
        if resolved_path != provisioned_path:
            raise SystemExit(
                "Omnigent stock-Codex resolver did not select the provisioned binary.\n"
                f"expected={provisioned_path}\nactual={resolved_raw}"
            )

        return PinnedCodexProvisionProof(
            source_codex_path=source_codex_path,
            source_codex_realpath=source_codex_realpath,
            source_codex_version=source_version,
            source_codex_sha256=source_digest,
            cache_root=cache_root,
            payload_dir=payload_dir,
            provisioned_codex_path=provisioned_path,
            provisioned_manifest_path=manifest_path,
            provisioned_version=provisioned_version,
            provisioned_sha256=provisioned_sha,
            omnigent_resolved_codex_path=resolved_path,
        )


def print_pinned_codex_provision_proof(proof: PinnedCodexProvisionProof) -> None:
    """Emit operator evidence for the temporary pinned Codex provision proof."""
    print("pinned_codex_provision_rehearsal=selected")
    print(f"pinned_codex_source_path={proof.source_codex_path}")
    print(f"pinned_codex_source_realpath={proof.source_codex_realpath}")
    print(f"pinned_codex_source_version={proof.source_codex_version}")
    print(f"pinned_codex_source_sha256={proof.source_codex_sha256}")
    print(f"pinned_codex_cache_root={proof.cache_root}")
    print(f"pinned_codex_payload_dir={proof.payload_dir}")
    print(f"pinned_codex_path={proof.provisioned_codex_path}")
    print(f"pinned_codex_version={proof.provisioned_version}")
    print(f"pinned_codex_sha256={proof.provisioned_sha256}")
    print(f"pinned_codex_manifest={proof.provisioned_manifest_path}")
    print(f"pinned_codex_env={OMNIGENT_STOCK_CODEX_PATH_ENV}={proof.provisioned_codex_path}")
    print(f"pinned_codex_omnigent_resolved_codex_path={proof.omnigent_resolved_codex_path}")
    print("pinned_codex_cache_lifecycle=temporary_removed_after_proof")
    print(
        "ASSERTION: pinned stock-Codex provisioning records source path, realpath, "
        "version, sha256, and environment contract before use"
    )
    print(
        "ASSERTION: Omnigent resolves the provisioned binary through "
        f"{OMNIGENT_STOCK_CODEX_PATH_ENV} without relying on ambient codex PATH lookup"
    )


def run_stock_codex_channel_proof(source_codex_path: Path) -> StockCodexChannelProof:
    """Prove a file-backed stock Codex channel provisions a verified payload."""
    source_codex_realpath = source_codex_path.expanduser().resolve()
    source_digest = sha256_file(source_codex_realpath)
    source_version = codex_version(source_codex_realpath)
    repo_root = Path(__file__).resolve().parents[1]
    provisioner = repo_root / "scripts" / "provision_stock_codex.py"
    with tempfile.TemporaryDirectory(prefix="omnigent-stock-codex-channel-proof-") as temp_root:
        root = Path(temp_root)
        artifacts_dir = root / "artifacts"
        artifacts_dir.mkdir()
        channel_artifact_path = artifacts_dir / "codex"
        shutil.copy2(source_codex_realpath, channel_artifact_path)
        channel_artifact_path.chmod(0o755)
        channel_manifest_path = root / "channel.json"
        channel_manifest_path.write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "kind": "omnigent-stock-codex-channel",
                    "latest": source_version,
                    "artifacts": [
                        {
                            "version": source_version,
                            "path": "artifacts/codex",
                            "sha256": source_digest,
                        }
                    ],
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        cache_root = root / "codex-stock"
        completed = subprocess.run(
            [
                sys.executable,
                str(provisioner),
                "--cache-root",
                str(cache_root),
                "--channel-manifest",
                str(channel_manifest_path),
                "--expected-sha256",
                source_digest,
                "--json",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if completed.returncode != 0:
            raise SystemExit(
                "Stock Codex channel provisioner failed with exit "
                f"{completed.returncode}:\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
            )
        try:
            provisioned = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise SystemExit(
                f"Stock Codex channel provisioner did not emit JSON:\n{completed.stdout}"
            ) from exc
        if not isinstance(provisioned, dict):
            raise SystemExit(
                f"Stock Codex channel provisioner JSON is not an object: {provisioned!r}"
            )

        provisioned_path = Path(_json_string(provisioned, "codexPath")).expanduser().resolve()
        payload_dir = Path(_json_string(provisioned, "payloadDir")).expanduser().resolve()
        manifest_path = Path(_json_string(provisioned, "manifestPath")).expanduser().resolve()
        provisioned_sha = _json_string(provisioned, "sha256")
        provisioned_version = _json_string(provisioned, "version")
        provisioned_source_kind = _json_string(provisioned, "sourceKind")
        channel_manifest_result = Path(
            _json_string(provisioned, "channelManifestPath")
        ).expanduser()
        channel_artifact = provisioned.get("channelArtifact")
        if not isinstance(channel_artifact, dict):
            raise SystemExit(
                f"Stock Codex channel provisioner omitted channel artifact: {provisioned!r}"
            )
        if channel_manifest_result != channel_manifest_path:
            raise SystemExit(
                "Stock Codex channel provisioner recorded an unexpected channel manifest.\n"
                f"expected={channel_manifest_path}\nactual={channel_manifest_result}"
            )
        if channel_artifact.get("path") != "artifacts/codex":
            raise SystemExit(
                "Stock Codex channel provisioner recorded unexpected artifact: "
                f"{channel_artifact!r}"
            )
        if provisioned_source_kind != "channel":
            raise SystemExit(
                f"Stock Codex channel provisioner source kind mismatch: {provisioned!r}"
            )
        if provisioned_sha.lower() != source_digest.lower():
            raise SystemExit(
                "Stock Codex channel provisioner installed an unexpected binary.\n"
                f"expected_sha256={source_digest}\nactual_sha256={provisioned_sha}"
            )
        if provisioned_version != source_version:
            raise SystemExit(
                "Stock Codex channel provisioner recorded an unexpected version.\n"
                f"expected_version={source_version!r}\nactual_version={provisioned_version!r}"
            )
        if not provisioned_path.is_file() or not os.access(provisioned_path, os.X_OK):
            raise SystemExit(f"Channel-provisioned Codex is not executable: {provisioned_path}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("kind") != "omnigent-stock-codex":
            raise SystemExit(f"Channel-provisioned manifest kind mismatch: {manifest!r}")
        if manifest.get("sourceKind") != "channel":
            raise SystemExit(f"Channel-provisioned manifest source mismatch: {manifest!r}")
        if manifest.get("sha256") != provisioned_sha:
            raise SystemExit(f"Channel-provisioned manifest sha mismatch: {manifest!r}")
        actual_provisioned_version = codex_version(provisioned_path)
        if actual_provisioned_version != provisioned_version:
            raise SystemExit(
                "Channel-provisioned Codex binary reported a different version.\n"
                f"manifest_version={provisioned_version!r}\nactual_version={actual_provisioned_version!r}"
            )
        with temporary_env({OMNIGENT_STOCK_CODEX_PATH_ENV: str(provisioned_path)}):
            resolved_raw = _find_codex_cli()
        if resolved_raw is None:
            raise SystemExit(f"{OMNIGENT_STOCK_CODEX_PATH_ENV} did not resolve a Codex binary.")
        resolved_path = Path(resolved_raw).expanduser().resolve()
        if resolved_path != provisioned_path:
            raise SystemExit(
                "Omnigent stock-Codex resolver did not select the channel-provisioned binary.\n"
                f"expected={provisioned_path}\nactual={resolved_raw}"
            )

        return StockCodexChannelProof(
            source_codex_path=source_codex_path,
            source_codex_realpath=source_codex_realpath,
            source_codex_version=source_version,
            source_codex_sha256=source_digest,
            channel_manifest_path=channel_manifest_path,
            channel_artifact_path=channel_artifact_path,
            cache_root=cache_root,
            payload_dir=payload_dir,
            provisioned_codex_path=provisioned_path,
            provisioned_manifest_path=manifest_path,
            provisioned_version=provisioned_version,
            provisioned_sha256=provisioned_sha,
            provisioned_source_kind=provisioned_source_kind,
            omnigent_resolved_codex_path=resolved_path,
        )


def print_stock_codex_channel_proof(proof: StockCodexChannelProof) -> None:
    """Emit operator evidence for the file-backed stock Codex channel proof."""
    print("stock_codex_channel_rehearsal=selected")
    print(f"stock_codex_channel_source_path={proof.source_codex_path}")
    print(f"stock_codex_channel_source_realpath={proof.source_codex_realpath}")
    print(f"stock_codex_channel_source_version={proof.source_codex_version}")
    print(f"stock_codex_channel_source_sha256={proof.source_codex_sha256}")
    print(f"stock_codex_channel_manifest={proof.channel_manifest_path}")
    print(f"stock_codex_channel_artifact={proof.channel_artifact_path}")
    print("stock_codex_channel_artifact_transport=local-file")
    print(f"stock_codex_channel_cache_root={proof.cache_root}")
    print(f"stock_codex_channel_payload_dir={proof.payload_dir}")
    print(f"stock_codex_channel_path={proof.provisioned_codex_path}")
    print(f"stock_codex_channel_version={proof.provisioned_version}")
    print(f"stock_codex_channel_sha256={proof.provisioned_sha256}")
    print(f"stock_codex_channel_source_kind={proof.provisioned_source_kind}")
    print(f"stock_codex_channel_payload_manifest={proof.provisioned_manifest_path}")
    print(
        f"stock_codex_channel_env={OMNIGENT_STOCK_CODEX_PATH_ENV}={proof.provisioned_codex_path}"
    )
    print(f"stock_codex_channel_omnigent_resolved_codex_path={proof.omnigent_resolved_codex_path}")
    print("stock_codex_channel_cache_lifecycle=temporary_removed_after_proof")
    print(
        "ASSERTION: stock Codex channel manifests can select a local artifact, "
        "verify sha256 and version, stage it, and install a channel-provenance payload"
    )
    print(
        "ASSERTION: this proof remains local-file-only; remote http(s) "
        "download transport is covered by stock-codex-homebrew-remote-channel"
    )


def run_stock_codex_homebrew_remote_channel_proof() -> StockCodexHomebrewRemoteChannelProof:
    """Prove the stock Codex channel can use Homebrew cask GitHub release metadata."""
    cask = _read_homebrew_codex_cask()
    cask_url = _json_string(cask, "url")
    cask_sha256 = _json_string(cask, "sha256").lower()
    cask_version = _json_string(cask, "version")
    cask_token = _json_string(cask, "token")
    cask_tap = _json_string(cask, "tap")
    cask_homepage = _json_string(cask, "homepage")
    archive_executable = _homebrew_codex_binary_name(cask)
    _validate_homebrew_codex_cask_metadata(
        token=cask_token,
        homepage=cask_homepage,
        url=cask_url,
        sha256=cask_sha256,
    )
    expected_version = f"codex-cli {cask_version}"
    repo_root = Path(__file__).resolve().parents[1]
    provisioner = repo_root / "scripts" / "provision_stock_codex.py"
    with tempfile.TemporaryDirectory(
        prefix="omnigent-stock-codex-homebrew-channel-proof-"
    ) as temp_root:
        root = Path(temp_root)
        channel_manifest_path = root / "channel.json"
        channel_manifest_path.write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "kind": "omnigent-stock-codex-channel",
                    "latest": expected_version,
                    "artifacts": [
                        {
                            "version": expected_version,
                            "url": cask_url,
                            "sha256": cask_sha256,
                            "archiveFormat": "tar.gz",
                            "archiveExecutable": archive_executable,
                        }
                    ],
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        cache_root = root / "codex-stock"
        completed = subprocess.run(
            [
                sys.executable,
                str(provisioner),
                "--cache-root",
                str(cache_root),
                "--channel-manifest",
                str(channel_manifest_path),
                "--expected-sha256",
                cask_sha256,
                "--allow-remote-channel-download",
                "--json",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=240,
        )
        if completed.returncode != 0:
            raise SystemExit(
                "Stock Codex Homebrew remote channel provisioner failed with exit "
                f"{completed.returncode}:\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
            )
        try:
            provisioned = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise SystemExit(
                "Stock Codex Homebrew remote channel provisioner did not emit JSON:\n"
                f"{completed.stdout}"
            ) from exc
        if not isinstance(provisioned, dict):
            raise SystemExit(
                "Stock Codex Homebrew remote channel provisioner JSON is not an object: "
                f"{provisioned!r}"
            )

        provisioned_path = Path(_json_string(provisioned, "codexPath")).expanduser().resolve()
        payload_dir = Path(_json_string(provisioned, "payloadDir")).expanduser().resolve()
        manifest_path = Path(_json_string(provisioned, "manifestPath")).expanduser().resolve()
        provisioned_sha = _json_string(provisioned, "sha256")
        provisioned_version = _json_string(provisioned, "version")
        provisioned_source_kind = _json_string(provisioned, "sourceKind")
        channel_artifact = provisioned.get("channelArtifact")
        if not isinstance(channel_artifact, dict):
            raise SystemExit(
                "Stock Codex Homebrew remote channel provisioner omitted channel artifact: "
                f"{provisioned!r}"
            )
        expected_channel_artifact = {
            "archiveExecutable": archive_executable,
            "archiveFormat": "tar.gz",
            "sha256": cask_sha256,
            "url": cask_url,
            "version": expected_version,
            "versionSlug": cask_version,
        }
        if channel_artifact != expected_channel_artifact:
            raise SystemExit(
                "Stock Codex Homebrew remote channel provisioner recorded unexpected "
                f"artifact:\nexpected={expected_channel_artifact!r}\nactual={channel_artifact!r}"
            )
        if provisioned_source_kind != "channel":
            raise SystemExit(
                f"Stock Codex Homebrew remote channel source kind mismatch: {provisioned!r}"
            )
        if provisioned_version != expected_version:
            raise SystemExit(
                "Stock Codex Homebrew remote channel recorded an unexpected version.\n"
                f"expected_version={expected_version!r}\nactual_version={provisioned_version!r}"
            )
        if not provisioned_path.is_file() or not os.access(provisioned_path, os.X_OK):
            raise SystemExit(
                f"Homebrew-channel-provisioned Codex is not executable: {provisioned_path}"
            )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("kind") != "omnigent-stock-codex":
            raise SystemExit(f"Homebrew-channel-provisioned manifest kind mismatch: {manifest!r}")
        if manifest.get("sourceKind") != "channel":
            raise SystemExit(
                f"Homebrew-channel-provisioned manifest source mismatch: {manifest!r}"
            )
        if manifest.get("sourcePath") != cask_url or manifest.get("sourceRealpath") != cask_url:
            raise SystemExit(
                f"Homebrew-channel-provisioned manifest source URL mismatch: {manifest!r}"
            )
        if manifest.get("sha256") != provisioned_sha:
            raise SystemExit(f"Homebrew-channel-provisioned manifest sha mismatch: {manifest!r}")
        actual_provisioned_version = codex_version(provisioned_path)
        if actual_provisioned_version != provisioned_version:
            raise SystemExit(
                "Homebrew-channel-provisioned Codex binary reported a different version.\n"
                f"manifest_version={provisioned_version!r}\nactual_version={actual_provisioned_version!r}"
            )
        with temporary_env({OMNIGENT_STOCK_CODEX_PATH_ENV: str(provisioned_path)}):
            resolved_raw = _find_codex_cli()
        if resolved_raw is None:
            raise SystemExit(f"{OMNIGENT_STOCK_CODEX_PATH_ENV} did not resolve a Codex binary.")
        resolved_path = Path(resolved_raw).expanduser().resolve()
        if resolved_path != provisioned_path:
            raise SystemExit(
                "Omnigent stock-Codex resolver did not select the Homebrew "
                "remote-channel-provisioned binary.\n"
                f"expected={provisioned_path}\nactual={resolved_raw}"
            )

        return StockCodexHomebrewRemoteChannelProof(
            cask_token=cask_token,
            cask_tap=cask_tap,
            cask_homepage=cask_homepage,
            cask_version=cask_version,
            cask_url=cask_url,
            cask_sha256=cask_sha256,
            archive_executable=archive_executable,
            channel_manifest_path=channel_manifest_path,
            cache_root=cache_root,
            payload_dir=payload_dir,
            provisioned_codex_path=provisioned_path,
            provisioned_manifest_path=manifest_path,
            provisioned_version=provisioned_version,
            provisioned_sha256=provisioned_sha,
            provisioned_source_kind=provisioned_source_kind,
            omnigent_resolved_codex_path=resolved_path,
        )


def _read_homebrew_codex_cask() -> dict[str, Any]:
    """Return the current local Homebrew cask metadata for Codex."""
    completed = subprocess.run(
        ["brew", "info", "--cask", "--json=v2", "codex"],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, "HOMEBREW_NO_AUTO_UPDATE": "1"},
    )
    if completed.returncode != 0:
        raise SystemExit(
            "Could not read Homebrew Codex cask metadata with auto-update disabled.\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Homebrew cask metadata was not JSON:\n{completed.stdout}") from exc
    if not isinstance(payload, dict):
        raise SystemExit(f"Homebrew cask metadata was not an object: {payload!r}")
    casks = payload.get("casks")
    if not isinstance(casks, list):
        raise SystemExit(f"Homebrew cask metadata omitted casks list: {payload!r}")
    matches = [cask for cask in casks if isinstance(cask, dict) and cask.get("token") == "codex"]
    if len(matches) != 1:
        raise SystemExit(f"Expected one Homebrew codex cask, found {len(matches)}")
    return matches[0]


def _homebrew_codex_binary_name(cask: dict[str, Any]) -> str:
    """Return the Codex binary member declared by the Homebrew cask."""
    artifacts = cask.get("artifacts")
    if not isinstance(artifacts, list):
        raise SystemExit(f"Homebrew Codex cask omitted artifacts: {cask!r}")
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue
        binary = artifact.get("binary")
        if not isinstance(binary, list) or not binary:
            continue
        source_name = binary[0]
        target = (
            binary[1].get("target") if len(binary) > 1 and isinstance(binary[1], dict) else None
        )
        if isinstance(source_name, str) and target == "codex":
            return source_name
    raise SystemExit(f"Homebrew Codex cask did not declare a codex binary artifact: {cask!r}")


def _validate_homebrew_codex_cask_metadata(
    *,
    token: str,
    homepage: str,
    url: str,
    sha256: str,
) -> None:
    """Fail closed unless the cask points to the expected stock Codex release source."""
    if token != "codex":
        raise SystemExit(f"Unexpected Homebrew cask token: {token!r}")
    if homepage != "https://github.com/openai/codex":
        raise SystemExit(f"Unexpected Homebrew Codex homepage: {homepage!r}")
    if len(sha256) != 64 or any(char not in "0123456789abcdef" for char in sha256):
        raise SystemExit(f"Unexpected Homebrew Codex sha256: {sha256!r}")
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.netloc != "github.com":
        raise SystemExit(f"Homebrew Codex URL is not an HTTPS GitHub URL: {url}")
    if not parsed.path.startswith("/openai/codex/releases/download/"):
        raise SystemExit(f"Homebrew Codex URL is not an OpenAI Codex release URL: {url}")
    if not parsed.path.endswith(".tar.gz"):
        raise SystemExit(f"Homebrew Codex URL is not a tar.gz archive: {url}")


def print_stock_codex_homebrew_remote_channel_proof(
    proof: StockCodexHomebrewRemoteChannelProof,
) -> None:
    """Emit operator evidence for the Homebrew/OpenAI remote channel proof."""
    print("stock_codex_homebrew_remote_channel_rehearsal=selected")
    print(f"stock_codex_homebrew_cask_token={proof.cask_token}")
    print(f"stock_codex_homebrew_cask_tap={proof.cask_tap}")
    print(f"stock_codex_homebrew_cask_homepage={proof.cask_homepage}")
    print(f"stock_codex_homebrew_cask_version={proof.cask_version}")
    print(f"stock_codex_homebrew_cask_url={proof.cask_url}")
    print(f"stock_codex_homebrew_cask_sha256={proof.cask_sha256}")
    print("stock_codex_homebrew_archive_format=tar.gz")
    print(f"stock_codex_homebrew_archive_executable={proof.archive_executable}")
    print(f"stock_codex_homebrew_channel_manifest={proof.channel_manifest_path}")
    print("stock_codex_homebrew_channel_artifact_transport=https")
    print(f"stock_codex_homebrew_cache_root={proof.cache_root}")
    print(f"stock_codex_homebrew_payload_dir={proof.payload_dir}")
    print(f"stock_codex_homebrew_path={proof.provisioned_codex_path}")
    print(f"stock_codex_homebrew_version={proof.provisioned_version}")
    print(f"stock_codex_homebrew_binary_sha256={proof.provisioned_sha256}")
    print(f"stock_codex_homebrew_source_kind={proof.provisioned_source_kind}")
    print(f"stock_codex_homebrew_payload_manifest={proof.provisioned_manifest_path}")
    print(
        f"stock_codex_homebrew_env={OMNIGENT_STOCK_CODEX_PATH_ENV}={proof.provisioned_codex_path}"
    )
    print(
        f"stock_codex_homebrew_omnigent_resolved_codex_path={proof.omnigent_resolved_codex_path}"
    )
    print("stock_codex_homebrew_cache_lifecycle=temporary_removed_after_proof")
    print(
        "stock_codex_homebrew_trust_boundary=homebrew_cask_sha256_plus_openai_github_release_url"
    )
    print(
        "ASSERTION: Homebrew Codex cask metadata selected an OpenAI GitHub "
        "release archive and the provisioner verified the archive SHA-256 before extraction"
    )
    print(
        "ASSERTION: the provisioner extracted the declared archive executable, "
        "verified codex --version, installed a channel-provenance payload, and "
        "proved Omnigent resolver selection through OMNIGENT_STOCK_CODEX_PATH"
    )
    print(
        "ASSERTION: this proof used a temporary cache and did not mutate "
        "persistent launcher defaults, CODEX_HOME, or the Codex fork"
    )


def run_clean_auth_onboarding_proof(stock_codex_path: Path) -> CleanAuthOnboardingProof:
    """Prove clean Codex auth handling without mutating credential state."""
    stock_codex_path = stock_codex_path.expanduser().resolve()
    real_auth_path, real_auth_source = _stock_replacement_auth_source()
    real_auth_available = codex_native._codex_auth_json_has_available_credential(real_auth_path)
    if not real_auth_available:
        raise SystemExit(
            "Current real Codex auth source is not available; cannot prove the "
            "preserved-auth success boundary.\n"
            f"auth_path={real_auth_path}\n"
            "Run stock Codex authentication outside this proof, or point CODEX_HOME "
            "at an authenticated Codex home, then rerun clean-auth-onboarding."
        )

    with tempfile.TemporaryDirectory(prefix="omnigent-clean-auth-onboarding-proof-") as temp_root:
        root = Path(temp_root)
        clean_home = root / "home"
        clean_codex_home = root / "codex-home-clean"
        synthetic_codex_home = root / "codex-home-synthetic"
        clean_home.mkdir()
        clean_codex_home.mkdir()
        synthetic_codex_home.mkdir()
        synthetic_auth_path = synthetic_codex_home / "auth.json"
        synthetic_auth_path.write_text(
            json.dumps(
                {
                    "auth_mode": "api",
                    "OPENAI_API_KEY": "sk-test-clean-auth-onboarding-proof",
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

        clean_reason = _codex_auth_reason_for_env(
            home=clean_home,
            codex_home=clean_codex_home,
            stock_codex_path=stock_codex_path,
        )
        if clean_reason != "needs-auth":
            raise SystemExit(
                "Clean Codex auth classification did not require onboarding.\n"
                f"expected=needs-auth\nactual={clean_reason!r}"
            )

        synthetic_reason = _codex_auth_reason_for_env(
            home=clean_home,
            codex_home=synthetic_codex_home,
            stock_codex_path=stock_codex_path,
        )
        if synthetic_reason is not None:
            raise SystemExit(
                "Synthetic Codex auth classification did not report available.\n"
                f"expected=None\nactual={synthetic_reason!r}"
            )

        return CleanAuthOnboardingProof(
            stock_codex_path=stock_codex_path,
            stock_codex_version=codex_version(stock_codex_path),
            real_auth_path=real_auth_path,
            real_auth_source=real_auth_source,
            real_auth_available=real_auth_available,
            clean_home=clean_home,
            clean_codex_home=clean_codex_home,
            clean_unavailable_reason=clean_reason,
            synthetic_codex_home=synthetic_codex_home,
            synthetic_available_reason=synthetic_reason,
        )


def _stock_replacement_auth_source() -> tuple[Path, str]:
    """Return the Codex auth path to prove for the stock replacement track."""
    explicit = os.environ.get("CODEX_HOME", "").strip()
    if explicit:
        explicit_home = Path(explicit).expanduser()
        if ".codex-fork" not in explicit_home.parts:
            return codex_native._resolve_codex_auth_source().auth_path, "explicit-CODEX_HOME"
    return Path.home() / ".codex" / "auth.json", "stock-default-home"


def _codex_auth_reason_for_env(
    *,
    home: Path,
    codex_home: Path,
    stock_codex_path: Path,
) -> str | None:
    """Return the Codex auth classifier result for an isolated env."""
    with temporary_env(
        {
            "HOME": str(home),
            "CODEX_HOME": str(codex_home),
            OMNIGENT_STOCK_CODEX_PATH_ENV: str(stock_codex_path),
        }
    ):
        return codex_native._codex_auth_unavailable_reason()


def _run_installed_runtime_auth_classifier(
    *,
    installed_runtime_root: Path,
    home: Path,
    codex_home: Path,
    stock_codex_path: Path,
) -> tuple[Path, str | None, str]:
    """Run the packaged runtime's auth classifier in an isolated subprocess."""
    classifier_code = (
        "import json\n"
        "from omnigent import codex_native\n"
        "source = codex_native._resolve_codex_auth_source()\n"
        "reason = codex_native._codex_auth_unavailable_reason()\n"
        "print(json.dumps({"
        "'authPath': str(source.auth_path), "
        "'unavailableReason': reason"
        "}, sort_keys=True))\n"
    )
    python_path_entries = [str(installed_runtime_root)]
    if os.environ.get("PYTHONPATH"):
        python_path_entries.append(os.environ["PYTHONPATH"])
    env = os.environ.copy()
    env.update(
        {
            "HOME": str(home),
            "CODEX_HOME": str(codex_home),
            OMNIGENT_STOCK_CODEX_PATH_ENV: str(stock_codex_path),
            "PYTHONPATH": os.pathsep.join(python_path_entries),
        }
    )
    completed = subprocess.run(
        [sys.executable, "-c", classifier_code],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        cwd=installed_runtime_root,
        timeout=30,
    )
    combined_output = (completed.stdout or "") + (completed.stderr or "")
    if completed.returncode != 0:
        raise SystemExit(
            "Installed runtime auth classifier failed.\n"
            f"runtime={installed_runtime_root}\n"
            f"exit={completed.returncode}\n"
            f"stdout={completed.stdout}\n"
            f"stderr={completed.stderr}"
        )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise SystemExit(
            "Installed runtime auth classifier did not emit JSON.\n"
            f"stdout={completed.stdout}\nstderr={completed.stderr}"
        ) from exc
    if not isinstance(payload, dict):
        raise SystemExit(
            f"Installed runtime auth classifier emitted non-object JSON: {payload!r}"
        )
    auth_path = Path(_json_string(payload, "authPath")).expanduser().resolve()
    reason_raw = payload.get("unavailableReason")
    if reason_raw is not None and not isinstance(reason_raw, str):
        raise SystemExit(
            "Installed runtime auth classifier returned invalid reason: "
            f"{payload!r}"
        )
    return auth_path, reason_raw, combined_output


def print_clean_auth_onboarding_proof(proof: CleanAuthOnboardingProof) -> None:
    """Emit operator evidence for the clean Codex auth onboarding proof."""
    print("clean_auth_onboarding_rehearsal=selected")
    print(f"clean_auth_stock_codex_path={proof.stock_codex_path}")
    print(f"clean_auth_stock_codex_version={proof.stock_codex_version}")
    print(f"clean_auth_real_auth_path={proof.real_auth_path}")
    print(f"clean_auth_real_auth_source={proof.real_auth_source}")
    print(f"clean_auth_real_auth_available={proof.real_auth_available}")
    print(f"clean_auth_clean_home={proof.clean_home}")
    print(f"clean_auth_clean_codex_home={proof.clean_codex_home}")
    print(f"clean_auth_clean_unavailable_reason={proof.clean_unavailable_reason}")
    print(f"clean_auth_synthetic_codex_home={proof.synthetic_codex_home}")
    print(f"clean_auth_synthetic_available_reason={proof.synthetic_available_reason}")
    print("clean_auth_cache_lifecycle=temporary_removed_after_proof")
    print("clean_auth_onboarding_command=CODEX_HOME=<new-or-restored-codex-home> codex login")
    print(
        "ASSERTION: a clean HOME and clean CODEX_HOME with a stock Codex binary "
        "fail closed as needs-auth rather than falling back to the Codex fork"
    )
    print(
        "ASSERTION: a populated Codex auth.json is recognized through CODEX_HOME "
        "without running Codex login or exposing credential material"
    )
    print(
        "ASSERTION: the current real Codex auth source is available for the "
        "existing preserved-CODEX_HOME proof path"
    )


def run_stock_codex_compat_proof(
    source_bundle: Path,
    stock_codex_path: Path,
) -> StockCodexCompatProof:
    """Prove stock Codex can carry the plugin plus Omnigent bridge config."""
    source_bundle = source_bundle.expanduser().resolve()
    stock_codex_path = stock_codex_path.expanduser().resolve()
    stock_codex_version = codex_version(stock_codex_path)
    with tempfile.TemporaryDirectory(prefix="omnigent-stock-codex-compat-proof-") as temp_root:
        root = Path(temp_root).resolve()
        codex_home = root / "codex-home"
        temp_home = root / "home"
        bridge_dir = root / "omnigent-bridge"
        marketplace_root = root / "local-apple-workflow-marketplace"
        codex_home.mkdir(mode=0o700)
        temp_home.mkdir(mode=0o700)

        plugin_source_path = _write_stock_codex_compat_marketplace(
            source_bundle=source_bundle,
            marketplace_root=marketplace_root,
        )
        env = _stock_codex_compat_env(home=temp_home, codex_home=codex_home)

        _run_stock_codex_json(
            stock_codex_path,
            ["plugin", "marketplace", "add", str(marketplace_root), "--json"],
            env=env,
        )
        plugin_add_output = _run_stock_codex_json(
            stock_codex_path,
            ["plugin", "add", STOCK_CODEX_COMPAT_PLUGIN_ID, "--json"],
            env=env,
        )
        if not isinstance(plugin_add_output, dict):
            raise SystemExit("Codex plugin add output was not a JSON object.")
        marketplace_list_output = _run_stock_codex_json(
            stock_codex_path,
            ["plugin", "marketplace", "list", "--json"],
            env=env,
        )
        plugin_list_output = _run_stock_codex_json(
            stock_codex_path,
            ["plugin", "list", "--json"],
            env=env,
        )
        installed_plugin_path = Path(
            str(
                plugin_add_output.get(
                    "installedPath",
                    codex_home
                    / "plugins"
                    / "cache"
                    / STOCK_CODEX_COMPAT_MARKETPLACE
                    / PLUGIN_NAME
                    / "0.1.1",
                )
            )
        )
        _validate_stock_codex_compat_plugin_state(
            marketplace_list_output=marketplace_list_output,
            plugin_list_output=plugin_list_output,
            installed_plugin_path=installed_plugin_path,
        )

        write_mcp_bridge_config(bridge_dir)
        write_policy_hook_config(
            bridge_dir,
            ap_server_url=STOCK_CODEX_COMPAT_AP_SERVER_URL,
            ap_auth_headers={},
        )
        _inject_mcp_server_config(codex_home, bridge_dir, sys.executable)
        _write_codex_policy_hooks_file(codex_home, bridge_dir, sys.executable)

        mcp_list_output = _run_stock_codex_json(
            stock_codex_path,
            ["mcp", "list", "--json"],
            env=env,
        )
        mcp_omnigent_output = _run_stock_codex_json(
            stock_codex_path,
            ["mcp", "get", "omnigent", "--json"],
            env=env,
        )
        hook_events, mcp_servers, mcp_command, mcp_args = _validate_stock_codex_compat_bridge(
            codex_home=codex_home,
            bridge_dir=bridge_dir,
            mcp_list_output=mcp_list_output,
            mcp_omnigent_output=mcp_omnigent_output,
        )

        return StockCodexCompatProof(
            stock_codex_path=stock_codex_path,
            stock_codex_version=stock_codex_version,
            source_bundle=source_bundle,
            codex_home=codex_home,
            marketplace_root=marketplace_root,
            marketplace_name=STOCK_CODEX_COMPAT_MARKETPLACE,
            plugin_id=STOCK_CODEX_COMPAT_PLUGIN_ID,
            plugin_source_path=plugin_source_path,
            installed_plugin_path=installed_plugin_path,
            bridge_dir=bridge_dir,
            bridge_config_path=bridge_dir / "bridge.json",
            policy_hook_config_path=bridge_dir / "policy_hook.json",
            config_path=codex_home / "config.toml",
            hooks_path=codex_home / "hooks.json",
            hook_events=hook_events,
            mcp_servers=mcp_servers,
            mcp_omnigent_command=mcp_command,
            mcp_omnigent_args=mcp_args,
            marketplace_list_output=marketplace_list_output,
            plugin_list_output=plugin_list_output,
        )


def _write_stock_codex_compat_marketplace(
    *,
    source_bundle: Path,
    marketplace_root: Path,
) -> Path:
    """Write a disposable local Codex marketplace containing the Apple plugin."""
    if not (source_bundle / ".codex-plugin" / "plugin.json").is_file():
        raise SystemExit(f"Apple plugin manifest not found under {source_bundle}")
    plugin_source_path = marketplace_root / "plugins" / PLUGIN_NAME
    plugin_source_path.parent.mkdir(parents=True)
    shutil.copytree(source_bundle, plugin_source_path)
    manifest_path = marketplace_root / ".agents" / "plugins" / "marketplace.json"
    manifest_path.parent.mkdir(parents=True)
    manifest = {
        "name": STOCK_CODEX_COMPAT_MARKETPLACE,
        "interface": {"displayName": "Local Apple Workflow"},
        "plugins": [
            {
                "name": PLUGIN_NAME,
                "source": {"source": "local", "path": f"./plugins/{PLUGIN_NAME}"},
                "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
                "category": "Engineering",
            }
        ],
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return plugin_source_path


def _stock_codex_compat_default_adapter_tool_spec() -> StockCodexCompatAdapterToolSpec:
    """Return the single adapter tool spec used by the baseline adapter proof."""
    return StockCodexCompatAdapterToolSpec(
        name=STOCK_CODEX_COMPAT_ADAPTER_COMMAND_NAME,
        argument=STOCK_CODEX_COMPAT_ADAPTER_COMMAND_ARGUMENT,
        output_sentinel=STOCK_CODEX_COMPAT_ADAPTER_OUTPUT_SENTINEL,
        capability="adapter-proof",
        description=(
            "Return deterministic Omnigent adapter evidence for a wrapped "
            "stock Codex proof."
        ),
    )


def _stock_codex_compat_adapter_arbitration_tool_specs() -> tuple[
    StockCodexCompatAdapterToolSpec,
    StockCodexCompatAdapterToolSpec,
]:
    """Return the selected and rejected adapter specs for arbitration proof."""
    return (
        StockCodexCompatAdapterToolSpec(
            name=STOCK_CODEX_COMPAT_ADAPTER_ROUTE_COMMAND_NAME,
            argument=STOCK_CODEX_COMPAT_ADAPTER_ROUTE_COMMAND_ARGUMENT,
            output_sentinel=STOCK_CODEX_COMPAT_ADAPTER_ROUTE_OUTPUT_SENTINEL,
            capability="route-selection",
            description="Return deterministic route-selection adapter evidence.",
        ),
        StockCodexCompatAdapterToolSpec(
            name=STOCK_CODEX_COMPAT_ADAPTER_RELEASE_COMMAND_NAME,
            argument=STOCK_CODEX_COMPAT_ADAPTER_RELEASE_COMMAND_ARGUMENT,
            output_sentinel=STOCK_CODEX_COMPAT_ADAPTER_RELEASE_OUTPUT_SENTINEL,
            capability="release-notes",
            description="Return deterministic release-notes adapter evidence.",
        ),
    )


def _write_stock_codex_compat_adapter_command(
    adapter_bin: Path,
    spec: StockCodexCompatAdapterToolSpec,
) -> Path:
    """Write one deterministic wrapper-owned adapter command for a live proof."""
    return write_stock_codex_compat_adapter_command(adapter_bin, spec)


def _write_stock_codex_compat_adapter_probe(adapter_bin: Path) -> Path:
    """Write the deterministic single-tool adapter command for the live proof."""
    return _write_stock_codex_compat_adapter_command(
        adapter_bin,
        _stock_codex_compat_default_adapter_tool_spec(),
    )


def _write_stock_codex_compat_adapter_manifest(
    adapter_package: Path,
    adapter_bin: Path,
    *,
    tool_specs: tuple[StockCodexCompatAdapterToolSpec, ...] | None = None,
) -> Path:
    """Write a deterministic adapter package manifest for the live proof."""
    if tool_specs is None:
        tool_specs = (_stock_codex_compat_default_adapter_tool_spec(),)
    return write_stock_codex_compat_adapter_manifest(
        adapter_package,
        adapter_bin,
        tool_specs,
    )


def _stock_codex_compat_env(*, home: Path, codex_home: Path) -> dict[str, str]:
    """Return an isolated environment for stock Codex compatibility probes."""
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["CODEX_HOME"] = str(codex_home)
    return env


def _run_stock_codex_json(
    stock_codex_path: Path,
    args: list[str],
    *,
    env: Mapping[str, str],
    timeout: float = 30.0,
) -> dict[str, Any] | list[dict[str, Any]]:
    """Run a stock Codex JSON inspection command and parse its payload."""
    completed = subprocess.run(
        [str(stock_codex_path), *args],
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=dict(env),
    )
    if completed.returncode != 0:
        raise SystemExit(
            "Stock Codex compatibility command failed.\n"
            f"command={shlex.join([str(stock_codex_path), *args])}\n"
            f"exit={completed.returncode}\n"
            f"stdout={completed.stdout}\n"
            f"stderr={completed.stderr}"
        )
    try:
        payload = json.loads(completed.stdout or "null")
    except json.JSONDecodeError as exc:
        raise SystemExit(
            "Stock Codex compatibility command did not emit JSON.\n"
            f"command={shlex.join([str(stock_codex_path), *args])}\n"
            f"stdout={completed.stdout}\n"
            f"stderr={completed.stderr}"
        ) from exc
    if not isinstance(payload, (dict, list)):
        raise SystemExit(
            "Stock Codex compatibility command returned an unexpected JSON root.\n"
            f"command={shlex.join([str(stock_codex_path), *args])}\n"
            f"type={type(payload).__name__}"
        )
    return payload


def _stock_codex_supported_feature_names(
    stock_codex_path: Path,
    *,
    env: Mapping[str, str],
) -> tuple[str, ...]:
    """Return stock Codex features that can be enabled for an isolated proof run."""
    completed = subprocess.run(
        [str(stock_codex_path), "features", "list"],
        check=False,
        capture_output=True,
        text=True,
        timeout=30.0,
        env=dict(env),
    )
    if completed.returncode != 0:
        raise SystemExit(
            "Stock Codex compatibility proof could not inspect feature flags.\n"
            f"exit={completed.returncode}\n"
            f"stdout={completed.stdout}\n"
            f"stderr={completed.stderr}"
        )
    features: list[str] = []
    for line in completed.stdout.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        parsed = re.match(
            r"^(?P<name>\S+)\s+"
            r"(?P<stage>stable|experimental|under development|deprecated|removed)\s+"
            r"(?:true|false)$",
            stripped,
        )
        if not parsed:
            continue
        feature_name = parsed.group("name")
        if (
            parsed.group("stage") in STOCK_CODEX_SUPPORTED_FEATURE_STAGES
            and feature_name not in STOCK_CODEX_FEATURES_REQUIRING_NONDEFAULT_SUPPORT
        ):
            features.append(feature_name)
    if not features:
        raise SystemExit(
            "Stock Codex compatibility proof found no enableable feature flags in "
            f"`codex features list` output:\n{completed.stdout}"
        )
    return tuple(features)


def _stock_codex_enable_feature_args(features: tuple[str, ...]) -> list[str]:
    """Render repeatable ``--enable`` args for a stock Codex feature set."""
    args: list[str] = []
    for feature in features:
        args.extend(["--enable", feature])
    return args


def _validate_stock_codex_compat_plugin_state(
    *,
    marketplace_list_output: dict[str, Any] | list[dict[str, Any]],
    plugin_list_output: dict[str, Any] | list[dict[str, Any]],
    installed_plugin_path: Path,
) -> None:
    """Fail closed unless stock Codex sees the installed Apple plugin."""
    if not isinstance(marketplace_list_output, dict):
        raise SystemExit("Codex marketplace list output was not a JSON object.")
    marketplaces = marketplace_list_output.get("marketplaces")
    if not isinstance(marketplaces, list):
        raise SystemExit("Codex marketplace list output did not contain marketplaces.")
    marketplace_names = {
        item.get("name") for item in marketplaces if isinstance(item, dict)
    }
    if STOCK_CODEX_COMPAT_MARKETPLACE not in marketplace_names:
        raise SystemExit(
            "Stock Codex did not register the local Apple workflow marketplace.\n"
            f"marketplaces={sorted(str(name) for name in marketplace_names)}"
        )
    if not isinstance(plugin_list_output, dict):
        raise SystemExit("Codex plugin list output was not a JSON object.")
    installed = plugin_list_output.get("installed")
    if not isinstance(installed, list):
        raise SystemExit("Codex plugin list output did not contain installed plugins.")
    matching = [
        item
        for item in installed
        if isinstance(item, dict) and item.get("pluginId") == STOCK_CODEX_COMPAT_PLUGIN_ID
    ]
    if not matching:
        raise SystemExit(
            "Stock Codex did not report the Apple workflow plugin as installed.\n"
            f"expected={STOCK_CODEX_COMPAT_PLUGIN_ID}"
        )
    if matching[0].get("enabled") is not True:
        raise SystemExit(
            "Stock Codex installed the Apple workflow plugin but did not enable it.\n"
            f"plugin={matching[0]!r}"
        )
    if not installed_plugin_path.is_dir():
        raise SystemExit(f"Installed Apple workflow plugin path missing: {installed_plugin_path}")


def _validate_stock_codex_compat_bridge(
    *,
    codex_home: Path,
    bridge_dir: Path,
    mcp_list_output: dict[str, Any] | list[dict[str, Any]],
    mcp_omnigent_output: dict[str, Any] | list[dict[str, Any]],
) -> tuple[tuple[str, ...], tuple[str, ...], str, tuple[str, ...]]:
    """Fail closed unless stock Codex sees the Omnigent MCP and hook bridge."""
    config_path = codex_home / "config.toml"
    hooks_path = codex_home / "hooks.json"
    bridge_config_path = bridge_dir / "bridge.json"
    policy_hook_config_path = bridge_dir / "policy_hook.json"
    missing = [
        path
        for path in (config_path, hooks_path, bridge_config_path, policy_hook_config_path)
        if not path.is_file()
    ]
    if missing:
        raise SystemExit(f"Stock Codex compatibility bridge files missing: {missing!r}")
    if not isinstance(mcp_list_output, list):
        raise SystemExit("Codex mcp list output was not a JSON list.")
    mcp_servers = tuple(
        sorted(
            str(item.get("name"))
            for item in mcp_list_output
            if isinstance(item, dict) and item.get("name")
        )
    )
    if "omnigent" not in mcp_servers:
        raise SystemExit(f"Codex mcp list did not include omnigent; servers={mcp_servers!r}")
    if not isinstance(mcp_omnigent_output, dict):
        raise SystemExit("Codex mcp get omnigent output was not a JSON object.")
    if mcp_omnigent_output.get("name") != "omnigent":
        raise SystemExit(f"Codex mcp get returned the wrong server: {mcp_omnigent_output!r}")
    transport = mcp_omnigent_output.get("transport")
    if not isinstance(transport, dict):
        raise SystemExit(f"Codex mcp get omnigent omitted transport: {mcp_omnigent_output!r}")
    command = transport.get("command")
    args = transport.get("args")
    if not isinstance(command, str) or not isinstance(args, list):
        raise SystemExit(f"Codex mcp get omnigent returned malformed transport: {transport!r}")
    args_tuple = tuple(str(arg) for arg in args)
    required_args = ("-I", "-m", "omnigent.claude_native_bridge", "serve-mcp", "--bridge-dir")
    if not all(arg in args_tuple for arg in required_args) or str(bridge_dir) not in args_tuple:
        raise SystemExit(f"Omnigent MCP bridge args did not match expected shape: {args_tuple!r}")

    hooks_payload = json.loads(hooks_path.read_text(encoding="utf-8"))
    hooks = hooks_payload.get("hooks") if isinstance(hooks_payload, dict) else None
    if not isinstance(hooks, dict):
        raise SystemExit(f"Codex hooks.json has unexpected shape: {hooks_payload!r}")
    expected_events = ("PostToolUse", "PreToolUse", "UserPromptSubmit")
    for event in expected_events:
        entries = hooks.get(event)
        if not isinstance(entries, list) or not entries:
            raise SystemExit(f"Codex hooks.json missing {event} hook: {hooks_payload!r}")
        command_text = entries[0]["hooks"][0]["command"]
        if "omnigent.codex_native_hook" not in command_text or str(bridge_dir) not in command_text:
            raise SystemExit(
                f"Codex {event} hook command does not target Omnigent: {command_text}"
            )
    return expected_events, mcp_servers, command, args_tuple


def print_stock_codex_compat_proof(proof: StockCodexCompatProof) -> None:
    """Emit operator evidence for the stock Codex compatibility proof."""
    print("stock_codex_compat_rehearsal=selected")
    print(f"stock_codex_compat_stock_codex_path={proof.stock_codex_path}")
    print(f"stock_codex_compat_stock_codex_version={proof.stock_codex_version}")
    print(f"stock_codex_compat_source_bundle={proof.source_bundle}")
    print(f"stock_codex_compat_codex_home={proof.codex_home}")
    print(f"stock_codex_compat_marketplace_root={proof.marketplace_root}")
    print(f"stock_codex_compat_marketplace_name={proof.marketplace_name}")
    print(f"stock_codex_compat_plugin_id={proof.plugin_id}")
    print(f"stock_codex_compat_plugin_source={proof.plugin_source_path}")
    print(f"stock_codex_compat_installed_plugin={proof.installed_plugin_path}")
    print(f"stock_codex_compat_config={proof.config_path}")
    print(f"stock_codex_compat_bridge_dir={proof.bridge_dir}")
    print(f"stock_codex_compat_bridge_config={proof.bridge_config_path}")
    print(f"stock_codex_compat_policy_hook_config={proof.policy_hook_config_path}")
    print(f"stock_codex_compat_hooks={proof.hooks_path}")
    print(f"stock_codex_compat_hook_events={','.join(proof.hook_events)}")
    print(f"stock_codex_compat_mcp_servers={','.join(proof.mcp_servers)}")
    print(f"stock_codex_compat_mcp_omnigent_command={proof.mcp_omnigent_command}")
    print(f"stock_codex_compat_mcp_omnigent_args={json.dumps(list(proof.mcp_omnigent_args))}")
    print("stock_codex_compat_cache_lifecycle=temporary_removed_after_proof")
    print(
        "ASSERTION: stock Codex installed and enabled the Apple workflow plugin "
        "from a disposable local marketplace without mutating persistent CODEX_HOME"
    )
    print(
        "ASSERTION: stock Codex read the Omnigent MCP bridge through its own "
        "mcp list/get commands from an isolated CODEX_HOME"
    )
    print(
        "ASSERTION: the isolated CODEX_HOME carries Omnigent PreToolUse, "
        "PostToolUse, and UserPromptSubmit policy hooks"
    )
    print(
        "ASSERTION: this is an install/config compatibility gate; live "
        "route-before-model parity still requires a separate stock-entrypoint "
        "session proof"
    )


def run_stock_codex_compat_live_proof(
    source_bundle: Path,
    stock_codex_path: Path,
    *,
    workspace_root: Path,
    timeout_seconds: float,
) -> StockCodexCompatLiveProof:
    """Prove a stock Codex entrypoint emits route evidence through the bridge."""
    source_bundle = source_bundle.expanduser().resolve()
    stock_codex_path = stock_codex_path.expanduser().resolve()
    workspace_root = workspace_root.expanduser().resolve()
    stock_codex_version = codex_version(stock_codex_path)
    auth_path, auth_source = _stock_replacement_auth_source()
    if not codex_native._codex_auth_json_has_available_credential(auth_path):
        raise SystemExit(
            "Current real Codex auth source is not available; cannot run live "
            "stock-codex-compat proof.\n"
            f"auth_path={auth_path}\n"
            f"auth_source={auth_source}"
        )

    with tempfile.TemporaryDirectory(
        prefix="omnigent-stock-codex-compat-live-proof-"
    ) as temp_root:
        root = Path(temp_root).resolve()
        codex_home = root / "codex-home"
        temp_home = root / "home"
        bridge_dir = root / "omnigent-bridge"
        marketplace_root = root / "local-apple-workflow-marketplace"
        codex_home.mkdir(mode=0o700)
        temp_home.mkdir(mode=0o700)
        (codex_home / "auth.json").symlink_to(auth_path)

        _write_stock_codex_compat_marketplace(
            source_bundle=source_bundle,
            marketplace_root=marketplace_root,
        )
        env = _stock_codex_compat_env(home=temp_home, codex_home=codex_home)
        _run_stock_codex_json(
            stock_codex_path,
            ["plugin", "marketplace", "add", str(marketplace_root), "--json"],
            env=env,
        )
        _run_stock_codex_json(
            stock_codex_path,
            ["plugin", "add", STOCK_CODEX_COMPAT_PLUGIN_ID, "--json"],
            env=env,
        )
        plugin_list_output = _run_stock_codex_json(
            stock_codex_path,
            ["plugin", "list", "--json"],
            env=env,
        )
        _validate_stock_codex_compat_plugin_state(
            marketplace_list_output=_run_stock_codex_json(
                stock_codex_path,
                ["plugin", "marketplace", "list", "--json"],
                env=env,
            ),
            plugin_list_output=plugin_list_output,
            installed_plugin_path=(
                codex_home
                / "plugins"
                / "cache"
                / STOCK_CODEX_COMPAT_MARKETPLACE
                / PLUGIN_NAME
                / "0.1.1"
            ),
        )

        write_mcp_bridge_config(bridge_dir)
        write_policy_hook_config(
            bridge_dir,
            ap_server_url=STOCK_CODEX_COMPAT_AP_SERVER_URL,
            ap_auth_headers={},
        )
        _inject_mcp_server_config(codex_home, bridge_dir, sys.executable)
        _write_codex_policy_hooks_file(codex_home, bridge_dir, sys.executable)
        mcp_list_output = _run_stock_codex_json(
            stock_codex_path,
            ["mcp", "list", "--json"],
            env=env,
        )
        mcp_omnigent_output = _run_stock_codex_json(
            stock_codex_path,
            ["mcp", "get", "omnigent", "--json"],
            env=env,
        )
        _hook_events, mcp_servers, _mcp_command, _mcp_args = _validate_stock_codex_compat_bridge(
            codex_home=codex_home,
            bridge_dir=bridge_dir,
            mcp_list_output=mcp_list_output,
            mcp_omnigent_output=mcp_omnigent_output,
        )

        prompt = (
            "No-tool stock-codex-compat live proof for a SwiftUI workflow. "
            "Do not inspect files, do not run commands, and do not explain. "
            "If an installed compatibility layer already inserted route "
            "evidence before this instruction, preserve that route evidence "
            f"first. Then reply exactly {STOCK_CODEX_COMPAT_LIVE_SENTINEL}."
        )
        completed = subprocess.run(
            [
                str(stock_codex_path),
                "exec",
                "--json",
                "--dangerously-bypass-hook-trust",
                "--skip-git-repo-check",
                "--sandbox",
                "read-only",
                "-C",
                str(workspace_root),
                prompt,
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds if timeout_seconds > 0 else None,
            env=env,
            stdin=subprocess.DEVNULL,
        )
        stderr_preview = _preview_text(completed.stderr, limit=2000)
        if completed.returncode != 0:
            raise SystemExit(
                "Live stock-codex-compat command failed.\n"
                f"exit={completed.returncode}\n"
                f"stderr={stderr_preview}\n"
                f"stdout_preview={_preview_text(completed.stdout, limit=2000)}"
            )
        events = _parse_stock_codex_exec_jsonl(completed.stdout)
        thread_id, first_agent_message = _validate_stock_codex_compat_live_events(events)
        if not first_agent_message.startswith(EXPECTED_ROUTE):
            raise SystemExit(
                "Live stock-codex-compat proof did not emit deterministic route "
                "evidence before model output.\n"
                f"expected_prefix={EXPECTED_ROUTE!r}\n"
                f"first_agent_message={first_agent_message!r}\n"
                f"sentinel={STOCK_CODEX_COMPAT_LIVE_SENTINEL!r}\n"
                "diagnosis=current Omnigent Codex policy hook can block "
                "UserPromptSubmit but does not rewrite or prepend prompt context "
                "for a stock Codex entrypoint."
            )
        return StockCodexCompatLiveProof(
            stock_codex_path=stock_codex_path,
            stock_codex_version=stock_codex_version,
            source_bundle=source_bundle,
            codex_home=codex_home,
            auth_path=auth_path,
            bridge_dir=bridge_dir,
            workspace_root=workspace_root,
            thread_id=thread_id,
            first_agent_message=first_agent_message,
            event_count=len(events),
            mcp_servers=mcp_servers,
            stderr_preview=stderr_preview,
        )


def run_stock_codex_compat_wrapper_live_proof(
    source_bundle: Path,
    stock_codex_path: Path,
    *,
    workspace_root: Path,
    timeout_seconds: float,
) -> StockCodexCompatWrapperLiveProof:
    """Prove an Omnigent-owned wrapper can prefix route evidence around stock Codex."""
    source_bundle = source_bundle.expanduser().resolve()
    stock_codex_path = stock_codex_path.expanduser().resolve()
    workspace_root = workspace_root.expanduser().resolve()
    stock_codex_version = codex_version(stock_codex_path)
    auth_path, auth_source = _stock_replacement_auth_source()
    if not codex_native._codex_auth_json_has_available_credential(auth_path):
        raise SystemExit(
            "Current real Codex auth source is not available; cannot run live "
            "stock-codex-compat-wrapper proof.\n"
            f"auth_path={auth_path}\n"
            f"auth_source={auth_source}"
        )

    with tempfile.TemporaryDirectory(
        prefix="omnigent-stock-codex-compat-wrapper-live-proof-"
    ) as temp_root:
        root = Path(temp_root).resolve()
        codex_home = root / "codex-home"
        temp_home = root / "home"
        bridge_dir = root / "omnigent-bridge"
        marketplace_root = root / "local-apple-workflow-marketplace"
        wrapper_path = Path(stock_codex_compat_wrapper.__file__).resolve()
        wrapper_evidence_path = root / "wrapper-evidence.json"
        codex_home.mkdir(mode=0o700)
        temp_home.mkdir(mode=0o700)
        (codex_home / "auth.json").symlink_to(auth_path)

        _write_stock_codex_compat_marketplace(
            source_bundle=source_bundle,
            marketplace_root=marketplace_root,
        )
        env = _stock_codex_compat_env(home=temp_home, codex_home=codex_home)
        _run_stock_codex_json(
            stock_codex_path,
            ["plugin", "marketplace", "add", str(marketplace_root), "--json"],
            env=env,
        )
        _run_stock_codex_json(
            stock_codex_path,
            ["plugin", "add", STOCK_CODEX_COMPAT_PLUGIN_ID, "--json"],
            env=env,
        )
        plugin_list_output = _run_stock_codex_json(
            stock_codex_path,
            ["plugin", "list", "--json"],
            env=env,
        )
        _validate_stock_codex_compat_plugin_state(
            marketplace_list_output=_run_stock_codex_json(
                stock_codex_path,
                ["plugin", "marketplace", "list", "--json"],
                env=env,
            ),
            plugin_list_output=plugin_list_output,
            installed_plugin_path=(
                codex_home
                / "plugins"
                / "cache"
                / STOCK_CODEX_COMPAT_MARKETPLACE
                / PLUGIN_NAME
                / "0.1.1"
            ),
        )

        write_mcp_bridge_config(bridge_dir)
        write_policy_hook_config(
            bridge_dir,
            ap_server_url=STOCK_CODEX_COMPAT_AP_SERVER_URL,
            ap_auth_headers={},
        )
        _inject_mcp_server_config(codex_home, bridge_dir, sys.executable)
        _write_codex_policy_hooks_file(codex_home, bridge_dir, sys.executable)
        mcp_list_output = _run_stock_codex_json(
            stock_codex_path,
            ["mcp", "list", "--json"],
            env=env,
        )
        mcp_omnigent_output = _run_stock_codex_json(
            stock_codex_path,
            ["mcp", "get", "omnigent", "--json"],
            env=env,
        )
        _hook_events, mcp_servers, _mcp_command, _mcp_args = _validate_stock_codex_compat_bridge(
            codex_home=codex_home,
            bridge_dir=bridge_dir,
            mcp_list_output=mcp_list_output,
            mcp_omnigent_output=mcp_omnigent_output,
        )

        prompt = (
            "No-tool stock-codex-compat wrapper live proof for a SwiftUI workflow. "
            "Do not inspect files, do not run commands, and do not explain. "
            f"Reply exactly {STOCK_CODEX_COMPAT_LIVE_SENTINEL}."
        )
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "omnigent.stock_codex_compat_wrapper",
                "--stock-codex-path",
                str(stock_codex_path),
                "--route-prefix",
                EXPECTED_ROUTE,
                "--evidence-path",
                str(wrapper_evidence_path),
                "--",
                "exec",
                "--json",
                "--dangerously-bypass-hook-trust",
                "--skip-git-repo-check",
                "--sandbox",
                "read-only",
                "-C",
                str(workspace_root),
                prompt,
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds if timeout_seconds > 0 else None,
            env=env,
            stdin=subprocess.DEVNULL,
        )
        stderr_preview = _preview_text(completed.stderr, limit=2000)
        if completed.returncode != 0:
            raise SystemExit(
                "Live stock-codex-compat-wrapper command failed.\n"
                f"exit={completed.returncode}\n"
                f"stderr={stderr_preview}\n"
                f"stdout_preview={_preview_text(completed.stdout, limit=2000)}"
            )
        events = _parse_stock_codex_exec_jsonl(completed.stdout)
        thread_id, first_agent_message = _validate_stock_codex_compat_live_events(events)
        if not first_agent_message.startswith(EXPECTED_ROUTE):
            raise SystemExit(
                "Live stock-codex-compat-wrapper proof did not emit deterministic "
                "route evidence before model output.\n"
                f"expected_prefix={EXPECTED_ROUTE!r}\n"
                f"first_agent_message={first_agent_message!r}\n"
                f"sentinel={STOCK_CODEX_COMPAT_LIVE_SENTINEL!r}\n"
                "diagnosis=the Omnigent wrapper did not prefix the first "
                "stock Codex agent message."
            )
        wrapper_evidence = _read_stock_codex_compat_wrapper_evidence(wrapper_evidence_path)
        if wrapper_evidence["routeInjected"] is not True:
            raise SystemExit(
                "Live stock-codex-compat-wrapper proof did not prove wrapper-owned "
                "route injection.\n"
                f"evidence={wrapper_evidence!r}"
            )
        return StockCodexCompatWrapperLiveProof(
            stock_codex_path=stock_codex_path,
            stock_codex_version=stock_codex_version,
            source_bundle=source_bundle,
            wrapper_path=wrapper_path,
            codex_home=codex_home,
            auth_path=auth_path,
            bridge_dir=bridge_dir,
            workspace_root=workspace_root,
            thread_id=thread_id,
            first_agent_message=first_agent_message,
            first_agent_message_before_wrapper=str(
                wrapper_evidence["firstAgentMessageBefore"]
            ),
            route_injected=bool(wrapper_evidence["routeInjected"]),
            wrapper_evidence_path=wrapper_evidence_path,
            event_count=len(events),
            mcp_servers=mcp_servers,
            stderr_preview=stderr_preview,
        )


def run_stock_codex_compat_wrapper_command_tool_proof(
    source_bundle: Path,
    stock_codex_path: Path,
    *,
    timeout_seconds: float,
) -> StockCodexCompatWrapperCommandToolProof:
    """Prove the wrapper preserves stock Codex command tool execution events."""
    source_bundle = source_bundle.expanduser().resolve()
    stock_codex_path = stock_codex_path.expanduser().resolve()
    stock_codex_version = codex_version(stock_codex_path)
    auth_path, auth_source = _stock_replacement_auth_source()
    if not codex_native._codex_auth_json_has_available_credential(auth_path):
        raise SystemExit(
            "Current real Codex auth source is not available; cannot run live "
            "stock-codex-compat-wrapper-command-tool proof.\n"
            f"auth_path={auth_path}\n"
            f"auth_source={auth_source}"
        )

    with tempfile.TemporaryDirectory(
        prefix="omnigent-stock-codex-compat-wrapper-tool-proof-"
    ) as temp_root:
        root = Path(temp_root).resolve()
        codex_home = root / "codex-home"
        temp_home = root / "home"
        bridge_dir = root / "omnigent-bridge"
        marketplace_root = root / "local-apple-workflow-marketplace"
        wrapper_path = Path(stock_codex_compat_wrapper.__file__).resolve()
        wrapper_evidence_path = root / "wrapper-evidence.json"
        workspace_root = root / "workspace"
        codex_home.mkdir(mode=0o700)
        temp_home.mkdir(mode=0o700)
        workspace_root.mkdir(mode=0o700)
        (workspace_root / "tool-proof.txt").write_text(
            f"{TOOL_SENTINEL}\n",
            encoding="utf-8",
        )
        (codex_home / "auth.json").symlink_to(auth_path)

        _write_stock_codex_compat_marketplace(
            source_bundle=source_bundle,
            marketplace_root=marketplace_root,
        )
        env = _stock_codex_compat_env(home=temp_home, codex_home=codex_home)
        _run_stock_codex_json(
            stock_codex_path,
            ["plugin", "marketplace", "add", str(marketplace_root), "--json"],
            env=env,
        )
        _run_stock_codex_json(
            stock_codex_path,
            ["plugin", "add", STOCK_CODEX_COMPAT_PLUGIN_ID, "--json"],
            env=env,
        )
        plugin_list_output = _run_stock_codex_json(
            stock_codex_path,
            ["plugin", "list", "--json"],
            env=env,
        )
        _validate_stock_codex_compat_plugin_state(
            marketplace_list_output=_run_stock_codex_json(
                stock_codex_path,
                ["plugin", "marketplace", "list", "--json"],
                env=env,
            ),
            plugin_list_output=plugin_list_output,
            installed_plugin_path=(
                codex_home
                / "plugins"
                / "cache"
                / STOCK_CODEX_COMPAT_MARKETPLACE
                / PLUGIN_NAME
                / "0.1.1"
            ),
        )

        write_mcp_bridge_config(bridge_dir)
        write_policy_hook_config(
            bridge_dir,
            ap_server_url=STOCK_CODEX_COMPAT_AP_SERVER_URL,
            ap_auth_headers={},
        )
        _inject_mcp_server_config(codex_home, bridge_dir, sys.executable)
        _write_codex_policy_hooks_file(codex_home, bridge_dir, sys.executable)
        mcp_list_output = _run_stock_codex_json(
            stock_codex_path,
            ["mcp", "list", "--json"],
            env=env,
        )
        mcp_omnigent_output = _run_stock_codex_json(
            stock_codex_path,
            ["mcp", "get", "omnigent", "--json"],
            env=env,
        )
        _hook_events, mcp_servers, _mcp_command, _mcp_args = _validate_stock_codex_compat_bridge(
            codex_home=codex_home,
            bridge_dir=bridge_dir,
            mcp_list_output=mcp_list_output,
            mcp_omnigent_output=mcp_omnigent_output,
        )

        prompt = (
            "Wrapped stock Codex command tool proof. Use the shell command tool "
            "exactly once to run `cat tool-proof.txt`. Do not inspect any other "
            "files. Reply exactly "
            f"{STOCK_CODEX_COMPAT_WRAPPER_TOOL_SENTINEL} if the output contains "
            f"{TOOL_SENTINEL}; otherwise reply TOOL_MISSING."
        )
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "omnigent.stock_codex_compat_wrapper",
                "--stock-codex-path",
                str(stock_codex_path),
                "--route-prefix",
                EXPECTED_ROUTE,
                "--evidence-path",
                str(wrapper_evidence_path),
                "--",
                "exec",
                "--json",
                "--dangerously-bypass-hook-trust",
                "--skip-git-repo-check",
                "--sandbox",
                "read-only",
                "-C",
                str(workspace_root),
                prompt,
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds if timeout_seconds > 0 else None,
            env=env,
            stdin=subprocess.DEVNULL,
        )
        stderr_preview = _preview_text(completed.stderr, limit=2000)
        if completed.returncode != 0:
            raise SystemExit(
                "Live stock-codex-compat-wrapper-command-tool command failed.\n"
                f"exit={completed.returncode}\n"
                f"stderr={stderr_preview}\n"
                f"stdout_preview={_preview_text(completed.stdout, limit=2000)}"
            )
        events = _parse_stock_codex_exec_jsonl(completed.stdout)
        thread_id, first_agent_message = _validate_stock_codex_agent_message(
            events,
            expected_sentinel=STOCK_CODEX_COMPAT_WRAPPER_TOOL_SENTINEL,
            proof_name="stock-codex-compat-wrapper-command-tool",
        )
        if not first_agent_message.startswith(EXPECTED_ROUTE):
            raise SystemExit(
                "Live stock-codex-compat-wrapper-command-tool proof did not emit "
                "deterministic route evidence before model output.\n"
                f"expected_prefix={EXPECTED_ROUTE!r}\n"
                f"first_agent_message={first_agent_message!r}"
            )
        command_item = _validate_stock_codex_command_execution_events(events)
        wrapper_evidence = _read_stock_codex_compat_wrapper_evidence(wrapper_evidence_path)
        if wrapper_evidence["routeInjected"] is not True:
            raise SystemExit(
                "Live stock-codex-compat-wrapper-command-tool proof did not prove "
                "wrapper-owned route injection.\n"
                f"evidence={wrapper_evidence!r}"
            )
        return StockCodexCompatWrapperCommandToolProof(
            stock_codex_path=stock_codex_path,
            stock_codex_version=stock_codex_version,
            source_bundle=source_bundle,
            wrapper_path=wrapper_path,
            codex_home=codex_home,
            auth_path=auth_path,
            bridge_dir=bridge_dir,
            workspace_root=workspace_root,
            thread_id=thread_id,
            command=str(command_item["command"]),
            command_output=str(command_item["aggregated_output"]),
            first_agent_message=first_agent_message,
            first_agent_message_before_wrapper=str(
                wrapper_evidence["firstAgentMessageBefore"]
            ),
            route_injected=bool(wrapper_evidence["routeInjected"]),
            wrapper_evidence_path=wrapper_evidence_path,
            event_count=len(events),
            mcp_servers=mcp_servers,
            stderr_preview=stderr_preview,
        )


def run_stock_codex_compat_wrapper_adapter_tool_proof(
    source_bundle: Path,
    stock_codex_path: Path,
    *,
    timeout_seconds: float,
) -> StockCodexCompatWrapperAdapterToolProof:
    """Prove the wrapper can expose an Omnigent-owned adapter command to stock Codex."""
    source_bundle = source_bundle.expanduser().resolve()
    stock_codex_path = stock_codex_path.expanduser().resolve()
    stock_codex_version = codex_version(stock_codex_path)
    auth_path, auth_source = _stock_replacement_auth_source()
    if not codex_native._codex_auth_json_has_available_credential(auth_path):
        raise SystemExit(
            "Current real Codex auth source is not available; cannot run live "
            "stock-codex-compat-wrapper-adapter-tool proof.\n"
            f"auth_path={auth_path}\n"
            f"auth_source={auth_source}"
        )

    with tempfile.TemporaryDirectory(
        prefix="omnigent-stock-codex-compat-wrapper-adapter-tool-proof-"
    ) as temp_root:
        root = Path(temp_root).resolve()
        codex_home = root / "codex-home"
        temp_home = root / "home"
        bridge_dir = root / "omnigent-bridge"
        marketplace_root = root / "local-apple-workflow-marketplace"
        wrapper_path = Path(stock_codex_compat_wrapper.__file__).resolve()
        wrapper_evidence_path = root / "wrapper-evidence.json"
        workspace_root = root / "workspace"
        adapter_package = root / "adapter-package"
        codex_home.mkdir(mode=0o700)
        temp_home.mkdir(mode=0o700)
        workspace_root.mkdir(mode=0o700)
        adapter_package_result = write_stock_codex_compat_adapter_package(
            adapter_package,
            (_stock_codex_compat_default_adapter_tool_spec(),),
        )
        adapter_bin = adapter_package_result.adapter_bin
        adapter_manifest = adapter_package_result.manifest_path
        (codex_home / "auth.json").symlink_to(auth_path)

        _write_stock_codex_compat_marketplace(
            source_bundle=source_bundle,
            marketplace_root=marketplace_root,
        )
        env = _stock_codex_compat_env(home=temp_home, codex_home=codex_home)
        _run_stock_codex_json(
            stock_codex_path,
            ["plugin", "marketplace", "add", str(marketplace_root), "--json"],
            env=env,
        )
        _run_stock_codex_json(
            stock_codex_path,
            ["plugin", "add", STOCK_CODEX_COMPAT_PLUGIN_ID, "--json"],
            env=env,
        )
        plugin_list_output = _run_stock_codex_json(
            stock_codex_path,
            ["plugin", "list", "--json"],
            env=env,
        )
        _validate_stock_codex_compat_plugin_state(
            marketplace_list_output=_run_stock_codex_json(
                stock_codex_path,
                ["plugin", "marketplace", "list", "--json"],
                env=env,
            ),
            plugin_list_output=plugin_list_output,
            installed_plugin_path=(
                codex_home
                / "plugins"
                / "cache"
                / STOCK_CODEX_COMPAT_MARKETPLACE
                / PLUGIN_NAME
                / "0.1.1"
            ),
        )

        write_mcp_bridge_config(bridge_dir)
        write_policy_hook_config(
            bridge_dir,
            ap_server_url=STOCK_CODEX_COMPAT_AP_SERVER_URL,
            ap_auth_headers={},
        )
        _inject_mcp_server_config(codex_home, bridge_dir, sys.executable)
        _write_codex_policy_hooks_file(codex_home, bridge_dir, sys.executable)
        mcp_list_output = _run_stock_codex_json(
            stock_codex_path,
            ["mcp", "list", "--json"],
            env=env,
        )
        mcp_omnigent_output = _run_stock_codex_json(
            stock_codex_path,
            ["mcp", "get", "omnigent", "--json"],
            env=env,
        )
        _hook_events, mcp_servers, _mcp_command, _mcp_args = _validate_stock_codex_compat_bridge(
            codex_home=codex_home,
            bridge_dir=bridge_dir,
            mcp_list_output=mcp_list_output,
            mcp_omnigent_output=mcp_omnigent_output,
        )

        adapter_command = (
            f"{STOCK_CODEX_COMPAT_ADAPTER_COMMAND_NAME} "
            f"--message {STOCK_CODEX_COMPAT_ADAPTER_COMMAND_ARGUMENT}"
        )
        adapter_arguments = json.dumps(
            {"message": STOCK_CODEX_COMPAT_ADAPTER_COMMAND_ARGUMENT},
            sort_keys=True,
        )
        prompt = (
            "Wrapped stock Codex Omnigent adapter package proof. Use the shell "
            f"command tool exactly once to run `{adapter_command}` with adapter "
            f"argument object `{adapter_arguments}`. Do not inspect files and "
            "do not use any other tool. Reply exactly "
            f"{STOCK_CODEX_COMPAT_WRAPPER_ADAPTER_TOOL_SENTINEL} if stdout "
            f"contains {STOCK_CODEX_COMPAT_ADAPTER_OUTPUT_SENTINEL}; otherwise "
            "reply ADAPTER_TOOL_MISSING."
        )
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "omnigent.stock_codex_compat_wrapper",
                "--stock-codex-path",
                str(stock_codex_path),
                "--route-prefix",
                EXPECTED_ROUTE,
                "--evidence-path",
                str(wrapper_evidence_path),
                "--adapter-bin",
                str(adapter_bin),
                "--adapter-manifest",
                str(adapter_manifest),
                "--",
                "exec",
                "--json",
                "--dangerously-bypass-hook-trust",
                "--skip-git-repo-check",
                "--sandbox",
                "read-only",
                "-C",
                str(workspace_root),
                prompt,
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds if timeout_seconds > 0 else None,
            env=env,
            stdin=subprocess.DEVNULL,
        )
        stderr_preview = _preview_text(completed.stderr, limit=2000)
        if completed.returncode != 0:
            raise SystemExit(
                "Live stock-codex-compat-wrapper-adapter-tool command failed.\n"
                f"exit={completed.returncode}\n"
                f"stderr={stderr_preview}\n"
                f"stdout_preview={_preview_text(completed.stdout, limit=2000)}"
            )
        events = _parse_stock_codex_exec_jsonl(completed.stdout)
        thread_id, first_agent_message = _validate_stock_codex_agent_message(
            events,
            expected_sentinel=STOCK_CODEX_COMPAT_WRAPPER_ADAPTER_TOOL_SENTINEL,
            proof_name="stock-codex-compat-wrapper-adapter-tool",
        )
        if not first_agent_message.startswith(EXPECTED_ROUTE):
            raise SystemExit(
                "Live stock-codex-compat-wrapper-adapter-tool proof did not emit "
                "deterministic route evidence before model output.\n"
                f"expected_prefix={EXPECTED_ROUTE!r}\n"
                f"first_agent_message={first_agent_message!r}"
            )
        command_item = _validate_stock_codex_adapter_command_execution_events(events)
        wrapper_evidence = _read_stock_codex_compat_wrapper_evidence(wrapper_evidence_path)
        if wrapper_evidence["routeInjected"] is not True:
            raise SystemExit(
                "Live stock-codex-compat-wrapper-adapter-tool proof did not prove "
                "wrapper-owned route injection.\n"
                f"evidence={wrapper_evidence!r}"
            )
        if wrapper_evidence.get("adapterBin") != str(adapter_bin):
            raise SystemExit(
                "Live stock-codex-compat-wrapper-adapter-tool proof did not prove "
                "wrapper-owned adapter-bin injection.\n"
                f"expected_adapter_bin={adapter_bin}\n"
                f"evidence={wrapper_evidence!r}"
            )
        if wrapper_evidence.get("adapterManifest") != str(adapter_manifest):
            raise SystemExit(
                "Live stock-codex-compat-wrapper-adapter-tool proof did not prove "
                "wrapper-owned adapter-manifest validation.\n"
                f"expected_adapter_manifest={adapter_manifest}\n"
                f"evidence={wrapper_evidence!r}"
            )
        expected_tool_names = [STOCK_CODEX_COMPAT_ADAPTER_COMMAND_NAME]
        if wrapper_evidence.get("adapterToolNames") != expected_tool_names:
            raise SystemExit(
                "Live stock-codex-compat-wrapper-adapter-tool proof did not record "
                "the expected adapter tool names.\n"
                f"expected_adapter_tool_names={expected_tool_names!r}\n"
                f"evidence={wrapper_evidence!r}"
            )
        if tuple(expected_tool_names) != adapter_package_result.tool_names:
            raise SystemExit(
                "Live stock-codex-compat-wrapper-adapter-tool proof did not use "
                "the production adapter package generator.\n"
                f"expected_adapter_tool_names={expected_tool_names!r}\n"
                f"package_tool_names={adapter_package_result.tool_names!r}"
            )
        return StockCodexCompatWrapperAdapterToolProof(
            stock_codex_path=stock_codex_path,
            stock_codex_version=stock_codex_version,
            source_bundle=source_bundle,
            wrapper_path=wrapper_path,
            codex_home=codex_home,
            auth_path=auth_path,
            bridge_dir=bridge_dir,
            workspace_root=workspace_root,
            adapter_bin=adapter_bin,
            adapter_manifest=adapter_manifest,
            adapter_tool_names=tuple(expected_tool_names),
            thread_id=thread_id,
            command=str(command_item["command"]),
            command_output=str(command_item["aggregated_output"]),
            first_agent_message=first_agent_message,
            first_agent_message_before_wrapper=str(
                wrapper_evidence["firstAgentMessageBefore"]
            ),
            route_injected=bool(wrapper_evidence["routeInjected"]),
            wrapper_evidence_path=wrapper_evidence_path,
            event_count=len(events),
            mcp_servers=mcp_servers,
            stderr_preview=stderr_preview,
        )


def run_stock_codex_compat_wrapper_adapter_arbitration_proof(
    source_bundle: Path,
    stock_codex_path: Path,
    *,
    timeout_seconds: float,
) -> StockCodexCompatWrapperAdapterArbitrationProof:
    """Prove a multi-tool adapter package can select one wrapper-owned adapter."""
    source_bundle = source_bundle.expanduser().resolve()
    stock_codex_path = stock_codex_path.expanduser().resolve()
    stock_codex_version = codex_version(stock_codex_path)
    auth_path, auth_source = _stock_replacement_auth_source()
    if not codex_native._codex_auth_json_has_available_credential(auth_path):
        raise SystemExit(
            "Current real Codex auth source is not available; cannot run live "
            "stock-codex-compat-wrapper-adapter-arbitration proof.\n"
            f"auth_path={auth_path}\n"
            f"auth_source={auth_source}"
        )

    selected_spec, rejected_spec = _stock_codex_compat_adapter_arbitration_tool_specs()
    tool_specs = (selected_spec, rejected_spec)

    with tempfile.TemporaryDirectory(
        prefix="omnigent-stock-codex-compat-wrapper-adapter-arbitration-proof-"
    ) as temp_root:
        root = Path(temp_root).resolve()
        codex_home = root / "codex-home"
        temp_home = root / "home"
        bridge_dir = root / "omnigent-bridge"
        marketplace_root = root / "local-apple-workflow-marketplace"
        wrapper_path = Path(stock_codex_compat_wrapper.__file__).resolve()
        wrapper_evidence_path = root / "wrapper-evidence.json"
        workspace_root = root / "workspace"
        adapter_package = root / "adapter-package"
        codex_home.mkdir(mode=0o700)
        temp_home.mkdir(mode=0o700)
        workspace_root.mkdir(mode=0o700)
        adapter_package_result = write_stock_codex_compat_adapter_package(
            adapter_package,
            tool_specs,
        )
        adapter_bin = adapter_package_result.adapter_bin
        adapter_manifest = adapter_package_result.manifest_path
        (codex_home / "auth.json").symlink_to(auth_path)

        _write_stock_codex_compat_marketplace(
            source_bundle=source_bundle,
            marketplace_root=marketplace_root,
        )
        env = _stock_codex_compat_env(home=temp_home, codex_home=codex_home)
        _run_stock_codex_json(
            stock_codex_path,
            ["plugin", "marketplace", "add", str(marketplace_root), "--json"],
            env=env,
        )
        _run_stock_codex_json(
            stock_codex_path,
            ["plugin", "add", STOCK_CODEX_COMPAT_PLUGIN_ID, "--json"],
            env=env,
        )
        plugin_list_output = _run_stock_codex_json(
            stock_codex_path,
            ["plugin", "list", "--json"],
            env=env,
        )
        _validate_stock_codex_compat_plugin_state(
            marketplace_list_output=_run_stock_codex_json(
                stock_codex_path,
                ["plugin", "marketplace", "list", "--json"],
                env=env,
            ),
            plugin_list_output=plugin_list_output,
            installed_plugin_path=(
                codex_home
                / "plugins"
                / "cache"
                / STOCK_CODEX_COMPAT_MARKETPLACE
                / PLUGIN_NAME
                / "0.1.1"
            ),
        )

        write_mcp_bridge_config(bridge_dir)
        write_policy_hook_config(
            bridge_dir,
            ap_server_url=STOCK_CODEX_COMPAT_AP_SERVER_URL,
            ap_auth_headers={},
        )
        _inject_mcp_server_config(codex_home, bridge_dir, sys.executable)
        _write_codex_policy_hooks_file(codex_home, bridge_dir, sys.executable)
        mcp_list_output = _run_stock_codex_json(
            stock_codex_path,
            ["mcp", "list", "--json"],
            env=env,
        )
        mcp_omnigent_output = _run_stock_codex_json(
            stock_codex_path,
            ["mcp", "get", "omnigent", "--json"],
            env=env,
        )
        _hook_events, mcp_servers, _mcp_command, _mcp_args = _validate_stock_codex_compat_bridge(
            codex_home=codex_home,
            bridge_dir=bridge_dir,
            mcp_list_output=mcp_list_output,
            mcp_omnigent_output=mcp_omnigent_output,
        )

        selected_command = f"{selected_spec.name} --message {selected_spec.argument}"
        rejected_command = f"{rejected_spec.name} --message {rejected_spec.argument}"
        manifest_preview = json.dumps(
            [
                {
                    "name": spec.name,
                    "capability": spec.capability,
                    "argumentObject": {"message": spec.argument},
                }
                for spec in tool_specs
            ],
            sort_keys=True,
        )
        prompt = (
            "Wrapped stock Codex multi-adapter arbitration proof. The adapter "
            f"manifest declares these tools: `{manifest_preview}`. The requested "
            f"capability is `{selected_spec.capability}`. Use the shell command "
            f"tool exactly once to run `{selected_command}`. Do not run "
            f"`{rejected_command}` and do not inspect files. Reply exactly "
            f"{STOCK_CODEX_COMPAT_WRAPPER_ADAPTER_ARBITRATION_SENTINEL} if stdout "
            f"contains {selected_spec.output_sentinel} and does not contain "
            f"{rejected_spec.output_sentinel}; otherwise reply ADAPTER_ARBITRATION_FAILED."
        )
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "omnigent.stock_codex_compat_wrapper",
                "--stock-codex-path",
                str(stock_codex_path),
                "--route-prefix",
                EXPECTED_ROUTE,
                "--evidence-path",
                str(wrapper_evidence_path),
                "--adapter-bin",
                str(adapter_bin),
                "--adapter-manifest",
                str(adapter_manifest),
                "--",
                "exec",
                "--json",
                "--dangerously-bypass-hook-trust",
                "--skip-git-repo-check",
                "--sandbox",
                "read-only",
                "-C",
                str(workspace_root),
                prompt,
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds if timeout_seconds > 0 else None,
            env=env,
            stdin=subprocess.DEVNULL,
        )
        stderr_preview = _preview_text(completed.stderr, limit=2000)
        if completed.returncode != 0:
            raise SystemExit(
                "Live stock-codex-compat-wrapper-adapter-arbitration command failed.\n"
                f"exit={completed.returncode}\n"
                f"stderr={stderr_preview}\n"
                f"stdout_preview={_preview_text(completed.stdout, limit=2000)}"
            )
        events = _parse_stock_codex_exec_jsonl(completed.stdout)
        thread_id, first_agent_message = _validate_stock_codex_agent_message(
            events,
            expected_sentinel=STOCK_CODEX_COMPAT_WRAPPER_ADAPTER_ARBITRATION_SENTINEL,
            proof_name="stock-codex-compat-wrapper-adapter-arbitration",
        )
        if not first_agent_message.startswith(EXPECTED_ROUTE):
            raise SystemExit(
                "Live stock-codex-compat-wrapper-adapter-arbitration proof did not "
                "emit deterministic route evidence before model output.\n"
                f"expected_prefix={EXPECTED_ROUTE!r}\n"
                f"first_agent_message={first_agent_message!r}"
            )
        command_item = _validate_stock_codex_adapter_command_execution_events(
            events,
            command_name=selected_spec.name,
            command_argument=selected_spec.argument,
            output_sentinel=selected_spec.output_sentinel,
            forbidden_command_names=(rejected_spec.name,),
            forbidden_output_sentinels=(rejected_spec.output_sentinel,),
        )
        wrapper_evidence = _read_stock_codex_compat_wrapper_evidence(wrapper_evidence_path)
        if wrapper_evidence["routeInjected"] is not True:
            raise SystemExit(
                "Live stock-codex-compat-wrapper-adapter-arbitration proof did not "
                "prove wrapper-owned route injection.\n"
                f"evidence={wrapper_evidence!r}"
            )
        if wrapper_evidence.get("adapterBin") != str(adapter_bin):
            raise SystemExit(
                "Live stock-codex-compat-wrapper-adapter-arbitration proof did not "
                "prove wrapper-owned adapter-bin injection.\n"
                f"expected_adapter_bin={adapter_bin}\n"
                f"evidence={wrapper_evidence!r}"
            )
        if wrapper_evidence.get("adapterManifest") != str(adapter_manifest):
            raise SystemExit(
                "Live stock-codex-compat-wrapper-adapter-arbitration proof did not "
                "prove wrapper-owned adapter-manifest validation.\n"
                f"expected_adapter_manifest={adapter_manifest}\n"
                f"evidence={wrapper_evidence!r}"
            )
        expected_tool_names = [spec.name for spec in tool_specs]
        if wrapper_evidence.get("adapterToolNames") != expected_tool_names:
            raise SystemExit(
                "Live stock-codex-compat-wrapper-adapter-arbitration proof did not "
                "record the expected adapter tool names.\n"
                f"expected_adapter_tool_names={expected_tool_names!r}\n"
                f"evidence={wrapper_evidence!r}"
            )
        if tuple(expected_tool_names) != adapter_package_result.tool_names:
            raise SystemExit(
                "Live stock-codex-compat-wrapper-adapter-arbitration proof did not "
                "use the production adapter package generator.\n"
                f"expected_adapter_tool_names={expected_tool_names!r}\n"
                f"package_tool_names={adapter_package_result.tool_names!r}"
            )
        return StockCodexCompatWrapperAdapterArbitrationProof(
            stock_codex_path=stock_codex_path,
            stock_codex_version=stock_codex_version,
            source_bundle=source_bundle,
            wrapper_path=wrapper_path,
            codex_home=codex_home,
            auth_path=auth_path,
            bridge_dir=bridge_dir,
            workspace_root=workspace_root,
            adapter_bin=adapter_bin,
            adapter_manifest=adapter_manifest,
            adapter_tool_names=tuple(expected_tool_names),
            selected_tool_name=selected_spec.name,
            rejected_tool_name=rejected_spec.name,
            thread_id=thread_id,
            command=str(command_item["command"]),
            command_output=str(command_item["aggregated_output"]),
            first_agent_message=first_agent_message,
            first_agent_message_before_wrapper=str(
                wrapper_evidence["firstAgentMessageBefore"]
            ),
            route_injected=bool(wrapper_evidence["routeInjected"]),
            wrapper_evidence_path=wrapper_evidence_path,
            event_count=len(events),
            mcp_servers=mcp_servers,
            stderr_preview=stderr_preview,
        )


def run_stock_codex_compat_wrapper_apple_docs_adapter_proof(
    source_bundle: Path,
    stock_codex_path: Path,
    *,
    timeout_seconds: float,
) -> StockCodexCompatWrapperAppleDocsAdapterProof:
    """Prove a real Apple docs adapter runs through the stock-Codex wrapper package."""
    source_bundle = source_bundle.expanduser().resolve()
    stock_codex_path = stock_codex_path.expanduser().resolve()
    stock_codex_version = codex_version(stock_codex_path)
    auth_path, auth_source = _stock_replacement_auth_source()
    if not codex_native._codex_auth_json_has_available_credential(auth_path):
        raise SystemExit(
            "Current real Codex auth source is not available; cannot run live "
            "stock-codex-compat-wrapper-apple-docs-adapter proof.\n"
            f"auth_path={auth_path}\n"
            f"auth_source={auth_source}"
        )

    sosumi_cli_path = shutil.which("sosumi")
    docs_command_prefix = (
        (sosumi_cli_path, "fetch")
        if sosumi_cli_path is not None
        else APPLE_DOCS_CLI_POLICY.command_prefix
    )
    docs_policy = replace(
        APPLE_DOCS_CLI_POLICY,
        command_prefix=docs_command_prefix,
        timeout_seconds=APPLE_DOCS_STOCK_COMPAT_TIMEOUT_SECONDS,
    )
    docs_spec = build_fetch_apple_docs_stock_codex_adapter_spec(docs_policy)

    with tempfile.TemporaryDirectory(
        prefix="omnigent-stock-codex-compat-wrapper-apple-docs-adapter-proof-"
    ) as temp_root:
        root = Path(temp_root).resolve()
        codex_home = root / "codex-home"
        temp_home = root / "home"
        bridge_dir = root / "omnigent-bridge"
        marketplace_root = root / "local-apple-workflow-marketplace"
        wrapper_path = Path(stock_codex_compat_wrapper.__file__).resolve()
        wrapper_evidence_path = root / "wrapper-evidence.json"
        workspace_root = root / "workspace"
        adapter_package = root / "adapter-package"
        codex_home.mkdir(mode=0o700)
        temp_home.mkdir(mode=0o700)
        workspace_root.mkdir(mode=0o700)
        adapter_package_result = write_stock_codex_compat_adapter_package(
            adapter_package,
            (docs_spec,),
        )
        adapter_bin = adapter_package_result.adapter_bin
        adapter_manifest = adapter_package_result.manifest_path
        (codex_home / "auth.json").symlink_to(auth_path)

        _write_stock_codex_compat_marketplace(
            source_bundle=source_bundle,
            marketplace_root=marketplace_root,
        )
        env = _stock_codex_compat_env(home=temp_home, codex_home=codex_home)
        _run_stock_codex_json(
            stock_codex_path,
            ["plugin", "marketplace", "add", str(marketplace_root), "--json"],
            env=env,
        )
        _run_stock_codex_json(
            stock_codex_path,
            ["plugin", "add", STOCK_CODEX_COMPAT_PLUGIN_ID, "--json"],
            env=env,
        )
        plugin_list_output = _run_stock_codex_json(
            stock_codex_path,
            ["plugin", "list", "--json"],
            env=env,
        )
        _validate_stock_codex_compat_plugin_state(
            marketplace_list_output=_run_stock_codex_json(
                stock_codex_path,
                ["plugin", "marketplace", "list", "--json"],
                env=env,
            ),
            plugin_list_output=plugin_list_output,
            installed_plugin_path=(
                codex_home
                / "plugins"
                / "cache"
                / STOCK_CODEX_COMPAT_MARKETPLACE
                / PLUGIN_NAME
                / "0.1.1"
            ),
        )

        write_mcp_bridge_config(bridge_dir)
        write_policy_hook_config(
            bridge_dir,
            ap_server_url=STOCK_CODEX_COMPAT_AP_SERVER_URL,
            ap_auth_headers={},
        )
        _inject_mcp_server_config(codex_home, bridge_dir, sys.executable)
        _write_codex_policy_hooks_file(codex_home, bridge_dir, sys.executable)
        mcp_list_output = _run_stock_codex_json(
            stock_codex_path,
            ["mcp", "list", "--json"],
            env=env,
        )
        mcp_omnigent_output = _run_stock_codex_json(
            stock_codex_path,
            ["mcp", "get", "omnigent", "--json"],
            env=env,
        )
        _hook_events, mcp_servers, _mcp_command, _mcp_args = _validate_stock_codex_compat_bridge(
            codex_home=codex_home,
            bridge_dir=bridge_dir,
            mcp_list_output=mcp_list_output,
            mcp_omnigent_output=mcp_omnigent_output,
        )

        adapter_command = f"{APPLE_DOCS_CLI_TOOL} --url {shlex.quote(APPLE_DOCS_CLI_URL)}"
        adapter_arguments = json.dumps({"url": APPLE_DOCS_CLI_URL}, sort_keys=True)
        expected_output = ", ".join(APPLE_MCP_SOSUMI_SENTINELS)
        prompt = (
            "Wrapped stock Codex real Apple docs adapter proof. The adapter "
            f"manifest declares `{APPLE_DOCS_CLI_TOOL}` for capability "
            f"`{docs_spec.capability}` with argument object `{adapter_arguments}`. "
            "Use the shell command tool exactly once to run "
            f"`{adapter_command}`. Do not use dynamicTools, MCP tools, or any "
            "other command. Reply exactly "
            f"{STOCK_CODEX_COMPAT_WRAPPER_APPLE_DOCS_ADAPTER_SENTINEL} if stdout "
            f"contains {expected_output}; otherwise reply APPLE_DOCS_ADAPTER_FAILED."
        )
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "omnigent.stock_codex_compat_wrapper",
                "--stock-codex-path",
                str(stock_codex_path),
                "--route-prefix",
                EXPECTED_ROUTE,
                "--evidence-path",
                str(wrapper_evidence_path),
                "--adapter-bin",
                str(adapter_bin),
                "--adapter-manifest",
                str(adapter_manifest),
                "--",
                "exec",
                "--json",
                "--dangerously-bypass-hook-trust",
                "--skip-git-repo-check",
                "--sandbox",
                "danger-full-access",
                "-C",
                str(workspace_root),
                prompt,
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds if timeout_seconds > 0 else None,
            env=env,
            stdin=subprocess.DEVNULL,
        )
        stderr_preview = _preview_text(completed.stderr, limit=2000)
        if completed.returncode != 0:
            raise SystemExit(
                "Live stock-codex-compat-wrapper-apple-docs-adapter command failed.\n"
                f"exit={completed.returncode}\n"
                f"stderr={stderr_preview}\n"
                f"stdout_preview={_preview_text(completed.stdout, limit=2000)}"
            )
        events = _parse_stock_codex_exec_jsonl(completed.stdout)
        thread_id, first_agent_message = _extract_stock_codex_thread_and_agent_message(
            events,
            proof_name="stock-codex-compat-wrapper-apple-docs-adapter",
        )
        if not first_agent_message.startswith(EXPECTED_ROUTE):
            raise SystemExit(
                "Live stock-codex-compat-wrapper-apple-docs-adapter proof did not "
                "emit deterministic route evidence before model output.\n"
                f"expected_prefix={EXPECTED_ROUTE!r}\n"
                f"first_agent_message={first_agent_message!r}"
            )
        command_item = _validate_stock_codex_adapter_command_execution_events(
            events,
            command_name=APPLE_DOCS_CLI_TOOL,
            command_argument=APPLE_DOCS_CLI_URL,
            output_sentinel=APPLE_MCP_SOSUMI_SENTINELS[0],
        )
        command_output = str(command_item["aggregated_output"])
        for output_sentinel in APPLE_MCP_SOSUMI_SENTINELS:
            if output_sentinel not in command_output:
                raise SystemExit(
                    "Wrapped stock Codex Apple docs adapter output missed expected "
                    f"sentinel {output_sentinel!r}: {command_item!r}"
                )
        if (
            STOCK_CODEX_COMPAT_WRAPPER_APPLE_DOCS_ADAPTER_SENTINEL
            not in first_agent_message
        ):
            raise SystemExit(
                "Live stock-codex-compat-wrapper-apple-docs-adapter proof did not "
                "return the expected sentinel after the adapter command.\n"
                f"sentinel={STOCK_CODEX_COMPAT_WRAPPER_APPLE_DOCS_ADAPTER_SENTINEL!r}\n"
                f"first_agent_message={first_agent_message!r}\n"
                f"command={command_item.get('command')!r}\n"
                f"command_output_preview={_preview_text(command_output, limit=1000)!r}"
            )
        wrapper_evidence = _read_stock_codex_compat_wrapper_evidence(wrapper_evidence_path)
        if wrapper_evidence["routeInjected"] is not True:
            raise SystemExit(
                "Live stock-codex-compat-wrapper-apple-docs-adapter proof did not "
                "prove wrapper-owned route injection.\n"
                f"evidence={wrapper_evidence!r}"
            )
        if wrapper_evidence.get("adapterBin") != str(adapter_bin):
            raise SystemExit(
                "Live stock-codex-compat-wrapper-apple-docs-adapter proof did not "
                "prove wrapper-owned adapter-bin injection.\n"
                f"expected_adapter_bin={adapter_bin}\n"
                f"evidence={wrapper_evidence!r}"
            )
        if wrapper_evidence.get("adapterManifest") != str(adapter_manifest):
            raise SystemExit(
                "Live stock-codex-compat-wrapper-apple-docs-adapter proof did not "
                "prove wrapper-owned adapter-manifest validation.\n"
                f"expected_adapter_manifest={adapter_manifest}\n"
                f"evidence={wrapper_evidence!r}"
            )
        expected_tool_names = [APPLE_DOCS_CLI_TOOL]
        if wrapper_evidence.get("adapterToolNames") != expected_tool_names:
            raise SystemExit(
                "Live stock-codex-compat-wrapper-apple-docs-adapter proof did not "
                "record the expected adapter tool names.\n"
                f"expected_adapter_tool_names={expected_tool_names!r}\n"
                f"evidence={wrapper_evidence!r}"
            )
        if tuple(expected_tool_names) != adapter_package_result.tool_names:
            raise SystemExit(
                "Live stock-codex-compat-wrapper-apple-docs-adapter proof did not "
                "use the production adapter package generator.\n"
                f"expected_adapter_tool_names={expected_tool_names!r}\n"
                f"package_tool_names={adapter_package_result.tool_names!r}"
            )
        return StockCodexCompatWrapperAppleDocsAdapterProof(
            stock_codex_path=stock_codex_path,
            stock_codex_version=stock_codex_version,
            source_bundle=source_bundle,
            wrapper_path=wrapper_path,
            codex_home=codex_home,
            auth_path=auth_path,
            bridge_dir=bridge_dir,
            workspace_root=workspace_root,
            adapter_bin=adapter_bin,
            adapter_manifest=adapter_manifest,
            adapter_tool_names=tuple(expected_tool_names),
            docs_url=APPLE_DOCS_CLI_URL,
            thread_id=thread_id,
            command=str(command_item["command"]),
            command_output=command_output,
            first_agent_message=first_agent_message,
            first_agent_message_before_wrapper=str(
                wrapper_evidence["firstAgentMessageBefore"]
            ),
            route_injected=bool(wrapper_evidence["routeInjected"]),
            wrapper_evidence_path=wrapper_evidence_path,
            event_count=len(events),
            mcp_servers=mcp_servers,
            stderr_preview=stderr_preview,
        )


def run_stock_codex_compat_wrapper_apple_docs_bridge_adapter_proof(
    source_bundle: Path,
    stock_codex_path: Path,
    *,
    timeout_seconds: float,
) -> StockCodexCompatWrapperAppleDocsBridgeAdapterProof:
    """Prove the Apple docs adapter can run through a wrapper-owned file bridge."""
    source_bundle = source_bundle.expanduser().resolve()
    stock_codex_path = stock_codex_path.expanduser().resolve()
    stock_codex_version = codex_version(stock_codex_path)
    auth_path, auth_source = _stock_replacement_auth_source()
    if not codex_native._codex_auth_json_has_available_credential(auth_path):
        raise SystemExit(
            "Current real Codex auth source is not available; cannot run live "
            "stock-codex-compat-wrapper-apple-docs-bridge-adapter proof.\n"
            f"auth_path={auth_path}\n"
            f"auth_source={auth_source}"
        )

    sosumi_cli_path = shutil.which("sosumi")
    docs_command_prefix = (
        (sosumi_cli_path, "fetch")
        if sosumi_cli_path is not None
        else APPLE_DOCS_CLI_POLICY.command_prefix
    )
    docs_policy = replace(
        APPLE_DOCS_CLI_POLICY,
        command_prefix=docs_command_prefix,
        timeout_seconds=APPLE_DOCS_STOCK_COMPAT_TIMEOUT_SECONDS,
    )
    docs_spec = build_fetch_apple_docs_stock_codex_bridge_adapter_spec(
        docs_policy,
        bridge_timeout_seconds=APPLE_DOCS_STOCK_COMPAT_BRIDGE_TIMEOUT_SECONDS,
    )

    with tempfile.TemporaryDirectory(
        prefix="omnigent-stock-codex-compat-wrapper-apple-docs-bridge-adapter-proof-"
    ) as temp_root:
        root = Path(temp_root).resolve()
        codex_home = root / "codex-home"
        temp_home = root / "home"
        bridge_dir = root / "omnigent-bridge"
        marketplace_root = root / "local-apple-workflow-marketplace"
        wrapper_path = Path(stock_codex_compat_wrapper.__file__).resolve()
        wrapper_evidence_path = root / "wrapper-evidence.json"
        workspace_root = root / "workspace"
        adapter_package = workspace_root / ".omnigent-adapter-package"
        adapter_bridge_dir = workspace_root / ".omnigent-adapter-bridge"
        codex_home.mkdir(mode=0o700)
        temp_home.mkdir(mode=0o700)
        workspace_root.mkdir(mode=0o700)
        adapter_package_result = write_stock_codex_compat_adapter_package(
            adapter_package,
            (docs_spec,),
        )
        adapter_bin = adapter_package_result.adapter_bin
        adapter_manifest = adapter_package_result.manifest_path
        (codex_home / "auth.json").symlink_to(auth_path)

        _write_stock_codex_compat_marketplace(
            source_bundle=source_bundle,
            marketplace_root=marketplace_root,
        )
        env = _stock_codex_compat_env(home=temp_home, codex_home=codex_home)
        _run_stock_codex_json(
            stock_codex_path,
            ["plugin", "marketplace", "add", str(marketplace_root), "--json"],
            env=env,
        )
        _run_stock_codex_json(
            stock_codex_path,
            ["plugin", "add", STOCK_CODEX_COMPAT_PLUGIN_ID, "--json"],
            env=env,
        )
        plugin_list_output = _run_stock_codex_json(
            stock_codex_path,
            ["plugin", "list", "--json"],
            env=env,
        )
        _validate_stock_codex_compat_plugin_state(
            marketplace_list_output=_run_stock_codex_json(
                stock_codex_path,
                ["plugin", "marketplace", "list", "--json"],
                env=env,
            ),
            plugin_list_output=plugin_list_output,
            installed_plugin_path=(
                codex_home
                / "plugins"
                / "cache"
                / STOCK_CODEX_COMPAT_MARKETPLACE
                / PLUGIN_NAME
                / "0.1.1"
            ),
        )

        write_mcp_bridge_config(bridge_dir)
        write_policy_hook_config(
            bridge_dir,
            ap_server_url=STOCK_CODEX_COMPAT_AP_SERVER_URL,
            ap_auth_headers={},
        )
        _inject_mcp_server_config(codex_home, bridge_dir, sys.executable)
        _write_codex_policy_hooks_file(codex_home, bridge_dir, sys.executable)
        mcp_list_output = _run_stock_codex_json(
            stock_codex_path,
            ["mcp", "list", "--json"],
            env=env,
        )
        mcp_omnigent_output = _run_stock_codex_json(
            stock_codex_path,
            ["mcp", "get", "omnigent", "--json"],
            env=env,
        )
        _hook_events, mcp_servers, _mcp_command, _mcp_args = _validate_stock_codex_compat_bridge(
            codex_home=codex_home,
            bridge_dir=bridge_dir,
            mcp_list_output=mcp_list_output,
            mcp_omnigent_output=mcp_omnigent_output,
        )

        adapter_command = f"{APPLE_DOCS_CLI_TOOL} --url {shlex.quote(APPLE_DOCS_CLI_URL)}"
        adapter_arguments = json.dumps({"url": APPLE_DOCS_CLI_URL}, sort_keys=True)
        expected_output = ", ".join(APPLE_MCP_SOSUMI_SENTINELS)
        prompt = (
            "Wrapped stock Codex real Apple docs bridge-adapter proof. The "
            f"adapter manifest declares `{APPLE_DOCS_CLI_TOOL}` for capability "
            f"`{docs_spec.capability}` with argument object `{adapter_arguments}`. "
            "Use the shell command tool exactly once to run "
            f"`{adapter_command}`. Do not use dynamicTools, MCP tools, or any "
            "other command. Reply exactly "
            f"{STOCK_CODEX_COMPAT_WRAPPER_APPLE_DOCS_BRIDGE_ADAPTER_SENTINEL} "
            f"if stdout contains {expected_output}; otherwise reply "
            "APPLE_DOCS_BRIDGE_ADAPTER_FAILED."
        )
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "omnigent.stock_codex_compat_wrapper",
                "--stock-codex-path",
                str(stock_codex_path),
                "--route-prefix",
                EXPECTED_ROUTE,
                "--evidence-path",
                str(wrapper_evidence_path),
                "--adapter-bin",
                str(adapter_bin),
                "--adapter-manifest",
                str(adapter_manifest),
                "--adapter-bridge-dir",
                str(adapter_bridge_dir),
                "--",
                "exec",
                "--json",
                "--dangerously-bypass-hook-trust",
                "--skip-git-repo-check",
                "--sandbox",
                "workspace-write",
                "-C",
                str(workspace_root),
                prompt,
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds if timeout_seconds > 0 else None,
            env=env,
            stdin=subprocess.DEVNULL,
        )
        stderr_preview = _preview_text(completed.stderr, limit=2000)
        if completed.returncode != 0:
            raise SystemExit(
                "Live stock-codex-compat-wrapper-apple-docs-bridge-adapter "
                "command failed.\n"
                f"exit={completed.returncode}\n"
                f"stderr={stderr_preview}\n"
                f"stdout_preview={_preview_text(completed.stdout, limit=2000)}"
            )
        events = _parse_stock_codex_exec_jsonl(completed.stdout)
        thread_id, first_agent_message = _extract_stock_codex_thread_and_agent_message(
            events,
            proof_name="stock-codex-compat-wrapper-apple-docs-bridge-adapter",
        )
        if not first_agent_message.startswith(EXPECTED_ROUTE):
            raise SystemExit(
                "Live stock-codex-compat-wrapper-apple-docs-bridge-adapter proof "
                "did not emit deterministic route evidence before model output.\n"
                f"expected_prefix={EXPECTED_ROUTE!r}\n"
                f"first_agent_message={first_agent_message!r}"
            )
        command_item = _validate_stock_codex_adapter_command_execution_events(
            events,
            command_name=APPLE_DOCS_CLI_TOOL,
            command_argument=APPLE_DOCS_CLI_URL,
            output_sentinel=APPLE_MCP_SOSUMI_SENTINELS[0],
        )
        command_output = str(command_item["aggregated_output"])
        for output_sentinel in APPLE_MCP_SOSUMI_SENTINELS:
            if output_sentinel not in command_output:
                raise SystemExit(
                    "Wrapped stock Codex Apple docs bridge adapter output missed "
                    f"expected sentinel {output_sentinel!r}: {command_item!r}"
                )
        if (
            STOCK_CODEX_COMPAT_WRAPPER_APPLE_DOCS_BRIDGE_ADAPTER_SENTINEL
            not in first_agent_message
        ):
            raise SystemExit(
                "Live stock-codex-compat-wrapper-apple-docs-bridge-adapter proof "
                "did not return the expected sentinel after the adapter command.\n"
                f"sentinel="
                f"{STOCK_CODEX_COMPAT_WRAPPER_APPLE_DOCS_BRIDGE_ADAPTER_SENTINEL!r}\n"
                f"first_agent_message={first_agent_message!r}\n"
                f"command={command_item.get('command')!r}\n"
                f"command_output_preview={_preview_text(command_output, limit=1000)!r}"
            )
        wrapper_evidence = _read_stock_codex_compat_wrapper_evidence(wrapper_evidence_path)
        if wrapper_evidence["routeInjected"] is not True:
            raise SystemExit(
                "Live stock-codex-compat-wrapper-apple-docs-bridge-adapter proof "
                "did not prove wrapper-owned route injection.\n"
                f"evidence={wrapper_evidence!r}"
            )
        if wrapper_evidence.get("adapterBin") != str(adapter_bin):
            raise SystemExit(
                "Live stock-codex-compat-wrapper-apple-docs-bridge-adapter proof "
                "did not prove wrapper-owned adapter-bin injection.\n"
                f"expected_adapter_bin={adapter_bin}\n"
                f"evidence={wrapper_evidence!r}"
            )
        if wrapper_evidence.get("adapterManifest") != str(adapter_manifest):
            raise SystemExit(
                "Live stock-codex-compat-wrapper-apple-docs-bridge-adapter proof "
                "did not prove wrapper-owned adapter-manifest validation.\n"
                f"expected_adapter_manifest={adapter_manifest}\n"
                f"evidence={wrapper_evidence!r}"
            )
        if wrapper_evidence.get("adapterBridgeDir") != str(adapter_bridge_dir):
            raise SystemExit(
                "Live stock-codex-compat-wrapper-apple-docs-bridge-adapter proof "
                "did not prove wrapper-owned adapter bridge injection.\n"
                f"expected_adapter_bridge_dir={adapter_bridge_dir}\n"
                f"evidence={wrapper_evidence!r}"
            )
        expected_tool_names = [APPLE_DOCS_CLI_TOOL]
        if wrapper_evidence.get("adapterToolNames") != expected_tool_names:
            raise SystemExit(
                "Live stock-codex-compat-wrapper-apple-docs-bridge-adapter proof "
                "did not record the expected adapter tool names.\n"
                f"expected_adapter_tool_names={expected_tool_names!r}\n"
                f"evidence={wrapper_evidence!r}"
            )
        if tuple(expected_tool_names) != adapter_package_result.tool_names:
            raise SystemExit(
                "Live stock-codex-compat-wrapper-apple-docs-bridge-adapter proof "
                "did not use the production adapter package generator.\n"
                f"expected_adapter_tool_names={expected_tool_names!r}\n"
                f"package_tool_names={adapter_package_result.tool_names!r}"
            )
        return StockCodexCompatWrapperAppleDocsBridgeAdapterProof(
            stock_codex_path=stock_codex_path,
            stock_codex_version=stock_codex_version,
            source_bundle=source_bundle,
            wrapper_path=wrapper_path,
            codex_home=codex_home,
            auth_path=auth_path,
            bridge_dir=bridge_dir,
            workspace_root=workspace_root,
            adapter_bin=adapter_bin,
            adapter_manifest=adapter_manifest,
            adapter_bridge_dir=adapter_bridge_dir,
            adapter_tool_names=tuple(expected_tool_names),
            docs_url=APPLE_DOCS_CLI_URL,
            sandbox="workspace-write",
            thread_id=thread_id,
            command=str(command_item["command"]),
            command_output=command_output,
            first_agent_message=first_agent_message,
            first_agent_message_before_wrapper=str(
                wrapper_evidence["firstAgentMessageBefore"]
            ),
            route_injected=bool(wrapper_evidence["routeInjected"]),
            wrapper_evidence_path=wrapper_evidence_path,
            event_count=len(events),
            mcp_servers=mcp_servers,
            stderr_preview=stderr_preview,
        )


def run_stock_codex_compat_wrapper_xcodebuild_bridge_adapter_proof(
    source_bundle: Path,
    stock_codex_path: Path,
    *,
    timeout_seconds: float,
) -> StockCodexCompatWrapperXcodebuildBridgeAdapterProof:
    """Prove XcodeBuildMCP build/run can execute through a wrapper-owned file bridge."""
    source_bundle = source_bundle.expanduser().resolve()
    stock_codex_path = stock_codex_path.expanduser().resolve()
    stock_codex_version = codex_version(stock_codex_path)
    auth_path, auth_source = _stock_replacement_auth_source()
    if not codex_native._codex_auth_json_has_available_credential(auth_path):
        raise SystemExit(
            "Current real Codex auth source is not available; cannot run live "
            "stock-codex-compat-wrapper-xcodebuild-bridge-adapter proof.\n"
            f"auth_path={auth_path}\n"
            f"auth_source={auth_source}"
        )

    xcodebuild_policy = XCODEBUILD_CLI_POLICY
    xcodebuild_spec = (
        build_xcodebuildmcp_simulator_build_run_stock_codex_bridge_adapter_spec(
            xcodebuild_policy,
            bridge_timeout_seconds=XCODEBUILD_CLI_STOCK_COMPAT_BRIDGE_TIMEOUT_SECONDS,
        )
    )
    xcodebuild_workspace_root = resolve_xcodebuild_mcp_workspace_root()
    project_path = (
        xcodebuild_workspace_root / APPLE_MCP_XCODEBUILD_PROJECT_RELATIVE_PATH
    )
    simulator_name = resolve_xcodebuild_mcp_simulator_name()

    with tempfile.TemporaryDirectory(
        prefix="omnigent-stock-codex-compat-wrapper-xcodebuild-bridge-adapter-proof-"
    ) as temp_root:
        unresolved_root = Path(temp_root)
        root = Path(temp_root).resolve()
        codex_home = root / "codex-home"
        temp_home = root / "home"
        bridge_dir = root / "omnigent-bridge"
        marketplace_root = root / "local-apple-workflow-marketplace"
        wrapper_path = Path(stock_codex_compat_wrapper.__file__).resolve()
        wrapper_evidence_path = root / "wrapper-evidence.json"
        workspace_root = root / "workspace"
        adapter_package = workspace_root / ".omnigent-adapter-package"
        adapter_bridge_dir = workspace_root / ".omnigent-adapter-bridge"
        derived_data_path = unresolved_root / "xcodebuild-bridge-deriveddata"
        codex_home.mkdir(mode=0o700)
        temp_home.mkdir(mode=0o700)
        workspace_root.mkdir(mode=0o700)
        adapter_package_result = write_stock_codex_compat_adapter_package(
            adapter_package,
            (xcodebuild_spec,),
        )
        adapter_bin = adapter_package_result.adapter_bin
        adapter_manifest = adapter_package_result.manifest_path
        (codex_home / "auth.json").symlink_to(auth_path)

        _write_stock_codex_compat_marketplace(
            source_bundle=source_bundle,
            marketplace_root=marketplace_root,
        )
        env = _stock_codex_compat_env(home=temp_home, codex_home=codex_home)
        _run_stock_codex_json(
            stock_codex_path,
            ["plugin", "marketplace", "add", str(marketplace_root), "--json"],
            env=env,
        )
        _run_stock_codex_json(
            stock_codex_path,
            ["plugin", "add", STOCK_CODEX_COMPAT_PLUGIN_ID, "--json"],
            env=env,
        )
        plugin_list_output = _run_stock_codex_json(
            stock_codex_path,
            ["plugin", "list", "--json"],
            env=env,
        )
        _validate_stock_codex_compat_plugin_state(
            marketplace_list_output=_run_stock_codex_json(
                stock_codex_path,
                ["plugin", "marketplace", "list", "--json"],
                env=env,
            ),
            plugin_list_output=plugin_list_output,
            installed_plugin_path=(
                codex_home
                / "plugins"
                / "cache"
                / STOCK_CODEX_COMPAT_MARKETPLACE
                / PLUGIN_NAME
                / "0.1.1"
            ),
        )

        write_mcp_bridge_config(bridge_dir)
        write_policy_hook_config(
            bridge_dir,
            ap_server_url=STOCK_CODEX_COMPAT_AP_SERVER_URL,
            ap_auth_headers={},
        )
        _inject_mcp_server_config(codex_home, bridge_dir, sys.executable)
        _write_codex_policy_hooks_file(codex_home, bridge_dir, sys.executable)
        mcp_list_output = _run_stock_codex_json(
            stock_codex_path,
            ["mcp", "list", "--json"],
            env=env,
        )
        mcp_omnigent_output = _run_stock_codex_json(
            stock_codex_path,
            ["mcp", "get", "omnigent", "--json"],
            env=env,
        )
        _hook_events, mcp_servers, _mcp_command, _mcp_args = _validate_stock_codex_compat_bridge(
            codex_home=codex_home,
            bridge_dir=bridge_dir,
            mcp_list_output=mcp_list_output,
            mcp_omnigent_output=mcp_omnigent_output,
        )

        tool_args = {
            "project_path": str(project_path),
            "scheme": APPLE_MCP_XCODEBUILD_SCHEME,
            "configuration": APPLE_MCP_XCODEBUILD_CONFIGURATION,
            "simulator_name": simulator_name,
            "derived_data_path": str(derived_data_path),
        }
        adapter_command = " ".join(
            [
                XCODEBUILD_CLI_TOOL,
                "--project_path",
                shlex.quote(tool_args["project_path"]),
                "--scheme",
                shlex.quote(tool_args["scheme"]),
                "--configuration",
                shlex.quote(tool_args["configuration"]),
                "--simulator_name",
                shlex.quote(tool_args["simulator_name"]),
                "--derived_data_path",
                shlex.quote(tool_args["derived_data_path"]),
            ]
        )
        expected_output = ", ".join(XCODEBUILD_CLI_RUN_SENTINELS)
        prompt = (
            "Wrapped stock Codex XcodeBuildMCP bridge-adapter proof. The "
            f"adapter manifest declares `{XCODEBUILD_CLI_TOOL}` for capability "
            f"`{xcodebuild_spec.capability}` with argument object "
            f"`{json.dumps(tool_args, sort_keys=True)}`. Use the shell command "
            f"tool exactly once to run `{adapter_command}`. Do not use "
            "dynamicTools, MCP tools, or any other command. Reply exactly "
            f"{STOCK_CODEX_COMPAT_WRAPPER_XCODEBUILD_BRIDGE_ADAPTER_SENTINEL} "
            f"if stdout contains {expected_output}; otherwise reply "
            "XCODEBUILD_BRIDGE_ADAPTER_FAILED."
        )
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "omnigent.stock_codex_compat_wrapper",
                "--stock-codex-path",
                str(stock_codex_path),
                "--route-prefix",
                EXPECTED_ROUTE,
                "--evidence-path",
                str(wrapper_evidence_path),
                "--adapter-bin",
                str(adapter_bin),
                "--adapter-manifest",
                str(adapter_manifest),
                "--adapter-bridge-dir",
                str(adapter_bridge_dir),
                "--",
                "exec",
                "--json",
                "--dangerously-bypass-hook-trust",
                "--skip-git-repo-check",
                "--sandbox",
                "workspace-write",
                "-C",
                str(workspace_root),
                prompt,
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds if timeout_seconds > 0 else None,
            env=env,
            stdin=subprocess.DEVNULL,
        )
        stderr_preview = _preview_text(completed.stderr, limit=2000)
        if completed.returncode != 0:
            raise SystemExit(
                "Live stock-codex-compat-wrapper-xcodebuild-bridge-adapter "
                "command failed.\n"
                f"exit={completed.returncode}\n"
                f"stderr={stderr_preview}\n"
                f"stdout_preview={_preview_text(completed.stdout, limit=2000)}"
            )
        events = _parse_stock_codex_exec_jsonl(completed.stdout)
        thread_id, first_agent_message = _extract_stock_codex_thread_and_agent_message(
            events,
            proof_name="stock-codex-compat-wrapper-xcodebuild-bridge-adapter",
        )
        if not first_agent_message.startswith(EXPECTED_ROUTE):
            raise SystemExit(
                "Live stock-codex-compat-wrapper-xcodebuild-bridge-adapter proof "
                "did not emit deterministic route evidence before model output.\n"
                f"expected_prefix={EXPECTED_ROUTE!r}\n"
                f"first_agent_message={first_agent_message!r}"
            )
        command_item = _validate_stock_codex_adapter_command_execution_events(
            events,
            command_name=XCODEBUILD_CLI_TOOL,
            command_argument=str(project_path),
            output_sentinel=XCODEBUILD_CLI_RUN_SENTINELS[0],
        )
        command_output = str(command_item["aggregated_output"])
        for output_sentinel in XCODEBUILD_CLI_RUN_SENTINELS:
            if output_sentinel not in command_output:
                raise SystemExit(
                    "Wrapped stock Codex XcodeBuildMCP bridge adapter output "
                    f"missed expected sentinel {output_sentinel!r}: {command_item!r}"
                )
        if (
            STOCK_CODEX_COMPAT_WRAPPER_XCODEBUILD_BRIDGE_ADAPTER_SENTINEL
            not in first_agent_message
        ):
            raise SystemExit(
                "Live stock-codex-compat-wrapper-xcodebuild-bridge-adapter proof "
                "did not return the expected sentinel after the adapter command.\n"
                f"sentinel="
                f"{STOCK_CODEX_COMPAT_WRAPPER_XCODEBUILD_BRIDGE_ADAPTER_SENTINEL!r}\n"
                f"first_agent_message={first_agent_message!r}\n"
                f"command={command_item.get('command')!r}\n"
                f"command_output_preview={_preview_text(command_output, limit=1000)!r}"
            )
        wrapper_evidence = _read_stock_codex_compat_wrapper_evidence(wrapper_evidence_path)
        if wrapper_evidence["routeInjected"] is not True:
            raise SystemExit(
                "Live stock-codex-compat-wrapper-xcodebuild-bridge-adapter proof "
                "did not prove wrapper-owned route injection.\n"
                f"evidence={wrapper_evidence!r}"
            )
        if wrapper_evidence.get("adapterBin") != str(adapter_bin):
            raise SystemExit(
                "Live stock-codex-compat-wrapper-xcodebuild-bridge-adapter proof "
                "did not prove wrapper-owned adapter-bin injection.\n"
                f"expected_adapter_bin={adapter_bin}\n"
                f"evidence={wrapper_evidence!r}"
            )
        if wrapper_evidence.get("adapterManifest") != str(adapter_manifest):
            raise SystemExit(
                "Live stock-codex-compat-wrapper-xcodebuild-bridge-adapter proof "
                "did not prove wrapper-owned adapter-manifest validation.\n"
                f"expected_adapter_manifest={adapter_manifest}\n"
                f"evidence={wrapper_evidence!r}"
            )
        if wrapper_evidence.get("adapterBridgeDir") != str(adapter_bridge_dir):
            raise SystemExit(
                "Live stock-codex-compat-wrapper-xcodebuild-bridge-adapter proof "
                "did not prove wrapper-owned adapter bridge injection.\n"
                f"expected_adapter_bridge_dir={adapter_bridge_dir}\n"
                f"evidence={wrapper_evidence!r}"
            )
        expected_tool_names = [XCODEBUILD_CLI_TOOL]
        if wrapper_evidence.get("adapterToolNames") != expected_tool_names:
            raise SystemExit(
                "Live stock-codex-compat-wrapper-xcodebuild-bridge-adapter proof "
                "did not record the expected adapter tool names.\n"
                f"expected_adapter_tool_names={expected_tool_names!r}\n"
                f"evidence={wrapper_evidence!r}"
            )
        if tuple(expected_tool_names) != adapter_package_result.tool_names:
            raise SystemExit(
                "Live stock-codex-compat-wrapper-xcodebuild-bridge-adapter proof "
                "did not use the production adapter package generator.\n"
                f"expected_adapter_tool_names={expected_tool_names!r}\n"
                f"package_tool_names={adapter_package_result.tool_names!r}"
            )
        return StockCodexCompatWrapperXcodebuildBridgeAdapterProof(
            stock_codex_path=stock_codex_path,
            stock_codex_version=stock_codex_version,
            source_bundle=source_bundle,
            wrapper_path=wrapper_path,
            codex_home=codex_home,
            auth_path=auth_path,
            bridge_dir=bridge_dir,
            workspace_root=workspace_root,
            adapter_bin=adapter_bin,
            adapter_manifest=adapter_manifest,
            adapter_bridge_dir=adapter_bridge_dir,
            adapter_tool_names=tuple(expected_tool_names),
            project_path=project_path,
            scheme=APPLE_MCP_XCODEBUILD_SCHEME,
            configuration=APPLE_MCP_XCODEBUILD_CONFIGURATION,
            simulator_name=simulator_name,
            derived_data_path=derived_data_path,
            sandbox="workspace-write",
            thread_id=thread_id,
            command=str(command_item["command"]),
            command_output=command_output,
            first_agent_message=first_agent_message,
            first_agent_message_before_wrapper=str(
                wrapper_evidence["firstAgentMessageBefore"]
            ),
            route_injected=bool(wrapper_evidence["routeInjected"]),
            wrapper_evidence_path=wrapper_evidence_path,
            event_count=len(events),
            mcp_servers=mcp_servers,
            stderr_preview=stderr_preview,
        )


def run_stock_codex_compat_wrapper_relay_tool_proof(
    source_bundle: Path,
    stock_codex_path: Path,
    *,
    timeout_seconds: float,
) -> StockCodexCompatWrapperRelayToolProof:
    """Prove the wrapper preserves an Omnigent relay MCP tool call."""
    source_bundle = source_bundle.expanduser().resolve()
    stock_codex_path = stock_codex_path.expanduser().resolve()
    stock_codex_version = codex_version(stock_codex_path)
    auth_path, auth_source = _stock_replacement_auth_source()
    if not codex_native._codex_auth_json_has_available_credential(auth_path):
        raise SystemExit(
            "Current real Codex auth source is not available; cannot run live "
            "stock-codex-compat-wrapper-relay-tool proof.\n"
            f"auth_path={auth_path}\n"
            f"auth_source={auth_source}"
        )

    with tempfile.TemporaryDirectory(
        prefix="omnigent-stock-codex-compat-wrapper-relay-tool-proof-"
    ) as temp_root:
        root = Path(temp_root).resolve()
        previous_bridge_root = codex_native_bridge._BRIDGE_ROOT
        codex_native_bridge._BRIDGE_ROOT = root / ".omnigent" / "codex-native"
        codex_home = root / "codex-home"
        temp_home = root / "home"
        bridge_dir = codex_native_bridge.bridge_dir_for_bridge_id(
            "stock-codex-wrapper-relay-proof"
        )
        marketplace_root = root / "local-apple-workflow-marketplace"
        wrapper_path = Path(stock_codex_compat_wrapper.__file__).resolve()
        wrapper_evidence_path = root / "wrapper-evidence.json"
        workspace_root = root / "workspace"
        codex_home.mkdir(mode=0o700)
        temp_home.mkdir(mode=0o700)
        workspace_root.mkdir(mode=0o700)
        (codex_home / "auth.json").symlink_to(auth_path)

        _write_stock_codex_compat_marketplace(
            source_bundle=source_bundle,
            marketplace_root=marketplace_root,
        )
        env = _stock_codex_compat_env(home=temp_home, codex_home=codex_home)
        enabled_features = _stock_codex_supported_feature_names(stock_codex_path, env=env)
        feature_args = _stock_codex_enable_feature_args(enabled_features)
        _run_stock_codex_json(
            stock_codex_path,
            ["plugin", "marketplace", "add", str(marketplace_root), "--json"],
            env=env,
        )
        _run_stock_codex_json(
            stock_codex_path,
            ["plugin", "add", STOCK_CODEX_COMPAT_PLUGIN_ID, "--json"],
            env=env,
        )
        plugin_list_output = _run_stock_codex_json(
            stock_codex_path,
            ["plugin", "list", "--json"],
            env=env,
        )
        _validate_stock_codex_compat_plugin_state(
            marketplace_list_output=_run_stock_codex_json(
                stock_codex_path,
                ["plugin", "marketplace", "list", "--json"],
                env=env,
            ),
            plugin_list_output=plugin_list_output,
            installed_plugin_path=(
                codex_home
                / "plugins"
                / "cache"
                / STOCK_CODEX_COMPAT_MARKETPLACE
                / PLUGIN_NAME
                / "0.1.1"
            ),
        )

        write_mcp_bridge_config(bridge_dir)
        write_policy_hook_config(
            bridge_dir,
            ap_server_url=STOCK_CODEX_COMPAT_AP_SERVER_URL,
            ap_auth_headers={},
        )
        _inject_mcp_server_config(codex_home, bridge_dir, sys.executable)
        _write_codex_policy_hooks_file(codex_home, bridge_dir, sys.executable)
        mcp_list_output = _run_stock_codex_json(
            stock_codex_path,
            ["mcp", "list", "--json"],
            env=env,
        )
        mcp_omnigent_output = _run_stock_codex_json(
            stock_codex_path,
            ["mcp", "get", "omnigent", "--json"],
            env=env,
        )
        _hook_events, mcp_servers, _mcp_command, _mcp_args = _validate_stock_codex_compat_bridge(
            codex_home=codex_home,
            bridge_dir=bridge_dir,
            mcp_list_output=mcp_list_output,
            mcp_omnigent_output=mcp_omnigent_output,
        )

        relay_calls: list[dict[str, Any]] = []
        loop = asyncio.new_event_loop()
        loop_ready = threading.Event()

        def run_loop() -> None:
            asyncio.set_event_loop(loop)
            loop_ready.set()
            loop.run_forever()

        loop_thread = threading.Thread(
            target=run_loop,
            name="omnigent-stock-codex-relay-proof-loop",
            daemon=True,
        )
        loop_thread.start()
        if not loop_ready.wait(timeout=5.0):
            raise SystemExit("Timed out starting relay event loop for stock Codex proof.")

        async def relay_executor(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
            relay_calls.append({"name": name, "arguments": dict(arguments)})
            if name != STOCK_CODEX_COMPAT_RELAY_TOOL_NAME:
                return {"error": f"unexpected relay tool: {name}"}
            if arguments.get("message") != STOCK_CODEX_COMPAT_RELAY_TOOL_ARGUMENT:
                return {
                    "error": "unexpected relay tool arguments",
                    "arguments": arguments,
                }
            return {
                "source": "omnigent-relay",
                "sentinel": STOCK_CODEX_COMPAT_RELAY_TOOL_OUTPUT_SENTINEL,
                "arguments": arguments,
            }

        relay = None
        try:
            try:
                relay = start_tool_relay(
                    bridge_dir=bridge_dir,
                    tools=[
                        {
                            "name": STOCK_CODEX_COMPAT_RELAY_TOOL_NAME,
                            "description": (
                                "Return deterministic Omnigent relay evidence for the "
                                "stock Codex compatibility wrapper proof."
                            ),
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "message": {
                                        "type": "string",
                                        "description": "Relay proof message.",
                                    }
                                },
                                "required": ["message"],
                                "additionalProperties": False,
                            },
                        }
                    ],
                    tool_executor=relay_executor,
                    loop=loop,
                )
            finally:
                codex_native_bridge._BRIDGE_ROOT = previous_bridge_root
            qualified_tool_name = f"mcp__omnigent__{STOCK_CODEX_COMPAT_RELAY_TOOL_NAME}"
            alt_qualified_tool_name = f"omnigent__{STOCK_CODEX_COMPAT_RELAY_TOOL_NAME}"
            prompt_input = subprocess.run(
                [
                    str(stock_codex_path),
                    "debug",
                    "prompt-input",
                    *feature_args,
                    "Omnigent relay prompt-input visibility probe.",
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=60.0,
                env=env,
                stdin=subprocess.DEVNULL,
            )
            prompt_input_preview = _preview_text(
                prompt_input.stdout or prompt_input.stderr,
                limit=2000,
            )
            if prompt_input.returncode != 0:
                raise SystemExit(
                    "Stock Codex debug prompt-input failed for relay-tool proof.\n"
                    f"exit={prompt_input.returncode}\n"
                    f"stdout_preview={_preview_text(prompt_input.stdout, limit=2000)}\n"
                    f"stderr_preview={_preview_text(prompt_input.stderr, limit=2000)}"
                )
            prompt_input_mentions_relay_tool = any(
                name in prompt_input.stdout
                for name in (
                    STOCK_CODEX_COMPAT_RELAY_TOOL_NAME,
                    qualified_tool_name,
                    alt_qualified_tool_name,
                )
            )
            relay_arguments_json = json.dumps(
                {"message": STOCK_CODEX_COMPAT_RELAY_TOOL_ARGUMENT},
                sort_keys=True,
            )
            prompt = (
                "Wrapped stock Codex Omnigent relay tool proof. Use the real MCP "
                f"tool `{qualified_tool_name}` exactly once. If this Codex build "
                "shows a different MCP prefix, the same tool may appear as "
                f"`{alt_qualified_tool_name}` or `{STOCK_CODEX_COMPAT_RELAY_TOOL_NAME}`. "
                "If the MCP tool is deferred, first use `tool_search` to search "
                f"for `{STOCK_CODEX_COMPAT_RELAY_TOOL_NAME}`, then call the exposed "
                "tool. "
                "Use JSON arguments "
                f"{relay_arguments_json}. Do not use the shell command tool, do "
                "not inspect files, and do not write a pseudo-call in text. "
                "Only the actual persisted MCP tool call counts. Reply exactly "
                f"{STOCK_CODEX_COMPAT_WRAPPER_RELAY_TOOL_SENTINEL} if the tool "
                f"output contains {STOCK_CODEX_COMPAT_RELAY_TOOL_OUTPUT_SENTINEL}; "
                "otherwise reply RELAY_TOOL_MISSING."
            )
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "omnigent.stock_codex_compat_wrapper",
                    "--stock-codex-path",
                    str(stock_codex_path),
                    "--route-prefix",
                    EXPECTED_ROUTE,
                    "--evidence-path",
                    str(wrapper_evidence_path),
                    "--",
                    "exec",
                    *feature_args,
                    "--json",
                    "--dangerously-bypass-hook-trust",
                    "--skip-git-repo-check",
                    "--sandbox",
                    "read-only",
                    "-C",
                    str(workspace_root),
                    prompt,
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout_seconds if timeout_seconds > 0 else None,
                env=env,
                stdin=subprocess.DEVNULL,
            )
        finally:
            if relay is not None:
                relay.close()
            loop.call_soon_threadsafe(loop.stop)
            loop_thread.join(timeout=5.0)
            loop.close()
        stderr_preview = _preview_text(completed.stderr, limit=2000)
        if completed.returncode != 0:
            raise SystemExit(
                "Live stock-codex-compat-wrapper-relay-tool command failed.\n"
                f"exit={completed.returncode}\n"
                f"stderr={stderr_preview}\n"
                f"stdout_preview={_preview_text(completed.stdout, limit=2000)}"
            )
        events = _parse_stock_codex_exec_jsonl(completed.stdout)
        relay_evidence = _validate_stock_codex_omnigent_relay_tool_events(
            events,
            tool_name=STOCK_CODEX_COMPAT_RELAY_TOOL_NAME,
            output_sentinel=STOCK_CODEX_COMPAT_RELAY_TOOL_OUTPUT_SENTINEL,
            executor_calls=relay_calls,
        )
        thread_id, first_agent_message = _validate_stock_codex_agent_message(
            events,
            expected_sentinel=STOCK_CODEX_COMPAT_WRAPPER_RELAY_TOOL_SENTINEL,
            proof_name="stock-codex-compat-wrapper-relay-tool",
        )
        if not first_agent_message.startswith(EXPECTED_ROUTE):
            raise SystemExit(
                "Live stock-codex-compat-wrapper-relay-tool proof did not emit "
                "deterministic route evidence before model output.\n"
                f"expected_prefix={EXPECTED_ROUTE!r}\n"
                f"first_agent_message={first_agent_message!r}"
            )
        wrapper_evidence = _read_stock_codex_compat_wrapper_evidence(wrapper_evidence_path)
        if wrapper_evidence["routeInjected"] is not True:
            raise SystemExit(
                "Live stock-codex-compat-wrapper-relay-tool proof did not prove "
                "wrapper-owned route injection.\n"
                f"evidence={wrapper_evidence!r}"
            )
        return StockCodexCompatWrapperRelayToolProof(
            stock_codex_path=stock_codex_path,
            stock_codex_version=stock_codex_version,
            source_bundle=source_bundle,
            wrapper_path=wrapper_path,
            codex_home=codex_home,
            auth_path=auth_path,
            bridge_dir=bridge_dir,
            workspace_root=workspace_root,
            thread_id=thread_id,
            relay_tool_name=STOCK_CODEX_COMPAT_RELAY_TOOL_NAME,
            relay_tool_arguments=dict(relay_evidence["arguments"]),
            relay_output_preview=str(relay_evidence["output_preview"]),
            relay_event_types=tuple(relay_evidence["event_types"]),
            enabled_features=enabled_features,
            skipped_features=tuple(sorted(STOCK_CODEX_FEATURES_REQUIRING_NONDEFAULT_SUPPORT)),
            prompt_input_mentions_relay_tool=prompt_input_mentions_relay_tool,
            prompt_input_preview=prompt_input_preview,
            first_agent_message=first_agent_message,
            first_agent_message_before_wrapper=str(
                wrapper_evidence["firstAgentMessageBefore"]
            ),
            route_injected=bool(wrapper_evidence["routeInjected"]),
            wrapper_evidence_path=wrapper_evidence_path,
            event_count=len(events),
            mcp_servers=mcp_servers,
            stderr_preview=stderr_preview,
        )


def _read_stock_codex_compat_wrapper_evidence(evidence_path: Path) -> dict[str, Any]:
    """Read and validate temporary evidence written by the Omnigent wrapper."""
    if not evidence_path.is_file():
        raise SystemExit(f"Stock Codex wrapper evidence file missing: {evidence_path}")
    try:
        payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Stock Codex wrapper evidence is not JSON: {evidence_path}") from exc
    if not isinstance(payload, dict):
        raise SystemExit(f"Stock Codex wrapper evidence root is not an object: {payload!r}")
    if not isinstance(payload.get("firstAgentMessageBefore"), str):
        raise SystemExit(f"Stock Codex wrapper evidence missing pre-wrapper text: {payload!r}")
    if not isinstance(payload.get("routeInjected"), bool):
        raise SystemExit(f"Stock Codex wrapper evidence missing injection flag: {payload!r}")
    if payload.get("routePresentAfter") is not True:
        raise SystemExit(f"Stock Codex wrapper evidence did not preserve route: {payload!r}")
    return payload


def _parse_stock_codex_exec_jsonl(stdout: str) -> list[dict[str, Any]]:
    """Parse ``codex exec --json`` output into event dictionaries."""
    events: list[dict[str, Any]] = []
    for index, line in enumerate(stdout.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"codex exec JSONL line {index} is not valid JSON: {line}") from exc
        if not isinstance(event, dict):
            raise SystemExit(f"codex exec JSONL line {index} is not an object: {line}")
        events.append(event)
    if not events:
        raise SystemExit("codex exec --json produced no events.")
    return events


def _validate_stock_codex_compat_live_events(events: list[dict[str, Any]]) -> tuple[str, str]:
    """Return live proof thread id and first assistant message or fail closed."""
    return _validate_stock_codex_agent_message(
        events,
        expected_sentinel=STOCK_CODEX_COMPAT_LIVE_SENTINEL,
        proof_name="stock-codex-compat-live",
    )


def _extract_stock_codex_thread_and_agent_message(
    events: list[dict[str, Any]],
    *,
    proof_name: str,
) -> tuple[str, str]:
    """Return proof thread id and first assistant message or fail closed."""
    thread_id = ""
    first_agent_message = ""
    for event in events:
        if event.get("type") == "thread.started" and not thread_id:
            raw_thread_id = event.get("thread_id")
            if isinstance(raw_thread_id, str):
                thread_id = raw_thread_id
        if event.get("type") != "item.completed":
            continue
        item = event.get("item")
        if not isinstance(item, dict):
            continue
        if item.get("type") != "agent_message":
            continue
        text = item.get("text")
        if isinstance(text, str):
            first_agent_message = text
            break
    if not thread_id:
        raise SystemExit(f"Live {proof_name} proof did not report a thread id.")
    return thread_id, first_agent_message


def _validate_stock_codex_agent_message(
    events: list[dict[str, Any]],
    *,
    expected_sentinel: str,
    proof_name: str,
) -> tuple[str, str]:
    """Return proof thread id and first assistant message or fail closed."""
    thread_id, first_agent_message = _extract_stock_codex_thread_and_agent_message(
        events,
        proof_name=proof_name,
    )
    if expected_sentinel not in first_agent_message:
        raise SystemExit(
            f"Live {proof_name} proof did not return the expected sentinel.\n"
            f"sentinel={expected_sentinel!r}\n"
            f"first_agent_message={first_agent_message!r}"
        )
    return thread_id, first_agent_message


def _validate_stock_codex_command_execution_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Return the completed command execution item or fail closed."""
    completed_commands: list[dict[str, Any]] = []
    for event in events:
        if event.get("type") != "item.completed":
            continue
        item = event.get("item")
        if not isinstance(item, dict) or item.get("type") != "command_execution":
            continue
        completed_commands.append(item)
    if len(completed_commands) != 1:
        raise SystemExit(
            "Expected exactly one completed command_execution item in wrapped "
            f"stock Codex proof; found {len(completed_commands)}."
        )
    item = completed_commands[0]
    command = item.get("command")
    output = item.get("aggregated_output")
    if not isinstance(command, str) or "cat tool-proof.txt" not in command:
        raise SystemExit(f"Wrapped stock Codex command did not read tool-proof.txt: {item!r}")
    if item.get("exit_code") != 0 or item.get("status") != "completed":
        raise SystemExit(f"Wrapped stock Codex command did not complete cleanly: {item!r}")
    if not isinstance(output, str) or TOOL_SENTINEL not in output:
        raise SystemExit(
            f"Wrapped stock Codex command output missed sentinel {TOOL_SENTINEL!r}: {item!r}"
        )
    return item


def _validate_stock_codex_adapter_command_execution_events(
    events: list[dict[str, Any]],
    *,
    command_name: str = STOCK_CODEX_COMPAT_ADAPTER_COMMAND_NAME,
    command_argument: str = STOCK_CODEX_COMPAT_ADAPTER_COMMAND_ARGUMENT,
    output_sentinel: str = STOCK_CODEX_COMPAT_ADAPTER_OUTPUT_SENTINEL,
    forbidden_command_names: tuple[str, ...] = (),
    forbidden_output_sentinels: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Return the completed wrapper adapter command item or fail closed."""
    completed_commands: list[dict[str, Any]] = []
    for event in events:
        if event.get("type") != "item.completed":
            continue
        item = event.get("item")
        if not isinstance(item, dict) or item.get("type") != "command_execution":
            continue
        completed_commands.append(item)
    if len(completed_commands) != 1:
        raise SystemExit(
            "Expected exactly one completed command_execution item in wrapped "
            f"stock Codex adapter proof; found {len(completed_commands)}."
        )
    item = completed_commands[0]
    command = item.get("command")
    output = item.get("aggregated_output")
    if (
        not isinstance(command, str)
        or command_name not in command
        or command_argument not in command
    ):
        raise SystemExit(f"Wrapped stock Codex did not run the adapter command: {item!r}")
    for forbidden_name in forbidden_command_names:
        if forbidden_name in command:
            raise SystemExit(
                "Wrapped stock Codex ran a rejected adapter command; "
                f"forbidden_name={forbidden_name!r} item={item!r}"
            )
    if item.get("exit_code") != 0 or item.get("status") != "completed":
        raise SystemExit(f"Wrapped stock Codex adapter command did not complete cleanly: {item!r}")
    if not isinstance(output, str) or output_sentinel not in output:
        raise SystemExit(
            "Wrapped stock Codex adapter command output missed sentinel "
            f"{output_sentinel!r}: {item!r}"
        )
    for forbidden_sentinel in forbidden_output_sentinels:
        if forbidden_sentinel in output:
            raise SystemExit(
                "Wrapped stock Codex output contained a rejected adapter sentinel; "
                f"forbidden_sentinel={forbidden_sentinel!r} item={item!r}"
            )
    return item


def _validate_stock_codex_omnigent_relay_tool_events(
    events: list[dict[str, Any]],
    *,
    tool_name: str,
    output_sentinel: str,
    executor_calls: list[dict[str, Any]],
) -> dict[str, Any]:
    """Validate one Omnigent relay tool call and its stock Codex JSONL evidence."""
    if len(executor_calls) != 1:
        raise SystemExit(
            "Expected exactly one Omnigent relay executor call in wrapped "
            f"stock Codex proof; found {len(executor_calls)}."
        )
    executor_call = executor_calls[0]
    if executor_call.get("name") != tool_name:
        raise SystemExit(f"Wrapped stock Codex called the wrong relay tool: {executor_call!r}")
    arguments = executor_call.get("arguments")
    if not isinstance(arguments, dict):
        raise SystemExit(f"Wrapped stock Codex relay call omitted arguments: {executor_call!r}")

    qualified_tool_name = f"mcp__omnigent__{tool_name}"
    completed_tool_items: list[dict[str, Any]] = []
    tool_name_items: list[dict[str, Any]] = []
    sentinel_items: list[dict[str, Any]] = []
    for event in events:
        if event.get("type") != "item.completed":
            continue
        item = event.get("item")
        if not isinstance(item, dict):
            continue
        item_type = item.get("type")
        if item_type in {"agent_message", "command_execution"}:
            continue
        encoded = json.dumps(item, sort_keys=True)
        if tool_name in encoded or qualified_tool_name in encoded:
            tool_name_items.append(item)
            completed_tool_items.append(item)
        if output_sentinel in encoded:
            sentinel_items.append(item)
            if item not in completed_tool_items:
                completed_tool_items.append(item)

    if len(tool_name_items) != 1:
        raise SystemExit(
            "Expected exactly one completed stock Codex JSONL tool item naming "
            f"{tool_name!r}; found {len(tool_name_items)}."
        )
    if not sentinel_items:
        raise SystemExit(
            "Wrapped stock Codex JSONL did not preserve the Omnigent relay "
            f"tool output sentinel {output_sentinel!r}."
        )
    event_types = tuple(
        str(item.get("type"))
        for item in completed_tool_items
        if isinstance(item.get("type"), str)
    )
    return {
        "arguments": arguments,
        "event_types": event_types,
        "output_preview": _preview_text(
            json.dumps(sentinel_items[0], sort_keys=True),
            limit=500,
        ),
    }


def _preview_text(value: str, *, limit: int) -> str:
    """Return a compact one-field diagnostic preview."""
    if len(value) <= limit:
        return value
    return f"{value[:limit]}...[truncated]"


def print_stock_codex_compat_live_proof(proof: StockCodexCompatLiveProof) -> None:
    """Emit operator evidence for a successful stock Codex live compatibility proof."""
    print("stock_codex_compat_live_rehearsal=selected")
    print(f"stock_codex_compat_live_stock_codex_path={proof.stock_codex_path}")
    print(f"stock_codex_compat_live_stock_codex_version={proof.stock_codex_version}")
    print(f"stock_codex_compat_live_source_bundle={proof.source_bundle}")
    print(f"stock_codex_compat_live_codex_home={proof.codex_home}")
    print(f"stock_codex_compat_live_auth_path={proof.auth_path}")
    print(f"stock_codex_compat_live_bridge_dir={proof.bridge_dir}")
    print(f"stock_codex_compat_live_workspace_root={proof.workspace_root}")
    print(f"stock_codex_compat_live_thread_id={proof.thread_id}")
    print(f"stock_codex_compat_live_event_count={proof.event_count}")
    print(f"stock_codex_compat_live_mcp_servers={','.join(proof.mcp_servers)}")
    print(
        "stock_codex_compat_live_first_agent_message_preview="
        f"{_preview_text(proof.first_agent_message, limit=500)!r}"
    )
    print(f"stock_codex_compat_live_stderr_preview={proof.stderr_preview!r}")
    print("stock_codex_compat_live_cache_lifecycle=temporary_removed_after_proof")
    print(
        "ASSERTION: stock Codex live entrypoint emitted deterministic route "
        "evidence before model output through the installed compatibility bridge"
    )


def print_stock_codex_compat_wrapper_live_proof(
    proof: StockCodexCompatWrapperLiveProof,
) -> None:
    """Emit operator evidence for the Omnigent-owned stock Codex wrapper proof."""
    print("stock_codex_compat_wrapper_live_rehearsal=selected")
    print(
        "stock_codex_compat_wrapper_live_route_surface="
        "omnigent-wrapper-jsonl-first-agent-message-prefix"
    )
    print(f"stock_codex_compat_wrapper_live_stock_codex_path={proof.stock_codex_path}")
    print(f"stock_codex_compat_wrapper_live_stock_codex_version={proof.stock_codex_version}")
    print(f"stock_codex_compat_wrapper_live_source_bundle={proof.source_bundle}")
    print(f"stock_codex_compat_wrapper_live_wrapper_path={proof.wrapper_path}")
    print(f"stock_codex_compat_wrapper_live_codex_home={proof.codex_home}")
    print(f"stock_codex_compat_wrapper_live_auth_path={proof.auth_path}")
    print(f"stock_codex_compat_wrapper_live_bridge_dir={proof.bridge_dir}")
    print(f"stock_codex_compat_wrapper_live_workspace_root={proof.workspace_root}")
    print(f"stock_codex_compat_wrapper_live_thread_id={proof.thread_id}")
    print(f"stock_codex_compat_wrapper_live_event_count={proof.event_count}")
    print(f"stock_codex_compat_wrapper_live_mcp_servers={','.join(proof.mcp_servers)}")
    print(f"stock_codex_compat_wrapper_live_route_injected={proof.route_injected}")
    print(f"stock_codex_compat_wrapper_live_evidence_path={proof.wrapper_evidence_path}")
    print(
        "stock_codex_compat_wrapper_live_pre_wrapper_message_preview="
        f"{_preview_text(proof.first_agent_message_before_wrapper, limit=500)!r}"
    )
    print(
        "stock_codex_compat_wrapper_live_first_agent_message_preview="
        f"{_preview_text(proof.first_agent_message, limit=500)!r}"
    )
    print(f"stock_codex_compat_wrapper_live_stderr_preview={proof.stderr_preview!r}")
    print("stock_codex_compat_wrapper_live_cache_lifecycle=temporary_removed_after_proof")
    print(
        "ASSERTION: an Omnigent-owned wrapper around stock Codex prefixed "
        "deterministic route evidence before visible model output"
    )
    print(
        "ASSERTION: the wrapped stock Codex process still used the isolated "
        "plugin, MCP bridge, policy-hook config, and stock auth profile"
    )


def print_stock_codex_compat_wrapper_command_tool_proof(
    proof: StockCodexCompatWrapperCommandToolProof,
) -> None:
    """Emit operator evidence for wrapped stock Codex command tool execution."""
    print("stock_codex_compat_wrapper_command_tool_rehearsal=selected")
    print(
        "stock_codex_compat_wrapper_command_tool_surface="
        "stock-codex-exec-json-command-execution"
    )
    print(f"stock_codex_compat_wrapper_command_tool_stock_codex_path={proof.stock_codex_path}")
    print(
        "stock_codex_compat_wrapper_command_tool_stock_codex_version="
        f"{proof.stock_codex_version}"
    )
    print(f"stock_codex_compat_wrapper_command_tool_source_bundle={proof.source_bundle}")
    print(f"stock_codex_compat_wrapper_command_tool_wrapper_path={proof.wrapper_path}")
    print(f"stock_codex_compat_wrapper_command_tool_codex_home={proof.codex_home}")
    print(f"stock_codex_compat_wrapper_command_tool_auth_path={proof.auth_path}")
    print(f"stock_codex_compat_wrapper_command_tool_bridge_dir={proof.bridge_dir}")
    print(f"stock_codex_compat_wrapper_command_tool_workspace_root={proof.workspace_root}")
    print(f"stock_codex_compat_wrapper_command_tool_thread_id={proof.thread_id}")
    print(f"stock_codex_compat_wrapper_command_tool_event_count={proof.event_count}")
    print(
        "stock_codex_compat_wrapper_command_tool_mcp_servers="
        f"{','.join(proof.mcp_servers)}"
    )
    print(f"stock_codex_compat_wrapper_command_tool_route_injected={proof.route_injected}")
    print(f"stock_codex_compat_wrapper_command_tool_evidence_path={proof.wrapper_evidence_path}")
    print(
        "stock_codex_compat_wrapper_command_tool_command="
        f"{_preview_text(proof.command, limit=500)!r}"
    )
    print(
        "stock_codex_compat_wrapper_command_tool_output_preview="
        f"{_preview_text(proof.command_output, limit=500)!r}"
    )
    print(
        "stock_codex_compat_wrapper_command_tool_pre_wrapper_message_preview="
        f"{_preview_text(proof.first_agent_message_before_wrapper, limit=500)!r}"
    )
    print(
        "stock_codex_compat_wrapper_command_tool_first_agent_message_preview="
        f"{_preview_text(proof.first_agent_message, limit=500)!r}"
    )
    print(f"stock_codex_compat_wrapper_command_tool_stderr_preview={proof.stderr_preview!r}")
    print("stock_codex_compat_wrapper_command_tool_cache_lifecycle=temporary_removed_after_proof")
    print(
        "ASSERTION: wrapped stock Codex executed one read-only command tool "
        "and preserved its command_execution event"
    )
    print(
        "ASSERTION: the Omnigent wrapper still prefixed deterministic route "
        "evidence before the final visible tool-result answer"
    )


def print_stock_codex_compat_wrapper_adapter_tool_proof(
    proof: StockCodexCompatWrapperAdapterToolProof,
) -> None:
    """Emit operator evidence for wrapper-owned adapter command execution."""
    print("stock_codex_compat_wrapper_adapter_tool_rehearsal=selected")
    print(
        "stock_codex_compat_wrapper_adapter_tool_surface="
        "wrapper-owned-adapter-package-via-stock-command-tool"
    )
    print(f"stock_codex_compat_wrapper_adapter_tool_stock_codex_path={proof.stock_codex_path}")
    print(
        "stock_codex_compat_wrapper_adapter_tool_stock_codex_version="
        f"{proof.stock_codex_version}"
    )
    print(f"stock_codex_compat_wrapper_adapter_tool_source_bundle={proof.source_bundle}")
    print(f"stock_codex_compat_wrapper_adapter_tool_wrapper_path={proof.wrapper_path}")
    print(f"stock_codex_compat_wrapper_adapter_tool_codex_home={proof.codex_home}")
    print(f"stock_codex_compat_wrapper_adapter_tool_auth_path={proof.auth_path}")
    print(f"stock_codex_compat_wrapper_adapter_tool_bridge_dir={proof.bridge_dir}")
    print(f"stock_codex_compat_wrapper_adapter_tool_workspace_root={proof.workspace_root}")
    print(f"stock_codex_compat_wrapper_adapter_tool_adapter_bin={proof.adapter_bin}")
    print(
        "stock_codex_compat_wrapper_adapter_tool_adapter_manifest="
        f"{proof.adapter_manifest}"
    )
    print(
        "stock_codex_compat_wrapper_adapter_tool_adapter_tools="
        f"{','.join(proof.adapter_tool_names)}"
    )
    print(f"stock_codex_compat_wrapper_adapter_tool_thread_id={proof.thread_id}")
    print(f"stock_codex_compat_wrapper_adapter_tool_event_count={proof.event_count}")
    print(
        "stock_codex_compat_wrapper_adapter_tool_mcp_servers="
        f"{','.join(proof.mcp_servers)}"
    )
    print(f"stock_codex_compat_wrapper_adapter_tool_route_injected={proof.route_injected}")
    print(f"stock_codex_compat_wrapper_adapter_tool_evidence_path={proof.wrapper_evidence_path}")
    print(
        "stock_codex_compat_wrapper_adapter_tool_command="
        f"{_preview_text(proof.command, limit=500)!r}"
    )
    print(
        "stock_codex_compat_wrapper_adapter_tool_output_preview="
        f"{_preview_text(proof.command_output, limit=500)!r}"
    )
    print(
        "stock_codex_compat_wrapper_adapter_tool_pre_wrapper_message_preview="
        f"{_preview_text(proof.first_agent_message_before_wrapper, limit=500)!r}"
    )
    print(
        "stock_codex_compat_wrapper_adapter_tool_first_agent_message_preview="
        f"{_preview_text(proof.first_agent_message, limit=500)!r}"
    )
    print(f"stock_codex_compat_wrapper_adapter_tool_stderr_preview={proof.stderr_preview!r}")
    print("stock_codex_compat_wrapper_adapter_tool_cache_lifecycle=temporary_removed_after_proof")
    print(
        "ASSERTION: the Omnigent wrapper exposed a wrapper-owned adapter "
        "package command to stock Codex through a validated manifest and PATH"
    )
    print(
        "ASSERTION: wrapped stock Codex executed that adapter command once "
        "and preserved the command_execution event"
    )
    print(
        "ASSERTION: the Omnigent wrapper still prefixed deterministic route "
        "evidence before the final visible adapter-result answer"
    )


def print_stock_codex_compat_wrapper_adapter_arbitration_proof(
    proof: StockCodexCompatWrapperAdapterArbitrationProof,
) -> None:
    """Emit operator evidence for multi-tool adapter arbitration."""
    print("stock_codex_compat_wrapper_adapter_arbitration_rehearsal=selected")
    print(
        "stock_codex_compat_wrapper_adapter_arbitration_surface="
        "wrapper-owned-multi-tool-adapter-package-via-stock-command-tool"
    )
    print(
        "stock_codex_compat_wrapper_adapter_arbitration_stock_codex_path="
        f"{proof.stock_codex_path}"
    )
    print(
        "stock_codex_compat_wrapper_adapter_arbitration_stock_codex_version="
        f"{proof.stock_codex_version}"
    )
    print(
        "stock_codex_compat_wrapper_adapter_arbitration_source_bundle="
        f"{proof.source_bundle}"
    )
    print(
        "stock_codex_compat_wrapper_adapter_arbitration_wrapper_path="
        f"{proof.wrapper_path}"
    )
    print(
        f"stock_codex_compat_wrapper_adapter_arbitration_codex_home={proof.codex_home}"
    )
    print(
        f"stock_codex_compat_wrapper_adapter_arbitration_auth_path={proof.auth_path}"
    )
    print(
        f"stock_codex_compat_wrapper_adapter_arbitration_bridge_dir={proof.bridge_dir}"
    )
    print(
        "stock_codex_compat_wrapper_adapter_arbitration_workspace_root="
        f"{proof.workspace_root}"
    )
    print(
        f"stock_codex_compat_wrapper_adapter_arbitration_adapter_bin={proof.adapter_bin}"
    )
    print(
        "stock_codex_compat_wrapper_adapter_arbitration_adapter_manifest="
        f"{proof.adapter_manifest}"
    )
    print(
        "stock_codex_compat_wrapper_adapter_arbitration_adapter_tools="
        f"{','.join(proof.adapter_tool_names)}"
    )
    print(
        "stock_codex_compat_wrapper_adapter_arbitration_selected_tool="
        f"{proof.selected_tool_name}"
    )
    print(
        "stock_codex_compat_wrapper_adapter_arbitration_rejected_tool="
        f"{proof.rejected_tool_name}"
    )
    print(
        f"stock_codex_compat_wrapper_adapter_arbitration_thread_id={proof.thread_id}"
    )
    print(
        f"stock_codex_compat_wrapper_adapter_arbitration_event_count={proof.event_count}"
    )
    print(
        "stock_codex_compat_wrapper_adapter_arbitration_mcp_servers="
        f"{','.join(proof.mcp_servers)}"
    )
    print(
        "stock_codex_compat_wrapper_adapter_arbitration_route_injected="
        f"{proof.route_injected}"
    )
    print(
        "stock_codex_compat_wrapper_adapter_arbitration_evidence_path="
        f"{proof.wrapper_evidence_path}"
    )
    print(
        "stock_codex_compat_wrapper_adapter_arbitration_command="
        f"{_preview_text(proof.command, limit=500)!r}"
    )
    print(
        "stock_codex_compat_wrapper_adapter_arbitration_output_preview="
        f"{_preview_text(proof.command_output, limit=500)!r}"
    )
    print(
        "stock_codex_compat_wrapper_adapter_arbitration_pre_wrapper_message_preview="
        f"{_preview_text(proof.first_agent_message_before_wrapper, limit=500)!r}"
    )
    print(
        "stock_codex_compat_wrapper_adapter_arbitration_first_agent_message_preview="
        f"{_preview_text(proof.first_agent_message, limit=500)!r}"
    )
    print(
        "stock_codex_compat_wrapper_adapter_arbitration_stderr_preview="
        f"{proof.stderr_preview!r}"
    )
    print(
        "stock_codex_compat_wrapper_adapter_arbitration_cache_lifecycle="
        "temporary_removed_after_proof"
    )
    print(
        "ASSERTION: the Omnigent wrapper validated a generated multi-tool "
        "adapter package before launching stock Codex"
    )
    print(
        "ASSERTION: wrapped stock Codex selected the route adapter, rejected "
        "the release adapter, and preserved exactly one command_execution event"
    )
    print(
        "ASSERTION: the Omnigent wrapper still prefixed deterministic route "
        "evidence before the final visible adapter-arbitration answer"
    )


def print_stock_codex_compat_wrapper_apple_docs_adapter_proof(
    proof: StockCodexCompatWrapperAppleDocsAdapterProof,
) -> None:
    """Emit operator evidence for real Apple docs adapter execution."""
    print("stock_codex_compat_wrapper_apple_docs_adapter_rehearsal=selected")
    print(
        "stock_codex_compat_wrapper_apple_docs_adapter_surface="
        "wrapper-owned-real-apple-docs-adapter-package-via-stock-command-tool"
    )
    print(
        "stock_codex_compat_wrapper_apple_docs_adapter_stock_codex_path="
        f"{proof.stock_codex_path}"
    )
    print(
        "stock_codex_compat_wrapper_apple_docs_adapter_stock_codex_version="
        f"{proof.stock_codex_version}"
    )
    print(
        "stock_codex_compat_wrapper_apple_docs_adapter_source_bundle="
        f"{proof.source_bundle}"
    )
    print(
        "stock_codex_compat_wrapper_apple_docs_adapter_wrapper_path="
        f"{proof.wrapper_path}"
    )
    print(f"stock_codex_compat_wrapper_apple_docs_adapter_codex_home={proof.codex_home}")
    print(f"stock_codex_compat_wrapper_apple_docs_adapter_auth_path={proof.auth_path}")
    print(f"stock_codex_compat_wrapper_apple_docs_adapter_bridge_dir={proof.bridge_dir}")
    print(
        "stock_codex_compat_wrapper_apple_docs_adapter_workspace_root="
        f"{proof.workspace_root}"
    )
    print(f"stock_codex_compat_wrapper_apple_docs_adapter_adapter_bin={proof.adapter_bin}")
    print(
        "stock_codex_compat_wrapper_apple_docs_adapter_adapter_manifest="
        f"{proof.adapter_manifest}"
    )
    print(
        "stock_codex_compat_wrapper_apple_docs_adapter_adapter_tools="
        f"{','.join(proof.adapter_tool_names)}"
    )
    print(f"stock_codex_compat_wrapper_apple_docs_adapter_docs_url={proof.docs_url}")
    print(f"stock_codex_compat_wrapper_apple_docs_adapter_thread_id={proof.thread_id}")
    print(f"stock_codex_compat_wrapper_apple_docs_adapter_event_count={proof.event_count}")
    print(
        "stock_codex_compat_wrapper_apple_docs_adapter_mcp_servers="
        f"{','.join(proof.mcp_servers)}"
    )
    print(
        "stock_codex_compat_wrapper_apple_docs_adapter_route_injected="
        f"{proof.route_injected}"
    )
    print(
        "stock_codex_compat_wrapper_apple_docs_adapter_evidence_path="
        f"{proof.wrapper_evidence_path}"
    )
    print(
        "stock_codex_compat_wrapper_apple_docs_adapter_command="
        f"{_preview_text(proof.command, limit=500)!r}"
    )
    print(
        "stock_codex_compat_wrapper_apple_docs_adapter_output_preview="
        f"{_preview_text(proof.command_output, limit=500)!r}"
    )
    print(
        "stock_codex_compat_wrapper_apple_docs_adapter_pre_wrapper_message_preview="
        f"{_preview_text(proof.first_agent_message_before_wrapper, limit=500)!r}"
    )
    print(
        "stock_codex_compat_wrapper_apple_docs_adapter_first_agent_message_preview="
        f"{_preview_text(proof.first_agent_message, limit=500)!r}"
    )
    print(
        "stock_codex_compat_wrapper_apple_docs_adapter_stderr_preview="
        f"{proof.stderr_preview!r}"
    )
    print(
        "stock_codex_compat_wrapper_apple_docs_adapter_cache_lifecycle="
        "temporary_removed_after_proof"
    )
    print(
        "ASSERTION: the Omnigent wrapper validated a real Apple docs adapter "
        "package before launching stock Codex"
    )
    print(
        "ASSERTION: wrapped stock Codex fetched Apple docs through the generated "
        "adapter command and preserved exactly one command_execution event"
    )
    print(
        "ASSERTION: the Omnigent wrapper still prefixed deterministic route "
        "evidence before the final visible Apple-docs adapter answer"
    )


def print_stock_codex_compat_wrapper_apple_docs_bridge_adapter_proof(
    proof: StockCodexCompatWrapperAppleDocsBridgeAdapterProof,
) -> None:
    """Emit operator evidence for Apple docs adapter bridge execution."""
    print("stock_codex_compat_wrapper_apple_docs_bridge_adapter_rehearsal=selected")
    print(
        "stock_codex_compat_wrapper_apple_docs_bridge_adapter_surface="
        "wrapper-owned-real-apple-docs-file-bridge-adapter-package-via-stock-command-tool"
    )
    print(
        "stock_codex_compat_wrapper_apple_docs_bridge_adapter_stock_codex_path="
        f"{proof.stock_codex_path}"
    )
    print(
        "stock_codex_compat_wrapper_apple_docs_bridge_adapter_stock_codex_version="
        f"{proof.stock_codex_version}"
    )
    print(
        "stock_codex_compat_wrapper_apple_docs_bridge_adapter_source_bundle="
        f"{proof.source_bundle}"
    )
    print(
        "stock_codex_compat_wrapper_apple_docs_bridge_adapter_wrapper_path="
        f"{proof.wrapper_path}"
    )
    print(
        "stock_codex_compat_wrapper_apple_docs_bridge_adapter_codex_home="
        f"{proof.codex_home}"
    )
    print(
        "stock_codex_compat_wrapper_apple_docs_bridge_adapter_auth_path="
        f"{proof.auth_path}"
    )
    print(
        "stock_codex_compat_wrapper_apple_docs_bridge_adapter_bridge_dir="
        f"{proof.bridge_dir}"
    )
    print(
        "stock_codex_compat_wrapper_apple_docs_bridge_adapter_workspace_root="
        f"{proof.workspace_root}"
    )
    print(
        "stock_codex_compat_wrapper_apple_docs_bridge_adapter_adapter_bin="
        f"{proof.adapter_bin}"
    )
    print(
        "stock_codex_compat_wrapper_apple_docs_bridge_adapter_adapter_manifest="
        f"{proof.adapter_manifest}"
    )
    print(
        "stock_codex_compat_wrapper_apple_docs_bridge_adapter_adapter_bridge_dir="
        f"{proof.adapter_bridge_dir}"
    )
    print(
        "stock_codex_compat_wrapper_apple_docs_bridge_adapter_adapter_tools="
        f"{','.join(proof.adapter_tool_names)}"
    )
    print(
        "stock_codex_compat_wrapper_apple_docs_bridge_adapter_docs_url="
        f"{proof.docs_url}"
    )
    print(f"stock_codex_compat_wrapper_apple_docs_bridge_adapter_sandbox={proof.sandbox}")
    print(
        "stock_codex_compat_wrapper_apple_docs_bridge_adapter_thread_id="
        f"{proof.thread_id}"
    )
    print(
        "stock_codex_compat_wrapper_apple_docs_bridge_adapter_event_count="
        f"{proof.event_count}"
    )
    print(
        "stock_codex_compat_wrapper_apple_docs_bridge_adapter_mcp_servers="
        f"{','.join(proof.mcp_servers)}"
    )
    print(
        "stock_codex_compat_wrapper_apple_docs_bridge_adapter_route_injected="
        f"{proof.route_injected}"
    )
    print(
        "stock_codex_compat_wrapper_apple_docs_bridge_adapter_evidence_path="
        f"{proof.wrapper_evidence_path}"
    )
    print(
        "stock_codex_compat_wrapper_apple_docs_bridge_adapter_command="
        f"{_preview_text(proof.command, limit=500)!r}"
    )
    print(
        "stock_codex_compat_wrapper_apple_docs_bridge_adapter_output_preview="
        f"{_preview_text(proof.command_output, limit=500)!r}"
    )
    print(
        "stock_codex_compat_wrapper_apple_docs_bridge_adapter_pre_wrapper_message_preview="
        f"{_preview_text(proof.first_agent_message_before_wrapper, limit=500)!r}"
    )
    print(
        "stock_codex_compat_wrapper_apple_docs_bridge_adapter_first_agent_message_preview="
        f"{_preview_text(proof.first_agent_message, limit=500)!r}"
    )
    print(
        "stock_codex_compat_wrapper_apple_docs_bridge_adapter_stderr_preview="
        f"{proof.stderr_preview!r}"
    )
    print(
        "stock_codex_compat_wrapper_apple_docs_bridge_adapter_cache_lifecycle="
        "temporary_removed_after_proof"
    )
    print(
        "ASSERTION: stock Codex ran the generated adapter command under "
        "workspace-write, not danger-full-access"
    )
    print(
        "ASSERTION: networked Apple docs execution happened through the "
        "Omnigent-owned file bridge outside the stock Codex sandbox"
    )
    print(
        "ASSERTION: the Omnigent wrapper still prefixed deterministic route "
        "evidence before the final visible Apple-docs bridge-adapter answer"
    )


def print_stock_codex_compat_wrapper_xcodebuild_bridge_adapter_proof(
    proof: StockCodexCompatWrapperXcodebuildBridgeAdapterProof,
) -> None:
    """Emit operator evidence for XcodeBuildMCP adapter bridge execution."""
    print("stock_codex_compat_wrapper_xcodebuild_bridge_adapter_rehearsal=selected")
    print(
        "stock_codex_compat_wrapper_xcodebuild_bridge_adapter_surface="
        "wrapper-owned-xcodebuild-file-bridge-adapter-package-via-stock-command-tool"
    )
    print(
        "stock_codex_compat_wrapper_xcodebuild_bridge_adapter_stock_codex_path="
        f"{proof.stock_codex_path}"
    )
    print(
        "stock_codex_compat_wrapper_xcodebuild_bridge_adapter_stock_codex_version="
        f"{proof.stock_codex_version}"
    )
    print(
        "stock_codex_compat_wrapper_xcodebuild_bridge_adapter_source_bundle="
        f"{proof.source_bundle}"
    )
    print(
        "stock_codex_compat_wrapper_xcodebuild_bridge_adapter_wrapper_path="
        f"{proof.wrapper_path}"
    )
    print(
        "stock_codex_compat_wrapper_xcodebuild_bridge_adapter_codex_home="
        f"{proof.codex_home}"
    )
    print(
        "stock_codex_compat_wrapper_xcodebuild_bridge_adapter_auth_path="
        f"{proof.auth_path}"
    )
    print(
        "stock_codex_compat_wrapper_xcodebuild_bridge_adapter_bridge_dir="
        f"{proof.bridge_dir}"
    )
    print(
        "stock_codex_compat_wrapper_xcodebuild_bridge_adapter_workspace_root="
        f"{proof.workspace_root}"
    )
    print(
        "stock_codex_compat_wrapper_xcodebuild_bridge_adapter_adapter_bin="
        f"{proof.adapter_bin}"
    )
    print(
        "stock_codex_compat_wrapper_xcodebuild_bridge_adapter_adapter_manifest="
        f"{proof.adapter_manifest}"
    )
    print(
        "stock_codex_compat_wrapper_xcodebuild_bridge_adapter_adapter_bridge_dir="
        f"{proof.adapter_bridge_dir}"
    )
    print(
        "stock_codex_compat_wrapper_xcodebuild_bridge_adapter_adapter_tools="
        f"{','.join(proof.adapter_tool_names)}"
    )
    print(
        "stock_codex_compat_wrapper_xcodebuild_bridge_adapter_project_path="
        f"{proof.project_path}"
    )
    print(f"stock_codex_compat_wrapper_xcodebuild_bridge_adapter_scheme={proof.scheme}")
    print(
        "stock_codex_compat_wrapper_xcodebuild_bridge_adapter_configuration="
        f"{proof.configuration}"
    )
    print(
        "stock_codex_compat_wrapper_xcodebuild_bridge_adapter_simulator="
        f"{proof.simulator_name}"
    )
    print(
        "stock_codex_compat_wrapper_xcodebuild_bridge_adapter_derived_data="
        f"{proof.derived_data_path}"
    )
    print(f"stock_codex_compat_wrapper_xcodebuild_bridge_adapter_sandbox={proof.sandbox}")
    print(
        "stock_codex_compat_wrapper_xcodebuild_bridge_adapter_thread_id="
        f"{proof.thread_id}"
    )
    print(
        "stock_codex_compat_wrapper_xcodebuild_bridge_adapter_event_count="
        f"{proof.event_count}"
    )
    print(
        "stock_codex_compat_wrapper_xcodebuild_bridge_adapter_mcp_servers="
        f"{','.join(proof.mcp_servers)}"
    )
    print(
        "stock_codex_compat_wrapper_xcodebuild_bridge_adapter_route_injected="
        f"{proof.route_injected}"
    )
    print(
        "stock_codex_compat_wrapper_xcodebuild_bridge_adapter_evidence_path="
        f"{proof.wrapper_evidence_path}"
    )
    print(
        "stock_codex_compat_wrapper_xcodebuild_bridge_adapter_command="
        f"{_preview_text(proof.command, limit=500)!r}"
    )
    print(
        "stock_codex_compat_wrapper_xcodebuild_bridge_adapter_output_preview="
        f"{_preview_text(proof.command_output, limit=500)!r}"
    )
    print(
        "stock_codex_compat_wrapper_xcodebuild_bridge_adapter_pre_wrapper_message_preview="
        f"{_preview_text(proof.first_agent_message_before_wrapper, limit=500)!r}"
    )
    print(
        "stock_codex_compat_wrapper_xcodebuild_bridge_adapter_first_agent_message_preview="
        f"{_preview_text(proof.first_agent_message, limit=500)!r}"
    )
    print(
        "stock_codex_compat_wrapper_xcodebuild_bridge_adapter_stderr_preview="
        f"{proof.stderr_preview!r}"
    )
    print(
        "stock_codex_compat_wrapper_xcodebuild_bridge_adapter_cache_lifecycle="
        "temporary_removed_after_proof"
    )
    print(
        "ASSERTION: stock Codex ran the generated XcodeBuildMCP adapter command "
        "under workspace-write, not danger-full-access"
    )
    print(
        "ASSERTION: XcodeBuildMCP build/install/launch execution happened "
        "through the Omnigent-owned file bridge outside the stock Codex sandbox"
    )
    print(
        "ASSERTION: the Omnigent wrapper still prefixed deterministic route "
        "evidence before the final visible XcodeBuildMCP bridge-adapter answer"
    )


def print_stock_codex_compat_wrapper_relay_tool_proof(
    proof: StockCodexCompatWrapperRelayToolProof,
) -> None:
    """Emit operator evidence for wrapped stock Codex Omnigent relay tool execution."""
    print("stock_codex_compat_wrapper_relay_tool_rehearsal=selected")
    print(
        "stock_codex_compat_wrapper_relay_tool_surface="
        "stock-codex-exec-json-omnigent-mcp-relay-tool"
    )
    print(f"stock_codex_compat_wrapper_relay_tool_stock_codex_path={proof.stock_codex_path}")
    print(
        "stock_codex_compat_wrapper_relay_tool_stock_codex_version="
        f"{proof.stock_codex_version}"
    )
    print(f"stock_codex_compat_wrapper_relay_tool_source_bundle={proof.source_bundle}")
    print(f"stock_codex_compat_wrapper_relay_tool_wrapper_path={proof.wrapper_path}")
    print(f"stock_codex_compat_wrapper_relay_tool_codex_home={proof.codex_home}")
    print(f"stock_codex_compat_wrapper_relay_tool_auth_path={proof.auth_path}")
    print(f"stock_codex_compat_wrapper_relay_tool_bridge_dir={proof.bridge_dir}")
    print(f"stock_codex_compat_wrapper_relay_tool_workspace_root={proof.workspace_root}")
    print(f"stock_codex_compat_wrapper_relay_tool_thread_id={proof.thread_id}")
    print(f"stock_codex_compat_wrapper_relay_tool_event_count={proof.event_count}")
    print(
        "stock_codex_compat_wrapper_relay_tool_mcp_servers="
        f"{','.join(proof.mcp_servers)}"
    )
    print(f"stock_codex_compat_wrapper_relay_tool_route_injected={proof.route_injected}")
    print(f"stock_codex_compat_wrapper_relay_tool_evidence_path={proof.wrapper_evidence_path}")
    print(f"stock_codex_compat_wrapper_relay_tool_name={proof.relay_tool_name}")
    print(
        "stock_codex_compat_wrapper_relay_tool_arguments="
        f"{json.dumps(proof.relay_tool_arguments, sort_keys=True)}"
    )
    print(
        "stock_codex_compat_wrapper_relay_tool_event_types="
        f"{','.join(proof.relay_event_types)}"
    )
    print(
        "stock_codex_compat_wrapper_relay_tool_enabled_features="
        f"{','.join(proof.enabled_features)}"
    )
    print(
        "stock_codex_compat_wrapper_relay_tool_skipped_features_requiring_nondefault_support="
        f"{','.join(proof.skipped_features)}"
    )
    print(
        "stock_codex_compat_wrapper_relay_tool_prompt_input_mentions_tool="
        f"{proof.prompt_input_mentions_relay_tool}"
    )
    print(
        "stock_codex_compat_wrapper_relay_tool_prompt_input_preview="
        f"{proof.prompt_input_preview!r}"
    )
    print(
        "stock_codex_compat_wrapper_relay_tool_output_preview="
        f"{proof.relay_output_preview!r}"
    )
    print(
        "stock_codex_compat_wrapper_relay_tool_pre_wrapper_message_preview="
        f"{_preview_text(proof.first_agent_message_before_wrapper, limit=500)!r}"
    )
    print(
        "stock_codex_compat_wrapper_relay_tool_first_agent_message_preview="
        f"{_preview_text(proof.first_agent_message, limit=500)!r}"
    )
    print(f"stock_codex_compat_wrapper_relay_tool_stderr_preview={proof.stderr_preview!r}")
    print("stock_codex_compat_wrapper_relay_tool_cache_lifecycle=temporary_removed_after_proof")
    print(
        "ASSERTION: wrapped stock Codex executed one Omnigent MCP relay tool "
        "advertised from tool_relay.json"
    )
    print(
        "ASSERTION: the Omnigent wrapper preserved stock Codex JSONL tool "
        "evidence while prefixing deterministic route evidence"
    )


def _load_stock_codex_compat_launcher_installer() -> Any:
    """Load the stock-Codex compatibility launcher installer script."""
    script_path = Path(__file__).resolve().with_name(
        "install_stock_codex_compat_launcher.py"
    )
    spec = importlib.util.spec_from_file_location(
        "omnigent_stock_codex_compat_launcher_installer",
        script_path,
    )
    if spec is None or spec.loader is None:
        raise SystemExit(f"Could not load compatibility launcher installer: {script_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def run_stock_codex_compat_launcher_doctor_proof(
    stock_codex_path: Path,
    *,
    launcher_path: Path | None = None,
    manifest_path: Path | None = None,
    uvx_path: Path | None = None,
    backup_existing: bool = False,
    force: bool = False,
    require_path_selected: bool = False,
) -> StockCodexCompatLauncherDoctorProof:
    """Prove the compatibility launcher install plan without mutating the host."""
    stock_codex_path = stock_codex_path.expanduser().resolve()
    assert_stock_codex_path(stock_codex_path, allow_fork_codex=False)

    installer = _load_stock_codex_compat_launcher_installer()
    uvx_path = uvx_path.expanduser().resolve() if uvx_path else None
    if uvx_path is None:
        uvx_raw = shutil.which("uvx")
        if not uvx_raw:
            raise SystemExit("Could not find uvx on PATH for compatibility launcher doctor.")
        uvx_path = Path(uvx_raw).expanduser().resolve()
    if not uvx_path.is_file() or not os.access(uvx_path, os.X_OK):
        raise SystemExit(f"uvx binary is not executable: {uvx_path}")

    repo_root = Path(__file__).resolve().parents[1]
    launcher_path = (
        launcher_path.expanduser()
        if launcher_path is not None
        else installer.DEFAULT_LAUNCHER_PATH
    )
    manifest_path = (
        manifest_path.expanduser()
        if manifest_path is not None
        else installer.DEFAULT_MANIFEST_PATH
    )
    with tempfile.TemporaryDirectory(
        prefix="omnigent-stock-codex-compat-launcher-doctor-"
    ) as temp_root:
        root = Path(temp_root).resolve()
        adapter_package_dir = root / "adapter-package"
        installer.materialize_default_adapter_package(
            adapter_package_dir,
            force=False,
        )
        adapter_bin, adapter_manifest = installer.resolve_adapter_paths(
            adapter_bin=None,
            adapter_manifest=None,
            adapter_package_dir=adapter_package_dir,
        )
        doctor = installer.doctor_launcher(
            launcher_path=launcher_path,
            manifest_path=manifest_path,
            repo_root=repo_root,
            uvx_path=uvx_path,
            pinned_codex_path=stock_codex_path,
            route_prefix=EXPECTED_ROUTE,
            adapter_bin=adapter_bin,
            adapter_manifest=adapter_manifest,
            adapter_bridge_dir=installer.DEFAULT_ADAPTER_BRIDGE_DIR,
            backup_existing=backup_existing,
            force=force,
            require_path_selected=require_path_selected,
        )
        if doctor.mutates_filesystem:
            raise SystemExit("Compatibility launcher doctor unexpectedly mutates files.")
        if doctor.pinned_codex_path != stock_codex_path:
            raise SystemExit(
                "Compatibility launcher doctor resolved the wrong pinned Codex.\n"
                f"expected={stock_codex_path}\nactual={doctor.pinned_codex_path}"
            )
        return StockCodexCompatLauncherDoctorProof(
            stock_codex_path=stock_codex_path,
            stock_codex_version=doctor.pinned_codex_version,
            launcher_path=doctor.launcher_path,
            manifest_path=doctor.manifest_path,
            repo_root=doctor.repo_root,
            uvx_path=doctor.uvx_path,
            adapter_bin=doctor.adapter_bin,
            adapter_manifest=doctor.adapter_manifest,
            adapter_bridge_dir=doctor.adapter_bridge_dir,
            adapter_package_dir=adapter_package_dir,
            adapter_tool_names=doctor.adapter_tool_names,
            install_allowed=doctor.install_allowed,
            install_blocker=doctor.install_blocker,
            existing_target_state=doctor.existing_target_state,
            existing_target_managed=doctor.existing_target_managed,
            existing_target_realpath=doctor.existing_target_realpath,
            selected_command_path=doctor.selected_command_path,
            target_selected_on_path=doctor.target_selected_on_path,
            launcher_parent_on_path=doctor.launcher_parent_on_path,
            launcher_parent_exists=doctor.launcher_parent_exists,
            nearest_existing_parent=doctor.nearest_existing_parent,
            nearest_existing_parent_writable=doctor.nearest_existing_parent_writable,
            backup_existing_requested=doctor.backup_existing_requested,
            force_requested=doctor.force_requested,
            would_backup_existing=doctor.would_backup_existing,
            backup_path=doctor.backup_path,
            rollback_command=doctor.rollback_command,
            install_command=doctor.install_command,
            mutates_filesystem=doctor.mutates_filesystem,
        )


def print_stock_codex_compat_launcher_doctor_proof(
    proof: StockCodexCompatLauncherDoctorProof,
) -> None:
    """Emit operator evidence for the compatibility launcher install plan."""
    print("stock_codex_compat_launcher_doctor_rehearsal=selected")
    print(
        "stock_codex_compat_launcher_doctor_surface="
        "non-mutating-managed-compatibility-launcher-install-plan"
    )
    print(f"stock_codex_compat_launcher_doctor_launcher_path={proof.launcher_path}")
    print(f"stock_codex_compat_launcher_doctor_manifest_path={proof.manifest_path}")
    print(f"stock_codex_compat_launcher_doctor_stock_codex_path={proof.stock_codex_path}")
    print(
        "stock_codex_compat_launcher_doctor_stock_codex_version="
        f"{proof.stock_codex_version}"
    )
    print(f"stock_codex_compat_launcher_doctor_repo_root={proof.repo_root}")
    print(f"stock_codex_compat_launcher_doctor_uvx_path={proof.uvx_path}")
    print(f"stock_codex_compat_launcher_doctor_adapter_bin={proof.adapter_bin}")
    print(
        "stock_codex_compat_launcher_doctor_adapter_manifest="
        f"{proof.adapter_manifest}"
    )
    print(
        "stock_codex_compat_launcher_doctor_adapter_package_dir="
        f"{proof.adapter_package_dir}"
    )
    print(
        "stock_codex_compat_launcher_doctor_adapter_bridge_dir="
        f"{proof.adapter_bridge_dir}"
    )
    print(
        "stock_codex_compat_launcher_doctor_adapter_tools="
        f"{','.join(proof.adapter_tool_names)}"
    )
    print(
        "stock_codex_compat_launcher_doctor_install_allowed="
        f"{proof.install_allowed}"
    )
    if proof.install_blocker is not None:
        print(
            "stock_codex_compat_launcher_doctor_install_blocker="
            f"{proof.install_blocker}"
        )
    print(
        "stock_codex_compat_launcher_doctor_existing_target_state="
        f"{proof.existing_target_state}"
    )
    print(
        "stock_codex_compat_launcher_doctor_existing_target_managed="
        f"{proof.existing_target_managed}"
    )
    if proof.existing_target_realpath is not None:
        print(
            "stock_codex_compat_launcher_doctor_existing_target_realpath="
            f"{proof.existing_target_realpath}"
        )
    if proof.selected_command_path is not None:
        print(
            "stock_codex_compat_launcher_doctor_selected_command_path="
            f"{proof.selected_command_path}"
        )
    print(
        "stock_codex_compat_launcher_doctor_target_selected_on_path="
        f"{proof.target_selected_on_path}"
    )
    print(
        "stock_codex_compat_launcher_doctor_launcher_parent_on_path="
        f"{proof.launcher_parent_on_path}"
    )
    print(
        "stock_codex_compat_launcher_doctor_launcher_parent_exists="
        f"{proof.launcher_parent_exists}"
    )
    print(
        "stock_codex_compat_launcher_doctor_nearest_existing_parent="
        f"{proof.nearest_existing_parent}"
    )
    print(
        "stock_codex_compat_launcher_doctor_nearest_existing_parent_writable="
        f"{proof.nearest_existing_parent_writable}"
    )
    print(
        "stock_codex_compat_launcher_doctor_backup_existing_requested="
        f"{proof.backup_existing_requested}"
    )
    print(f"stock_codex_compat_launcher_doctor_force_requested={proof.force_requested}")
    print(
        "stock_codex_compat_launcher_doctor_would_backup_existing="
        f"{proof.would_backup_existing}"
    )
    if proof.backup_path is not None:
        print(f"stock_codex_compat_launcher_doctor_backup_path={proof.backup_path}")
    print(
        "stock_codex_compat_launcher_doctor_mutates_filesystem="
        f"{proof.mutates_filesystem}"
    )
    print(
        "stock_codex_compat_launcher_doctor_rollback_command="
        f"{proof.rollback_command}"
    )
    print(
        "stock_codex_compat_launcher_doctor_install_command="
        f"{proof.install_command}"
    )
    print(
        "stock_codex_compat_launcher_doctor_cache_lifecycle="
        "temporary_default_layout_adapter_package_removed_after_proof"
    )
    print(
        "ASSERTION: compatibility launcher doctor validates the target, pinned "
        "stock Codex, uvx, adapter manifest, PATH posture, and rollback command "
        "without creating or replacing launcher files"
    )
    print(
        "ASSERTION: this proof preserves the Codex fork and current host launcher "
        "state; it is a production-install readiness gate, not an install"
    )


def _run_stock_codex_compat_installer_cli_json(
    args: list[str],
    *,
    env: dict[str, str],
    repo_root: Path,
    script_path: Path | None = None,
) -> dict[str, Any]:
    """Run the compatibility launcher installer CLI and return its JSON output."""
    script_path = script_path or (
        repo_root / "scripts" / "install_stock_codex_compat_launcher.py"
    )
    completed = subprocess.run(
        [sys.executable, str(script_path), *args, "--json"],
        check=False,
        capture_output=True,
        text=True,
        cwd=repo_root,
        env=env,
        timeout=30,
    )
    if completed.returncode != 0:
        raise SystemExit(
            "Compatibility installer command failed.\n"
            f"args={args!r}\n"
            f"exit={completed.returncode}\n"
            f"stdout={completed.stdout}\n"
            f"stderr={completed.stderr}"
        )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise SystemExit(
            "Compatibility installer command did not emit JSON.\n"
            f"args={args!r}\n"
            f"stdout={completed.stdout}\n"
            f"stderr={completed.stderr}"
        ) from exc
    if not isinstance(payload, dict):
        raise SystemExit(
            "Compatibility installer command emitted non-object JSON.\n"
            f"args={args!r}\n"
            f"payload={payload!r}"
        )
    return payload


def _run_stock_codex_compat_bundle_builder_cli_json(
    args: list[str],
    *,
    repo_root: Path,
) -> dict[str, Any]:
    """Run the compatibility bundle builder CLI and return its JSON output."""
    script_path = repo_root / "scripts" / "build_stock_codex_compat_bundle.py"
    completed = subprocess.run(
        [sys.executable, str(script_path), *args, "--json"],
        check=False,
        capture_output=True,
        text=True,
        cwd=repo_root,
        timeout=60,
    )
    if completed.returncode != 0:
        raise SystemExit(
            "Compatibility bundle build command failed.\n"
            f"args={args!r}\n"
            f"exit={completed.returncode}\n"
            f"stdout={completed.stdout}\n"
            f"stderr={completed.stderr}"
        )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise SystemExit(
            "Compatibility bundle build command did not emit JSON.\n"
            f"args={args!r}\n"
            f"stdout={completed.stdout}\n"
            f"stderr={completed.stderr}"
        ) from exc
    if not isinstance(payload, dict):
        raise SystemExit(
            "Compatibility bundle build command emitted non-object JSON.\n"
            f"args={args!r}\n"
            f"payload={payload!r}"
        )
    return payload


def _run_stock_codex_compat_pkg_builder_cli_json(
    args: list[str],
    *,
    repo_root: Path,
) -> dict[str, Any]:
    """Run the compatibility pkg builder CLI and return its JSON output."""
    script_path = repo_root / "scripts" / "build_stock_codex_compat_pkg.py"
    completed = subprocess.run(
        [sys.executable, str(script_path), *args, "--json"],
        check=False,
        capture_output=True,
        text=True,
        cwd=repo_root,
        timeout=240,
    )
    if completed.returncode != 0:
        raise SystemExit(
            "Compatibility pkg build command failed.\n"
            f"args={args!r}\n"
            f"exit={completed.returncode}\n"
            f"stdout={completed.stdout}\n"
            f"stderr={completed.stderr}"
        )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise SystemExit(
            "Compatibility pkg build command did not emit JSON.\n"
            f"args={args!r}\n"
            f"stdout={completed.stdout}\n"
            f"stderr={completed.stderr}"
        ) from exc
    if not isinstance(payload, dict):
        raise SystemExit(
            "Compatibility pkg build command emitted non-object JSON.\n"
            f"args={args!r}\n"
            f"payload={payload!r}"
        )
    return payload


def _safe_extract_tar_gz(archive_path: Path, destination: Path) -> None:
    """Extract a tar.gz archive while rejecting path traversal entries."""
    destination = destination.expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive_path, "r:gz") as archive:
        for member in archive.getmembers():
            target = (destination / member.name).resolve()
            if target != destination and not str(target).startswith(
                f"{destination}{os.sep}"
            ):
                raise SystemExit(
                    "Compatibility bundle contains unsafe archive member: "
                    f"{member.name!r}"
                )
            if member.isdev():
                raise SystemExit(
                    "Compatibility bundle contains unsupported device member: "
                    f"{member.name!r}"
                )
        archive.extractall(destination)


def run_stock_codex_compat_clean_install_proof(
    stock_codex_path: Path,
    *,
    uvx_path: Path | None = None,
) -> StockCodexCompatCleanInstallProof:
    """Prove the compatibility launcher install sequence under a clean HOME."""
    stock_codex_path = stock_codex_path.expanduser().resolve()
    assert_stock_codex_path(stock_codex_path, allow_fork_codex=False)
    stock_codex_version = codex_version(stock_codex_path)
    uvx_path = uvx_path.expanduser().resolve() if uvx_path is not None else None
    if uvx_path is None:
        uvx_raw = shutil.which("uvx")
        if not uvx_raw:
            raise SystemExit("Could not find uvx on PATH for clean install proof.")
        uvx_path = Path(uvx_raw).expanduser().resolve()
    if not uvx_path.is_file() or not os.access(uvx_path, os.X_OK):
        raise SystemExit(f"uvx binary is not executable: {uvx_path}")

    repo_root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(
        prefix="omnigent-stock-codex-compat-clean-install-"
    ) as temp_root:
        root = Path(temp_root).resolve()
        clean_home = root / "home"
        clean_tmp = root / "tmp"
        clean_home.mkdir()
        clean_tmp.mkdir()
        clean_bin_dir = clean_home / ".local" / "bin"
        launcher_path = clean_bin_dir / "omnigent-stock-codex-compat"
        manifest_path = (
            clean_home / ".local" / "omnigent" / "launchers" / "stock-codex-compat.json"
        )
        adapter_package_dir = (
            clean_home / ".local" / "omnigent" / "stock-codex-compat" / "adapter-package"
        )
        adapter_bridge_dir = (
            clean_home / ".local" / "omnigent" / "stock-codex-compat" / "adapter-bridge"
        )
        proof_path = (
            f"{clean_bin_dir}{os.pathsep}{uvx_path.parent}{os.pathsep}"
            f"{os.environ.get('PATH', '')}"
        )
        python_path = str(repo_root)
        if os.environ.get("PYTHONPATH"):
            python_path = f"{python_path}{os.pathsep}{os.environ['PYTHONPATH']}"
        env = os.environ.copy()
        env.update(
            {
                "HOME": str(clean_home),
                "TMPDIR": str(clean_tmp),
                "PATH": proof_path,
                "PYTHONPATH": python_path,
            }
        )
        env.pop("CODEX_HOME", None)
        env.pop(OMNIGENT_STOCK_CODEX_PATH_ENV, None)

        adapter_payload = _run_stock_codex_compat_installer_cli_json(
            ["--install-adapter-package"],
            env=env,
            repo_root=repo_root,
        )
        install_payload = _run_stock_codex_compat_installer_cli_json(
            [
                "--install",
                "--pinned-codex-path",
                str(stock_codex_path),
                "--repo-root",
                str(repo_root),
                "--uvx-path",
                str(uvx_path),
                "--require-path-selected",
            ],
            env=env,
            repo_root=repo_root,
        )
        selected = shutil.which("omnigent-stock-codex-compat", path=env["PATH"])
        if selected is None:
            raise SystemExit("Clean install proof did not select compatibility command.")
        selected_command_path = Path(selected).expanduser().resolve()
        if selected_command_path != launcher_path.resolve():
            raise SystemExit(
                "Clean install proof selected the wrong compatibility command.\n"
                f"expected={launcher_path.resolve()}\nactual={selected_command_path}"
            )
        version = subprocess.run(
            [str(selected_command_path), "--version"],
            check=False,
            capture_output=True,
            text=True,
            env=env,
            timeout=10,
        )
        version_output = (version.stdout or version.stderr).strip()
        if version.returncode != 0 or version_output != stock_codex_version:
            raise SystemExit(
                "Clean install proof version delegation failed.\n"
                f"expected={stock_codex_version!r}\nactual={version_output!r}\n"
                f"exit={version.returncode}"
            )
        probe = subprocess.run(
            [str(selected_command_path), "--omnigent-stock-codex-compat-launcher-probe"],
            check=False,
            capture_output=True,
            text=True,
            env=env,
            timeout=10,
        )
        probe_output = ((probe.stdout or "") + (probe.stderr or "")).strip()
        if probe.returncode != 0 or "OMNIGENT_STOCK_CODEX_COMPAT_LAUNCHER_OK" not in (
            probe_output
        ):
            raise SystemExit(
                "Clean install proof launcher probe failed.\n"
                f"exit={probe.returncode}\noutput={probe_output}"
            )
        doctor_payload = _run_stock_codex_compat_installer_cli_json(
            [
                "--doctor",
                "--pinned-codex-path",
                str(stock_codex_path),
                "--repo-root",
                str(repo_root),
                "--uvx-path",
                str(uvx_path),
                "--require-path-selected",
                "--force",
            ],
            env=env,
            repo_root=repo_root,
        )
        if doctor_payload.get("installAllowed") is not True:
            raise SystemExit(f"Clean install doctor did not allow reinstall: {doctor_payload!r}")
        if doctor_payload.get("targetSelectedOnPath") is not True:
            raise SystemExit(
                f"Clean install doctor did not see PATH selection: {doctor_payload!r}"
            )
        if doctor_payload.get("mutatesFilesystem") is not False:
            raise SystemExit(f"Clean install doctor unexpectedly mutates: {doctor_payload!r}")

        rollback_payload = _run_stock_codex_compat_installer_cli_json(
            ["--uninstall"],
            env=env,
            repo_root=repo_root,
        )
        launcher_removed = not launcher_path.exists()
        manifest_removed = not manifest_path.exists()
        if not launcher_removed or not manifest_removed:
            raise SystemExit(
                "Clean install rollback left launcher artifacts behind.\n"
                f"launcher_exists={launcher_path.exists()}\n"
                f"manifest_exists={manifest_path.exists()}"
            )

        return StockCodexCompatCleanInstallProof(
            stock_codex_path=stock_codex_path,
            stock_codex_version=stock_codex_version,
            clean_home=clean_home,
            clean_bin_dir=clean_bin_dir,
            launcher_path=launcher_path,
            manifest_path=manifest_path,
            adapter_package_dir=adapter_package_dir,
            adapter_bin=Path(str(adapter_payload["adapterBin"])),
            adapter_manifest=Path(str(adapter_payload["adapterManifest"])),
            adapter_bridge_dir=adapter_bridge_dir,
            adapter_tool_names=tuple(
                str(name) for name in adapter_payload.get("adapterToolNames", [])
            ),
            repo_root=repo_root,
            uvx_path=uvx_path,
            selected_command_path=selected_command_path,
            version_output=version_output,
            probe_output=probe_output,
            adapter_package_action=str(adapter_payload["action"]),
            install_action=str(install_payload["action"]),
            rollback_action=str(rollback_payload["action"]),
            doctor_install_allowed=bool(doctor_payload["installAllowed"]),
            doctor_existing_target_state=str(doctor_payload["existingTargetState"]),
            doctor_existing_target_managed=bool(doctor_payload["existingTargetManaged"]),
            doctor_target_selected_on_path=bool(doctor_payload["targetSelectedOnPath"]),
            doctor_mutates_filesystem=bool(doctor_payload["mutatesFilesystem"]),
            launcher_removed_after_rollback=launcher_removed,
            manifest_removed_after_rollback=manifest_removed,
        )


def run_stock_codex_compat_bundle_install_proof(
    stock_codex_path: Path,
    *,
    uvx_path: Path | None = None,
) -> StockCodexCompatBundleInstallProof:
    """Prove clean-home install from a portable compatibility bundle artifact."""
    stock_codex_path = stock_codex_path.expanduser().resolve()
    assert_stock_codex_path(stock_codex_path, allow_fork_codex=False)
    stock_codex_version = codex_version(stock_codex_path)
    uvx_path = uvx_path.expanduser().resolve() if uvx_path is not None else None
    if uvx_path is None:
        uvx_raw = shutil.which("uvx")
        if not uvx_raw:
            raise SystemExit("Could not find uvx on PATH for bundle install proof.")
        uvx_path = Path(uvx_raw).expanduser().resolve()
    if not uvx_path.is_file() or not os.access(uvx_path, os.X_OK):
        raise SystemExit(f"uvx binary is not executable: {uvx_path}")

    source_repo_root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(
        prefix="omnigent-stock-codex-compat-bundle-install-"
    ) as temp_root:
        root = Path(temp_root).resolve()
        clean_home = root / "home"
        clean_tmp = root / "tmp"
        artifact_dir = root / "artifacts"
        extract_dir = root / "extract"
        clean_home.mkdir()
        clean_tmp.mkdir()
        artifact_dir.mkdir()
        bundle_path = artifact_dir / "omnigent-stock-codex-compat-bundle.tar.gz"
        bundle_payload = _run_stock_codex_compat_bundle_builder_cli_json(
            [
                "--repo-root",
                str(source_repo_root),
                "--output",
                str(bundle_path),
                "--force",
            ],
            repo_root=source_repo_root,
        )
        bundle_path = Path(_json_string(bundle_payload, "bundlePath")).resolve()
        bundle_sha256 = _json_string(bundle_payload, "sha256")
        if sha256_file(bundle_path) != bundle_sha256:
            raise SystemExit(
                "Compatibility bundle digest mismatch after build.\n"
                f"bundle={bundle_path}\nexpected={bundle_sha256}"
            )

        _safe_extract_tar_gz(bundle_path, extract_dir)
        bundle_root_name = _json_string(bundle_payload, "bundleRootName")
        manifest_name = _json_string(bundle_payload, "manifestName")
        extracted_bundle_root = extract_dir / bundle_root_name
        bundle_manifest_path = extracted_bundle_root / manifest_name
        if not bundle_manifest_path.is_file():
            raise SystemExit(
                f"Extracted compatibility bundle manifest is missing: {bundle_manifest_path}"
            )
        bundle_manifest = json.loads(bundle_manifest_path.read_text(encoding="utf-8"))
        if bundle_manifest.get("kind") != "omnigent-stock-codex-compat-bundle":
            raise SystemExit(f"Compatibility bundle manifest kind mismatch: {bundle_manifest!r}")
        runtime_root_raw = bundle_manifest.get("runtimeRoot")
        installer_raw = bundle_manifest.get("installer")
        if not isinstance(runtime_root_raw, str) or not runtime_root_raw:
            raise SystemExit(f"Compatibility bundle omitted runtimeRoot: {bundle_manifest!r}")
        if not isinstance(installer_raw, str) or not installer_raw:
            raise SystemExit(f"Compatibility bundle omitted installer: {bundle_manifest!r}")
        extracted_runtime_root = (extracted_bundle_root / runtime_root_raw).resolve()
        installer_script_path = (extracted_bundle_root / installer_raw).resolve()
        if extracted_runtime_root == source_repo_root.resolve():
            raise SystemExit("Compatibility bundle proof reused the development checkout.")
        if not extracted_runtime_root.is_dir():
            raise SystemExit(
                f"Extracted compatibility runtime root is missing: {extracted_runtime_root}"
            )
        if not installer_script_path.is_file():
            raise SystemExit(
                f"Extracted compatibility installer is missing: {installer_script_path}"
            )

        clean_bin_dir = clean_home / ".local" / "bin"
        launcher_path = clean_bin_dir / "omnigent-stock-codex-compat"
        manifest_path = (
            clean_home / ".local" / "omnigent" / "launchers" / "stock-codex-compat.json"
        )
        adapter_package_dir = (
            clean_home / ".local" / "omnigent" / "stock-codex-compat" / "adapter-package"
        )
        adapter_bridge_dir = (
            clean_home / ".local" / "omnigent" / "stock-codex-compat" / "adapter-bridge"
        )
        proof_path = (
            f"{clean_bin_dir}{os.pathsep}{uvx_path.parent}{os.pathsep}"
            f"{os.environ.get('PATH', '')}"
        )
        python_path = str(extracted_runtime_root)
        if os.environ.get("PYTHONPATH"):
            python_path = f"{python_path}{os.pathsep}{os.environ['PYTHONPATH']}"
        env = os.environ.copy()
        env.update(
            {
                "HOME": str(clean_home),
                "TMPDIR": str(clean_tmp),
                "PATH": proof_path,
                "PYTHONPATH": python_path,
            }
        )
        env.pop("CODEX_HOME", None)
        env.pop(OMNIGENT_STOCK_CODEX_PATH_ENV, None)

        adapter_payload = _run_stock_codex_compat_installer_cli_json(
            ["--install-adapter-package"],
            env=env,
            repo_root=extracted_runtime_root,
            script_path=installer_script_path,
        )
        install_payload = _run_stock_codex_compat_installer_cli_json(
            [
                "--install",
                "--pinned-codex-path",
                str(stock_codex_path),
                "--repo-root",
                str(extracted_runtime_root),
                "--uvx-path",
                str(uvx_path),
                "--require-path-selected",
            ],
            env=env,
            repo_root=extracted_runtime_root,
            script_path=installer_script_path,
        )
        launcher_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        launcher_repo_root_raw = launcher_manifest.get("repoRoot")
        if not isinstance(launcher_repo_root_raw, str) or not launcher_repo_root_raw:
            raise SystemExit(
                f"Installed launcher manifest omitted repoRoot: {launcher_manifest!r}"
            )
        launcher_manifest_repo_root = Path(launcher_repo_root_raw).expanduser().resolve()
        if launcher_manifest_repo_root != extracted_runtime_root:
            raise SystemExit(
                "Bundle install wrote the wrong runtime root into the launcher manifest.\n"
                f"expected={extracted_runtime_root}\nactual={launcher_manifest_repo_root}"
            )

        selected = shutil.which("omnigent-stock-codex-compat", path=env["PATH"])
        if selected is None:
            raise SystemExit("Bundle install proof did not select compatibility command.")
        selected_command_path = Path(selected).expanduser().resolve()
        if selected_command_path != launcher_path.resolve():
            raise SystemExit(
                "Bundle install proof selected the wrong compatibility command.\n"
                f"expected={launcher_path.resolve()}\nactual={selected_command_path}"
            )
        version = subprocess.run(
            [str(selected_command_path), "--version"],
            check=False,
            capture_output=True,
            text=True,
            env=env,
            timeout=10,
        )
        version_output = (version.stdout or version.stderr).strip()
        if version.returncode != 0 or version_output != stock_codex_version:
            raise SystemExit(
                "Bundle install proof version delegation failed.\n"
                f"expected={stock_codex_version!r}\nactual={version_output!r}\n"
                f"exit={version.returncode}"
            )
        probe = subprocess.run(
            [str(selected_command_path), "--omnigent-stock-codex-compat-launcher-probe"],
            check=False,
            capture_output=True,
            text=True,
            env=env,
            timeout=10,
        )
        probe_output = ((probe.stdout or "") + (probe.stderr or "")).strip()
        if probe.returncode != 0 or "OMNIGENT_STOCK_CODEX_COMPAT_LAUNCHER_OK" not in (
            probe_output
        ):
            raise SystemExit(
                "Bundle install proof launcher probe failed.\n"
                f"exit={probe.returncode}\noutput={probe_output}"
            )
        if str(extracted_runtime_root) not in probe_output:
            raise SystemExit(
                "Bundle install proof launcher probe did not delegate to extracted runtime.\n"
                f"expected_runtime={extracted_runtime_root}\noutput={probe_output}"
            )

        doctor_payload = _run_stock_codex_compat_installer_cli_json(
            [
                "--doctor",
                "--pinned-codex-path",
                str(stock_codex_path),
                "--repo-root",
                str(extracted_runtime_root),
                "--uvx-path",
                str(uvx_path),
                "--require-path-selected",
                "--force",
            ],
            env=env,
            repo_root=extracted_runtime_root,
            script_path=installer_script_path,
        )
        if doctor_payload.get("installAllowed") is not True:
            raise SystemExit(f"Bundle install doctor did not allow reinstall: {doctor_payload!r}")
        if doctor_payload.get("targetSelectedOnPath") is not True:
            raise SystemExit(
                f"Bundle install doctor did not see PATH selection: {doctor_payload!r}"
            )
        if doctor_payload.get("mutatesFilesystem") is not False:
            raise SystemExit(f"Bundle install doctor unexpectedly mutates: {doctor_payload!r}")

        rollback_payload = _run_stock_codex_compat_installer_cli_json(
            ["--uninstall"],
            env=env,
            repo_root=extracted_runtime_root,
            script_path=installer_script_path,
        )
        launcher_removed = not launcher_path.exists()
        manifest_removed = not manifest_path.exists()
        if not launcher_removed or not manifest_removed:
            raise SystemExit(
                "Bundle install rollback left launcher artifacts behind.\n"
                f"launcher_exists={launcher_path.exists()}\n"
                f"manifest_exists={manifest_path.exists()}"
            )

        return StockCodexCompatBundleInstallProof(
            stock_codex_path=stock_codex_path,
            stock_codex_version=stock_codex_version,
            bundle_path=bundle_path,
            bundle_sha256=bundle_sha256,
            bundle_manifest_path=bundle_manifest_path,
            extracted_bundle_root=extracted_bundle_root,
            extracted_runtime_root=extracted_runtime_root,
            installer_script_path=installer_script_path,
            clean_home=clean_home,
            clean_bin_dir=clean_bin_dir,
            launcher_path=launcher_path,
            manifest_path=manifest_path,
            adapter_package_dir=adapter_package_dir,
            adapter_bin=Path(str(adapter_payload["adapterBin"])),
            adapter_manifest=Path(str(adapter_payload["adapterManifest"])),
            adapter_bridge_dir=adapter_bridge_dir,
            adapter_tool_names=tuple(
                str(name) for name in adapter_payload.get("adapterToolNames", [])
            ),
            uvx_path=uvx_path,
            selected_command_path=selected_command_path,
            launcher_manifest_repo_root=launcher_manifest_repo_root,
            version_output=version_output,
            probe_output=probe_output,
            adapter_package_action=str(adapter_payload["action"]),
            install_action=str(install_payload["action"]),
            rollback_action=str(rollback_payload["action"]),
            doctor_install_allowed=bool(doctor_payload["installAllowed"]),
            doctor_existing_target_state=str(doctor_payload["existingTargetState"]),
            doctor_existing_target_managed=bool(doctor_payload["existingTargetManaged"]),
            doctor_target_selected_on_path=bool(doctor_payload["targetSelectedOnPath"]),
            doctor_mutates_filesystem=bool(doctor_payload["mutatesFilesystem"]),
            launcher_removed_after_rollback=launcher_removed,
            manifest_removed_after_rollback=manifest_removed,
        )


def _validate_stock_codex_compat_pkg_builder_payload(
    payload: dict[str, Any],
    *,
    source_repo_root: Path,
    expect_signed: bool = False,
) -> StockCodexCompatPkgStructureProof:
    """Validate compatibility pkg builder JSON and return common proof evidence."""
    if payload.get("kind") != "omnigent-stock-codex-compat-pkg":
        raise SystemExit(f"Compatibility pkg kind mismatch: {payload!r}")
    package_path = Path(_json_string(payload, "packagePath")).resolve()
    package_sha256 = _json_string(payload, "packageSha256")
    if sha256_file(package_path) != package_sha256:
        raise SystemExit(
            "Compatibility pkg digest mismatch after build.\n"
            f"package={package_path}\nexpected={package_sha256}"
        )
    inspection = payload.get("inspection")
    if not isinstance(inspection, dict):
        raise SystemExit(f"Compatibility pkg proof omitted inspection: {payload!r}")
    package_identifier = _json_string(payload, "packageIdentifier")
    package_version = _json_string(payload, "packageVersion")
    install_location = _json_string(payload, "installLocation")
    install_prefix = Path(_json_string(payload, "installPrefix"))
    runtime_root = Path(_json_string(payload, "runtimeRoot"))
    source_bundle_sha256 = _json_string(payload, "sourceBundleSha256")
    if len(source_bundle_sha256) != 64:
        raise SystemExit(
            "Compatibility pkg source bundle digest was not a SHA-256.\n"
            f"sourceBundleSha256={source_bundle_sha256!r}"
        )
    if package_identifier != "ai.omnigent.stock-codex-compat":
        raise SystemExit(f"Compatibility pkg identifier mismatch: {package_identifier!r}")
    if install_location != "/":
        raise SystemExit(f"Compatibility pkg install location mismatch: {install_location!r}")
    if str(install_prefix) != "/Library/Application Support/Omnigent/stock-codex-compat":
        raise SystemExit(f"Compatibility pkg install prefix mismatch: {install_prefix}")
    if str(runtime_root) != f"{install_prefix}/runtime":
        raise SystemExit(f"Compatibility pkg runtime root mismatch: {runtime_root}")
    signature_status = str(inspection.get("signatureStatus"))
    if expect_signed:
        if inspection.get("signed") is not True:
            raise SystemExit(f"Compatibility pkg was expected to be signed: {inspection!r}")
        if signature_status.lower() == "no signature":
            raise SystemExit(f"Compatibility pkg signature status mismatch: {inspection!r}")
    else:
        if inspection.get("signed") is not False:
            raise SystemExit(f"Compatibility pkg was expected to be unsigned: {inspection!r}")
        if signature_status != "no signature":
            raise SystemExit(f"Compatibility pkg signature status mismatch: {inspection!r}")
    if inspection.get("allRequiredPayloadFilesPresent") is not True:
        raise SystemExit(
            "Compatibility pkg missed required payload files.\n"
            f"required={inspection.get('requiredPayloadFiles')!r}"
        )
    script_names_raw = inspection.get("scriptNames")
    if not isinstance(script_names_raw, list) or "postinstall" not in script_names_raw:
        raise SystemExit(f"Compatibility pkg missed postinstall script: {inspection!r}")
    archive_entries_raw = inspection.get("archiveEntries")
    if not isinstance(archive_entries_raw, list):
        raise SystemExit(f"Compatibility pkg archive entries missing: {inspection!r}")
    for required_entry in ("Bom", "PackageInfo", "Payload", "Scripts"):
        if required_entry not in archive_entries_raw:
            raise SystemExit(
                "Compatibility pkg missed flat-package archive entry.\n"
                f"entry={required_entry!r}\narchive={archive_entries_raw!r}"
            )
    required_payload_raw = inspection.get("requiredPayloadFiles")
    if not isinstance(required_payload_raw, dict):
        raise SystemExit(f"Compatibility pkg required payload map missing: {inspection!r}")
    required_payload = {str(key): bool(value) for key, value in required_payload_raw.items()}
    pkg_manifest_raw = inspection.get("pkgManifest")
    bundle_manifest_raw = inspection.get("bundleManifest")
    if not isinstance(pkg_manifest_raw, dict):
        raise SystemExit(f"Compatibility pkg manifest missing: {inspection!r}")
    if not isinstance(bundle_manifest_raw, dict):
        raise SystemExit(f"Compatibility bundle manifest missing: {inspection!r}")
    pkg_contract_raw = pkg_manifest_raw.get("contract")
    if not isinstance(pkg_contract_raw, dict):
        raise SystemExit(f"Compatibility pkg contract missing: {pkg_manifest_raw!r}")
    if pkg_contract_raw.get("runtime") != "machine-level-runtime-only":
        raise SystemExit(f"Compatibility pkg runtime contract mismatch: {pkg_contract_raw!r}")
    if pkg_contract_raw.get("userBootstrap") != "deferred-to-installed-runtime-command":
        raise SystemExit(
            f"Compatibility pkg bootstrap contract mismatch: {pkg_contract_raw!r}"
        )
    bundle_source_root = bundle_manifest_raw.get("sourceRoot")
    if bundle_source_root != "<omitted-from-pkg>":
        raise SystemExit(
            "Compatibility pkg should not embed the development checkout path in "
            f"bundle-manifest.json: {bundle_manifest_raw!r}"
        )
    source_root_text = str(source_repo_root)
    manifest_text = json.dumps(
        {"pkgManifest": pkg_manifest_raw, "bundleManifest": bundle_manifest_raw},
        sort_keys=True,
    )
    if source_root_text in manifest_text:
        raise SystemExit(
            "Compatibility pkg manifests embedded the development checkout path.\n"
            f"source_root={source_root_text}"
        )
    payload_file_count_raw = inspection.get("payloadFileCount")
    if not isinstance(payload_file_count_raw, int) or payload_file_count_raw <= 0:
        raise SystemExit(f"Compatibility pkg payload file count invalid: {inspection!r}")

    return StockCodexCompatPkgStructureProof(
        package_path=package_path,
        package_sha256=package_sha256,
        source_bundle_sha256=source_bundle_sha256,
        package_identifier=package_identifier,
        package_version=package_version,
        install_location=install_location,
        install_prefix=install_prefix,
        runtime_root=runtime_root,
        payload_file_count=payload_file_count_raw,
        required_payload_files=required_payload,
        script_names=tuple(str(name) for name in script_names_raw),
        archive_entries=tuple(str(entry) for entry in archive_entries_raw),
        signature_status=signature_status,
        signed=bool(inspection.get("signed")),
        pkg_manifest_path=Path(_json_string(inspection, "pkgManifestPath")),
        bundle_manifest_path=Path(_json_string(inspection, "bundleManifestPath")),
        pkg_contract={str(key): value for key, value in pkg_contract_raw.items()},
        bundle_source_root=str(bundle_source_root),
    )


def run_stock_codex_compat_pkg_structure_proof() -> StockCodexCompatPkgStructureProof:
    """Build and inspect an unsigned flat pkg without installing it."""
    source_repo_root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(
        prefix="omnigent-stock-codex-compat-pkg-structure-"
    ) as temp_root:
        root = Path(temp_root).resolve()
        artifact_dir = root / "artifacts"
        artifact_dir.mkdir()
        package_path = artifact_dir / "omnigent-stock-codex-compat.pkg"
        payload = _run_stock_codex_compat_pkg_builder_cli_json(
            [
                "--repo-root",
                str(source_repo_root),
                "--output",
                str(package_path),
                "--force",
            ],
            repo_root=source_repo_root,
        )
        return _validate_stock_codex_compat_pkg_builder_payload(
            payload,
            source_repo_root=source_repo_root,
        )


def _xcrun_find_tool(xcrun_path: str, tool_name: str) -> str | None:
    completed = subprocess.run(
        [xcrun_path, "--find", tool_name],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if completed.returncode != 0:
        return None
    path = completed.stdout.strip()
    return path or None


def _developer_id_identities(
    *,
    signing_keychain: Path | None,
    identity_family: str,
) -> tuple[str, ...]:
    security = shutil.which("security")
    if not security:
        return ()
    command = [security, "find-identity", "-v", "-p", "basic"]
    if signing_keychain is not None:
        command.append(str(signing_keychain))
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if completed.returncode != 0:
        return ()
    identities: list[str] = []
    marker = f"Developer ID {identity_family}:"
    for line in completed.stdout.splitlines():
        if marker not in line:
            continue
        match = re.search(
            rf'"(?P<identity>[^"]*{re.escape(marker)}[^"]*)"',
            line,
        )
        if match:
            identities.append(match.group("identity"))
    return tuple(sorted(set(identities)))


def _developer_id_installer_identities(
    *,
    signing_keychain: Path | None,
) -> tuple[str, ...]:
    return _developer_id_identities(
        signing_keychain=signing_keychain,
        identity_family="Installer",
    )


def _developer_id_application_identities(
    *,
    signing_keychain: Path | None,
) -> tuple[str, ...]:
    return _developer_id_identities(
        signing_keychain=signing_keychain,
        identity_family="Application",
    )


def _stock_codex_compat_pkg_signing_prerequisites(
    *,
    sign_identity: str | None,
    signing_keychain: Path | None,
    notarytool_profile: str | None,
) -> StockCodexCompatPkgSigningPrerequisites:
    signing_keychain = (
        signing_keychain.expanduser().resolve() if signing_keychain is not None else None
    )
    tool_paths: dict[str, str | None] = {
        "pkgbuild": shutil.which("pkgbuild"),
        "pkgutil": shutil.which("pkgutil"),
        "xcrun": shutil.which("xcrun"),
        "spctl": shutil.which("spctl"),
        "notarytool": None,
        "stapler": None,
    }
    missing: list[str] = []
    for tool_name in ("pkgbuild", "pkgutil", "xcrun", "spctl"):
        if not tool_paths[tool_name]:
            missing.append(f"missing tool: {tool_name}")
    if tool_paths["xcrun"]:
        tool_paths["notarytool"] = _xcrun_find_tool(str(tool_paths["xcrun"]), "notarytool")
        tool_paths["stapler"] = _xcrun_find_tool(str(tool_paths["xcrun"]), "stapler")
    if not tool_paths["notarytool"]:
        missing.append("missing xcrun notarytool")
    if not tool_paths["stapler"]:
        missing.append("missing xcrun stapler")
    if signing_keychain is not None and not signing_keychain.exists():
        missing.append(f"missing signing keychain: {signing_keychain}")

    identities = _developer_id_installer_identities(signing_keychain=signing_keychain)
    application_identities = _developer_id_application_identities(
        signing_keychain=signing_keychain,
    )
    identity_source = "explicit" if sign_identity else "missing"
    resolved_identity = sign_identity.strip() if sign_identity else None
    if resolved_identity and "Developer ID Application:" in resolved_identity:
        missing.append(
            "Developer ID Application identities cannot sign installer packages; "
            "use a Developer ID Installer identity"
        )
    if not resolved_identity:
        if len(identities) == 1:
            resolved_identity = identities[0]
            identity_source = "autodiscovered-developer-id-installer"
        elif len(identities) > 1:
            identity_source = "ambiguous"
            missing.append(
                f"set {PKG_SIGN_IDENTITY_ENV} or --pkg-sign-identity; "
                "multiple Developer ID Installer identities are installed"
            )
        else:
            missing.append(f"set {PKG_SIGN_IDENTITY_ENV} or --pkg-sign-identity")
            if application_identities:
                missing.append(
                    "Developer ID Application identity is present, but a "
                    "Developer ID Installer identity is required for .pkg signing"
                )
    if not notarytool_profile:
        missing.append(f"set {NOTARYTOOL_PROFILE_ENV} or --notarytool-profile")

    return StockCodexCompatPkgSigningPrerequisites(
        status="ready" if not missing else "blocked",
        missing_prerequisites=tuple(missing),
        tool_paths=tool_paths,
        sign_identity=resolved_identity,
        sign_identity_source=identity_source,
        signing_keychain=signing_keychain,
        developer_id_installer_identities=identities,
        developer_id_application_identities=application_identities,
        notarytool_profile=notarytool_profile,
    )


def _run_pkg_distribution_command(
    command: list[str],
    *,
    timeout: float,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if completed.returncode != 0:
        raise SystemExit(
            "Signed/notarized pkg validation command failed.\n"
            f"command={command!r}\n"
            f"exit={completed.returncode}\n"
            f"stdout={completed.stdout}\n"
            f"stderr={completed.stderr}"
        )
    return completed


def _notary_submit_result(completed: subprocess.CompletedProcess[str]) -> tuple[str, str]:
    combined_output = ((completed.stdout or "") + "\n" + (completed.stderr or "")).strip()
    submission_id = ""
    status = ""
    if completed.stdout.strip():
        with contextlib.suppress(json.JSONDecodeError):
            payload = json.loads(completed.stdout)
            if isinstance(payload, dict):
                submission_id = str(payload.get("id") or "")
                status = str(payload.get("status") or "")
    if not status:
        for line in combined_output.splitlines():
            stripped = line.strip()
            if stripped.lower().startswith("id:"):
                submission_id = stripped.split(":", 1)[1].strip()
            if stripped.lower().startswith("status:"):
                status = stripped.split(":", 1)[1].strip()
    return submission_id, status


def run_stock_codex_compat_pkg_signed_notarized_proof(
    *,
    sign_identity: str | None,
    signing_keychain: Path | None,
    notarytool_profile: str | None,
) -> StockCodexCompatPkgSignedNotarizedProof:
    """Build, sign, notarize, staple, and Gatekeeper-check the compatibility pkg."""
    source_repo_root = Path(__file__).resolve().parents[1]
    prerequisites = _stock_codex_compat_pkg_signing_prerequisites(
        sign_identity=sign_identity,
        signing_keychain=signing_keychain,
        notarytool_profile=notarytool_profile,
    )
    if prerequisites.status != "ready":
        return StockCodexCompatPkgSignedNotarizedProof(
            status="blocked",
            missing_prerequisites=prerequisites.missing_prerequisites,
            tool_paths=prerequisites.tool_paths,
            sign_identity=prerequisites.sign_identity,
            sign_identity_source=prerequisites.sign_identity_source,
            signing_keychain=prerequisites.signing_keychain,
            developer_id_installer_identities=(
                prerequisites.developer_id_installer_identities
            ),
            developer_id_application_identities=(
                prerequisites.developer_id_application_identities
            ),
            notarytool_profile=prerequisites.notarytool_profile,
            package_path=None,
            package_sha256=None,
            source_bundle_sha256=None,
            package_identifier=None,
            package_version=None,
            signature_status=None,
            signed=None,
            notary_submission_id=None,
            notary_status=None,
            notary_output_preview=None,
            staple_output_preview=None,
            stapler_validate_output_preview=None,
            gatekeeper_output_preview=None,
        )

    assert prerequisites.sign_identity is not None
    assert prerequisites.notarytool_profile is not None
    assert prerequisites.tool_paths["xcrun"] is not None
    assert prerequisites.tool_paths["spctl"] is not None
    with tempfile.TemporaryDirectory(
        prefix="omnigent-stock-codex-compat-pkg-signed-"
    ) as temp_root:
        root = Path(temp_root).resolve()
        artifact_dir = root / "artifacts"
        artifact_dir.mkdir()
        package_path = artifact_dir / "omnigent-stock-codex-compat.pkg"
        build_args = [
            "--repo-root",
            str(source_repo_root),
            "--output",
            str(package_path),
            "--force",
            "--sign-identity",
            prerequisites.sign_identity,
        ]
        if prerequisites.signing_keychain is not None:
            build_args.extend(["--signing-keychain", str(prerequisites.signing_keychain)])
        payload = _run_stock_codex_compat_pkg_builder_cli_json(
            build_args,
            repo_root=source_repo_root,
        )
        structure = _validate_stock_codex_compat_pkg_builder_payload(
            payload,
            source_repo_root=source_repo_root,
            expect_signed=True,
        )
        notary_completed = _run_pkg_distribution_command(
            [
                str(prerequisites.tool_paths["xcrun"]),
                "notarytool",
                "submit",
                str(structure.package_path),
                "--keychain-profile",
                prerequisites.notarytool_profile,
                "--wait",
                "--output-format",
                "json",
            ],
            timeout=1800,
        )
        notary_submission_id, notary_status = _notary_submit_result(notary_completed)
        if notary_status.lower() != "accepted":
            raise SystemExit(
                "Compatibility pkg notarization was not accepted.\n"
                f"status={notary_status!r}\n"
                f"stdout={notary_completed.stdout}\n"
                f"stderr={notary_completed.stderr}"
            )
        staple_completed = _run_pkg_distribution_command(
            [
                str(prerequisites.tool_paths["xcrun"]),
                "stapler",
                "staple",
                str(structure.package_path),
            ],
            timeout=300,
        )
        stapler_validate_completed = _run_pkg_distribution_command(
            [
                str(prerequisites.tool_paths["xcrun"]),
                "stapler",
                "validate",
                str(structure.package_path),
            ],
            timeout=300,
        )
        gatekeeper_completed = _run_pkg_distribution_command(
            [
                str(prerequisites.tool_paths["spctl"]),
                "-a",
                "-vv",
                "-t",
                "install",
                str(structure.package_path),
            ],
            timeout=120,
        )
        return StockCodexCompatPkgSignedNotarizedProof(
            status="replacement-ready",
            missing_prerequisites=(),
            tool_paths=prerequisites.tool_paths,
            sign_identity=prerequisites.sign_identity,
            sign_identity_source=prerequisites.sign_identity_source,
            signing_keychain=prerequisites.signing_keychain,
            developer_id_installer_identities=(
                prerequisites.developer_id_installer_identities
            ),
            developer_id_application_identities=(
                prerequisites.developer_id_application_identities
            ),
            notarytool_profile=prerequisites.notarytool_profile,
            package_path=structure.package_path,
            package_sha256=structure.package_sha256,
            source_bundle_sha256=structure.source_bundle_sha256,
            package_identifier=structure.package_identifier,
            package_version=structure.package_version,
            signature_status=structure.signature_status,
            signed=structure.signed,
            notary_submission_id=notary_submission_id,
            notary_status=notary_status,
            notary_output_preview=_preview_text(
                (notary_completed.stdout or "") + (notary_completed.stderr or ""),
                limit=1000,
            ),
            staple_output_preview=_preview_text(
                (staple_completed.stdout or "") + (staple_completed.stderr or ""),
                limit=1000,
            ),
            stapler_validate_output_preview=_preview_text(
                (stapler_validate_completed.stdout or "")
                + (stapler_validate_completed.stderr or ""),
                limit=1000,
            ),
            gatekeeper_output_preview=_preview_text(
                (gatekeeper_completed.stdout or "") + (gatekeeper_completed.stderr or ""),
                limit=1000,
            ),
        )


def _expand_stock_codex_compat_pkg(package_path: Path, expand_dir: Path) -> Path:
    """Expand a flat compatibility pkg and return the expanded payload root."""
    pkgutil = shutil.which("pkgutil")
    if not pkgutil:
        raise SystemExit("Could not find pkgutil on PATH for compatibility pkg proof.")
    if expand_dir.exists():
        shutil.rmtree(expand_dir)
    completed = subprocess.run(
        [pkgutil, "--expand-full", str(package_path), str(expand_dir)],
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if completed.returncode != 0:
        raise SystemExit(
            "Compatibility pkg expansion failed.\n"
            f"package={package_path}\n"
            f"exit={completed.returncode}\n"
            f"stdout={completed.stdout}\n"
            f"stderr={completed.stderr}"
        )
    payload_root = expand_dir / "Payload"
    if not payload_root.is_dir():
        raise SystemExit(f"Expanded compatibility pkg payload is missing: {payload_root}")
    return payload_root


def _validate_expanded_stock_codex_compat_runtime(
    *,
    payload_root: Path,
    packaged_runtime_root: Path,
    source_repo_root: Path,
) -> Path:
    """Return the expanded runtime root or fail if the pkg runtime is incomplete."""
    expanded_runtime_root = (payload_root / packaged_runtime_root.relative_to("/")).resolve()
    if expanded_runtime_root == source_repo_root.resolve():
        raise SystemExit("Expanded compatibility pkg runtime reused the development checkout.")
    if not expanded_runtime_root.is_dir():
        raise SystemExit(
            f"Expanded compatibility pkg runtime root is missing: {expanded_runtime_root}"
        )
    required_runtime_files = (
        Path("pyproject.toml"),
        Path("scripts") / "install_stock_codex_compat_launcher.py",
        Path("scripts") / "provision_stock_codex.py",
        Path("omnigent") / "stock_codex_compat_wrapper.py",
    )
    missing = [
        relative
        for relative in required_runtime_files
        if not (expanded_runtime_root / relative).is_file()
    ]
    if missing:
        raise SystemExit(
            "Expanded compatibility pkg runtime missed required files.\n"
            f"runtime_root={expanded_runtime_root}\n"
            f"missing={','.join(str(path) for path in missing)}"
        )
    return expanded_runtime_root


def _stage_stock_codex_compat_pkg_install_root(
    *,
    payload_root: Path,
    install_root: Path,
    packaged_runtime_root: Path,
    source_repo_root: Path,
) -> Path:
    """Copy a pkg payload into a temp install root and return its runtime root."""
    if install_root.exists():
        shutil.rmtree(install_root)
    install_root.mkdir(parents=True)
    for child in payload_root.iterdir():
        target = install_root / child.name
        if child.is_dir():
            shutil.copytree(child, target, symlinks=True)
        else:
            shutil.copy2(child, target)
    return _validate_expanded_stock_codex_compat_runtime(
        payload_root=install_root,
        packaged_runtime_root=packaged_runtime_root,
        source_repo_root=source_repo_root,
    )


def _run_shell_command_for_proof(
    command: str,
    *,
    env: Mapping[str, str],
    cwd: Path,
    timeout: float = 60.0,
) -> subprocess.CompletedProcess[str]:
    """Execute generated shell metadata in a proof-scoped environment."""
    completed = subprocess.run(
        command,
        shell=True,
        executable="/bin/sh",
        check=False,
        capture_output=True,
        text=True,
        env=dict(env),
        cwd=cwd,
        timeout=timeout,
    )
    if completed.returncode != 0:
        raise SystemExit(
            "Generated proof command failed.\n"
            f"command={command}\n"
            f"exit={completed.returncode}\n"
            f"stdout={completed.stdout}\n"
            f"stderr={completed.stderr}"
        )
    return completed


def run_stock_codex_compat_pkg_runtime_live_proof(
    source_bundle: Path,
    stock_codex_path: Path,
    *,
    workspace_root: Path,
    timeout_seconds: float,
) -> StockCodexCompatPkgRuntimeLiveProof:
    """Run a real stock Codex turn through an expanded compatibility pkg runtime."""
    source_bundle = source_bundle.expanduser().resolve()
    stock_codex_path = stock_codex_path.expanduser().resolve()
    workspace_root = workspace_root.expanduser().resolve()
    source_repo_root = Path(__file__).resolve().parents[1]
    stock_codex_version = codex_version(stock_codex_path)
    uvx_raw = shutil.which("uvx")
    if not uvx_raw:
        raise SystemExit("Could not find uvx on PATH for compatibility pkg live proof.")
    uvx_path = Path(uvx_raw).expanduser().resolve()
    if not uvx_path.is_file() or not os.access(uvx_path, os.X_OK):
        raise SystemExit(f"uvx binary is not executable: {uvx_path}")
    auth_path, auth_source = _stock_replacement_auth_source()
    if not codex_native._codex_auth_json_has_available_credential(auth_path):
        raise SystemExit(
            "Current real Codex auth source is not available; cannot run live "
            "stock-codex-compat-pkg-runtime proof.\n"
            f"auth_path={auth_path}\n"
            f"auth_source={auth_source}"
        )

    with tempfile.TemporaryDirectory(
        prefix="omnigent-stock-codex-compat-pkg-runtime-live-"
    ) as temp_root:
        root = Path(temp_root).resolve()
        artifact_dir = root / "artifacts"
        artifact_dir.mkdir()
        package_path = artifact_dir / "omnigent-stock-codex-compat.pkg"
        payload = _run_stock_codex_compat_pkg_builder_cli_json(
            [
                "--repo-root",
                str(source_repo_root),
                "--output",
                str(package_path),
                "--force",
            ],
            repo_root=source_repo_root,
        )
        package_proof = _validate_stock_codex_compat_pkg_builder_payload(
            payload,
            source_repo_root=source_repo_root,
        )
        expanded_payload_root = _expand_stock_codex_compat_pkg(
            package_proof.package_path,
            root / "pkg-expanded",
        )
        expanded_runtime_root = _validate_expanded_stock_codex_compat_runtime(
            payload_root=expanded_payload_root,
            packaged_runtime_root=package_proof.runtime_root,
            source_repo_root=source_repo_root,
        )

        codex_home = root / "codex-home"
        temp_home = root / "home"
        bridge_dir = root / "omnigent-bridge"
        marketplace_root = root / "local-apple-workflow-marketplace"
        wrapper_evidence_path = root / "wrapper-evidence.json"
        codex_home.mkdir(mode=0o700)
        temp_home.mkdir(mode=0o700)
        (codex_home / "auth.json").symlink_to(auth_path)

        _write_stock_codex_compat_marketplace(
            source_bundle=source_bundle,
            marketplace_root=marketplace_root,
        )
        env = _stock_codex_compat_env(home=temp_home, codex_home=codex_home)
        env["PATH"] = f"{uvx_path.parent}{os.pathsep}{env.get('PATH', '')}"
        env.pop("PYTHONPATH", None)
        enabled_features = _stock_codex_supported_feature_names(stock_codex_path, env=env)
        feature_args = _stock_codex_enable_feature_args(enabled_features)
        _run_stock_codex_json(
            stock_codex_path,
            ["plugin", "marketplace", "add", str(marketplace_root), "--json"],
            env=env,
        )
        _run_stock_codex_json(
            stock_codex_path,
            ["plugin", "add", STOCK_CODEX_COMPAT_PLUGIN_ID, "--json"],
            env=env,
        )
        plugin_list_output = _run_stock_codex_json(
            stock_codex_path,
            ["plugin", "list", "--json"],
            env=env,
        )
        _validate_stock_codex_compat_plugin_state(
            marketplace_list_output=_run_stock_codex_json(
                stock_codex_path,
                ["plugin", "marketplace", "list", "--json"],
                env=env,
            ),
            plugin_list_output=plugin_list_output,
            installed_plugin_path=(
                codex_home
                / "plugins"
                / "cache"
                / STOCK_CODEX_COMPAT_MARKETPLACE
                / PLUGIN_NAME
                / "0.1.1"
            ),
        )

        write_mcp_bridge_config(bridge_dir)
        write_policy_hook_config(
            bridge_dir,
            ap_server_url=STOCK_CODEX_COMPAT_AP_SERVER_URL,
            ap_auth_headers={},
        )
        _inject_mcp_server_config(codex_home, bridge_dir, sys.executable)
        _write_codex_policy_hooks_file(codex_home, bridge_dir, sys.executable)
        mcp_list_output = _run_stock_codex_json(
            stock_codex_path,
            ["mcp", "list", "--json"],
            env=env,
        )
        mcp_omnigent_output = _run_stock_codex_json(
            stock_codex_path,
            ["mcp", "get", "omnigent", "--json"],
            env=env,
        )
        _hook_events, mcp_servers, _mcp_command, _mcp_args = _validate_stock_codex_compat_bridge(
            codex_home=codex_home,
            bridge_dir=bridge_dir,
            mcp_list_output=mcp_list_output,
            mcp_omnigent_output=mcp_omnigent_output,
        )

        prompt = (
            "No-tool stock-codex-compat package runtime live proof for a "
            "SwiftUI workflow. Do not inspect files, do not run commands, "
            f"and do not explain. Reply exactly {STOCK_CODEX_COMPAT_LIVE_SENTINEL}."
        )
        wrapper_command = (
            str(uvx_path),
            "--from",
            str(expanded_runtime_root),
            "omnigent-stock-codex-wrapper",
            "--stock-codex-path",
            str(stock_codex_path),
            "--route-prefix",
            EXPECTED_ROUTE,
            "--evidence-path",
            str(wrapper_evidence_path),
            "--",
            "exec",
            *feature_args,
            "--json",
            "--dangerously-bypass-hook-trust",
            "--skip-git-repo-check",
            "--sandbox",
            "read-only",
            "-C",
            str(workspace_root),
            prompt,
        )
        completed = subprocess.run(
            list(wrapper_command),
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds if timeout_seconds > 0 else None,
            env=env,
            cwd=expanded_runtime_root,
            stdin=subprocess.DEVNULL,
        )
        stderr_preview = _preview_text(completed.stderr, limit=2000)
        if completed.returncode != 0:
            raise SystemExit(
                "Live stock-codex-compat-pkg-runtime command failed.\n"
                f"exit={completed.returncode}\n"
                f"stderr={stderr_preview}\n"
                f"stdout_preview={_preview_text(completed.stdout, limit=2000)}"
            )
        events = _parse_stock_codex_exec_jsonl(completed.stdout)
        thread_id, first_agent_message = _validate_stock_codex_compat_live_events(events)
        if not first_agent_message.startswith(EXPECTED_ROUTE):
            raise SystemExit(
                "Live stock-codex-compat-pkg-runtime proof did not emit "
                "deterministic route evidence before model output.\n"
                f"expected_prefix={EXPECTED_ROUTE!r}\n"
                f"first_agent_message={first_agent_message!r}\n"
                f"sentinel={STOCK_CODEX_COMPAT_LIVE_SENTINEL!r}"
            )
        wrapper_evidence = _read_stock_codex_compat_wrapper_evidence(wrapper_evidence_path)
        if wrapper_evidence["routeInjected"] is not True:
            raise SystemExit(
                "Live stock-codex-compat-pkg-runtime proof did not prove "
                "wrapper-owned route injection.\n"
                f"evidence={wrapper_evidence!r}"
            )

        return StockCodexCompatPkgRuntimeLiveProof(
            stock_codex_path=stock_codex_path,
            stock_codex_version=stock_codex_version,
            source_bundle=source_bundle,
            package_path=package_proof.package_path,
            package_sha256=package_proof.package_sha256,
            source_bundle_sha256=package_proof.source_bundle_sha256,
            package_identifier=package_proof.package_identifier,
            package_version=package_proof.package_version,
            install_prefix=package_proof.install_prefix,
            packaged_runtime_root=package_proof.runtime_root,
            expanded_payload_root=expanded_payload_root,
            expanded_runtime_root=expanded_runtime_root,
            uvx_path=uvx_path,
            wrapper_command=wrapper_command,
            codex_home=codex_home,
            auth_path=auth_path,
            bridge_dir=bridge_dir,
            workspace_root=workspace_root,
            enabled_features=enabled_features,
            thread_id=thread_id,
            first_agent_message=first_agent_message,
            first_agent_message_before_wrapper=str(
                wrapper_evidence["firstAgentMessageBefore"]
            ),
            route_injected=bool(wrapper_evidence["routeInjected"]),
            wrapper_evidence_path=wrapper_evidence_path,
            event_count=len(events),
            mcp_servers=mcp_servers,
            stderr_preview=stderr_preview,
        )


def run_stock_codex_compat_pkg_user_bootstrap_proof(
    stock_codex_path: Path,
    *,
    uvx_path: Path | None = None,
) -> StockCodexCompatPkgUserBootstrapProof:
    """Prove a pkg-installed runtime can bootstrap a clean user's launcher."""
    stock_codex_path = stock_codex_path.expanduser().resolve()
    assert_stock_codex_path(stock_codex_path, allow_fork_codex=False)
    stock_codex_version = codex_version(stock_codex_path)
    uvx_path = uvx_path.expanduser().resolve() if uvx_path is not None else None
    if uvx_path is None:
        uvx_raw = shutil.which("uvx")
        if not uvx_raw:
            raise SystemExit("Could not find uvx on PATH for pkg bootstrap proof.")
        uvx_path = Path(uvx_raw).expanduser().resolve()
    if not uvx_path.is_file() or not os.access(uvx_path, os.X_OK):
        raise SystemExit(f"uvx binary is not executable: {uvx_path}")

    source_repo_root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(
        prefix="omnigent-stock-codex-compat-pkg-user-bootstrap-"
    ) as temp_root:
        root = Path(temp_root).resolve()
        artifact_dir = root / "artifacts"
        artifact_dir.mkdir()
        package_path = artifact_dir / "omnigent-stock-codex-compat.pkg"
        payload = _run_stock_codex_compat_pkg_builder_cli_json(
            [
                "--repo-root",
                str(source_repo_root),
                "--output",
                str(package_path),
                "--force",
            ],
            repo_root=source_repo_root,
        )
        package_proof = _validate_stock_codex_compat_pkg_builder_payload(
            payload,
            source_repo_root=source_repo_root,
        )
        expanded_payload_root = _expand_stock_codex_compat_pkg(
            package_proof.package_path,
            root / "pkg-expanded",
        )
        install_root = root / "installed-root"
        installed_runtime_root = _stage_stock_codex_compat_pkg_install_root(
            payload_root=expanded_payload_root,
            install_root=install_root,
            packaged_runtime_root=package_proof.runtime_root,
            source_repo_root=source_repo_root,
        )
        installed_prefix = install_root / package_proof.install_prefix.relative_to("/")
        installer_script_path = (
            installed_runtime_root / "scripts" / "install_stock_codex_compat_launcher.py"
        )
        pkg_manifest_path = installed_prefix / "pkg-manifest.json"
        bundle_manifest_path = installed_prefix / "bundle-manifest.json"
        pkg_manifest = json.loads(pkg_manifest_path.read_text(encoding="utf-8"))
        bundle_manifest = json.loads(bundle_manifest_path.read_text(encoding="utf-8"))
        if not isinstance(pkg_manifest, dict) or not isinstance(bundle_manifest, dict):
            raise SystemExit("Installed compatibility pkg manifests were not JSON objects.")
        pkg_contract = pkg_manifest.get("contract")
        if not isinstance(pkg_contract, dict):
            raise SystemExit(f"Installed compatibility pkg contract missing: {pkg_manifest!r}")
        if pkg_contract.get("userBootstrap") != "deferred-to-installed-runtime-command":
            raise SystemExit(
                "Installed compatibility bootstrap contract mismatch: "
                f"{pkg_contract!r}"
            )
        if bundle_manifest.get("sourceRoot") != "<omitted-from-pkg>":
            raise SystemExit(
                "Installed compatibility bundle manifest embedded source root: "
                f"{bundle_manifest!r}"
            )

        clean_home = root / "home"
        clean_tmp = root / "tmp"
        clean_home.mkdir()
        clean_tmp.mkdir()
        clean_bin_dir = clean_home / ".local" / "bin"
        launcher_path = clean_bin_dir / "omnigent-stock-codex-compat"
        manifest_path = (
            clean_home / ".local" / "omnigent" / "launchers" / "stock-codex-compat.json"
        )
        adapter_package_dir = (
            clean_home / ".local" / "omnigent" / "stock-codex-compat" / "adapter-package"
        )
        adapter_bridge_dir = (
            clean_home / ".local" / "omnigent" / "stock-codex-compat" / "adapter-bridge"
        )
        proof_path = (
            f"{clean_bin_dir}{os.pathsep}{uvx_path.parent}{os.pathsep}"
            f"{os.environ.get('PATH', '')}"
        )
        python_path = str(installed_runtime_root)
        if os.environ.get("PYTHONPATH"):
            python_path = f"{python_path}{os.pathsep}{os.environ['PYTHONPATH']}"
        env = os.environ.copy()
        env.update(
            {
                "HOME": str(clean_home),
                "TMPDIR": str(clean_tmp),
                "PATH": proof_path,
                "PYTHONPATH": python_path,
            }
        )
        env.pop("CODEX_HOME", None)
        env.pop(OMNIGENT_STOCK_CODEX_PATH_ENV, None)

        adapter_payload = _run_stock_codex_compat_installer_cli_json(
            ["--install-adapter-package"],
            env=env,
            repo_root=installed_runtime_root,
            script_path=installer_script_path,
        )
        install_payload = _run_stock_codex_compat_installer_cli_json(
            [
                "--install",
                "--pinned-codex-path",
                str(stock_codex_path),
                "--repo-root",
                str(installed_runtime_root),
                "--uvx-path",
                str(uvx_path),
                "--require-path-selected",
            ],
            env=env,
            repo_root=installed_runtime_root,
            script_path=installer_script_path,
        )
        selected = shutil.which("omnigent-stock-codex-compat", path=env["PATH"])
        if selected is None:
            raise SystemExit("Pkg bootstrap proof did not select compatibility command.")
        selected_command_path = Path(selected).expanduser().resolve()
        if selected_command_path != launcher_path.resolve():
            raise SystemExit(
                "Pkg bootstrap proof selected the wrong compatibility command.\n"
                f"expected={launcher_path.resolve()}\nactual={selected_command_path}"
            )
        version = subprocess.run(
            [str(selected_command_path), "--version"],
            check=False,
            capture_output=True,
            text=True,
            env=env,
            timeout=10,
        )
        version_output = (version.stdout or version.stderr).strip()
        if version.returncode != 0 or version_output != stock_codex_version:
            raise SystemExit(
                "Pkg bootstrap proof version delegation failed.\n"
                f"expected={stock_codex_version!r}\nactual={version_output!r}\n"
                f"exit={version.returncode}"
            )
        probe = subprocess.run(
            [str(selected_command_path), "--omnigent-stock-codex-compat-launcher-probe"],
            check=False,
            capture_output=True,
            text=True,
            env=env,
            timeout=10,
        )
        probe_output = ((probe.stdout or "") + (probe.stderr or "")).strip()
        if probe.returncode != 0 or "OMNIGENT_STOCK_CODEX_COMPAT_LAUNCHER_OK" not in (
            probe_output
        ):
            raise SystemExit(
                "Pkg bootstrap proof launcher probe failed.\n"
                f"exit={probe.returncode}\noutput={probe_output}"
            )
        if str(installed_runtime_root) not in probe_output:
            raise SystemExit(
                "Pkg bootstrap proof launcher probe did not delegate to installed runtime.\n"
                f"expected_runtime={installed_runtime_root}\noutput={probe_output}"
            )
        launcher_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        launcher_repo_root_raw = launcher_manifest.get("repoRoot")
        if not isinstance(launcher_repo_root_raw, str) or not launcher_repo_root_raw:
            raise SystemExit(
                f"Installed launcher manifest omitted repoRoot: {launcher_manifest!r}"
            )
        launcher_manifest_repo_root = Path(launcher_repo_root_raw).expanduser().resolve()
        if launcher_manifest_repo_root != installed_runtime_root:
            raise SystemExit(
                "Pkg bootstrap wrote the wrong runtime root into the launcher manifest.\n"
                f"expected={installed_runtime_root}\nactual={launcher_manifest_repo_root}"
            )
        wrapper_entrypoint = launcher_manifest.get("wrapperEntrypoint")
        if wrapper_entrypoint != "omnigent-stock-codex-wrapper":
            raise SystemExit(
                "Pkg bootstrap launcher manifest had wrong wrapper entrypoint: "
                f"{launcher_manifest!r}"
            )
        manifest_tool_names_raw = launcher_manifest.get("adapterToolNames")
        if not isinstance(manifest_tool_names_raw, list) or not all(
            isinstance(item, str) for item in manifest_tool_names_raw
        ):
            raise SystemExit(
                "Pkg bootstrap launcher manifest omitted adapter tool names: "
                f"{launcher_manifest!r}"
            )

        doctor_payload = _run_stock_codex_compat_installer_cli_json(
            [
                "--doctor",
                "--pinned-codex-path",
                str(stock_codex_path),
                "--repo-root",
                str(installed_runtime_root),
                "--uvx-path",
                str(uvx_path),
                "--require-path-selected",
                "--force",
            ],
            env=env,
            repo_root=installed_runtime_root,
            script_path=installer_script_path,
        )
        if doctor_payload.get("installAllowed") is not True:
            raise SystemExit(f"Pkg bootstrap doctor did not allow update: {doctor_payload!r}")
        if doctor_payload.get("existingTargetState") != "managed":
            raise SystemExit(f"Pkg bootstrap doctor missed managed launcher: {doctor_payload!r}")
        if doctor_payload.get("targetSelectedOnPath") is not True:
            raise SystemExit(
                f"Pkg bootstrap doctor did not see PATH selection: {doctor_payload!r}"
            )
        if doctor_payload.get("mutatesFilesystem") is not False:
            raise SystemExit(f"Pkg bootstrap doctor unexpectedly mutates: {doctor_payload!r}")

        update_payload = _run_stock_codex_compat_installer_cli_json(
            [
                "--install",
                "--pinned-codex-path",
                str(stock_codex_path),
                "--repo-root",
                str(installed_runtime_root),
                "--uvx-path",
                str(uvx_path),
                "--require-path-selected",
                "--force",
            ],
            env=env,
            repo_root=installed_runtime_root,
            script_path=installer_script_path,
        )
        rollback_command_raw = update_payload.get("rollbackCommand")
        if not isinstance(rollback_command_raw, str) or not rollback_command_raw:
            raise SystemExit(f"Pkg bootstrap update omitted rollback command: {update_payload!r}")
        if str(installed_runtime_root) not in rollback_command_raw:
            raise SystemExit(
                "Pkg bootstrap rollback command did not target installed runtime.\n"
                f"expected_runtime={installed_runtime_root}\n"
                f"rollback_command={rollback_command_raw}"
            )
        adapter_package_exists_after_install = (
            adapter_package_dir.is_dir()
            and Path(str(adapter_payload["adapterBin"])).is_dir()
            and Path(str(adapter_payload["adapterManifest"])).is_file()
        )
        rollback = _run_shell_command_for_proof(
            rollback_command_raw,
            env=env,
            cwd=installed_runtime_root,
            timeout=240,
        )
        if "compat_launcher_action=uninstalled" not in rollback.stdout:
            raise SystemExit(
                "Pkg bootstrap generated rollback command did not uninstall launcher.\n"
                f"stdout={rollback.stdout}\nstderr={rollback.stderr}"
            )
        launcher_removed = not launcher_path.exists()
        manifest_removed = not manifest_path.exists()
        if not launcher_removed or not manifest_removed:
            raise SystemExit(
                "Pkg bootstrap rollback left launcher artifacts behind.\n"
                f"launcher_exists={launcher_path.exists()}\n"
                f"manifest_exists={manifest_path.exists()}"
            )

        return StockCodexCompatPkgUserBootstrapProof(
            stock_codex_path=stock_codex_path,
            stock_codex_version=stock_codex_version,
            package_path=package_proof.package_path,
            package_sha256=package_proof.package_sha256,
            package_identifier=package_proof.package_identifier,
            package_version=package_proof.package_version,
            install_root=install_root,
            installed_prefix=installed_prefix,
            installed_runtime_root=installed_runtime_root,
            installer_script_path=installer_script_path,
            pkg_manifest_path=pkg_manifest_path,
            bundle_manifest_path=bundle_manifest_path,
            clean_home=clean_home,
            clean_bin_dir=clean_bin_dir,
            launcher_path=launcher_path,
            manifest_path=manifest_path,
            adapter_package_dir=adapter_package_dir,
            adapter_bin=Path(str(adapter_payload["adapterBin"])),
            adapter_manifest=Path(str(adapter_payload["adapterManifest"])),
            adapter_bridge_dir=adapter_bridge_dir,
            adapter_tool_names=tuple(
                str(name) for name in adapter_payload.get("adapterToolNames", [])
            ),
            uvx_path=uvx_path,
            selected_command_path=selected_command_path,
            launcher_manifest_repo_root=launcher_manifest_repo_root,
            launcher_manifest_wrapper_entrypoint=str(wrapper_entrypoint),
            launcher_manifest_adapter_tool_names=tuple(manifest_tool_names_raw),
            version_output=version_output,
            probe_output=probe_output,
            adapter_package_action=str(adapter_payload["action"]),
            install_action=str(install_payload["action"]),
            update_action=str(update_payload["action"]),
            rollback_command=rollback_command_raw,
            rollback_action="uninstalled",
            doctor_install_allowed=bool(doctor_payload["installAllowed"]),
            doctor_existing_target_state=str(doctor_payload["existingTargetState"]),
            doctor_existing_target_managed=bool(doctor_payload["existingTargetManaged"]),
            doctor_target_selected_on_path=bool(doctor_payload["targetSelectedOnPath"]),
            doctor_mutates_filesystem=bool(doctor_payload["mutatesFilesystem"]),
            adapter_package_exists_after_install=adapter_package_exists_after_install,
            launcher_removed_after_rollback=launcher_removed,
            manifest_removed_after_rollback=manifest_removed,
        )


def run_stock_codex_compat_pkg_clean_provision_proof(
    stock_codex_path: Path,
) -> StockCodexCompatPkgCleanProvisionProof:
    """Prove a pkg-installed runtime can provision stock Codex into a clean cache."""
    stock_codex_path = stock_codex_path.expanduser().resolve()
    assert_stock_codex_path(stock_codex_path, allow_fork_codex=False)
    stock_codex_realpath = stock_codex_path.resolve()
    stock_codex_version = codex_version(stock_codex_realpath)
    stock_codex_sha256 = sha256_file(stock_codex_realpath)

    source_repo_root = Path(__file__).resolve().parents[1]
    host_cache_root = (
        Path.home() / ".local" / "omnigent" / "codex-stock"
    ).expanduser().resolve()
    with tempfile.TemporaryDirectory(
        prefix="omnigent-stock-codex-compat-pkg-clean-provision-"
    ) as temp_root:
        root = Path(temp_root).resolve()
        artifact_dir = root / "artifacts"
        artifact_dir.mkdir()
        package_path = artifact_dir / "omnigent-stock-codex-compat.pkg"
        payload = _run_stock_codex_compat_pkg_builder_cli_json(
            [
                "--repo-root",
                str(source_repo_root),
                "--output",
                str(package_path),
                "--force",
            ],
            repo_root=source_repo_root,
        )
        package_proof = _validate_stock_codex_compat_pkg_builder_payload(
            payload,
            source_repo_root=source_repo_root,
        )
        expanded_payload_root = _expand_stock_codex_compat_pkg(
            package_proof.package_path,
            root / "pkg-expanded",
        )
        install_root = root / "installed-root"
        installed_runtime_root = _stage_stock_codex_compat_pkg_install_root(
            payload_root=expanded_payload_root,
            install_root=install_root,
            packaged_runtime_root=package_proof.runtime_root,
            source_repo_root=source_repo_root,
        )
        installed_prefix = install_root / package_proof.install_prefix.relative_to("/")
        provisioner_script_path = installed_runtime_root / "scripts" / "provision_stock_codex.py"
        if not provisioner_script_path.is_file():
            raise SystemExit(
                "Pkg-installed runtime is missing the stock Codex provisioner.\n"
                f"expected={provisioner_script_path}"
            )
        pkg_manifest_path = installed_prefix / "pkg-manifest.json"
        bundle_manifest_path = installed_prefix / "bundle-manifest.json"
        pkg_manifest = json.loads(pkg_manifest_path.read_text(encoding="utf-8"))
        bundle_manifest = json.loads(bundle_manifest_path.read_text(encoding="utf-8"))
        if not isinstance(pkg_manifest, dict) or not isinstance(bundle_manifest, dict):
            raise SystemExit("Installed compatibility pkg manifests were not JSON objects.")
        pkg_contract = pkg_manifest.get("contract")
        if not isinstance(pkg_contract, dict):
            raise SystemExit(f"Installed compatibility pkg contract missing: {pkg_manifest!r}")
        if (
            pkg_contract.get("stockCodexProvisioning")
            != "deferred-to-installed-runtime-command"
        ):
            raise SystemExit(
                "Installed compatibility stock Codex provisioning contract mismatch: "
                f"{pkg_contract!r}"
            )
        provisioner_manifest_path = pkg_manifest.get("stockCodexProvisioner")
        expected_provisioner_manifest_path = str(
            package_proof.runtime_root / "scripts" / "provision_stock_codex.py"
        )
        if provisioner_manifest_path != expected_provisioner_manifest_path:
            raise SystemExit(
                "Installed compatibility pkg manifest recorded the wrong provisioner path: "
                f"{pkg_manifest!r}"
            )
        if bundle_manifest.get("sourceRoot") != "<omitted-from-pkg>":
            raise SystemExit(
                "Installed compatibility bundle manifest embedded source root: "
                f"{bundle_manifest!r}"
            )

        clean_home = root / "home"
        clean_tmp = root / "tmp"
        clean_home.mkdir(mode=0o700)
        clean_tmp.mkdir(mode=0o700)
        clean_cache_root = clean_home / ".local" / "omnigent" / "codex-stock"
        if clean_cache_root.exists():
            raise SystemExit(f"Clean stock Codex cache unexpectedly exists: {clean_cache_root}")

        channel_root = root / "stock-codex-channel"
        channel_artifacts = channel_root / "artifacts"
        channel_artifacts.mkdir(parents=True)
        channel_artifact_path = channel_artifacts / "codex"
        shutil.copy2(stock_codex_realpath, channel_artifact_path)
        channel_artifact_path.chmod(0o755)
        if sha256_file(channel_artifact_path) != stock_codex_sha256:
            raise SystemExit(
                "Clean stock Codex channel artifact digest mismatch after copy.\n"
                f"source={stock_codex_realpath}\nartifact={channel_artifact_path}"
            )
        channel_manifest_path = channel_root / "channel.json"
        channel_manifest_path.write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "kind": "omnigent-stock-codex-channel",
                    "latest": stock_codex_version,
                    "artifacts": [
                        {
                            "version": stock_codex_version,
                            "path": "artifacts/codex",
                            "sha256": stock_codex_sha256,
                        }
                    ],
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

        python_path_entries = [str(installed_runtime_root)]
        if os.environ.get("PYTHONPATH"):
            python_path_entries.append(os.environ["PYTHONPATH"])
        env = os.environ.copy()
        env.update(
            {
                "HOME": str(clean_home),
                "TMPDIR": str(clean_tmp),
                "PYTHONPATH": os.pathsep.join(python_path_entries),
            }
        )
        env.pop("CODEX_HOME", None)
        env.pop(OMNIGENT_STOCK_CODEX_PATH_ENV, None)

        provisioner_command = [
            sys.executable,
            str(provisioner_script_path),
            "--cache-root",
            str(clean_cache_root),
            "--channel-manifest",
            str(channel_manifest_path),
            "--expected-sha256",
            stock_codex_sha256,
            "--json",
        ]

        def run_provisioner_json() -> dict[str, Any]:
            completed = subprocess.run(
                provisioner_command,
                check=False,
                capture_output=True,
                text=True,
                env=env,
                cwd=installed_runtime_root,
                timeout=120,
            )
            if completed.returncode != 0:
                raise SystemExit(
                    "Pkg-installed stock Codex provisioner failed.\n"
                    f"command={shlex.join(provisioner_command)}\n"
                    f"exit={completed.returncode}\n"
                    f"stdout={completed.stdout}\n"
                    f"stderr={completed.stderr}"
                )
            try:
                parsed = json.loads(completed.stdout)
            except json.JSONDecodeError as exc:
                raise SystemExit(
                    "Pkg-installed stock Codex provisioner did not emit JSON.\n"
                    f"stdout={completed.stdout}\nstderr={completed.stderr}"
                ) from exc
            if not isinstance(parsed, dict):
                raise SystemExit(
                    "Pkg-installed stock Codex provisioner emitted non-object JSON: "
                    f"{parsed!r}"
                )
            return parsed

        provisioned = run_provisioner_json()
        provisioned_path = Path(_json_string(provisioned, "codexPath")).resolve()
        payload_dir = Path(_json_string(provisioned, "payloadDir")).resolve()
        manifest_path = Path(_json_string(provisioned, "manifestPath")).resolve()
        provisioned_sha = _json_string(provisioned, "sha256")
        provisioned_version = _json_string(provisioned, "version")
        provisioned_source_kind = _json_string(provisioned, "sourceKind")
        if not payload_dir.is_relative_to(clean_cache_root.resolve()):
            raise SystemExit(
                "Pkg-installed provisioner wrote outside the clean cache root.\n"
                f"cache_root={clean_cache_root}\npayload_dir={payload_dir}"
            )
        if not provisioned_path.is_relative_to(clean_cache_root.resolve()):
            raise SystemExit(
                "Pkg-installed provisioner returned a Codex path outside the clean cache.\n"
                f"cache_root={clean_cache_root}\ncodex_path={provisioned_path}"
            )
        if provisioned_sha.lower() != stock_codex_sha256.lower():
            raise SystemExit(
                "Pkg-installed provisioner installed an unexpected stock Codex binary.\n"
                f"expected_sha256={stock_codex_sha256}\nactual_sha256={provisioned_sha}"
            )
        if provisioned_version != stock_codex_version:
            raise SystemExit(
                "Pkg-installed provisioner recorded an unexpected stock Codex version.\n"
                f"expected_version={stock_codex_version!r}\nactual_version={provisioned_version!r}"
            )
        if provisioned_source_kind != "channel":
            raise SystemExit(
                f"Pkg-installed provisioner source kind mismatch: {provisioned!r}"
            )
        provisioned_env = provisioned.get("env")
        if not isinstance(provisioned_env, dict):
            raise SystemExit(f"Pkg-installed provisioner omitted env contract: {provisioned!r}")
        provisioned_env_raw = provisioned_env.get(OMNIGENT_STOCK_CODEX_PATH_ENV)
        if provisioned_env_raw != str(provisioned_path):
            raise SystemExit(
                "Pkg-installed provisioner emitted the wrong env contract.\n"
                f"expected={provisioned_path}\nactual={provisioned_env_raw!r}"
            )
        provisioned_env_path = Path(str(provisioned_env_raw)).resolve()
        if not provisioned_path.is_file() or not os.access(provisioned_path, os.X_OK):
            raise SystemExit(f"Clean-provisioned Codex is not executable: {provisioned_path}")
        if codex_version(provisioned_path) != provisioned_version:
            raise SystemExit(
                "Clean-provisioned Codex binary reported a different version.\n"
                f"manifest_version={provisioned_version!r}"
            )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("kind") != "omnigent-stock-codex":
            raise SystemExit(f"Clean-provisioned manifest kind mismatch: {manifest!r}")
        if manifest.get("sourceKind") != "channel":
            raise SystemExit(f"Clean-provisioned manifest source mismatch: {manifest!r}")
        if manifest.get("channelManifestPath") != str(channel_manifest_path):
            raise SystemExit(
                f"Clean-provisioned manifest channel path mismatch: {manifest!r}"
            )
        channel_artifact = manifest.get("channelArtifact")
        if not isinstance(channel_artifact, dict):
            raise SystemExit(f"Clean-provisioned manifest omitted channel artifact: {manifest!r}")
        if channel_artifact.get("path") != "artifacts/codex":
            raise SystemExit(
                f"Clean-provisioned manifest recorded unexpected artifact: {manifest!r}"
            )

        with temporary_env({OMNIGENT_STOCK_CODEX_PATH_ENV: str(provisioned_path)}):
            resolved_raw = _find_codex_cli()
        if resolved_raw is None:
            raise SystemExit(f"{OMNIGENT_STOCK_CODEX_PATH_ENV} did not resolve a Codex binary.")
        resolved_path = Path(resolved_raw).expanduser().resolve()
        if resolved_path != provisioned_path:
            raise SystemExit(
                "Omnigent stock-Codex resolver did not select the clean-provisioned binary.\n"
                f"expected={provisioned_path}\nactual={resolved_raw}"
            )

        reused = run_provisioner_json()
        reuse_path = Path(_json_string(reused, "codexPath")).resolve()
        reuse_payload_dir = Path(_json_string(reused, "payloadDir")).resolve()
        if reuse_path != provisioned_path or reuse_payload_dir != payload_dir:
            raise SystemExit(
                "Pkg-installed provisioner did not reuse the verified clean-cache payload.\n"
                f"first_path={provisioned_path}\nreuse_path={reuse_path}\n"
                f"first_payload={payload_dir}\nreuse_payload={reuse_payload_dir}"
            )

        proof_text = (
            json.dumps(provisioned, sort_keys=True)
            + "\n"
            + json.dumps(reused, sort_keys=True)
            + "\n"
            + json.dumps(manifest, sort_keys=True)
        )
        host_cache_referenced = str(host_cache_root) in proof_text
        if host_cache_referenced:
            raise SystemExit(
                "Pkg-installed clean provisioning referenced the host stock Codex cache.\n"
                f"host_cache_root={host_cache_root}"
            )

        return StockCodexCompatPkgCleanProvisionProof(
            stock_codex_path=stock_codex_path,
            stock_codex_version=stock_codex_version,
            stock_codex_sha256=stock_codex_sha256,
            package_path=package_proof.package_path,
            package_sha256=package_proof.package_sha256,
            package_identifier=package_proof.package_identifier,
            package_version=package_proof.package_version,
            install_root=install_root,
            installed_prefix=installed_prefix,
            installed_runtime_root=installed_runtime_root,
            provisioner_script_path=provisioner_script_path,
            pkg_manifest_path=pkg_manifest_path,
            bundle_manifest_path=bundle_manifest_path,
            clean_home=clean_home,
            clean_cache_root=clean_cache_root,
            channel_manifest_path=channel_manifest_path,
            channel_artifact_path=channel_artifact_path,
            payload_dir=payload_dir,
            provisioned_codex_path=provisioned_path,
            provisioned_manifest_path=manifest_path,
            provisioned_version=provisioned_version,
            provisioned_sha256=provisioned_sha,
            provisioned_source_kind=provisioned_source_kind,
            provisioned_env_path=provisioned_env_path,
            omnigent_resolved_codex_path=resolved_path,
            reuse_payload_dir=reuse_payload_dir,
            reuse_provisioned_codex_path=reuse_path,
            host_cache_root=host_cache_root,
            host_cache_referenced=host_cache_referenced,
        )


def run_stock_codex_compat_pkg_clean_auth_proof(
    stock_codex_path: Path,
) -> StockCodexCompatPkgCleanAuthProof:
    """Prove clean auth onboarding classification from a pkg-installed runtime."""
    stock_codex_path = stock_codex_path.expanduser().resolve()
    assert_stock_codex_path(stock_codex_path, allow_fork_codex=False)
    stock_codex_realpath = stock_codex_path.resolve()
    stock_codex_version = codex_version(stock_codex_realpath)
    stock_codex_sha256 = sha256_file(stock_codex_realpath)
    real_auth_path, real_auth_source = _stock_replacement_auth_source()
    real_auth_available = codex_native._codex_auth_json_has_available_credential(
        real_auth_path
    )
    if not real_auth_available:
        raise SystemExit(
            "Current real Codex auth source is not available; cannot prove the "
            "packaged clean-auth boundary.\n"
            f"auth_path={real_auth_path}\n"
            "Run stock Codex authentication outside this proof, or point CODEX_HOME "
            "at an authenticated Codex home, then rerun "
            "stock-codex-compat-pkg-clean-auth-onboarding."
        )

    source_repo_root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(
        prefix="omnigent-stock-codex-compat-pkg-clean-auth-"
    ) as temp_root:
        root = Path(temp_root).resolve()
        artifact_dir = root / "artifacts"
        artifact_dir.mkdir()
        package_path = artifact_dir / "omnigent-stock-codex-compat.pkg"
        payload = _run_stock_codex_compat_pkg_builder_cli_json(
            [
                "--repo-root",
                str(source_repo_root),
                "--output",
                str(package_path),
                "--force",
            ],
            repo_root=source_repo_root,
        )
        package_proof = _validate_stock_codex_compat_pkg_builder_payload(
            payload,
            source_repo_root=source_repo_root,
        )
        expanded_payload_root = _expand_stock_codex_compat_pkg(
            package_proof.package_path,
            root / "pkg-expanded",
        )
        install_root = root / "installed-root"
        installed_runtime_root = _stage_stock_codex_compat_pkg_install_root(
            payload_root=expanded_payload_root,
            install_root=install_root,
            packaged_runtime_root=package_proof.runtime_root,
            source_repo_root=source_repo_root,
        )
        installed_prefix = install_root / package_proof.install_prefix.relative_to("/")
        provisioner_script_path = installed_runtime_root / "scripts" / "provision_stock_codex.py"
        if not provisioner_script_path.is_file():
            raise SystemExit(
                "Pkg-installed runtime is missing the stock Codex provisioner.\n"
                f"expected={provisioner_script_path}"
            )

        clean_home = root / "home"
        clean_tmp = root / "tmp"
        clean_home.mkdir(mode=0o700)
        clean_tmp.mkdir(mode=0o700)
        clean_cache_root = clean_home / ".local" / "omnigent" / "codex-stock"

        channel_root = root / "stock-codex-channel"
        channel_artifacts = channel_root / "artifacts"
        channel_artifacts.mkdir(parents=True)
        channel_artifact_path = channel_artifacts / "codex"
        shutil.copy2(stock_codex_realpath, channel_artifact_path)
        channel_artifact_path.chmod(0o755)
        channel_manifest_path = channel_root / "channel.json"
        channel_manifest_path.write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "kind": "omnigent-stock-codex-channel",
                    "latest": stock_codex_version,
                    "artifacts": [
                        {
                            "version": stock_codex_version,
                            "path": "artifacts/codex",
                            "sha256": stock_codex_sha256,
                        }
                    ],
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

        python_path_entries = [str(installed_runtime_root)]
        if os.environ.get("PYTHONPATH"):
            python_path_entries.append(os.environ["PYTHONPATH"])
        provision_env = os.environ.copy()
        provision_env.update(
            {
                "HOME": str(clean_home),
                "TMPDIR": str(clean_tmp),
                "PYTHONPATH": os.pathsep.join(python_path_entries),
            }
        )
        provision_env.pop("CODEX_HOME", None)
        provision_env.pop(OMNIGENT_STOCK_CODEX_PATH_ENV, None)
        provision_command = [
            sys.executable,
            str(provisioner_script_path),
            "--cache-root",
            str(clean_cache_root),
            "--channel-manifest",
            str(channel_manifest_path),
            "--expected-sha256",
            stock_codex_sha256,
            "--json",
        ]
        completed = subprocess.run(
            provision_command,
            check=False,
            capture_output=True,
            text=True,
            env=provision_env,
            cwd=installed_runtime_root,
            timeout=120,
        )
        if completed.returncode != 0:
            raise SystemExit(
                "Pkg-installed stock Codex provisioner failed during clean-auth proof.\n"
                f"command={shlex.join(provision_command)}\n"
                f"exit={completed.returncode}\n"
                f"stdout={completed.stdout}\n"
                f"stderr={completed.stderr}"
            )
        try:
            provisioned = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise SystemExit(
                "Pkg-installed stock Codex provisioner did not emit JSON during "
                f"clean-auth proof.\nstdout={completed.stdout}\nstderr={completed.stderr}"
            ) from exc
        if not isinstance(provisioned, dict):
            raise SystemExit(
                "Pkg-installed stock Codex provisioner emitted non-object JSON "
                f"during clean-auth proof: {provisioned!r}"
            )
        provisioned_codex_path = Path(_json_string(provisioned, "codexPath")).resolve()
        provisioned_version = _json_string(provisioned, "version")
        if provisioned_version != stock_codex_version:
            raise SystemExit(
                "Clean-auth proof provisioned an unexpected stock Codex version.\n"
                f"expected={stock_codex_version!r}\nactual={provisioned_version!r}"
            )
        if not provisioned_codex_path.is_relative_to(clean_cache_root.resolve()):
            raise SystemExit(
                "Clean-auth proof provisioned Codex outside the clean cache root.\n"
                f"cache_root={clean_cache_root}\ncodex_path={provisioned_codex_path}"
            )

        clean_codex_home = root / "codex-home-clean"
        synthetic_codex_home = root / "codex-home-synthetic"
        real_classifier_home = root / "home-real-auth"
        clean_codex_home.mkdir()
        synthetic_codex_home.mkdir()
        real_classifier_home.mkdir()
        synthetic_secret = "sk-test-clean-auth-onboarding-proof"
        (synthetic_codex_home / "auth.json").write_text(
            json.dumps(
                {"auth_mode": "api", "OPENAI_API_KEY": synthetic_secret},
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

        real_classifier_path, real_reason, real_output = (
            _run_installed_runtime_auth_classifier(
                installed_runtime_root=installed_runtime_root,
                home=real_classifier_home,
                codex_home=real_auth_path.parent,
                stock_codex_path=provisioned_codex_path,
            )
        )
        if real_classifier_path != real_auth_path.expanduser().resolve():
            raise SystemExit(
                "Installed runtime auth classifier selected the wrong real auth path.\n"
                f"expected={real_auth_path}\nactual={real_classifier_path}"
            )
        if real_reason is not None:
            raise SystemExit(
                "Installed runtime auth classifier did not accept the real auth source.\n"
                f"expected=None\nactual={real_reason!r}"
            )

        clean_classifier_path, clean_reason, clean_output = (
            _run_installed_runtime_auth_classifier(
                installed_runtime_root=installed_runtime_root,
                home=clean_home,
                codex_home=clean_codex_home,
                stock_codex_path=provisioned_codex_path,
            )
        )
        if clean_classifier_path != (clean_codex_home / "auth.json").resolve():
            raise SystemExit(
                "Installed runtime auth classifier selected the wrong clean auth path.\n"
                f"expected={clean_codex_home / 'auth.json'}\n"
                f"actual={clean_classifier_path}"
            )
        if clean_reason != "needs-auth":
            raise SystemExit(
                "Installed runtime clean auth classification did not require onboarding.\n"
                f"expected=needs-auth\nactual={clean_reason!r}"
            )

        synthetic_classifier_path, synthetic_reason, synthetic_output = (
            _run_installed_runtime_auth_classifier(
                installed_runtime_root=installed_runtime_root,
                home=clean_home,
                codex_home=synthetic_codex_home,
                stock_codex_path=provisioned_codex_path,
            )
        )
        if synthetic_classifier_path != (synthetic_codex_home / "auth.json").resolve():
            raise SystemExit(
                "Installed runtime auth classifier selected the wrong synthetic auth path.\n"
                f"expected={synthetic_codex_home / 'auth.json'}\n"
                f"actual={synthetic_classifier_path}"
            )
        if synthetic_reason is not None:
            raise SystemExit(
                "Installed runtime synthetic auth classification did not report available.\n"
                f"expected=None\nactual={synthetic_reason!r}"
            )

        classifier_output = real_output + clean_output + synthetic_output
        credential_material_leaked = synthetic_secret in classifier_output
        if credential_material_leaked:
            raise SystemExit(
                "Installed runtime auth classifier leaked synthetic credential material."
            )
        onboarding_command = (
            f"CODEX_HOME={shlex.quote(str(clean_codex_home))} "
            f"{shlex.quote(str(provisioned_codex_path))} login"
        )

        return StockCodexCompatPkgCleanAuthProof(
            stock_codex_path=stock_codex_path,
            stock_codex_version=stock_codex_version,
            stock_codex_sha256=stock_codex_sha256,
            package_path=package_proof.package_path,
            package_sha256=package_proof.package_sha256,
            package_identifier=package_proof.package_identifier,
            package_version=package_proof.package_version,
            install_root=install_root,
            installed_prefix=installed_prefix,
            installed_runtime_root=installed_runtime_root,
            provisioner_script_path=provisioner_script_path,
            clean_home=clean_home,
            clean_cache_root=clean_cache_root,
            provisioned_codex_path=provisioned_codex_path,
            provisioned_version=provisioned_version,
            real_auth_path=real_auth_path,
            real_auth_source=real_auth_source,
            real_auth_available=real_auth_available,
            real_auth_classifier_path=real_classifier_path,
            real_auth_unavailable_reason=real_reason,
            clean_codex_home=clean_codex_home,
            clean_auth_classifier_path=clean_classifier_path,
            clean_unavailable_reason=str(clean_reason),
            synthetic_codex_home=synthetic_codex_home,
            synthetic_auth_classifier_path=synthetic_classifier_path,
            synthetic_available_reason=synthetic_reason,
            onboarding_command=onboarding_command,
            credential_material_leaked=credential_material_leaked,
        )


def print_stock_codex_compat_clean_install_proof(
    proof: StockCodexCompatCleanInstallProof,
) -> None:
    """Emit operator evidence for the clean-home compatibility install proof."""
    print("stock_codex_compat_clean_install_rehearsal=selected")
    print(
        "stock_codex_compat_clean_install_surface="
        "clean-home-separate-command-install-rollback"
    )
    print(f"stock_codex_compat_clean_install_stock_codex_path={proof.stock_codex_path}")
    print(
        "stock_codex_compat_clean_install_stock_codex_version="
        f"{proof.stock_codex_version}"
    )
    print(f"stock_codex_compat_clean_install_home={proof.clean_home}")
    print(f"stock_codex_compat_clean_install_bin_dir={proof.clean_bin_dir}")
    print(f"stock_codex_compat_clean_install_launcher_path={proof.launcher_path}")
    print(f"stock_codex_compat_clean_install_manifest_path={proof.manifest_path}")
    print(
        "stock_codex_compat_clean_install_adapter_package_dir="
        f"{proof.adapter_package_dir}"
    )
    print(f"stock_codex_compat_clean_install_adapter_bin={proof.adapter_bin}")
    print(f"stock_codex_compat_clean_install_adapter_manifest={proof.adapter_manifest}")
    print(
        "stock_codex_compat_clean_install_adapter_bridge_dir="
        f"{proof.adapter_bridge_dir}"
    )
    print(
        "stock_codex_compat_clean_install_adapter_tools="
        f"{','.join(proof.adapter_tool_names)}"
    )
    print(f"stock_codex_compat_clean_install_repo_root={proof.repo_root}")
    print(f"stock_codex_compat_clean_install_uvx_path={proof.uvx_path}")
    print(
        "stock_codex_compat_clean_install_selected_command_path="
        f"{proof.selected_command_path}"
    )
    print(f"stock_codex_compat_clean_install_version_output={proof.version_output}")
    print(
        "stock_codex_compat_clean_install_adapter_package_action="
        f"{proof.adapter_package_action}"
    )
    print(f"stock_codex_compat_clean_install_install_action={proof.install_action}")
    print(f"stock_codex_compat_clean_install_rollback_action={proof.rollback_action}")
    print(
        "stock_codex_compat_clean_install_doctor_install_allowed="
        f"{proof.doctor_install_allowed}"
    )
    print(
        "stock_codex_compat_clean_install_doctor_existing_target_state="
        f"{proof.doctor_existing_target_state}"
    )
    print(
        "stock_codex_compat_clean_install_doctor_existing_target_managed="
        f"{proof.doctor_existing_target_managed}"
    )
    print(
        "stock_codex_compat_clean_install_doctor_target_selected_on_path="
        f"{proof.doctor_target_selected_on_path}"
    )
    print(
        "stock_codex_compat_clean_install_doctor_mutates_filesystem="
        f"{proof.doctor_mutates_filesystem}"
    )
    print(
        "stock_codex_compat_clean_install_launcher_removed_after_rollback="
        f"{proof.launcher_removed_after_rollback}"
    )
    print(
        "stock_codex_compat_clean_install_manifest_removed_after_rollback="
        f"{proof.manifest_removed_after_rollback}"
    )
    print(
        "stock_codex_compat_clean_install_probe_output="
        f"{_preview_text(proof.probe_output, limit=1000)!r}"
    )
    print("stock_codex_compat_clean_install_cache_lifecycle=temporary_removed_after_proof")
    print(
        "ASSERTION: stock-codex-compat can install its adapter package and "
        "separate launcher command from defaults under a clean HOME"
    )
    print(
        "ASSERTION: clean-home install, doctor, probe, version delegation, and "
        "rollback are repeatable without mutating the current host codex default"
    )


def print_stock_codex_compat_bundle_install_proof(
    proof: StockCodexCompatBundleInstallProof,
) -> None:
    """Emit operator evidence for the bundle compatibility install proof."""
    print("stock_codex_compat_bundle_install_rehearsal=selected")
    print(
        "stock_codex_compat_bundle_install_surface="
        "portable-bundle-clean-home-install-rollback"
    )
    print(f"stock_codex_compat_bundle_install_stock_codex_path={proof.stock_codex_path}")
    print(
        "stock_codex_compat_bundle_install_stock_codex_version="
        f"{proof.stock_codex_version}"
    )
    print(f"stock_codex_compat_bundle_install_bundle_path={proof.bundle_path}")
    print(f"stock_codex_compat_bundle_install_bundle_sha256={proof.bundle_sha256}")
    print(
        "stock_codex_compat_bundle_install_bundle_manifest="
        f"{proof.bundle_manifest_path}"
    )
    print(
        "stock_codex_compat_bundle_install_extracted_bundle_root="
        f"{proof.extracted_bundle_root}"
    )
    print(
        "stock_codex_compat_bundle_install_extracted_runtime_root="
        f"{proof.extracted_runtime_root}"
    )
    print(
        "stock_codex_compat_bundle_install_installer_script="
        f"{proof.installer_script_path}"
    )
    print(f"stock_codex_compat_bundle_install_home={proof.clean_home}")
    print(f"stock_codex_compat_bundle_install_bin_dir={proof.clean_bin_dir}")
    print(f"stock_codex_compat_bundle_install_launcher_path={proof.launcher_path}")
    print(f"stock_codex_compat_bundle_install_manifest_path={proof.manifest_path}")
    print(
        "stock_codex_compat_bundle_install_adapter_package_dir="
        f"{proof.adapter_package_dir}"
    )
    print(f"stock_codex_compat_bundle_install_adapter_bin={proof.adapter_bin}")
    print(
        "stock_codex_compat_bundle_install_adapter_manifest="
        f"{proof.adapter_manifest}"
    )
    print(
        "stock_codex_compat_bundle_install_adapter_bridge_dir="
        f"{proof.adapter_bridge_dir}"
    )
    print(
        "stock_codex_compat_bundle_install_adapter_tools="
        f"{','.join(proof.adapter_tool_names)}"
    )
    print(f"stock_codex_compat_bundle_install_uvx_path={proof.uvx_path}")
    print(
        "stock_codex_compat_bundle_install_selected_command_path="
        f"{proof.selected_command_path}"
    )
    print(
        "stock_codex_compat_bundle_install_launcher_manifest_repo_root="
        f"{proof.launcher_manifest_repo_root}"
    )
    print(f"stock_codex_compat_bundle_install_version_output={proof.version_output}")
    print(
        "stock_codex_compat_bundle_install_adapter_package_action="
        f"{proof.adapter_package_action}"
    )
    print(f"stock_codex_compat_bundle_install_install_action={proof.install_action}")
    print(f"stock_codex_compat_bundle_install_rollback_action={proof.rollback_action}")
    print(
        "stock_codex_compat_bundle_install_doctor_install_allowed="
        f"{proof.doctor_install_allowed}"
    )
    print(
        "stock_codex_compat_bundle_install_doctor_existing_target_state="
        f"{proof.doctor_existing_target_state}"
    )
    print(
        "stock_codex_compat_bundle_install_doctor_existing_target_managed="
        f"{proof.doctor_existing_target_managed}"
    )
    print(
        "stock_codex_compat_bundle_install_doctor_target_selected_on_path="
        f"{proof.doctor_target_selected_on_path}"
    )
    print(
        "stock_codex_compat_bundle_install_doctor_mutates_filesystem="
        f"{proof.doctor_mutates_filesystem}"
    )
    print(
        "stock_codex_compat_bundle_install_launcher_removed_after_rollback="
        f"{proof.launcher_removed_after_rollback}"
    )
    print(
        "stock_codex_compat_bundle_install_manifest_removed_after_rollback="
        f"{proof.manifest_removed_after_rollback}"
    )
    print(
        "stock_codex_compat_bundle_install_probe_output="
        f"{_preview_text(proof.probe_output, limit=1000)!r}"
    )
    print("stock_codex_compat_bundle_install_cache_lifecycle=temporary_removed_after_proof")
    print(
        "ASSERTION: stock-codex-compat can be packaged as a portable runtime "
        "bundle and installed from the extracted artifact under a clean HOME"
    )
    print(
        "ASSERTION: the installed launcher manifest and probe delegate to the "
        "extracted bundle runtime, not the development checkout"
    )


def print_stock_codex_compat_pkg_structure_proof(
    proof: StockCodexCompatPkgStructureProof,
) -> None:
    """Emit operator evidence for the unsigned pkg structure proof."""
    print("stock_codex_compat_pkg_structure_rehearsal=selected")
    print("stock_codex_compat_pkg_structure_surface=unsigned-flat-pkg-structure")
    print(f"stock_codex_compat_pkg_structure_package_path={proof.package_path}")
    print(f"stock_codex_compat_pkg_structure_package_sha256={proof.package_sha256}")
    print(
        "stock_codex_compat_pkg_structure_source_bundle_sha256="
        f"{proof.source_bundle_sha256}"
    )
    print(
        "stock_codex_compat_pkg_structure_identifier="
        f"{proof.package_identifier}"
    )
    print(f"stock_codex_compat_pkg_structure_version={proof.package_version}")
    print(
        "stock_codex_compat_pkg_structure_install_location="
        f"{proof.install_location}"
    )
    print(f"stock_codex_compat_pkg_structure_install_prefix={proof.install_prefix}")
    print(f"stock_codex_compat_pkg_structure_runtime_root={proof.runtime_root}")
    print(
        "stock_codex_compat_pkg_structure_payload_file_count="
        f"{proof.payload_file_count}"
    )
    print(
        "stock_codex_compat_pkg_structure_required_payload_files="
        f"{json.dumps(proof.required_payload_files, sort_keys=True)}"
    )
    print(
        "stock_codex_compat_pkg_structure_scripts="
        f"{','.join(proof.script_names)}"
    )
    print(
        "stock_codex_compat_pkg_structure_archive_entries="
        f"{','.join(proof.archive_entries)}"
    )
    print(
        "stock_codex_compat_pkg_structure_signature_status="
        f"{proof.signature_status}"
    )
    print(f"stock_codex_compat_pkg_structure_signed={proof.signed}")
    print(
        "stock_codex_compat_pkg_structure_pkg_manifest="
        f"{proof.pkg_manifest_path}"
    )
    print(
        "stock_codex_compat_pkg_structure_bundle_manifest="
        f"{proof.bundle_manifest_path}"
    )
    print(
        "stock_codex_compat_pkg_structure_contract="
        f"{json.dumps(proof.pkg_contract, sort_keys=True)}"
    )
    print(
        "stock_codex_compat_pkg_structure_bundle_source_root="
        f"{proof.bundle_source_root}"
    )
    print("stock_codex_compat_pkg_structure_artifact_lifecycle=temporary_removed_after_proof")
    print(
        "ASSERTION: stock-codex-compat can be packaged as an unsigned flat "
        "macOS pkg with sane identifier, version, install root, scripts, and "
        "runtime payload layout"
    )
    print(
        "ASSERTION: the pkg installs only the machine-level runtime payload; "
        "user bootstrap, stock-Codex provisioning, auth, signing, and "
        "notarization remain separate gates"
    )


def print_stock_codex_compat_pkg_signed_notarized_proof(
    proof: StockCodexCompatPkgSignedNotarizedProof,
) -> None:
    """Emit operator evidence for the signed/notarized pkg proof."""
    print("stock_codex_compat_pkg_signed_notarized_rehearsal=selected")
    print("stock_codex_compat_pkg_signed_notarized_surface=signed-notarized-pkg")
    print(f"stock_codex_compat_pkg_signed_notarized_status={proof.status}")
    print(
        "stock_codex_compat_pkg_signed_notarized_missing_prerequisites="
        f"{json.dumps(list(proof.missing_prerequisites), sort_keys=True)}"
    )
    print(
        "stock_codex_compat_pkg_signed_notarized_tool_paths="
        f"{json.dumps(proof.tool_paths, sort_keys=True)}"
    )
    print(
        "stock_codex_compat_pkg_signed_notarized_sign_identity="
        f"{proof.sign_identity}"
    )
    print(
        "stock_codex_compat_pkg_signed_notarized_sign_identity_source="
        f"{proof.sign_identity_source}"
    )
    print(
        "stock_codex_compat_pkg_signed_notarized_signing_keychain="
        f"{proof.signing_keychain}"
    )
    print(
        "stock_codex_compat_pkg_signed_notarized_notarytool_profile="
        f"{proof.notarytool_profile}"
    )
    print(
        "stock_codex_compat_pkg_signed_notarized_developer_id_installer_count="
        f"{len(proof.developer_id_installer_identities)}"
    )
    print(
        "stock_codex_compat_pkg_signed_notarized_developer_id_application_count="
        f"{len(proof.developer_id_application_identities)}"
    )
    print(f"stock_codex_compat_pkg_signed_notarized_package_path={proof.package_path}")
    print(f"stock_codex_compat_pkg_signed_notarized_package_sha256={proof.package_sha256}")
    print(
        "stock_codex_compat_pkg_signed_notarized_source_bundle_sha256="
        f"{proof.source_bundle_sha256}"
    )
    print(
        "stock_codex_compat_pkg_signed_notarized_identifier="
        f"{proof.package_identifier}"
    )
    print(f"stock_codex_compat_pkg_signed_notarized_version={proof.package_version}")
    print(
        "stock_codex_compat_pkg_signed_notarized_signature_status="
        f"{proof.signature_status}"
    )
    print(f"stock_codex_compat_pkg_signed_notarized_signed={proof.signed}")
    print(
        "stock_codex_compat_pkg_signed_notarized_notary_submission_id="
        f"{proof.notary_submission_id}"
    )
    print(f"stock_codex_compat_pkg_signed_notarized_notary_status={proof.notary_status}")
    print(
        "stock_codex_compat_pkg_signed_notarized_notary_output="
        f"{proof.notary_output_preview!r}"
    )
    print(
        "stock_codex_compat_pkg_signed_notarized_staple_output="
        f"{proof.staple_output_preview!r}"
    )
    print(
        "stock_codex_compat_pkg_signed_notarized_stapler_validate_output="
        f"{proof.stapler_validate_output_preview!r}"
    )
    print(
        "stock_codex_compat_pkg_signed_notarized_gatekeeper_output="
        f"{proof.gatekeeper_output_preview!r}"
    )
    if proof.status == "blocked":
        print(
            "ASSERTION: signed/notarized pkg validation is blocked by local "
            "signing or notary prerequisites, not by the compatibility runtime "
            "or unsigned package contract"
        )
        return
    print(
        "ASSERTION: stock-codex-compat can be built as a Developer ID signed "
        "pkg, notarized, stapled, validated by stapler, and accepted by "
        "Gatekeeper for installation"
    )


def print_stock_codex_compat_pkg_clean_provision_proof(
    proof: StockCodexCompatPkgCleanProvisionProof,
) -> None:
    """Emit operator evidence for installed-runtime clean stock Codex provisioning."""
    print("stock_codex_compat_pkg_clean_provision_rehearsal=selected")
    print(
        "stock_codex_compat_pkg_clean_provision_surface="
        "pkg-installed-runtime-clean-stock-codex-channel-provision"
    )
    print(f"stock_codex_compat_pkg_clean_provision_stock_codex_path={proof.stock_codex_path}")
    print(
        "stock_codex_compat_pkg_clean_provision_stock_codex_version="
        f"{proof.stock_codex_version}"
    )
    print(
        "stock_codex_compat_pkg_clean_provision_stock_codex_sha256="
        f"{proof.stock_codex_sha256}"
    )
    print(f"stock_codex_compat_pkg_clean_provision_package_path={proof.package_path}")
    print(f"stock_codex_compat_pkg_clean_provision_package_sha256={proof.package_sha256}")
    print(
        "stock_codex_compat_pkg_clean_provision_identifier="
        f"{proof.package_identifier}"
    )
    print(f"stock_codex_compat_pkg_clean_provision_version={proof.package_version}")
    print(f"stock_codex_compat_pkg_clean_provision_install_root={proof.install_root}")
    print(f"stock_codex_compat_pkg_clean_provision_installed_prefix={proof.installed_prefix}")
    print(
        "stock_codex_compat_pkg_clean_provision_installed_runtime_root="
        f"{proof.installed_runtime_root}"
    )
    print(
        "stock_codex_compat_pkg_clean_provision_provisioner_script="
        f"{proof.provisioner_script_path}"
    )
    print(f"stock_codex_compat_pkg_clean_provision_pkg_manifest={proof.pkg_manifest_path}")
    print(
        "stock_codex_compat_pkg_clean_provision_bundle_manifest="
        f"{proof.bundle_manifest_path}"
    )
    print(f"stock_codex_compat_pkg_clean_provision_home={proof.clean_home}")
    print(f"stock_codex_compat_pkg_clean_provision_cache_root={proof.clean_cache_root}")
    print(
        "stock_codex_compat_pkg_clean_provision_channel_manifest="
        f"{proof.channel_manifest_path}"
    )
    print(
        "stock_codex_compat_pkg_clean_provision_channel_artifact="
        f"{proof.channel_artifact_path}"
    )
    print(f"stock_codex_compat_pkg_clean_provision_payload_dir={proof.payload_dir}")
    print(
        "stock_codex_compat_pkg_clean_provision_codex_path="
        f"{proof.provisioned_codex_path}"
    )
    print(
        "stock_codex_compat_pkg_clean_provision_manifest="
        f"{proof.provisioned_manifest_path}"
    )
    print(
        "stock_codex_compat_pkg_clean_provision_provisioned_version="
        f"{proof.provisioned_version}"
    )
    print(
        "stock_codex_compat_pkg_clean_provision_provisioned_sha256="
        f"{proof.provisioned_sha256}"
    )
    print(
        "stock_codex_compat_pkg_clean_provision_source_kind="
        f"{proof.provisioned_source_kind}"
    )
    print(
        "stock_codex_compat_pkg_clean_provision_env="
        f"{OMNIGENT_STOCK_CODEX_PATH_ENV}={proof.provisioned_env_path}"
    )
    print(
        "stock_codex_compat_pkg_clean_provision_omnigent_resolved_codex_path="
        f"{proof.omnigent_resolved_codex_path}"
    )
    print(
        "stock_codex_compat_pkg_clean_provision_reuse_payload_dir="
        f"{proof.reuse_payload_dir}"
    )
    print(
        "stock_codex_compat_pkg_clean_provision_reuse_codex_path="
        f"{proof.reuse_provisioned_codex_path}"
    )
    print(
        "stock_codex_compat_pkg_clean_provision_host_cache_root="
        f"{proof.host_cache_root}"
    )
    print(
        "stock_codex_compat_pkg_clean_provision_host_cache_referenced="
        f"{proof.host_cache_referenced}"
    )
    print("stock_codex_compat_pkg_clean_provision_cache_lifecycle=temporary_removed_after_proof")
    print(
        "ASSERTION: a pkg-installed machine-level runtime can provision a "
        "verified stock Codex payload into a clean user cache from an explicit "
        "channel artifact without using the host stock-Codex cache"
    )
    print(
        "ASSERTION: the clean-provisioned payload is selected by Omnigent "
        f"through {OMNIGENT_STOCK_CODEX_PATH_ENV}, and a second no-force "
        "provision reuses the same verified payload"
    )


def print_stock_codex_compat_pkg_clean_auth_proof(
    proof: StockCodexCompatPkgCleanAuthProof,
) -> None:
    """Emit operator evidence for installed-runtime clean auth onboarding."""
    print("stock_codex_compat_pkg_clean_auth_rehearsal=selected")
    print(
        "stock_codex_compat_pkg_clean_auth_surface="
        "pkg-installed-runtime-clean-stock-codex-auth-onboarding"
    )
    print(f"stock_codex_compat_pkg_clean_auth_stock_codex_path={proof.stock_codex_path}")
    print(
        "stock_codex_compat_pkg_clean_auth_stock_codex_version="
        f"{proof.stock_codex_version}"
    )
    print(
        "stock_codex_compat_pkg_clean_auth_stock_codex_sha256="
        f"{proof.stock_codex_sha256}"
    )
    print(f"stock_codex_compat_pkg_clean_auth_package_path={proof.package_path}")
    print(f"stock_codex_compat_pkg_clean_auth_package_sha256={proof.package_sha256}")
    print(
        "stock_codex_compat_pkg_clean_auth_identifier="
        f"{proof.package_identifier}"
    )
    print(f"stock_codex_compat_pkg_clean_auth_version={proof.package_version}")
    print(f"stock_codex_compat_pkg_clean_auth_install_root={proof.install_root}")
    print(f"stock_codex_compat_pkg_clean_auth_installed_prefix={proof.installed_prefix}")
    print(
        "stock_codex_compat_pkg_clean_auth_installed_runtime_root="
        f"{proof.installed_runtime_root}"
    )
    print(
        "stock_codex_compat_pkg_clean_auth_provisioner_script="
        f"{proof.provisioner_script_path}"
    )
    print(f"stock_codex_compat_pkg_clean_auth_home={proof.clean_home}")
    print(f"stock_codex_compat_pkg_clean_auth_cache_root={proof.clean_cache_root}")
    print(
        "stock_codex_compat_pkg_clean_auth_provisioned_codex_path="
        f"{proof.provisioned_codex_path}"
    )
    print(
        "stock_codex_compat_pkg_clean_auth_provisioned_version="
        f"{proof.provisioned_version}"
    )
    print(f"stock_codex_compat_pkg_clean_auth_real_auth_path={proof.real_auth_path}")
    print(f"stock_codex_compat_pkg_clean_auth_real_auth_source={proof.real_auth_source}")
    print(
        "stock_codex_compat_pkg_clean_auth_real_auth_available="
        f"{proof.real_auth_available}"
    )
    print(
        "stock_codex_compat_pkg_clean_auth_real_classifier_path="
        f"{proof.real_auth_classifier_path}"
    )
    print(
        "stock_codex_compat_pkg_clean_auth_real_unavailable_reason="
        f"{proof.real_auth_unavailable_reason}"
    )
    print(f"stock_codex_compat_pkg_clean_auth_clean_codex_home={proof.clean_codex_home}")
    print(
        "stock_codex_compat_pkg_clean_auth_clean_classifier_path="
        f"{proof.clean_auth_classifier_path}"
    )
    print(
        "stock_codex_compat_pkg_clean_auth_clean_unavailable_reason="
        f"{proof.clean_unavailable_reason}"
    )
    print(
        "stock_codex_compat_pkg_clean_auth_synthetic_codex_home="
        f"{proof.synthetic_codex_home}"
    )
    print(
        "stock_codex_compat_pkg_clean_auth_synthetic_classifier_path="
        f"{proof.synthetic_auth_classifier_path}"
    )
    print(
        "stock_codex_compat_pkg_clean_auth_synthetic_available_reason="
        f"{proof.synthetic_available_reason}"
    )
    print(
        "stock_codex_compat_pkg_clean_auth_credential_material_leaked="
        f"{proof.credential_material_leaked}"
    )
    print(
        "stock_codex_compat_pkg_clean_auth_onboarding_command="
        f"{proof.onboarding_command}"
    )
    print("stock_codex_compat_pkg_clean_auth_cache_lifecycle=temporary_removed_after_proof")
    print(
        "ASSERTION: the pkg-installed runtime classifies a clean CODEX_HOME "
        "as needs-auth while using the clean-provisioned stock Codex binary"
    )
    print(
        "ASSERTION: the pkg-installed runtime recognizes both the current real "
        "auth source and a synthetic populated auth.json without printing "
        "credential material"
    )


def print_stock_codex_compat_pkg_runtime_live_proof(
    proof: StockCodexCompatPkgRuntimeLiveProof,
) -> None:
    """Emit operator evidence for the expanded pkg runtime live proof."""
    print("stock_codex_compat_pkg_runtime_live_rehearsal=selected")
    print(
        "stock_codex_compat_pkg_runtime_live_surface="
        "expanded-pkg-runtime-uvx-wrapper-live-model-turn"
    )
    print(f"stock_codex_compat_pkg_runtime_live_stock_codex_path={proof.stock_codex_path}")
    print(
        "stock_codex_compat_pkg_runtime_live_stock_codex_version="
        f"{proof.stock_codex_version}"
    )
    print(f"stock_codex_compat_pkg_runtime_live_source_bundle={proof.source_bundle}")
    print(f"stock_codex_compat_pkg_runtime_live_package_path={proof.package_path}")
    print(f"stock_codex_compat_pkg_runtime_live_package_sha256={proof.package_sha256}")
    print(
        "stock_codex_compat_pkg_runtime_live_source_bundle_sha256="
        f"{proof.source_bundle_sha256}"
    )
    print(
        "stock_codex_compat_pkg_runtime_live_identifier="
        f"{proof.package_identifier}"
    )
    print(f"stock_codex_compat_pkg_runtime_live_version={proof.package_version}")
    print(f"stock_codex_compat_pkg_runtime_live_install_prefix={proof.install_prefix}")
    print(
        "stock_codex_compat_pkg_runtime_live_packaged_runtime_root="
        f"{proof.packaged_runtime_root}"
    )
    print(
        "stock_codex_compat_pkg_runtime_live_expanded_payload_root="
        f"{proof.expanded_payload_root}"
    )
    print(
        "stock_codex_compat_pkg_runtime_live_expanded_runtime_root="
        f"{proof.expanded_runtime_root}"
    )
    print(f"stock_codex_compat_pkg_runtime_live_uvx_path={proof.uvx_path}")
    print(
        "stock_codex_compat_pkg_runtime_live_wrapper_command="
        f"{shlex.join(proof.wrapper_command)}"
    )
    print(f"stock_codex_compat_pkg_runtime_live_codex_home={proof.codex_home}")
    print(f"stock_codex_compat_pkg_runtime_live_auth_path={proof.auth_path}")
    print(f"stock_codex_compat_pkg_runtime_live_bridge_dir={proof.bridge_dir}")
    print(f"stock_codex_compat_pkg_runtime_live_workspace_root={proof.workspace_root}")
    print(
        "stock_codex_compat_pkg_runtime_live_enabled_features="
        f"{','.join(proof.enabled_features)}"
    )
    print(f"stock_codex_compat_pkg_runtime_live_thread_id={proof.thread_id}")
    print(f"stock_codex_compat_pkg_runtime_live_event_count={proof.event_count}")
    print(
        "stock_codex_compat_pkg_runtime_live_mcp_servers="
        f"{','.join(proof.mcp_servers)}"
    )
    print(f"stock_codex_compat_pkg_runtime_live_route_injected={proof.route_injected}")
    print(
        "stock_codex_compat_pkg_runtime_live_evidence_path="
        f"{proof.wrapper_evidence_path}"
    )
    print(
        "stock_codex_compat_pkg_runtime_live_pre_wrapper_message_preview="
        f"{_preview_text(proof.first_agent_message_before_wrapper, limit=500)!r}"
    )
    print(
        "stock_codex_compat_pkg_runtime_live_first_agent_message_preview="
        f"{_preview_text(proof.first_agent_message, limit=500)!r}"
    )
    print(f"stock_codex_compat_pkg_runtime_live_stderr_preview={proof.stderr_preview!r}")
    print("stock_codex_compat_pkg_runtime_live_cache_lifecycle=temporary_removed_after_proof")
    print(
        "ASSERTION: an expanded unsigned pkg runtime launched a real stock "
        "Codex model turn through uvx --from without using the development "
        "checkout as the wrapper runtime"
    )
    print(
        "ASSERTION: known-good stock auth was reused; package install, "
        "per-user bootstrap, clean stock-Codex provisioning, clean auth "
        "onboarding, signing, and notarization remain separate gates"
    )


def print_stock_codex_compat_pkg_user_bootstrap_proof(
    proof: StockCodexCompatPkgUserBootstrapProof,
) -> None:
    """Emit operator evidence for the installed-runtime user bootstrap proof."""
    print("stock_codex_compat_pkg_user_bootstrap_rehearsal=selected")
    print(
        "stock_codex_compat_pkg_user_bootstrap_surface="
        "pkg-installed-runtime-clean-user-bootstrap-update-rollback"
    )
    print(f"stock_codex_compat_pkg_user_bootstrap_stock_codex_path={proof.stock_codex_path}")
    print(
        "stock_codex_compat_pkg_user_bootstrap_stock_codex_version="
        f"{proof.stock_codex_version}"
    )
    print(f"stock_codex_compat_pkg_user_bootstrap_package_path={proof.package_path}")
    print(f"stock_codex_compat_pkg_user_bootstrap_package_sha256={proof.package_sha256}")
    print(
        "stock_codex_compat_pkg_user_bootstrap_identifier="
        f"{proof.package_identifier}"
    )
    print(f"stock_codex_compat_pkg_user_bootstrap_version={proof.package_version}")
    print(f"stock_codex_compat_pkg_user_bootstrap_install_root={proof.install_root}")
    print(f"stock_codex_compat_pkg_user_bootstrap_installed_prefix={proof.installed_prefix}")
    print(
        "stock_codex_compat_pkg_user_bootstrap_installed_runtime_root="
        f"{proof.installed_runtime_root}"
    )
    print(
        "stock_codex_compat_pkg_user_bootstrap_installer_script="
        f"{proof.installer_script_path}"
    )
    print(f"stock_codex_compat_pkg_user_bootstrap_pkg_manifest={proof.pkg_manifest_path}")
    print(
        "stock_codex_compat_pkg_user_bootstrap_bundle_manifest="
        f"{proof.bundle_manifest_path}"
    )
    print(f"stock_codex_compat_pkg_user_bootstrap_home={proof.clean_home}")
    print(f"stock_codex_compat_pkg_user_bootstrap_bin_dir={proof.clean_bin_dir}")
    print(f"stock_codex_compat_pkg_user_bootstrap_launcher_path={proof.launcher_path}")
    print(f"stock_codex_compat_pkg_user_bootstrap_manifest_path={proof.manifest_path}")
    print(
        "stock_codex_compat_pkg_user_bootstrap_adapter_package_dir="
        f"{proof.adapter_package_dir}"
    )
    print(f"stock_codex_compat_pkg_user_bootstrap_adapter_bin={proof.adapter_bin}")
    print(
        "stock_codex_compat_pkg_user_bootstrap_adapter_manifest="
        f"{proof.adapter_manifest}"
    )
    print(
        "stock_codex_compat_pkg_user_bootstrap_adapter_bridge_dir="
        f"{proof.adapter_bridge_dir}"
    )
    print(
        "stock_codex_compat_pkg_user_bootstrap_adapter_tools="
        f"{','.join(proof.adapter_tool_names)}"
    )
    print(f"stock_codex_compat_pkg_user_bootstrap_uvx_path={proof.uvx_path}")
    print(
        "stock_codex_compat_pkg_user_bootstrap_selected_command_path="
        f"{proof.selected_command_path}"
    )
    print(
        "stock_codex_compat_pkg_user_bootstrap_launcher_manifest_repo_root="
        f"{proof.launcher_manifest_repo_root}"
    )
    print(
        "stock_codex_compat_pkg_user_bootstrap_launcher_manifest_wrapper_entrypoint="
        f"{proof.launcher_manifest_wrapper_entrypoint}"
    )
    print(
        "stock_codex_compat_pkg_user_bootstrap_launcher_manifest_adapter_tools="
        f"{','.join(proof.launcher_manifest_adapter_tool_names)}"
    )
    print(f"stock_codex_compat_pkg_user_bootstrap_version_output={proof.version_output}")
    print(
        "stock_codex_compat_pkg_user_bootstrap_adapter_package_action="
        f"{proof.adapter_package_action}"
    )
    print(f"stock_codex_compat_pkg_user_bootstrap_install_action={proof.install_action}")
    print(f"stock_codex_compat_pkg_user_bootstrap_update_action={proof.update_action}")
    print(
        "stock_codex_compat_pkg_user_bootstrap_rollback_command="
        f"{proof.rollback_command}"
    )
    print(f"stock_codex_compat_pkg_user_bootstrap_rollback_action={proof.rollback_action}")
    print(
        "stock_codex_compat_pkg_user_bootstrap_doctor_install_allowed="
        f"{proof.doctor_install_allowed}"
    )
    print(
        "stock_codex_compat_pkg_user_bootstrap_doctor_existing_target_state="
        f"{proof.doctor_existing_target_state}"
    )
    print(
        "stock_codex_compat_pkg_user_bootstrap_doctor_existing_target_managed="
        f"{proof.doctor_existing_target_managed}"
    )
    print(
        "stock_codex_compat_pkg_user_bootstrap_doctor_target_selected_on_path="
        f"{proof.doctor_target_selected_on_path}"
    )
    print(
        "stock_codex_compat_pkg_user_bootstrap_doctor_mutates_filesystem="
        f"{proof.doctor_mutates_filesystem}"
    )
    print(
        "stock_codex_compat_pkg_user_bootstrap_adapter_package_exists_after_install="
        f"{proof.adapter_package_exists_after_install}"
    )
    print(
        "stock_codex_compat_pkg_user_bootstrap_launcher_removed_after_rollback="
        f"{proof.launcher_removed_after_rollback}"
    )
    print(
        "stock_codex_compat_pkg_user_bootstrap_manifest_removed_after_rollback="
        f"{proof.manifest_removed_after_rollback}"
    )
    print(
        "stock_codex_compat_pkg_user_bootstrap_probe_output="
        f"{_preview_text(proof.probe_output, limit=1000)!r}"
    )
    print("stock_codex_compat_pkg_user_bootstrap_cache_lifecycle=temporary_removed_after_proof")
    print(
        "ASSERTION: a pkg-installed machine-level runtime can bootstrap a "
        "clean user's compatibility launcher, adapter package, manifest, and "
        "bridge path without touching the current host profile"
    )
    print(
        "ASSERTION: the generated rollback command targets the installed "
        "runtime and was executed successfully to remove the launcher and "
        "manifest"
    )


def run_stock_codex_compat_launcher_activation_proof(
    *,
    timeout_seconds: float = DEFAULT_LIVE_PROOF_TIMEOUT_SECONDS,
) -> StockCodexCompatLauncherActivationProof:
    """Prove the persistent compatibility launcher can be the active ``codex``."""
    uvx_raw = shutil.which("uvx")
    if not uvx_raw:
        raise SystemExit("Could not find uvx on PATH for compatibility launcher proof.")
    uvx_path = Path(uvx_raw).expanduser().resolve()
    if not uvx_path.is_file() or not os.access(uvx_path, os.X_OK):
        raise SystemExit(f"uvx binary is not executable: {uvx_path}")

    installer = _load_stock_codex_compat_launcher_installer()
    repo_root = Path(__file__).resolve().parents[1]
    original_path = os.environ.get("PATH", "")
    with tempfile.TemporaryDirectory(
        prefix="omnigent-stock-codex-compat-launcher-proof-"
    ) as temp_root:
        root = Path(temp_root).resolve()
        launcher_dir = root / "bin"
        fake_bin = root / "fake-bin"
        stock_codex_path = root / "stock-codex" / "codex"
        launcher_path = launcher_dir / "codex"
        manifest_path = root / "launcher-manifest.json"
        workspace_root = root / "workspace"
        adapter_bridge_dir = root / "adapter-bridge"
        wrapper_evidence_path = root / "wrapper-evidence.json"
        launcher_dir.mkdir()
        fake_bin.mkdir()
        workspace_root.mkdir(mode=0o700)
        _write_stock_codex_compat_launcher_fake_sosumi(fake_bin / "sosumi")
        _write_stock_codex_compat_launcher_fake_codex(stock_codex_path)
        stock_codex_version = codex_version(stock_codex_path)
        adapter_package = write_stock_codex_compat_adapter_package(
            root / "adapter-package",
            (build_fetch_apple_docs_stock_codex_bridge_adapter_spec(),),
        )

        activated_path = f"{launcher_dir}{os.pathsep}{fake_bin}{os.pathsep}{original_path}"
        previous_pinned_env = os.environ.pop(OMNIGENT_STOCK_CODEX_PATH_ENV, None)
        try:
            with temporary_env({"PATH": activated_path}):
                install_result = installer.install_launcher(
                    launcher_path=launcher_path,
                    manifest_path=manifest_path,
                    repo_root=repo_root,
                    uvx_path=uvx_path,
                    pinned_codex_path=stock_codex_path,
                    route_prefix=EXPECTED_ROUTE,
                    adapter_bin=adapter_package.adapter_bin,
                    adapter_manifest=adapter_package.manifest_path,
                    adapter_bridge_dir=adapter_bridge_dir,
                    backup_existing=False,
                    force=False,
                    require_path_selected=True,
                    validate=True,
                )
                resolved_raw = _find_codex_cli()
                if resolved_raw is None:
                    raise SystemExit(
                        "Compatibility launcher proof did not resolve a Codex binary."
                    )
                resolved_codex_path = Path(resolved_raw).expanduser().resolve()
                if resolved_codex_path != stock_codex_path.resolve():
                    raise SystemExit(
                        "Compatibility launcher proof resolved the wrong stock Codex.\n"
                        f"expected={stock_codex_path.resolve()}\n"
                        f"actual={resolved_codex_path}"
                    )
                probe = subprocess.run(
                    ["codex", installer.PROBE_ARG],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                probe_output = (probe.stdout or "") + (probe.stderr or "")
                if probe.returncode != 0 or installer.PROBE_SENTINEL not in probe_output:
                    raise SystemExit(
                        "Compatibility launcher probe failed.\n"
                        f"exit={probe.returncode}\n"
                        f"output={probe_output}"
                    )
                prompt = (
                    "Persistent stock Codex compatibility launcher proof. Use the "
                    f"shell command tool exactly once to run `{APPLE_DOCS_CLI_TOOL} "
                    f"--url {APPLE_DOCS_CLI_URL}`. Reply exactly "
                    f"{STOCK_CODEX_COMPAT_LAUNCHER_ACTIVATION_SENTINEL} if stdout "
                    "contains title: String and the Apple documentation source URL."
                )
                run_env = os.environ.copy()
                run_env[STOCK_CODEX_COMPAT_WRAPPER_EVIDENCE_ENV] = str(
                    wrapper_evidence_path
                )
                completed = subprocess.run(
                    [
                        "codex",
                        "exec",
                        "--json",
                        "--skip-git-repo-check",
                        "--sandbox",
                        "workspace-write",
                        "-C",
                        str(workspace_root),
                        prompt,
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=timeout_seconds if timeout_seconds > 0 else None,
                    env=run_env,
                    stdin=subprocess.DEVNULL,
                )
                stderr_preview = _preview_text(completed.stderr, limit=2000)
                if completed.returncode != 0:
                    raise SystemExit(
                        "Compatibility launcher wrapped command failed.\n"
                        f"exit={completed.returncode}\n"
                        f"stderr={stderr_preview}\n"
                        f"stdout_preview={_preview_text(completed.stdout, limit=2000)}"
                    )
                events = _parse_stock_codex_exec_jsonl(completed.stdout)
                thread_id, first_agent_message = (
                    _extract_stock_codex_thread_and_agent_message(
                        events,
                        proof_name="stock-codex-compat-launcher-activation",
                    )
                )
                if not first_agent_message.startswith(EXPECTED_ROUTE):
                    raise SystemExit(
                        "Compatibility launcher proof did not prefix route evidence.\n"
                        f"expected_prefix={EXPECTED_ROUTE!r}\n"
                        f"first_agent_message={first_agent_message!r}"
                    )
                if (
                    STOCK_CODEX_COMPAT_LAUNCHER_ACTIVATION_SENTINEL
                    not in first_agent_message
                ):
                    raise SystemExit(
                        "Compatibility launcher proof missed the expected sentinel.\n"
                        f"sentinel={STOCK_CODEX_COMPAT_LAUNCHER_ACTIVATION_SENTINEL!r}\n"
                        f"first_agent_message={first_agent_message!r}"
                    )
                command_item = _validate_stock_codex_adapter_command_execution_events(
                    events,
                    command_name=APPLE_DOCS_CLI_TOOL,
                    command_argument=APPLE_DOCS_CLI_URL,
                    output_sentinel=APPLE_MCP_SOSUMI_SENTINELS[0],
                )
                command_output = str(command_item["aggregated_output"])
                for output_sentinel in APPLE_MCP_SOSUMI_SENTINELS:
                    if output_sentinel not in command_output:
                        raise SystemExit(
                            "Compatibility launcher adapter output missed sentinel "
                            f"{output_sentinel!r}: {command_item!r}"
                        )
                wrapper_evidence = _read_stock_codex_compat_wrapper_evidence(
                    wrapper_evidence_path
                )
                if wrapper_evidence["routeInjected"] is not True:
                    raise SystemExit(
                        "Compatibility launcher proof did not inject route evidence.\n"
                        f"evidence={wrapper_evidence!r}"
                    )
                if wrapper_evidence.get("adapterBridgeDir") != str(
                    adapter_bridge_dir.resolve()
                ):
                    raise SystemExit(
                        "Compatibility launcher proof did not record adapter bridge dir.\n"
                        f"expected={adapter_bridge_dir.resolve()}\n"
                        f"evidence={wrapper_evidence!r}"
                    )
                if wrapper_evidence.get("adapterToolNames") != [APPLE_DOCS_CLI_TOOL]:
                    raise SystemExit(
                        "Compatibility launcher proof recorded wrong adapter tools.\n"
                        f"evidence={wrapper_evidence!r}"
                    )
                removed = installer.uninstall_launcher(
                    launcher_path=launcher_path,
                    manifest_path=manifest_path,
                )
                if launcher_path.exists() or manifest_path.exists():
                    raise SystemExit(
                        "Compatibility launcher uninstall left launcher artifacts behind."
                    )
        finally:
            if previous_pinned_env is not None:
                os.environ[OMNIGENT_STOCK_CODEX_PATH_ENV] = previous_pinned_env

        return StockCodexCompatLauncherActivationProof(
            stock_codex_path=stock_codex_path,
            stock_codex_version=stock_codex_version,
            launcher_path=install_result.launcher_path,
            manifest_path=install_result.manifest_path,
            repo_root=repo_root,
            uvx_path=uvx_path,
            resolved_codex_path=resolved_codex_path,
            adapter_bin=adapter_package.adapter_bin,
            adapter_manifest=adapter_package.manifest_path,
            adapter_bridge_dir=adapter_bridge_dir,
            adapter_tool_names=adapter_package.tool_names,
            workspace_root=workspace_root,
            sandbox="workspace-write",
            wrapper_evidence_path=wrapper_evidence_path,
            thread_id=thread_id,
            command=str(command_item["command"]),
            command_output=command_output,
            first_agent_message=first_agent_message,
            first_agent_message_before_wrapper=str(
                wrapper_evidence["firstAgentMessageBefore"]
            ),
            route_injected=bool(wrapper_evidence["routeInjected"]),
            probe_output=probe_output.strip(),
            uninstall_action=str(removed.action),
            event_count=len(events),
            stderr_preview=stderr_preview,
        )


def _write_stock_codex_compat_launcher_fake_sosumi(path: Path) -> None:
    """Write the deterministic Sosumi CLI fixture used by the launcher proof."""
    path.write_text(
        "#!/bin/sh\n"
        "if [ \"${1:-}\" != \"fetch\" ] || "
        f"[ \"${{2:-}}\" != {shlex.quote(APPLE_DOCS_CLI_URL)} ]; then\n"
        "  echo unexpected sosumi arguments >&2\n"
        "  exit 66\n"
        "fi\n"
        "cat <<'EOF'\n"
        "---\n"
        "title: String\n"
        f"source: {APPLE_DOCS_CLI_URL}\n"
        "timestamp: 2026-07-04T12:00:00.000Z\n"
        "---\n"
        "EOF\n",
        encoding="utf-8",
    )
    path.chmod(0o755)


def _write_stock_codex_compat_launcher_fake_codex(path: Path) -> None:
    """Write a fake stock Codex binary that emits one adapter command event."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""#!/usr/bin/env python3
import json
import subprocess
import sys

VERSION = "codex-cli 0.142.2"
THREAD_ID = "thread-stock-codex-compat-launcher"
COMMAND = "fetch_apple_docs --url {APPLE_DOCS_CLI_URL}"
SENTINEL = {STOCK_CODEX_COMPAT_LAUNCHER_ACTIVATION_SENTINEL!r}

if len(sys.argv) > 1 and sys.argv[1] == "--version":
    print(VERSION)
    raise SystemExit(0)

completed = subprocess.run(
    ["/bin/zsh", "-lc", COMMAND],
    check=False,
    capture_output=True,
    text=True,
)
output = completed.stdout + completed.stderr
print(json.dumps({{"type": "thread.started", "thread_id": THREAD_ID}}))
print(json.dumps({{
    "type": "item.completed",
    "item": {{
        "type": "command_execution",
        "command": "/bin/zsh -lc '" + COMMAND + "'",
        "aggregated_output": output,
        "exit_code": completed.returncode,
        "status": "completed",
    }},
}}))
agent_message = (
    SENTINEL
    if "title: String" in output and {APPLE_DOCS_CLI_URL!r} in output
    else "STOCK_CODEX_COMPAT_LAUNCHER_ACTIVATION_FAILED"
)
print(json.dumps({{
    "type": "item.completed",
    "item": {{"type": "agent_message", "text": agent_message}},
}}))
raise SystemExit(completed.returncode)
""",
        encoding="utf-8",
    )
    path.chmod(0o755)


def print_stock_codex_compat_launcher_activation_proof(
    proof: StockCodexCompatLauncherActivationProof,
) -> None:
    """Emit operator evidence for compatibility launcher activation."""
    print("stock_codex_compat_launcher_activation_rehearsal=selected")
    print(
        "stock_codex_compat_launcher_activation_surface="
        "managed-codex-launcher-to-wrapper-owned-file-bridge-adapter"
    )
    print(f"stock_codex_compat_launcher_activation_launcher_path={proof.launcher_path}")
    print(f"stock_codex_compat_launcher_activation_manifest_path={proof.manifest_path}")
    print(
        "stock_codex_compat_launcher_activation_stock_codex_path="
        f"{proof.stock_codex_path}"
    )
    print(
        "stock_codex_compat_launcher_activation_stock_codex_version="
        f"{proof.stock_codex_version}"
    )
    print(
        "stock_codex_compat_launcher_activation_resolved_codex_path="
        f"{proof.resolved_codex_path}"
    )
    print(f"stock_codex_compat_launcher_activation_repo_root={proof.repo_root}")
    print(f"stock_codex_compat_launcher_activation_uvx_path={proof.uvx_path}")
    print(f"stock_codex_compat_launcher_activation_adapter_bin={proof.adapter_bin}")
    print(
        "stock_codex_compat_launcher_activation_adapter_manifest="
        f"{proof.adapter_manifest}"
    )
    print(
        "stock_codex_compat_launcher_activation_adapter_bridge_dir="
        f"{proof.adapter_bridge_dir}"
    )
    print(
        "stock_codex_compat_launcher_activation_adapter_tools="
        f"{','.join(proof.adapter_tool_names)}"
    )
    print(f"stock_codex_compat_launcher_activation_workspace_root={proof.workspace_root}")
    print(f"stock_codex_compat_launcher_activation_sandbox={proof.sandbox}")
    print(f"stock_codex_compat_launcher_activation_thread_id={proof.thread_id}")
    print(f"stock_codex_compat_launcher_activation_event_count={proof.event_count}")
    print(
        "stock_codex_compat_launcher_activation_route_injected="
        f"{proof.route_injected}"
    )
    print(
        "stock_codex_compat_launcher_activation_evidence_path="
        f"{proof.wrapper_evidence_path}"
    )
    print(
        "stock_codex_compat_launcher_activation_command="
        f"{_preview_text(proof.command, limit=500)!r}"
    )
    print(
        "stock_codex_compat_launcher_activation_output_preview="
        f"{_preview_text(proof.command_output, limit=500)!r}"
    )
    print(
        "stock_codex_compat_launcher_activation_pre_wrapper_message_preview="
        f"{_preview_text(proof.first_agent_message_before_wrapper, limit=500)!r}"
    )
    print(
        "stock_codex_compat_launcher_activation_first_agent_message_preview="
        f"{_preview_text(proof.first_agent_message, limit=500)!r}"
    )
    print(
        "stock_codex_compat_launcher_activation_probe_output="
        f"{proof.probe_output!r}"
    )
    print(
        "stock_codex_compat_launcher_activation_uninstall_action="
        f"{proof.uninstall_action}"
    )
    print(
        "stock_codex_compat_launcher_activation_stderr_preview="
        f"{proof.stderr_preview!r}"
    )
    print(
        "stock_codex_compat_launcher_activation_cache_lifecycle="
        "temporary_removed_after_proof"
    )
    print(
        "ASSERTION: managed compatibility launcher can be selected as codex on "
        "PATH while Omnigent resolves its manifest-pinned stock Codex binary"
    )
    print(
        "ASSERTION: the launcher delegates through uvx to "
        "omnigent-stock-codex-wrapper with the adapter bridge package active"
    )
    print(
        "ASSERTION: uninstall removed the temporary managed launcher and manifest "
        "without touching Codex fork state"
    )


def run_app_bundle_entrypoint_proof(stock_codex_path: Path) -> AppBundleEntrypointProof:
    """Prove a temporary macOS app bundle can enter the Omnigent Codex path."""
    stock_codex_path = stock_codex_path.expanduser().resolve()
    assert_stock_codex_path(stock_codex_path, allow_fork_codex=False)
    stock_codex_version = codex_version(stock_codex_path)

    uvx_raw = shutil.which("uvx")
    if not uvx_raw:
        raise SystemExit("Could not find uvx on PATH for app-bundle entrypoint proof.")
    uvx_path = Path(uvx_raw).expanduser().resolve()
    if not uvx_path.is_file() or not os.access(uvx_path, os.X_OK):
        raise SystemExit(f"uvx binary is not executable: {uvx_path}")

    repo_root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="omnigent-codex-app-bundle-proof-") as temp_root:
        app_bundle_path = (Path(temp_root) / f"{APP_BUNDLE_ENTRYPOINT_NAME}.app").resolve()
        contents_path = app_bundle_path / "Contents"
        macos_path = contents_path / "MacOS"
        macos_path.mkdir(parents=True)
        info_plist_path = contents_path / "Info.plist"
        executable_path = (macos_path / APP_BUNDLE_ENTRYPOINT_EXECUTABLE).resolve()

        info = {
            "CFBundleDisplayName": APP_BUNDLE_ENTRYPOINT_NAME,
            "CFBundleExecutable": APP_BUNDLE_ENTRYPOINT_EXECUTABLE,
            "CFBundleIdentifier": APP_BUNDLE_ENTRYPOINT_IDENTIFIER,
            "CFBundleName": APP_BUNDLE_ENTRYPOINT_NAME,
            "CFBundlePackageType": "APPL",
            "CFBundleShortVersionString": "0.1",
            "CFBundleVersion": "1",
        }
        with info_plist_path.open("wb") as handle:
            plistlib.dump(info, handle, sort_keys=True)

        _write_app_bundle_entrypoint_launcher(
            executable_path,
            app_bundle_path=app_bundle_path,
            repo_root=repo_root,
            uvx_path=uvx_path,
            stock_codex_path=stock_codex_path,
            stock_codex_version=stock_codex_version,
        )
        _validate_app_bundle_entrypoint_plist(
            info_plist_path,
            expected_identifier=APP_BUNDLE_ENTRYPOINT_IDENTIFIER,
            expected_executable=APP_BUNDLE_ENTRYPOINT_EXECUTABLE,
        )

        completed = subprocess.run(
            [str(executable_path), APP_BUNDLE_ENTRYPOINT_PROBE_ARG],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        probe_output = (completed.stdout or "") + (completed.stderr or "")
        if completed.returncode != 0:
            raise SystemExit(
                "Temporary app-bundle entrypoint probe failed with exit "
                f"{completed.returncode}:\n{probe_output}"
            )
        _validate_app_bundle_entrypoint_probe_output(
            probe_output,
            app_bundle_path=app_bundle_path,
            executable_path=executable_path,
            stock_codex_path=stock_codex_path,
            stock_codex_version=stock_codex_version,
            uvx_path=uvx_path,
            repo_root=repo_root,
        )

        return AppBundleEntrypointProof(
            app_bundle_path=app_bundle_path,
            executable_path=executable_path,
            info_plist_path=info_plist_path,
            bundle_identifier=APP_BUNDLE_ENTRYPOINT_IDENTIFIER,
            bundle_executable=APP_BUNDLE_ENTRYPOINT_EXECUTABLE,
            stock_codex_path=stock_codex_path,
            stock_codex_version=stock_codex_version,
            uvx_path=uvx_path,
            repo_root=repo_root,
            probe_output=probe_output.strip(),
        )


def print_app_bundle_entrypoint_proof(proof: AppBundleEntrypointProof) -> None:
    """Emit operator evidence for the temporary app-bundle entrypoint proof."""
    print("app_bundle_entrypoint_rehearsal=selected")
    print(f"app_bundle_entrypoint_bundle={proof.app_bundle_path}")
    print(f"app_bundle_entrypoint_executable={proof.executable_path}")
    print(f"app_bundle_entrypoint_info_plist={proof.info_plist_path}")
    print(f"app_bundle_entrypoint_bundle_identifier={proof.bundle_identifier}")
    print(f"app_bundle_entrypoint_bundle_executable={proof.bundle_executable}")
    print(f"app_bundle_entrypoint_stock_codex_path={proof.stock_codex_path}")
    print(f"app_bundle_entrypoint_stock_codex_version={proof.stock_codex_version}")
    print(
        f"app_bundle_entrypoint_pinned_env={OMNIGENT_STOCK_CODEX_PATH_ENV}="
        f"{proof.stock_codex_path}"
    )
    print(
        "app_bundle_entrypoint_delegate_preview="
        f"{proof.uvx_path} --from {proof.repo_root} omnigent codex"
    )
    print(f"app_bundle_entrypoint_probe_output={proof.probe_output!r}")
    print("app_bundle_entrypoint_cache_lifecycle=temporary_removed_after_proof")
    print("app_bundle_entrypoint_launchservices_registration=not_attempted")
    print(
        "ASSERTION: temporary macOS .app bundle contained a valid Info.plist "
        "and executable Omnigent Codex entrypoint"
    )
    print(
        "ASSERTION: the app executable exports an explicit stock-Codex path "
        "before delegating to uvx --from <repo> omnigent codex"
    )
    print(
        "ASSERTION: this proof ran the bundle executable directly and did not "
        "install into /Applications, register LaunchServices, or mutate Codex.app"
    )


def _write_app_bundle_entrypoint_launcher(
    executable_path: Path,
    *,
    app_bundle_path: Path,
    repo_root: Path,
    uvx_path: Path,
    stock_codex_path: Path,
    stock_codex_version: str,
) -> None:
    """Write the temporary macOS app-bundle executable used by the proof."""
    quoted_app_bundle_path = shlex.quote(str(app_bundle_path))
    quoted_repo_root = shlex.quote(str(repo_root))
    quoted_uvx_path = shlex.quote(str(uvx_path))
    quoted_stock_codex_path = shlex.quote(str(stock_codex_path))
    quoted_stock_codex_version = shlex.quote(stock_codex_version)
    quoted_probe_arg = shlex.quote(APP_BUNDLE_ENTRYPOINT_PROBE_ARG)
    quoted_sentinel = shlex.quote(APP_BUNDLE_ENTRYPOINT_SENTINEL)
    executable_path.write_text(
        f"""#!/bin/sh
set -eu

APP_BUNDLE_PATH={quoted_app_bundle_path}
REPO_ROOT={quoted_repo_root}
UVX_PATH={quoted_uvx_path}
STOCK_CODEX_PATH={quoted_stock_codex_path}
STOCK_CODEX_VERSION={quoted_stock_codex_version}
PROBE_ARG={quoted_probe_arg}
SENTINEL={quoted_sentinel}

if [ "${{1:-}}" = "$PROBE_ARG" ]; then
  if [ ! -x "$UVX_PATH" ]; then
    printf 'app_bundle_entrypoint_error=uvx missing: %s\\n' "$UVX_PATH" >&2
    exit 2
  fi
  if [ ! -x "$STOCK_CODEX_PATH" ]; then
    printf 'app_bundle_entrypoint_error=stock codex missing: %s\\n' "$STOCK_CODEX_PATH" >&2
    exit 3
  fi
  actual_version="$("$STOCK_CODEX_PATH" --version 2>&1)"
  if [ "$actual_version" != "$STOCK_CODEX_VERSION" ]; then
    printf 'app_bundle_entrypoint_error=stock codex version mismatch\\n' >&2
    printf 'expected_stock_codex_version=%s\\n' "$STOCK_CODEX_VERSION" >&2
    printf 'actual_stock_codex_version=%s\\n' "$actual_version" >&2
    exit 4
  fi
  printf '%s\\n' "$SENTINEL"
  printf 'app_bundle_path=%s\\n' "$APP_BUNDLE_PATH"
  printf 'executable_path=%s\\n' "$0"
  printf 'delegates_to=%s --from %s omnigent codex\\n' "$UVX_PATH" "$REPO_ROOT"
  printf 'pinned_env={OMNIGENT_STOCK_CODEX_PATH_ENV}=%s\\n' "$STOCK_CODEX_PATH"
  printf 'stock_codex_path=%s\\n' "$STOCK_CODEX_PATH"
  printf 'stock_codex_version=%s\\n' "$STOCK_CODEX_VERSION"
  exit 0
fi

{OMNIGENT_STOCK_CODEX_PATH_ENV}="$STOCK_CODEX_PATH"
export {OMNIGENT_STOCK_CODEX_PATH_ENV}
exec "$UVX_PATH" --from "$REPO_ROOT" omnigent codex "$@"
""",
        encoding="utf-8",
    )
    executable_path.chmod(0o755)


def _validate_app_bundle_entrypoint_plist(
    info_plist_path: Path,
    *,
    expected_identifier: str,
    expected_executable: str,
) -> None:
    """Validate the generated app bundle plist declares the expected entrypoint."""
    with info_plist_path.open("rb") as handle:
        info = plistlib.load(handle)
    expected = {
        "CFBundleIdentifier": expected_identifier,
        "CFBundleExecutable": expected_executable,
        "CFBundlePackageType": "APPL",
        "CFBundleName": APP_BUNDLE_ENTRYPOINT_NAME,
        "CFBundleDisplayName": APP_BUNDLE_ENTRYPOINT_NAME,
    }
    mismatches = {
        key: (value, info.get(key)) for key, value in expected.items() if info.get(key) != value
    }
    if mismatches:
        raise SystemExit(f"Temporary app-bundle Info.plist mismatch: {mismatches!r}")


def _validate_app_bundle_entrypoint_probe_output(
    output: str,
    *,
    app_bundle_path: Path,
    executable_path: Path,
    stock_codex_path: Path,
    stock_codex_version: str,
    uvx_path: Path,
    repo_root: Path,
) -> None:
    """Validate the temporary app executable emitted delegation evidence."""
    expected_lines = [
        APP_BUNDLE_ENTRYPOINT_SENTINEL,
        f"app_bundle_path={app_bundle_path}",
        f"executable_path={executable_path}",
        f"delegates_to={uvx_path} --from {repo_root} omnigent codex",
        f"pinned_env={OMNIGENT_STOCK_CODEX_PATH_ENV}={stock_codex_path}",
        f"stock_codex_path={stock_codex_path}",
        f"stock_codex_version={stock_codex_version}",
    ]
    missing = [line for line in expected_lines if line not in output.splitlines()]
    if missing:
        raise SystemExit(
            "Temporary app-bundle entrypoint probe missed expected evidence.\n"
            f"missing={missing!r}\nOutput:\n{output}"
        )


def sha256_file(path: Path) -> str:
    """Return the SHA-256 digest for a proof input file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_string(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise SystemExit(f"Pinned stock Codex provisioner JSON missing string field {key!r}.")
    return value


def run_launcher_activation_proof() -> LauncherActivationProof:
    """Prove a temporary ``codex`` shim can activate and roll back cleanly."""
    baseline_raw = shutil.which("codex")
    if not baseline_raw:
        raise SystemExit("Could not find codex on PATH for launcher activation proof.")
    baseline_path = Path(baseline_raw)
    baseline_realpath = baseline_path.expanduser().resolve()
    assert_stock_codex_path(baseline_realpath, allow_fork_codex=False)

    uvx_raw = shutil.which("uvx")
    if not uvx_raw:
        raise SystemExit("Could not find uvx on PATH for launcher activation proof.")
    uvx_path = Path(uvx_raw).expanduser().resolve()
    if not uvx_path.is_file():
        raise SystemExit(f"uvx binary not found: {uvx_path}")

    repo_root = Path(__file__).resolve().parents[1]
    original_path = os.environ.get("PATH", "")
    with tempfile.TemporaryDirectory(prefix="omnigent-codex-launcher-proof-") as temp_root:
        shim_dir = Path(temp_root) / "bin"
        shim_dir.mkdir()
        shim_path = shim_dir / "codex"
        version_dir = _codex_version_dir_name(codex_version(baseline_realpath))
        pinned_codex_path = Path(temp_root) / "omnigent" / "codex-stock" / version_dir / "codex"
        pinned_codex_path.parent.mkdir(parents=True)
        shutil.copy2(baseline_realpath, pinned_codex_path)
        pinned_codex_path.chmod(0o755)
        pinned_codex_version = codex_version(pinned_codex_path)
        sanitized_path = _path_without_directory(original_path, shim_dir)
        _write_launcher_activation_shim(
            shim_path,
            repo_root=repo_root,
            uvx_path=uvx_path,
            expected_codex_path=baseline_path,
            expected_codex_realpath=baseline_realpath,
            pinned_codex_path=pinned_codex_path,
            pinned_codex_version=pinned_codex_version,
            sanitized_path=sanitized_path,
        )

        activated_path_value = f"{shim_dir}{os.pathsep}{original_path}"
        with temporary_env(
            {
                "PATH": activated_path_value,
                OMNIGENT_STOCK_CODEX_PATH_ENV: str(pinned_codex_path),
            }
        ):
            activated_raw = shutil.which("codex")
            if activated_raw is None:
                raise SystemExit("Temporary launcher activation removed codex from PATH.")
            activated_path = Path(activated_raw).expanduser().resolve()
            if activated_path != shim_path.resolve():
                raise SystemExit(
                    "Temporary launcher activation did not select the shim.\n"
                    f"expected={shim_path}\nactual={activated_raw}"
                )
            omnigent_resolved_raw = _find_codex_cli()
            if omnigent_resolved_raw is None:
                raise SystemExit(
                    f"{OMNIGENT_STOCK_CODEX_PATH_ENV} did not resolve a Codex binary."
                )
            omnigent_resolved_path = Path(omnigent_resolved_raw).expanduser().resolve()
            if omnigent_resolved_path != pinned_codex_path.resolve():
                raise SystemExit(
                    "Omnigent stock-Codex resolver did not select the pinned binary.\n"
                    f"expected={pinned_codex_path}\nactual={omnigent_resolved_raw}"
                )
            completed = subprocess.run(
                ["codex", LAUNCHER_ACTIVATION_PROBE_ARG],
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )
            probe_output = (completed.stdout or "") + (completed.stderr or "")
            if completed.returncode != 0:
                raise SystemExit(
                    "Temporary launcher activation probe failed with exit "
                    f"{completed.returncode}:\n{probe_output}"
                )
            _validate_launcher_activation_probe_output(
                probe_output,
                expected_codex_path=baseline_path,
            )

        restored_raw = shutil.which("codex")
        if restored_raw is None:
            raise SystemExit("Launcher activation rollback removed codex from PATH.")
        restored_path = Path(restored_raw)
        if restored_path != baseline_path:
            raise SystemExit(
                "Launcher activation rollback did not restore the original PATH lookup.\n"
                f"expected={baseline_path}\nactual={restored_path}"
            )

        return LauncherActivationProof(
            baseline_codex_path=baseline_path,
            baseline_codex_realpath=baseline_realpath,
            pinned_codex_path=pinned_codex_path,
            pinned_codex_version=pinned_codex_version,
            omnigent_resolved_codex_path=omnigent_resolved_path,
            activated_codex_path=activated_path,
            restored_codex_path=restored_path,
            shim_path=shim_path,
            uvx_path=uvx_path,
            sanitized_path=sanitized_path,
            probe_output=probe_output.strip(),
        )


def print_launcher_activation_proof(proof: LauncherActivationProof) -> None:
    """Emit operator evidence for the temporary launcher activation proof."""
    print("launcher_activation_rehearsal=selected")
    print(f"launcher_activation_baseline_codex_path={proof.baseline_codex_path}")
    print(f"launcher_activation_baseline_codex_realpath={proof.baseline_codex_realpath}")
    print(f"launcher_activation_pinned_codex_path={proof.pinned_codex_path}")
    print(f"launcher_activation_pinned_codex_version={proof.pinned_codex_version}")
    print(
        f"launcher_activation_pinned_env={OMNIGENT_STOCK_CODEX_PATH_ENV}={proof.pinned_codex_path}"
    )
    print(f"launcher_activation_omnigent_resolved_codex_path={proof.omnigent_resolved_codex_path}")
    print(f"launcher_activation_activated_codex_path={proof.activated_codex_path}")
    print(f"launcher_activation_restored_codex_path={proof.restored_codex_path}")
    print(f"launcher_activation_shim_path={proof.shim_path}")
    print(f"launcher_activation_uvx_path={proof.uvx_path}")
    print(
        "launcher_activation_delegate_preview="
        f"{proof.uvx_path} --from {Path(__file__).resolve().parents[1]} omnigent codex"
    )
    print("launcher_activation_rollback=remove the shim directory from PATH")
    print(f"launcher_activation_probe_output={proof.probe_output!r}")
    print(
        "ASSERTION: temporary PATH activation selected the Omnigent launcher shim "
        "without mutating shell profiles or launcher defaults"
    )
    print(
        "ASSERTION: the shim exports an explicit pinned stock-Codex path, so "
        "Omnigent resolves the managed binary instead of the shadowed codex command"
    )
    print("ASSERTION: PATH lookup was restored after the isolated activation scope")


def _codex_version_dir_name(version_text: str) -> str:
    """Return a filesystem-safe version directory name from ``codex --version``."""
    match = re.search(r"(\d+(?:\.\d+)+(?:[-.A-Za-z0-9]+)?)", version_text)
    if match is not None:
        return match.group(1)
    return "unknown"


def _path_without_directory(path_value: str, directory: Path) -> str:
    """Return ``path_value`` with any entries resolving to ``directory`` removed."""
    directory_resolved = directory.expanduser().resolve()
    parts: list[str] = []
    for raw_part in path_value.split(os.pathsep):
        if not raw_part:
            continue
        try:
            if Path(raw_part).expanduser().resolve() == directory_resolved:
                continue
        except OSError:
            pass
        parts.append(raw_part)
    return os.pathsep.join(parts)


def _write_launcher_activation_shim(
    shim_path: Path,
    *,
    repo_root: Path,
    uvx_path: Path,
    expected_codex_path: Path,
    expected_codex_realpath: Path,
    pinned_codex_path: Path,
    pinned_codex_version: str,
    sanitized_path: str,
) -> None:
    """Write the temporary ``codex`` launcher shim used by the proof."""
    quoted_sanitized_path = shlex.quote(sanitized_path)
    quoted_expected_codex_path = shlex.quote(str(expected_codex_path))
    quoted_expected_codex_realpath = shlex.quote(str(expected_codex_realpath))
    quoted_pinned_codex_path = shlex.quote(str(pinned_codex_path))
    quoted_pinned_codex_version = shlex.quote(pinned_codex_version)
    quoted_pinned_env_key = shlex.quote(OMNIGENT_STOCK_CODEX_PATH_ENV)
    quoted_uvx_path = shlex.quote(str(uvx_path))
    quoted_repo_root = shlex.quote(str(repo_root))
    quoted_probe_arg = shlex.quote(LAUNCHER_ACTIVATION_PROBE_ARG)
    quoted_sentinel = shlex.quote(LAUNCHER_ACTIVATION_SENTINEL)
    quoted_resolver_probe = shlex.quote(
        "from omnigent.inner.codex_executor import _find_codex_cli; print(_find_codex_cli() or '')"
    )
    shim_path.write_text(
        f"""#!/bin/sh
set -eu

SANITIZED_PATH={quoted_sanitized_path}
EXPECTED_CODEX_PATH={quoted_expected_codex_path}
EXPECTED_CODEX_REALPATH={quoted_expected_codex_realpath}
PINNED_CODEX_PATH={quoted_pinned_codex_path}
PINNED_CODEX_VERSION={quoted_pinned_codex_version}
PINNED_ENV_KEY={quoted_pinned_env_key}
UVX_PATH={quoted_uvx_path}
REPO_ROOT={quoted_repo_root}
PROBE_ARG={quoted_probe_arg}
SENTINEL={quoted_sentinel}
RESOLVER_PROBE={quoted_resolver_probe}

if [ "${{1:-}}" = "$PROBE_ARG" ]; then
  resolved="$(PATH="$SANITIZED_PATH" command -v codex || true)"
  if [ "$resolved" != "$EXPECTED_CODEX_PATH" ]; then
    printf 'launcher_activation_error=underlying codex mismatch\\n' >&2
    printf 'expected_underlying_codex_path=%s\\n' "$EXPECTED_CODEX_PATH" >&2
    printf 'resolved_underlying_codex_path=%s\\n' "$resolved" >&2
    exit 2
  fi
  if [ ! -x "$UVX_PATH" ]; then
    printf 'launcher_activation_error=uvx missing: %s\\n' "$UVX_PATH" >&2
    exit 3
  fi
  if [ ! -x "$PINNED_CODEX_PATH" ]; then
    printf 'launcher_activation_error=pinned codex missing: %s\\n' "$PINNED_CODEX_PATH" >&2
    exit 4
  fi
  omnigent_resolved="$(
    env PATH="$SANITIZED_PATH" "$PINNED_ENV_KEY=$PINNED_CODEX_PATH" \\
      "$UVX_PATH" --from "$REPO_ROOT" python -c "$RESOLVER_PROBE"
  )"
  if [ "$omnigent_resolved" != "$PINNED_CODEX_PATH" ]; then
    printf 'launcher_activation_error=omnigent resolver mismatch\\n' >&2
    printf 'expected_pinned_codex_path=%s\\n' "$PINNED_CODEX_PATH" >&2
    printf 'omnigent_resolved_codex_path=%s\\n' "$omnigent_resolved" >&2
    exit 5
  fi
  printf '%s\\n' "$SENTINEL"
  printf 'shim_path=%s\\n' "$0"
  printf 'delegates_to=%s --from %s omnigent codex\\n' "$UVX_PATH" "$REPO_ROOT"
  printf 'pinned_env=%s=%s\\n' "$PINNED_ENV_KEY" "$PINNED_CODEX_PATH"
  printf 'pinned_codex_version=%s\\n' "$PINNED_CODEX_VERSION"
  printf 'omnigent_resolved_codex_path=%s\\n' "$omnigent_resolved"
  printf 'resolved_underlying_codex_path=%s\\n' "$resolved"
  printf 'expected_underlying_codex_path=%s\\n' "$EXPECTED_CODEX_PATH"
  printf 'expected_underlying_codex_realpath=%s\\n' "$EXPECTED_CODEX_REALPATH"
  exit 0
fi

PATH="$SANITIZED_PATH"
export PATH
export "$PINNED_ENV_KEY=$PINNED_CODEX_PATH"
exec "$UVX_PATH" --from "$REPO_ROOT" omnigent codex "$@"
""",
        encoding="utf-8",
    )
    shim_path.chmod(0o755)


def _validate_launcher_activation_probe_output(
    output: str,
    *,
    expected_codex_path: Path,
) -> None:
    """Validate the temporary shim probe emitted the no-recursion evidence."""
    if LAUNCHER_ACTIVATION_SENTINEL not in output:
        raise SystemExit(f"Launcher activation probe missed sentinel:\n{output}")
    expected_underlying_line = f"resolved_underlying_codex_path={expected_codex_path}"
    if expected_underlying_line not in output:
        raise SystemExit(
            "Launcher activation probe did not resolve the underlying stock Codex.\n"
            f"Expected line: {expected_underlying_line}\nOutput:\n{output}"
        )
    if "delegates_to=" not in output:
        raise SystemExit(f"Launcher activation probe missed delegation preview:\n{output}")
    if "omnigent_resolved_codex_path=" not in output:
        raise SystemExit(f"Launcher activation probe missed Omnigent resolver evidence:\n{output}")


def run_live_proof_step(
    name: str,
    *,
    timeout_seconds: float,
    action: Callable[[], T],
) -> T:
    """Run one live proof step with explicit progress and timeout evidence."""
    timeout_label = _format_seconds(timeout_seconds)
    print(f"live_proof_start={name} timeout={timeout_label}", flush=True)
    started = time.monotonic()
    try:
        with _live_proof_timeout(name, timeout_seconds):
            result = action()
    except LiveProofTimeoutError as exc:
        elapsed = time.monotonic() - started
        print(
            f"live_proof_timeout={name} elapsed={_format_seconds(elapsed)} "
            f"timeout={timeout_label}",
            flush=True,
        )
        raise SystemExit(
            f"Live proof step {name!r} exceeded {timeout_label}. "
            "The proof run stopped at this isolated surface."
        ) from exc
    except SystemExit as exc:
        elapsed = time.monotonic() - started
        print(
            f"live_proof_failed={name} elapsed={_format_seconds(elapsed)} exit={exc.code!r}",
            flush=True,
        )
        raise
    except Exception as exc:
        elapsed = time.monotonic() - started
        print(
            f"live_proof_failed={name} elapsed={_format_seconds(elapsed)} "
            f"error={type(exc).__name__}: {exc}",
            flush=True,
        )
        raise
    elapsed = time.monotonic() - started
    print(f"live_proof_ok={name} elapsed={_format_seconds(elapsed)}", flush=True)
    return result


@contextlib.contextmanager
def _live_proof_timeout(name: str, timeout_seconds: float) -> Iterator[None]:
    """Install a temporary SIGALRM deadline for one live proof step."""
    if timeout_seconds <= 0:
        yield
        return

    previous_handler = signal.getsignal(signal.SIGALRM)
    previous_timer = signal.setitimer(signal.ITIMER_REAL, 0)

    def _raise_timeout(_signum: int, _frame: Any) -> None:
        raise LiveProofTimeoutError(
            f"live proof step {name!r} exceeded {_format_seconds(timeout_seconds)}"
        )

    signal.signal(signal.SIGALRM, _raise_timeout)
    signal.setitimer(signal.ITIMER_REAL, timeout_seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
        if previous_timer[0] > 0:
            signal.setitimer(signal.ITIMER_REAL, previous_timer[0], previous_timer[1])


@contextlib.contextmanager
def temporary_env(overrides: Mapping[str, str]) -> Iterator[None]:
    """Temporarily set environment values for one live proof surface."""
    previous: dict[str, str | None] = {key: os.environ.get(key) for key in overrides}
    try:
        for key, value in overrides.items():
            os.environ[key] = value
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _format_seconds(seconds: float) -> str:
    """Format elapsed seconds compactly for proof logs."""
    if seconds == int(seconds):
        return f"{int(seconds)}s"
    return f"{seconds:.1f}s"


def copy_bundle(source: Path, destination: Path) -> None:
    """Copy the installed bundle into the temporary proof agent."""
    shutil.copytree(
        source,
        destination,
        ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc", ".DS_Store"),
    )


def write_agent_config(
    agent_dir: Path,
    *,
    apple_mcp_servers: dict[str, dict[str, Any]] | None = None,
    mcp_env_overrides: dict[str, dict[str, str]] | None = None,
    router_selection_host_scope: str | None = None,
) -> None:
    """Write the Omnigent harness config into the copied bundle root."""
    mcp_tools_block = ""
    if apple_mcp_servers:
        mcp_tools_block = _mcp_tools_yaml(
            apple_mcp_servers,
            env_overrides=mcp_env_overrides or {},
        )
    router_selection_config = ""
    if router_selection_host_scope is not None:
        router_selection_config = (
            f"    router_selection_host_scope: {_yaml_string(router_selection_host_scope)}\n"
        )
    (agent_dir / "config.yaml").write_text(
        f"""
spec_version: 1
name: apple_codex_stock_replacement_proof
prompt: |
  You are a terse stock-Codex replacement proof agent.
  Obey the active bundle policy and answer proof prompts exactly.
skills: all
executor:
  type: omnigent
  config:
    harness: codex
{router_selection_config.rstrip()}
os_env:
  type: caller_process
  cwd: .
  sandbox:
    type: none
{mcp_tools_block}""".lstrip(),
        encoding="utf-8",
    )


def _mcp_tools_yaml(
    server_configs: dict[str, dict[str, Any]],
    *,
    env_overrides: dict[str, dict[str, str]],
) -> str:
    """Translate Apple ``.mcp.json`` server configs into Omnigent YAML."""
    lines = ["tools:"]
    for server_name, config in server_configs.items():
        command = config.get("command")
        args = config.get("args", [])
        if not isinstance(command, str) or not command:
            raise SystemExit(f"Apple MCP server {server_name!r} does not declare a command")
        if not isinstance(args, list) or not all(isinstance(arg, str) for arg in args):
            raise SystemExit(f"Apple MCP server {server_name!r} args must be a list of strings")
        raw_env = config.get("env", {})
        if raw_env and not isinstance(raw_env, dict):
            raise SystemExit(f"Apple MCP server {server_name!r} env must be an object")
        env = {str(key): str(value) for key, value in (raw_env or {}).items()}
        env.update(env_overrides.get(server_name, {}))

        lines.extend(
            [
                f"  {server_name}:",
                "    type: mcp",
                f"    command: {_yaml_string(command)}",
                "    args:",
            ]
        )
        lines.extend(f"      - {_yaml_string(arg)}" for arg in args)
        if env:
            lines.append("    env:")
            lines.extend(f"      {key}: {_yaml_string(value)}" for key, value in env.items())
    return "\n".join(lines) + "\n"


def _yaml_string(value: str) -> str:
    """Render a JSON-style quoted scalar, valid as YAML."""
    return json.dumps(value)


def prove_selected_skill_graph(bundle_dir: Path) -> GraphProof:
    """Verify selected skill relative files and referenced skills exist."""
    skill_path = bundle_dir / "skills" / SELECTED_SKILL / "SKILL.md"
    if not skill_path.is_file():
        raise SystemExit(f"Selected skill missing: {skill_path}")
    skill_text = skill_path.read_text(encoding="utf-8")

    relative_paths: dict[str, Path] = {}
    missing_relative: list[tuple[str, Path]] = []
    bundle_root = bundle_dir.resolve()
    for raw in sorted(set(RELATIVE_MARKDOWN_PATH_RE.findall(skill_text))):
        resolved = (skill_path.parent / raw).resolve()
        if not _is_relative_to(resolved, bundle_root) or not resolved.is_file():
            missing_relative.append((raw, resolved))
            continue
        relative_paths[raw] = resolved

    skill_refs: dict[str, Path] = {}
    missing_skills: list[tuple[str, Path]] = []
    for skill_name in sorted(set(PLUGIN_SKILL_REF_RE.findall(skill_text))):
        resolved = bundle_dir / "skills" / skill_name / "SKILL.md"
        if not resolved.is_file():
            missing_skills.append((skill_name, resolved))
            continue
        skill_refs[skill_name] = resolved

    if missing_relative or missing_skills:
        details = []
        if missing_relative:
            details.append("Missing relative files:")
            details.extend(f"- {raw} -> {path}" for raw, path in missing_relative)
        if missing_skills:
            details.append("Missing plugin skill refs:")
            details.extend(f"- {name} -> {path}" for name, path in missing_skills)
        raise SystemExit("\n".join(details))

    return GraphProof(relative_paths=relative_paths, skill_refs=skill_refs)


def prove_apple_mcp_manifest(bundle_dir: Path) -> dict[str, Any]:
    """Verify the Apple plugin MCP manifest is present in the bundle."""
    plugin_manifest_path = bundle_dir / ".codex-plugin" / "plugin.json"
    try:
        plugin_manifest = json.loads(plugin_manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Could not read plugin manifest: {plugin_manifest_path}: {exc}") from exc
    if not isinstance(plugin_manifest, dict):
        raise SystemExit(f"Plugin manifest is not a JSON object: {plugin_manifest_path}")
    mcp_ref = plugin_manifest.get("mcpServers")
    if not isinstance(mcp_ref, str) or not mcp_ref:
        raise SystemExit("Plugin manifest does not declare mcpServers")
    mcp_path = (bundle_dir / mcp_ref).resolve()
    if not _is_relative_to(mcp_path, bundle_dir.resolve()) or not mcp_path.is_file():
        raise SystemExit(f"Plugin mcpServers path is not a bundled file: {mcp_ref} -> {mcp_path}")
    try:
        mcp_manifest = json.loads(mcp_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Could not read MCP manifest: {mcp_path}: {exc}") from exc
    if not isinstance(mcp_manifest, dict):
        raise SystemExit(f"MCP manifest is not a JSON object: {mcp_path}")
    missing = EXPECTED_APPLE_MCP_SERVERS.difference(mcp_manifest)
    if missing:
        raise SystemExit(
            "Apple MCP manifest missing expected servers: " + ", ".join(sorted(missing))
        )
    for name, config in mcp_manifest.items():
        if not isinstance(config, dict):
            raise SystemExit(f"MCP server {name!r} config is not an object")
        if not isinstance(config.get("command"), str) and not isinstance(config.get("url"), str):
            raise SystemExit(f"MCP server {name!r} has neither command nor url")
    return mcp_manifest


def mcp_config_from_manifest(mcp_manifest: dict[str, Any], server_name: str) -> dict[str, Any]:
    """Return one Apple MCP server config from a parsed manifest."""
    server_config = mcp_manifest.get(server_name)
    if not isinstance(server_config, dict):
        raise SystemExit(f"Apple MCP manifest does not contain a {server_name!r} server object")
    return server_config


def run_live_runner_proof(agent_dir: Path, codex_path: Path) -> str:
    """Run the live stock-Codex proof through Omnigent ``run_prompt()``."""
    prompt = (
        "SwiftUI replacement proof. Using the selected skill path and bundle root "
        "from the active policy, resolve ../../references/brigade-output-contract.md "
        f"and read it. Reply exactly GRAPH_OK if it contains {REFERENCE_SENTINEL!r}; "
        "otherwise reply exactly GRAPH_MISSING."
    )
    old_cwd = Path.cwd()
    old_codex_path = os.environ.get("HARNESS_CODEX_PATH")
    os.environ["HARNESS_CODEX_PATH"] = str(codex_path)
    stdout = io.StringIO()
    stderr = io.StringIO()
    try:
        os.chdir(agent_dir)
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            run_prompt(
                str(agent_dir / "config.yaml"),
                None,
                prompt=prompt,
                ephemeral=True,
            )
    finally:
        os.chdir(old_cwd)
        if old_codex_path is None:
            os.environ.pop("HARNESS_CODEX_PATH", None)
        else:
            os.environ["HARNESS_CODEX_PATH"] = old_codex_path

    if stderr.getvalue().strip():
        raise SystemExit(f"run_prompt emitted stderr:\n{stderr.getvalue()}")
    transcript = stdout.getvalue().strip()
    if not transcript.startswith(EXPECTED_ROUTE):
        raise SystemExit(
            "Transcript did not start with expected route block.\n"
            f"Expected prefix:\n{EXPECTED_ROUTE}\n\nActual:\n{transcript[:1000]}"
        )
    if "GRAPH_OK" not in transcript:
        raise SystemExit(f"Live proof did not return GRAPH_OK. Transcript:\n{transcript}")
    if transcript.find(EXPECTED_ROUTE) > transcript.find("GRAPH_OK"):
        raise SystemExit("GRAPH_OK appeared before the route evidence block.")
    return transcript


def run_live_router_matrix_proof(agent_dir: Path, codex_path: Path) -> list[RouterMatrixCaseProof]:
    """Prove router-selection matrix behavior through stock Codex."""
    proofs: list[RouterMatrixCaseProof] = []
    marker_path = agent_dir / "Package.swift"
    extension_path = agent_dir / "RouterMatrixProof.xcodeproj"

    cases = [
        {
            "name": "prompt-signal",
            "prompt": (
                "Router matrix prompt-signal proof for a SwiftUI branch. "
                f"Reply exactly {ROUTER_MATRIX_PROMPT_SIGNAL_SENTINEL}."
            ),
            "sentinel": ROUTER_MATRIX_PROMPT_SIGNAL_SENTINEL,
            "expected_route": True,
            "host_scope": "desktop",
        },
        {
            "name": "xcode-host-scope",
            "prompt": (
                "Router matrix xcode host-scope proof for a SwiftUI branch. "
                f"Reply exactly {ROUTER_MATRIX_XCODE_HOST_SENTINEL}."
            ),
            "sentinel": ROUTER_MATRIX_XCODE_HOST_SENTINEL,
            "expected_route": True,
            "host_scope": "xcode",
        },
        {
            "name": "workspace-file",
            "prompt": (
                "Router matrix workspace-file proof. "
                f"Reply exactly {ROUTER_MATRIX_WORKSPACE_FILE_SENTINEL}."
            ),
            "sentinel": ROUTER_MATRIX_WORKSPACE_FILE_SENTINEL,
            "expected_route": True,
            "host_scope": "desktop",
            "before": lambda: marker_path.write_text(
                "// router matrix marker\n", encoding="utf-8"
            ),
            "after": lambda: marker_path.unlink(missing_ok=True),
        },
        {
            "name": "workspace-extension",
            "prompt": (
                "Router matrix workspace-extension proof. "
                f"Reply exactly {ROUTER_MATRIX_WORKSPACE_EXTENSION_SENTINEL}."
            ),
            "sentinel": ROUTER_MATRIX_WORKSPACE_EXTENSION_SENTINEL,
            "expected_route": True,
            "host_scope": "desktop",
            "before": lambda: extension_path.mkdir(exist_ok=True),
            "after": lambda: shutil.rmtree(extension_path, ignore_errors=True),
        },
        {
            "name": "explicit-downstream-route",
            "prompt": (
                f"${ROUTER_MATRIX_REVIEW_OWNER} review this iOS branch diff. "
                f"Reply exactly {ROUTER_MATRIX_DOWNSTREAM_ROUTE_SENTINEL}."
            ),
            "sentinel": ROUTER_MATRIX_DOWNSTREAM_ROUTE_SENTINEL,
            "expected_route": True,
            "host_scope": "desktop",
        },
        {
            "name": "focused-specialist-suppression",
            "prompt": (
                f"${ROUTER_MATRIX_FOCUSED_OWNER} stress test this iOS architecture decision. "
                f"Reply exactly {ROUTER_MATRIX_FOCUSED_SUPPRESS_SENTINEL}."
            ),
            "sentinel": ROUTER_MATRIX_FOCUSED_SUPPRESS_SENTINEL,
            "expected_route": False,
            "host_scope": "desktop",
        },
        {
            "name": "non-matching-host-scope",
            "prompt": (
                "Router matrix non-matching host proof for a SwiftUI branch. "
                f"Reply exactly {ROUTER_MATRIX_NON_MATCHING_HOST_SENTINEL}."
            ),
            "sentinel": ROUTER_MATRIX_NON_MATCHING_HOST_SENTINEL,
            "expected_route": False,
            "host_scope": "server",
        },
    ]

    for case in cases:
        before = case.get("before")
        after = case.get("after")
        if callable(before):
            before()
        try:
            write_agent_config(
                agent_dir,
                router_selection_host_scope=str(case["host_scope"]),
            )
            run = asyncio_run_session_query(
                agent_dir=agent_dir,
                codex_path=codex_path,
                prompt=str(case["prompt"]),
            )
        finally:
            if callable(after):
                after()

        proof = RouterMatrixCaseProof(
            name=str(case["name"]),
            session_id=run.session_id,
            sentinel=str(case["sentinel"]),
            expected_route=bool(case["expected_route"]),
            transcript=run.text.strip(),
        )
        validate_router_matrix_case(proof)
        proofs.append(proof)

    write_agent_config(agent_dir)
    return proofs


def validate_router_matrix_case(proof: RouterMatrixCaseProof) -> None:
    """Validate one router-selection matrix proof transcript."""
    transcript = proof.transcript
    if proof.sentinel not in transcript:
        raise SystemExit(
            f"Router matrix case {proof.name!r} missed sentinel {proof.sentinel!r}. "
            f"Transcript:\n{transcript}"
        )
    route_index = transcript.find(EXPECTED_ROUTE)
    sentinel_index = transcript.find(proof.sentinel)
    if proof.expected_route:
        if not transcript.startswith(EXPECTED_ROUTE):
            raise SystemExit(
                f"Router matrix case {proof.name!r} did not start with route block.\n"
                f"Expected prefix:\n{EXPECTED_ROUTE}\n\nActual:\n{transcript[:1000]}"
            )
        if route_index > sentinel_index:
            raise SystemExit(
                f"Router matrix case {proof.name!r} returned sentinel before route evidence."
            )
        return

    if route_index != -1:
        raise SystemExit(
            f"Router matrix case {proof.name!r} unexpectedly emitted route evidence. "
            f"Transcript:\n{transcript}"
        )


async def _run_session_query(
    *,
    agent_dir: Path,
    codex_path: Path,
    prompt: str,
    query_timeout_seconds: float | None = None,
) -> SessionRun:
    old_cwd = Path.cwd()
    old_codex_path = os.environ.get("HARNESS_CODEX_PATH")
    os.environ["HARNESS_CODEX_PATH"] = str(codex_path)
    try:
        os.chdir(agent_dir)
        path = _canonicalize_local_agent_path(agent_dir / "config.yaml")
        spec_path = _materialize_override_bundle(path, ChatOverrides())
        try:
            _validate_agent_spec(spec_path)
            agent_name = _extract_agent_name(spec_path)
            port = _find_free_port()
            server = _start_local_server(spec_path, port, ephemeral=True)
            try:
                _wait_for_server(port, server)
                base_url = f"http://127.0.0.1:{port}"
                session_holder: dict[str, str] = {}
                async with OmnigentClient(
                    base_url=base_url,
                    headers=_server_headers(runner_id=server.runner_id),
                    auth=_server_auth(server_url=base_url),
                ) as client:
                    query = _query_sessions_once(
                        client=client,
                        agent_name=agent_name,
                        tool_handler=None,
                        prompt=prompt,
                        session_bundle=_bundle_agent(spec_path),
                        session_bundle_filename="agent.tar.gz",
                        runner_id=server.runner_id,
                        on_session_ready=lambda sid: session_holder.setdefault("id", sid),
                    )
                    try:
                        if query_timeout_seconds is not None and query_timeout_seconds > 0:
                            text = await asyncio.wait_for(
                                query,
                                timeout=query_timeout_seconds,
                            )
                        else:
                            text = await query
                    except TimeoutError as exc:
                        diagnostic_error = await _build_session_query_timeout_error(
                            client=client,
                            session_id=session_holder.get("id"),
                            timeout_seconds=query_timeout_seconds,
                        )
                        raise diagnostic_error from exc
                    session_id = session_holder.get("id")
                    if session_id is None:
                        raise SystemExit("Session id was not captured during proof run")
                    items = await client.sessions.list_items(
                        session_id,
                        limit=100,
                        order="asc",
                    )
                    return SessionRun(session_id=session_id, text=text or "", items=items)
            finally:
                _stop_local_server(server)
        finally:
            _cleanup_materialized_override_bundle(spec_path)
    finally:
        os.chdir(old_cwd)
        if old_codex_path is None:
            os.environ.pop("HARNESS_CODEX_PATH", None)
        else:
            os.environ["HARNESS_CODEX_PATH"] = old_codex_path


async def _build_session_query_timeout_error(
    *,
    client: OmnigentClient,
    session_id: str | None,
    timeout_seconds: float | None,
) -> SessionQueryTimeoutError:
    """Collect best-effort session diagnostics for a timed-out proof query."""
    timeout_label = _format_seconds(timeout_seconds or 0)
    if session_id is None:
        return SessionQueryTimeoutError(
            f"sessions query timed out after {timeout_label}; session_id was not captured"
        )
    await asyncio.sleep(1.0)
    status = "unavailable"
    last_task_error: Any = None
    items: list[dict[str, Any]] = []
    snapshot_error: str | None = None
    items_error: str | None = None
    try:
        snapshot = await client.sessions.get(session_id)
        status = getattr(snapshot, "status", "unknown")
        last_task_error = getattr(snapshot, "last_task_error", None)
    except Exception as exc:  # noqa: BLE001 - diagnostic best effort only
        snapshot_error = f"{type(exc).__name__}: {exc}"
    try:
        items = await client.sessions.list_items(
            session_id,
            limit=100,
            order="asc",
        )
    except Exception as exc:  # noqa: BLE001 - diagnostic best effort only
        items_error = f"{type(exc).__name__}: {exc}"
    return SessionQueryTimeoutError(
        "sessions query timed out before transcript completion.\n"
        f"timeout={timeout_label}\n"
        f"session_id={session_id}\n"
        f"session_status={status}\n"
        f"last_task_error={last_task_error!r}\n"
        f"items={_session_item_summary(items)}\n"
        f"snapshot_error={snapshot_error!r}\n"
        f"items_error={items_error!r}"
    )


def run_live_tool_proof(agent_dir: Path, codex_path: Path) -> ToolProof:
    """Prove stock Codex can call an Omnigent-exposed dynamic tool."""
    proof_file = agent_dir / "tool-proof.txt"
    proof_file.write_text(f"{TOOL_SENTINEL}\n", encoding="utf-8")
    prompt = (
        "SwiftUI tool exposure proof. Use sys_os_read to read tool-proof.txt. "
        f"Reply exactly TOOL_OK if it contains {TOOL_SENTINEL}; otherwise reply "
        "TOOL_MISSING."
    )
    run = asyncio_run_session_query(agent_dir=agent_dir, codex_path=codex_path, prompt=prompt)
    transcript = run.text.strip()
    if not transcript.startswith(EXPECTED_ROUTE):
        raise SystemExit(
            "Tool proof transcript did not start with expected route block.\n"
            f"Expected prefix:\n{EXPECTED_ROUTE}\n\nActual:\n{transcript[:1000]}"
        )
    if "TOOL_OK" not in transcript:
        raise SystemExit(f"Tool proof did not return TOOL_OK. Transcript:\n{transcript}")

    calls = [
        item
        for item in run.items
        if item.get("type") == "function_call" and item.get("name") == "sys_os_read"
    ]
    if not calls:
        raise SystemExit("No persisted sys_os_read function_call found in session items")
    call = calls[-1]
    call_id = call.get("call_id")
    if not isinstance(call_id, str) or not call_id:
        raise SystemExit(f"Persisted sys_os_read call has invalid call_id: {call!r}")
    outputs = [
        item
        for item in run.items
        if item.get("type") == "function_call_output" and item.get("call_id") == call_id
    ]
    if not outputs:
        raise SystemExit(f"No persisted function_call_output found for call_id={call_id}")
    output_text = str(outputs[-1].get("output", ""))
    if TOOL_SENTINEL not in output_text:
        raise SystemExit(
            f"sys_os_read output did not contain sentinel {TOOL_SENTINEL!r}: {output_text}"
        )
    return ToolProof(session_id=run.session_id, call_id=call_id, transcript=transcript)


def run_live_apple_memory_mcp_proof(agent_dir: Path, codex_path: Path) -> AppleMcpProof:
    """Prove stock Codex can call the Apple memory MCP through Omnigent."""
    prompt = (
        "SwiftUI Apple MCP execution proof. Call the available tool named "
        f"{APPLE_MCP_MEMORY_TOOL} exactly once before answering. Pass exactly one "
        "entity with name "
        f"{APPLE_MCP_MEMORY_SENTINEL!r}, entityType 'proof', and one observation "
        "'created by Omnigent stock Codex proof'. Do not use any other tool "
        "for this proof. After the tool call succeeds, reply exactly APPLE_MCP_OK."
    )
    run = asyncio_run_session_query(agent_dir=agent_dir, codex_path=codex_path, prompt=prompt)
    transcript = run.text.strip()
    if not transcript.startswith(EXPECTED_ROUTE):
        raise SystemExit(
            "Apple MCP proof transcript did not start with expected route block.\n"
            f"Expected prefix:\n{EXPECTED_ROUTE}\n\nActual:\n{transcript[:1000]}"
        )
    if "APPLE_MCP_OK" not in transcript:
        raise SystemExit(f"Apple MCP proof did not return APPLE_MCP_OK. Transcript:\n{transcript}")

    calls = [
        item
        for item in run.items
        if item.get("type") == "function_call" and item.get("name") == APPLE_MCP_MEMORY_TOOL
    ]
    if not calls:
        raise SystemExit(_missing_tool_call_message(APPLE_MCP_MEMORY_TOOL, run))
    call = calls[-1]
    call_id = call.get("call_id")
    if not isinstance(call_id, str) or not call_id:
        raise SystemExit(f"Persisted {APPLE_MCP_MEMORY_TOOL} call has invalid call_id: {call!r}")
    outputs = [
        item
        for item in run.items
        if item.get("type") == "function_call_output" and item.get("call_id") == call_id
    ]
    if not outputs:
        raise SystemExit(f"No persisted function_call_output found for call_id={call_id}")
    output_text = str(outputs[-1].get("output", ""))
    if APPLE_MCP_MEMORY_SENTINEL not in output_text or "error" in output_text.lower():
        raise SystemExit(
            "Apple MCP tool output did not contain the sentinel or looked erroneous: "
            f"{output_text}"
        )
    return AppleMcpProof(
        session_id=run.session_id,
        call_id=call_id,
        transcript=transcript,
        output_preview=output_text[:500],
    )


def run_live_apple_sosumi_mcp_proof(agent_dir: Path, codex_path: Path) -> AppleMcpProof:
    """Prove stock Codex can call the Apple sosumi MCP through Omnigent."""
    prompts = (
        (
            "Tool invocation drill. After the required route block, your next "
            f"action must be a function call to {APPLE_MCP_SOSUMI_TOOL}, not "
            "prose. Use JSON arguments "
            f'{{"path": "{APPLE_MCP_SOSUMI_DOC_PATH}"}}. The function result '
            "will contain a line beginning 'timestamp:'. After the tool result "
            "is available, reply exactly SOSUMI_MCP_TIMESTAMP=<timestamp value>. "
            "Do not guess the timestamp; it is not present in this prompt."
        ),
        (
            "SwiftUI Apple documentation MCP proof. Call the available tool "
            f"named {APPLE_MCP_SOSUMI_TOOL} exactly once before answering. "
            f"Pass the path {APPLE_MCP_SOSUMI_DOC_PATH!r}. Do not use any "
            "other tool for this proof. After the tool call succeeds, extract "
            "the timestamp value from the function result and reply exactly "
            "SOSUMI_MCP_TIMESTAMP=<timestamp value>."
        ),
        (
            f"Use {APPLE_MCP_SOSUMI_TOOL} now to fetch "
            f"{APPLE_MCP_SOSUMI_DOC_PATH}. This is a tool-call proof; a text "
            "answer without the function call is invalid. After the function "
            "call output is available, copy only the timestamp value from the "
            "tool result and reply exactly SOSUMI_MCP_TIMESTAMP=<timestamp value>."
        ),
    )
    errors: list[str] = []
    for attempt, prompt in enumerate(prompts, start=1):
        try:
            run = asyncio_run_session_query(
                agent_dir=agent_dir,
                codex_path=codex_path,
                prompt=prompt,
                query_timeout_seconds=APPLE_MCP_SOSUMI_SESSION_QUERY_TIMEOUT_SECONDS,
            )
            return _validate_sosumi_mcp_run(run, attempt=attempt)
        except SessionQueryTimeoutError as exc:
            raise SystemExit(f"Sosumi MCP proof attempt {attempt} timed out:\n{exc}") from exc
        except SosumiProofAttemptError as exc:
            errors.append(str(exc))
    joined_errors = "\n\n".join(errors)
    raise SystemExit(f"Sosumi MCP proof failed after {len(prompts)} attempts:\n{joined_errors}")


def run_live_apple_docs_cli_proof(agent_dir: Path, codex_path: Path) -> AppleMcpProof:
    """Prove stock Codex can fetch Apple docs through the Sosumi CLI adapter."""
    prompts = (
        (
            "Tool invocation drill. After the required route block, your next "
            f"action must be a function call to {APPLE_DOCS_CLI_TOOL}, not prose. "
            f'Use JSON arguments {{"url": "{APPLE_DOCS_CLI_URL}"}}. The '
            "function result will contain a line beginning 'timestamp:'. After "
            "the tool result is available, reply exactly "
            "APPLE_DOCS_CLI_TIMESTAMP=<timestamp value>. Do not guess the "
            "timestamp; it is not present in this prompt."
        ),
        (
            "Apple documentation CLI proof. Call the available tool named "
            f"{APPLE_DOCS_CLI_TOOL} exactly once before answering. Pass the url "
            f"{APPLE_DOCS_CLI_URL!r}. After the tool call succeeds, extract the "
            "timestamp value from the function result and reply exactly "
            "APPLE_DOCS_CLI_TIMESTAMP=<timestamp value>."
        ),
    )
    errors: list[str] = []
    for attempt, prompt in enumerate(prompts, start=1):
        run = asyncio_run_session_query(
            agent_dir=agent_dir,
            codex_path=codex_path,
            prompt=prompt,
        )
        try:
            return _validate_apple_docs_cli_run(run, attempt=attempt)
        except AppleDocsCliProofAttemptError as exc:
            errors.append(str(exc))
    joined_errors = "\n\n".join(errors)
    raise SystemExit(
        f"Apple docs CLI proof failed after {len(prompts)} attempts:\n{joined_errors}"
    )


def run_live_apple_workflow_smoke_proof(
    agent_dir: Path,
    codex_path: Path,
    *,
    workspace_root: Path,
) -> AppleWorkflowSmokeProof:
    """Run a representative routed Apple workflow with docs and project discovery."""
    workspace = str(workspace_root)
    docs_args = {"url": APPLE_DOCS_CLI_URL}
    xcode_args = {"workspaceRoot": workspace, "maxDepth": 5}
    prompts = (
        (
            "Representative Apple workflow smoke. After the required route block, "
            f"call {APPLE_DOCS_CLI_TOOL} exactly once with JSON arguments "
            f"{json.dumps(docs_args)}. Then call {APPLE_MCP_XCODEBUILD_TOOL} "
            f"exactly once with JSON arguments {json.dumps(xcode_args)}. Do not "
            "build, run, test, launch, mutate Xcode defaults, or call any other "
            "tool. After both tool results are available, reply exactly "
            f"{APPLE_WORKFLOW_SMOKE_SENTINEL}."
        ),
        (
            "Apple workflow smoke: fetch the official Swift String documentation "
            f"using {APPLE_DOCS_CLI_TOOL}, then discover local Xcode projects using "
            f"{APPLE_MCP_XCODEBUILD_TOOL}. Use only these exact arguments: "
            f"{APPLE_DOCS_CLI_TOOL}={json.dumps(docs_args)} and "
            f"{APPLE_MCP_XCODEBUILD_TOOL}={json.dumps(xcode_args)}. End with "
            f"only {APPLE_WORKFLOW_SMOKE_SENTINEL} after both tool calls finish."
        ),
    )
    errors: list[str] = []
    for attempt, prompt in enumerate(prompts, start=1):
        run = asyncio_run_session_query(
            agent_dir=agent_dir,
            codex_path=codex_path,
            prompt=prompt,
        )
        try:
            return _validate_apple_workflow_smoke_run(
                run,
                attempt=attempt,
                workspace_root=workspace_root,
            )
        except AppleWorkflowSmokeProofError as exc:
            errors.append(str(exc))
    joined_errors = "\n\n".join(errors)
    raise SystemExit(
        f"Apple workflow smoke proof failed after {len(prompts)} attempts:\n{joined_errors}"
    )


def run_live_xcodebuild_cli_run_proof(
    agent_dir: Path,
    codex_path: Path,
    *,
    workspace_root: Path,
    simulator_name: str,
    derived_data_path: Path,
) -> AppleMcpProof:
    """Prove stock Codex can build/run through the XcodeBuildMCP CLI adapter."""
    project_path = workspace_root / APPLE_MCP_XCODEBUILD_PROJECT_RELATIVE_PATH
    tool_args = {
        "project_path": str(project_path),
        "scheme": APPLE_MCP_XCODEBUILD_SCHEME,
        "configuration": APPLE_MCP_XCODEBUILD_CONFIGURATION,
        "simulator_name": simulator_name,
        "derived_data_path": str(derived_data_path),
        "extra_args": ["-quiet"],
        "use_latest_os": True,
    }
    tool_args_json = json.dumps(tool_args)
    prompts = (
        (
            "Tool invocation drill. After the required route block, your next "
            f"assistant item must be a real function call to {XCODEBUILD_CLI_TOOL}, "
            "not prose. Do not write JSON as text, pseudo-calls, `tool=...`, "
            "`mcp__...`, or dot notation. Use exactly these JSON arguments: "
            f"{tool_args_json}. After the tool result contains 'Build & Run "
            "complete', reply exactly XCODEBUILDMCP_CLI_RUN_OK."
        ),
        (
            "XcodeBuildMCP CLI adapter proof. Call the available dynamic tool "
            f"named {XCODEBUILD_CLI_TOOL} exactly once before answering. Pass "
            f"these exact arguments: {tool_args_json}. Do not use any other "
            "tool. Reply exactly XCODEBUILDMCP_CLI_RUN_OK only after the tool "
            "output says Build & Run complete."
        ),
    )
    errors: list[str] = []
    for attempt, prompt in enumerate(prompts, start=1):
        run = asyncio_run_session_query(
            agent_dir=agent_dir,
            codex_path=codex_path,
            prompt=prompt,
        )
        try:
            return _validate_xcodebuild_cli_run(
                run,
                attempt=attempt,
                expected_arguments=tool_args,
            )
        except XcodeBuildCliProofAttemptError as exc:
            errors.append(str(exc))
    joined_errors = "\n\n".join(errors)
    raise SystemExit(
        f"XcodeBuildMCP CLI adapter proof failed after {len(prompts)} attempts:\n{joined_errors}"
    )


def run_live_xcodebuild_cli_test_proof(
    agent_dir: Path,
    codex_path: Path,
    *,
    workspace_root: Path,
    simulator_name: str,
    derived_data_path: Path,
) -> AppleMcpProof:
    """Prove stock Codex can test through the XcodeBuildMCP CLI adapter."""
    project_path = workspace_root / APPLE_MCP_XCODEBUILD_PROJECT_RELATIVE_PATH
    tool_args = {
        "project_path": str(project_path),
        "scheme": APPLE_MCP_XCODEBUILD_SCHEME,
        "configuration": APPLE_MCP_XCODEBUILD_CONFIGURATION,
        "simulator_name": simulator_name,
        "derived_data_path": str(derived_data_path),
        "extra_args": ["-quiet"],
        "use_latest_os": True,
    }
    tool_args_json = json.dumps(tool_args)
    prompts = (
        (
            "Tool invocation drill. After the required route block, your next "
            f"assistant item must be a real function call to {XCODEBUILD_CLI_TEST_TOOL}, "
            "not prose. Do not write JSON as text, pseudo-calls, `tool=...`, "
            "`mcp__...`, or dot notation. Use exactly these JSON arguments: "
            f"{tool_args_json}. After the tool result contains '9 tests passed', "
            "reply exactly XCODEBUILDMCP_CLI_TEST_OK."
        ),
        (
            "XcodeBuildMCP CLI simulator test adapter proof. Call the available "
            f"dynamic tool named {XCODEBUILD_CLI_TEST_TOOL} exactly once before "
            f"answering. Pass these exact arguments: {tool_args_json}. Do not "
            "use any other tool. Reply exactly XCODEBUILDMCP_CLI_TEST_OK only "
            "after the tool output says 9 tests passed."
        ),
    )
    errors: list[str] = []
    for attempt, prompt in enumerate(prompts, start=1):
        run = asyncio_run_session_query(
            agent_dir=agent_dir,
            codex_path=codex_path,
            prompt=prompt,
        )
        try:
            return _validate_xcodebuild_cli_test(
                run,
                attempt=attempt,
                expected_arguments=tool_args,
            )
        except XcodeBuildCliProofAttemptError as exc:
            errors.append(str(exc))
    joined_errors = "\n\n".join(errors)
    raise SystemExit(
        f"XcodeBuildMCP CLI simulator test proof failed after {len(prompts)} "
        f"attempts:\n{joined_errors}"
    )


def run_live_xcodebuild_cli_screenshot_proof(
    agent_dir: Path,
    codex_path: Path,
    *,
    workspace_root: Path,
    simulator_name: str,
    derived_data_path: Path,
) -> AppleMcpProof:
    """Prove stock Codex can capture a screenshot through the CLI adapter."""
    project_path = workspace_root / APPLE_MCP_XCODEBUILD_PROJECT_RELATIVE_PATH
    tool_args = {
        "project_path": str(project_path),
        "scheme": APPLE_MCP_XCODEBUILD_SCHEME,
        "configuration": APPLE_MCP_XCODEBUILD_CONFIGURATION,
        "simulator_name": simulator_name,
        "derived_data_path": str(derived_data_path),
        "extra_args": ["-quiet"],
        "use_latest_os": True,
    }
    tool_args_json = json.dumps(tool_args)
    prompts = (
        (
            "Tool invocation drill. After the required route block, your next "
            f"assistant item must be a real function call to {XCODEBUILD_CLI_SCREENSHOT_TOOL}, "
            "not prose. Do not write JSON as text, pseudo-calls, `tool=...`, "
            "`mcp__...`, or dot notation. Use exactly these JSON arguments: "
            f"{tool_args_json}. After the tool result contains "
            '\'"screenshotStatus": "SUCCEEDED"\', reply exactly '
            "XCODEBUILDMCP_CLI_SCREENSHOT_OK."
        ),
        (
            "XcodeBuildMCP CLI simulator screenshot adapter proof. Call the "
            f"available dynamic tool named {XCODEBUILD_CLI_SCREENSHOT_TOOL} "
            f"exactly once before answering. Pass these exact arguments: {tool_args_json}. "
            "Do not use any other tool. Reply exactly "
            "XCODEBUILDMCP_CLI_SCREENSHOT_OK only after the tool output says "
            '"screenshotStatus": "SUCCEEDED".'
        ),
    )
    errors: list[str] = []
    for attempt, prompt in enumerate(prompts, start=1):
        run = asyncio_run_session_query(
            agent_dir=agent_dir,
            codex_path=codex_path,
            prompt=prompt,
        )
        try:
            return _validate_xcodebuild_cli_screenshot(
                run,
                attempt=attempt,
                expected_arguments=tool_args,
            )
        except XcodeBuildCliProofAttemptError as exc:
            errors.append(str(exc))
    joined_errors = "\n\n".join(errors)
    raise SystemExit(
        f"XcodeBuildMCP CLI simulator screenshot proof failed after {len(prompts)} "
        f"attempts:\n{joined_errors}"
    )


def run_live_xcodebuild_cli_runtime_logs_proof(
    agent_dir: Path,
    codex_path: Path,
    *,
    workspace_root: Path,
    simulator_name: str,
    derived_data_path: Path,
) -> AppleMcpProof:
    """Prove stock Codex can observe runtime logs through the CLI adapter."""
    project_path = workspace_root / APPLE_MCP_XCODEBUILD_PROJECT_RELATIVE_PATH
    tool_args = {
        "project_path": str(project_path),
        "scheme": APPLE_MCP_XCODEBUILD_SCHEME,
        "configuration": APPLE_MCP_XCODEBUILD_CONFIGURATION,
        "simulator_name": simulator_name,
        "derived_data_path": str(derived_data_path),
        "extra_args": ["-quiet"],
        "use_latest_os": True,
    }
    tool_args_json = json.dumps(tool_args)
    prompts = (
        (
            "Tool invocation drill. After the required route block, your next "
            f"assistant item must be a real function call to {XCODEBUILD_CLI_RUNTIME_LOGS_TOOL}, "
            "not prose. Do not write JSON as text, pseudo-calls, `tool=...`, "
            "`mcp__...`, or dot notation. Use exactly these JSON arguments: "
            f"{tool_args_json}. After the tool result contains "
            '\'"runtimeLogStatus": "SUCCEEDED"\', reply exactly '
            "XCODEBUILDMCP_CLI_RUNTIME_LOGS_OK."
        ),
        (
            "XcodeBuildMCP CLI simulator runtime logs adapter proof. Call the "
            f"available dynamic tool named {XCODEBUILD_CLI_RUNTIME_LOGS_TOOL} "
            f"exactly once before answering. Pass these exact arguments: {tool_args_json}. "
            "Do not use any other tool. Reply exactly "
            "XCODEBUILDMCP_CLI_RUNTIME_LOGS_OK only after the tool output says "
            '"runtimeLogStatus": "SUCCEEDED".'
        ),
    )
    errors: list[str] = []
    for attempt, prompt in enumerate(prompts, start=1):
        run = asyncio_run_session_query(
            agent_dir=agent_dir,
            codex_path=codex_path,
            prompt=prompt,
        )
        try:
            return _validate_xcodebuild_cli_runtime_logs(
                run,
                attempt=attempt,
                expected_arguments=tool_args,
            )
        except XcodeBuildCliProofAttemptError as exc:
            errors.append(str(exc))
    joined_errors = "\n\n".join(errors)
    raise SystemExit(
        f"XcodeBuildMCP CLI simulator runtime logs proof failed after {len(prompts)} "
        f"attempts:\n{joined_errors}"
    )


def run_live_xcodebuild_cli_snapshot_ui_proof(
    agent_dir: Path,
    codex_path: Path,
    *,
    workspace_root: Path,
    simulator_name: str,
    derived_data_path: Path,
    axe_path: Path | None,
) -> AppleMcpProof:
    """Prove stock Codex can capture semantic UI through the CLI adapter."""
    project_path = workspace_root / APPLE_MCP_XCODEBUILD_PROJECT_RELATIVE_PATH
    tool_args = {
        "project_path": str(project_path),
        "scheme": APPLE_MCP_XCODEBUILD_SCHEME,
        "configuration": APPLE_MCP_XCODEBUILD_CONFIGURATION,
        "simulator_name": simulator_name,
        "derived_data_path": str(derived_data_path),
        "extra_args": ["-quiet"],
        "use_latest_os": True,
    }
    tool_args_json = json.dumps(tool_args)
    prompts = (
        (
            "Tool invocation drill. After the required route block, your next "
            f"assistant item must be a real function call to {XCODEBUILD_CLI_SNAPSHOT_UI_TOOL}, "
            "not prose. Do not write JSON as text, pseudo-calls, `tool=...`, "
            "`mcp__...`, or dot notation. Use exactly these JSON arguments: "
            f"{tool_args_json}. After the tool result contains "
            '\'"snapshotStatus": "SUCCEEDED"\', reply exactly '
            "XCODEBUILDMCP_CLI_SNAPSHOT_UI_OK."
        ),
        (
            "XcodeBuildMCP CLI simulator semantic snapshot adapter proof. Call "
            f"the available dynamic tool named {XCODEBUILD_CLI_SNAPSHOT_UI_TOOL} "
            f"exactly once before answering. Pass these exact arguments: {tool_args_json}. "
            "Do not use any other tool. Reply exactly "
            "XCODEBUILDMCP_CLI_SNAPSHOT_UI_OK only after the tool output says "
            '"snapshotStatus": "SUCCEEDED".'
        ),
    )
    env_overrides = (
        {OMNIGENT_XCODEBUILDMCP_AXE_PATH_ENV: str(axe_path)} if axe_path is not None else {}
    )
    errors: list[str] = []
    with temporary_env(env_overrides):
        for attempt, prompt in enumerate(prompts, start=1):
            run = asyncio_run_session_query(
                agent_dir=agent_dir,
                codex_path=codex_path,
                prompt=prompt,
            )
            try:
                return _validate_xcodebuild_cli_snapshot_ui(
                    run,
                    attempt=attempt,
                    expected_arguments=tool_args,
                )
            except XcodeBuildCliProofAttemptError as exc:
                errors.append(str(exc))
    joined_errors = "\n\n".join(errors)
    raise SystemExit(
        f"XcodeBuildMCP CLI simulator semantic snapshot proof failed after "
        f"{len(prompts)} attempts:\n{joined_errors}"
    )


def run_live_xcodebuild_cli_type_text_proof(
    agent_dir: Path,
    codex_path: Path,
    *,
    workspace_root: Path,
    simulator_name: str,
    derived_data_path: Path,
    axe_path: Path | None,
) -> AppleMcpProof:
    """Prove stock Codex can perform bounded type-text UI interaction."""
    project_path = workspace_root / APPLE_MCP_XCODEBUILD_PROJECT_RELATIVE_PATH
    tool_args = {
        "project_path": str(project_path),
        "scheme": APPLE_MCP_XCODEBUILD_SCHEME,
        "configuration": APPLE_MCP_XCODEBUILD_CONFIGURATION,
        "simulator_name": simulator_name,
        "derived_data_path": str(derived_data_path),
        "text": XCODEBUILD_CLI_TYPE_TEXT_PROOF_TEXT,
        "extra_args": ["-quiet"],
        "use_latest_os": True,
    }
    tool_args_json = json.dumps(tool_args)
    prompts = (
        (
            "Tool invocation drill. After the required route block, your next "
            f"assistant item must be a real function call to {XCODEBUILD_CLI_TYPE_TEXT_TOOL}, "
            "not prose. Do not write JSON as text, pseudo-calls, `tool=...`, "
            "`mcp__...`, or dot notation. Use exactly these JSON arguments: "
            f"{tool_args_json}. After the tool result contains "
            '\'"typeTextStatus": "SUCCEEDED"\', reply exactly '
            "XCODEBUILDMCP_CLI_TYPE_TEXT_OK."
        ),
        (
            "XcodeBuildMCP CLI simulator type-text adapter proof. Call the "
            f"available dynamic tool named {XCODEBUILD_CLI_TYPE_TEXT_TOOL} "
            f"exactly once before answering. Pass these exact arguments: {tool_args_json}. "
            "Do not use any other tool. Reply exactly "
            "XCODEBUILDMCP_CLI_TYPE_TEXT_OK only after the tool output says "
            '"typeTextStatus": "SUCCEEDED".'
        ),
    )
    env_overrides = (
        {OMNIGENT_XCODEBUILDMCP_AXE_PATH_ENV: str(axe_path)} if axe_path is not None else {}
    )
    errors: list[str] = []
    with temporary_env(env_overrides):
        for attempt, prompt in enumerate(prompts, start=1):
            run = asyncio_run_session_query(
                agent_dir=agent_dir,
                codex_path=codex_path,
                prompt=prompt,
            )
            try:
                return _validate_xcodebuild_cli_type_text(
                    run,
                    attempt=attempt,
                    expected_arguments=tool_args,
                )
            except XcodeBuildCliProofAttemptError as exc:
                errors.append(str(exc))
    joined_errors = "\n\n".join(errors)
    raise SystemExit(
        f"XcodeBuildMCP CLI simulator type-text proof failed after "
        f"{len(prompts)} attempts:\n{joined_errors}"
    )


def run_live_xcodebuild_cli_tap_proof(
    agent_dir: Path,
    codex_path: Path,
    *,
    workspace_root: Path,
    simulator_name: str,
    derived_data_path: Path,
    axe_path: Path | None,
) -> AppleMcpProof:
    """Prove stock Codex can perform a bounded tap UI interaction."""
    project_path = workspace_root / APPLE_MCP_XCODEBUILD_PROJECT_RELATIVE_PATH
    tool_args = {
        "project_path": str(project_path),
        "scheme": APPLE_MCP_XCODEBUILD_SCHEME,
        "configuration": APPLE_MCP_XCODEBUILD_CONFIGURATION,
        "simulator_name": simulator_name,
        "derived_data_path": str(derived_data_path),
        "text": XCODEBUILD_CLI_TAP_PROOF_TEXT,
        "extra_args": ["-quiet"],
        "use_latest_os": True,
    }
    tool_args_json = json.dumps(tool_args)
    prompts = (
        (
            "Tool invocation drill. After the required route block, your next "
            f"assistant item must be a real function call to {XCODEBUILD_CLI_TAP_TOOL}, "
            "not prose. Do not write JSON as text, pseudo-calls, `tool=...`, "
            "`mcp__...`, or dot notation. Use exactly these JSON arguments: "
            f"{tool_args_json}. After the tool result contains "
            '\'"tapStatus": "SUCCEEDED"\', reply exactly XCODEBUILDMCP_CLI_TAP_OK.'
        ),
        (
            "XcodeBuildMCP CLI simulator tap adapter proof. Call the available "
            f"dynamic tool named {XCODEBUILD_CLI_TAP_TOOL} exactly once before "
            f"answering. Pass these exact arguments: {tool_args_json}. Do not use "
            "any other tool. Reply exactly XCODEBUILDMCP_CLI_TAP_OK only after "
            'the tool output says "tapStatus": "SUCCEEDED".'
        ),
    )
    env_overrides = (
        {OMNIGENT_XCODEBUILDMCP_AXE_PATH_ENV: str(axe_path)} if axe_path is not None else {}
    )
    errors: list[str] = []
    with temporary_env(env_overrides):
        for attempt, prompt in enumerate(prompts, start=1):
            run = asyncio_run_session_query(
                agent_dir=agent_dir,
                codex_path=codex_path,
                prompt=prompt,
            )
            try:
                return _validate_xcodebuild_cli_tap(
                    run,
                    attempt=attempt,
                    expected_arguments=tool_args,
                )
            except XcodeBuildCliProofAttemptError as exc:
                errors.append(str(exc))
    joined_errors = "\n\n".join(errors)
    raise SystemExit(
        f"XcodeBuildMCP CLI simulator tap proof failed after "
        f"{len(prompts)} attempts:\n{joined_errors}"
    )


class SosumiProofAttemptError(Exception):
    """One failed sosumi proof attempt that can be retried."""


class AppleDocsCliProofAttemptError(Exception):
    """One failed Apple docs CLI proof attempt that can be retried."""


class XcodeBuildCliProofAttemptError(Exception):
    """One failed XcodeBuildMCP CLI adapter proof attempt that can be retried."""


def _validate_sosumi_mcp_run(run: SessionRun, *, attempt: int) -> AppleMcpProof:
    """Validate one sosumi proof attempt."""
    transcript = run.text.strip()
    if not transcript.startswith(EXPECTED_ROUTE):
        raise SosumiProofAttemptError(
            f"attempt={attempt}: transcript did not start with expected route block.\n"
            f"Expected prefix:\n{EXPECTED_ROUTE}\n\nActual:\n{transcript[:1000]}"
        )

    calls = [
        item
        for item in run.items
        if item.get("type") == "function_call" and item.get("name") == APPLE_MCP_SOSUMI_TOOL
    ]
    if not calls:
        raise SosumiProofAttemptError(
            f"attempt={attempt}: " + _missing_tool_call_message(APPLE_MCP_SOSUMI_TOOL, run)
        )
    call = calls[-1]
    call_id = call.get("call_id")
    if not isinstance(call_id, str) or not call_id:
        raise SosumiProofAttemptError(
            f"attempt={attempt}: persisted {APPLE_MCP_SOSUMI_TOOL} call "
            f"has invalid call_id: {call!r}"
        )
    outputs = [
        item
        for item in run.items
        if item.get("type") == "function_call_output" and item.get("call_id") == call_id
    ]
    if not outputs:
        raise SosumiProofAttemptError(
            f"attempt={attempt}: no persisted function_call_output found for call_id={call_id}"
        )
    output_text = str(outputs[-1].get("output", ""))
    missing = [sentinel for sentinel in APPLE_MCP_SOSUMI_SENTINELS if sentinel not in output_text]
    if missing or "error" in output_text.lower():
        raise SosumiProofAttemptError(
            f"attempt={attempt}: sosumi MCP tool output missed expected "
            "documentation sentinels or looked erroneous. "
            f"missing={missing!r} output={output_text[:1000]}"
        )
    timestamp_match = APPLE_MCP_SOSUMI_TIMESTAMP_RE.search(output_text)
    if timestamp_match is None:
        raise SosumiProofAttemptError(
            f"attempt={attempt}: sosumi MCP tool output did not contain a timestamp "
            f"line. output={output_text[:1000]}"
        )
    expected_timestamp_reply = f"SOSUMI_MCP_TIMESTAMP={timestamp_match.group('timestamp')}"
    if expected_timestamp_reply not in transcript:
        raise SosumiProofAttemptError(
            f"attempt={attempt}: sosumi MCP proof did not return "
            f"{expected_timestamp_reply}. Transcript:\n{transcript}"
        )
    return AppleMcpProof(
        session_id=run.session_id,
        call_id=call_id,
        transcript=transcript,
        output_preview=output_text[:500],
    )


def _validate_apple_docs_cli_run(run: SessionRun, *, attempt: int) -> AppleMcpProof:
    """Validate one Apple docs CLI adapter proof attempt."""
    transcript = run.text.strip()
    if not transcript.startswith(EXPECTED_ROUTE):
        raise AppleDocsCliProofAttemptError(
            f"attempt={attempt}: transcript did not start with expected route block.\n"
            f"Expected prefix:\n{EXPECTED_ROUTE}\n\nActual:\n{transcript[:1000]}"
        )

    calls = [
        item
        for item in run.items
        if item.get("type") == "function_call" and item.get("name") == APPLE_DOCS_CLI_TOOL
    ]
    if not calls:
        raise AppleDocsCliProofAttemptError(
            f"attempt={attempt}: " + _missing_tool_call_message(APPLE_DOCS_CLI_TOOL, run)
        )
    call = calls[-1]
    call_id = call.get("call_id")
    if not isinstance(call_id, str) or not call_id:
        raise AppleDocsCliProofAttemptError(
            f"attempt={attempt}: persisted {APPLE_DOCS_CLI_TOOL} call "
            f"has invalid call_id: {call!r}"
        )
    arguments = _function_call_arguments(call)
    if arguments.get("url") != APPLE_DOCS_CLI_URL:
        raise AppleDocsCliProofAttemptError(
            f"attempt={attempt}: {APPLE_DOCS_CLI_TOOL} used unexpected url. "
            f"expected={APPLE_DOCS_CLI_URL!r} arguments={arguments!r}"
        )
    outputs = [
        item
        for item in run.items
        if item.get("type") == "function_call_output" and item.get("call_id") == call_id
    ]
    if not outputs:
        raise AppleDocsCliProofAttemptError(
            f"attempt={attempt}: no persisted function_call_output found for call_id={call_id}"
        )
    output_text = str(outputs[-1].get("output", ""))
    missing = [sentinel for sentinel in APPLE_MCP_SOSUMI_SENTINELS if sentinel not in output_text]
    if missing or "error" in output_text.lower():
        raise AppleDocsCliProofAttemptError(
            f"attempt={attempt}: Apple docs CLI output missed expected "
            "documentation sentinels or looked erroneous. "
            f"missing={missing!r} output={output_text[:1000]}"
        )
    timestamp_match = APPLE_MCP_SOSUMI_TIMESTAMP_RE.search(output_text)
    if timestamp_match is None:
        raise AppleDocsCliProofAttemptError(
            f"attempt={attempt}: Apple docs CLI output did not contain a timestamp "
            f"line. output={output_text[:1000]}"
        )
    expected_timestamp_reply = f"APPLE_DOCS_CLI_TIMESTAMP={timestamp_match.group('timestamp')}"
    if expected_timestamp_reply not in transcript:
        raise AppleDocsCliProofAttemptError(
            f"attempt={attempt}: Apple docs CLI proof did not return "
            f"{expected_timestamp_reply}. Transcript:\n{transcript}"
        )
    return AppleMcpProof(
        session_id=run.session_id,
        call_id=call_id,
        transcript=transcript,
        output_preview=output_text[:500],
    )


def _validate_xcodebuild_cli_run(
    run: SessionRun,
    *,
    attempt: int,
    expected_arguments: dict[str, object],
) -> AppleMcpProof:
    """Validate one XcodeBuildMCP CLI adapter proof attempt."""
    transcript = run.text.strip()
    if not transcript.startswith(EXPECTED_ROUTE):
        raise XcodeBuildCliProofAttemptError(
            f"attempt={attempt}: transcript did not start with expected route block.\n"
            f"Expected prefix:\n{EXPECTED_ROUTE}\n\nActual:\n{transcript[:1000]}"
        )

    calls = [
        item
        for item in run.items
        if item.get("type") == "function_call" and item.get("name") == XCODEBUILD_CLI_TOOL
    ]
    if not calls:
        raise XcodeBuildCliProofAttemptError(
            f"attempt={attempt}: " + _missing_tool_call_message(XCODEBUILD_CLI_TOOL, run)
        )
    call = calls[-1]
    call_id = call.get("call_id")
    if not isinstance(call_id, str) or not call_id:
        raise XcodeBuildCliProofAttemptError(
            f"attempt={attempt}: persisted {XCODEBUILD_CLI_TOOL} call "
            f"has invalid call_id: {call!r}"
        )
    arguments = _function_call_arguments(call)
    mismatches = {
        key: (expected, arguments.get(key))
        for key, expected in expected_arguments.items()
        if arguments.get(key) != expected
    }
    if mismatches:
        raise XcodeBuildCliProofAttemptError(
            f"attempt={attempt}: {XCODEBUILD_CLI_TOOL} used unexpected arguments. "
            f"mismatches={mismatches!r} arguments={arguments!r}"
        )
    outputs = [
        item
        for item in run.items
        if item.get("type") == "function_call_output" and item.get("call_id") == call_id
    ]
    if not outputs:
        raise XcodeBuildCliProofAttemptError(
            f"attempt={attempt}: no persisted function_call_output found for call_id={call_id}"
        )
    output_text = str(outputs[-1].get("output", ""))
    missing = [
        sentinel for sentinel in XCODEBUILD_CLI_RUN_SENTINELS if sentinel not in output_text
    ]
    if missing or "Error:" in output_text:
        raise XcodeBuildCliProofAttemptError(
            f"attempt={attempt}: XcodeBuildMCP CLI adapter output missed expected "
            "run sentinels or looked erroneous. "
            f"missing={missing!r} output={output_text[:1000]}"
        )
    if "XCODEBUILDMCP_CLI_RUN_OK" not in transcript:
        raise XcodeBuildCliProofAttemptError(
            f"attempt={attempt}: XcodeBuildMCP CLI adapter proof did not return "
            f"XCODEBUILDMCP_CLI_RUN_OK. Transcript:\n{transcript}"
        )
    return AppleMcpProof(
        session_id=run.session_id,
        call_id=call_id,
        transcript=transcript,
        output_preview=output_text[:500],
    )


def _validate_xcodebuild_cli_test(
    run: SessionRun,
    *,
    attempt: int,
    expected_arguments: dict[str, object],
) -> AppleMcpProof:
    """Validate one XcodeBuildMCP CLI simulator test adapter proof attempt."""
    transcript = run.text.strip()
    if not transcript.startswith(EXPECTED_ROUTE):
        raise XcodeBuildCliProofAttemptError(
            f"attempt={attempt}: transcript did not start with expected route block.\n"
            f"Expected prefix:\n{EXPECTED_ROUTE}\n\nActual:\n{transcript[:1000]}"
        )

    calls = [
        item
        for item in run.items
        if item.get("type") == "function_call" and item.get("name") == XCODEBUILD_CLI_TEST_TOOL
    ]
    if not calls:
        raise XcodeBuildCliProofAttemptError(
            f"attempt={attempt}: " + _missing_tool_call_message(XCODEBUILD_CLI_TEST_TOOL, run)
        )
    call = calls[-1]
    call_id = call.get("call_id")
    if not isinstance(call_id, str) or not call_id:
        raise XcodeBuildCliProofAttemptError(
            f"attempt={attempt}: persisted {XCODEBUILD_CLI_TEST_TOOL} call "
            f"has invalid call_id: {call!r}"
        )
    arguments = _function_call_arguments(call)
    mismatches = {
        key: (expected, arguments.get(key))
        for key, expected in expected_arguments.items()
        if arguments.get(key) != expected
    }
    if mismatches:
        raise XcodeBuildCliProofAttemptError(
            f"attempt={attempt}: {XCODEBUILD_CLI_TEST_TOOL} used unexpected "
            f"arguments. mismatches={mismatches!r} arguments={arguments!r}"
        )
    outputs = [
        item
        for item in run.items
        if item.get("type") == "function_call_output" and item.get("call_id") == call_id
    ]
    if not outputs:
        raise XcodeBuildCliProofAttemptError(
            f"attempt={attempt}: no persisted function_call_output found for call_id={call_id}"
        )
    output_text = str(outputs[-1].get("output", ""))
    missing = [
        sentinel for sentinel in XCODEBUILD_CLI_TEST_SENTINELS if sentinel not in output_text
    ]
    if missing or "Error:" in output_text:
        raise XcodeBuildCliProofAttemptError(
            f"attempt={attempt}: XcodeBuildMCP CLI test adapter output missed "
            "expected test sentinels or looked erroneous. "
            f"missing={missing!r} output={output_text[:1000]}"
        )
    if "XCODEBUILDMCP_CLI_TEST_OK" not in transcript:
        raise XcodeBuildCliProofAttemptError(
            f"attempt={attempt}: XcodeBuildMCP CLI test adapter proof did not "
            f"return XCODEBUILDMCP_CLI_TEST_OK. Transcript:\n{transcript}"
        )
    return AppleMcpProof(
        session_id=run.session_id,
        call_id=call_id,
        transcript=transcript,
        output_preview=output_text[:500],
    )


def _validate_xcodebuild_cli_screenshot(
    run: SessionRun,
    *,
    attempt: int,
    expected_arguments: dict[str, object],
) -> AppleMcpProof:
    """Validate one XcodeBuildMCP CLI screenshot adapter proof attempt."""
    transcript = run.text.strip()
    if not transcript.startswith(EXPECTED_ROUTE):
        raise XcodeBuildCliProofAttemptError(
            f"attempt={attempt}: transcript did not start with expected route block.\n"
            f"Expected prefix:\n{EXPECTED_ROUTE}\n\nActual:\n{transcript[:1000]}"
        )

    calls = [
        item
        for item in run.items
        if item.get("type") == "function_call"
        and item.get("name") == XCODEBUILD_CLI_SCREENSHOT_TOOL
    ]
    if not calls:
        raise XcodeBuildCliProofAttemptError(
            f"attempt={attempt}: "
            + _missing_tool_call_message(XCODEBUILD_CLI_SCREENSHOT_TOOL, run)
        )
    call = calls[-1]
    call_id = call.get("call_id")
    if not isinstance(call_id, str) or not call_id:
        raise XcodeBuildCliProofAttemptError(
            f"attempt={attempt}: persisted {XCODEBUILD_CLI_SCREENSHOT_TOOL} call "
            f"has invalid call_id: {call!r}"
        )
    arguments = _function_call_arguments(call)
    mismatches = {
        key: (expected, arguments.get(key))
        for key, expected in expected_arguments.items()
        if arguments.get(key) != expected
    }
    if mismatches:
        raise XcodeBuildCliProofAttemptError(
            f"attempt={attempt}: {XCODEBUILD_CLI_SCREENSHOT_TOOL} used unexpected "
            f"arguments. mismatches={mismatches!r} arguments={arguments!r}"
        )
    outputs = [
        item
        for item in run.items
        if item.get("type") == "function_call_output" and item.get("call_id") == call_id
    ]
    if not outputs:
        raise XcodeBuildCliProofAttemptError(
            f"attempt={attempt}: no persisted function_call_output found for call_id={call_id}"
        )
    output_text = str(outputs[-1].get("output", ""))
    missing = [
        sentinel for sentinel in XCODEBUILD_CLI_SCREENSHOT_SENTINELS if sentinel not in output_text
    ]
    if missing or "Error:" in output_text:
        raise XcodeBuildCliProofAttemptError(
            f"attempt={attempt}: XcodeBuildMCP CLI screenshot adapter output missed "
            "expected screenshot sentinels or looked erroneous. "
            f"missing={missing!r} output={output_text[:1000]}"
        )
    try:
        parsed_output = json.loads(output_text)
    except json.JSONDecodeError as exc:
        raise XcodeBuildCliProofAttemptError(
            f"attempt={attempt}: screenshot adapter returned invalid JSON: {exc}"
        ) from exc
    screenshot_path = parsed_output.get("screenshotPath")
    width = parsed_output.get("width")
    height = parsed_output.get("height")
    if (
        not isinstance(screenshot_path, str)
        or not screenshot_path
        or not isinstance(width, int)
        or width <= 0
        or not isinstance(height, int)
        or height <= 0
    ):
        raise XcodeBuildCliProofAttemptError(
            f"attempt={attempt}: screenshot adapter JSON missed a usable path or size. "
            f"output={parsed_output!r}"
        )
    if "XCODEBUILDMCP_CLI_SCREENSHOT_OK" not in transcript:
        raise XcodeBuildCliProofAttemptError(
            f"attempt={attempt}: XcodeBuildMCP CLI screenshot adapter proof did not "
            f"return XCODEBUILDMCP_CLI_SCREENSHOT_OK. Transcript:\n{transcript}"
        )
    return AppleMcpProof(
        session_id=run.session_id,
        call_id=call_id,
        transcript=transcript,
        output_preview=output_text[:500],
    )


def _validate_xcodebuild_cli_runtime_logs(
    run: SessionRun,
    *,
    attempt: int,
    expected_arguments: dict[str, object],
) -> AppleMcpProof:
    """Validate one XcodeBuildMCP CLI runtime-log adapter proof attempt."""
    transcript = run.text.strip()
    if not transcript.startswith(EXPECTED_ROUTE):
        raise XcodeBuildCliProofAttemptError(
            f"attempt={attempt}: transcript did not start with expected route block.\n"
            f"Expected prefix:\n{EXPECTED_ROUTE}\n\nActual:\n{transcript[:1000]}"
        )

    calls = [
        item
        for item in run.items
        if item.get("type") == "function_call"
        and item.get("name") == XCODEBUILD_CLI_RUNTIME_LOGS_TOOL
    ]
    if not calls:
        raise XcodeBuildCliProofAttemptError(
            f"attempt={attempt}: "
            + _missing_tool_call_message(XCODEBUILD_CLI_RUNTIME_LOGS_TOOL, run)
        )
    call = calls[-1]
    call_id = call.get("call_id")
    if not isinstance(call_id, str) or not call_id:
        raise XcodeBuildCliProofAttemptError(
            f"attempt={attempt}: persisted {XCODEBUILD_CLI_RUNTIME_LOGS_TOOL} call "
            f"has invalid call_id: {call!r}"
        )
    arguments = _function_call_arguments(call)
    mismatches = {
        key: (expected, arguments.get(key))
        for key, expected in expected_arguments.items()
        if arguments.get(key) != expected
    }
    if mismatches:
        raise XcodeBuildCliProofAttemptError(
            f"attempt={attempt}: {XCODEBUILD_CLI_RUNTIME_LOGS_TOOL} used unexpected "
            f"arguments. mismatches={mismatches!r} arguments={arguments!r}"
        )
    outputs = [
        item
        for item in run.items
        if item.get("type") == "function_call_output" and item.get("call_id") == call_id
    ]
    if not outputs:
        raise XcodeBuildCliProofAttemptError(
            f"attempt={attempt}: no persisted function_call_output found for call_id={call_id}"
        )
    output_text = str(outputs[-1].get("output", ""))
    missing = [
        sentinel
        for sentinel in XCODEBUILD_CLI_RUNTIME_LOGS_SENTINELS
        if sentinel not in output_text
    ]
    if missing or "Error:" in output_text:
        raise XcodeBuildCliProofAttemptError(
            f"attempt={attempt}: XcodeBuildMCP CLI runtime logs adapter output missed "
            "expected log sentinels or looked erroneous. "
            f"missing={missing!r} output={output_text[:1000]}"
        )
    try:
        parsed_output = json.loads(output_text)
    except json.JSONDecodeError as exc:
        raise XcodeBuildCliProofAttemptError(
            f"attempt={attempt}: runtime logs adapter returned invalid JSON: {exc}"
        ) from exc
    runtime_log_path = parsed_output.get("runtimeLogPath")
    os_log_path = parsed_output.get("osLogPath")
    runtime_excerpt = parsed_output.get("runtimeLogExcerpt")
    os_excerpt = parsed_output.get("osLogExcerpt")
    runtime_line_count = parsed_output.get("runtimeLogLineCount")
    os_line_count = parsed_output.get("osLogLineCount")
    if (
        not isinstance(runtime_log_path, str)
        or not runtime_log_path
        or not isinstance(os_log_path, str)
        or not os_log_path
        or not isinstance(runtime_excerpt, list)
        or not runtime_excerpt
        or not isinstance(os_excerpt, list)
        or not os_excerpt
        or not isinstance(runtime_line_count, int)
        or runtime_line_count <= 0
        or not isinstance(os_line_count, int)
        or os_line_count <= 0
    ):
        raise XcodeBuildCliProofAttemptError(
            f"attempt={attempt}: runtime logs adapter JSON missed usable log evidence. "
            f"output={parsed_output!r}"
        )
    if "XCODEBUILDMCP_CLI_RUNTIME_LOGS_OK" not in transcript:
        raise XcodeBuildCliProofAttemptError(
            f"attempt={attempt}: XcodeBuildMCP CLI runtime logs adapter proof did not "
            f"return XCODEBUILDMCP_CLI_RUNTIME_LOGS_OK. Transcript:\n{transcript}"
        )
    return AppleMcpProof(
        session_id=run.session_id,
        call_id=call_id,
        transcript=transcript,
        output_preview=output_text[:500],
    )


def _validate_xcodebuild_cli_snapshot_ui(
    run: SessionRun,
    *,
    attempt: int,
    expected_arguments: dict[str, object],
) -> AppleMcpProof:
    """Validate one XcodeBuildMCP CLI semantic snapshot adapter proof attempt."""
    transcript = run.text.strip()
    if not transcript.startswith(EXPECTED_ROUTE):
        raise XcodeBuildCliProofAttemptError(
            f"attempt={attempt}: transcript did not start with expected route block.\n"
            f"Expected prefix:\n{EXPECTED_ROUTE}\n\nActual:\n{transcript[:1000]}"
        )

    calls = [
        item
        for item in run.items
        if item.get("type") == "function_call"
        and item.get("name") == XCODEBUILD_CLI_SNAPSHOT_UI_TOOL
    ]
    if not calls:
        raise XcodeBuildCliProofAttemptError(
            f"attempt={attempt}: "
            + _missing_tool_call_message(XCODEBUILD_CLI_SNAPSHOT_UI_TOOL, run)
        )
    call = calls[-1]
    call_id = call.get("call_id")
    if not isinstance(call_id, str) or not call_id:
        raise XcodeBuildCliProofAttemptError(
            f"attempt={attempt}: persisted {XCODEBUILD_CLI_SNAPSHOT_UI_TOOL} call "
            f"has invalid call_id: {call!r}"
        )
    arguments = _function_call_arguments(call)
    mismatches = {
        key: (expected, arguments.get(key))
        for key, expected in expected_arguments.items()
        if arguments.get(key) != expected
    }
    if mismatches:
        raise XcodeBuildCliProofAttemptError(
            f"attempt={attempt}: {XCODEBUILD_CLI_SNAPSHOT_UI_TOOL} used unexpected "
            f"arguments. mismatches={mismatches!r} arguments={arguments!r}"
        )
    outputs = [
        item
        for item in run.items
        if item.get("type") == "function_call_output" and item.get("call_id") == call_id
    ]
    if not outputs:
        raise XcodeBuildCliProofAttemptError(
            f"attempt={attempt}: no persisted function_call_output found for call_id={call_id}"
        )
    output_text = str(outputs[-1].get("output", ""))
    missing = [
        sentinel
        for sentinel in XCODEBUILD_CLI_SNAPSHOT_UI_SENTINELS
        if sentinel not in output_text
    ]
    if missing or "Error:" in output_text:
        raise XcodeBuildCliProofAttemptError(
            f"attempt={attempt}: XcodeBuildMCP CLI snapshot-ui adapter output missed "
            "expected snapshot sentinels or looked erroneous. "
            f"missing={missing!r} output={output_text[:1000]}"
        )
    try:
        parsed_output = json.loads(output_text)
    except json.JSONDecodeError as exc:
        raise XcodeBuildCliProofAttemptError(
            f"attempt={attempt}: snapshot-ui adapter returned invalid JSON: {exc}"
        ) from exc
    count = parsed_output.get("count")
    targets = parsed_output.get("targets")
    if not isinstance(count, int) or count <= 0:
        raise XcodeBuildCliProofAttemptError(
            f"attempt={attempt}: snapshot-ui adapter JSON missed positive count. "
            f"output={parsed_output!r}"
        )
    if not isinstance(targets, list) or not targets:
        raise XcodeBuildCliProofAttemptError(
            f"attempt={attempt}: snapshot-ui adapter JSON missed targets. output={parsed_output!r}"
        )
    if "XCODEBUILDMCP_CLI_SNAPSHOT_UI_OK" not in transcript:
        raise XcodeBuildCliProofAttemptError(
            f"attempt={attempt}: XcodeBuildMCP CLI snapshot-ui adapter proof did not "
            f"return XCODEBUILDMCP_CLI_SNAPSHOT_UI_OK. Transcript:\n{transcript}"
        )
    return AppleMcpProof(
        session_id=run.session_id,
        call_id=call_id,
        transcript=transcript,
        output_preview=output_text[:500],
    )


def _validate_xcodebuild_cli_type_text(
    run: SessionRun,
    *,
    attempt: int,
    expected_arguments: dict[str, object],
) -> AppleMcpProof:
    """Validate one XcodeBuildMCP CLI type-text adapter proof attempt."""
    transcript = run.text.strip()
    if not transcript.startswith(EXPECTED_ROUTE):
        raise XcodeBuildCliProofAttemptError(
            f"attempt={attempt}: transcript did not start with expected route block.\n"
            f"Expected prefix:\n{EXPECTED_ROUTE}\n\nActual:\n{transcript[:1000]}"
        )

    calls = [
        item
        for item in run.items
        if item.get("type") == "function_call"
        and item.get("name") == XCODEBUILD_CLI_TYPE_TEXT_TOOL
    ]
    if not calls:
        raise XcodeBuildCliProofAttemptError(
            f"attempt={attempt}: " + _missing_tool_call_message(XCODEBUILD_CLI_TYPE_TEXT_TOOL, run)
        )
    call = calls[-1]
    call_id = call.get("call_id")
    if not isinstance(call_id, str) or not call_id:
        raise XcodeBuildCliProofAttemptError(
            f"attempt={attempt}: persisted {XCODEBUILD_CLI_TYPE_TEXT_TOOL} call "
            f"has invalid call_id: {call!r}"
        )
    arguments = _function_call_arguments(call)
    mismatches = {
        key: (expected, arguments.get(key))
        for key, expected in expected_arguments.items()
        if arguments.get(key) != expected
    }
    if mismatches:
        raise XcodeBuildCliProofAttemptError(
            f"attempt={attempt}: {XCODEBUILD_CLI_TYPE_TEXT_TOOL} used unexpected "
            f"arguments. mismatches={mismatches!r} arguments={arguments!r}"
        )
    outputs = [
        item
        for item in run.items
        if item.get("type") == "function_call_output" and item.get("call_id") == call_id
    ]
    if not outputs:
        raise XcodeBuildCliProofAttemptError(
            f"attempt={attempt}: no persisted function_call_output found for call_id={call_id}"
        )
    output_text = str(outputs[-1].get("output", ""))
    missing = [
        sentinel for sentinel in XCODEBUILD_CLI_TYPE_TEXT_SENTINELS if sentinel not in output_text
    ]
    if missing or "Error:" in output_text:
        raise XcodeBuildCliProofAttemptError(
            f"attempt={attempt}: XcodeBuildMCP CLI type-text adapter output missed "
            "expected interaction sentinels or looked erroneous. "
            f"missing={missing!r} output={output_text[:1000]}"
        )
    try:
        parsed_output = json.loads(output_text)
    except json.JSONDecodeError as exc:
        raise XcodeBuildCliProofAttemptError(
            f"attempt={attempt}: type-text adapter returned invalid JSON: {exc}"
        ) from exc
    element_ref = parsed_output.get("elementRef")
    before_target = parsed_output.get("beforeTarget")
    after_targets = parsed_output.get("afterTargets")
    typed_text = parsed_output.get("typedText")
    verified_text = parsed_output.get("verifiedText")
    if (
        parsed_output.get("typeTextStatus") != "SUCCEEDED"
        or parsed_output.get("waitStatus") != "SUCCEEDED"
        or not isinstance(element_ref, str)
        or not element_ref
        or not isinstance(before_target, str)
        or "typeText" not in before_target
        or "text-field" not in before_target
        or not isinstance(after_targets, list)
        or not after_targets
        or typed_text != XCODEBUILD_CLI_TYPE_TEXT_PROOF_TEXT
        or verified_text != XCODEBUILD_CLI_TYPE_TEXT_PROOF_TEXT
        or not any(XCODEBUILD_CLI_TYPE_TEXT_PROOF_TEXT in str(target) for target in after_targets)
    ):
        raise XcodeBuildCliProofAttemptError(
            f"attempt={attempt}: type-text adapter JSON missed usable interaction evidence. "
            f"output={parsed_output!r}"
        )
    if "XCODEBUILDMCP_CLI_TYPE_TEXT_OK" not in transcript:
        raise XcodeBuildCliProofAttemptError(
            f"attempt={attempt}: XcodeBuildMCP CLI type-text adapter proof did not "
            f"return XCODEBUILDMCP_CLI_TYPE_TEXT_OK. Transcript:\n{transcript}"
        )
    return AppleMcpProof(
        session_id=run.session_id,
        call_id=call_id,
        transcript=transcript,
        output_preview=output_text[:500],
    )


def _validate_xcodebuild_cli_tap(
    run: SessionRun,
    *,
    attempt: int,
    expected_arguments: dict[str, object],
) -> AppleMcpProof:
    """Validate one XcodeBuildMCP CLI tap adapter proof attempt."""
    transcript = run.text.strip()
    if not transcript.startswith(EXPECTED_ROUTE):
        raise XcodeBuildCliProofAttemptError(
            f"attempt={attempt}: transcript did not start with expected route block.\n"
            f"Expected prefix:\n{EXPECTED_ROUTE}\n\nActual:\n{transcript[:1000]}"
        )

    calls = [
        item
        for item in run.items
        if item.get("type") == "function_call" and item.get("name") == XCODEBUILD_CLI_TAP_TOOL
    ]
    if not calls:
        raise XcodeBuildCliProofAttemptError(
            f"attempt={attempt}: " + _missing_tool_call_message(XCODEBUILD_CLI_TAP_TOOL, run)
        )
    call = calls[-1]
    call_id = call.get("call_id")
    if not isinstance(call_id, str) or not call_id:
        raise XcodeBuildCliProofAttemptError(
            f"attempt={attempt}: persisted {XCODEBUILD_CLI_TAP_TOOL} call "
            f"has invalid call_id: {call!r}"
        )
    arguments = _function_call_arguments(call)
    mismatches = {
        key: (expected, arguments.get(key))
        for key, expected in expected_arguments.items()
        if arguments.get(key) != expected
    }
    if mismatches:
        raise XcodeBuildCliProofAttemptError(
            f"attempt={attempt}: {XCODEBUILD_CLI_TAP_TOOL} used unexpected "
            f"arguments. mismatches={mismatches!r} arguments={arguments!r}"
        )
    outputs = [
        item
        for item in run.items
        if item.get("type") == "function_call_output" and item.get("call_id") == call_id
    ]
    if not outputs:
        raise XcodeBuildCliProofAttemptError(
            f"attempt={attempt}: no persisted function_call_output found for call_id={call_id}"
        )
    output_text = str(outputs[-1].get("output", ""))
    missing = [
        sentinel for sentinel in XCODEBUILD_CLI_TAP_SENTINELS if sentinel not in output_text
    ]
    if missing or "Error:" in output_text:
        raise XcodeBuildCliProofAttemptError(
            f"attempt={attempt}: XcodeBuildMCP CLI tap adapter output missed "
            "expected interaction sentinels or looked erroneous. "
            f"missing={missing!r} output={output_text[:1000]}"
        )
    try:
        parsed_output = json.loads(output_text)
    except json.JSONDecodeError as exc:
        raise XcodeBuildCliProofAttemptError(
            f"attempt={attempt}: tap adapter returned invalid JSON: {exc}"
        ) from exc
    tap_element_ref = parsed_output.get("tapElementRef")
    tap_target = parsed_output.get("tapTarget")
    after_tap_target = parsed_output.get("afterTapTarget")
    after_tap_targets = parsed_output.get("afterTapTargets")
    typed_target = parsed_output.get("typedTarget")
    if (
        parsed_output.get("preResetBuildStatus") != "SUCCEEDED"
        or parsed_output.get("resetStatus") != "SUCCEEDED"
        or parsed_output.get("typeTextStatus") != "SUCCEEDED"
        or parsed_output.get("typedWaitStatus") != "SUCCEEDED"
        or parsed_output.get("tapStatus") != "SUCCEEDED"
        or parsed_output.get("settledStatus") != "SUCCEEDED"
        or parsed_output.get("typedText") != XCODEBUILD_CLI_TAP_PROOF_TEXT
        or parsed_output.get("postTapText") != XCODEBUILD_CLI_TAP_POST_TEXT
        or not isinstance(tap_element_ref, str)
        or not tap_element_ref
        or not isinstance(tap_target, str)
        or "tap" not in tap_target
        or "button|Connect" not in tap_target
        or not isinstance(typed_target, str)
        or XCODEBUILD_CLI_TAP_PROOF_TEXT not in typed_target
        or not isinstance(after_tap_target, str)
        or XCODEBUILD_CLI_TAP_POST_TEXT not in after_tap_target
        or XCODEBUILD_CLI_TAP_PROOF_TEXT in after_tap_target
        or not isinstance(after_tap_targets, list)
        or not after_tap_targets
        or any(XCODEBUILD_CLI_TAP_PROOF_TEXT in str(target) for target in after_tap_targets)
    ):
        raise XcodeBuildCliProofAttemptError(
            f"attempt={attempt}: tap adapter JSON missed usable interaction evidence. "
            f"output={parsed_output!r}"
        )
    if "XCODEBUILDMCP_CLI_TAP_OK" not in transcript:
        raise XcodeBuildCliProofAttemptError(
            f"attempt={attempt}: XcodeBuildMCP CLI tap adapter proof did not "
            f"return XCODEBUILDMCP_CLI_TAP_OK. Transcript:\n{transcript}"
        )
    return AppleMcpProof(
        session_id=run.session_id,
        call_id=call_id,
        transcript=transcript,
        output_preview=output_text[:500],
    )


def run_live_apple_xcodebuild_mcp_proof(
    agent_dir: Path,
    codex_path: Path,
    *,
    workspace_root: Path,
) -> AppleMcpProof:
    """Prove stock Codex can call a read-only XcodeBuildMCP discovery tool."""
    workspace = str(workspace_root)
    prompts = (
        (
            "Tool invocation drill. After the required route block, your next "
            f"action must be a function call to {APPLE_MCP_XCODEBUILD_TOOL}, "
            "not prose. Use JSON arguments "
            f'{{"workspaceRoot": "{workspace}", "maxDepth": 5}}. Do not call '
            "any build, run, test, simulator, device, scaffold, launch, or "
            "session mutation tool. After the tool result is available, reply "
            "exactly XCODEBUILDMCP_OK."
        ),
        (
            "Read-only XcodeBuildMCP project-discovery proof. Call the "
            f"available tool named {APPLE_MCP_XCODEBUILD_TOOL} exactly once "
            "with JSON arguments "
            f'{{"workspaceRoot": "{workspace}", "maxDepth": 5}}. Do not use '
            "any other tool. After the tool call succeeds, reply exactly "
            "XCODEBUILDMCP_OK."
        ),
        (
            f"Use {APPLE_MCP_XCODEBUILD_TOOL} now to scan {workspace}. This "
            "is a tool-call proof; a text answer without the function call is "
            "invalid. Do not build, run, test, launch, or mutate defaults. "
            "After the function call output is available, reply exactly "
            "XCODEBUILDMCP_OK."
        ),
    )
    errors: list[str] = []
    for attempt, prompt in enumerate(prompts, start=1):
        run = asyncio_run_session_query(
            agent_dir=agent_dir,
            codex_path=codex_path,
            prompt=prompt,
        )
        try:
            return _validate_xcodebuild_mcp_run(
                run,
                attempt=attempt,
                workspace_root=workspace_root,
            )
        except XcodeBuildMcpProofAttemptError as exc:
            errors.append(str(exc))
    joined_errors = "\n\n".join(errors)
    raise SystemExit(f"XcodeBuildMCP proof failed after {len(prompts)} attempts:\n{joined_errors}")


def run_live_apple_xcodebuild_mcp_build_proof(
    agent_dir: Path,
    codex_path: Path,
    *,
    workspace_root: Path,
    simulator_name: str,
    derived_data_path: Path,
) -> XcodeBuildMcpBuildProof:
    """Prove stock Codex can drive a compile-only XcodeBuildMCP simulator build."""
    project_path = workspace_root / APPLE_MCP_XCODEBUILD_PROJECT_RELATIVE_PATH
    set_defaults_args = (
        "{"
        f'"projectPath": "{project_path}", '
        f'"scheme": "{APPLE_MCP_XCODEBUILD_SCHEME}", '
        f'"configuration": "{APPLE_MCP_XCODEBUILD_CONFIGURATION}", '
        f'"simulatorName": "{simulator_name}", '
        '"simulatorPlatform": "iOS Simulator", '
        '"useLatestOS": true, '
        '"persist": false, '
        '"suppressWarnings": true, '
        f'"derivedDataPath": "{derived_data_path}"'
        "}"
    )
    build_args = '{"extraArgs": ["-quiet"]}'
    prompts = (
        (
            "Function-call drill. After the required route block, your next "
            "assistant item must be a real tool/function call, not prose. Do "
            "not write JSON, pseudo-calls, `tool=...`, `mcp__...`, or dot "
            "notation in text. Use only these exact function names, in order: "
            f"{APPLE_MCP_XCODEBUILD_SESSION_SHOW_DEFAULTS_TOOL} with {{}}, "
            f"{APPLE_MCP_XCODEBUILD_SESSION_SET_DEFAULTS_TOOL} with "
            f"{set_defaults_args}, then {APPLE_MCP_XCODEBUILD_BUILD_SIM_TOOL} "
            f"with {build_args}. This is compile-only; do not call build_run_sim, "
            "launch_app_sim, boot_sim, open_sim, test, device, or any persisted "
            "defaults tool. After the build tool result reports success, reply "
            "exactly XCODEBUILDMCP_BUILD_OK."
        ),
        (
            "XcodeBuildMCP compile-only simulator build proof. A text answer "
            "with JSON is invalid; only persisted function_call items count. "
            f"Call {APPLE_MCP_XCODEBUILD_SESSION_SHOW_DEFAULTS_TOOL} with empty "
            f"arguments, then call {APPLE_MCP_XCODEBUILD_SESSION_SET_DEFAULTS_TOOL} "
            f"with {set_defaults_args}, then call "
            f"{APPLE_MCP_XCODEBUILD_BUILD_SIM_TOOL} with {build_args}. "
            "Do not launch, boot, run, test, or persist defaults. Reply exactly "
            "XCODEBUILDMCP_BUILD_OK only after the build_sim tool output says "
            "the build succeeded."
        ),
    )
    errors: list[str] = []
    for attempt, prompt in enumerate(prompts, start=1):
        run = asyncio_run_session_query(
            agent_dir=agent_dir,
            codex_path=codex_path,
            prompt=prompt,
        )
        try:
            return _validate_xcodebuild_mcp_build_run(
                run,
                project_path=project_path,
                simulator_name=simulator_name,
                derived_data_path=derived_data_path,
            )
        except XcodeBuildMcpBuildProofError as exc:
            errors.append(f"attempt={attempt}: {exc}")
    joined_errors = "\n\n".join(errors)
    raise SystemExit(
        f"XcodeBuildMCP build proof failed after {len(prompts)} attempts:\n{joined_errors}"
    )


def run_live_apple_xcodebuild_mcp_run_proof(
    agent_dir: Path,
    codex_path: Path,
    *,
    workspace_root: Path,
    simulator_name: str,
    derived_data_path: Path,
) -> XcodeBuildMcpRunProof:
    """Prove stock Codex can drive an XcodeBuildMCP simulator build/install/launch."""
    project_path = workspace_root / APPLE_MCP_XCODEBUILD_PROJECT_RELATIVE_PATH
    set_defaults_args = (
        "{"
        f'"projectPath": "{project_path}", '
        f'"scheme": "{APPLE_MCP_XCODEBUILD_SCHEME}", '
        f'"configuration": "{APPLE_MCP_XCODEBUILD_CONFIGURATION}", '
        f'"simulatorName": "{simulator_name}", '
        '"simulatorPlatform": "iOS Simulator", '
        '"useLatestOS": true, '
        '"persist": false, '
        '"suppressWarnings": true, '
        f'"derivedDataPath": "{derived_data_path}"'
        "}"
    )
    run_args = '{"extraArgs": ["-quiet"]}'
    prompts = (
        (
            "Function-call drill. After the required route block, your next "
            "assistant item must be a real tool/function call, not prose. Do "
            "not write JSON, pseudo-calls, `tool=...`, `mcp__...`, or dot "
            "notation in text. Use only these exact function names, in order: "
            f"{APPLE_MCP_XCODEBUILD_SESSION_SHOW_DEFAULTS_TOOL} with {{}}, "
            f"{APPLE_MCP_XCODEBUILD_SESSION_SET_DEFAULTS_TOOL} with "
            f"{set_defaults_args}, then {APPLE_MCP_XCODEBUILD_BUILD_RUN_SIM_TOOL} "
            f"with {run_args}. This boundary is build/install/launch only; "
            "do not call build_sim, launch_app_sim, boot_sim, open_sim, test, "
            "device, log, screenshot, UI automation, or any persisted defaults "
            "tool. After the build_run_sim result reports that the app is now "
            "running in the iOS Simulator, reply exactly XCODEBUILDMCP_RUN_OK."
        ),
        (
            "XcodeBuildMCP simulator run proof. A text answer with JSON is "
            "invalid; only persisted function_call items count. Call "
            f"{APPLE_MCP_XCODEBUILD_SESSION_SHOW_DEFAULTS_TOOL} with empty "
            f"arguments, then call {APPLE_MCP_XCODEBUILD_SESSION_SET_DEFAULTS_TOOL} "
            f"with {set_defaults_args}, then call "
            f"{APPLE_MCP_XCODEBUILD_BUILD_RUN_SIM_TOOL} with {run_args}. "
            "Do not call any other XcodeBuildMCP tool. Reply exactly "
            "XCODEBUILDMCP_RUN_OK only after the build_run_sim tool output says "
            "the app is now running in the iOS Simulator."
        ),
    )
    errors: list[str] = []
    for attempt, prompt in enumerate(prompts, start=1):
        run = asyncio_run_session_query(
            agent_dir=agent_dir,
            codex_path=codex_path,
            prompt=prompt,
        )
        try:
            return _validate_xcodebuild_mcp_run_launch(
                run,
                project_path=project_path,
                simulator_name=simulator_name,
                derived_data_path=derived_data_path,
            )
        except XcodeBuildMcpRunProofError as exc:
            errors.append(f"attempt={attempt}: {exc}")
    joined_errors = "\n\n".join(errors)
    raise SystemExit(
        f"XcodeBuildMCP simulator run proof failed after {len(prompts)} attempts:\n{joined_errors}"
    )


class XcodeBuildMcpProofAttemptError(Exception):
    """One failed XcodeBuildMCP proof attempt that can be retried."""


class AppleWorkflowSmokeProofError(Exception):
    """One failed representative Apple workflow smoke attempt."""


class XcodeBuildMcpSequenceProofError(Exception):
    """A failed ordered XcodeBuildMCP tool sequence proof."""


class XcodeBuildMcpBuildProofError(XcodeBuildMcpSequenceProofError):
    """A failed XcodeBuildMCP build boundary proof."""


class XcodeBuildMcpRunProofError(XcodeBuildMcpSequenceProofError):
    """A failed XcodeBuildMCP simulator run boundary proof."""


def _validate_xcodebuild_mcp_run(
    run: SessionRun,
    *,
    attempt: int,
    workspace_root: Path,
) -> AppleMcpProof:
    """Validate one XcodeBuildMCP discovery proof attempt."""
    transcript = run.text.strip()
    if not transcript.startswith(EXPECTED_ROUTE):
        raise XcodeBuildMcpProofAttemptError(
            f"attempt={attempt}: transcript did not start with expected route block.\n"
            f"Expected prefix:\n{EXPECTED_ROUTE}\n\nActual:\n{transcript[:1000]}"
        )

    calls = [
        item
        for item in run.items
        if item.get("type") == "function_call" and item.get("name") == APPLE_MCP_XCODEBUILD_TOOL
    ]
    if not calls:
        raise XcodeBuildMcpProofAttemptError(
            f"attempt={attempt}: " + _missing_tool_call_message(APPLE_MCP_XCODEBUILD_TOOL, run)
        )
    call = calls[-1]
    call_id = call.get("call_id")
    if not isinstance(call_id, str) or not call_id:
        raise XcodeBuildMcpProofAttemptError(
            f"attempt={attempt}: persisted {APPLE_MCP_XCODEBUILD_TOOL} call "
            f"has invalid call_id: {call!r}"
        )
    arguments = _function_call_arguments(call)
    expected_workspace = str(workspace_root)
    if arguments.get("workspaceRoot") != expected_workspace:
        raise XcodeBuildMcpProofAttemptError(
            f"attempt={attempt}: {APPLE_MCP_XCODEBUILD_TOOL} used unexpected "
            f"workspaceRoot. expected={expected_workspace!r} arguments={arguments!r}"
        )
    outputs = [
        item
        for item in run.items
        if item.get("type") == "function_call_output" and item.get("call_id") == call_id
    ]
    if not outputs:
        raise XcodeBuildMcpProofAttemptError(
            f"attempt={attempt}: no persisted function_call_output found for call_id={call_id}"
        )
    output_text = str(outputs[-1].get("output", ""))
    missing = [
        sentinel for sentinel in APPLE_MCP_XCODEBUILD_SENTINELS if sentinel not in output_text
    ]
    if missing:
        raise XcodeBuildMcpProofAttemptError(
            f"attempt={attempt}: XcodeBuildMCP output missed expected discovery "
            f"sentinels. missing={missing!r} output={output_text[:1000]}"
        )
    if "XCODEBUILDMCP_OK" not in transcript:
        raise XcodeBuildMcpProofAttemptError(
            f"attempt={attempt}: XcodeBuildMCP proof did not return "
            f"XCODEBUILDMCP_OK. Transcript:\n{transcript}"
        )
    return AppleMcpProof(
        session_id=run.session_id,
        call_id=call_id,
        transcript=transcript,
        output_preview=output_text[:500],
    )


def _validate_apple_workflow_smoke_run(
    run: SessionRun,
    *,
    attempt: int,
    workspace_root: Path,
) -> AppleWorkflowSmokeProof:
    """Validate a representative Apple workflow smoke session."""
    transcript = run.text.strip()
    if not transcript.startswith(EXPECTED_ROUTE):
        raise AppleWorkflowSmokeProofError(
            f"attempt={attempt}: transcript did not start with expected route block.\n"
            f"Expected prefix:\n{EXPECTED_ROUTE}\n\nActual:\n{transcript[:1000]}"
        )

    disallowed_xcode_tools = {
        "XcodeBuildMCP__build_sim",
        "XcodeBuildMCP__build_run_sim",
        "XcodeBuildMCP__launch_app_sim",
        "XcodeBuildMCP__boot_sim",
        "XcodeBuildMCP__open_sim",
        "XcodeBuildMCP__test_sim",
        "XcodeBuildMCP__build_device",
        "XcodeBuildMCP__build_run_device",
    }
    observed_disallowed = [
        name for name in _function_call_names(run.items) if name in disallowed_xcode_tools
    ]
    if observed_disallowed:
        raise AppleWorkflowSmokeProofError(
            f"attempt={attempt}: workflow smoke used disallowed Xcode tools: "
            f"{observed_disallowed!r}"
        )

    docs_call = _single_indexed_call(
        run,
        APPLE_DOCS_CLI_TOOL,
        error_type=AppleWorkflowSmokeProofError,
    )
    xcode_call = _single_indexed_call(
        run,
        APPLE_MCP_XCODEBUILD_TOOL,
        error_type=AppleWorkflowSmokeProofError,
    )
    if docs_call[0] >= xcode_call[0]:
        raise AppleWorkflowSmokeProofError(
            "Apple workflow smoke calls were not in the required order: "
            f"docs={docs_call[0]} xcodebuild={xcode_call[0]}"
        )

    docs_arguments = _function_call_arguments(docs_call[1])
    if docs_arguments.get("url") != APPLE_DOCS_CLI_URL:
        raise AppleWorkflowSmokeProofError(
            f"attempt={attempt}: {APPLE_DOCS_CLI_TOOL} used unexpected url. "
            f"expected={APPLE_DOCS_CLI_URL!r} arguments={docs_arguments!r}"
        )
    xcode_arguments = _function_call_arguments(xcode_call[1])
    expected_workspace = str(workspace_root)
    if xcode_arguments.get("workspaceRoot") != expected_workspace:
        raise AppleWorkflowSmokeProofError(
            f"attempt={attempt}: {APPLE_MCP_XCODEBUILD_TOOL} used unexpected "
            f"workspaceRoot. expected={expected_workspace!r} arguments={xcode_arguments!r}"
        )

    docs_call_id = _require_call_id(
        docs_call[1],
        tool_name=APPLE_DOCS_CLI_TOOL,
        error_type=AppleWorkflowSmokeProofError,
    )
    xcode_call_id = _require_call_id(
        xcode_call[1],
        tool_name=APPLE_MCP_XCODEBUILD_TOOL,
        error_type=AppleWorkflowSmokeProofError,
    )
    docs_output = _function_output_for_call(
        run.items,
        docs_call_id,
        error_type=AppleWorkflowSmokeProofError,
    )
    xcode_output = _function_output_for_call(
        run.items,
        xcode_call_id,
        error_type=AppleWorkflowSmokeProofError,
    )
    docs_missing = [
        sentinel for sentinel in APPLE_MCP_SOSUMI_SENTINELS if sentinel not in docs_output
    ]
    if docs_missing or "error" in docs_output.lower():
        raise AppleWorkflowSmokeProofError(
            f"attempt={attempt}: Apple docs output missed expected sentinels or "
            f"looked erroneous. missing={docs_missing!r} output={docs_output[:1000]}"
        )
    xcode_missing = [
        sentinel for sentinel in APPLE_MCP_XCODEBUILD_SENTINELS if sentinel not in xcode_output
    ]
    if xcode_missing:
        raise AppleWorkflowSmokeProofError(
            f"attempt={attempt}: XcodeBuildMCP output missed expected discovery "
            f"sentinels. missing={xcode_missing!r} output={xcode_output[:1000]}"
        )
    if APPLE_WORKFLOW_SMOKE_SENTINEL not in transcript:
        raise AppleWorkflowSmokeProofError(
            f"attempt={attempt}: workflow smoke did not return "
            f"{APPLE_WORKFLOW_SMOKE_SENTINEL}. Transcript:\n{transcript}"
        )
    return AppleWorkflowSmokeProof(
        session_id=run.session_id,
        apple_docs_call_id=docs_call_id,
        xcodebuild_call_id=xcode_call_id,
        transcript=transcript,
        apple_docs_output_preview=docs_output[:500],
        xcodebuild_output_preview=xcode_output[:500],
    )


def _validate_xcodebuild_mcp_build_run(
    run: SessionRun,
    *,
    project_path: Path,
    simulator_name: str,
    derived_data_path: Path,
) -> XcodeBuildMcpBuildProof:
    """Validate the XcodeBuildMCP build-only proof sequence."""
    transcript = run.text.strip()
    if not transcript.startswith(EXPECTED_ROUTE):
        raise XcodeBuildMcpBuildProofError(
            "transcript did not start with expected route block.\n"
            f"Expected prefix:\n{EXPECTED_ROUTE}\n\nActual:\n{transcript[:1000]}"
        )
    disallowed = {
        "XcodeBuildMCP__build_run_sim",
        "XcodeBuildMCP__launch_app_sim",
        "XcodeBuildMCP__boot_sim",
        "XcodeBuildMCP__open_sim",
        "XcodeBuildMCP__build_run_device",
    }
    observed_disallowed = [name for name in _function_call_names(run.items) if name in disallowed]
    if observed_disallowed:
        raise XcodeBuildMcpBuildProofError(
            f"build proof used disallowed tools: {observed_disallowed!r}"
        )

    show_call = _single_indexed_call(
        run,
        APPLE_MCP_XCODEBUILD_SESSION_SHOW_DEFAULTS_TOOL,
    )
    set_call = _single_indexed_call(
        run,
        APPLE_MCP_XCODEBUILD_SESSION_SET_DEFAULTS_TOOL,
    )
    build_call = _single_indexed_call(run, APPLE_MCP_XCODEBUILD_BUILD_SIM_TOOL)
    if not (show_call[0] < set_call[0] < build_call[0]):
        raise XcodeBuildMcpBuildProofError(
            "XcodeBuildMCP build proof calls were not in the required order: "
            f"show={show_call[0]} set={set_call[0]} build={build_call[0]}"
        )

    set_arguments = _function_call_arguments(set_call[1])
    expected_set_args = {
        "projectPath": str(project_path),
        "scheme": APPLE_MCP_XCODEBUILD_SCHEME,
        "configuration": APPLE_MCP_XCODEBUILD_CONFIGURATION,
        "simulatorName": simulator_name,
        "useLatestOS": True,
        "persist": False,
        "suppressWarnings": True,
        "derivedDataPath": str(derived_data_path),
    }
    mismatches = {
        key: (expected, set_arguments.get(key))
        for key, expected in expected_set_args.items()
        if set_arguments.get(key) != expected
    }
    if mismatches:
        raise XcodeBuildMcpBuildProofError(
            "session_set_defaults used unexpected arguments: "
            f"mismatches={mismatches!r} arguments={set_arguments!r}"
        )
    build_arguments = _function_call_arguments(build_call[1])
    if build_arguments.get("extraArgs") != ["-quiet"]:
        raise XcodeBuildMcpBuildProofError(
            f"build_sim used unexpected arguments: {build_arguments!r}"
        )

    build_call_id = _require_call_id(
        build_call[1],
        tool_name=APPLE_MCP_XCODEBUILD_BUILD_SIM_TOOL,
    )
    build_output = _function_output_for_call(run.items, build_call_id)
    missing = [
        sentinel
        for sentinel in APPLE_MCP_XCODEBUILD_BUILD_SENTINELS
        if sentinel not in build_output
    ]
    if missing:
        raise XcodeBuildMcpBuildProofError(
            f"XcodeBuildMCP build output missed expected sentinels. "
            f"missing={missing!r} output={build_output[:1000]}"
        )
    if "XCODEBUILDMCP_BUILD_OK" not in transcript:
        raise XcodeBuildMcpBuildProofError(
            "XcodeBuildMCP build proof did not return "
            f"XCODEBUILDMCP_BUILD_OK. Transcript:\n{transcript}"
        )
    return XcodeBuildMcpBuildProof(
        session_id=run.session_id,
        show_defaults_call_id=_require_call_id(
            show_call[1],
            tool_name=APPLE_MCP_XCODEBUILD_SESSION_SHOW_DEFAULTS_TOOL,
        ),
        set_defaults_call_id=_require_call_id(
            set_call[1],
            tool_name=APPLE_MCP_XCODEBUILD_SESSION_SET_DEFAULTS_TOOL,
        ),
        build_call_id=build_call_id,
        transcript=transcript,
        output_preview=build_output[:500],
    )


def _validate_xcodebuild_mcp_run_launch(
    run: SessionRun,
    *,
    project_path: Path,
    simulator_name: str,
    derived_data_path: Path,
) -> XcodeBuildMcpRunProof:
    """Validate the XcodeBuildMCP simulator build/install/launch proof sequence."""
    transcript = run.text.strip()
    if not transcript.startswith(EXPECTED_ROUTE):
        raise XcodeBuildMcpRunProofError(
            "transcript did not start with expected route block.\n"
            f"Expected prefix:\n{EXPECTED_ROUTE}\n\nActual:\n{transcript[:1000]}"
        )
    allowed = {
        APPLE_MCP_XCODEBUILD_SESSION_SHOW_DEFAULTS_TOOL,
        APPLE_MCP_XCODEBUILD_SESSION_SET_DEFAULTS_TOOL,
        APPLE_MCP_XCODEBUILD_BUILD_RUN_SIM_TOOL,
    }
    unexpected = [
        name
        for name in _function_call_names(run.items)
        if name.startswith(f"{APPLE_MCP_XCODEBUILD_SERVER}__") and name not in allowed
    ]
    if unexpected:
        raise XcodeBuildMcpRunProofError(
            f"simulator run proof used unexpected XcodeBuildMCP tools: {unexpected!r}"
        )

    show_call = _single_indexed_call(
        run,
        APPLE_MCP_XCODEBUILD_SESSION_SHOW_DEFAULTS_TOOL,
        error_type=XcodeBuildMcpRunProofError,
    )
    set_call = _single_indexed_call(
        run,
        APPLE_MCP_XCODEBUILD_SESSION_SET_DEFAULTS_TOOL,
        error_type=XcodeBuildMcpRunProofError,
    )
    run_call = _single_indexed_call(
        run,
        APPLE_MCP_XCODEBUILD_BUILD_RUN_SIM_TOOL,
        error_type=XcodeBuildMcpRunProofError,
    )
    if not (show_call[0] < set_call[0] < run_call[0]):
        raise XcodeBuildMcpRunProofError(
            "XcodeBuildMCP simulator run proof calls were not in the required "
            f"order: show={show_call[0]} set={set_call[0]} run={run_call[0]}"
        )

    set_arguments = _function_call_arguments(set_call[1])
    expected_set_args = {
        "projectPath": str(project_path),
        "scheme": APPLE_MCP_XCODEBUILD_SCHEME,
        "configuration": APPLE_MCP_XCODEBUILD_CONFIGURATION,
        "simulatorName": simulator_name,
        "useLatestOS": True,
        "persist": False,
        "suppressWarnings": True,
        "derivedDataPath": str(derived_data_path),
    }
    mismatches = {
        key: (expected, set_arguments.get(key))
        for key, expected in expected_set_args.items()
        if set_arguments.get(key) != expected
    }
    if mismatches:
        raise XcodeBuildMcpRunProofError(
            "session_set_defaults used unexpected arguments: "
            f"mismatches={mismatches!r} arguments={set_arguments!r}"
        )
    run_arguments = _function_call_arguments(run_call[1])
    if run_arguments.get("extraArgs") != ["-quiet"]:
        raise XcodeBuildMcpRunProofError(
            f"build_run_sim used unexpected arguments: {run_arguments!r}"
        )

    run_call_id = _require_call_id(
        run_call[1],
        tool_name=APPLE_MCP_XCODEBUILD_BUILD_RUN_SIM_TOOL,
        error_type=XcodeBuildMcpRunProofError,
    )
    run_output = _function_output_for_call(
        run.items,
        run_call_id,
        error_type=XcodeBuildMcpRunProofError,
    )
    missing = [
        sentinel for sentinel in APPLE_MCP_XCODEBUILD_RUN_SENTINELS if sentinel not in run_output
    ]
    if missing:
        raise XcodeBuildMcpRunProofError(
            f"XcodeBuildMCP simulator run output missed expected sentinels. "
            f"missing={missing!r} output={run_output[:1000]}"
        )
    if "XCODEBUILDMCP_RUN_OK" not in transcript:
        raise XcodeBuildMcpRunProofError(
            "XcodeBuildMCP simulator run proof did not return "
            f"XCODEBUILDMCP_RUN_OK. Transcript:\n{transcript}"
        )
    return XcodeBuildMcpRunProof(
        session_id=run.session_id,
        show_defaults_call_id=_require_call_id(
            show_call[1],
            tool_name=APPLE_MCP_XCODEBUILD_SESSION_SHOW_DEFAULTS_TOOL,
            error_type=XcodeBuildMcpRunProofError,
        ),
        set_defaults_call_id=_require_call_id(
            set_call[1],
            tool_name=APPLE_MCP_XCODEBUILD_SESSION_SET_DEFAULTS_TOOL,
            error_type=XcodeBuildMcpRunProofError,
        ),
        run_call_id=run_call_id,
        transcript=transcript,
        output_preview=run_output[:500],
    )


def _missing_tool_call_message(expected_tool: str, run: SessionRun) -> str:
    """Return a compact diagnostic for proof runs that skip a required tool."""
    return (
        f"No persisted {expected_tool} function_call found.\n"
        f"session_id={run.session_id}\n"
        f"observed_function_calls={_function_call_names(run.items)!r}\n"
        f"session_items={_session_item_summary(run.items)}\n"
        f"transcript:\n{run.text.strip()}"
    )


def _function_call_names(items: list[dict[str, Any]]) -> list[str]:
    """Extract persisted function-call names from Omnigent session items."""
    return [
        str(item.get("name"))
        for item in items
        if item.get("type") == "function_call" and item.get("name") is not None
    ]


def _function_call_arguments(call: dict[str, Any]) -> dict[str, Any]:
    """Decode persisted function-call arguments from a session item."""
    raw_arguments = call.get("arguments")
    if isinstance(raw_arguments, dict):
        return raw_arguments
    if isinstance(raw_arguments, str):
        try:
            parsed = json.loads(raw_arguments)
        except json.JSONDecodeError:
            return {}
        if isinstance(parsed, dict):
            return parsed
    return {}


def _single_indexed_call(
    run: SessionRun,
    tool_name: str,
    *,
    error_type: type[Exception] = XcodeBuildMcpBuildProofError,
) -> tuple[int, dict[str, Any]]:
    """Return the single expected function call and its item index."""
    calls = [
        (index, item)
        for index, item in enumerate(run.items)
        if item.get("type") == "function_call" and item.get("name") == tool_name
    ]
    if len(calls) != 1:
        raise error_type(
            f"expected exactly one {tool_name} function_call, found {len(calls)}.\n"
            + _missing_tool_call_message(tool_name, run)
        )
    return calls[0]


def _require_call_id(
    call: dict[str, Any],
    *,
    tool_name: str,
    error_type: type[Exception] = XcodeBuildMcpBuildProofError,
) -> str:
    """Return a function-call id or raise a proof error."""
    call_id = call.get("call_id")
    if not isinstance(call_id, str) or not call_id:
        raise error_type(f"persisted {tool_name} call has invalid call_id: {call!r}")
    return call_id


def _function_output_for_call(
    items: list[dict[str, Any]],
    call_id: str,
    *,
    error_type: type[Exception] = XcodeBuildMcpBuildProofError,
) -> str:
    """Return the persisted function output for a call id."""
    outputs = [
        item
        for item in items
        if item.get("type") == "function_call_output" and item.get("call_id") == call_id
    ]
    if not outputs:
        raise error_type(f"no persisted function_call_output found for call_id={call_id}")
    return str(outputs[-1].get("output", ""))


def _session_item_summary(items: list[dict[str, Any]]) -> str:
    """Summarize persisted session items without dumping full tool payloads."""
    summary: list[str] = []
    for index, item in enumerate(items):
        item_type = item.get("type")
        if item_type == "function_call":
            summary.append(f"{index}:function_call:{item.get('name')}:{item.get('call_id')}")
        elif item_type == "function_call_output":
            output = str(item.get("output", ""))
            summary.append(f"{index}:function_call_output:{item.get('call_id')}:len={len(output)}")
        elif item_type == "message":
            role = item.get("role", "?")
            content = str(item.get("content", ""))
            summary.append(f"{index}:message:{role}:len={len(content)}")
        else:
            summary.append(f"{index}:{item_type}")
    return "[" + ", ".join(summary[:40]) + "]"


def asyncio_run_session_query(
    *,
    agent_dir: Path,
    codex_path: Path,
    prompt: str,
    query_timeout_seconds: float | None = None,
) -> SessionRun:
    """Run the async session query from the synchronous proof script."""
    return asyncio.run(
        _run_session_query(
            agent_dir=agent_dir,
            codex_path=codex_path,
            prompt=prompt,
            query_timeout_seconds=query_timeout_seconds,
        )
    )


@contextlib.contextmanager
def temporary_agent_dir(keep_fixture: bool) -> Iterator[Path]:
    """Yield a temp agent dir, optionally preserving it for debugging."""
    root = Path(tempfile.mkdtemp(prefix="omnigent-stock-codex-proof-"))
    try:
        yield root / "apple-appdev-agent"
    finally:
        if keep_fixture:
            print(f"fixture_kept={root}")
        else:
            shutil.rmtree(root, ignore_errors=True)


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def resolve_xcodebuild_mcp_workspace_root() -> Path:
    """Return the local repo root used for the read-only XcodeBuildMCP proof."""
    repo_root = Path(__file__).resolve().parents[1]
    expected_project = repo_root / APPLE_MCP_XCODEBUILD_PROJECT_RELATIVE_PATH
    if not expected_project.is_dir():
        raise SystemExit(
            "XcodeBuildMCP proof expected an Xcode project at "
            f"{expected_project}, but it was not found"
        )
    return repo_root


def resolve_xcodebuild_mcp_simulator_name() -> str:
    """Pick an available iPhone simulator for the build-only proof."""
    fallback = APPLE_MCP_XCODEBUILD_PREFERRED_SIMULATORS[0]
    try:
        completed = subprocess.run(
            ["xcrun", "simctl", "list", "devices", "available", "-j"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:  # noqa: BLE001 - fallback keeps the proof command deterministic
        return fallback
    if completed.returncode != 0:
        return fallback
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return fallback
    devices = payload.get("devices")
    if not isinstance(devices, dict):
        return fallback
    names: list[str] = []
    for runtime_devices in devices.values():
        if not isinstance(runtime_devices, list):
            continue
        for device in runtime_devices:
            if not isinstance(device, dict):
                continue
            name = device.get("name")
            if (
                isinstance(name, str)
                and name.startswith("iPhone")
                and device.get("isAvailable", True) is not False
            ):
                names.append(name)
    for preferred in APPLE_MCP_XCODEBUILD_PREFERRED_SIMULATORS:
        if preferred in names:
            return preferred
    return names[0] if names else fallback


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prove Omnigent can wrap stock Codex for the Apple routerSelection path."
    )
    parser.add_argument(
        "--proof",
        choices=(
            "graph",
            "router-matrix",
            "tool-plane",
            "mcp-tools",
            "apple-mcp",
            "apple-mcp-sosumi",
            "apple-docs-cli",
            "apple-mcp-xcodebuild",
            "apple-mcp-xcodebuild-build",
            "apple-mcp-xcodebuild-run",
            "apple-xcodebuild-cli-run",
            "apple-xcodebuild-cli-test",
            "apple-xcodebuild-cli-screenshot",
            "apple-xcodebuild-cli-runtime-logs",
            "apple-xcodebuild-cli-snapshot-ui",
            "apple-xcodebuild-cli-type-text",
            "apple-xcodebuild-cli-tap",
            "apple-workflow-smoke",
            "cutover-ready",
            "default-path-cutover",
            "pinned-codex-provision",
            "stock-codex-channel",
            "stock-codex-homebrew-remote-channel",
            "clean-auth-onboarding",
            "stock-codex-compat",
            "stock-codex-compat-live",
            "stock-codex-compat-wrapper-live",
            "stock-codex-compat-wrapper-command-tool",
            "stock-codex-compat-wrapper-adapter-tool",
            "stock-codex-compat-wrapper-adapter-arbitration",
            "stock-codex-compat-wrapper-apple-docs-adapter",
            "stock-codex-compat-wrapper-apple-docs-bridge-adapter",
            "stock-codex-compat-launcher-activation",
            "stock-codex-compat-launcher-doctor",
            "stock-codex-compat-clean-install",
            "stock-codex-compat-bundle-install",
            "stock-codex-compat-pkg-structure",
            "stock-codex-compat-pkg-runtime-live",
            "stock-codex-compat-pkg-user-bootstrap",
            "stock-codex-compat-pkg-clean-provision",
            "stock-codex-compat-pkg-clean-auth-onboarding",
            "stock-codex-compat-pkg-signed-notarized",
            "stock-codex-compat-wrapper-xcodebuild-bridge-adapter",
            "stock-codex-compat-wrapper-relay-tool",
            "app-bundle-entrypoint",
            "launcher-activation",
            "all",
        ),
        default="graph",
        help=(
            "Proof gate to run. Defaults to the existing graph proof. "
            "'router-matrix' proves the manifest router-selection matrix "
            "through the live stock-Codex session/runner path; "
            "'mcp-tools' is accepted as an alias for 'tool-plane'; "
            "'apple-mcp' proves memory, 'apple-mcp-sosumi' proves sosumi, "
            "'apple-docs-cli' proves the Sosumi CLI Apple-docs adapter, "
            "'apple-mcp-xcodebuild' proves read-only XcodeBuildMCP discovery, "
            "'apple-mcp-xcodebuild-build' proves compile-only simulator build, "
            "'apple-mcp-xcodebuild-run' proves simulator build/install/launch "
            "through MCP, and 'apple-xcodebuild-cli-run' proves the simulator "
            "build/install/launch CLI adapter, and 'apple-xcodebuild-cli-test' "
            "proves the simulator test CLI adapter, and "
            "'apple-xcodebuild-cli-screenshot' proves a bounded non-mutating "
            "screenshot through the XcodeBuildMCP CLI adapter, "
            "'apple-xcodebuild-cli-runtime-logs' proves bounded runtime log "
            "observation through the XcodeBuildMCP CLI adapter, and "
            "'apple-xcodebuild-cli-snapshot-ui' proves a bounded semantic UI "
            "snapshot through the XcodeBuildMCP CLI adapter, and "
            "'apple-xcodebuild-cli-type-text' proves a bounded type-text "
            "interaction through the XcodeBuildMCP CLI adapter, and "
            "'apple-xcodebuild-cli-tap' proves a bounded tap interaction "
            "through the XcodeBuildMCP CLI adapter. "
            "'apple-workflow-smoke' runs one routed Apple workflow that uses "
            "Apple docs plus read-only XcodeBuildMCP discovery, and "
            "'cutover-ready' runs the replacement-ready aggregate and "
            "intentionally excludes known-blocked MCP sosumi/run paths. "
            "'default-path-cutover' runs the same replacement-ready aggregate "
            "using ambient default bundle lookup and PATH-resolved stock Codex. "
            "'pinned-codex-provision' proves the stock-Codex provisioner can "
            "install and verify a pinned binary in an isolated cache. "
            "'stock-codex-channel' proves a file-backed channel manifest can "
            "select, stage, verify, and install a pinned stock-Codex payload "
            "with channel provenance in an isolated cache. "
            "'stock-codex-homebrew-remote-channel' proves Homebrew Codex cask "
            "metadata can feed the opt-in OpenAI GitHub release archive "
            "download path in an isolated cache. "
            "'clean-auth-onboarding' proves clean CODEX_HOME needs-auth "
            "classification plus populated auth detection without running "
            "interactive login. "
            "'stock-codex-compat' proves stock Codex can install the Apple "
            "workflow plugin from a disposable local marketplace and read "
            "the Omnigent MCP plus policy-hook bridge from an isolated "
            "CODEX_HOME. "
            "'stock-codex-compat-live' starts from stock Codex exec with "
            "the isolated compatibility profile and requires deterministic "
            "route evidence before the live model sentinel. "
            "'stock-codex-compat-wrapper-live' starts from an Omnigent-owned "
            "wrapper around stock Codex exec, keeps the isolated compatibility "
            "profile, and requires the wrapper to prefix deterministic route "
            "evidence before the live model sentinel. "
            "'stock-codex-compat-wrapper-command-tool' proves that the same "
            "source-owned wrapper preserves a stock Codex command_execution "
            "tool event while still prefixing route evidence before the final "
            "agent message. "
            "'stock-codex-compat-wrapper-adapter-tool' proves that the same "
            "source-owned wrapper can validate an Omnigent-owned adapter "
            "package manifest, expose the declared command through PATH, have "
            "stock Codex execute it via the command tool, and still prefix "
            "route evidence before the final agent message. "
            "'stock-codex-compat-wrapper-adapter-arbitration' proves that "
            "the same wrapper can validate a generated multi-tool adapter "
            "package, have stock Codex select the route adapter, reject the "
            "non-matching adapter, and still prefix route evidence before "
            "the final agent message. "
            "'stock-codex-compat-wrapper-apple-docs-adapter' proves that "
            "the same generated adapter package surface can run the real "
            "Apple docs adapter through stock Codex's command tool. "
            "'stock-codex-compat-wrapper-apple-docs-bridge-adapter' proves "
            "that the real Apple docs adapter can run through a wrapper-owned "
            "file bridge while stock Codex stays in workspace-write. "
            "'stock-codex-compat-launcher-activation' proves that a managed "
            "stock-Codex compatibility launcher can be PATH-selected as "
            "`codex`, resolve back to its manifest-pinned stock binary without "
            "recursion, delegate through uvx to omnigent-stock-codex-wrapper, "
            "and run the generated file-bridge adapter package. "
            "'stock-codex-compat-launcher-doctor' validates the intended "
            "compatibility launcher install target, pinned stock Codex, uvx, "
            "adapter manifest, PATH posture, backup/rollback policy, and "
            "install command without mutating launcher files. "
            "'stock-codex-compat-clean-install' proves the same separate "
            "compatibility command can install, validate, and roll back from "
            "defaults under a clean temporary HOME. "
            "'stock-codex-compat-bundle-install' builds a portable runtime "
            "bundle, extracts it, and proves the same clean-home install and "
            "rollback flow from the extracted artifact runtime. "
            "'stock-codex-compat-pkg-structure' builds an unsigned flat "
            "macOS pkg from the portable runtime bundle and inspects "
            "identifier, version, install root, scripts, signature status, "
            "and required payload layout without installing it. "
            "'stock-codex-compat-pkg-runtime-live' builds the same unsigned "
            "pkg, expands it without installing, and launches a live stock "
            "Codex model turn through uvx --from the expanded runtime. "
            "'stock-codex-compat-pkg-user-bootstrap' stages the same pkg "
            "payload in a temporary install root and proves the installed "
            "runtime can bootstrap, update, doctor, and roll back a clean "
            "user-level compatibility command. "
            "'stock-codex-compat-pkg-signed-notarized' builds the pkg with a "
            "Developer ID Installer identity, submits it through notarytool, "
            "staples it, validates the staple, and checks Gatekeeper; when "
            "credentials are absent it reports a blocked prerequisite state "
            "instead of a harness failure. "
            "'stock-codex-compat-wrapper-xcodebuild-bridge-adapter' proves "
            "that XcodeBuildMCP simulator build/run can execute through the "
            "same wrapper-owned file bridge while stock Codex stays in "
            "workspace-write. "
            "'stock-codex-compat-wrapper-relay-tool' proves that the same "
            "source-owned wrapper preserves a stock Codex MCP call into the "
            "Omnigent tool_relay.json sidecar while still prefixing route "
            "evidence before the final agent message. "
            "'app-bundle-entrypoint' proves a temporary macOS .app bundle can "
            "enter the Omnigent Codex path, pin stock Codex through "
            "OMNIGENT_STOCK_CODEX_PATH, and delegate through uvx without "
            "persistent app mutation. "
            "'launcher-activation' proves a temporary codex shim can shadow "
            "PATH, delegate through uvx to omnigent codex without recursion, "
            "and roll back without mutating launcher defaults."
        ),
    )
    parser.add_argument(
        "--apple-bundle",
        type=Path,
        default=None,
        help="Installed Apple AppDev Workflow bundle root. Defaults to known local cache paths.",
    )
    parser.add_argument(
        "--codex-path",
        type=str,
        default=None,
        help="Stock codex binary path. Defaults to the first codex on PATH.",
    )
    parser.add_argument(
        "--skip-live",
        action="store_true",
        help="Only run static bundle graph checks; do not launch Codex.",
    )
    parser.add_argument(
        "--allow-fork-codex",
        action="store_true",
        help="Allow a .codex-fork binary for diagnostic comparison. Not a stock proof.",
    )
    parser.add_argument(
        "--keep-fixture",
        action="store_true",
        help="Keep the generated temp agent directory for debugging.",
    )
    parser.add_argument(
        "--live-proof-timeout",
        type=float,
        default=DEFAULT_LIVE_PROOF_TIMEOUT_SECONDS,
        help=(
            "Wall-clock seconds allowed for each live proof step. "
            "Use 0 or a negative value to disable. Defaults to "
            f"{DEFAULT_LIVE_PROOF_TIMEOUT_SECONDS:.0f}."
        ),
    )
    parser.add_argument(
        "--xcodebuildmcp-axe-path",
        type=Path,
        default=None,
        help=(
            "Optional patched AXe binary for XcodeBuildMCP UI automation. "
            f"When set, it is exposed only as {OMNIGENT_XCODEBUILDMCP_AXE_PATH_ENV} "
            "during the selected live proof."
        ),
    )
    parser.add_argument(
        "--pkg-sign-identity",
        default=os.environ.get(PKG_SIGN_IDENTITY_ENV),
        help=(
            "Developer ID Installer identity for signed pkg validation. "
            f"Defaults to {PKG_SIGN_IDENTITY_ENV}."
        ),
    )
    parser.add_argument(
        "--pkg-sign-keychain",
        type=Path,
        default=(
            Path(os.environ[PKG_SIGN_KEYCHAIN_ENV])
            if os.environ.get(PKG_SIGN_KEYCHAIN_ENV)
            else None
        ),
        help=(
            "Optional keychain path for the pkg signing identity. Defaults to "
            f"{PKG_SIGN_KEYCHAIN_ENV}."
        ),
    )
    parser.add_argument(
        "--notarytool-profile",
        default=os.environ.get(NOTARYTOOL_PROFILE_ENV),
        help=(
            "notarytool keychain profile for pkg notarization. Defaults to "
            f"{NOTARYTOOL_PROFILE_ENV}."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    requested_proof = "tool-plane" if args.proof == "mcp-tools" else args.proof
    if requested_proof == "pinned-codex-provision":
        if args.apple_bundle is not None:
            raise SystemExit("pinned-codex-provision does not use --apple-bundle; omit it.")
        if args.allow_fork_codex:
            raise SystemExit("pinned-codex-provision cannot allow a Codex-fork binary.")
        codex_path = resolve_codex_path(args.codex_path)
        assert_stock_codex_path(codex_path, allow_fork_codex=False)
        print_pinned_codex_provision_proof(run_pinned_codex_provision_proof(codex_path))
        return 0

    if requested_proof == "stock-codex-channel":
        if args.apple_bundle is not None:
            raise SystemExit("stock-codex-channel does not use --apple-bundle; omit it.")
        if args.allow_fork_codex:
            raise SystemExit("stock-codex-channel cannot allow a Codex-fork binary.")
        codex_path = resolve_codex_path(args.codex_path)
        assert_stock_codex_path(codex_path, allow_fork_codex=False)
        print_stock_codex_channel_proof(run_stock_codex_channel_proof(codex_path))
        return 0

    if requested_proof == "stock-codex-homebrew-remote-channel":
        if args.apple_bundle is not None:
            raise SystemExit(
                "stock-codex-homebrew-remote-channel does not use --apple-bundle; omit it."
            )
        if args.codex_path is not None:
            raise SystemExit(
                "stock-codex-homebrew-remote-channel reads Homebrew cask metadata; "
                "omit --codex-path."
            )
        if args.allow_fork_codex:
            raise SystemExit(
                "stock-codex-homebrew-remote-channel cannot allow a Codex-fork binary."
            )
        print_stock_codex_homebrew_remote_channel_proof(
            run_stock_codex_homebrew_remote_channel_proof()
        )
        return 0

    if requested_proof == "clean-auth-onboarding":
        if args.apple_bundle is not None:
            raise SystemExit("clean-auth-onboarding does not use --apple-bundle; omit it.")
        if args.allow_fork_codex:
            raise SystemExit("clean-auth-onboarding cannot allow a Codex-fork binary.")
        codex_path = resolve_codex_path(args.codex_path)
        assert_stock_codex_path(codex_path, allow_fork_codex=False)
        print_clean_auth_onboarding_proof(run_clean_auth_onboarding_proof(codex_path))
        return 0

    if requested_proof == "stock-codex-compat":
        if args.allow_fork_codex:
            raise SystemExit("stock-codex-compat cannot allow a Codex-fork binary.")
        source_bundle = (
            args.apple_bundle.expanduser() if args.apple_bundle else resolve_default_bundle()
        )
        if not source_bundle.is_dir():
            raise SystemExit(f"Apple bundle not found: {source_bundle}")
        codex_path = resolve_codex_path(args.codex_path)
        assert_stock_codex_path(codex_path, allow_fork_codex=False)
        print_stock_codex_compat_proof(
            run_stock_codex_compat_proof(source_bundle, codex_path)
        )
        return 0

    if requested_proof == "stock-codex-compat-live":
        if args.allow_fork_codex:
            raise SystemExit("stock-codex-compat-live cannot allow a Codex-fork binary.")
        source_bundle = (
            args.apple_bundle.expanduser() if args.apple_bundle else resolve_default_bundle()
        )
        if not source_bundle.is_dir():
            raise SystemExit(f"Apple bundle not found: {source_bundle}")
        codex_path = resolve_codex_path(args.codex_path)
        assert_stock_codex_path(codex_path, allow_fork_codex=False)
        print_stock_codex_compat_live_proof(
            run_stock_codex_compat_live_proof(
                source_bundle,
                codex_path,
                workspace_root=Path.cwd(),
                timeout_seconds=args.live_proof_timeout,
            )
        )
        return 0

    if requested_proof == "stock-codex-compat-wrapper-live":
        if args.allow_fork_codex:
            raise SystemExit(
                "stock-codex-compat-wrapper-live cannot allow a Codex-fork binary."
            )
        source_bundle = (
            args.apple_bundle.expanduser() if args.apple_bundle else resolve_default_bundle()
        )
        if not source_bundle.is_dir():
            raise SystemExit(f"Apple bundle not found: {source_bundle}")
        codex_path = resolve_codex_path(args.codex_path)
        assert_stock_codex_path(codex_path, allow_fork_codex=False)
        print_stock_codex_compat_wrapper_live_proof(
            run_stock_codex_compat_wrapper_live_proof(
                source_bundle,
                codex_path,
                workspace_root=Path.cwd(),
                timeout_seconds=args.live_proof_timeout,
            )
        )
        return 0

    if requested_proof == "stock-codex-compat-wrapper-command-tool":
        if args.allow_fork_codex:
            raise SystemExit(
                "stock-codex-compat-wrapper-command-tool cannot allow a Codex-fork binary."
            )
        source_bundle = (
            args.apple_bundle.expanduser() if args.apple_bundle else resolve_default_bundle()
        )
        if not source_bundle.is_dir():
            raise SystemExit(f"Apple bundle not found: {source_bundle}")
        codex_path = resolve_codex_path(args.codex_path)
        assert_stock_codex_path(codex_path, allow_fork_codex=False)
        print_stock_codex_compat_wrapper_command_tool_proof(
            run_stock_codex_compat_wrapper_command_tool_proof(
                source_bundle,
                codex_path,
                timeout_seconds=args.live_proof_timeout,
            )
        )
        return 0

    if requested_proof == "stock-codex-compat-wrapper-adapter-tool":
        if args.allow_fork_codex:
            raise SystemExit(
                "stock-codex-compat-wrapper-adapter-tool cannot allow a Codex-fork binary."
            )
        source_bundle = (
            args.apple_bundle.expanduser() if args.apple_bundle else resolve_default_bundle()
        )
        if not source_bundle.is_dir():
            raise SystemExit(f"Apple bundle not found: {source_bundle}")
        codex_path = resolve_codex_path(args.codex_path)
        assert_stock_codex_path(codex_path, allow_fork_codex=False)
        print_stock_codex_compat_wrapper_adapter_tool_proof(
            run_stock_codex_compat_wrapper_adapter_tool_proof(
                source_bundle,
                codex_path,
                timeout_seconds=args.live_proof_timeout,
            )
        )
        return 0

    if requested_proof == "stock-codex-compat-wrapper-adapter-arbitration":
        if args.allow_fork_codex:
            raise SystemExit(
                "stock-codex-compat-wrapper-adapter-arbitration cannot allow a "
                "Codex-fork binary."
            )
        source_bundle = (
            args.apple_bundle.expanduser() if args.apple_bundle else resolve_default_bundle()
        )
        if not source_bundle.is_dir():
            raise SystemExit(f"Apple bundle not found: {source_bundle}")
        codex_path = resolve_codex_path(args.codex_path)
        assert_stock_codex_path(codex_path, allow_fork_codex=False)
        print_stock_codex_compat_wrapper_adapter_arbitration_proof(
            run_stock_codex_compat_wrapper_adapter_arbitration_proof(
                source_bundle,
                codex_path,
                timeout_seconds=args.live_proof_timeout,
            )
        )
        return 0

    if requested_proof == "stock-codex-compat-wrapper-apple-docs-adapter":
        if args.allow_fork_codex:
            raise SystemExit(
                "stock-codex-compat-wrapper-apple-docs-adapter cannot allow a "
                "Codex-fork binary."
            )
        source_bundle = (
            args.apple_bundle.expanduser() if args.apple_bundle else resolve_default_bundle()
        )
        if not source_bundle.is_dir():
            raise SystemExit(f"Apple bundle not found: {source_bundle}")
        codex_path = resolve_codex_path(args.codex_path)
        assert_stock_codex_path(codex_path, allow_fork_codex=False)
        print_stock_codex_compat_wrapper_apple_docs_adapter_proof(
            run_stock_codex_compat_wrapper_apple_docs_adapter_proof(
                source_bundle,
                codex_path,
                timeout_seconds=args.live_proof_timeout,
            )
        )
        return 0

    if requested_proof == "stock-codex-compat-wrapper-apple-docs-bridge-adapter":
        if args.allow_fork_codex:
            raise SystemExit(
                "stock-codex-compat-wrapper-apple-docs-bridge-adapter cannot "
                "allow a Codex-fork binary."
            )
        source_bundle = (
            args.apple_bundle.expanduser() if args.apple_bundle else resolve_default_bundle()
        )
        if not source_bundle.is_dir():
            raise SystemExit(f"Apple bundle not found: {source_bundle}")
        codex_path = resolve_codex_path(args.codex_path)
        assert_stock_codex_path(codex_path, allow_fork_codex=False)
        print_stock_codex_compat_wrapper_apple_docs_bridge_adapter_proof(
            run_stock_codex_compat_wrapper_apple_docs_bridge_adapter_proof(
                source_bundle,
                codex_path,
                timeout_seconds=args.live_proof_timeout,
            )
        )
        return 0

    if requested_proof == "stock-codex-compat-launcher-activation":
        if args.apple_bundle is not None:
            raise SystemExit(
                "stock-codex-compat-launcher-activation does not use --apple-bundle; "
                "omit it."
            )
        if args.codex_path is not None:
            raise SystemExit(
                "stock-codex-compat-launcher-activation creates an isolated fake "
                "stock Codex binary; omit --codex-path."
            )
        if args.allow_fork_codex:
            raise SystemExit(
                "stock-codex-compat-launcher-activation cannot allow a Codex-fork "
                "binary."
            )
        print_stock_codex_compat_launcher_activation_proof(
            run_stock_codex_compat_launcher_activation_proof(
                timeout_seconds=args.live_proof_timeout,
            )
        )
        return 0

    if requested_proof == "stock-codex-compat-launcher-doctor":
        if args.apple_bundle is not None:
            raise SystemExit(
                "stock-codex-compat-launcher-doctor does not use --apple-bundle; omit it."
            )
        if args.allow_fork_codex:
            raise SystemExit(
                "stock-codex-compat-launcher-doctor cannot allow a Codex-fork binary."
            )
        codex_path = resolve_codex_path(args.codex_path)
        assert_stock_codex_path(codex_path, allow_fork_codex=False)
        print_stock_codex_compat_launcher_doctor_proof(
            run_stock_codex_compat_launcher_doctor_proof(codex_path)
        )
        return 0

    if requested_proof == "stock-codex-compat-clean-install":
        if args.apple_bundle is not None:
            raise SystemExit(
                "stock-codex-compat-clean-install does not use --apple-bundle; omit it."
            )
        if args.allow_fork_codex:
            raise SystemExit(
                "stock-codex-compat-clean-install cannot allow a Codex-fork binary."
            )
        codex_path = resolve_codex_path(args.codex_path)
        assert_stock_codex_path(codex_path, allow_fork_codex=False)
        print_stock_codex_compat_clean_install_proof(
            run_stock_codex_compat_clean_install_proof(codex_path)
        )
        return 0

    if requested_proof == "stock-codex-compat-bundle-install":
        if args.apple_bundle is not None:
            raise SystemExit(
                "stock-codex-compat-bundle-install does not use --apple-bundle; omit it."
            )
        if args.allow_fork_codex:
            raise SystemExit(
                "stock-codex-compat-bundle-install cannot allow a Codex-fork binary."
            )
        codex_path = resolve_codex_path(args.codex_path)
        assert_stock_codex_path(codex_path, allow_fork_codex=False)
        print_stock_codex_compat_bundle_install_proof(
            run_stock_codex_compat_bundle_install_proof(codex_path)
        )
        return 0

    if requested_proof == "stock-codex-compat-pkg-structure":
        if args.apple_bundle is not None:
            raise SystemExit(
                "stock-codex-compat-pkg-structure does not use --apple-bundle; omit it."
            )
        if args.codex_path is not None:
            raise SystemExit(
                "stock-codex-compat-pkg-structure does not use --codex-path; omit it."
            )
        if args.allow_fork_codex:
            raise SystemExit(
                "stock-codex-compat-pkg-structure cannot allow a Codex-fork binary."
            )
        print_stock_codex_compat_pkg_structure_proof(
            run_stock_codex_compat_pkg_structure_proof()
        )
        return 0

    if requested_proof == "stock-codex-compat-pkg-runtime-live":
        if args.allow_fork_codex:
            raise SystemExit(
                "stock-codex-compat-pkg-runtime-live cannot allow a Codex-fork binary."
            )
        source_bundle = (
            args.apple_bundle.expanduser() if args.apple_bundle else resolve_default_bundle()
        )
        if not source_bundle.is_dir():
            raise SystemExit(f"Apple bundle not found: {source_bundle}")
        codex_path = resolve_codex_path(args.codex_path)
        assert_stock_codex_path(codex_path, allow_fork_codex=False)
        print_stock_codex_compat_pkg_runtime_live_proof(
            run_stock_codex_compat_pkg_runtime_live_proof(
                source_bundle,
                codex_path,
                workspace_root=Path.cwd(),
                timeout_seconds=args.live_proof_timeout,
            )
        )
        return 0

    if requested_proof == "stock-codex-compat-pkg-user-bootstrap":
        if args.apple_bundle is not None:
            raise SystemExit(
                "stock-codex-compat-pkg-user-bootstrap does not use --apple-bundle; "
                "omit it."
            )
        if args.allow_fork_codex:
            raise SystemExit(
                "stock-codex-compat-pkg-user-bootstrap cannot allow a Codex-fork binary."
            )
        codex_path = resolve_codex_path(args.codex_path)
        assert_stock_codex_path(codex_path, allow_fork_codex=False)
        print_stock_codex_compat_pkg_user_bootstrap_proof(
            run_stock_codex_compat_pkg_user_bootstrap_proof(codex_path)
        )
        return 0

    if requested_proof == "stock-codex-compat-pkg-clean-provision":
        if args.apple_bundle is not None:
            raise SystemExit(
                "stock-codex-compat-pkg-clean-provision does not use --apple-bundle; "
                "omit it."
            )
        if args.allow_fork_codex:
            raise SystemExit(
                "stock-codex-compat-pkg-clean-provision cannot allow a Codex-fork binary."
            )
        codex_path = resolve_codex_path(args.codex_path)
        assert_stock_codex_path(codex_path, allow_fork_codex=False)
        print_stock_codex_compat_pkg_clean_provision_proof(
            run_stock_codex_compat_pkg_clean_provision_proof(codex_path)
        )
        return 0

    if requested_proof == "stock-codex-compat-pkg-clean-auth-onboarding":
        if args.apple_bundle is not None:
            raise SystemExit(
                "stock-codex-compat-pkg-clean-auth-onboarding does not use "
                "--apple-bundle; omit it."
            )
        if args.allow_fork_codex:
            raise SystemExit(
                "stock-codex-compat-pkg-clean-auth-onboarding cannot allow a "
                "Codex-fork binary."
            )
        codex_path = resolve_codex_path(args.codex_path)
        assert_stock_codex_path(codex_path, allow_fork_codex=False)
        print_stock_codex_compat_pkg_clean_auth_proof(
            run_stock_codex_compat_pkg_clean_auth_proof(codex_path)
        )
        return 0

    if requested_proof == "stock-codex-compat-pkg-signed-notarized":
        if args.apple_bundle is not None:
            raise SystemExit(
                "stock-codex-compat-pkg-signed-notarized does not use "
                "--apple-bundle; omit it."
            )
        if args.codex_path is not None:
            raise SystemExit(
                "stock-codex-compat-pkg-signed-notarized does not use "
                "--codex-path; omit it."
            )
        if args.allow_fork_codex:
            raise SystemExit(
                "stock-codex-compat-pkg-signed-notarized cannot allow a "
                "Codex-fork binary."
            )
        print_stock_codex_compat_pkg_signed_notarized_proof(
            run_stock_codex_compat_pkg_signed_notarized_proof(
                sign_identity=args.pkg_sign_identity,
                signing_keychain=args.pkg_sign_keychain,
                notarytool_profile=args.notarytool_profile,
            )
        )
        return 0

    if requested_proof == "stock-codex-compat-wrapper-xcodebuild-bridge-adapter":
        if args.allow_fork_codex:
            raise SystemExit(
                "stock-codex-compat-wrapper-xcodebuild-bridge-adapter cannot "
                "allow a Codex-fork binary."
            )
        source_bundle = (
            args.apple_bundle.expanduser() if args.apple_bundle else resolve_default_bundle()
        )
        if not source_bundle.is_dir():
            raise SystemExit(f"Apple bundle not found: {source_bundle}")
        codex_path = resolve_codex_path(args.codex_path)
        assert_stock_codex_path(codex_path, allow_fork_codex=False)
        print_stock_codex_compat_wrapper_xcodebuild_bridge_adapter_proof(
            run_stock_codex_compat_wrapper_xcodebuild_bridge_adapter_proof(
                source_bundle,
                codex_path,
                timeout_seconds=args.live_proof_timeout,
            )
        )
        return 0

    if requested_proof == "stock-codex-compat-wrapper-relay-tool":
        if args.allow_fork_codex:
            raise SystemExit(
                "stock-codex-compat-wrapper-relay-tool cannot allow a Codex-fork binary."
            )
        source_bundle = (
            args.apple_bundle.expanduser() if args.apple_bundle else resolve_default_bundle()
        )
        if not source_bundle.is_dir():
            raise SystemExit(f"Apple bundle not found: {source_bundle}")
        codex_path = resolve_codex_path(args.codex_path)
        assert_stock_codex_path(codex_path, allow_fork_codex=False)
        print_stock_codex_compat_wrapper_relay_tool_proof(
            run_stock_codex_compat_wrapper_relay_tool_proof(
                source_bundle,
                codex_path,
                timeout_seconds=args.live_proof_timeout,
            )
        )
        return 0

    if requested_proof == "app-bundle-entrypoint":
        if args.apple_bundle is not None:
            raise SystemExit("app-bundle-entrypoint does not use --apple-bundle; omit it.")
        if args.allow_fork_codex:
            raise SystemExit("app-bundle-entrypoint cannot allow a Codex-fork binary.")
        codex_path = resolve_codex_path(args.codex_path)
        assert_stock_codex_path(codex_path, allow_fork_codex=False)
        print_app_bundle_entrypoint_proof(run_app_bundle_entrypoint_proof(codex_path))
        return 0

    if requested_proof == "launcher-activation":
        if args.apple_bundle is not None:
            raise SystemExit("launcher-activation does not use --apple-bundle; omit it.")
        if args.codex_path is not None:
            raise SystemExit(
                "launcher-activation must prove PATH-resolved stock Codex; omit --codex-path."
            )
        if args.allow_fork_codex:
            raise SystemExit("launcher-activation cannot allow a Codex-fork binary.")
        print_launcher_activation_proof(run_launcher_activation_proof())
        return 0

    default_path_cutover = requested_proof == "default-path-cutover"
    if default_path_cutover:
        if args.apple_bundle is not None:
            raise SystemExit(
                "default-path-cutover must use default Apple bundle lookup; omit --apple-bundle."
            )
        if args.codex_path is not None:
            raise SystemExit(
                "default-path-cutover must use PATH-resolved stock Codex; omit --codex-path."
            )
        if args.allow_fork_codex:
            raise SystemExit("default-path-cutover cannot allow a Codex-fork binary.")
    proof = "cutover-ready" if default_path_cutover else requested_proof
    source_bundle = (
        args.apple_bundle.expanduser() if args.apple_bundle else resolve_default_bundle()
    )
    if not source_bundle.is_dir():
        raise SystemExit(f"Apple bundle not found: {source_bundle}")

    codex_path: Path | None = None
    if not args.skip_live or args.codex_path or default_path_cutover:
        codex_path = resolve_codex_path(args.codex_path)
        assert_stock_codex_path(codex_path, allow_fork_codex=args.allow_fork_codex)

    xcodebuildmcp_axe_path = (
        args.xcodebuildmcp_axe_path.expanduser()
        if args.xcodebuildmcp_axe_path is not None
        else None
    )
    if xcodebuildmcp_axe_path is not None and not xcodebuildmcp_axe_path.is_file():
        raise SystemExit(f"AXe binary not found: {xcodebuildmcp_axe_path}")

    with temporary_agent_dir(args.keep_fixture) as agent_dir:
        copy_bundle(source_bundle, agent_dir)
        aggregate_proof = proof in {"all", "cutover-ready"}
        needs_memory_mcp = proof in {"apple-mcp", "all", "cutover-ready"}
        needs_sosumi_mcp = proof in {"apple-mcp-sosumi", "all"}
        needs_apple_docs_cli = proof in {
            "apple-docs-cli",
            "apple-workflow-smoke",
            "cutover-ready",
        }
        needs_xcodebuild_discovery_mcp = proof in {
            "apple-mcp-xcodebuild",
            "apple-workflow-smoke",
            "all",
            "cutover-ready",
        }
        runs_xcodebuild_discovery_mcp = proof in {
            "apple-mcp-xcodebuild",
            "all",
            "cutover-ready",
        }
        needs_xcodebuild_build_mcp = proof == "apple-mcp-xcodebuild-build"
        needs_xcodebuild_run_mcp = proof == "apple-mcp-xcodebuild-run"
        needs_xcodebuild_cli_run = proof in {"apple-xcodebuild-cli-run", "cutover-ready"}
        needs_xcodebuild_cli_test = proof == "apple-xcodebuild-cli-test"
        needs_xcodebuild_cli_screenshot = proof == "apple-xcodebuild-cli-screenshot"
        needs_xcodebuild_cli_runtime_logs = proof == "apple-xcodebuild-cli-runtime-logs"
        needs_xcodebuild_cli_snapshot_ui = proof == "apple-xcodebuild-cli-snapshot-ui"
        needs_xcodebuild_cli_type_text = proof == "apple-xcodebuild-cli-type-text"
        needs_xcodebuild_cli_tap = proof == "apple-xcodebuild-cli-tap"
        runs_apple_docs_cli = proof in {"apple-docs-cli", "cutover-ready"}
        needs_xcodebuild_cli = (
            needs_xcodebuild_cli_run
            or needs_xcodebuild_cli_test
            or needs_xcodebuild_cli_screenshot
            or needs_xcodebuild_cli_runtime_logs
            or needs_xcodebuild_cli_snapshot_ui
            or needs_xcodebuild_cli_type_text
            or needs_xcodebuild_cli_tap
        )
        needs_xcodebuild_mcp = (
            needs_xcodebuild_discovery_mcp
            or needs_xcodebuild_build_mcp
            or needs_xcodebuild_run_mcp
        )
        needs_apple_mcp = needs_memory_mcp or needs_sosumi_mcp or needs_xcodebuild_mcp
        needs_apple_mcp_manifest = needs_apple_mcp or needs_apple_docs_cli or needs_xcodebuild_cli
        mcp_manifest = None
        apple_docs_cli_decision = None
        apple_docs_cli_tool_path = None
        xcodebuild_cli_decision = None
        xcodebuild_cli_tool_path = None
        memory_file = None
        xcodebuild_workspace_root = (
            resolve_xcodebuild_mcp_workspace_root()
            if needs_xcodebuild_mcp or needs_xcodebuild_cli
            else None
        )
        xcodebuild_simulator_name = (
            resolve_xcodebuild_mcp_simulator_name()
            if needs_xcodebuild_build_mcp or needs_xcodebuild_run_mcp or needs_xcodebuild_cli
            else None
        )
        xcodebuild_derived_data_path = (
            agent_dir.parent
            / (
                "xcodebuild-cli-test-deriveddata"
                if needs_xcodebuild_cli_test
                else "xcodebuild-cli-snapshot-ui-deriveddata"
                if needs_xcodebuild_cli_snapshot_ui
                else "xcodebuild-cli-type-text-deriveddata"
                if needs_xcodebuild_cli_type_text
                else "xcodebuild-cli-tap-deriveddata"
                if needs_xcodebuild_cli_tap
                else "xcodebuild-cli-runtime-logs-deriveddata"
                if needs_xcodebuild_cli_runtime_logs
                else "xcodebuild-cli-screenshot-deriveddata"
                if needs_xcodebuild_cli_screenshot
                else "xcodebuild-cli-run-deriveddata"
                if needs_xcodebuild_cli_run
                else "xcodebuild-run-deriveddata"
                if needs_xcodebuild_run_mcp
                else "xcodebuild-deriveddata"
            )
            if needs_xcodebuild_build_mcp or needs_xcodebuild_run_mcp or needs_xcodebuild_cli
            else None
        )
        apple_mcp_servers: dict[str, dict[str, Any]] = {}
        mcp_env_overrides: dict[str, dict[str, str]] = {}
        if proof in {
            "tool-plane",
            "apple-mcp",
            "apple-mcp-sosumi",
            "apple-docs-cli",
            "apple-mcp-xcodebuild",
            "apple-mcp-xcodebuild-build",
            "apple-mcp-xcodebuild-run",
            "apple-xcodebuild-cli-run",
            "apple-xcodebuild-cli-test",
            "apple-xcodebuild-cli-screenshot",
            "apple-xcodebuild-cli-runtime-logs",
            "apple-xcodebuild-cli-snapshot-ui",
            "apple-xcodebuild-cli-type-text",
            "apple-xcodebuild-cli-tap",
            "apple-workflow-smoke",
            "cutover-ready",
            "default-path-cutover",
            "all",
        }:
            mcp_manifest = prove_apple_mcp_manifest(agent_dir)
        if needs_apple_mcp_manifest:
            assert mcp_manifest is not None
        if needs_apple_mcp:
            if needs_memory_mcp:
                memory_file = agent_dir / "memory-proof.json"
                memory_file.write_text("{}", encoding="utf-8")
                apple_mcp_servers[APPLE_MCP_MEMORY_SERVER] = mcp_config_from_manifest(
                    mcp_manifest,
                    APPLE_MCP_MEMORY_SERVER,
                )
                mcp_env_overrides[APPLE_MCP_MEMORY_SERVER] = {"MEMORY_FILE_PATH": str(memory_file)}
            if needs_sosumi_mcp:
                apple_mcp_servers[APPLE_MCP_SOSUMI_SERVER] = mcp_config_from_manifest(
                    mcp_manifest,
                    APPLE_MCP_SOSUMI_SERVER,
                )
            if needs_xcodebuild_mcp:
                apple_mcp_servers[APPLE_MCP_XCODEBUILD_SERVER] = mcp_config_from_manifest(
                    mcp_manifest,
                    APPLE_MCP_XCODEBUILD_SERVER,
                )
        if needs_apple_docs_cli:
            assert mcp_manifest is not None
            apple_docs_cli_decision = APPLE_DOCS_CLI_POLICY.decide_for_mcp_servers(mcp_manifest)
            if not apple_docs_cli_decision.install:
                raise SystemExit(apple_docs_cli_decision.reason)
            apple_docs_cli_tool_path = write_fetch_apple_docs_cli_tool(
                agent_dir,
                policy=APPLE_DOCS_CLI_POLICY,
            )
        if needs_xcodebuild_cli:
            assert mcp_manifest is not None
            xcodebuild_cli_decision = XCODEBUILD_CLI_POLICY.decide_for_mcp_servers(mcp_manifest)
            if not xcodebuild_cli_decision.install:
                raise SystemExit(xcodebuild_cli_decision.reason)
            xcodebuild_cli_tool_path = (
                write_xcodebuildmcp_simulator_test_tool(
                    agent_dir,
                    policy=XCODEBUILD_CLI_POLICY,
                )
                if needs_xcodebuild_cli_test
                else write_xcodebuildmcp_simulator_screenshot_tool(
                    agent_dir,
                    policy=XCODEBUILD_CLI_POLICY,
                )
                if needs_xcodebuild_cli_screenshot
                else write_xcodebuildmcp_simulator_snapshot_ui_tool(
                    agent_dir,
                    policy=XCODEBUILD_CLI_POLICY,
                )
                if needs_xcodebuild_cli_snapshot_ui
                else write_xcodebuildmcp_simulator_type_text_tool(
                    agent_dir,
                    policy=XCODEBUILD_CLI_POLICY,
                )
                if needs_xcodebuild_cli_type_text
                else write_xcodebuildmcp_simulator_tap_tool(
                    agent_dir,
                    policy=XCODEBUILD_CLI_POLICY,
                )
                if needs_xcodebuild_cli_tap
                else write_xcodebuildmcp_simulator_runtime_logs_tool(
                    agent_dir,
                    policy=XCODEBUILD_CLI_POLICY,
                )
                if needs_xcodebuild_cli_runtime_logs
                else write_xcodebuildmcp_simulator_build_run_tool(
                    agent_dir,
                    policy=XCODEBUILD_CLI_POLICY,
                )
            )
        if aggregate_proof and not args.skip_live:
            # Keep each live proof surface minimal. With every MCP exposed at once,
            # stock Codex can choose to narrate instead of calling the one proof
            # tool, which tests model selection noise rather than the adapter path.
            write_agent_config(agent_dir)
        elif needs_apple_mcp:
            write_agent_config(
                agent_dir,
                apple_mcp_servers=apple_mcp_servers,
                mcp_env_overrides=mcp_env_overrides,
            )
        else:
            write_agent_config(agent_dir)

        graph = prove_selected_skill_graph(agent_dir)
        print(f"bundle_source={source_bundle}")
        print(f"generated_agent={agent_dir}")
        if codex_path is None:
            print("codex_path=not_checked")
            print("codex_version=not_checked")
        else:
            print(f"codex_path={codex_path}")
            print(f"codex_version={codex_version(codex_path)}")
        if default_path_cutover:
            assert codex_path is not None
            print_default_path_cutover_fallback_steps(
                source_bundle=source_bundle,
                bundle_selector=default_bundle_selector(source_bundle),
                codex_path=codex_path,
            )
        print(f"static_relative_files={len(graph.relative_paths)}")
        print(f"static_skill_refs={len(graph.skill_refs)}")
        print("ASSERTION: selected Apple skill graph resolves inside the Omnigent bundle")

        if proof in {"tool-plane", "all", "cutover-ready"}:
            assert mcp_manifest is not None
            print(f"static_apple_mcp_servers={','.join(sorted(mcp_manifest))}")
            print("ASSERTION: Apple plugin MCP manifest is bundled and well-formed")
        if needs_memory_mcp:
            assert mcp_manifest is not None
            print(f"static_apple_mcp_servers={','.join(sorted(mcp_manifest))}")
            print(f"converted_apple_mcp_server={APPLE_MCP_MEMORY_SERVER}")
            print(f"converted_apple_mcp_memory_file={memory_file}")
            print("ASSERTION: Apple memory MCP config converted into Omnigent tools config")
        if needs_sosumi_mcp:
            assert mcp_manifest is not None
            print(f"static_apple_mcp_servers={','.join(sorted(mcp_manifest))}")
            print(f"converted_apple_mcp_server={APPLE_MCP_SOSUMI_SERVER}")
            print(f"converted_apple_mcp_sosumi_path={APPLE_MCP_SOSUMI_DOC_PATH}")
            print("ASSERTION: Apple sosumi MCP config converted into Omnigent tools config")
        if needs_apple_docs_cli:
            assert mcp_manifest is not None
            assert apple_docs_cli_decision is not None
            assert apple_docs_cli_tool_path is not None
            print(f"static_apple_mcp_servers={','.join(sorted(mcp_manifest))}")
            print(f"apple_docs_cli_policy_reason={apple_docs_cli_decision.reason}")
            print(f"apple_docs_cli_tool={APPLE_DOCS_CLI_TOOL}")
            print(f"apple_docs_cli_url={APPLE_DOCS_CLI_URL}")
            print(f"apple_docs_cli_tool_path={apple_docs_cli_tool_path}")
            print(
                "ASSERTION: Apple docs CLI adapter policy installed the generated "
                "tool without mutating the Apple MCP manifest"
            )
        if needs_xcodebuild_cli:
            assert mcp_manifest is not None
            assert xcodebuild_cli_decision is not None
            assert xcodebuild_cli_tool_path is not None
            assert xcodebuild_workspace_root is not None
            assert xcodebuild_simulator_name is not None
            assert xcodebuild_derived_data_path is not None
            xcodebuild_cli_tool = (
                XCODEBUILD_CLI_TEST_TOOL
                if needs_xcodebuild_cli_test
                else XCODEBUILD_CLI_SCREENSHOT_TOOL
                if needs_xcodebuild_cli_screenshot
                else XCODEBUILD_CLI_SNAPSHOT_UI_TOOL
                if needs_xcodebuild_cli_snapshot_ui
                else XCODEBUILD_CLI_TYPE_TEXT_TOOL
                if needs_xcodebuild_cli_type_text
                else XCODEBUILD_CLI_TAP_TOOL
                if needs_xcodebuild_cli_tap
                else XCODEBUILD_CLI_RUNTIME_LOGS_TOOL
                if needs_xcodebuild_cli_runtime_logs
                else XCODEBUILD_CLI_TOOL
            )
            xcodebuild_cli_command = (
                XCODEBUILDMCP_CLI_TEST_COMMAND
                if needs_xcodebuild_cli_test
                else XCODEBUILDMCP_CLI_SCREENSHOT_COMMAND
                if needs_xcodebuild_cli_screenshot
                else XCODEBUILDMCP_CLI_SNAPSHOT_UI_COMMAND
                if needs_xcodebuild_cli_snapshot_ui
                else XCODEBUILDMCP_CLI_TYPE_TEXT_COMMAND
                if needs_xcodebuild_cli_type_text
                else XCODEBUILDMCP_CLI_TAP_COMMAND
                if needs_xcodebuild_cli_tap
                else XCODEBUILDMCP_CLI_COMMAND
            )
            print(f"static_apple_mcp_servers={','.join(sorted(mcp_manifest))}")
            print(f"xcodebuild_cli_policy_reason={xcodebuild_cli_decision.reason}")
            print(f"xcodebuild_cli_tool={xcodebuild_cli_tool}")
            print("xcodebuild_cli_command=" + " ".join(xcodebuild_cli_command))
            for env_key, env_value in sorted(XCODEBUILDMCP_CLI_ENV_OVERRIDES.items()):
                print(f"xcodebuild_cli_env_{env_key}={env_value}")
            print(
                f"xcodebuild_cli_env_{OMNIGENT_XCODEBUILDMCP_AXE_PATH_ENV}="
                f"{xcodebuildmcp_axe_path or 'not_set'}"
            )
            print(f"xcodebuild_cli_tool_path={xcodebuild_cli_tool_path}")
            print(f"xcodebuild_cli_root={xcodebuild_workspace_root}")
            print(f"xcodebuild_cli_scheme={APPLE_MCP_XCODEBUILD_SCHEME}")
            print(f"xcodebuild_cli_configuration={APPLE_MCP_XCODEBUILD_CONFIGURATION}")
            print(f"xcodebuild_cli_simulator={xcodebuild_simulator_name}")
            print(f"xcodebuild_cli_derived_data={xcodebuild_derived_data_path}")
            print(
                "ASSERTION: XcodeBuildMCP CLI adapter policy installed the "
                "generated tool without mutating the Apple MCP manifest"
            )
        if needs_xcodebuild_mcp:
            assert mcp_manifest is not None
            assert xcodebuild_workspace_root is not None
            print(f"static_apple_mcp_servers={','.join(sorted(mcp_manifest))}")
            print(f"converted_apple_mcp_server={APPLE_MCP_XCODEBUILD_SERVER}")
            print(f"converted_apple_mcp_xcodebuild_root={xcodebuild_workspace_root}")
            if needs_xcodebuild_discovery_mcp:
                print(f"converted_apple_mcp_xcodebuild_tool={APPLE_MCP_XCODEBUILD_TOOL}")
            if needs_xcodebuild_build_mcp or needs_xcodebuild_run_mcp:
                assert xcodebuild_simulator_name is not None
                assert xcodebuild_derived_data_path is not None
                xcodebuild_action_tool = (
                    APPLE_MCP_XCODEBUILD_BUILD_RUN_SIM_TOOL
                    if needs_xcodebuild_run_mcp
                    else APPLE_MCP_XCODEBUILD_BUILD_SIM_TOOL
                )
                print(
                    "converted_apple_mcp_xcodebuild_tools="
                    f"{APPLE_MCP_XCODEBUILD_SESSION_SHOW_DEFAULTS_TOOL},"
                    f"{APPLE_MCP_XCODEBUILD_SESSION_SET_DEFAULTS_TOOL},"
                    f"{xcodebuild_action_tool}"
                )
                print(f"xcodebuild_mcp_scheme={APPLE_MCP_XCODEBUILD_SCHEME}")
                print(f"xcodebuild_mcp_configuration={APPLE_MCP_XCODEBUILD_CONFIGURATION}")
                print(f"xcodebuild_mcp_simulator={xcodebuild_simulator_name}")
                print(f"xcodebuild_mcp_derived_data={xcodebuild_derived_data_path}")
            print("ASSERTION: Apple XcodeBuildMCP config converted into Omnigent tools config")

        if args.skip_live:
            print("live_runner_proof=skipped")
            return 0

        assert codex_path is not None
        if proof in {"graph", "all", "cutover-ready"}:
            transcript = run_live_proof_step(
                "graph",
                timeout_seconds=args.live_proof_timeout,
                action=lambda: run_live_runner_proof(agent_dir, codex_path),
            )
            print(f"graph_transcript_preview={transcript[:500]!r}")
            print(
                "ASSERTION: normal Omnigent run_prompt session/runner path "
                "emitted route block first"
            )
            print("ASSERTION: stock Codex read a bundled Apple reference through Omnigent")
        if proof in {"router-matrix", "all", "cutover-ready"}:
            matrix_proofs = run_live_proof_step(
                "router-matrix",
                timeout_seconds=args.live_proof_timeout,
                action=lambda: run_live_router_matrix_proof(agent_dir, codex_path),
            )
            for case_proof in matrix_proofs:
                print(f"router_matrix_case={case_proof.name}")
                print(f"router_matrix_session_id={case_proof.session_id}")
                print(f"router_matrix_expected_route={case_proof.expected_route}")
                print(f"router_matrix_sentinel={case_proof.sentinel}")
                print(f"router_matrix_transcript_preview={case_proof.transcript[:500]!r}")
            print(
                "ASSERTION: stock Codex preserved manifest routerSelection "
                "positive route evidence through Omnigent"
            )
            print(
                "ASSERTION: stock Codex suppressed manifest routerSelection "
                "for focused explicit skills and non-matching host scopes"
            )
        if proof in {"tool-plane", "all", "cutover-ready"}:
            tool_proof = run_live_proof_step(
                "tool-plane",
                timeout_seconds=args.live_proof_timeout,
                action=lambda: run_live_tool_proof(agent_dir, codex_path),
            )
            print(f"tool_session_id={tool_proof.session_id}")
            print(f"tool_call_id={tool_proof.call_id}")
            print(f"tool_transcript_preview={tool_proof.transcript[:500]!r}")
            print(
                "ASSERTION: stock Codex invoked Omnigent-exposed sys_os_read through dynamicTools"
            )
            print("ASSERTION: persisted session items include sys_os_read call and result")
        if needs_memory_mcp:

            def run_memory_step() -> AppleMcpProof:
                if aggregate_proof:
                    write_agent_config(
                        agent_dir,
                        apple_mcp_servers={
                            APPLE_MCP_MEMORY_SERVER: apple_mcp_servers[APPLE_MCP_MEMORY_SERVER]
                        },
                        mcp_env_overrides={
                            APPLE_MCP_MEMORY_SERVER: mcp_env_overrides[APPLE_MCP_MEMORY_SERVER]
                        },
                    )
                return run_live_apple_memory_mcp_proof(agent_dir, codex_path)

            mcp_proof = run_live_proof_step(
                "apple-mcp-memory",
                timeout_seconds=args.live_proof_timeout,
                action=run_memory_step,
            )
            print(f"apple_mcp_session_id={mcp_proof.session_id}")
            print(f"apple_mcp_call_id={mcp_proof.call_id}")
            print(f"apple_mcp_output_preview={mcp_proof.output_preview!r}")
            print(f"apple_mcp_transcript_preview={mcp_proof.transcript[:500]!r}")
            print(
                "ASSERTION: stock Codex invoked Apple memory MCP through "
                "Omnigent-converted MCP config"
            )
            print(f"ASSERTION: persisted session items include {APPLE_MCP_MEMORY_TOOL} result")
        if needs_sosumi_mcp:

            def run_sosumi_step() -> AppleMcpProof:
                if proof == "all":
                    write_agent_config(
                        agent_dir,
                        apple_mcp_servers={
                            APPLE_MCP_SOSUMI_SERVER: apple_mcp_servers[APPLE_MCP_SOSUMI_SERVER]
                        },
                        mcp_env_overrides={},
                    )
                return run_live_apple_sosumi_mcp_proof(agent_dir, codex_path)

            sosumi_proof = run_live_proof_step(
                "apple-mcp-sosumi",
                timeout_seconds=args.live_proof_timeout,
                action=run_sosumi_step,
            )
            print(f"sosumi_mcp_session_id={sosumi_proof.session_id}")
            print(f"sosumi_mcp_call_id={sosumi_proof.call_id}")
            print(f"sosumi_mcp_output_preview={sosumi_proof.output_preview!r}")
            print(f"sosumi_mcp_transcript_preview={sosumi_proof.transcript[:500]!r}")
            print(
                "ASSERTION: stock Codex invoked Apple sosumi MCP through "
                "Omnigent-converted MCP config"
            )
            print(f"ASSERTION: persisted session items include {APPLE_MCP_SOSUMI_TOOL} result")
        if runs_apple_docs_cli:
            cli_proof = run_live_proof_step(
                "apple-docs-cli",
                timeout_seconds=args.live_proof_timeout,
                action=lambda: run_live_apple_docs_cli_proof(agent_dir, codex_path),
            )
            print(f"apple_docs_cli_session_id={cli_proof.session_id}")
            print(f"apple_docs_cli_call_id={cli_proof.call_id}")
            print(f"apple_docs_cli_output_preview={cli_proof.output_preview!r}")
            print(f"apple_docs_cli_transcript_preview={cli_proof.transcript[:500]!r}")
            print(
                "ASSERTION: stock Codex invoked the generated Apple docs CLI adapter "
                "through Omnigent dynamicTools"
            )
            print(f"ASSERTION: persisted session items include {APPLE_DOCS_CLI_TOOL} result")
        if proof == "apple-workflow-smoke":
            assert xcodebuild_workspace_root is not None
            smoke_proof = run_live_proof_step(
                "apple-workflow-smoke",
                timeout_seconds=args.live_proof_timeout,
                action=lambda: run_live_apple_workflow_smoke_proof(
                    agent_dir,
                    codex_path,
                    workspace_root=xcodebuild_workspace_root,
                ),
            )
            print(f"apple_workflow_smoke_session_id={smoke_proof.session_id}")
            print(f"apple_workflow_smoke_docs_call_id={smoke_proof.apple_docs_call_id}")
            print(f"apple_workflow_smoke_xcodebuild_call_id={smoke_proof.xcodebuild_call_id}")
            print(
                "apple_workflow_smoke_docs_output_preview="
                f"{smoke_proof.apple_docs_output_preview!r}"
            )
            print(
                "apple_workflow_smoke_xcodebuild_output_preview="
                f"{smoke_proof.xcodebuild_output_preview!r}"
            )
            print(f"apple_workflow_smoke_transcript_preview={smoke_proof.transcript[:500]!r}")
            print(
                "ASSERTION: representative Apple workflow emitted route evidence, "
                "fetched Apple docs, and discovered the local Xcode project"
            )
            print(
                f"ASSERTION: persisted session items include {APPLE_DOCS_CLI_TOOL} "
                f"and {APPLE_MCP_XCODEBUILD_TOOL} results"
            )
        if needs_xcodebuild_cli_run:
            assert xcodebuild_workspace_root is not None
            assert xcodebuild_simulator_name is not None
            assert xcodebuild_derived_data_path is not None
            xcodebuild_cli_proof = run_live_proof_step(
                "apple-xcodebuild-cli-run",
                timeout_seconds=args.live_proof_timeout,
                action=lambda: run_live_xcodebuild_cli_run_proof(
                    agent_dir,
                    codex_path,
                    workspace_root=xcodebuild_workspace_root,
                    simulator_name=xcodebuild_simulator_name,
                    derived_data_path=xcodebuild_derived_data_path,
                ),
            )
            print(f"xcodebuild_cli_session_id={xcodebuild_cli_proof.session_id}")
            print(f"xcodebuild_cli_call_id={xcodebuild_cli_proof.call_id}")
            print(f"xcodebuild_cli_output_preview={xcodebuild_cli_proof.output_preview!r}")
            print(f"xcodebuild_cli_transcript_preview={xcodebuild_cli_proof.transcript[:500]!r}")
            print(
                "ASSERTION: stock Codex invoked the generated XcodeBuildMCP "
                "CLI adapter through Omnigent dynamicTools"
            )
            print(f"ASSERTION: persisted session items include {XCODEBUILD_CLI_TOOL} result")
        if needs_xcodebuild_cli_test:
            assert xcodebuild_workspace_root is not None
            assert xcodebuild_simulator_name is not None
            assert xcodebuild_derived_data_path is not None
            xcodebuild_cli_test_proof = run_live_proof_step(
                "apple-xcodebuild-cli-test",
                timeout_seconds=args.live_proof_timeout,
                action=lambda: run_live_xcodebuild_cli_test_proof(
                    agent_dir,
                    codex_path,
                    workspace_root=xcodebuild_workspace_root,
                    simulator_name=xcodebuild_simulator_name,
                    derived_data_path=xcodebuild_derived_data_path,
                ),
            )
            print(f"xcodebuild_cli_test_session_id={xcodebuild_cli_test_proof.session_id}")
            print(f"xcodebuild_cli_test_call_id={xcodebuild_cli_test_proof.call_id}")
            print(
                f"xcodebuild_cli_test_output_preview={xcodebuild_cli_test_proof.output_preview!r}"
            )
            print(
                "xcodebuild_cli_test_transcript_preview="
                f"{xcodebuild_cli_test_proof.transcript[:500]!r}"
            )
            print(
                "ASSERTION: stock Codex invoked the generated XcodeBuildMCP "
                "CLI simulator test adapter through Omnigent dynamicTools"
            )
            print(f"ASSERTION: persisted session items include {XCODEBUILD_CLI_TEST_TOOL} result")
        if needs_xcodebuild_cli_screenshot:
            assert xcodebuild_workspace_root is not None
            assert xcodebuild_simulator_name is not None
            assert xcodebuild_derived_data_path is not None
            xcodebuild_cli_screenshot_proof = run_live_proof_step(
                "apple-xcodebuild-cli-screenshot",
                timeout_seconds=args.live_proof_timeout,
                action=lambda: run_live_xcodebuild_cli_screenshot_proof(
                    agent_dir,
                    codex_path,
                    workspace_root=xcodebuild_workspace_root,
                    simulator_name=xcodebuild_simulator_name,
                    derived_data_path=xcodebuild_derived_data_path,
                ),
            )
            print(
                "xcodebuild_cli_screenshot_session_id="
                f"{xcodebuild_cli_screenshot_proof.session_id}"
            )
            print(f"xcodebuild_cli_screenshot_call_id={xcodebuild_cli_screenshot_proof.call_id}")
            print(
                "xcodebuild_cli_screenshot_output_preview="
                f"{xcodebuild_cli_screenshot_proof.output_preview!r}"
            )
            print(
                "xcodebuild_cli_screenshot_transcript_preview="
                f"{xcodebuild_cli_screenshot_proof.transcript[:500]!r}"
            )
            print(
                "ASSERTION: stock Codex invoked the generated XcodeBuildMCP "
                "CLI simulator screenshot adapter through Omnigent dynamicTools"
            )
            print(
                f"ASSERTION: persisted session items include "
                f"{XCODEBUILD_CLI_SCREENSHOT_TOOL} result"
            )
        if needs_xcodebuild_cli_runtime_logs:
            assert xcodebuild_workspace_root is not None
            assert xcodebuild_simulator_name is not None
            assert xcodebuild_derived_data_path is not None
            xcodebuild_cli_runtime_logs_proof = run_live_proof_step(
                "apple-xcodebuild-cli-runtime-logs",
                timeout_seconds=args.live_proof_timeout,
                action=lambda: run_live_xcodebuild_cli_runtime_logs_proof(
                    agent_dir,
                    codex_path,
                    workspace_root=xcodebuild_workspace_root,
                    simulator_name=xcodebuild_simulator_name,
                    derived_data_path=xcodebuild_derived_data_path,
                ),
            )
            print(
                "xcodebuild_cli_runtime_logs_session_id="
                f"{xcodebuild_cli_runtime_logs_proof.session_id}"
            )
            print(
                f"xcodebuild_cli_runtime_logs_call_id={xcodebuild_cli_runtime_logs_proof.call_id}"
            )
            print(
                "xcodebuild_cli_runtime_logs_output_preview="
                f"{xcodebuild_cli_runtime_logs_proof.output_preview!r}"
            )
            print(
                "xcodebuild_cli_runtime_logs_transcript_preview="
                f"{xcodebuild_cli_runtime_logs_proof.transcript[:500]!r}"
            )
            print(
                "ASSERTION: stock Codex invoked the generated XcodeBuildMCP "
                "CLI simulator runtime logs adapter through Omnigent dynamicTools"
            )
            print(
                f"ASSERTION: persisted session items include "
                f"{XCODEBUILD_CLI_RUNTIME_LOGS_TOOL} result"
            )
        if needs_xcodebuild_cli_snapshot_ui:
            assert xcodebuild_workspace_root is not None
            assert xcodebuild_simulator_name is not None
            assert xcodebuild_derived_data_path is not None
            xcodebuild_cli_snapshot_ui_proof = run_live_proof_step(
                "apple-xcodebuild-cli-snapshot-ui",
                timeout_seconds=args.live_proof_timeout,
                action=lambda: run_live_xcodebuild_cli_snapshot_ui_proof(
                    agent_dir,
                    codex_path,
                    workspace_root=xcodebuild_workspace_root,
                    simulator_name=xcodebuild_simulator_name,
                    derived_data_path=xcodebuild_derived_data_path,
                    axe_path=xcodebuildmcp_axe_path,
                ),
            )
            print(
                "xcodebuild_cli_snapshot_ui_session_id="
                f"{xcodebuild_cli_snapshot_ui_proof.session_id}"
            )
            print(f"xcodebuild_cli_snapshot_ui_call_id={xcodebuild_cli_snapshot_ui_proof.call_id}")
            print(
                "xcodebuild_cli_snapshot_ui_output_preview="
                f"{xcodebuild_cli_snapshot_ui_proof.output_preview!r}"
            )
            print(
                "xcodebuild_cli_snapshot_ui_transcript_preview="
                f"{xcodebuild_cli_snapshot_ui_proof.transcript[:500]!r}"
            )
            print(
                "ASSERTION: stock Codex invoked the generated XcodeBuildMCP "
                "CLI semantic snapshot adapter through Omnigent dynamicTools"
            )
            print(
                f"ASSERTION: persisted session items include "
                f"{XCODEBUILD_CLI_SNAPSHOT_UI_TOOL} result"
            )
        if needs_xcodebuild_cli_type_text:
            assert xcodebuild_workspace_root is not None
            assert xcodebuild_simulator_name is not None
            assert xcodebuild_derived_data_path is not None
            xcodebuild_cli_type_text_proof = run_live_proof_step(
                "apple-xcodebuild-cli-type-text",
                timeout_seconds=args.live_proof_timeout,
                action=lambda: run_live_xcodebuild_cli_type_text_proof(
                    agent_dir,
                    codex_path,
                    workspace_root=xcodebuild_workspace_root,
                    simulator_name=xcodebuild_simulator_name,
                    derived_data_path=xcodebuild_derived_data_path,
                    axe_path=xcodebuildmcp_axe_path,
                ),
            )
            print(
                f"xcodebuild_cli_type_text_session_id={xcodebuild_cli_type_text_proof.session_id}"
            )
            print(f"xcodebuild_cli_type_text_call_id={xcodebuild_cli_type_text_proof.call_id}")
            print(
                "xcodebuild_cli_type_text_output_preview="
                f"{xcodebuild_cli_type_text_proof.output_preview!r}"
            )
            print(
                "xcodebuild_cli_type_text_transcript_preview="
                f"{xcodebuild_cli_type_text_proof.transcript[:500]!r}"
            )
            print(
                "ASSERTION: stock Codex invoked the generated XcodeBuildMCP "
                "CLI type-text adapter through Omnigent dynamicTools"
            )
            print(
                f"ASSERTION: persisted session items include "
                f"{XCODEBUILD_CLI_TYPE_TEXT_TOOL} result"
            )
        if needs_xcodebuild_cli_tap:
            assert xcodebuild_workspace_root is not None
            assert xcodebuild_simulator_name is not None
            assert xcodebuild_derived_data_path is not None
            xcodebuild_cli_tap_proof = run_live_proof_step(
                "apple-xcodebuild-cli-tap",
                timeout_seconds=args.live_proof_timeout,
                action=lambda: run_live_xcodebuild_cli_tap_proof(
                    agent_dir,
                    codex_path,
                    workspace_root=xcodebuild_workspace_root,
                    simulator_name=xcodebuild_simulator_name,
                    derived_data_path=xcodebuild_derived_data_path,
                    axe_path=xcodebuildmcp_axe_path,
                ),
            )
            print(f"xcodebuild_cli_tap_session_id={xcodebuild_cli_tap_proof.session_id}")
            print(f"xcodebuild_cli_tap_call_id={xcodebuild_cli_tap_proof.call_id}")
            print(f"xcodebuild_cli_tap_output_preview={xcodebuild_cli_tap_proof.output_preview!r}")
            print(
                "xcodebuild_cli_tap_transcript_preview="
                f"{xcodebuild_cli_tap_proof.transcript[:500]!r}"
            )
            print(
                "ASSERTION: stock Codex invoked the generated XcodeBuildMCP "
                "CLI tap adapter through Omnigent dynamicTools"
            )
            print(f"ASSERTION: persisted session items include {XCODEBUILD_CLI_TAP_TOOL} result")
        if runs_xcodebuild_discovery_mcp:
            assert xcodebuild_workspace_root is not None

            def run_xcodebuild_step() -> AppleMcpProof:
                if aggregate_proof:
                    write_agent_config(
                        agent_dir,
                        apple_mcp_servers={
                            APPLE_MCP_XCODEBUILD_SERVER: apple_mcp_servers[
                                APPLE_MCP_XCODEBUILD_SERVER
                            ]
                        },
                        mcp_env_overrides={},
                    )
                return run_live_apple_xcodebuild_mcp_proof(
                    agent_dir,
                    codex_path,
                    workspace_root=xcodebuild_workspace_root,
                )

            xcodebuild_proof = run_live_proof_step(
                "apple-mcp-xcodebuild",
                timeout_seconds=args.live_proof_timeout,
                action=run_xcodebuild_step,
            )
            print(f"xcodebuild_mcp_session_id={xcodebuild_proof.session_id}")
            print(f"xcodebuild_mcp_call_id={xcodebuild_proof.call_id}")
            print(f"xcodebuild_mcp_output_preview={xcodebuild_proof.output_preview!r}")
            print(f"xcodebuild_mcp_transcript_preview={xcodebuild_proof.transcript[:500]!r}")
            print(
                "ASSERTION: stock Codex invoked Apple XcodeBuildMCP discovery through "
                "Omnigent-converted MCP config"
            )
            print(f"ASSERTION: persisted session items include {APPLE_MCP_XCODEBUILD_TOOL} result")
        if needs_xcodebuild_build_mcp:
            assert xcodebuild_workspace_root is not None
            assert xcodebuild_simulator_name is not None
            assert xcodebuild_derived_data_path is not None
            build_proof = run_live_proof_step(
                "apple-mcp-xcodebuild-build",
                timeout_seconds=args.live_proof_timeout,
                action=lambda: run_live_apple_xcodebuild_mcp_build_proof(
                    agent_dir,
                    codex_path,
                    workspace_root=xcodebuild_workspace_root,
                    simulator_name=xcodebuild_simulator_name,
                    derived_data_path=xcodebuild_derived_data_path,
                ),
            )
            print(f"xcodebuild_mcp_build_session_id={build_proof.session_id}")
            print(f"xcodebuild_mcp_show_defaults_call_id={build_proof.show_defaults_call_id}")
            print(f"xcodebuild_mcp_set_defaults_call_id={build_proof.set_defaults_call_id}")
            print(f"xcodebuild_mcp_build_call_id={build_proof.build_call_id}")
            print(f"xcodebuild_mcp_build_output_preview={build_proof.output_preview!r}")
            print(f"xcodebuild_mcp_build_transcript_preview={build_proof.transcript[:500]!r}")
            print(
                "ASSERTION: stock Codex drove compile-only XcodeBuildMCP "
                "simulator build through Omnigent-converted MCP config"
            )
            print(
                f"ASSERTION: persisted session items include "
                f"{APPLE_MCP_XCODEBUILD_BUILD_SIM_TOOL} result"
            )
        if needs_xcodebuild_run_mcp:
            assert xcodebuild_workspace_root is not None
            assert xcodebuild_simulator_name is not None
            assert xcodebuild_derived_data_path is not None
            run_proof = run_live_proof_step(
                "apple-mcp-xcodebuild-run",
                timeout_seconds=args.live_proof_timeout,
                action=lambda: run_live_apple_xcodebuild_mcp_run_proof(
                    agent_dir,
                    codex_path,
                    workspace_root=xcodebuild_workspace_root,
                    simulator_name=xcodebuild_simulator_name,
                    derived_data_path=xcodebuild_derived_data_path,
                ),
            )
            print(f"xcodebuild_mcp_run_session_id={run_proof.session_id}")
            print(f"xcodebuild_mcp_run_show_defaults_call_id={run_proof.show_defaults_call_id}")
            print(f"xcodebuild_mcp_run_set_defaults_call_id={run_proof.set_defaults_call_id}")
            print(f"xcodebuild_mcp_run_call_id={run_proof.run_call_id}")
            print(f"xcodebuild_mcp_run_output_preview={run_proof.output_preview!r}")
            print(f"xcodebuild_mcp_run_transcript_preview={run_proof.transcript[:500]!r}")
            print(
                "ASSERTION: stock Codex drove XcodeBuildMCP simulator "
                "build/install/launch through Omnigent-converted MCP config"
            )
            print(
                f"ASSERTION: persisted session items include "
                f"{APPLE_MCP_XCODEBUILD_BUILD_RUN_SIM_TOOL} result"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
