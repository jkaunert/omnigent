"""Parity tests for manifest-driven Codex router selection."""

from __future__ import annotations

import json
from pathlib import Path

from omnigent.inner.router_selection import resolve_router_selection

PLUGIN_NAME = "apple-appdev-workflow"
OWNER = f"{PLUGIN_NAME}:apple-app-orchestrator"
REVIEW = f"{PLUGIN_NAME}:apple-review-orchestrator"
DECISION = f"{PLUGIN_NAME}:apple-decision-stress-test"


def _make_bundle(root: Path) -> Path:
    bundle = root / "bundle"
    _write_skill(
        bundle,
        "apple-app-orchestrator",
        "---\nname: apple-app-orchestrator\n---\nUse the Apple orchestrator.\n",
    )
    _write_skill(
        bundle,
        "apple-review-orchestrator",
        (
            "---\n"
            "name: apple-review-orchestrator\n"
            "metadata:\n"
            "  role: brigade-orchestrator\n"
            "  routing_scope: domain\n"
            "---\n"
            "Use the Apple review orchestrator.\n"
        ),
    )
    _write_skill(
        bundle,
        "apple-decision-stress-test",
        (
            "---\n"
            "name: apple-decision-stress-test\n"
            "metadata:\n"
            "  role: specialist\n"
            "  routing_scope: focused\n"
            "---\n"
            "Use the focused decision specialist.\n"
        ),
    )
    manifest_dir = bundle / ".codex-plugin"
    manifest_dir.mkdir(parents=True)
    (manifest_dir / "plugin.json").write_text(
        json.dumps(
            {
                "name": PLUGIN_NAME,
                "routerSelection": {
                    "schemaVersion": 1,
                    "hostScopes": ["desktop"],
                    "domains": [
                        {
                            "id": "apple-appdev",
                            "promptSignals": ["ios", "swiftui"],
                            "workspaceFiles": ["Package.swift"],
                            "workspaceExtensions": ["xcodeproj", "xcworkspace"],
                            "select": OWNER,
                        }
                    ],
                    "suppression": {"whenExplicitSkillSelected": True},
                },
            }
        ),
        encoding="utf-8",
    )
    return bundle


def _write_skill(bundle: Path, name: str, contents: str) -> None:
    skill_dir = bundle / "skills" / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(contents, encoding="utf-8")


def _resolve(
    *,
    bundle: Path,
    prompt: str,
    cwd: Path,
    host_scope: str | None = "desktop",
    skills_filter: str | list[str] = "all",
):
    return resolve_router_selection(
        bundle_dir=bundle,
        messages=[{"role": "user", "content": prompt}],
        cwd=str(cwd),
        host_scope=host_scope,
        skills_filter=skills_filter,
    )


def test_prompt_signal_matching_uses_codex_carry_boundaries(tmp_path: Path) -> None:
    bundle = _make_bundle(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    swiftui = _resolve(bundle=bundle, prompt="Review this SwiftUI branch diff", cwd=workspace)
    ios_version = _resolve(bundle=bundle, prompt="Review this iOS17 branch diff", cwd=workspace)
    embedded = _resolve(bundle=bundle, prompt="adios for now", cwd=workspace)

    assert swiftui is not None
    assert swiftui.selected_owner == OWNER
    assert ios_version is not None
    assert ios_version.selected_owner == OWNER
    assert embedded is None


def test_workspace_file_and_extension_signals_select_owner(tmp_path: Path) -> None:
    bundle = _make_bundle(tmp_path)
    package_workspace = tmp_path / "package-workspace"
    package_workspace.mkdir()
    (package_workspace / "Package.swift").write_text("// marker\n", encoding="utf-8")
    project_workspace = tmp_path / "project-workspace"
    project_workspace.mkdir()
    (project_workspace / "Demo.xcodeproj").mkdir()

    package_match = _resolve(bundle=bundle, prompt="Review this branch", cwd=package_workspace)
    project_match = _resolve(bundle=bundle, prompt="Review this branch", cwd=project_workspace)

    assert package_match is not None
    assert package_match.selected_owner == OWNER
    assert project_match is not None
    assert project_match.selected_owner == OWNER


def test_host_scope_and_skills_filter_gate_selection(tmp_path: Path) -> None:
    bundle = _make_bundle(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    desktop_like = _resolve(
        bundle=bundle,
        prompt="Review this SwiftUI diff",
        cwd=workspace,
        host_scope="desktop-client",
    )
    wrong_host = _resolve(
        bundle=bundle,
        prompt="Review this SwiftUI diff",
        cwd=workspace,
        host_scope="xcode",
    )
    filtered_out = _resolve(
        bundle=bundle,
        prompt="Review this SwiftUI diff",
        cwd=workspace,
        skills_filter=["fetch-apple-docs"],
    )

    assert desktop_like is not None
    assert desktop_like.selected_owner == OWNER
    assert wrong_host is None
    assert filtered_out is None


def test_explicit_downstream_domain_route_preserves_parent_owner(tmp_path: Path) -> None:
    bundle = _make_bundle(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    selection = _resolve(
        bundle=bundle,
        prompt=f"${REVIEW} review this iOS branch diff",
        cwd=workspace,
    )

    assert selection is not None
    assert selection.selected_owner == OWNER


def test_explicit_owner_or_focused_specialist_suppresses_parent_owner(
    tmp_path: Path,
) -> None:
    bundle = _make_bundle(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    explicit_owner = _resolve(
        bundle=bundle,
        prompt=f"${OWNER} review this iOS branch diff",
        cwd=workspace,
    )
    focused_specialist = _resolve(
        bundle=bundle,
        prompt=f"${DECISION} stress test this iOS architecture decision",
        cwd=workspace,
    )
    other_plugin = _resolve(
        bundle=bundle,
        prompt="$other-plugin:some-skill review this iOS branch diff",
        cwd=workspace,
    )

    assert explicit_owner is None
    assert focused_specialist is None
    assert other_plugin is None
