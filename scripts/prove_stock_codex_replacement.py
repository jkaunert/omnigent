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
import io
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

from omnigent_client import OmnigentClient

from omnigent.adapters.apple_docs_cli import (
    APPLE_DOCS_CLI_URL,
    DEFAULT_APPLE_DOCS_CLI_POLICY,
    write_fetch_apple_docs_cli_tool,
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
LAUNCHER_ACTIVATION_SENTINEL = "OMNIGENT_CODEX_LAUNCHER_ACTIVATION_OK"
LAUNCHER_ACTIVATION_PROBE_ARG = "--omnigent-launcher-probe"
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
    activated_codex_path: Path
    restored_codex_path: Path
    shim_path: Path
    uvx_path: Path
    sanitized_path: str
    probe_output: str


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
    raw = value or shutil.which("codex")
    if not raw:
        raise SystemExit("Could not find codex on PATH. Pass --codex-path.")
    path = Path(raw).expanduser().resolve()
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
        sanitized_path = _path_without_directory(original_path, shim_dir)
        _write_launcher_activation_shim(
            shim_path,
            repo_root=repo_root,
            uvx_path=uvx_path,
            expected_codex_path=baseline_path,
            expected_codex_realpath=baseline_realpath,
            sanitized_path=sanitized_path,
        )

        activated_path_value = f"{shim_dir}{os.pathsep}{original_path}"
        with temporary_env({"PATH": activated_path_value}):
            activated_raw = shutil.which("codex")
            if activated_raw is None:
                raise SystemExit("Temporary launcher activation removed codex from PATH.")
            activated_path = Path(activated_raw).expanduser().resolve()
            if activated_path != shim_path.resolve():
                raise SystemExit(
                    "Temporary launcher activation did not select the shim.\n"
                    f"expected={shim_path}\nactual={activated_raw}"
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
        "ASSERTION: the shim removed itself from PATH before delegation, so "
        "Omnigent's internal codex lookup resolves the underlying stock Codex"
    )
    print("ASSERTION: PATH lookup was restored after the isolated activation scope")


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
    sanitized_path: str,
) -> None:
    """Write the temporary ``codex`` launcher shim used by the proof."""
    quoted_sanitized_path = shlex.quote(sanitized_path)
    quoted_expected_codex_path = shlex.quote(str(expected_codex_path))
    quoted_expected_codex_realpath = shlex.quote(str(expected_codex_realpath))
    quoted_uvx_path = shlex.quote(str(uvx_path))
    quoted_repo_root = shlex.quote(str(repo_root))
    quoted_probe_arg = shlex.quote(LAUNCHER_ACTIVATION_PROBE_ARG)
    quoted_sentinel = shlex.quote(LAUNCHER_ACTIVATION_SENTINEL)
    shim_path.write_text(
        f"""#!/bin/sh
set -eu

SANITIZED_PATH={quoted_sanitized_path}
EXPECTED_CODEX_PATH={quoted_expected_codex_path}
EXPECTED_CODEX_REALPATH={quoted_expected_codex_realpath}
UVX_PATH={quoted_uvx_path}
REPO_ROOT={quoted_repo_root}
PROBE_ARG={quoted_probe_arg}
SENTINEL={quoted_sentinel}

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
  printf '%s\\n' "$SENTINEL"
  printf 'shim_path=%s\\n' "$0"
  printf 'delegates_to=%s --from %s omnigent codex\\n' "$UVX_PATH" "$REPO_ROOT"
  printf 'resolved_underlying_codex_path=%s\\n' "$resolved"
  printf 'expected_underlying_codex_path=%s\\n' "$EXPECTED_CODEX_PATH"
  printf 'expected_underlying_codex_realpath=%s\\n' "$EXPECTED_CODEX_REALPATH"
  exit 0
fi

PATH="$SANITIZED_PATH"
export PATH
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
    expected_line = f"resolved_underlying_codex_path={expected_codex_path}"
    if expected_line not in output:
        raise SystemExit(
            "Launcher activation probe did not resolve the underlying stock Codex.\n"
            f"Expected line: {expected_line}\nOutput:\n{output}"
        )
    if "delegates_to=" not in output:
        raise SystemExit(f"Launcher activation probe missed delegation preview:\n{output}")


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
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    requested_proof = "tool-plane" if args.proof == "mcp-tools" else args.proof
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
