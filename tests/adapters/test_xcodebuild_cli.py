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
    OMNIGENT_XCODEBUILDMCP_AXE_PATH_ENV,
    XCODEBUILD_CLI_RUNTIME_LOGS_TOOL_NAME,
    XCODEBUILD_CLI_SCREENSHOT_TOOL_NAME,
    XCODEBUILD_CLI_SNAPSHOT_UI_TOOL_NAME,
    XCODEBUILD_CLI_TEST_TOOL_NAME,
    XCODEBUILD_CLI_TOOL_NAME,
    XCODEBUILDMCP_AXE_PATH_ENV,
    XCODEBUILDMCP_CLI_COMMAND,
    XCODEBUILDMCP_CLI_ENV_OVERRIDES,
    XCODEBUILDMCP_CLI_SCREENSHOT_COMMAND,
    XCODEBUILDMCP_CLI_TEST_COMMAND,
    XcodeBuildCliAdapterPolicy,
    build_xcodebuildmcp_simulator_build_run_tool_source,
    build_xcodebuildmcp_simulator_runtime_logs_tool_source,
    build_xcodebuildmcp_simulator_screenshot_tool_source,
    build_xcodebuildmcp_simulator_snapshot_ui_tool_source,
    build_xcodebuildmcp_simulator_test_tool_source,
    write_xcodebuildmcp_simulator_build_run_tool,
    write_xcodebuildmcp_simulator_runtime_logs_tool,
    write_xcodebuildmcp_simulator_screenshot_tool,
    write_xcodebuildmcp_simulator_snapshot_ui_tool,
    write_xcodebuildmcp_simulator_test_tool,
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


def _expected_subprocess_env(module: ModuleType, *, axe_path: str | None = None) -> dict[str, str]:
    env = {**module.os.environ, **XCODEBUILDMCP_CLI_ENV_OVERRIDES}
    env.pop(XCODEBUILDMCP_AXE_PATH_ENV, None)
    if axe_path is not None:
        env[XCODEBUILDMCP_AXE_PATH_ENV] = axe_path
    return env


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


def test_policy_builds_cli_test_command_for_valid_project(tmp_path: Path) -> None:
    project_path = tmp_path / "Demo.xcodeproj"
    project_path.mkdir()
    derived_data_path = tmp_path / "DerivedData"
    policy = XcodeBuildCliAdapterPolicy(
        allowed_derived_data_roots=(str(tmp_path),),
    )

    command = policy.command_for_simulator_test(
        project_path=str(project_path),
        scheme="Demo",
        configuration="Debug",
        simulator_name="iPhone 17",
        derived_data_path=str(derived_data_path),
        extra_args=["-quiet"],
    )

    assert command[:3] == [*XCODEBUILDMCP_CLI_TEST_COMMAND]
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
    assert "XCODEBUILDMCP_ENABLED_WORKFLOWS" in source
    assert "XCODEBUILDMCP_EXPERIMENTAL_WORKFLOW_DISCOVERY" in source


def test_generated_test_tool_source_names_expected_tool() -> None:
    source = build_xcodebuildmcp_simulator_test_tool_source()

    assert f"def {XCODEBUILD_CLI_TEST_TOOL_NAME}(" in source
    assert "xcodebuildmcp" in source
    assert "simulator" in source
    assert "test" in source
    assert "XCODEBUILDMCP_ENABLED_WORKFLOWS" in source
    assert "XCODEBUILDMCP_EXPERIMENTAL_WORKFLOW_DISCOVERY" in source


def test_generated_screenshot_tool_source_names_expected_tool() -> None:
    source = build_xcodebuildmcp_simulator_screenshot_tool_source()

    assert f"def {XCODEBUILD_CLI_SCREENSHOT_TOOL_NAME}(" in source
    assert "xcodebuildmcp" in source
    assert "build-and-run" in source
    assert "ui-automation" in source
    assert "screenshot" in source
    assert "XCODEBUILDMCP_ENABLED_WORKFLOWS" in source
    assert "XCODEBUILDMCP_EXPERIMENTAL_WORKFLOW_DISCOVERY" in source


def test_generated_snapshot_ui_tool_source_names_expected_tool() -> None:
    source = build_xcodebuildmcp_simulator_snapshot_ui_tool_source()

    assert f"def {XCODEBUILD_CLI_SNAPSHOT_UI_TOOL_NAME}(" in source
    assert "xcodebuildmcp" in source
    assert "build-and-run" in source
    assert "ui-automation" in source
    assert "snapshot-ui" in source
    assert "XCODEBUILDMCP_ENABLED_WORKFLOWS" in source
    assert "XCODEBUILDMCP_EXPERIMENTAL_WORKFLOW_DISCOVERY" in source
    assert OMNIGENT_XCODEBUILDMCP_AXE_PATH_ENV in source
    assert XCODEBUILDMCP_AXE_PATH_ENV in source


