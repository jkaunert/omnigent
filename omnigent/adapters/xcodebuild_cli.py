"""XcodeBuildMCP CLI adapter for stock-Codex replacement bundles."""

from __future__ import annotations

import json
import textwrap
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

XCODEBUILD_CLI_BUILD_RUN_TOOL_NAME = "xcodebuildmcp_simulator_build_run"
XCODEBUILD_CLI_TOOL_NAME = XCODEBUILD_CLI_BUILD_RUN_TOOL_NAME
XCODEBUILD_CLI_TEST_TOOL_NAME = "xcodebuildmcp_simulator_test"
XCODEBUILD_CLI_SCREENSHOT_TOOL_NAME = "xcodebuildmcp_simulator_screenshot"
XCODEBUILDMCP_MCP_SERVER_NAME = "XcodeBuildMCP"
XCODEBUILDMCP_CLI_BUILD_RUN_COMMAND = ("xcodebuildmcp", "simulator", "build-and-run")
XCODEBUILDMCP_CLI_COMMAND = XCODEBUILDMCP_CLI_BUILD_RUN_COMMAND
XCODEBUILDMCP_CLI_TEST_COMMAND = ("xcodebuildmcp", "simulator", "test")
XCODEBUILDMCP_CLI_SCREENSHOT_COMMAND = ("xcodebuildmcp", "ui-automation", "screenshot")
XCODEBUILDMCP_ALL_WORKFLOWS = (
    "coverage",
    "debugging",
    "device",
    "doctor",
    "macos",
    "project-discovery",
    "project-scaffolding",
    "session-management",
    "simulator-management",
    "simulator",
    "swift-package",
    "ui-automation",
    "utilities",
    "workflow-discovery",
    "xcode-ide",
)
XCODEBUILDMCP_CLI_ENV_OVERRIDES = {
    "XCODEBUILDMCP_ENABLED_WORKFLOWS": ",".join(XCODEBUILDMCP_ALL_WORKFLOWS),
    "XCODEBUILDMCP_EXPERIMENTAL_WORKFLOW_DISCOVERY": "true",
    "XCODEBUILDMCP_DEBUG": "true",
}
XCODEBUILD_ALLOWED_SIMULATOR_PREFIXES = ("iPhone", "iPad")
XCODEBUILD_ALLOWED_DERIVED_DATA_ROOTS = ("/tmp", "/var/folders")
XCODEBUILD_ALLOWED_EXTRA_ARGS = ("-quiet",)


@dataclass(frozen=True)
class AdapterInstallDecision:
    """Decision from an adapter policy for one generated local tool."""

    install: bool
    reason: str


