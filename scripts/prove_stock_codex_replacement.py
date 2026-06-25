#!/usr/bin/env python3
"""Proof gate for the Omnigent stock-Codex replacement track.

This script is intentionally local/operator-facing. It does not modify the
Codex fork. It copies an Apple workflow bundle into a temporary Omnigent agent,
verifies the selected top-level skill graph is present, then can run a live
stock-Codex proof through Omnigent's normal ``run_prompt()`` session/runner path.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

from omnigent_client import OmnigentClient

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
EXPECTED_ROUTE = (
    "Routing: orchestrator-led\n\n"
    "Activated skills\n"
    f"- `{SELECTED_OWNER}`"
)
REFERENCE_SENTINEL = "Use this shared contract for broad brigade-orchestrator lanes"
TOOL_SENTINEL = "OMNIGENT_TOOL_SENTINEL_42"
APPLE_MCP_MEMORY_SERVER = "memory"
APPLE_MCP_MEMORY_TOOL = "memory__create_entities"
APPLE_MCP_MEMORY_SENTINEL = "APPLE_MCP_SENTINEL_73"
APPLE_MCP_SOSUMI_SERVER = "sosumi"
APPLE_MCP_SOSUMI_TOOL = "sosumi__fetchAppleDocumentation"
APPLE_MCP_SOSUMI_DOC_PATH = "/documentation/swift/string"
APPLE_MCP_SOSUMI_SENTINELS = (
    "title: String",
    "source: https://developer.apple.com/documentation/swift/string",
)
APPLE_MCP_XCODEBUILD_SERVER = "XcodeBuildMCP"
APPLE_MCP_XCODEBUILD_TOOL = "XcodeBuildMCP__discover_projs"
APPLE_MCP_XCODEBUILD_PROJECT_RELATIVE_PATH = "ap-web/ios/Omnigent.xcodeproj"
APPLE_MCP_XCODEBUILD_SENTINELS = (
    "Discovery finished. Found",
    "Projects found:",
    "Omnigent.xcodeproj",
)
RELATIVE_MARKDOWN_PATH_RE = re.compile(r"`((?:\.\.?/)[^`]+)`")
PLUGIN_SKILL_REF_RE = re.compile(rf"\b{re.escape(PLUGIN_NAME)}:([A-Za-z0-9_.-]+)\b")
EXPECTED_APPLE_MCP_SERVERS = frozenset({"sosumi", "memory", "XcodeBuildMCP"})
DEFAULT_LIVE_PROOF_TIMEOUT_SECONDS = 180.0
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
class AppleMcpProof:
    """Live proof result for an Apple MCP-backed tool call."""

    session_id: str
    call_id: str
    transcript: str
    output_preview: str


@dataclass(frozen=True)
class SessionRun:
    """Captured result from one normal Omnigent session/runner query."""

    session_id: str
    text: str
    items: list[dict[str, Any]]


class LiveProofTimeoutError(Exception):
    """A single live proof step exceeded its configured wall-clock budget."""


def _candidate_bundles() -> list[Path]:
    env_path = os.environ.get("APPLE_APPDEV_WORKFLOW_BUNDLE", "").strip()
    candidates: list[Path] = []
    if env_path:
        candidates.append(Path(env_path).expanduser())
    candidates.extend(
        [
            Path.home()
            / ".codex-fork/plugins/cache/LocalAppleWorkflow/apple-appdev-workflow/0.1.1",
            Path.home() / ".codex/plugins/cache/LocalAppleWorkflow/apple-appdev-workflow/0.1.1",
        ]
    )
    return candidates


def resolve_default_bundle() -> Path:
    """Return the first installed Apple workflow bundle candidate."""
    for candidate in _candidate_bundles():
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
            f"live_proof_failed={name} elapsed={_format_seconds(elapsed)} "
            f"exit={exc.code!r}",
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
) -> None:
    """Write the Omnigent harness config into the copied bundle root."""
    mcp_tools_block = ""
    if apple_mcp_servers:
        mcp_tools_block = _mcp_tools_yaml(
            apple_mcp_servers,
            env_overrides=mcp_env_overrides or {},
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


async def _run_session_query(
    *,
    agent_dir: Path,
    codex_path: Path,
    prompt: str,
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
                    text = await _query_sessions_once(
                        client=client,
                        agent_name=agent_name,
                        tool_handler=None,
                        prompt=prompt,
                        session_bundle=_bundle_agent(spec_path),
                        session_bundle_filename="agent.tar.gz",
                        runner_id=server.runner_id,
                        on_session_ready=lambda sid: session_holder.setdefault("id", sid),
                    )
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
            f'{{"path": "{APPLE_MCP_SOSUMI_DOC_PATH}"}}. After the tool result '
            "is available, reply exactly SOSUMI_MCP_OK."
        ),
        (
            "SwiftUI Apple documentation MCP proof. Call the available tool "
            f"named {APPLE_MCP_SOSUMI_TOOL} exactly once before answering. "
            f"Pass the path {APPLE_MCP_SOSUMI_DOC_PATH!r}. Do not use any "
            "other tool for this proof. After the tool call succeeds, reply "
            "exactly SOSUMI_MCP_OK."
        ),
        (
            f"Use {APPLE_MCP_SOSUMI_TOOL} now to fetch "
            f"{APPLE_MCP_SOSUMI_DOC_PATH}. This is a tool-call proof; a text "
            "answer without the function call is invalid. After the function "
            "call output is available, reply exactly SOSUMI_MCP_OK."
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
            return _validate_sosumi_mcp_run(run, attempt=attempt)
        except SosumiProofAttemptError as exc:
            errors.append(str(exc))
    joined_errors = "\n\n".join(errors)
    raise SystemExit(f"Sosumi MCP proof failed after {len(prompts)} attempts:\n{joined_errors}")


class SosumiProofAttemptError(Exception):
    """One failed sosumi proof attempt that can be retried."""


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
            f"attempt={attempt}: "
            + _missing_tool_call_message(APPLE_MCP_SOSUMI_TOOL, run)
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
    if "SOSUMI_MCP_OK" not in transcript:
        raise SosumiProofAttemptError(
            f"attempt={attempt}: sosumi MCP proof did not return "
            f"SOSUMI_MCP_OK. Transcript:\n{transcript}"
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
    raise SystemExit(
        f"XcodeBuildMCP proof failed after {len(prompts)} attempts:\n{joined_errors}"
    )


class XcodeBuildMcpProofAttemptError(Exception):
    """One failed XcodeBuildMCP proof attempt that can be retried."""


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
        if item.get("type") == "function_call"
        and item.get("name") == APPLE_MCP_XCODEBUILD_TOOL
    ]
    if not calls:
        raise XcodeBuildMcpProofAttemptError(
            f"attempt={attempt}: "
            + _missing_tool_call_message(APPLE_MCP_XCODEBUILD_TOOL, run)
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
        sentinel
        for sentinel in APPLE_MCP_XCODEBUILD_SENTINELS
        if sentinel not in output_text
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


def _session_item_summary(items: list[dict[str, Any]]) -> str:
    """Summarize persisted session items without dumping full tool payloads."""
    summary: list[str] = []
    for index, item in enumerate(items):
        item_type = item.get("type")
        if item_type == "function_call":
            summary.append(
                f"{index}:function_call:{item.get('name')}:{item.get('call_id')}"
            )
        elif item_type == "function_call_output":
            output = str(item.get("output", ""))
            summary.append(
                f"{index}:function_call_output:{item.get('call_id')}:len={len(output)}"
            )
        elif item_type == "message":
            role = item.get("role", "?")
            content = str(item.get("content", ""))
            summary.append(f"{index}:message:{role}:len={len(content)}")
        else:
            summary.append(f"{index}:{item_type}")
    return "[" + ", ".join(summary[:40]) + "]"


def asyncio_run_session_query(*, agent_dir: Path, codex_path: Path, prompt: str) -> SessionRun:
    """Run the async session query from the synchronous proof script."""
    import asyncio

    return asyncio.run(
        _run_session_query(agent_dir=agent_dir, codex_path=codex_path, prompt=prompt)
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prove Omnigent can wrap stock Codex for the Apple routerSelection path."
    )
    parser.add_argument(
        "--proof",
        choices=(
            "graph",
            "tool-plane",
            "mcp-tools",
            "apple-mcp",
            "apple-mcp-sosumi",
            "apple-mcp-xcodebuild",
            "all",
        ),
        default="graph",
        help=(
            "Proof gate to run. Defaults to the existing graph proof. "
            "'mcp-tools' is accepted as an alias for 'tool-plane'; "
            "'apple-mcp' proves memory, 'apple-mcp-sosumi' proves sosumi, "
            "and 'apple-mcp-xcodebuild' proves read-only XcodeBuildMCP discovery."
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
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    proof = "tool-plane" if args.proof == "mcp-tools" else args.proof
    source_bundle = (
        args.apple_bundle.expanduser() if args.apple_bundle else resolve_default_bundle()
    )
    if not source_bundle.is_dir():
        raise SystemExit(f"Apple bundle not found: {source_bundle}")

    codex_path: Path | None = None
    if not args.skip_live or args.codex_path:
        codex_path = resolve_codex_path(args.codex_path)
        assert_stock_codex_path(codex_path, allow_fork_codex=args.allow_fork_codex)

    with temporary_agent_dir(args.keep_fixture) as agent_dir:
        copy_bundle(source_bundle, agent_dir)
        needs_memory_mcp = proof in {"apple-mcp", "all"}
        needs_sosumi_mcp = proof in {"apple-mcp-sosumi", "all"}
        needs_xcodebuild_mcp = proof in {"apple-mcp-xcodebuild", "all"}
        needs_apple_mcp = needs_memory_mcp or needs_sosumi_mcp or needs_xcodebuild_mcp
        mcp_manifest = None
        memory_file = None
        xcodebuild_workspace_root = (
            resolve_xcodebuild_mcp_workspace_root() if needs_xcodebuild_mcp else None
        )
        apple_mcp_servers: dict[str, dict[str, Any]] = {}
        mcp_env_overrides: dict[str, dict[str, str]] = {}
        if proof in {
            "tool-plane",
            "apple-mcp",
            "apple-mcp-sosumi",
            "apple-mcp-xcodebuild",
            "all",
        }:
            mcp_manifest = prove_apple_mcp_manifest(agent_dir)
        if needs_apple_mcp:
            assert mcp_manifest is not None
            if needs_memory_mcp:
                memory_file = agent_dir / "memory-proof.json"
                memory_file.write_text("{}", encoding="utf-8")
                apple_mcp_servers[APPLE_MCP_MEMORY_SERVER] = mcp_config_from_manifest(
                    mcp_manifest,
                    APPLE_MCP_MEMORY_SERVER,
                )
                mcp_env_overrides[APPLE_MCP_MEMORY_SERVER] = {
                    "MEMORY_FILE_PATH": str(memory_file)
                }
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
        if proof == "all" and not args.skip_live:
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
        print(f"static_relative_files={len(graph.relative_paths)}")
        print(f"static_skill_refs={len(graph.skill_refs)}")
        print("ASSERTION: selected Apple skill graph resolves inside the Omnigent bundle")

        if proof in {"tool-plane", "all"}:
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
        if needs_xcodebuild_mcp:
            assert mcp_manifest is not None
            assert xcodebuild_workspace_root is not None
            print(f"static_apple_mcp_servers={','.join(sorted(mcp_manifest))}")
            print(f"converted_apple_mcp_server={APPLE_MCP_XCODEBUILD_SERVER}")
            print(f"converted_apple_mcp_xcodebuild_tool={APPLE_MCP_XCODEBUILD_TOOL}")
            print(f"converted_apple_mcp_xcodebuild_root={xcodebuild_workspace_root}")
            print(
                "ASSERTION: Apple XcodeBuildMCP config converted into Omnigent tools config"
            )

        if args.skip_live:
            print("live_runner_proof=skipped")
            return 0

        assert codex_path is not None
        if proof in {"graph", "all"}:
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
        if proof in {"tool-plane", "all"}:
            tool_proof = run_live_proof_step(
                "tool-plane",
                timeout_seconds=args.live_proof_timeout,
                action=lambda: run_live_tool_proof(agent_dir, codex_path),
            )
            print(f"tool_session_id={tool_proof.session_id}")
            print(f"tool_call_id={tool_proof.call_id}")
            print(f"tool_transcript_preview={tool_proof.transcript[:500]!r}")
            print(
                "ASSERTION: stock Codex invoked Omnigent-exposed sys_os_read "
                "through dynamicTools"
            )
            print("ASSERTION: persisted session items include sys_os_read call and result")
        if needs_memory_mcp:
            def run_memory_step() -> AppleMcpProof:
                if proof == "all":
                    write_agent_config(
                        agent_dir,
                        apple_mcp_servers={
                            APPLE_MCP_MEMORY_SERVER: apple_mcp_servers[
                                APPLE_MCP_MEMORY_SERVER
                            ]
                        },
                        mcp_env_overrides={
                            APPLE_MCP_MEMORY_SERVER: mcp_env_overrides[
                                APPLE_MCP_MEMORY_SERVER
                            ]
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
                            APPLE_MCP_SOSUMI_SERVER: apple_mcp_servers[
                                APPLE_MCP_SOSUMI_SERVER
                            ]
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
        if needs_xcodebuild_mcp:
            assert xcodebuild_workspace_root is not None
            def run_xcodebuild_step() -> AppleMcpProof:
                if proof == "all":
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
            print(
                f"xcodebuild_mcp_transcript_preview={xcodebuild_proof.transcript[:500]!r}"
            )
            print(
                "ASSERTION: stock Codex invoked Apple XcodeBuildMCP discovery through "
                "Omnigent-converted MCP config"
            )
            print(f"ASSERTION: persisted session items include {APPLE_MCP_XCODEBUILD_TOOL} result")
    return 0


if __name__ == "__main__":
    sys.exit(main())