def test_generated_runtime_logs_tool_source_names_expected_tool() -> None:
    source = build_xcodebuildmcp_simulator_runtime_logs_tool_source()

    assert f"def {XCODEBUILD_CLI_RUNTIME_LOGS_TOOL_NAME}(" in source
    assert "xcodebuildmcp" in source
    assert "build-and-run" in source
    assert "runtimeLogPath" in source
    assert "osLogPath" in source
    assert "import time" in source
    assert "XCODEBUILDMCP_ENABLED_WORKFLOWS" in source
    assert "XCODEBUILDMCP_EXPERIMENTAL_WORKFLOW_DISCOVERY" in source


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
            stdout=("Build succeeded\nBuild & Run complete\nBundle ID: ai.omnigent.ios\n"),
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
                "env": _expected_subprocess_env(module),
            },
        )
    ]
    assert "Build & Run complete" in valid_result


def test_generated_tool_strips_ambient_axe_path_without_omnigent_override(
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
        return subprocess.CompletedProcess(cmd, 0, stdout="Build & Run complete", stderr="")

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    monkeypatch.setenv(XCODEBUILDMCP_AXE_PATH_ENV, "/ambient/axe")

    result = module.xcodebuildmcp_simulator_build_run(
        str(project_path),
        "Demo",
        "Debug",
        "iPhone 17",
        str(derived_data_path),
        ["-quiet"],
    )

    assert "Build & Run complete" in result
    assert len(calls) == 1
    forwarded_env = calls[0][1]["env"]
    assert XCODEBUILDMCP_AXE_PATH_ENV not in forwarded_env


def test_generated_test_tool_validates_arguments_before_calling_cli(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_path = tmp_path / "Demo.xcodeproj"
    project_path.mkdir()
    derived_data_path = tmp_path / "DerivedData"
    policy = XcodeBuildCliAdapterPolicy(allowed_derived_data_roots=(str(tmp_path),))
    tool_path = write_xcodebuildmcp_simulator_test_tool(tmp_path, policy=policy)
    module = _load_module(tool_path)
    calls: list[tuple[list[str], dict[str, Any]]] = []

    def fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append((cmd, kwargs))
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout=("Test succeeded\nTest complete\nScheme: Demo\n"),
            stderr="",
        )

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    invalid_result = module.xcodebuildmcp_simulator_test(
        str(project_path),
        "Demo",
        "Debug",
        "Vision Pro",
        str(derived_data_path),
        ["-quiet"],
    )
    valid_result = module.xcodebuildmcp_simulator_test(
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
                *XCODEBUILDMCP_CLI_TEST_COMMAND,
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
                "env": _expected_subprocess_env(module),
            },
        )
    ]
    assert "Test complete" in valid_result


def test_generated_screenshot_tool_launches_then_captures_screenshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_path = tmp_path / "Demo.xcodeproj"
    project_path.mkdir()
    derived_data_path = tmp_path / "DerivedData"
    screenshot_path = tmp_path / "screenshot.jpg"
    screenshot_path.write_bytes(b"jpeg")
    policy = XcodeBuildCliAdapterPolicy(allowed_derived_data_roots=(str(tmp_path),))
    tool_path = write_xcodebuildmcp_simulator_screenshot_tool(tmp_path, policy=policy)
    module = _load_module(tool_path)
    calls: list[tuple[list[str], dict[str, Any]]] = []

    def fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append((cmd, kwargs))
        if cmd[:3] == [*XCODEBUILDMCP_CLI_COMMAND]:
            stdout = json.dumps(
                {
                    "didError": False,
                    "data": {
                        "summary": {"status": "SUCCEEDED"},
                        "artifacts": {
                            "bundleId": "ai.omnigent.ios",
                            "simulatorId": "SIM-123",
                        },
                    },
                }
            )
        else:
            stdout = json.dumps(
                {
                    "didError": False,
                    "data": {
                        "summary": {"status": "SUCCEEDED"},
                        "artifacts": {"screenshotPath": str(screenshot_path)},
                        "capture": {
                            "format": "image/jpeg",
                            "width": 368,
                            "height": 800,
                        },
                    },
                }
            )
        return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    invalid_result = module.xcodebuildmcp_simulator_screenshot(
        str(project_path),
        "Demo",
        "Debug",
        "Vision Pro",
        str(derived_data_path),
        ["-quiet"],
    )
    valid_result = module.xcodebuildmcp_simulator_screenshot(
        str(project_path),
        "Demo",
        "Debug",
        "iPhone 17",
        str(derived_data_path),
        ["-quiet"],
    )

    assert invalid_result.startswith("Error: simulator_name must start with")
    assert len(calls) == 2
    build_cmd, build_kwargs = calls[0]
    screenshot_cmd, screenshot_kwargs = calls[1]
    assert build_cmd[:3] == [*XCODEBUILDMCP_CLI_COMMAND]
    assert build_cmd[-2:] == ["--output", "json"]
    assert json.loads(build_cmd[build_cmd.index("--json") + 1]) == {
        "projectPath": str(project_path),
        "scheme": "Demo",
        "configuration": "Debug",
        "simulatorName": "iPhone 17",
        "useLatestOS": True,
        "derivedDataPath": str(derived_data_path),
        "extraArgs": ["-quiet"],
    }
    assert screenshot_cmd[:3] == [*XCODEBUILDMCP_CLI_SCREENSHOT_COMMAND]
    assert screenshot_cmd[-2:] == ["--output", "json"]
    assert json.loads(screenshot_cmd[screenshot_cmd.index("--json") + 1]) == {
        "simulatorId": "SIM-123",
        "returnFormat": "path",
    }
    expected_env = _expected_subprocess_env(module)
    assert build_kwargs == {
        "check": False,
        "capture_output": True,
        "text": True,
        "timeout": 180,
        "env": expected_env,
    }
    assert screenshot_kwargs == build_kwargs
    result = json.loads(valid_result)
    assert result == {
        "buildStatus": "SUCCEEDED",
        "bundleId": "ai.omnigent.ios",
        "format": "image/jpeg",
        "height": 800,
        "screenshotPath": str(screenshot_path),
        "screenshotStatus": "SUCCEEDED",
        "simulatorId": "SIM-123",
        "width": 368,
    }