@dataclass(frozen=True)
class XcodeBuildCliAdapterPolicy:
    """Policy for replacing simulator build/run MCP calls with a CLI tool."""

    tool_name: str = XCODEBUILD_CLI_BUILD_RUN_TOOL_NAME
    test_tool_name: str = XCODEBUILD_CLI_TEST_TOOL_NAME
    screenshot_tool_name: str = XCODEBUILD_CLI_SCREENSHOT_TOOL_NAME
    mcp_server_name: str = XCODEBUILDMCP_MCP_SERVER_NAME
    command_prefix: tuple[str, ...] = XCODEBUILDMCP_CLI_BUILD_RUN_COMMAND
    test_command_prefix: tuple[str, ...] = XCODEBUILDMCP_CLI_TEST_COMMAND
    screenshot_command_prefix: tuple[str, ...] = XCODEBUILDMCP_CLI_SCREENSHOT_COMMAND
    env_overrides: Mapping[str, str] | None = None
    allowed_simulator_prefixes: tuple[str, ...] = XCODEBUILD_ALLOWED_SIMULATOR_PREFIXES
    allowed_derived_data_roots: tuple[str, ...] = XCODEBUILD_ALLOWED_DERIVED_DATA_ROOTS
    allowed_extra_args: tuple[str, ...] = XCODEBUILD_ALLOWED_EXTRA_ARGS
    timeout_seconds: int = 180

    def __post_init__(self) -> None:
        """Fill env defaults without sharing a mutable mapping."""
        if self.env_overrides is None:
            object.__setattr__(
                self,
                "env_overrides",
                XCODEBUILDMCP_CLI_ENV_OVERRIDES,
            )

    def decide_for_mcp_servers(
        self,
        server_configs: Mapping[str, object],
    ) -> AdapterInstallDecision:
        """Decide whether this adapter should be installed for a bundle."""
        if self.mcp_server_name not in server_configs:
            return AdapterInstallDecision(
                install=False,
                reason=(
                    f"XcodeBuildMCP CLI adapter not installed because MCP server "
                    f"{self.mcp_server_name!r} is absent."
                ),
            )
        return AdapterInstallDecision(
            install=True,
            reason=(
                f"XcodeBuildMCP CLI adapter installed because MCP server "
                f"{self.mcp_server_name!r} is present; existing MCP config is unchanged."
            ),
        )

    def command_for_build_run(
        self,
        *,
        project_path: str,
        scheme: str,
        configuration: str,
        simulator_name: str,
        derived_data_path: str,
        extra_args: list[str] | None = None,
        use_latest_os: bool = True,
    ) -> list[str]:
        """Return the CLI command for a validated simulator build/run request."""
        payload = self.payload_for_build_run(
            project_path=project_path,
            scheme=scheme,
            configuration=configuration,
            simulator_name=simulator_name,
            derived_data_path=derived_data_path,
            extra_args=extra_args,
            use_latest_os=use_latest_os,
        )
        return [*self.command_prefix, "--json", json.dumps(payload), "--output", "text"]

    def command_for_simulator_test(
        self,
        *,
        project_path: str,
        scheme: str,
        configuration: str,
        simulator_name: str,
        derived_data_path: str,
        extra_args: list[str] | None = None,
        use_latest_os: bool = True,
    ) -> list[str]:
        """Return the CLI command for a validated simulator test request."""
        payload = self.payload_for_build_run(
            project_path=project_path,
            scheme=scheme,
            configuration=configuration,
            simulator_name=simulator_name,
            derived_data_path=derived_data_path,
            extra_args=extra_args,
            use_latest_os=use_latest_os,
        )
        return [*self.test_command_prefix, "--json", json.dumps(payload), "--output", "text"]

    def payload_for_build_run(
        self,
        *,
        project_path: str,
        scheme: str,
        configuration: str,
        simulator_name: str,
        derived_data_path: str,
        extra_args: list[str] | None = None,
        use_latest_os: bool = True,
    ) -> dict[str, object]:
        """Build the validated JSON payload for the CLI tool."""
        if not project_path:
            raise ValueError("project_path must not be empty")
        project = Path(project_path).expanduser()
        if not project.is_absolute():
            raise ValueError("project_path must be absolute")
        if project.suffix != ".xcodeproj":
            raise ValueError("project_path must point to an .xcodeproj")
        if not project.exists():
            raise ValueError(f"project_path does not exist: {project}")
        if not scheme.strip():
            raise ValueError("scheme must not be empty")
        if not configuration.strip():
            raise ValueError("configuration must not be empty")
        if not simulator_name.startswith(self.allowed_simulator_prefixes):
            prefixes = ", ".join(self.allowed_simulator_prefixes)
            raise ValueError(f"simulator_name must start with one of: {prefixes}")
        derived_data = Path(derived_data_path).expanduser()
        if not derived_data.is_absolute():
            raise ValueError("derived_data_path must be absolute")
        if not str(derived_data).startswith(self.allowed_derived_data_roots):
            roots = ", ".join(self.allowed_derived_data_roots)
            raise ValueError(f"derived_data_path must be under one of: {roots}")
        normalized_extra_args = list(extra_args or [])
        unexpected_extra_args = [
            arg for arg in normalized_extra_args if arg not in self.allowed_extra_args
        ]
        if unexpected_extra_args:
            allowed = ", ".join(self.allowed_extra_args)
            raise ValueError(
                f"extra_args may only contain: {allowed}; "
                f"unexpected={unexpected_extra_args!r}"
            )
        return {
            "projectPath": str(project),
            "scheme": scheme,
            "configuration": configuration,
            "simulatorName": simulator_name,
            "useLatestOS": use_latest_os,
            "derivedDataPath": str(derived_data),
            "extraArgs": normalized_extra_args,
        }


