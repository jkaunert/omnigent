"""Stock Codex compatibility adapter package generation."""

from __future__ import annotations

import json
import shlex
import textwrap
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from omnigent.tools.base import is_valid_tool_name

ADAPTER_MANIFEST_KIND = "omnigent-stock-codex-compat-adapter-package"
ADAPTER_BRIDGE_DIR_ENV = "OMNIGENT_STOCK_CODEX_COMPAT_ADAPTER_BRIDGE_DIR"


@dataclass(frozen=True)
class StockCodexCompatAdapterToolSpec:
    """Metadata for one generated stock-Codex-compatible adapter command."""

    name: str
    argument: str
    output_sentinel: str
    capability: str
    description: str
    argument_name: str = "message"

    def validate(self) -> None:
        """Validate fields before writing shell or manifest content."""
        if not is_valid_tool_name(self.name):
            raise ValueError(f"adapter tool name is invalid: {self.name!r}")
        for field_name, value in (
            ("argument", self.argument),
            ("output_sentinel", self.output_sentinel),
            ("capability", self.capability),
            ("description", self.description),
            ("argument_name", self.argument_name),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"adapter {field_name} must be a non-empty string")
            if "\n" in value or "\r" in value:
                raise ValueError(f"adapter {field_name} must be single-line")
        if not is_valid_tool_name(self.argument_name):
            raise ValueError(f"adapter argument_name is invalid: {self.argument_name!r}")

    def parameter_schema(self) -> dict[str, Any]:
        """Return the closed JSON schema for this adapter command."""
        self.validate()
        return {
            "type": "object",
            "properties": {
                self.argument_name: {
                    "type": "string",
                    "const": self.argument,
                    "description": "Fixed proof message for adapter validation.",
                }
            },
            "required": [self.argument_name],
            "additionalProperties": False,
        }

    def manifest_entry(self) -> dict[str, Any]:
        """Return one adapter manifest tool entry."""
        self.validate()
        return {
            "name": self.name,
            "command": self.name,
            "capability": self.capability,
            "description": self.description,
            "parameters": self.parameter_schema(),
        }

    def success_payload(self) -> dict[str, str]:
        """Return the deterministic JSON payload emitted by the generated command."""
        self.validate()
        return {
            "source": "omnigent-wrapper-adapter",
            "tool": self.name,
            "capability": self.capability,
            "sentinel": self.output_sentinel,
            self.argument_name: self.argument,
        }


@dataclass(frozen=True)
class StockCodexCompatAdapterCommandSpec:
    """Metadata and source for one real workflow adapter command."""

    name: str
    capability: str
    description: str
    parameters: Mapping[str, Any]
    command_source: str
    command: str | None = None

    def validate(self) -> None:
        """Validate fields before writing shell or manifest content."""
        if not is_valid_tool_name(self.name):
            raise ValueError(f"adapter tool name is invalid: {self.name!r}")
        for field_name, value in (
            ("capability", self.capability),
            ("description", self.description),
            ("command_source", self.command_source),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"adapter {field_name} must be a non-empty string")
        if "\0" in self.command_source:
            raise ValueError("adapter command_source must not contain NUL bytes")
        if not self.command_source.startswith("#!"):
            raise ValueError("adapter command_source must start with a shebang")
        if self.command is not None:
            _validate_manifest_command_name(self.command, tool_name=self.name)
        _validate_parameter_schema(self.parameters, tool_name=self.name)

    def parameter_schema(self) -> dict[str, Any]:
        """Return the closed JSON schema for this adapter command."""
        self.validate()
        return dict(self.parameters)

    def manifest_entry(self) -> dict[str, Any]:
        """Return one adapter manifest tool entry."""
        self.validate()
        return {
            "name": self.name,
            "command": self.command or self.name,
            "capability": self.capability,
            "description": self.description,
            "parameters": self.parameter_schema(),
        }


