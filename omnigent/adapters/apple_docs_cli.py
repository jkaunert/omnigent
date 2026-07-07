"""Apple documentation CLI adapter for stock-Codex replacement bundles."""

from __future__ import annotations

import subprocess
import textwrap
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from omnigent.adapters.stock_codex_compat import (
    StockCodexCompatAdapterCommandSpec,
    build_stock_codex_compat_file_bridge_command_source,
)
from omnigent.stock_codex_adapter_bridge import (
    AdapterBridgeHandler,
    AdapterBridgeResponse,
    require_string_argument,
)

APPLE_DOCS_CLI_TOOL_NAME = "fetch_apple_docs"
APPLE_DOCS_CLI_URL = "https://developer.apple.com/documentation/swift/string"
APPLE_DEVELOPER_HOST = "developer.apple.com"
SOSUMI_MCP_SERVER_NAME = "sosumi"
SOSUMI_CLI_COMMAND = ("npx", "-y", "@nshipster/sosumi", "fetch")
APPLE_DOCS_PATH_PREFIXES = ("/documentation/", "/design/", "/videos/")


@dataclass(frozen=True)
class AdapterInstallDecision:
    """Decision from an adapter policy for one generated local tool."""

    install: bool
    reason: str


@dataclass(frozen=True)
class AppleDocsCliAdapterPolicy:
    """Policy for replacing Apple docs MCP lookup with a Sosumi CLI tool."""

    tool_name: str = APPLE_DOCS_CLI_TOOL_NAME
    mcp_server_name: str = SOSUMI_MCP_SERVER_NAME
    allowed_host: str = APPLE_DEVELOPER_HOST
    allowed_path_prefixes: tuple[str, ...] = APPLE_DOCS_PATH_PREFIXES
    command_prefix: tuple[str, ...] = SOSUMI_CLI_COMMAND
    timeout_seconds: int = 30

    def decide_for_mcp_servers(
        self,
        server_configs: Mapping[str, object],
    ) -> AdapterInstallDecision:
        """Decide whether this adapter should be installed for a bundle."""
        if self.mcp_server_name not in server_configs:
            return AdapterInstallDecision(
                install=False,
                reason=(
                    f"Apple docs CLI adapter not installed because MCP server "
                    f"{self.mcp_server_name!r} is absent."
                ),
            )
        return AdapterInstallDecision(
            install=True,
            reason=(
                f"Apple docs CLI adapter installed because MCP server "
                f"{self.mcp_server_name!r} is present; existing MCP config is unchanged."
            ),
        )

    def validate_url(self, url: str) -> None:
        """Validate that a URL stays inside the allowed Apple docs surface."""
        parsed = urlparse(url)
        hostname = (parsed.hostname or "").lower()
        allowed_host = self.allowed_host.lower()
        if parsed.scheme != "https" or hostname != allowed_host:
            raise ValueError(
                f"url must be an https://{allowed_host} documentation URL"
            )
        if parsed.port not in (None, 443):
            raise ValueError(f"url must not specify a non-default port: {parsed.port}")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("url must not contain embedded credentials")
        if not parsed.path.startswith(self.allowed_path_prefixes):
            prefixes = ", ".join(self.allowed_path_prefixes)
            raise ValueError(f"url path must start with one of: {prefixes}")

    def command_for_url(self, url: str) -> list[str]:
        """Return the CLI command that will fetch the validated URL."""
        self.validate_url(url)
        return [*self.command_prefix, url]


DEFAULT_APPLE_DOCS_CLI_POLICY = AppleDocsCliAdapterPolicy()


