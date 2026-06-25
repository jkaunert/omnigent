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
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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
APPLE_MCP_PROOF_SERVER = "memory"
APPLE_MCP_PROOF_TOOL = "memory__create_entities"
APPLE_MCP_SENTINEL = "APPLE_MCP_SENTINEL_73"
RELATIVE_MARKDOWN_PATH_RE = re.compile(r"`((?:\.\.?/)[^`]+)`")
PLUGIN_SKILL_REF_RE = re.compile(rf"\b{re.escape(PLUGIN_NAME)}:([A-Za-z0-9_.-]+)\b")
EXPECTED_APPLE_MCP_SERVERS = frozenset({"sosumi", "memory", "XcodeBuildMCP"})


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
    apple_mcp_memory: dict[str, Any] | None = None,
    memory_file: Path | None = None,
) -> None:
    """Write the Omnigent harness config into the copied bundle root."""
    mcp_tools_block = ""
    if apple_mcp_memory is not None:
        if memory_file is None:
            raise ValueError("memory_file is required when apple_mcp_memory is set")
        mcp_tools_block = _memory_mcp_tools_yaml(apple_mcp_memory, memory_file)
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


def _memory_mcp_tools_yaml(memory_config: dict[str, Any], memory_file: Path) -> str:
    """Translate the Apple ``memory`` MCP config into Omnigent YAML."""
    command = memory_config.get("command")
    args = memory_config.get("args", [])
    if not isinstance(command, str) or not command:
        raise SystemExit("Apple memory MCP config does not declare a command")
    if not isinstance(args, list) or not all(isinstance(arg, str) for arg in args):
        raise SystemExit("Apple memory MCP config args must be a list of strings")
    lines = [
        "tools:",
        f"  {APPLE_MCP_PROOF_SERVER}:",
        "    type: mcp",
        f"    command: {_yaml_string(command)}",
        "    args:",
    ]
    lines.extend(f"      - {_yaml_string(arg)}" for arg in args)
    lines.extend(
        [
            "    env:",
            f"      MEMORY_FILE_PATH: {_yaml_string(str(memory_file))}",
        ]
    )
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


def memory_mcp_config_from_manifest(mcp_manifest: dict[str, Any]) -> dict[str, Any]:
    """Return the Apple memory MCP server config from a parsed manifest."""
    memory_config = mcp_manifest.get(APPLE_MCP_PROOF_SERVER)
    if not isinstance(memory_config, dict):
        raise SystemExit("Apple MCP manifest does not contain a memory server object")
    return memory_config


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


def run_live_apple_mcp_proof(agent_dir: Path, codex_path: Path) -> AppleMcpProof:
    """Prove stock Codex can call an Apple MCP-backed tool through Omnigent."""
    prompt = (
        "SwiftUI Apple MCP execution proof. Call the available tool named "
        f"{APPLE_MCP_PROOF_TOOL} exactly once before answering. Pass exactly one "
        "entity with name "
        f"{APPLE_MCP_SENTINEL!r}, entityType 'proof', and one observation "
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
        if item.get("type") == "function_call" and item.get("name") == APPLE_MCP_PROOF_TOOL
    ]
    if not calls:
        raise SystemExit(f"No persisted {APPLE_MCP_PROOF_TOOL} function_call found")
    call = calls[-1]
    call_id = call.get("call_id")
    if not isinstance(call_id, str) or not call_id:
        raise SystemExit(f"Persisted {APPLE_MCP_PROOF_TOOL} call has invalid call_id: {call!r}")
    outputs = [
        item
        for item in run.items
        if item.get("type") == "function_call_output" and item.get("call_id") == call_id
    ]
    if not outputs:
        raise SystemExit(f"No persisted function_call_output found for call_id={call_id}")
    output_text = str(outputs[-1].get("output", ""))
    if APPLE_MCP_SENTINEL not in output_text or "error" in output_text.lower():
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prove Omnigent can wrap stock Codex for the Apple routerSelection path."
    )
    parser.add_argument(
        "--proof",
        choices=("graph", "tool-plane", "mcp-tools", "apple-mcp", "all"),
        default="graph",
        help=(
            "Proof gate to run. Defaults to the existing graph proof. "
            "'mcp-tools' is accepted as an alias for 'tool-plane'."
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
        needs_apple_mcp = proof in {"apple-mcp", "all"}
        mcp_manifest = None
        memory_file = None
        if proof in {"tool-plane", "apple-mcp", "all"}:
            mcp_manifest = prove_apple_mcp_manifest(agent_dir)
        if needs_apple_mcp:
            assert mcp_manifest is not None
            memory_file = agent_dir / "memory-proof.json"
            memory_file.write_text("{}", encoding="utf-8")
            write_agent_config(
                agent_dir,
                apple_mcp_memory=memory_mcp_config_from_manifest(mcp_manifest),
                memory_file=memory_file,
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
        if proof in {"apple-mcp", "all"}:
            assert mcp_manifest is not None
            print(f"static_apple_mcp_servers={','.join(sorted(mcp_manifest))}")
            print(f"converted_apple_mcp_server={APPLE_MCP_PROOF_SERVER}")
            print(f"converted_apple_mcp_memory_file={memory_file}")
            print("ASSERTION: Apple memory MCP config converted into Omnigent tools config")

        if args.skip_live:
            print("live_runner_proof=skipped")
            return 0

        assert codex_path is not None
        if proof in {"graph", "all"}:
            transcript = run_live_runner_proof(agent_dir, codex_path)
            print(f"graph_transcript_preview={transcript[:500]!r}")
            print(
                "ASSERTION: normal Omnigent run_prompt session/runner path "
                "emitted route block first"
            )
            print("ASSERTION: stock Codex read a bundled Apple reference through Omnigent")
        if proof in {"tool-plane", "all"}:
            tool_proof = run_live_tool_proof(agent_dir, codex_path)
            print(f"tool_session_id={tool_proof.session_id}")
            print(f"tool_call_id={tool_proof.call_id}")
            print(f"tool_transcript_preview={tool_proof.transcript[:500]!r}")
            print(
                "ASSERTION: stock Codex invoked Omnigent-exposed sys_os_read "
                "through dynamicTools"
            )
            print("ASSERTION: persisted session items include sys_os_read call and result")
        if proof in {"apple-mcp", "all"}:
            mcp_proof = run_live_apple_mcp_proof(agent_dir, codex_path)
            print(f"apple_mcp_session_id={mcp_proof.session_id}")
            print(f"apple_mcp_call_id={mcp_proof.call_id}")
            print(f"apple_mcp_output_preview={mcp_proof.output_preview!r}")
            print(f"apple_mcp_transcript_preview={mcp_proof.transcript[:500]!r}")
            print(
                "ASSERTION: stock Codex invoked Apple memory MCP through "
                "Omnigent-converted MCP config"
            )
            print(f"ASSERTION: persisted session items include {APPLE_MCP_PROOF_TOOL} result")
    return 0


if __name__ == "__main__":
    sys.exit(main())
