"""Stock Codex compatibility wrapper for Omnigent-owned route injection."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

from omnigent.adapters.stock_codex_compat import (
    ADAPTER_BRIDGE_DIR_ENV as STOCK_CODEX_COMPAT_ADAPTER_BRIDGE_DIR_ENV,
)
from omnigent.adapters.stock_codex_compat import (
    ADAPTER_MANIFEST_KIND,
)
from omnigent.stock_codex_adapter_runtime import build_stock_codex_adapter_bridge_service

STOCK_CODEX_PATH_ENV = "OMNIGENT_STOCK_CODEX_PATH"
ROUTE_PREFIX_ENV = "OMNIGENT_STOCK_CODEX_COMPAT_ROUTE_PREFIX"
WRAPPER_EVIDENCE_ENV = "OMNIGENT_STOCK_CODEX_COMPAT_WRAPPER_EVIDENCE"
ADAPTER_BIN_ENV = "OMNIGENT_STOCK_CODEX_COMPAT_ADAPTER_BIN"
ADAPTER_MANIFEST_ENV = "OMNIGENT_STOCK_CODEX_COMPAT_ADAPTER_MANIFEST"
ADAPTER_BRIDGE_DIR_ENV = STOCK_CODEX_COMPAT_ADAPTER_BRIDGE_DIR_ENV


@dataclass(frozen=True)
class WrapperEvidence:
    """Evidence produced by a wrapper run."""

    firstAgentMessageBefore: str
    routeInjected: bool
    routePresentAfter: bool
    stockCodexPath: str
    adapterBin: str | None = None
    adapterManifest: str | None = None
    adapterBridgeDir: str | None = None
    adapterToolNames: tuple[str, ...] | None = None


@dataclass(frozen=True)
class AdapterPackage:
    """Validated adapter package metadata for a wrapped stock Codex run."""

    adapter_bin: Path
    manifest_path: Path
    tool_names: tuple[str, ...]


def _require_object(value: object, *, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SystemExit(f"{context} must be a JSON object.")
    return value


def _require_string(value: object, *, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SystemExit(f"{context} must be a non-empty string.")
    return value


def _validate_adapter_command_name(command: str, *, tool_name: str) -> None:
    command_path = Path(command)
    if (
        command_path.is_absolute()
        or command_path.name != command
        or command in {".", ".."}
        or "/" in command
        or "\\" in command
    ):
        raise SystemExit(
            "Adapter manifest command must name an executable in adapter-bin; "
            f"tool={tool_name!r} command={command!r}"
        )


def _validate_adapter_parameters(value: object, *, tool_name: str) -> None:
    parameters = _require_object(
        value,
        context=f"Adapter manifest parameters for {tool_name!r}",
    )
    if parameters.get("type") != "object":
        raise SystemExit(
            "Adapter manifest parameters must use an object schema; "
            f"tool={tool_name!r}"
        )
    properties = _require_object(
        parameters.get("properties"),
        context=f"Adapter manifest parameters.properties for {tool_name!r}",
    )
    required = parameters.get("required")
    if not isinstance(required, list) or not all(
        isinstance(item, str) for item in required
    ):
        raise SystemExit(
            "Adapter manifest parameters.required must be a list of strings; "
            f"tool={tool_name!r}"
        )
    if parameters.get("additionalProperties") is not False:
        raise SystemExit(
            "Adapter manifest parameters must set additionalProperties=false; "
            f"tool={tool_name!r}"
        )
    for required_property in required:
        if required_property not in properties:
            raise SystemExit(
                "Adapter manifest required parameter is missing from properties; "
                f"tool={tool_name!r} parameter={required_property!r}"
            )
    for property_name, property_schema in properties.items():
        if not isinstance(property_name, str) or not property_name:
            raise SystemExit(
                "Adapter manifest parameter property names must be non-empty strings; "
                f"tool={tool_name!r}"
            )
        schema = _require_object(
            property_schema,
            context=(
                "Adapter manifest parameter schema for "
                f"{tool_name!r}.{property_name}"
            ),
        )
        _require_string(
            schema.get("type"),
            context=(
                "Adapter manifest parameter schema type for "
                f"{tool_name!r}.{property_name}"
            ),
        )


def validate_adapter_manifest(
    manifest_path: Path,
    adapter_bin: Path | None,
) -> AdapterPackage:
    """Validate an adapter manifest before stock Codex can see the adapter bin."""
    if adapter_bin is None:
        raise SystemExit("Adapter manifest requires --adapter-bin.")
    manifest_path = manifest_path.expanduser().resolve()
    adapter_bin = adapter_bin.expanduser().resolve()
    if not manifest_path.is_file():
        raise SystemExit(f"Adapter manifest not found: {manifest_path}")
    if not adapter_bin.is_dir():
        raise SystemExit(f"Adapter bin is not a directory: {adapter_bin}")
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(
            f"Adapter manifest is not valid JSON: {manifest_path}: {exc}"
        ) from exc
    manifest = _require_object(payload, context="Adapter manifest")
    if manifest.get("kind") != ADAPTER_MANIFEST_KIND:
        raise SystemExit(
            "Adapter manifest kind mismatch; "
            f"expected={ADAPTER_MANIFEST_KIND!r} actual={manifest.get('kind')!r}"
        )
    if manifest.get("version") != 1:
        raise SystemExit(
            f"Adapter manifest version must be 1; actual={manifest.get('version')!r}"
        )
    manifest_adapter_bin = manifest.get("adapterBin")
    if manifest_adapter_bin is not None:
        manifest_adapter_bin_path = _require_string(
            manifest_adapter_bin,
            context="Adapter manifest adapterBin",
        )
        if Path(manifest_adapter_bin_path).expanduser().resolve() != adapter_bin:
            raise SystemExit(
                "Adapter manifest adapterBin does not match --adapter-bin; "
                f"manifest_adapter_bin={manifest_adapter_bin_path!r} "
                f"adapter_bin={str(adapter_bin)!r}"
            )
    tools = manifest.get("tools")
    if not isinstance(tools, list) or not tools:
        raise SystemExit("Adapter manifest tools must be a non-empty list.")

    tool_names: list[str] = []
    seen_names: set[str] = set()
    seen_commands: set[str] = set()
    for index, raw_tool in enumerate(tools):
        tool = _require_object(
            raw_tool,
            context=f"Adapter manifest tool at index {index}",
        )
        name = _require_string(
            tool.get("name"),
            context=f"Adapter manifest tool name at index {index}",
        )
        command = _require_string(
            tool.get("command"),
            context=f"Adapter manifest command for {name!r}",
        )
        if name in seen_names:
            raise SystemExit(f"Adapter manifest contains duplicate tool name: {name}")
        if command in seen_commands:
            raise SystemExit(
                f"Adapter manifest contains duplicate adapter command: {command}"
            )
        _validate_adapter_command_name(command, tool_name=name)
        command_path = adapter_bin / command
        if not command_path.is_file() or not os.access(command_path, os.X_OK):
            raise SystemExit(
                "Adapter manifest command is not executable from adapter-bin; "
                f"tool={name!r} command_path={command_path}"
            )
        _validate_adapter_parameters(tool.get("parameters"), tool_name=name)
        seen_names.add(name)
        seen_commands.add(command)
        tool_names.append(name)

    return AdapterPackage(
        adapter_bin=adapter_bin,
        manifest_path=manifest_path,
        tool_names=tuple(tool_names),
    )


def stock_codex_env_with_adapter_bin(
    adapter_bin: Path | None,
    *,
    adapter_manifest: Path | None = None,
    adapter_bridge_dir: Path | None = None,
) -> dict[str, str]:
    """Return the stock Codex child environment with optional adapter-bin PATH injection."""
    env = os.environ.copy()
    if adapter_bridge_dir is not None:
        env[ADAPTER_BRIDGE_DIR_ENV] = str(adapter_bridge_dir)
    if adapter_bin is None:
        return env
    adapter_path = str(adapter_bin)
    existing_path = env.get("PATH", "")
    env[ADAPTER_BIN_ENV] = adapter_path
    env["PATH"] = (
        adapter_path
        if not existing_path
        else f"{adapter_path}{os.pathsep}{existing_path}"
    )
    if adapter_manifest is not None:
        env[ADAPTER_MANIFEST_ENV] = str(adapter_manifest)
    return env


def _resolve_optional_path(value: object) -> Path | None:
    if value is None:
        return None
    return Path(value).expanduser().resolve()


def prefix_first_agent_message(
    stdout: str,
    *,
    route_prefix: str,
    stock_codex_path: str,
) -> tuple[str, WrapperEvidence]:
    """Prefix route evidence on the first completed Codex agent message."""
    out_lines: list[str] = []
    route_injected = False
    route_present_after = False
    first_agent_before = ""
    for line in stdout.splitlines():
        if not line.strip():
            out_lines.append(line)
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            out_lines.append(line)
            continue
        if (
            not route_present_after
            and isinstance(event, dict)
            and event.get("type") == "item.completed"
        ):
            item = event.get("item")
            if isinstance(item, dict) and item.get("type") == "agent_message":
                text = item.get("text")
                if isinstance(text, str):
                    first_agent_before = text
                    if text.startswith(route_prefix):
                        route_present_after = True
                    else:
                        item["text"] = f"{route_prefix}\n\n{text}"
                        route_injected = True
                        route_present_after = True
        if isinstance(event, dict):
            out_lines.append(json.dumps(event, separators=(",", ":")))
        else:
            out_lines.append(line)
    transformed = "\n".join(out_lines)
    if out_lines:
        transformed += "\n"
    return transformed, WrapperEvidence(
        firstAgentMessageBefore=first_agent_before,
        routeInjected=route_injected,
        routePresentAfter=route_present_after,
        stockCodexPath=stock_codex_path,
    )


def run_wrapper(
    codex_args: Sequence[str],
    *,
    stock_codex_path: Path,
    route_prefix: str,
    evidence_path: Path | None,
    adapter_bin: Path | None = None,
    adapter_manifest: Path | None = None,
    adapter_bridge_dir: Path | None = None,
) -> int:
    """Run stock Codex and prefix route evidence on JSONL exec output."""
    adapter_tool_names: tuple[str, ...] | None = None
    if adapter_bridge_dir is not None:
        adapter_bridge_dir = adapter_bridge_dir.expanduser().resolve()
        if adapter_bridge_dir.exists() and not adapter_bridge_dir.is_dir():
            raise SystemExit(f"Adapter bridge dir is not a directory: {adapter_bridge_dir}")
    if adapter_manifest is not None:
        adapter_package = validate_adapter_manifest(adapter_manifest, adapter_bin)
        adapter_bin = adapter_package.adapter_bin
        adapter_manifest = adapter_package.manifest_path
        adapter_tool_names = adapter_package.tool_names
    elif adapter_bin is not None:
        adapter_bin = adapter_bin.expanduser().resolve()
        if not adapter_bin.is_dir():
            raise SystemExit(f"Adapter bin is not a directory: {adapter_bin}")

    bridge_service = (
        build_stock_codex_adapter_bridge_service(
            adapter_bridge_dir,
            adapter_manifest=adapter_manifest,
        )
        if adapter_bridge_dir is not None
        else None
    )
    bridge_context = bridge_service if bridge_service is not None else contextlib.nullcontext()
    with bridge_context:
        completed = subprocess.run(
            [str(stock_codex_path), *codex_args],
            check=False,
            capture_output=True,
            text=True,
            env=stock_codex_env_with_adapter_bin(
                adapter_bin,
                adapter_manifest=adapter_manifest,
                adapter_bridge_dir=adapter_bridge_dir,
            ),
            stdin=sys.stdin,
        )
    stdout, evidence = prefix_first_agent_message(
        completed.stdout,
        route_prefix=route_prefix,
        stock_codex_path=str(stock_codex_path),
    )
    if adapter_bin is not None:
        evidence = replace(evidence, adapterBin=str(adapter_bin))
    if adapter_manifest is not None:
        evidence = replace(
            evidence,
            adapterManifest=str(adapter_manifest),
            adapterToolNames=adapter_tool_names,
        )
    if adapter_bridge_dir is not None:
        evidence = replace(evidence, adapterBridgeDir=str(adapter_bridge_dir))
    if stdout:
        sys.stdout.write(stdout)
    if completed.stderr:
        sys.stderr.write(completed.stderr)
    if evidence_path is not None:
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        evidence_path.write_text(
            json.dumps(asdict(evidence), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return completed.returncode


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse wrapper arguments before the stock Codex passthrough args."""
    parser = argparse.ArgumentParser(
        description="Run stock Codex behind an Omnigent compatibility wrapper."
    )
    parser.add_argument(
        "--stock-codex-path",
        type=Path,
        default=os.environ.get(STOCK_CODEX_PATH_ENV),
        help=f"Stock Codex binary path. Defaults to ${STOCK_CODEX_PATH_ENV}.",
    )
    parser.add_argument(
        "--route-prefix",
        default=os.environ.get(ROUTE_PREFIX_ENV),
        help=f"Route prefix to inject. Defaults to ${ROUTE_PREFIX_ENV}.",
    )
    parser.add_argument(
        "--evidence-path",
        type=Path,
        default=os.environ.get(WRAPPER_EVIDENCE_ENV),
        help=f"Optional JSON evidence path. Defaults to ${WRAPPER_EVIDENCE_ENV}.",
    )
    parser.add_argument(
        "--adapter-bin",
        type=Path,
        default=os.environ.get(ADAPTER_BIN_ENV),
        help=(
            "Optional directory containing Omnigent adapter executables to prepend "
            f"to PATH. Defaults to ${ADAPTER_BIN_ENV}."
        ),
    )
    parser.add_argument(
        "--adapter-manifest",
        type=Path,
        default=os.environ.get(ADAPTER_MANIFEST_ENV),
        help=(
            "Optional adapter package manifest to validate before launching stock "
            f"Codex. Defaults to ${ADAPTER_MANIFEST_ENV}."
        ),
    )
    parser.add_argument(
        "--adapter-bridge-dir",
        type=Path,
        default=os.environ.get(ADAPTER_BRIDGE_DIR_ENV),
        help=(
            "Optional wrapper-owned file bridge directory for adapter commands. "
            f"Defaults to ${ADAPTER_BRIDGE_DIR_ENV}."
        ),
    )
    parser.add_argument("codex_args", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if args.codex_args[:1] == ["--"]:
        args.codex_args = args.codex_args[1:]
    return args


def main(argv: Sequence[str] | None = None) -> int:
    """Console entrypoint for the stock Codex compatibility wrapper."""
    args = parse_args(argv)
    if args.stock_codex_path is None:
        raise SystemExit(f"Missing --stock-codex-path or ${STOCK_CODEX_PATH_ENV}.")
    if not args.route_prefix:
        raise SystemExit(f"Missing --route-prefix or ${ROUTE_PREFIX_ENV}.")
    if not args.codex_args:
        raise SystemExit("Missing stock Codex arguments after --.")
    stock_codex_path = _resolve_optional_path(args.stock_codex_path)
    if stock_codex_path is None:
        raise SystemExit(f"Missing --stock-codex-path or ${STOCK_CODEX_PATH_ENV}.")
    return run_wrapper(
        args.codex_args,
        stock_codex_path=stock_codex_path,
        route_prefix=str(args.route_prefix),
        evidence_path=_resolve_optional_path(args.evidence_path),
        adapter_bin=_resolve_optional_path(args.adapter_bin),
        adapter_manifest=_resolve_optional_path(args.adapter_manifest),
        adapter_bridge_dir=_resolve_optional_path(args.adapter_bridge_dir),
    )


if __name__ == "__main__":
    raise SystemExit(main())
