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
XCODEBUILD_CLI_SNAPSHOT_UI_TOOL_NAME = "xcodebuildmcp_simulator_snapshot_ui"
XCODEBUILD_CLI_RUNTIME_LOGS_TOOL_NAME = "xcodebuildmcp_simulator_runtime_logs"
XCODEBUILDMCP_MCP_SERVER_NAME = "XcodeBuildMCP"
XCODEBUILDMCP_CLI_BUILD_RUN_COMMAND = ("xcodebuildmcp", "simulator", "build-and-run")
XCODEBUILDMCP_CLI_COMMAND = XCODEBUILDMCP_CLI_BUILD_RUN_COMMAND
XCODEBUILDMCP_CLI_TEST_COMMAND = ("xcodebuildmcp", "simulator", "test")
XCODEBUILDMCP_CLI_SCREENSHOT_COMMAND = ("xcodebuildmcp", "ui-automation", "screenshot")
XCODEBUILDMCP_CLI_SNAPSHOT_UI_COMMAND = ("xcodebuildmcp", "ui-automation", "snapshot-ui")
OMNIGENT_XCODEBUILDMCP_AXE_PATH_ENV = "OMNIGENT_XCODEBUILDMCP_AXE_PATH"
XCODEBUILDMCP_AXE_PATH_ENV = "XCODEBUILDMCP_AXE_PATH"
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
    snapshot_ui_tool_name: str = XCODEBUILD_CLI_SNAPSHOT_UI_TOOL_NAME
    runtime_logs_tool_name: str = XCODEBUILD_CLI_RUNTIME_LOGS_TOOL_NAME
    mcp_server_name: str = XCODEBUILDMCP_MCP_SERVER_NAME
    command_prefix: tuple[str, ...] = XCODEBUILDMCP_CLI_BUILD_RUN_COMMAND
    test_command_prefix: tuple[str, ...] = XCODEBUILDMCP_CLI_TEST_COMMAND
    screenshot_command_prefix: tuple[str, ...] = XCODEBUILDMCP_CLI_SCREENSHOT_COMMAND
    snapshot_ui_command_prefix: tuple[str, ...] = XCODEBUILDMCP_CLI_SNAPSHOT_UI_COMMAND
    env_overrides: Mapping[str, str] | None = None
    axe_path: str | None = None
    axe_path_env_var: str = OMNIGENT_XCODEBUILDMCP_AXE_PATH_ENV
    target_axe_path_env_var: str = XCODEBUILDMCP_AXE_PATH_ENV
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
                f"extra_args may only contain: {allowed}; unexpected={unexpected_extra_args!r}"
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
    axe_path = policy.axe_path
    axe_path_env_var = policy.axe_path_env_var
    target_axe_path_env_var = policy.target_axe_path_env_var
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
        _STATIC_AXE_PATH = {axe_path!r}
        _AXE_PATH_ENV_VAR = {axe_path_env_var!r}
        _TARGET_AXE_PATH_ENV_VAR = {target_axe_path_env_var!r}


        def _subprocess_env() -> dict[str, str]:
            env = {{**os.environ, **_ENV_OVERRIDES}}
            env.pop(_TARGET_AXE_PATH_ENV_VAR, None)
            axe_path = _STATIC_AXE_PATH or os.environ.get(_AXE_PATH_ENV_VAR, "").strip()
            if axe_path:
                env[_TARGET_AXE_PATH_ENV_VAR] = str(Path(axe_path).expanduser())
            return env


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
            env = _subprocess_env()
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
    axe_path = policy.axe_path
    axe_path_env_var = policy.axe_path_env_var
    target_axe_path_env_var = policy.target_axe_path_env_var
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
        _STATIC_AXE_PATH = {axe_path!r}
        _AXE_PATH_ENV_VAR = {axe_path_env_var!r}
        _TARGET_AXE_PATH_ENV_VAR = {target_axe_path_env_var!r}


        def _subprocess_env() -> dict[str, str]:
            env = {{**os.environ, **_ENV_OVERRIDES}}
            env.pop(_TARGET_AXE_PATH_ENV_VAR, None)
            axe_path = _STATIC_AXE_PATH or os.environ.get(_AXE_PATH_ENV_VAR, "").strip()
            if axe_path:
                env[_TARGET_AXE_PATH_ENV_VAR] = str(Path(axe_path).expanduser())
            return env


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
            env = _subprocess_env()
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
    axe_path = policy.axe_path
    axe_path_env_var = policy.axe_path_env_var
    target_axe_path_env_var = policy.target_axe_path_env_var
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
        _STATIC_AXE_PATH = {axe_path!r}
        _AXE_PATH_ENV_VAR = {axe_path_env_var!r}
        _TARGET_AXE_PATH_ENV_VAR = {target_axe_path_env_var!r}


        def _subprocess_env() -> dict[str, str]:
            env = {{**os.environ, **_ENV_OVERRIDES}}
            env.pop(_TARGET_AXE_PATH_ENV_VAR, None)
            axe_path = _STATIC_AXE_PATH or os.environ.get(_AXE_PATH_ENV_VAR, "").strip()
            if axe_path:
                env[_TARGET_AXE_PATH_ENV_VAR] = str(Path(axe_path).expanduser())
            return env


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
            env = _subprocess_env()
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