def test_generated_snapshot_ui_tool_launches_then_captures_semantic_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_path = tmp_path / "Demo.xcodeproj"
    project_path.mkdir()
    derived_data_path = tmp_path / "DerivedData"
    patched_axe_path = str(tmp_path / "axe")
    policy = XcodeBuildCliAdapterPolicy(allowed_derived_data_roots=(str(tmp_path),))
    tool_path = write_xcodebuildmcp_simulator_snapshot_ui_tool(tmp_path, policy=policy)
    module = _load_module(tool_path)
    calls: list[tuple[list[str], dict[str, Any]]] = []

    def fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append((cmd, kwargs))
        if "build-and-run" in cmd:
            stdout = json.dumps(
                {
                    "didError": False,
                    "data": {
                        "summary": {"status": "SUCCEEDED"},
                        "artifacts": {
                            "bundleId": "ai.omnigent.ios",
                            "simulatorId": "SIM-123",
                        },
                    },
                }
            )
        elif "snapshot-ui" in cmd:
            stdout = json.dumps(
                {
                    "didError": False,
                    "data": {
                        "summary": {"status": "SUCCEEDED"},
                        "capture": {
                            "type": "runtime-snapshot",
                            "rs": "1",
                            "screenHash": "0d3ho2y",
                            "seq": 1,
                            "count": 2,
                            "targets": [
                                "e14|typeText|text-field||http://localhost:6767|",
                                "e15|tap|button|Connect||",
                            ],
                        },
                    },
                }
            )
        else:
            stdout = ""
        return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    monkeypatch.setenv(OMNIGENT_XCODEBUILDMCP_AXE_PATH_ENV, patched_axe_path)

    invalid_result = module.xcodebuildmcp_simulator_snapshot_ui(
        str(project_path),
        "Demo",
        "Debug",
        "Vision Pro",
        str(derived_data_path),
        ["-quiet"],
    )
    valid_result = module.xcodebuildmcp_simulator_snapshot_ui(
        str(project_path),
        "Demo",
        "Debug",
        "iPhone 17",
        str(derived_data_path),
        ["-quiet"],
    )

    assert invalid_result.startswith("Error: simulator_name must start with")
    assert len(calls) == 3
    build_cmd, build_kwargs = calls[0]
    snapshot_cmd, snapshot_kwargs = calls[1]
    stop_cmd, stop_kwargs = calls[2]
    assert build_cmd[:5] == [
        "xcodebuildmcp",
        "--socket",
        build_cmd[2],
        "simulator",
        "build-and-run",
    ]
    assert build_cmd[-2:] == ["--output", "json"]
    assert json.loads(build_cmd[build_cmd.index("--json") + 1]) == {
        "projectPath": str(project_path),
        "scheme": "Demo",
        "configuration": "Debug",
        "simulatorName": "iPhone 17",
        "useLatestOS": True,
        "derivedDataPath": str(derived_data_path),
        "extraArgs": ["-quiet"],
    }
    assert snapshot_cmd[:5] == [
        "xcodebuildmcp",
        "--socket",
        build_cmd[2],
        "ui-automation",
        "snapshot-ui",
    ]
    assert snapshot_cmd[-4:] == ["--simulator-id", "SIM-123", "--output", "json"]
    assert stop_cmd == ["xcodebuildmcp", "--socket", build_cmd[2], "daemon", "stop"]
    expected_env = _expected_subprocess_env(module, axe_path=patched_axe_path)
    assert build_kwargs == {
        "check": False,
        "capture_output": True,
        "text": True,
        "timeout": 180,
        "env": expected_env,
    }
    assert snapshot_kwargs == build_kwargs
    assert stop_kwargs == {
        "check": False,
        "capture_output": True,
        "text": True,
        "timeout": 10,
        "env": expected_env,
    }
    result = json.loads(valid_result)
    assert result == {
        "buildStatus": "SUCCEEDED",
        "bundleId": "ai.omnigent.ios",
        "count": 2,
        "rs": "1",
        "screenHash": "0d3ho2y",
        "seq": 1,
        "simulatorId": "SIM-123",
        "snapshotStatus": "SUCCEEDED",
        "targets": [
            "e14|typeText|text-field||http://localhost:6767|",
            "e15|tap|button|Connect||",
        ],
        "type": "runtime-snapshot",
    }