DEFAULT_XCODEBUILD_CLI_POLICY = XcodeBuildCliAdapterPolicy()


def build_xcodebuildmcp_simulator_build_run_tool_source(
    policy: XcodeBuildCliAdapterPolicy = DEFAULT_XCODEBUILD_CLI_POLICY,
) -> str:
    """Build the self-contained Python source for the generated local tool."""
    if not policy.tool_name.isidentifier():
        raise ValueError(f"tool_name must be a valid Python identifier: {policy.tool_name!r}")
    if policy.timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be greater than zero")
    command_prefix = list(policy.command_prefix)
    env_overrides = dict(policy.env_overrides)
    allowed_simulator_prefixes = tuple(policy.allowed_simulator_prefixes)
    allowed_derived_data_roots = tuple(policy.allowed_derived_data_roots)
    allowed_extra_args = tuple(policy.allowed_extra_args)
    return textwrap.dedent(
        f'''\
        """XcodeBuildMCP CLI adapter generated by Omnigent."""

        from __future__ import annotations

        import json
        import os
        import subprocess
        from pathlib import Path

        from omnigent_client import tool

        _COMMAND_PREFIX = {command_prefix!r}
        _ENV_OVERRIDES = {env_overrides!r}
        _ALLOWED_SIMULATOR_PREFIXES = {allowed_simulator_prefixes!r}
        _ALLOWED_DERIVED_DATA_ROOTS = {allowed_derived_data_roots!r}
        _ALLOWED_EXTRA_ARGS = {allowed_extra_args!r}
        _TIMEOUT_SECONDS = {policy.timeout_seconds!r}


        def _validation_error(
            project_path: str,
            scheme: str,
            configuration: str,
            simulator_name: str,
            derived_data_path: str,
            extra_args: list[str] | None,
        ) -> str | None:
            if not project_path:
                return "Error: project_path must not be empty."
            project = Path(project_path).expanduser()
            if not project.is_absolute():
                return "Error: project_path must be absolute."
            if project.suffix != ".xcodeproj":
                return "Error: project_path must point to an .xcodeproj."
            if not project.exists():
                return f"Error: project_path does not exist: {{project}}."
            if not scheme.strip():
                return "Error: scheme must not be empty."
            if not configuration.strip():
                return "Error: configuration must not be empty."
            if not simulator_name.startswith(_ALLOWED_SIMULATOR_PREFIXES):
                prefixes = ", ".join(_ALLOWED_SIMULATOR_PREFIXES)
                return f"Error: simulator_name must start with one of: {{prefixes}}."
            derived_data = Path(derived_data_path).expanduser()
            if not derived_data.is_absolute():
                return "Error: derived_data_path must be absolute."
            if not str(derived_data).startswith(_ALLOWED_DERIVED_DATA_ROOTS):
                roots = ", ".join(_ALLOWED_DERIVED_DATA_ROOTS)
                return f"Error: derived_data_path must be under one of: {{roots}}."
            normalized_extra_args = list(extra_args or [])
            unexpected_extra_args = [
                arg for arg in normalized_extra_args if arg not in _ALLOWED_EXTRA_ARGS
            ]
            if unexpected_extra_args:
                allowed = ", ".join(_ALLOWED_EXTRA_ARGS)
                return (
                    f"Error: extra_args may only contain: {{allowed}}; "
                    f"unexpected={{unexpected_extra_args!r}}."
                )
            return None


        @tool
        def {policy.tool_name}(
            project_path: str,
            scheme: str,
            configuration: str,
            simulator_name: str,
            derived_data_path: str,
            extra_args: list[str] | None = None,
            use_latest_os: bool = True,
        ) -> str:
            """Build, install, and launch an iOS app through the XcodeBuildMCP CLI."""
            validation_error = _validation_error(
                project_path,
                scheme,
                configuration,
                simulator_name,
                derived_data_path,
                extra_args,
            )
            if validation_error is not None:
                return validation_error
            payload = {{
                "projectPath": str(Path(project_path).expanduser()),
                "scheme": scheme,
                "configuration": configuration,
                "simulatorName": simulator_name,
                "useLatestOS": use_latest_os,
                "derivedDataPath": str(Path(derived_data_path).expanduser()),
                "extraArgs": list(extra_args or []),
            }}
            command = [*_COMMAND_PREFIX, "--json", json.dumps(payload), "--output", "text"]
            env = {{**os.environ, **_ENV_OVERRIDES}}
            try:
                completed = subprocess.run(
                    command,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=_TIMEOUT_SECONDS,
                    env=env,
                )
            except subprocess.TimeoutExpired:
                return f"Error: xcodebuildmcp CLI timed out after {{_TIMEOUT_SECONDS}} seconds."
            if completed.returncode != 0:
                detail = (completed.stderr or completed.stdout).strip()
                return (
                    f"Error: xcodebuildmcp CLI exited {{completed.returncode}}: "
                    f"{{detail[:4000]}}"
                )
            return completed.stdout
        '''
    )


