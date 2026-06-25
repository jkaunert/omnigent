"""Manifest-driven route selection for bundled Codex skills.

This is the narrow adapter layer between an Omnigent bundle manifest and a
stock Codex surface. It consumes the optional ``routerSelection`` block from
``.codex-plugin/plugin.json`` and produces two deterministic artifacts:

* a route-evidence text block that can be streamed before model output; and
* a system-prompt policy addendum that tells Codex which bundled skill owner
  has already been selected.

The selector is intentionally conservative. It only selects owners that are
declared by the bundle manifest and backed by a bundled ``SKILL.md`` file.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .executor import Message

_PLUGIN_MANIFEST = ".codex-plugin/plugin.json"
_EXPLICIT_SKILL_RE = re.compile(r"\$[A-Za-z0-9_.-]+:[A-Za-z0-9_.-]+")


@dataclass(frozen=True)
class RouterSelection:
    """Resolved route-selection result for one turn."""

    selected_owner: str
    selected_skill_name: str
    route_block: str
    prompt_addendum: str


def resolve_router_selection(
    *,
    bundle_dir: Path | None,
    messages: list[Message],
    cwd: str | None,
    host_scope: str | None,
    skills_filter: str | list[str],
) -> RouterSelection | None:
    """Resolve a bundle manifest's ``routerSelection`` for one Codex turn.

    :param bundle_dir: Extracted bundle root containing
        ``.codex-plugin/plugin.json`` and ``skills/``.
    :param messages: Conversation messages for the turn. The latest user text
        drives prompt-signal matching.
    :param cwd: Workspace directory used for optional file/extension signals.
    :param host_scope: Current host surface. Manifests may constrain selection
        with ``routerSelection.hostScopes``.
    :param skills_filter: Effective Codex skill exposure filter. If the
        selected skill is not exposed, no route is selected.
    :returns: A deterministic route selection, or ``None`` when the bundle has
        no applicable manifest route.
    """
    if bundle_dir is None or skills_filter == "none":
        return None

    manifest_path = bundle_dir / _PLUGIN_MANIFEST
    manifest = _read_manifest(manifest_path)
    if manifest is None:
        return None

    router = manifest.get("routerSelection")
    if not isinstance(router, Mapping):
        return None

    if not _host_scope_matches(router.get("hostScopes"), host_scope):
        return None

    prompt = _latest_user_text(messages)
    suppression = router.get("suppression")
    if (
        isinstance(suppression, Mapping)
        and suppression.get("whenExplicitSkillSelected") is True
        and _EXPLICIT_SKILL_RE.search(prompt)
    ):
        return None

    selected_owner = _selected_owner(router, prompt, cwd)
    if selected_owner is None:
        return None

    plugin_name = manifest.get("name")
    if not isinstance(plugin_name, str) or not plugin_name:
        return None

    skill_name = _skill_name_for_owner(selected_owner, plugin_name)
    if skill_name is None:
        return None

    if isinstance(skills_filter, list) and skill_name not in skills_filter:
        return None

    skill_path = bundle_dir / "skills" / skill_name / "SKILL.md"
    try:
        skill_text = skill_path.read_text(encoding="utf-8")
    except OSError:
        return None

    route_block = _route_block(selected_owner)
    prompt_addendum = _prompt_addendum(
        selected_owner=selected_owner,
        skill_name=skill_name,
        skill_path=skill_path,
        bundle_dir=bundle_dir,
        skill_text=skill_text,
    )
    return RouterSelection(
        selected_owner=selected_owner,
        selected_skill_name=skill_name,
        route_block=route_block,
        prompt_addendum=prompt_addendum,
    )


def apply_router_prompt_addendum(system_prompt: str, selection: RouterSelection | None) -> str:
    """Append route-selection policy text to a system prompt when selected."""
    if selection is None:
        return system_prompt
    if system_prompt:
        return f"{system_prompt.rstrip()}\n\n{selection.prompt_addendum}"
    return selection.prompt_addendum


def _read_manifest(path: Path) -> Mapping[str, Any] | None:
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return parsed if isinstance(parsed, Mapping) else None


def _host_scope_matches(value: object, host_scope: str | None) -> bool:
    if not isinstance(value, Sequence) or isinstance(value, str):
        return True
    scopes = {scope for scope in value if isinstance(scope, str)}
    return not scopes or (host_scope is not None and host_scope in scopes)


def _selected_owner(router: Mapping[str, Any], prompt: str, cwd: str | None) -> str | None:
    domains = router.get("domains")
    if isinstance(domains, Sequence) and not isinstance(domains, str):
        for domain in domains:
            if not isinstance(domain, Mapping):
                continue
            if not _domain_matches(domain, prompt, cwd):
                continue
            selected = domain.get("select")
            if isinstance(selected, str) and selected:
                return selected

    top_level = router.get("topLevelOwner")
    if isinstance(top_level, str) and top_level:
        return top_level
    return None


def _domain_matches(domain: Mapping[str, Any], prompt: str, cwd: str | None) -> bool:
    prompt_lc = prompt.lower()
    signals = domain.get("promptSignals")
    if isinstance(signals, Sequence) and not isinstance(signals, str):
        for signal in signals:
            if isinstance(signal, str) and signal.lower() in prompt_lc:
                return True

    workspace_files = domain.get("workspaceFiles")
    if _workspace_file_matches(workspace_files, cwd):
        return True

    workspace_extensions = domain.get("workspaceExtensions")
    return _workspace_extension_matches(workspace_extensions, cwd)


def _workspace_file_matches(value: object, cwd: str | None) -> bool:
    root = _workspace_root(cwd)
    if root is None or not isinstance(value, Sequence) or isinstance(value, str):
        return False
    for filename in value:
        if isinstance(filename, str) and filename and (root / filename).exists():
            return True
    return False


def _workspace_extension_matches(value: object, cwd: str | None) -> bool:
    root = _workspace_root(cwd)
    if root is None or not isinstance(value, Sequence) or isinstance(value, str):
        return False
    suffixes = [
        f".{ext.lstrip('.').lower()}"
        for ext in value
        if isinstance(ext, str) and ext.strip()
    ]
    if not suffixes:
        return False
    try:
        children = list(root.iterdir())
    except OSError:
        return False
    return any(child.name.lower().endswith(tuple(suffixes)) for child in children)


def _workspace_root(cwd: str | None) -> Path | None:
    if cwd is None:
        return None
    root = Path(cwd)
    return root if root.is_dir() else None


def _latest_user_text(messages: list[Message]) -> str:
    for message in reversed(messages):
        if not isinstance(message, Mapping):
            continue
        if message.get("role") != "user":
            continue
        return _content_to_text(message.get("content"))
    return ""


def _content_to_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, Mapping):
        text = content.get("text")
        return text if isinstance(text, str) else ""
    if isinstance(content, Sequence) and not isinstance(content, bytes | bytearray | str):
        parts = [_content_to_text(item) for item in content]
        return "\n".join(part for part in parts if part)
    return ""


def _skill_name_for_owner(owner: str, plugin_name: str) -> str | None:
    prefix = f"{plugin_name}:"
    if not owner.startswith(prefix):
        return None
    name = owner[len(prefix) :]
    return name or None


def _route_block(selected_owner: str) -> str:
    return (
        "Routing: orchestrator-led\n\n"
        "Activated skills\n"
        f"- `{selected_owner}`"
    )


def _prompt_addendum(
    *,
    selected_owner: str,
    skill_name: str,
    skill_path: Path,
    bundle_dir: Path,
    skill_text: str,
) -> str:
    return (
        "[Omnigent routerSelection]\n"
        f"The bundle manifest selected `{selected_owner}` for this turn.\n"
        "Omnigent already emitted the route-evidence block before your response. "
        "Continue after that block; do not repeat or alter it.\n"
        f"Use the bundled `{skill_name}` skill instructions below as active policy.\n"
        f"Selected skill path: `{skill_path}`.\n"
        f"Bundle root: `{bundle_dir}`.\n"
        f"Resolve relative paths in that SKILL.md from `{skill_path.parent}`.\n\n"
        f"{skill_text}"
    )
