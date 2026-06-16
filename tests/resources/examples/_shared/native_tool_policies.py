"""Sample policy functions for testing PreToolUse/PostToolUse enforcement."""

from __future__ import annotations

from omnigent.policies.schema import PolicyEvent, PolicyResponse

_ALLOW: PolicyResponse = {"result": "ALLOW"}

# Native file-write tool wire names across the coding harnesses, surfaced to a
# TOOL_CALL policy by each harness's pre-tool gate:
#   - antigravity SDK bundled tools (``BuiltinTools``): ``create_file`` /
#     ``edit_file`` (see
#     ``omnigent.inner.antigravity_executor._NATIVE_TOOL_WIRE_NAMES``)
#   - Claude Code / Codex native tools (PreToolUse hook): ``Write`` / ``Edit``
#   - Pi native tools (lowercase, pi ``tool_call`` hook): ``write`` / ``edit``
# This is the deny set the live bug-bash used to prove a native ``create_file``
# bypassed an ``on:[tool_call]`` deny on pre-#284 main.
_NATIVE_FILE_WRITE_TOOLS = frozenset(
    {"create_file", "edit_file", "Write", "Edit", "write", "edit"}
)


def block_native_file_writes(event: PolicyEvent) -> PolicyResponse:
    """
    Deny every native file-write tool call (``create_file`` / ``edit_file`` /
    ``Write`` / ``Edit`` / ``write`` / ``edit``) at the TOOL_CALL phase.

    A harness-agnostic deny used by the antigravity policy-gating e2e
    acceptance test: the agent's model is asked to write a sentinel file with
    its bundled native ``create_file`` tool, and this policy must block the
    call BEFORE it runs so nothing reaches disk. The callable self-selects
    (returns ALLOW for every non-matching event), so no ``on:`` field is
    required in the YAML.

    The DENY verdict is what #284's ``PreToolCallDecideHook`` consults via
    ``AntigravityExecutor._evaluate_tool_call_policy`` — on pre-#284 main the
    native call was never routed through policy and wrote to disk regardless.

    :param event: V0 event dict with ``type``, ``target``, ``data``,
        ``context`` keys. For a tool call, ``data`` is
        ``{"name": "<wire-name>", "arguments": {...}}``.
    :returns: V0 decision dict — DENY for a native file-write call, ALLOW
        otherwise.
    """
    if event.get("type") != "tool_call":
        return _ALLOW

    data = event.get("data")
    tool_name: str = data.get("name", "") if isinstance(data, dict) else ""
    if tool_name not in _NATIVE_FILE_WRITE_TOOLS:
        return _ALLOW

    return {
        "result": "DENY",
        "reason": (
            f"Native file-write tool {tool_name!r} is denied by the "
            "on:[tool_call] guardrail policy."
        ),
    }


def block_bash_rm(event: PolicyEvent) -> PolicyResponse:
    """
    Block Bash tool calls that contain ``rm``.

    Returns ALLOW for non-tool-call events and tool calls that aren't
    Bash or don't contain ``rm``.

    :param event: V0 event dict with ``type``, ``target``, ``data``,
        ``context`` keys.
    :returns: V0 decision dict.
    """
    if event.get("type") != "tool_call":
        return _ALLOW

    data = event.get("data")
    if not isinstance(data, dict):
        return _ALLOW
    tool_name: str = data.get("name", "")
    if tool_name != "Bash":
        return _ALLOW

    args = data.get("arguments")
    command: str = args.get("command", "") if isinstance(args, dict) else ""
    if "rm " in command or command.startswith("rm"):
        return {
            "result": "DENY",
            "reason": "Destructive rm commands are blocked by admin policy.",
        }

    return _ALLOW


def block_sensitive_output(event: PolicyEvent) -> PolicyResponse:
    """
    Flag tool results that contain ``/etc/passwd`` content.

    Fires on ``tool_result`` phase. Returns DENY with a reason so the
    PostToolUse hook surfaces a warning to Claude.

    :param event: V0 event dict.
    :returns: V0 decision dict.
    """
    if event.get("type") != "tool_result":
        return _ALLOW

    data = event.get("data")
    if not isinstance(data, str):
        data = str(data)
    if "root:x:0:0" in data:
        return {
            "result": "DENY",
            "reason": "Tool output contains sensitive system data.",
        }

    return _ALLOW