def build_xcodebuildmcp_simulator_test_tool_source(
    policy: XcodeBuildCliAdapterPolicy = DEFAULT_XCODEBUILD_CLI_POLICY,
) -> str:
    """Build the self-contained Python source for the generated local test tool."""
    if not policy.test_tool_name.isidentifier():
        raise ValueError(
            f"test_tool_name must be a valid Python identifier: {policy.test_tool_name!r}"
        )
    if policy.timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be greater than zero")
    command_prefix = list(policy.test_command_prefix)
    env_overrides = dict(policy.env_overrides)
    allowed_simulator_prefixes = tuple(policy.allowed_simulator_prefixes)
    allowed_derived_data_roots = tuple(policy.allowed_derived_data_roots)
    allowed_extra_args = tuple(policy.allowed_extra_args)
    return textwrap.dedent(
        f'''\
        """XcodeBuildMCP simulator test CLI adapter generated by Omnigent."""

        from __future__ import annotations

        import json
        import os
        import subprocess
        from pathlib import Path

        from omnigent_client import tool

        _COMMAND_PREFIX = {command_prefix!r}
        _ENV_OVERRIDES = {env_overrides!r}
        _ALLOWED_SIMULATOR_PREFIXES = {allowed_simulator_prefixes!r}
        _ALLOWED_DERIVED_DATA_ROOTS = {allowed_derived_data_roots!r}
        _ALLOWED_EXTRA_ARGS = {allowed_extra_args!r}
        _TIMEOUT_SECONDS = {policy.timeout_seconds!r}


        def _validation_error(
            project_path: str,
            scheme: str,
            configuration: str,
            simulator_name: str,
            derived_data_path: str,
            extra_args: list[str] | None,
        ) -> str | None:
            if not project_path:
                return "Error: project_path must not be empty."
            project = Path(project_path).expanduser()
            if not project.is_absolute():
                return "Error: project_path must be absolute."
            if project.suffix != ".xcodeproj":
                return "Error: project_path must point to an .xcodeproj."
            if not project.exists():
                return f"Error: project_path does not exist: {{project}}."
            if not scheme.strip():
                return "Error: scheme must not be empty."
            if not configuration.strip():
                return "Error: configuration must not be empty."
            if not simulator_name.startswith(_ALLOWED_SIMULATOR_PREFIXES):
                prefixes = ", ".join(_ALLOWED_SIMULATOR_PREFIXES)
                return f"Error: simulator_name must start with one of: {{prefixes}}."
            derived_data = Path(derived_data_path).expanduser()
            if not derived_data.is_absolute():
                return "Error: derived_data_path must be absolute."
            if not str(derived_data).startswith(_ALLOWED_DERIVED_DATA_ROOTS):
                roots = ", ".join(_ALLOWED_DERIVED_DATA_ROOTS)
                return f"Error: derived_data_path must be under one of: {{roots}}."
            normalized_extra_args = list(extra_args or [])
            unexpected_extra_args = [
                arg for arg in normalized_extra_args if arg not in _ALLOWED_EXTRA_ARGS
            ]
            if unexpected_extra_args:
                allowed = ", ".join(_ALLOWED_EXTRA_ARGS)
                return (
                    f"Error: extra_args may only contain: {{allowed}}; "
                    f"unexpected={{unexpected_extra_args!r}}."
                )
            return None


        @tool
        def {policy.test_tool_name}(
            project_path: str,
            scheme: str,
            configuration: str,
            simulator_name: str,
            derived_data_path: str,
            extra_args: list[str] | None = None,
            use_latest_os: bool = True,
        ) -> str:
            """Run iOS simulator tests through the XcodeBuildMCP CLI."""
            validation_error = _validation_error(
                project_path,
                scheme,
                configuration,
                simulator_name,
                derived_data_path,
                extra_args,
            )
            if validation_error is not None:
                return validation_error
            payload = {{
                "projectPath": str(Path(project_path).expanduser()),
                "scheme": scheme,
                "configuration": configuration,
                "simulatorName": simulator_name,
                "useLatestOS": use_latest_os,
                "derivedDataPath": str(Path(derived_data_path).expanduser()),
                "extraArgs": list(extra_args or []),
            }}
            command = [*_COMMAND_PREFIX, "--json", json.dumps(payload), "--output", "text"]
            env = {{**os.environ, **_ENV_OVERRIDES}}
            try:
                completed = subprocess.run(
                    command,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=_TIMEOUT_SECONDS,
                    env=env,
                )
            except subprocess.TimeoutExpired:
                return f"Error: xcodebuildmcp CLI timed out after {{_TIMEOUT_SECONDS}} seconds."
            if completed.returncode != 0:
                detail = (completed.stderr or completed.stdout).strip()
                return (
                    f"Error: xcodebuildmcp CLI exited {{completed.returncode}}: "
                    f"{{detail[:4000]}}"
                )
            return completed.stdout
        '''
    )


