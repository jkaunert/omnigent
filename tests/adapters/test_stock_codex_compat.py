"""Tests for stock Codex compatibility adapter package generation."""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

import pytest

from omnigent import stock_codex_compat_wrapper
from omnigent.adapters.stock_codex_compat import (
    ADAPTER_BRIDGE_DIR_ENV,
    ADAPTER_MANIFEST_KIND,
    StockCodexCompatAdapterCommandSpec,
    StockCodexCompatAdapterToolSpec,
    build_stock_codex_compat_adapter_command_source,
    build_stock_codex_compat_adapter_manifest,
    build_stock_codex_compat_file_bridge_command_source,
    write_stock_codex_compat_adapter_package,
)


def _route_tool_spec() -> StockCodexCompatAdapterToolSpec:
    return StockCodexCompatAdapterToolSpec(
        name="omnigent-wrapper-route-adapter-probe",
        argument="route-selection-proof",
        output_sentinel="OMNIGENT_ADAPTER_ARBITRATION_ROUTE_SENTINEL_88",
        capability="route-selection",
        description="Return deterministic route-selection adapter evidence.",
    )


def _release_tool_spec() -> StockCodexCompatAdapterToolSpec:
    return StockCodexCompatAdapterToolSpec(
        name="omnigent-wrapper-release-adapter-probe",
        argument="release-notes-proof",
        output_sentinel="OMNIGENT_ADAPTER_ARBITRATION_RELEASE_SENTINEL_19",
        capability="release-notes",
        description="Return deterministic release-notes adapter evidence.",
    )


def test_generated_manifest_uses_closed_object_schemas(tmp_path: Path) -> None:
    specs = (_route_tool_spec(), _release_tool_spec())
    manifest = build_stock_codex_compat_adapter_manifest(tmp_path / "bin", specs)

    assert manifest["kind"] == ADAPTER_MANIFEST_KIND
    assert manifest["version"] == 1
    assert [tool["name"] for tool in manifest["tools"]] == [spec.name for spec in specs]
    assert all(
        tool["parameters"]["additionalProperties"] is False
        for tool in manifest["tools"]
    )
    assert manifest["tools"][0]["parameters"]["properties"]["message"]["const"] == (
        "route-selection-proof"
    )


def test_generated_package_validates_with_stock_codex_wrapper(tmp_path: Path) -> None:
    specs = (_route_tool_spec(), _release_tool_spec())

    package = write_stock_codex_compat_adapter_package(tmp_path / "adapter-package", specs)
    validated = stock_codex_compat_wrapper.validate_adapter_manifest(
        package.manifest_path,
        package.adapter_bin,
    )

    assert package.tool_names == tuple(spec.name for spec in specs)
    assert validated.tool_names == package.tool_names


def test_wrapper_rejects_manifest_adapter_bin_mismatch(tmp_path: Path) -> None:
    specs = (_route_tool_spec(),)
    package = write_stock_codex_compat_adapter_package(tmp_path / "adapter-package", specs)
    other_bin = tmp_path / "other-bin"
    other_bin.mkdir()

    with pytest.raises(SystemExit, match="adapterBin does not match"):
        stock_codex_compat_wrapper.validate_adapter_manifest(
            package.manifest_path,
            other_bin,
        )


