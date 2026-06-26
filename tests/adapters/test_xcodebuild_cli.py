"""Tests for the XcodeBuildMCP CLI adapter policy."""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from omnigent.adapters.xcodebuild_cli import (
    XCODEBUILD_CLI_TOOL_NAME,
    XCODEBUILDMCP_CLI_COMMAND,
    XcodeBuildCliAdapterPolicy,
    build_xcodebuildmcp_simulator_build_run_tool_source,
    write_xcodebuildmcp_simulator_build_run_tool,
)


def _load_module(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "generated_xcodebuildmcp_simulator_build_run",
        path,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_policy_installs_when_xcodebuild_mcp_server_is_present() -> None:
    policy = XcodeBuildCliAdapterPolicy()

    decision = policy.decide_for_mcp_servers({"XcodeBuildMCP": {"command": "xcodebuildmcp"}})

    assert decision.install is True
    assert "XcodeBuildMCP" in decision.reason
    assert "existing MCP config is unchanged" in decision.reason


def test_policy_does_not_install_when_xcodebuild_mcp_server_is_absent() -> None:
    policy = XcodeBuildCliAdapterPolicy()

    decision = policy.decide_for_mcp_servers({"memory": {"command": "npx"}})

    assert decision.install is False
    assert "absent" in decision.reason


def test_policy_builds_cli_command_for_valid_project(tmp_path: Path) -> None:
    project_path = tmp_path / "Demo.xcodeproj"
    project_path.mkdir()
    derived_data_path = tmp_path / "DerivedData"
    policy = XcodeBuildCliAdapterPolicy(
        allowed_derived_data_roots=(str(tmp_path),),
    )

    command = policy.command_for_build_run(
        project_path=str(project_path),
        scheme="Demo",
        configuration="Debug",
        simulator_name="iPhone 17",
        derived_data_path=str(derived_data_path),
        extra_args=["-quiet"],
    )

    assert command[:3] == [*XCODEBUILDMCP_CLI_COMMAND]
    assert command[-2:] == ["--output", "text"]
    payload = json.loads(command[command.index("--json") + 1])
    assert payload == {
        "projectPath": str(project_path),
        "scheme": "Demo",
        "configuration": "Debug",
        "simulatorName": "iPhone 17",
        "useLatestOS": True,
        "derivedDataPath": str(derived_data_path),
        "extraArgs": ["-quiet"],
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("project_path", "relative/Demo.xcodeproj"),
        ("project_path", "/tmp/Demo.xcworkspace"),
        ("scheme", ""),
        ("configuration", ""),
        ("simulator_name", "Vision Pro"),
        ("derived_data_path", "relative/DerivedData"),
    ],
)
def test_policy_rejects_invalid_build_run_arguments(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    project_path = tmp_path / "Demo.xcodeproj"
    project_path.mkdir()
    policy = XcodeBuildCliAdapterPolicy(allowed_derived_data_roots=(str(tmp_path),))
    kwargs: dict[str, object] = {
        "project_path": str(project_path),
        "scheme": "Demo",
        "configuration": "Debug",
        "simulator_name": "iPhone 17",
        "derived_data_path": str(tmp_path / "DerivedData"),
        "extra_args": ["-quiet"],
    }
    kwargs[field] = value

    with pytest.raises(ValueError):
        policy.command_for_build_run(**kwargs)  # type: ignore[arg-type]


def test_policy_rejects_unexpected_extra_args(tmp_path: Path) -> None:
    project_path = tmp_path / "Demo.xcodeproj"
    project_path.mkdir()
    policy = XcodeBuildCliAdapterPolicy(allowed_derived_data_roots=(str(tmp_path),))

    with pytest.raises(ValueError):
        policy.command_for_build_run(
            project_path=str(project_path),
            scheme="Demo",
            configuration="Debug",
            simulator_name="iPhone 17",
            derived_data_path=str(tmp_path / "DerivedData"),
            extra_args=["-quiet", "-derivedDataPath", "/tmp/other"],
        )


def test_generated_tool_source_names_expected_tool() -> None:
    source = build_xcodebuildmcp_simulator_build_run_tool_source()

    assert f"def {XCODEBUILD_CLI_TOOL_NAME}(" in source
    assert "xcodebuildmcp" in source
    assert "build-and-run" in source


def test_generated_tool_validates_arguments_before_calling_cli(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_path = tmp_path / "Demo.xcodeproj"
    project_path.mkdir()
    derived_data_path = tmp_path / "DerivedData"
    policy = XcodeBuildCliAdapterPolicy(allowed_derived_data_roots=(str(tmp_path),))
    tool_path = write_xcodebuildmcp_simulator_build_run_tool(tmp_path, policy=policy)
    module = _load_module(tool_path)
    calls: list[tuple[list[str], dict[str, Any]]] = []

    def fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append((cmd, kwargs))
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout=(
                "Build succeeded\n"
                "Build & Run complete\n"
                "Bundle ID: ai.omnigent.ios\n"
            ),
            stderr="",
        )

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    invalid_result = module.xcodebuildmcp_simulator_build_run(
        str(project_path),
        "Demo",
        "Debug",
        "Vision Pro",
        str(derived_data_path),
        ["-quiet"],
    )
    valid_result = module.xcodebuildmcp_simulator_build_run(
        str(project_path),
        "Demo",
        "Debug",
        "iPhone 17",
        str(derived_data_path),
        ["-quiet"],
    )

    assert invalid_result.startswith("Error: simulator_name must start with")
    assert calls == [
        (
            [
                *XCODEBUILDMCP_CLI_COMMAND,
                "--json",
                json.dumps(
                    {
                        "projectPath": str(project_path),
                        "scheme": "Demo",
                        "configuration": "Debug",
                        "simulatorName": "iPhone 17",
                        "useLatestOS": True,
                        "derivedDataPath": str(derived_data_path),
                        "extraArgs": ["-quiet"],
                    }
                ),
                "--output",
                "text",
            ],
            {
                "check": False,
                "capture_output": True,
                "text": True,
                "timeout": 180,
            },
        )
    ]
    assert "Build & Run complete" in valid_result