def build_xcodebuildmcp_simulator_screenshot_tool_source(
    policy: XcodeBuildCliAdapterPolicy = DEFAULT_XCODEBUILD_CLI_POLICY,
) -> str:
    """Build the self-contained Python source for the generated screenshot tool."""
    if not policy.screenshot_tool_name.isidentifier():
        raise ValueError(
            "screenshot_tool_name must be a valid Python identifier: "
            f"{policy.screenshot_tool_name!r}"
        )
    if policy.timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be greater than zero")
    build_run_command_prefix = list(policy.command_prefix)
    screenshot_command_prefix = list(policy.screenshot_command_prefix)
    env_overrides = dict(policy.env_overrides)
    allowed_simulator_prefixes = tuple(policy.allowed_simulator_prefixes)
    allowed_derived_data_roots = tuple(policy.allowed_derived_data_roots)
    allowed_extra_args = tuple(policy.allowed_extra_args)
    return textwrap.dedent(
        f'''\
        """XcodeBuildMCP simulator screenshot CLI adapter generated by Omnigent."""

        from __future__ import annotations

        import json
        import os
        import subprocess
        from pathlib import Path
        from typing import Any

        from omnigent_client import tool

        _BUILD_RUN_COMMAND_PREFIX = {build_run_command_prefix!r}
        _SCREENSHOT_COMMAND_PREFIX = {screenshot_command_prefix!r}
        _ENV_OVERRIDES = {env_overrides!r}
        _ALLOWED_SIMULATOR_PREFIXES = {allowed_simulator_prefixes!r}
        _ALLOWED_DERIVED_DATA_ROOTS = {allowed_derived_data_roots!r}
        _ALLOWED_EXTRA_ARGS = {allowed_extra_args!r}
        _TIMEOUT_SECONDS = {policy.timeout_seconds!r}


        def _validation_error(
            project_path: str,
            scheme: str,
            configuration: str,
            simulator_name: str,
            derived_data_path: str,
            extra_args: list[str] | None,
        ) -> str | None:
            if not project_path:
                return "Error: project_path must not be empty."
            project = Path(project_path).expanduser()
            if not project.is_absolute():
                return "Error: project_path must be absolute."
            if project.suffix != ".xcodeproj":
                return "Error: project_path must point to an .xcodeproj."
            if not project.exists():
                return f"Error: project_path does not exist: {{project}}."
            if not scheme.strip():
                return "Error: scheme must not be empty."
            if not configuration.strip():
                return "Error: configuration must not be empty."
            if not simulator_name.startswith(_ALLOWED_SIMULATOR_PREFIXES):
                prefixes = ", ".join(_ALLOWED_SIMULATOR_PREFIXES)
                return f"Error: simulator_name must start with one of: {{prefixes}}."
            derived_data = Path(derived_data_path).expanduser()
            if not derived_data.is_absolute():
                return "Error: derived_data_path must be absolute."
            if not str(derived_data).startswith(_ALLOWED_DERIVED_DATA_ROOTS):
                roots = ", ".join(_ALLOWED_DERIVED_DATA_ROOTS)
                return f"Error: derived_data_path must be under one of: {{roots}}."
            normalized_extra_args = list(extra_args or [])
            unexpected_extra_args = [
                arg for arg in normalized_extra_args if arg not in _ALLOWED_EXTRA_ARGS
            ]
            if unexpected_extra_args:
                allowed = ", ".join(_ALLOWED_EXTRA_ARGS)
                return (
                    f"Error: extra_args may only contain: {{allowed}}; "
                    f"unexpected={{unexpected_extra_args!r}}."
                )
            return None


        def _run_json_command(
            command: list[str],
            env: dict[str, str],
        ) -> tuple[dict[str, Any] | None, str | None]:
            try:
                completed = subprocess.run(
                    command,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=_TIMEOUT_SECONDS,
                    env=env,
                )
            except subprocess.TimeoutExpired:
                return (
                    None,
                    "Error: xcodebuildmcp CLI timed out after "
                    f"{{_TIMEOUT_SECONDS}} seconds.",
                )
            if completed.returncode != 0:
                detail = (completed.stderr or completed.stdout).strip()
                return (
                    None,
                    f"Error: xcodebuildmcp CLI exited {{completed.returncode}}: "
                    f"{{detail[:4000]}}",
                )
            try:
                result = json.loads(completed.stdout)
            except json.JSONDecodeError as exc:
                return None, f"Error: xcodebuildmcp CLI returned invalid JSON: {{exc}}."
            if not isinstance(result, dict):
                return None, "Error: xcodebuildmcp CLI returned a non-object JSON payload."
            if result.get("didError"):
                return (
                    None,
                    "Error: xcodebuildmcp CLI reported an error: "
                    f"{{result.get('error')}}.",
                )
            return result, None


        def _require_dict(value: object, path: str) -> dict[str, Any] | str:
            if isinstance(value, dict):
                return value
            return f"Error: xcodebuildmcp JSON field {{path}} was not an object."


        @tool
        def {policy.screenshot_tool_name}(
            project_path: str,
            scheme: str,
            configuration: str,
            simulator_name: str,
            derived_data_path: str,
            extra_args: list[str] | None = None,
            use_latest_os: bool = True,
        ) -> str:
            """Build, launch, then capture a non-mutating simulator screenshot."""
            validation_error = _validation_error(
                project_path,
                scheme,
                configuration,
                simulator_name,
                derived_data_path,
                extra_args,
            )
            if validation_error is not None:
                return validation_error

            build_payload = {{
                "projectPath": str(Path(project_path).expanduser()),
                "scheme": scheme,
                "configuration": configuration,
                "simulatorName": simulator_name,
                "useLatestOS": use_latest_os,
                "derivedDataPath": str(Path(derived_data_path).expanduser()),
                "extraArgs": list(extra_args or []),
            }}
            env = {{**os.environ, **_ENV_OVERRIDES}}
            build_command = [
                *_BUILD_RUN_COMMAND_PREFIX,
                "--json",
                json.dumps(build_payload),
                "--output",
                "json",
            ]
            build_result, error = _run_json_command(build_command, env)
            if error is not None:
                return error
            assert build_result is not None
            build_data = _require_dict(build_result.get("data"), "data")
            if isinstance(build_data, str):
                return build_data
            build_summary = _require_dict(build_data.get("summary"), "data.summary")
            if isinstance(build_summary, str):
                return build_summary
            build_artifacts = _require_dict(build_data.get("artifacts"), "data.artifacts")
            if isinstance(build_artifacts, str):
                return build_artifacts
            if build_summary.get("status") != "SUCCEEDED":
                return f"Error: build-and-run status was {{build_summary.get('status')!r}}."
            simulator_id = build_artifacts.get("simulatorId")
            if not isinstance(simulator_id, str) or not simulator_id:
                return "Error: build-and-run result did not include simulatorId."

            screenshot_payload = {{"simulatorId": simulator_id, "returnFormat": "path"}}
            screenshot_command = [
                *_SCREENSHOT_COMMAND_PREFIX,
                "--json",
                json.dumps(screenshot_payload),
                "--output",
                "json",
            ]
            screenshot_result, error = _run_json_command(screenshot_command, env)
            if error is not None:
                return error
            assert screenshot_result is not None
            screenshot_data = _require_dict(screenshot_result.get("data"), "data")
            if isinstance(screenshot_data, str):
                return screenshot_data
            screenshot_summary = _require_dict(
                screenshot_data.get("summary"),
                "data.summary",
            )
            if isinstance(screenshot_summary, str):
                return screenshot_summary
            screenshot_artifacts = _require_dict(
                screenshot_data.get("artifacts"),
                "data.artifacts",
            )
            if isinstance(screenshot_artifacts, str):
                return screenshot_artifacts
            screenshot_capture = _require_dict(
                screenshot_data.get("capture"),
                "data.capture",
            )
            if isinstance(screenshot_capture, str):
                return screenshot_capture
            if screenshot_summary.get("status") != "SUCCEEDED":
                return f"Error: screenshot status was {{screenshot_summary.get('status')!r}}."
            screenshot_path_value = screenshot_artifacts.get("screenshotPath")
            if not isinstance(screenshot_path_value, str) or not screenshot_path_value:
                return "Error: screenshot result did not include screenshotPath."
            screenshot_path = Path(screenshot_path_value).expanduser()
            if not screenshot_path.is_file():
                return f"Error: screenshot file was not created: {{screenshot_path}}."

            return json.dumps(
                {{
                    "buildStatus": build_summary.get("status"),
                    "screenshotStatus": screenshot_summary.get("status"),
                    "bundleId": build_artifacts.get("bundleId"),
                    "simulatorId": simulator_id,
                    "screenshotPath": str(screenshot_path),
                    "format": screenshot_capture.get("format"),
                    "width": screenshot_capture.get("width"),
                    "height": screenshot_capture.get("height"),
                }},
                indent=2,
                sort_keys=True,
            )
        '''
    )