def build_fetch_apple_docs_stock_codex_bridge_handler(
    policy: AppleDocsCliAdapterPolicy = DEFAULT_APPLE_DOCS_CLI_POLICY,
) -> AdapterBridgeHandler:
    """Build the wrapper-side file-bridge handler for Apple documentation lookup."""

    def handler(arguments: Mapping[str, object]) -> AdapterBridgeResponse:
        url = require_string_argument(arguments, "url")
        try:
            completed = subprocess.run(
                policy.command_for_url(url),
                check=False,
                capture_output=True,
                text=True,
                timeout=policy.timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            return AdapterBridgeResponse.error(
                f"Error: sosumi CLI timed out after {policy.timeout_seconds} seconds.",
                exit_code=75,
            )
        return AdapterBridgeResponse.from_completed_process(
            stdout=completed.stdout,
            stderr=completed.stderr,
            returncode=completed.returncode,
        )

    return handler


def build_fetch_apple_docs_cli_tool_source(
    policy: AppleDocsCliAdapterPolicy = DEFAULT_APPLE_DOCS_CLI_POLICY,
) -> str:
    """Build the self-contained Python source for the generated local tool."""
    if not policy.tool_name.isidentifier():
        raise ValueError(f"tool_name must be a valid Python identifier: {policy.tool_name!r}")
    if policy.timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be greater than zero")
    allowed_host = policy.allowed_host.lower()
    allowed_prefixes = tuple(policy.allowed_path_prefixes)
    command_prefix = list(policy.command_prefix)
    return textwrap.dedent(
        f'''\
        """Apple documentation CLI adapter generated by Omnigent."""

        from __future__ import annotations

        import subprocess
        from urllib.parse import urlparse

        from omnigent_client import tool

        _ALLOWED_HOST = {allowed_host!r}
        _ALLOWED_PATH_PREFIXES = {allowed_prefixes!r}
        _COMMAND_PREFIX = {command_prefix!r}
        _TIMEOUT_SECONDS = {policy.timeout_seconds!r}


        def _validate_apple_docs_url(url: str) -> str | None:
            parsed = urlparse(url)
            hostname = (parsed.hostname or "").lower()
            if parsed.scheme != "https" or hostname != _ALLOWED_HOST:
                return f"Error: url must be an https://{{_ALLOWED_HOST}} documentation URL."
            if parsed.port not in (None, 443):
                return f"Error: url must not specify a non-default port: {{parsed.port}}."
            if parsed.username is not None or parsed.password is not None:
                return "Error: url must not contain embedded credentials."
            if not parsed.path.startswith(_ALLOWED_PATH_PREFIXES):
                prefixes = ", ".join(_ALLOWED_PATH_PREFIXES)
                return f"Error: url path must start with one of: {{prefixes}}."
            return None


        @tool
        def {policy.tool_name}(url: str) -> str:
            """Fetch Apple documentation Markdown through the Sosumi CLI."""
            validation_error = _validate_apple_docs_url(url)
            if validation_error is not None:
                return validation_error
            try:
                completed = subprocess.run(
                    [*_COMMAND_PREFIX, url],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=_TIMEOUT_SECONDS,
                )
            except subprocess.TimeoutExpired:
                return f"Error: sosumi CLI timed out after {{_TIMEOUT_SECONDS}} seconds."
            if completed.returncode != 0:
                detail = (completed.stderr or completed.stdout).strip()
                return f"Error: sosumi CLI exited {{completed.returncode}}: {{detail[:2000]}}"
            return completed.stdout
        '''
    )


def write_fetch_apple_docs_cli_tool(
    agent_dir: Path,
    *,
    policy: AppleDocsCliAdapterPolicy = DEFAULT_APPLE_DOCS_CLI_POLICY,
) -> Path:
    """Write the generated Apple docs CLI local tool into an agent bundle."""
    source = build_fetch_apple_docs_cli_tool_source(policy)
    tools_dir = agent_dir / "tools" / "python"
    tools_dir.mkdir(parents=True, exist_ok=True)
    tool_path = tools_dir / f"{policy.tool_name}.py"
    tool_path.write_text(source, encoding="utf-8")
    return tool_path


def build_fetch_apple_docs_stock_codex_adapter_command_source(
    policy: AppleDocsCliAdapterPolicy = DEFAULT_APPLE_DOCS_CLI_POLICY,
) -> str:
    """Build executable source for the stock-Codex wrapper Apple docs adapter."""
    if policy.timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be greater than zero")
    allowed_host = policy.allowed_host.lower()
    allowed_prefixes = tuple(policy.allowed_path_prefixes)
    command_prefix = list(policy.command_prefix)
    return textwrap.dedent(
        f'''\
        #!/usr/bin/env python3
        """Apple documentation command adapter generated by Omnigent."""

        from __future__ import annotations

        import argparse
        import subprocess
        import sys
        from urllib.parse import urlparse

        _ALLOWED_HOST = {allowed_host!r}
        _ALLOWED_PATH_PREFIXES = {allowed_prefixes!r}
        _COMMAND_PREFIX = {command_prefix!r}
        _TIMEOUT_SECONDS = {policy.timeout_seconds!r}


        def _validate_apple_docs_url(url: str) -> str | None:
            parsed = urlparse(url)
            hostname = (parsed.hostname or "").lower()
            if parsed.scheme != "https" or hostname != _ALLOWED_HOST:
                return f"Error: url must be an https://{{_ALLOWED_HOST}} documentation URL."
            if parsed.port not in (None, 443):
                return f"Error: url must not specify a non-default port: {{parsed.port}}."
            if parsed.username is not None or parsed.password is not None:
                return "Error: url must not contain embedded credentials."
            if not parsed.path.startswith(_ALLOWED_PATH_PREFIXES):
                prefixes = ", ".join(_ALLOWED_PATH_PREFIXES)
                return f"Error: url path must start with one of: {{prefixes}}."
            return None


        def main() -> int:
            parser = argparse.ArgumentParser(
                description="Fetch Apple documentation Markdown through the Sosumi CLI."
            )
            parser.add_argument("--url", required=True)
            args = parser.parse_args()
            validation_error = _validate_apple_docs_url(args.url)
            if validation_error is not None:
                print(validation_error, file=sys.stderr)
                return 64
            try:
                completed = subprocess.run(
                    [*_COMMAND_PREFIX, args.url],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=_TIMEOUT_SECONDS,
                )
            except subprocess.TimeoutExpired:
                print(
                    f"Error: sosumi CLI timed out after {{_TIMEOUT_SECONDS}} seconds.",
                    file=sys.stderr,
                )
                return 75
            if completed.returncode != 0:
                detail = (completed.stderr or completed.stdout).strip()
                print(
                    f"Error: sosumi CLI exited {{completed.returncode}}: {{detail[:2000]}}",
                    file=sys.stderr,
                )
                return completed.returncode or 70
            sys.stdout.write(completed.stdout)
            return 0


        if __name__ == "__main__":
            raise SystemExit(main())
        '''
    )


def _apple_docs_stock_codex_url_parameters() -> dict[str, object]:
    return {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": (
                    "HTTPS developer.apple.com documentation, design, or video URL."
                ),
            }
        },
        "required": ["url"],
        "additionalProperties": False,
    }