@dataclass(frozen=True)
class StockCodexCompatAdapterPackage:
    """Paths and tool names produced by a generated adapter package."""

    root: Path
    adapter_bin: Path
    manifest_path: Path
    tool_names: tuple[str, ...]


StockCodexCompatAdapterSpec = (
    StockCodexCompatAdapterToolSpec | StockCodexCompatAdapterCommandSpec
)


def build_stock_codex_compat_adapter_manifest(
    adapter_bin: Path,
    tool_specs: tuple[StockCodexCompatAdapterSpec, ...],
) -> dict[str, Any]:
    """Build a validated stock-Codex adapter package manifest."""
    _validate_tool_specs(tool_specs)
    return {
        "kind": ADAPTER_MANIFEST_KIND,
        "version": 1,
        "adapterBin": str(adapter_bin),
        "tools": [spec.manifest_entry() for spec in tool_specs],
    }


def build_stock_codex_compat_adapter_command_source(
    spec: StockCodexCompatAdapterToolSpec,
) -> str:
    """Build the executable shell source for one stock-Codex adapter command."""
    spec.validate()
    success_payload = json.dumps(spec.success_payload(), separators=(",", ":"))
    error_payload = json.dumps(
        {
            "error": "unexpected arguments",
            "tool": spec.name,
            "expected": {
                spec.argument_name: spec.argument,
            },
        },
        separators=(",", ":"),
    )
    quoted_argument_name = shlex.quote(f"--{spec.argument_name}")
    quoted_argument = shlex.quote(spec.argument)
    quoted_error_payload = shlex.quote(error_payload)
    quoted_success_payload = shlex.quote(success_payload)
    return (
        "#!/bin/sh\n"
        f"if [ \"${{1:-}}\" != {quoted_argument_name} ] || "
        f"[ \"${{2:-}}\" != {quoted_argument} ]; then\n"
        f"  printf '%s\\n' {quoted_error_payload}\n"
        "  exit 64\n"
        "fi\n"
        f"printf '%s\\n' {quoted_success_payload}\n"
    )