def build_xcodebuildmcp_simulator_snapshot_ui_tool_source(
    policy: XcodeBuildCliAdapterPolicy = DEFAULT_XCODEBUILD_CLI_POLICY,
) -> str:
    """Build the self-contained Python source for the generated snapshot-ui tool."""
    if not policy.snapshot_ui_tool_name.isidentifier():
        raise ValueError(
            "snapshot_ui_tool_name must be a valid Python identifier: "
            f"{policy.snapshot_ui_tool_name!r}"
        )
    if policy.timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be greater than zero")
    build_run_command_prefix = list(policy.command_prefix)
    snapshot_ui_command_prefix = list(policy.snapshot_ui_command_prefix)
    env_overrides = dict(policy.env_overrides)
    axe_path = policy.axe_path
    axe_path_env_var = policy.axe_path_env_var
    target_axe_path_env_var = policy.target_axe_path_env_var
    allowed_simulator_prefixes = tuple(policy.allowed_simulator_prefixes)
    allowed_derived_data_roots = tuple(policy.allowed_derived_data_roots)
    allowed_extra_args = tuple(policy.allowed_extra_args)
    return textwrap.dedent(
        f'''\
        """XcodeBuildMCP simulator snapshot-ui CLI adapter generated by Omnigent."""

        from __future__ import annotations

        import json
        import os
        import shutil
        import subprocess
        import tempfile
        from pathlib import Path
        from typing import Any

        from omnigent_client import tool

        _BUILD_RUN_COMMAND_PREFIX = {build_run_command_prefix!r}
        _SNAPSHOT_UI_COMMAND_PREFIX = {snapshot_ui_command_prefix!r}
        _ENV_OVERRIDES = {env_overrides!r}
        _ALLOWED_SIMULATOR_PREFIXES = {allowed_simulator_prefixes!r}
        _ALLOWED_DERIVED_DATA_ROOTS = {allowed_derived_data_roots!r}
        _ALLOWED_EXTRA_ARGS = {allowed_extra_args!r}
        _TIMEOUT_SECONDS = {policy.timeout_seconds!r}
        _STATIC_AXE_PATH = {axe_path!r}
        _AXE_PATH_ENV_VAR = {axe_path_env_var!r}
        _TARGET_AXE_PATH_ENV_VAR = {target_axe_path_env_var!r}


        def _subprocess_env() -> dict[str, str]:
            env = {{**os.environ, **_ENV_OVERRIDES}}
            env.pop(_TARGET_AXE_PATH_ENV_VAR, None)
            axe_path = _STATIC_AXE_PATH or os.environ.get(_AXE_PATH_ENV_VAR, "").strip()
            if axe_path:
                env[_TARGET_AXE_PATH_ENV_VAR] = str(Path(axe_path).expanduser())
            return env


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


        def _with_socket(command_prefix: list[str], socket_path: Path) -> list[str]:
            if not command_prefix:
                return command_prefix
            return [command_prefix[0], "--socket", str(socket_path), *command_prefix[1:]]


        def _stop_daemon(socket_path: Path, env: dict[str, str]) -> None:
            binary = _BUILD_RUN_COMMAND_PREFIX[0] if _BUILD_RUN_COMMAND_PREFIX else "xcodebuildmcp"
            try:
                subprocess.run(
                    [binary, "--socket", str(socket_path), "daemon", "stop"],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=10,
                    env=env,
                )
            except Exception:
                return


        @tool
        def {policy.snapshot_ui_tool_name}(
            project_path: str,
            scheme: str,
            configuration: str,
            simulator_name: str,
            derived_data_path: str,
            extra_args: list[str] | None = None,
            use_latest_os: bool = True,
        ) -> str:
            """Build, launch, then capture a semantic simulator UI snapshot."""
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
            env = _subprocess_env()
            socket_dir = Path(tempfile.mkdtemp(prefix="omnigent-xcodebuildmcp-"))
            socket_path = socket_dir / "xcodebuildmcp.sock"
            try:
                build_command = [
                    *_with_socket(_BUILD_RUN_COMMAND_PREFIX, socket_path),
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

                snapshot_command = [
                    *_with_socket(_SNAPSHOT_UI_COMMAND_PREFIX, socket_path),
                    "--simulator-id",
                    simulator_id,
                    "--output",
                    "json",
                ]
                snapshot_result, error = _run_json_command(snapshot_command, env)
                if error is not None:
                    return error
                assert snapshot_result is not None
                snapshot_data = _require_dict(snapshot_result.get("data"), "data")
                if isinstance(snapshot_data, str):
                    return snapshot_data
                snapshot_summary = _require_dict(
                    snapshot_data.get("summary"),
                    "data.summary",
                )
                if isinstance(snapshot_summary, str):
                    return snapshot_summary
                snapshot_capture_value = snapshot_data.get("capture")
                if (
                    snapshot_capture_value is None
                    and snapshot_data.get("type") == "runtime-snapshot"
                ):
                    snapshot_capture_value = snapshot_data
                snapshot_capture = _require_dict(snapshot_capture_value, "data.capture")
                if isinstance(snapshot_capture, str):
                    return snapshot_capture
                if snapshot_summary.get("status") != "SUCCEEDED":
                    return f"Error: snapshot-ui status was {{snapshot_summary.get('status')!r}}."
                if snapshot_capture.get("type") != "runtime-snapshot":
                    return (
                        "Error: snapshot-ui capture type was "
                        f"{{snapshot_capture.get('type')!r}}."
                    )
                count = snapshot_capture.get("count")
                targets = snapshot_capture.get("targets")
                if not isinstance(count, int) or count <= 0:
                    return f"Error: snapshot-ui count was not positive: {{count!r}}."
                if not isinstance(targets, list) or not targets:
                    return "Error: snapshot-ui result did not include targets."

                return json.dumps(
                    {{
                        "buildStatus": build_summary.get("status"),
                        "snapshotStatus": snapshot_summary.get("status"),
                        "bundleId": build_artifacts.get("bundleId"),
                        "simulatorId": simulator_id,
                        "type": snapshot_capture.get("type"),
                        "rs": snapshot_capture.get("rs"),
                        "screenHash": snapshot_capture.get("screenHash"),
                        "seq": snapshot_capture.get("seq"),
                        "count": count,
                        "targets": targets[:12],
                    }},
                    indent=2,
                    sort_keys=True,
                )
            finally:
                _stop_daemon(socket_path, env)
                shutil.rmtree(socket_dir, ignore_errors=True)
        '''
    )