def build_fetch_apple_docs_stock_codex_adapter_spec(
    policy: AppleDocsCliAdapterPolicy = DEFAULT_APPLE_DOCS_CLI_POLICY,
) -> StockCodexCompatAdapterCommandSpec:
    """Build the stock-Codex wrapper adapter spec for Apple docs."""
    return StockCodexCompatAdapterCommandSpec(
        name=policy.tool_name,
        capability="apple-docs",
        description="Fetch Apple documentation Markdown through the Sosumi CLI.",
        parameters=_apple_docs_stock_codex_url_parameters(),
        command_source=build_fetch_apple_docs_stock_codex_adapter_command_source(policy),
    )


def build_fetch_apple_docs_stock_codex_bridge_adapter_spec(
    policy: AppleDocsCliAdapterPolicy = DEFAULT_APPLE_DOCS_CLI_POLICY,
    *,
    bridge_timeout_seconds: int = 60,
) -> StockCodexCompatAdapterCommandSpec:
    """Build an Apple docs adapter that relays execution to the Omnigent wrapper."""
    return StockCodexCompatAdapterCommandSpec(
        name=policy.tool_name,
        capability="apple-docs",
        description=(
            "Fetch Apple documentation Markdown through the Omnigent wrapper bridge."
        ),
        parameters=_apple_docs_stock_codex_url_parameters(),
        command_source=build_stock_codex_compat_file_bridge_command_source(
            policy.tool_name,
            ("url",),
            timeout_seconds=bridge_timeout_seconds,
        ),
    )
