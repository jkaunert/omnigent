"""Tests for stock-Codex adapter bridge runtime assembly."""

from __future__ import annotations

from pathlib import Path

from omnigent.adapters.apple_docs_cli import (
    APPLE_DOCS_CLI_TOOL_NAME,
    AppleDocsCliAdapterPolicy,
    build_fetch_apple_docs_stock_codex_bridge_adapter_spec,
)
from omnigent.adapters.stock_codex_compat import (
    StockCodexCompatAdapterToolSpec,
    write_stock_codex_compat_adapter_package,
)
from omnigent.adapters.xcodebuild_cli import (
    XCODEBUILD_CLI_TOOL_NAME,
    XcodeBuildCliAdapterPolicy,
    build_xcodebuildmcp_simulator_build_run_stock_codex_bridge_adapter_spec,
)
from omnigent.stock_codex_adapter_runtime import (
    APPLE_DOCS_BRIDGE_CAPABILITY,
    SUPPORTED_STOCK_CODEX_BRIDGE_CAPABILITIES,
    XCODEBUILD_BRIDGE_CAPABILITY,
    build_stock_codex_adapter_bridge_handlers,
)


def test_runtime_builds_handlers_for_supported_bridge_capabilities(
    tmp_path: Path,
) -> None:
    package = write_stock_codex_compat_adapter_package(
        tmp_path / "adapter-package",
        (
            build_fetch_apple_docs_stock_codex_bridge_adapter_spec(),
            build_xcodebuildmcp_simulator_build_run_stock_codex_bridge_adapter_spec(),
        ),
    )

    handlers = build_stock_codex_adapter_bridge_handlers(
        adapter_manifest=package.manifest_path,
        apple_docs_policy=AppleDocsCliAdapterPolicy(command_prefix=("/bin/echo",)),
        xcodebuild_policy=XcodeBuildCliAdapterPolicy(command_prefix=("/bin/echo",)),
    )

    assert SUPPORTED_STOCK_CODEX_BRIDGE_CAPABILITIES == (
        APPLE_DOCS_BRIDGE_CAPABILITY,
        XCODEBUILD_BRIDGE_CAPABILITY,
    )
    assert set(handlers) == {APPLE_DOCS_CLI_TOOL_NAME, XCODEBUILD_CLI_TOOL_NAME}


def test_runtime_skips_unsupported_adapter_capabilities(tmp_path: Path) -> None:
    package = write_stock_codex_compat_adapter_package(
        tmp_path / "adapter-package",
        (
            StockCodexCompatAdapterToolSpec(
                name="omnigent-wrapper-route-adapter-probe",
                argument="route-selection-proof",
                output_sentinel="OMNIGENT_ADAPTER_ARBITRATION_ROUTE_SENTINEL_88",
                capability="route-selection",
                description="Return deterministic route-selection adapter evidence.",
            ),
        ),
    )

    handlers = build_stock_codex_adapter_bridge_handlers(
        adapter_manifest=package.manifest_path
    )

    assert handlers == {}