def test_generated_command_emits_selected_payload(tmp_path: Path) -> None:
    spec = _route_tool_spec()
    package = write_stock_codex_compat_adapter_package(tmp_path / "adapter-package", (spec,))
    command_path = package.adapter_bin / spec.name

    completed = subprocess.run(
        [str(command_path), "--message", spec.argument],
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(completed.stdout)
    assert payload == {
        "source": "omnigent-wrapper-adapter",
        "tool": spec.name,
        "capability": spec.capability,
        "sentinel": spec.output_sentinel,
        "message": spec.argument,
    }


def test_generated_command_rejects_unexpected_arguments(tmp_path: Path) -> None:
    spec = _route_tool_spec()
    package = write_stock_codex_compat_adapter_package(tmp_path / "adapter-package", (spec,))
    command_path = package.adapter_bin / spec.name

    completed = subprocess.run(
        [str(command_path), "--message", "wrong-proof"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 64
    payload = json.loads(completed.stdout)
    assert payload["error"] == "unexpected arguments"
    assert payload["tool"] == spec.name


def test_file_bridge_command_round_trips_request_response(tmp_path: Path) -> None:
    bridge_dir = tmp_path / "bridge"
    requests_dir = bridge_dir / "requests"
    responses_dir = bridge_dir / "responses"
    requests_dir.mkdir(parents=True)
    responses_dir.mkdir(parents=True)
    spec = StockCodexCompatAdapterCommandSpec(
        name="fetch_apple_docs",
        capability="apple-docs",
        description="Fetch Apple documentation through a file bridge.",
        parameters={
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
            "additionalProperties": False,
        },
        command_source=build_stock_codex_compat_file_bridge_command_source(
            "fetch_apple_docs",
            ("url",),
            timeout_seconds=5,
        ),
    )
    package = write_stock_codex_compat_adapter_package(tmp_path / "adapter-package", (spec,))
    process = subprocess.Popen(
        [
            str(package.adapter_bin / spec.name),
            "--url",
            "https://developer.apple.com/documentation/swift/string",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env={**os.environ, ADAPTER_BRIDGE_DIR_ENV: str(bridge_dir)},
    )
    deadline = time.monotonic() + 5
    request_path: Path | None = None
    while time.monotonic() < deadline:
        request_paths = sorted(requests_dir.glob("*.json"))
        if request_paths:
            request_path = request_paths[0]
            break
        time.sleep(0.05)
    assert request_path is not None
    request = json.loads(request_path.read_text(encoding="utf-8"))
    assert request["tool"] == "fetch_apple_docs"
    assert request["arguments"] == {
        "url": "https://developer.apple.com/documentation/swift/string"
    }
    response_path = responses_dir / f"{request['id']}.json"
    response_tmp_path = responses_dir / f"{request['id']}.tmp"
    response_tmp_path.write_text(
        json.dumps(
            {
                "status": "ok",
                "stdout": "title: String\n",
                "stderr": "",
                "exitCode": 0,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    os.replace(response_tmp_path, response_path)

    stdout, stderr = process.communicate(timeout=5)

    assert process.returncode == 0
    assert stdout == "title: String\n"
    assert stderr == ""


def test_file_bridge_command_emits_error_diagnostic(tmp_path: Path) -> None:
    bridge_dir = tmp_path / "bridge"
    requests_dir = bridge_dir / "requests"
    responses_dir = bridge_dir / "responses"
    requests_dir.mkdir(parents=True)
    responses_dir.mkdir(parents=True)
    spec = StockCodexCompatAdapterCommandSpec(
        name="fetch_apple_docs",
        capability="apple-docs",
        description="Fetch Apple documentation through a file bridge.",
        parameters={
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
            "additionalProperties": False,
        },
        command_source=build_stock_codex_compat_file_bridge_command_source(
            "fetch_apple_docs",
            ("url",),
            timeout_seconds=5,
        ),
    )
    package = write_stock_codex_compat_adapter_package(tmp_path / "adapter-package", (spec,))
    process = subprocess.Popen(
        [
            str(package.adapter_bin / spec.name),
            "--url",
            "https://example.com/not-apple",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env={**os.environ, ADAPTER_BRIDGE_DIR_ENV: str(bridge_dir)},
    )
    deadline = time.monotonic() + 5
    request_path: Path | None = None
    while time.monotonic() < deadline:
        request_paths = sorted(requests_dir.glob("*.json"))
        if request_paths:
            request_path = request_paths[0]
            break
        time.sleep(0.05)
    assert request_path is not None
    request = json.loads(request_path.read_text(encoding="utf-8"))
    response_path = responses_dir / f"{request['id']}.json"
    response_tmp_path = responses_dir / f"{request['id']}.tmp"
    response_tmp_path.write_text(
        json.dumps(
            {
                "status": "error",
                "stdout": "",
                "stderr": "Error: url must be developer.apple.com\n",
                "exitCode": 64,
                "diagnostics": {
                    "bridge": "stock-codex-file-bridge",
                    "requestId": request["id"],
                    "tool": "fetch_apple_docs",
                    "startedAt": "2026-07-07T00:00:00Z",
                    "completedAt": "2026-07-07T00:00:01Z",
                    "durationMs": 1,
                },
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    os.replace(response_tmp_path, response_path)

    stdout, stderr = process.communicate(timeout=5)
    diagnostic_lines = [
        line
        for line in stderr.splitlines()
        if line.startswith("OMNIGENT_ADAPTER_BRIDGE_DIAGNOSTIC ")
    ]
    diagnostic = json.loads(
        diagnostic_lines[0].removeprefix("OMNIGENT_ADAPTER_BRIDGE_DIAGNOSTIC ")
    )

    assert process.returncode == 64
    assert stdout == ""
    assert "url must be developer.apple.com" in stderr
    assert diagnostic["source"] == "omnigent-stock-codex-file-bridge"
    assert diagnostic["status"] == "error"
    assert diagnostic["exitCode"] == 64
    assert diagnostic["diagnostics"]["requestId"] == request["id"]
    assert diagnostic["diagnostics"]["tool"] == "fetch_apple_docs"


def test_wrapper_env_records_adapter_bridge_dir(tmp_path: Path) -> None:
    adapter_bin = tmp_path / "adapter-bin"
    adapter_bridge_dir = tmp_path / "adapter-bridge"
    adapter_bin.mkdir()
    adapter_bridge_dir.mkdir()

    env = stock_codex_compat_wrapper.stock_codex_env_with_adapter_bin(
        adapter_bin,
        adapter_bridge_dir=adapter_bridge_dir,
    )

    assert env[stock_codex_compat_wrapper.ADAPTER_BRIDGE_DIR_ENV] == str(
        adapter_bridge_dir
    )
    assert env["PATH"].split(os.pathsep)[0] == str(adapter_bin)


def test_duplicate_tool_names_are_rejected() -> None:
    spec = _route_tool_spec()

    with pytest.raises(ValueError, match="duplicate adapter tool name"):
        build_stock_codex_compat_adapter_manifest(Path("/tmp/adapter-bin"), (spec, spec))


def test_command_source_requires_valid_tool_name() -> None:
    spec = StockCodexCompatAdapterToolSpec(
        name="../bad",
        argument="route-selection-proof",
        output_sentinel="OMNIGENT_ADAPTER_ARBITRATION_ROUTE_SENTINEL_88",
        capability="route-selection",
        description="Return deterministic route-selection adapter evidence.",
    )

    with pytest.raises(ValueError, match="adapter tool name is invalid"):
        build_stock_codex_compat_adapter_command_source(spec)