def test_generated_runtime_logs_tool_launches_then_reads_log_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_path = tmp_path / "Demo.xcodeproj"
    project_path.mkdir()
    derived_data_path = tmp_path / "DerivedData"
    runtime_log_path = tmp_path / "runtime.log"
    runtime_log_path.write_text("runtime line 1\nruntime line 2\n")
    os_log_path = tmp_path / "os.log"
    os_log_path.write_text("os line 1\nos line 2\n")
    policy = XcodeBuildCliAdapterPolicy(allowed_derived_data_roots=(str(tmp_path),))
    tool_path = write_xcodebuildmcp_simulator_runtime_logs_tool(tmp_path, policy=policy)
    module = _load_module(tool_path)
    calls: list[tuple[list[str], dict[str, Any]]] = []

    def fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append((cmd, kwargs))
        stdout = json.dumps(
            {
                "didError": False,
                "data": {
                    "summary": {"status": "SUCCEEDED"},
                    "artifacts": {
                        "bundleId": "ai.omnigent.ios",
                        "processId": 1234,
                        "simulatorId": "SIM-123",
                        "runtimeLogPath": str(runtime_log_path),
                        "osLogPath": str(os_log_path),
                    },
                },
            }
        )
        return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    invalid_result = module.xcodebuildmcp_simulator_runtime_logs(
        str(project_path),
        "Demo",
        "Debug",
        "Vision Pro",
        str(derived_data_path),
        ["-quiet"],
    )
    valid_result = module.xcodebuildmcp_simulator_runtime_logs(
        str(project_path),
        "Demo",
        "Debug",
        "iPhone 17",
        str(derived_data_path),
        ["-quiet"],
    )

    assert invalid_result.startswith("Error: simulator_name must start with")
    assert len(calls) == 1
    build_cmd, build_kwargs = calls[0]
    assert build_cmd[:3] == [*XCODEBUILDMCP_CLI_COMMAND]
    assert build_cmd[-2:] == ["--output", "json"]
    assert json.loads(build_cmd[build_cmd.index("--json") + 1]) == {
        "projectPath": str(project_path),
        "scheme": "Demo",
        "configuration": "Debug",
        "simulatorName": "iPhone 17",
        "useLatestOS": True,
        "derivedDataPath": str(derived_data_path),
        "extraArgs": ["-quiet"],
    }
    assert build_kwargs == {
        "check": False,
        "capture_output": True,
        "text": True,
        "timeout": 180,
        "env": _expected_subprocess_env(module),
    }
    result = json.loads(valid_result)
    assert result == {
        "buildStatus": "SUCCEEDED",
        "bundleId": "ai.omnigent.ios",
        "launchStatus": "SUCCEEDED",
        "osLogExcerpt": ["os line 1", "os line 2"],
        "osLogLineCount": 2,
        "osLogPath": str(os_log_path),
        "osLogStatus": "SUCCEEDED",
        "processId": 1234,
        "runtimeLogExcerpt": ["runtime line 1", "runtime line 2"],
        "runtimeLogLineCount": 2,
        "runtimeLogPath": str(runtime_log_path),
        "runtimeLogStatus": "SUCCEEDED",
        "simulatorId": "SIM-123",
    }

    monkeypatch.setattr(module.time, "sleep", lambda _seconds: None)
    runtime_log_path.write_text("")
    empty_result = module.xcodebuildmcp_simulator_runtime_logs(
        str(project_path),
        "Demo",
        "Debug",
        "iPhone 17",
        str(derived_data_path),
        ["-quiet"],
    )

    assert empty_result.startswith(
        "Error: runtimeLogPath file did not contain non-empty log lines"
    )