def build_xcodebuildmcp_simulator_runtime_logs_tool_source(
    policy: XcodeBuildCliAdapterPolicy = DEFAULT_XCODEBUILD_CLI_POLICY,
) -> str:
    """Build the self-contained Python source for the generated runtime-log tool."""
    if not policy.runtime_logs_tool_name.isidentifier():
        raise ValueError(
            "runtime_logs_tool_name must be a valid Python identifier: "
            f"{policy.runtime_logs_tool_name!r}"
        )
    if policy.timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be greater than zero")
    build_run_command_prefix = list(policy.command_prefix)
    env_overrides = dict(policy.env_overrides)
    axe_path = policy.axe_path
    axe_path_env_var = policy.axe_path_env_var
    target_axe_path_env_var = policy.target_axe_path_env_var
    allowed_simulator_prefixes = tuple(policy.allowed_simulator_prefixes)
    allowed_derived_data_roots = tuple(policy.allowed_derived_data_roots)
    allowed_extra_args = tuple(policy.allowed_extra_args)
    return textwrap.dedent(
        f'''\
        """XcodeBuildMCP simulator runtime-log CLI adapter generated by Omnigent."""

        from __future__ import annotations

        import json
        import os
        import subprocess
        import time
        from pathlib import Path
        from typing import Any

        from omnigent_client import tool

        _BUILD_RUN_COMMAND_PREFIX = {build_run_command_prefix!r}
        _ENV_OVERRIDES = {env_overrides!r}
        _ALLOWED_SIMULATOR_PREFIXES = {allowed_simulator_prefixes!r}
        _ALLOWED_DERIVED_DATA_ROOTS = {allowed_derived_data_roots!r}
        _ALLOWED_EXTRA_ARGS = {allowed_extra_args!r}
        _TIMEOUT_SECONDS = {policy.timeout_seconds!r}
        _STATIC_AXE_PATH = {axe_path!r}
        _AXE_PATH_ENV_VAR = {axe_path_env_var!r}
        _TARGET_AXE_PATH_ENV_VAR = {target_axe_path_env_var!r}
        _MAX_EXCERPT_LINES = 12
        _MAX_LINE_CHARS = 500


        def _subprocess_env() -> dict[str, str]:
            env = {{**os.environ, **_ENV_OVERRIDES}}
            env.pop(_TARGET_AXE_PATH_ENV_VAR, None)
            axe_path = _STATIC_AXE_PATH or os.environ.get(_AXE_PATH_ENV_VAR, "").strip()
            if axe_path:
                env[_TARGET_AXE_PATH_ENV_VAR] = str(Path(axe_path).expanduser())
            return env


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


        def _read_log_summary(path_value: object, label: str) -> dict[str, Any] | str:
            if not isinstance(path_value, str) or not path_value:
                return f"Error: build-and-run result did not include {{label}}."
            path = Path(path_value).expanduser()
            if not path.is_file():
                return f"Error: {{label}} file was not created: {{path}}."
            for _ in range(20):
                if path.stat().st_size > 0:
                    break
                time.sleep(0.25)
            text = path.read_text(encoding="utf-8", errors="replace")
            lines = [line.rstrip() for line in text.splitlines()]
            non_empty_lines = [line for line in lines if line.strip()]
            excerpt = [
                line[:_MAX_LINE_CHARS]
                for line in non_empty_lines[-_MAX_EXCERPT_LINES:]
            ]
            if not excerpt:
                return (
                    f"Error: {{label}} file did not contain non-empty log lines "
                    f"after waiting: {{path}}."
                )
            return {{
                "path": str(path),
                "status": "SUCCEEDED",
                "lineCount": len(lines),
                "excerpt": excerpt,
            }}


        @tool
        def {policy.runtime_logs_tool_name}(
            project_path: str,
            scheme: str,
            configuration: str,
            simulator_name: str,
            derived_data_path: str,
            extra_args: list[str] | None = None,
            use_latest_os: bool = True,
        ) -> str:
            """Build, launch, and return compact simulator runtime log evidence."""
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
            env = _subprocess_env()
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

            runtime_log = _read_log_summary(
                build_artifacts.get("runtimeLogPath"),
                "runtimeLogPath",
            )
            if isinstance(runtime_log, str):
                return runtime_log
            os_log = _read_log_summary(build_artifacts.get("osLogPath"), "osLogPath")
            if isinstance(os_log, str):
                return os_log

            return json.dumps(
                {{
                    "buildStatus": build_summary.get("status"),
                    "launchStatus": build_summary.get("status"),
                    "bundleId": build_artifacts.get("bundleId"),
                    "processId": build_artifacts.get("processId"),
                    "simulatorId": simulator_id,
                    "runtimeLogStatus": runtime_log["status"],
                    "runtimeLogPath": runtime_log["path"],
                    "runtimeLogLineCount": runtime_log["lineCount"],
                    "runtimeLogExcerpt": runtime_log["excerpt"],
                    "osLogStatus": os_log["status"],
                    "osLogPath": os_log["path"],
                    "osLogLineCount": os_log["lineCount"],
                    "osLogExcerpt": os_log["excerpt"],
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


def write_xcodebuildmcp_simulator_snapshot_ui_tool(
    agent_dir: Path,
    *,
    policy: XcodeBuildCliAdapterPolicy = DEFAULT_XCODEBUILD_CLI_POLICY,
) -> Path:
    """Write the generated XcodeBuildMCP CLI snapshot-ui tool into an agent bundle."""
    source = build_xcodebuildmcp_simulator_snapshot_ui_tool_source(policy)
    tools_dir = agent_dir / "tools" / "python"
    tools_dir.mkdir(parents=True, exist_ok=True)
    tool_path = tools_dir / f"{policy.snapshot_ui_tool_name}.py"
    tool_path.write_text(source, encoding="utf-8")
    return tool_path


def write_xcodebuildmcp_simulator_runtime_logs_tool(
    agent_dir: Path,
    *,
    policy: XcodeBuildCliAdapterPolicy = DEFAULT_XCODEBUILD_CLI_POLICY,
) -> Path:
    """Write the generated XcodeBuildMCP CLI runtime-log tool into an agent bundle."""
    source = build_xcodebuildmcp_simulator_runtime_logs_tool_source(policy)
    tools_dir = agent_dir / "tools" / "python"
    tools_dir.mkdir(parents=True, exist_ok=True)
    tool_path = tools_dir / f"{policy.runtime_logs_tool_name}.py"
    tool_path.write_text(source, encoding="utf-8")
    return tool_path