def build_stock_codex_compat_file_bridge_command_source(
    tool_name: str,
    argument_names: tuple[str, ...],
    *,
    bridge_dir_env: str = ADAPTER_BRIDGE_DIR_ENV,
    timeout_seconds: int = 60,
) -> str:
    """Build a command that relays adapter calls through a wrapper-owned file bridge."""
    if not is_valid_tool_name(tool_name):
        raise ValueError(f"adapter tool name is invalid: {tool_name!r}")
    if not argument_names:
        raise ValueError("adapter bridge command requires at least one argument")
    for argument_name in argument_names:
        if not is_valid_tool_name(argument_name):
            raise ValueError(f"adapter argument name is invalid: {argument_name!r}")
    if not isinstance(bridge_dir_env, str) or not bridge_dir_env.strip():
        raise ValueError("bridge_dir_env must be a non-empty string")
    if "\n" in bridge_dir_env or "\r" in bridge_dir_env or "\0" in bridge_dir_env:
        raise ValueError("bridge_dir_env must be a single-line environment variable name")
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be greater than zero")
    return textwrap.dedent(
        f'''\
        #!/usr/bin/env python3
        """Stock Codex adapter file bridge command generated by Omnigent."""

        from __future__ import annotations

        import argparse
        import json
        import os
        import sys
        import time
        import uuid
        from pathlib import Path

        _TOOL_NAME = {tool_name!r}
        _ARGUMENT_NAMES = {argument_names!r}
        _BRIDGE_DIR_ENV = {bridge_dir_env!r}
        _TIMEOUT_SECONDS = {timeout_seconds!r}


        def _write_stream(value: object, stream: object) -> None:
            if isinstance(value, str) and value:
                stream.write(value)
                if not value.endswith("\\n"):
                    stream.write("\\n")


        def _write_diagnostic(response: dict[str, object]) -> None:
            if response.get("status") != "error":
                return
            diagnostics = response.get("diagnostics")
            payload = {{
                "source": "omnigent-stock-codex-file-bridge",
                "status": response.get("status"),
                "exitCode": response.get("exitCode"),
                "diagnostics": diagnostics if isinstance(diagnostics, dict) else {{}},
            }}
            print(
                "OMNIGENT_ADAPTER_BRIDGE_DIAGNOSTIC "
                + json.dumps(payload, sort_keys=True),
                file=sys.stderr,
            )


        def main() -> int:
            bridge_dir_value = os.environ.get(_BRIDGE_DIR_ENV)
            if not bridge_dir_value:
                print(f"Error: missing ${{_BRIDGE_DIR_ENV}}.", file=sys.stderr)
                return 72
            bridge_dir = Path(bridge_dir_value)
            requests_dir = bridge_dir / "requests"
            responses_dir = bridge_dir / "responses"
            if not requests_dir.is_dir() or not responses_dir.is_dir():
                print(
                    f"Error: adapter bridge is not initialized at {{bridge_dir}}.",
                    file=sys.stderr,
                )
                return 72

            parser = argparse.ArgumentParser(description=f"Relay {{_TOOL_NAME}} through Omnigent.")
            for argument_name in _ARGUMENT_NAMES:
                parser.add_argument(f"--{{argument_name}}", required=True)
            args = parser.parse_args()

            request_id = f"{{os.getpid()}}-{{uuid.uuid4().hex}}"
            payload = {{
                "id": request_id,
                "tool": _TOOL_NAME,
                "arguments": vars(args),
            }}
            request_path = requests_dir / f"{{request_id}}.json"
            request_tmp_path = requests_dir / f"{{request_id}}.tmp"
            response_path = responses_dir / f"{{request_id}}.json"
            request_tmp_path.write_text(
                json.dumps(payload, sort_keys=True) + "\\n",
                encoding="utf-8",
            )
            os.replace(request_tmp_path, request_path)

            deadline = time.monotonic() + _TIMEOUT_SECONDS
            while time.monotonic() < deadline:
                if response_path.exists():
                    try:
                        response = json.loads(response_path.read_text(encoding="utf-8"))
                    except json.JSONDecodeError as exc:
                        print(f"Error: invalid adapter bridge response: {{exc}}", file=sys.stderr)
                        return 70
                    if not isinstance(response, dict):
                        print("Error: adapter bridge response must be an object.", file=sys.stderr)
                        return 70
                    status = response.get("status")
                    if status not in ("ok", "error"):
                        print(
                            f"Error: adapter bridge response has invalid status: {{status!r}}.",
                            file=sys.stderr,
                        )
                        return 70
                    _write_stream(response.get("stdout"), sys.stdout)
                    _write_stream(response.get("stderr"), sys.stderr)
                    _write_diagnostic(response)
                    exit_code = response.get("exitCode")
                    if not isinstance(exit_code, int):
                        print(
                            "Error: adapter bridge response omitted integer exitCode.",
                            file=sys.stderr,
                        )
                        return 70
                    return exit_code
                time.sleep(0.05)

            print(
                f"Error: adapter bridge timed out after {{_TIMEOUT_SECONDS}} seconds.",
                file=sys.stderr,
            )
            return 75


        if __name__ == "__main__":
            raise SystemExit(main())
        '''
    )


def write_stock_codex_compat_adapter_command(
    adapter_bin: Path,
    spec: StockCodexCompatAdapterSpec,
) -> Path:
    """Write one generated adapter executable under ``adapter_bin``."""
    spec.validate()
    adapter_bin.mkdir(parents=True, exist_ok=True)
    command_name = (
        (spec.command or spec.name)
        if isinstance(spec, StockCodexCompatAdapterCommandSpec)
        else spec.name
    )
    command_source = (
        spec.command_source
        if isinstance(spec, StockCodexCompatAdapterCommandSpec)
        else build_stock_codex_compat_adapter_command_source(spec)
    )
    command_path = adapter_bin / command_name
    command_path.write_text(command_source, encoding="utf-8")
    command_path.chmod(0o755)
    return command_path