def write_xcodebuildmcp_simulator_build_run_tool(
    agent_dir: Path,
    *,
    policy: XcodeBuildCliAdapterPolicy = DEFAULT_XCODEBUILD_CLI_POLICY,
) -> Path:
    """Write the generated XcodeBuildMCP CLI local tool into an agent bundle."""
    source = build_xcodebuildmcp_simulator_build_run_tool_source(policy)
    tools_dir = agent_dir / "tools" / "python"
    tools_dir.mkdir(parents=True, exist_ok=True)
    tool_path = tools_dir / f"{policy.tool_name}.py"
    tool_path.write_text(source, encoding="utf-8")
    return tool_path


def write_xcodebuildmcp_simulator_test_tool(
    agent_dir: Path,
    *,
    policy: XcodeBuildCliAdapterPolicy = DEFAULT_XCODEBUILD_CLI_POLICY,
) -> Path:
    """Write the generated XcodeBuildMCP CLI test tool into an agent bundle."""
    source = build_xcodebuildmcp_simulator_test_tool_source(policy)
    tools_dir = agent_dir / "tools" / "python"
    tools_dir.mkdir(parents=True, exist_ok=True)
    tool_path = tools_dir / f"{policy.test_tool_name}.py"
    tool_path.write_text(source, encoding="utf-8")
    return tool_path


def write_xcodebuildmcp_simulator_screenshot_tool(
    agent_dir: Path,
    *,
    policy: XcodeBuildCliAdapterPolicy = DEFAULT_XCODEBUILD_CLI_POLICY,
) -> Path:
    """Write the generated XcodeBuildMCP CLI screenshot tool into an agent bundle."""
    source = build_xcodebuildmcp_simulator_screenshot_tool_source(policy)
    tools_dir = agent_dir / "tools" / "python"
    tools_dir.mkdir(parents=True, exist_ok=True)
    tool_path = tools_dir / f"{policy.screenshot_tool_name}.py"
    tool_path.write_text(source, encoding="utf-8")
    return tool_path