def write_stock_codex_compat_adapter_manifest(
    adapter_package: Path,
    adapter_bin: Path,
    tool_specs: tuple[StockCodexCompatAdapterSpec, ...],
) -> Path:
    """Write the adapter package manifest only."""
    manifest_path = adapter_package / "adapter-manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = build_stock_codex_compat_adapter_manifest(adapter_bin, tool_specs)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest_path


def write_stock_codex_compat_adapter_package(
    adapter_package: Path,
    tool_specs: tuple[StockCodexCompatAdapterSpec, ...],
) -> StockCodexCompatAdapterPackage:
    """Write a complete stock-Codex adapter package."""
    _validate_tool_specs(tool_specs)
    adapter_bin = adapter_package / "bin"
    adapter_bin.mkdir(parents=True, exist_ok=True)
    for spec in tool_specs:
        write_stock_codex_compat_adapter_command(adapter_bin, spec)
    manifest_path = write_stock_codex_compat_adapter_manifest(
        adapter_package,
        adapter_bin,
        tool_specs,
    )
    return StockCodexCompatAdapterPackage(
        root=adapter_package,
        adapter_bin=adapter_bin,
        manifest_path=manifest_path,
        tool_names=tuple(spec.name for spec in tool_specs),
    )


def _validate_tool_specs(
    tool_specs: tuple[StockCodexCompatAdapterSpec, ...],
) -> None:
    if not tool_specs:
        raise ValueError("adapter package requires at least one tool")
    seen_names: set[str] = set()
    for spec in tool_specs:
        spec.validate()
        if spec.name in seen_names:
            raise ValueError(f"duplicate adapter tool name: {spec.name}")
        seen_names.add(spec.name)


def _validate_manifest_command_name(command: str, *, tool_name: str) -> None:
    command_path = Path(command)
    if (
        command_path.is_absolute()
        or command_path.name != command
        or command in {".", ".."}
        or "/" in command
        or "\\" in command
    ):
        raise ValueError(
            "adapter command must name an executable in adapter-bin; "
            f"tool={tool_name!r} command={command!r}"
        )


def _validate_parameter_schema(parameters: Mapping[str, Any], *, tool_name: str) -> None:
    if parameters.get("type") != "object":
        raise ValueError(f"adapter parameters must use an object schema: {tool_name!r}")
    properties = parameters.get("properties")
    if not isinstance(properties, Mapping):
        raise ValueError(
            f"adapter parameters.properties must be an object: {tool_name!r}"
        )
    required = parameters.get("required")
    if not isinstance(required, list) or not all(isinstance(item, str) for item in required):
        raise ValueError(
            f"adapter parameters.required must be a list of strings: {tool_name!r}"
        )
    if parameters.get("additionalProperties") is not False:
        raise ValueError(
            f"adapter parameters must set additionalProperties=false: {tool_name!r}"
        )
    for required_property in required:
        if required_property not in properties:
            raise ValueError(
                "adapter required parameter is missing from properties: "
                f"tool={tool_name!r} parameter={required_property!r}"
            )
    for property_name, property_schema in properties.items():
        if not isinstance(property_name, str) or not property_name:
            raise ValueError(
                f"adapter parameter property names must be non-empty strings: {tool_name!r}"
            )
        if not isinstance(property_schema, Mapping):
            raise ValueError(
                "adapter parameter property schemas must be objects: "
                f"tool={tool_name!r} parameter={property_name!r}"
            )
        property_type = property_schema.get("type")
        if not isinstance(property_type, str) or not property_type:
            raise ValueError(
                "adapter parameter property schemas must declare a type: "
                f"tool={tool_name!r} parameter={property_name!r}"
            )
