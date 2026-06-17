"""
REPL approval-flow e2e test.

Spawns ``omnigent chat examples/agents/ask-demo/`` as a subprocess
under a pseudo-TTY (pexpect), feeds real input, and asserts
the agent responds after the user approves a policy ASK.
This exercises the full Phase 10 path — prompt_toolkit's
real input loop, the SSE stream consuming ``ElicitationRequest``
events, the REPL's future-based approval wiring, and the
server PATCHing the verdict back through DBOS.

Unlike ``test_policies_e2e.py`` (polling API, background=True),
this test drives the REPL through the actual streaming code
path — the code path a human types into at the terminal.

Prerequisites:
    - ``pexpect`` installed (4.9+).
    - ``--llm-api-key`` pytest option set to a valid key for
      ``openai/gpt-4o``.
    - ``ap`` on ``PATH`` resolving to this worktree's entry
      point (set ``PYTHONPATH`` so the editable install from
      a sibling worktree doesn't shadow it).

Usage::

    PYTHONPATH=/home/ubuntu/omnigent-policies:\\
    /home/ubuntu/omnigent-policies/sdks/python-client:\\
    /home/ubuntu/omnigent-policies/sdks/frontend \\
    python -m pytest tests/e2e/test_repl_approval_e2e.py \\
      --llm-api-key $(cat /tmp/mykey) -v
"""

from __future__ import annotations

import contextlib
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest

pexpect = pytest.importorskip("pexpect")

_ASK_DEMO_DIR = Path(__file__).resolve().parents[1] / "resources" / "agents" / "ask-demo"
_FIXTURES_DIR = Path(__file__).resolve().parents[1] / "_fixtures" / "agents"
_TOOL_GATE_DIR = _FIXTURES_DIR / "e2e-tool-gate"
_SUBAGENT_GATE_DIR = _FIXTURES_DIR / "e2e-subagent-gate"
_LABEL_ASK_GATE_DIR = _FIXTURES_DIR / "e2e-label-ask-gate"
_OUTPUT_GATE_DIR = _FIXTURES_DIR / "e2e-output-gate"
_TOOL_RESULT_GATE_DIR = _FIXTURES_DIR / "e2e-tool-result-gate"
_SUBAGENT_TOOL_GATE_DIR = _FIXTURES_DIR / "e2e-subagent-tool-gate"

# Regex to strip ANSI escape codes from pexpect output before
# asserting. prompt_toolkit emits heavy styling — searching for
# substrings ("approval required", "Hi") against the raw bytes
# finds them most of the time but is flaky on split sequences.
_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")

# The visible input-prompt glyph the REPL re-renders once
# prompt_toolkit's input widget is armed and ready to accept a
# submission. Matching it AFTER the welcome banner is the fix for
# the dropped-first-send race: the welcome block (agent name) is
# painted by the boot path BEFORE the prompt-toolkit application is
# focused, so a ``send()`` issued the instant the welcome text
# appears lands in a not-yet-live input and is silently dropped —
# the turn never starts and every downstream ``expect`` times out.
# ``❯`` sits mid-left in the layout, so unlike the far-right
# ``state:`` toolbar badge (which wraps/truncates at the screen edge
# depending on the agent-name length, e.g. ``state: sleepi\rn``) it
# is width-independent and survives PTY rendering. This mirrors the
# merged REPL smoke / Ctrl+C e2e tests, which sync on the same ``❯``
# prompt rather than the removed ``You>`` / ``state:`` markers.
_PROMPT_READY = "❯"
_RUNNING_MARKER = "working"
_TURN_SETTLED = r"state:\s*s|ready\s+/help"


def _strip_ansi(text: str) -> str:
    """
    Remove ANSI escape codes from a pexpect buffer slice.

    :param text: Captured output with escape sequences.
    :returns: Plain text suitable for substring assertions.
    """
    return _ANSI_RE.sub("", text)


@pytest.fixture(scope="module")
def repl_env(llm_api_key: str) -> dict[str, str]:
    """
    Build the env dict for ``omnigent chat`` — OPENAI_API_KEY plus
    whatever PYTHONPATH the outer shell already provides (so
    ``omnigent`` + ``omnigent_client`` resolve to this
    worktree, not the sibling editable install).

    :param llm_api_key: The API key for the LLM.
    :returns: Env mapping for ``pexpect.spawn``.
    """
    env: dict[str, str] = {
        **os.environ,
        "OPENAI_API_KEY": llm_api_key,
        # Force ANSI on — pexpect captures everything, stripping
        # happens per-assertion via _strip_ansi.
        "TERM": "xterm-256color",
        # Disable prompt_toolkit's alt-screen / mouse reporting
        # so the buffer doesn't fill with cursor-position-query
        # sequences that throw off expect matches.
        "PROMPT_TOOLKIT_NO_CPR": "1",
    }
    return env


def _require_omnigent_cli() -> str:
    """
    Resolve the CLI path. Prefers the framework's own
    ``omnigent`` binary (via the running pytest interpreter's
    venv) over a sibling ``ap`` binary on PATH — the legacy
    ``omnigent`` ``ap`` CLI doesn't understand
    Omnigent-format fixtures.

    :returns: Absolute path to an executable.
    """
    venv_omnigent = Path(sys.executable).parent / "omnigent"
    if venv_omnigent.exists():
        return str(venv_omnigent)
    path = shutil.which("omnigent") or shutil.which("ap")
    if path is None:
        pytest.skip("Neither omnigent nor omnigent CLI on PATH")
    return path


@pytest.fixture(scope="module")
def ap_cli() -> str:
    """Session-scoped resolved ``ap`` binary."""
    return _require_omnigent_cli()


def _wait_for_prompt_ready(
    child: Any,
    timeout: float = 30.0,
    welcome_pattern: str = "ask.demo",
) -> None:
    """
    Wait until the REPL is actually ready to accept a submission.

    ``omnigent run <path>`` starts a local server, waits for
    health, then launches the REPL. Two synchronization points,
    in order:

    1. The welcome block — ``TimedFormatter`` renders the agent
       name (dashes → spaces), so ``welcome_pattern`` proves the
       right agent booted. But the welcome text is painted by the
       boot path BEFORE prompt_toolkit focuses its input widget,
       so matching it alone is NOT sufficient: a ``send()`` issued
       the instant it appears races the widget and is dropped.
    2. The ``❯`` input prompt — re-rendered once the widget is
       armed. Waiting for it after the welcome closes the
       dropped-first-send race that made every approval test time
       out at the first ``approval required`` expect.

    Using a generous timeout — agent upload + DBOS boot add
    latency on cold starts.

    :param child: Active pexpect child.
    :param timeout: Max seconds to wait for EACH of the two
        synchronization points.
    :param welcome_pattern: Regex pattern to match in the
        welcome block. Defaults to ``"ask.demo"`` (for the
        ``ask-demo`` fixture); pass a different pattern for
        other fixtures.
    """
    child.expect(welcome_pattern, timeout=timeout)
    child.expect(_PROMPT_READY, timeout=timeout)


def _read_pending(child: Any, seconds: float = 0.2) -> str:
    """
    Non-blocking read of everything buffered so far.

    :param child: pexpect child.
    :param seconds: Small timeout so the call returns promptly
        after the buffer is drained.
    :returns: Whatever pexpect had queued, stripped of ANSI.
    """
    with contextlib.suppress(pexpect.EOF):
        child.expect(pexpect.TIMEOUT, timeout=seconds)
    captured = child.before or ""
    if isinstance(captured, bytes):
        captured = captured.decode("utf-8", errors="replace")
    return _strip_ansi(captured)


def _completed_turn_text(child: Any, timeout: int) -> str:
    """Wait for a running turn to settle and return stripped output."""
    child.expect(_RUNNING_MARKER, timeout=timeout)
    running_frame = child.before or ""
    child.expect(_TURN_SETTLED, timeout=timeout)
    captured = running_frame + (child.before or "") + (child.after or "")
    if isinstance(captured, bytes):
        captured = captured.decode("utf-8", errors="replace")
    return _strip_ansi(captured)


def _assistant_turn_text(child: Any, timeout: int) -> str:
    """Wait for turn completion and assert assistant output rendered."""
    captured = _completed_turn_text(child, timeout=timeout)
    _assert_assistant_reply_rendered(captured, "turn completion")
    return captured


def _deny_turn_text(child: Any, timeout: int) -> str:
    """Wait for the policy-deny sentinel and return stripped turn output."""
    captured = _completed_turn_text(child, timeout=timeout)
    assert "Denied by policy" in captured, (
        f"DENY sentinel did not render after refusal.\nCaptured:\n{captured[:1500]}"
    )
    return captured


def _assert_assistant_reply_rendered(text: str, context: str) -> None:
    """Assert the prompt-toolkit assistant header rendered for a real reply."""
    assert "◆" in text, (
        f"No assistant reply (◆ header) appeared after {context}.\nCaptured:\n{text[:1500]}"
    )


def test_repl_single_approval_allows_llm_response(
    ap_cli: str,
    repl_env: dict[str, str],
) -> None:
    """
    Drive the full approval → LLM → response loop through the
    REPL.

    Scenario: the ``ask-demo`` agent declares
    ``always_ask_on_input`` (a policy at INPUT that
    always ASKs). We send "Hello", expect the approval
    prompt, type "y", and expect the LLM's real reply.

    Why this is the right test layer: unit tests can stub the
    approval hook, but only a real pexpect run proves the
    end-to-end stack — prompt_toolkit's raw keystroke
    handling, the SDK's ``ElicitationRequest`` event routing,
    the server's ``response.elicitation_request`` emission, the
    session ``approval`` event reply path, and DBOS wake
    semantics — all cohere in production.

    Load-bearing assertion: EXACTLY ONE approval prompt. The
    "three approvals for one message" bug (prior bug:
    ``_enforce_input_policies`` walked history from index 0
    each invocation) would fail this test by rendering
    multiple ``⚠ approval required`` banners. Counting on
    the ANSI-stripped buffer is the regression guard.
    """
    child = pexpect.spawn(
        ap_cli,
        ["run", str(_ASK_DEMO_DIR)],
        env=repl_env,
        encoding="utf-8",
        codec_errors="replace",
        dimensions=(40, 120),  # rows, cols
        timeout=60,
    )
    try:
        _wait_for_prompt_ready(child, timeout=60)

        # Send the user message and wait for the approval
        # banner. 'approval required' is the human-readable
        # header emitted by the REPL's _make_approval_prompt.
        child.send("Hello" + "\r")
        child.expect("approval required", timeout=30)
        # The preview line should echo what we just typed —
        # confirms the server-side INPUT-phase eval and the
        # client-side SSE parsing both agreed on the payload.
        child.expect("Hello", timeout=5)

        # Approve. Any input while an approval is pending is
        # routed to the verdict future — no special slash
        # command, just "y".
        child.send("y" + "\r")
        # Echo line confirms the REPL resolved the verdict
        # (sanity on the main-loop routing).
        child.expect("approved", timeout=5)

        # Now wait for the LLM's actual reply to fully land. The
        # elapsed-time label (``<n>.<n>s``) is rendered by
        # ``TimedFormatter.format_response_end`` ONLY when a
        # response actually completes — an errored turn renders an
        # error panel and never paints it — so syncing on it is
        # itself a "the turn produced a real reply" signal.
        buffered = _assistant_turn_text(child, timeout=30)

        # Exactly one approval banner — regression guard for
        # the "three approvals for one message" bug.
        approval_count = buffered.count("approval required")
        # The `.expect("approval required")` above already
        # consumed the first banner from pexpect's buffer,
        # so anything here would be an extra. Zero is the
        # correct assertion.
        assert approval_count == 0, (
            "Saw "
            f"{approval_count} extra approval banners after the first — "
            "`_enforce_input_policies` re-firing on same message?\n"
            f"Buffer snippet:\n{buffered[:800]}"
        )
        # The agent replied with real assistant text. The ``◆``
        # diamond is the formatter's assistant-message header
        # (``_DiamondMarkdown`` / ``◆ <model>``) — committed to the
        # transcript ONLY when the model returns text, and never on
        # the user-prompt echo (``❯``) or an error panel. Asserting
        # it (instead of a bare ``[A-Za-z]{3,}`` substring, which an
        # error box's "inner executor error" prose also satisfies)
        # keeps the "approval surfaces the LLM reply" tooth.
        _assert_assistant_reply_rendered(buffered, "approval")
    finally:
        # Best-effort clean shutdown — /quit is the REPL's
        # documented exit command, but if it's stuck we fall
        # back to SIGTERM.
        try:
            child.send("/quit" + "\r")
            child.expect(pexpect.EOF, timeout=5)
        except Exception:
            pass
        if child.isalive():
            child.terminate(force=True)


def test_repl_refusal_shows_deny_sentinel(
    ap_cli: str,
    repl_env: dict[str, str],
) -> None:
    """
    Same flow, user refuses → server substitutes the DENY
    sentinel → that text lands as the assistant reply.

    This proves the fail-closed path end-to-end: hook returns
    False → SDK POSTs a session ``approval`` event → server's
    ``_await_elicitation`` parses verdict, hits the DENY
    branch, ``_enforce_input_policies`` returns the
    ``[Denied by policy: ...]`` sentinel, and
    ``_persist_input_deny_sentinel`` surfaces it as the
    assistant message the REPL renders.
    """
    child = pexpect.spawn(
        ap_cli,
        ["run", str(_ASK_DEMO_DIR)],
        env=repl_env,
        encoding="utf-8",
        codec_errors="replace",
        dimensions=(40, 120),
        timeout=60,
    )
    try:
        _wait_for_prompt_ready(child, timeout=60)

        child.send("Hello" + "\r")
        child.expect("approval required", timeout=30)
        child.expect("Hello", timeout=5)

        # Refuse. Typing anything non-affirmative refuses —
        # "n" is the natural keyboard muscle memory.
        child.send("n" + "\r")
        child.expect("refused", timeout=5)

        # The server emits the DENY sentinel as the assistant
        # reply. Exact reason string is shaped by the
        # Policy spec in ask-demo/config.yaml
        # ("Confirm this message before I process it.").
        child.expect(r"Denied by policy", timeout=10)
    finally:
        try:
            child.send("/quit" + "\r")
            child.expect(pexpect.EOF, timeout=5)
        except Exception:
            pass
        if child.isalive():
            child.terminate(force=True)


def test_repl_two_turns_fires_one_approval_per_turn(
    ap_cli: str,
    repl_env: dict[str, str],
) -> None:
    """
    Regression guard for the multi-turn duplicate-ASK bug.

    Scenario: two consecutive turns in the same conversation.
    Each turn must fire EXACTLY ONE approval. The bug this
    pins: `_enforce_input_policies` previously walked history
    from index 0 on every new workflow, re-ASKing historical
    user messages from prior turns.

    The fix: skip past the last assistant message on fresh
    invocation. The fact that we only see one approval on
    turn 2 proves the prior user message from turn 1 is NOT
    being re-enforced.
    """
    child = pexpect.spawn(
        ap_cli,
        ["run", str(_ASK_DEMO_DIR)],
        env=repl_env,
        encoding="utf-8",
        codec_errors="replace",
        dimensions=(40, 120),
        timeout=60,
    )
    try:
        _wait_for_prompt_ready(child, timeout=60)

        # Turn 1: approve, wait for reply.
        child.send("Hello" + "\r")
        child.expect("approval required", timeout=30)
        child.send("y" + "\r")
        child.expect("approved", timeout=5)
        # Wait for the turn to fully land — the stream-done
        # elapsed-time label is the cleanest signal.
        _assistant_turn_text(child, timeout=30)

        # Drain anything queued so the next expect starts
        # from a clean slate. Generous wait because the REPL
        # emits a flurry of cursor-position codes after the
        # response completes — we want them all absorbed
        # before sending the next input.
        _read_pending(child, seconds=1.5)

        # Turn 2: a brand-new message in the same
        # conversation. If the old bug were present, the
        # REPL would render TWO approval banners here (one
        # for the historical "Hello", one for "kk"). The
        # fix means exactly one banner appears — for "kk".
        child.send("kk" + "\r")
        # Capture the buffer from the send through the
        # approval banner so we can inspect the preview line
        # — pexpect's .expect on "preview:\\s*kk" has been
        # flaky against heavily-styled output. Match on the
        # banner, then scan the drained buffer afterwards.
        child.expect("approval required", timeout=30)
        # Pull the remaining banner text (policy / reason /
        # preview / prompt line) into a buffer we can assert
        # against with substring checks after ANSI stripping.
        banner_tail = _read_pending(child, seconds=1.5)
        assert "kk" in banner_tail, (
            "Turn 2 banner's preview did not contain 'kk' — the fix for "
            "`_enforce_input_policies` re-firing on historical messages "
            "may have regressed.\n"
            f"Tail captured (ANSI-stripped):\n{banner_tail[:800]}"
        )
        # And turn 2's banner window MUST NOT contain the prior
        # turn's 'Hello' — that would be the historical-message
        # regression (a second banner previewing the turn-1
        # message). The preview now renders the gated content as a
        # JSON message object (``preview: {"role": "user",
        # "content": [{"type": "input_text", "text": "kk"}]}``), so
        # the old ``"preview: Hello"`` literal could never match the
        # current format and silently caught nothing. ``banner_tail``
        # is drained only AFTER turn 2's ``approval required``, so
        # turn 1's already-consumed 'Hello' cannot leak in — any
        # 'Hello' here is a re-fired historical ASK.
        assert "Hello" not in banner_tail, (
            "Turn 2's approval window previewed the prior turn's 'Hello' — "
            "`_enforce_input_policies` re-firing on historical messages.\n"
            f"Tail:\n{banner_tail[:800]}"
        )

        # Approve and confirm one-and-done.
        child.send("y" + "\r")
        child.expect("approved", timeout=5)
        _assistant_turn_text(child, timeout=30)

        # Final sweep: no extra approval banners after the
        # two we expected.
        buffered = _read_pending(child, seconds=1.0)
        extras = buffered.count("approval required")
        assert extras == 0, f"Unexpected extra approval banner after turn 2:\n{buffered[:800]}"
    finally:
        try:
            child.send("/quit" + "\r")
            child.expect(pexpect.EOF, timeout=5)
        except Exception:
            pass
        if child.isalive():
            child.terminate(force=True)


def test_repl_approve_always_caches_for_later_turns(
    ap_cli: str,
    repl_env: dict[str, str],
) -> None:
    """
    End-to-end coverage for the "approve always" cache.

    Turn 1: user types "a" at the approval prompt. The
    ``_ApprovalState`` caches ``(always_ask_on_input, input)``
    for this REPL session.

    Turn 2: the same policy fires at the same phase. The hook
    short-circuits on the cache — prints a muted
    ``auto-approved`` audit line and returns True WITHOUT
    rendering the ``⚠ approval required`` banner. The LLM
    proceeds as if the user pre-approved.

    Load-bearing assertions:

    1. Turn 2 must show ``auto-approved`` in the transcript —
       silent auto-approve would be security-hostile (users
       forget they flipped "always" on).
    2. Turn 2 must NOT show ``⚠ approval required`` — that's
       the whole point of the cache; a user who typed "a"
       expects no more prompting for this policy in this
       session.
    """
    child = pexpect.spawn(
        ap_cli,
        ["run", str(_ASK_DEMO_DIR)],
        env=repl_env,
        encoding="utf-8",
        codec_errors="replace",
        dimensions=(40, 120),
        timeout=60,
    )
    try:
        _wait_for_prompt_ready(child, timeout=60)

        # Turn 1: approve always.
        child.send("Hello" + "\r")
        child.expect("approval required", timeout=30)
        child.send("a" + "\r")
        # Echo line confirms the REPL parsed "a" as
        # APPROVE_ALWAYS, not as a generic non-"y" refusal.
        child.expect("approved always", timeout=5)
        _assistant_turn_text(child, timeout=30)

        # Drain between turns so the next buffer is clean.
        _read_pending(child, seconds=1.5)

        # Turn 2: the auto-approved audit line must appear
        # AND the banner must NOT. After .expect() lands on
        # the elapsed-time marker, ``child.before`` holds the
        # full span from the last expect up to (but not
        # including) the match. That's the whole turn 2
        # output — banner (if any) + auto-approved line (if
        # any) + LLM response + elapsed-time prefix.
        child.send("follow up please" + "\r")
        turn_two = _assistant_turn_text(child, timeout=45)

        assert "auto-approved" in turn_two, (
            "Turn 2 did not render the auto-approve audit line.\n"
            f"Captured (ANSI-stripped, {len(turn_two)} chars):\n{turn_two[:1500]}"
        )
        assert "approval required" not in turn_two, (
            "Turn 2 rendered the approval banner even though the user "
            "said 'always' on turn 1 — cache lookup is broken.\n"
            f"Captured:\n{turn_two[:1500]}"
        )
    finally:
        try:
            child.send("/quit" + "\r")
            child.expect(pexpect.EOF, timeout=5)
        except Exception:
            pass
        if child.isalive():
            child.terminate(force=True)


# ── TOOL_CALL-phase approval coverage ─────────────────────
#
# Phase 6 wired the TOOL_CALL enforcement site in
# ``_execute_tools``. These tests prove the full round-trip:
# user message → LLM emits tool_call → policy ASKs → server
# parks → SSE surfaces ``response.elicitation_request`` →
# REPL renders → user answers → SDK POSTs a session approval
# event → server wakes the parked workflow → tool dispatches (on approve)
# or sentinel replaces output (on refuse).


def test_repl_tool_call_approval_allows_tool_to_run(
    ap_cli: str,
    repl_env: dict[str, str],
) -> None:
    """
    TOOL_CALL ASK → approve → tool runs → LLM responds.

    The ``e2e-tool-gate`` fixture's AGENTS.md instructs the
    LLM to call the ``echo`` tool for every user message.
    The policy ``ask_before_echo`` ASKs on every
    ``tool_call:echo``. After the user approves, the tool
    runs and its output (prefixed ``echo:``) flows back to
    the LLM, which includes it in the final reply.

    The banner's ``phase`` field must be ``tool_call`` — not
    ``input`` — which is the critical distinction from the
    INPUT-phase tests above. Proves the TOOL_CALL site is
    wired and end-to-end correct.
    """
    child = pexpect.spawn(
        ap_cli,
        ["run", str(_TOOL_GATE_DIR)],
        env=repl_env,
        encoding="utf-8",
        codec_errors="replace",
        dimensions=(40, 120),
        timeout=60,
    )
    try:
        _wait_for_prompt_ready(child, timeout=60, welcome_pattern="e2e.tool.gate")
        child.send("testing123" + "\r")
        child.expect("approval required", timeout=45)
        banner_tail = _read_pending(child, seconds=1.0)
        # Must be the TOOL_CALL phase (not INPUT) — this is
        # the whole point of the test.
        assert "tool_call" in banner_tail, (
            "Banner phase field was not 'tool_call' — the ASK may have "
            "fired at a different phase than expected.\n"
            f"Banner tail:\n{banner_tail[:800]}"
        )
        # Policy name and echo tool should be on the banner.
        assert "ask_before_echo" in banner_tail, (
            f"Policy name missing from banner.\nBanner:\n{banner_tail[:800]}"
        )
        child.send("y" + "\r")
        child.expect("approved", timeout=5)
        # Wait for turn completion (elapsed-time marker).
        full_turn = _assistant_turn_text(child, timeout=45)
        # The echo tool runs; its output prefix 'echo:' should
        # reach the LLM's reply (the AGENTS.md tells it to
        # include the tool's output).
        assert "echo:" in full_turn or "testing123" in full_turn, (
            f"Tool output did not make it into the LLM's reply.\nCaptured:\n{full_turn[:1500]}"
        )
        _assert_assistant_reply_rendered(full_turn, "TOOL_CALL approval")
    finally:
        try:
            child.send("/quit" + "\r")
            child.expect(pexpect.EOF, timeout=5)
        except Exception:
            pass
        if child.isalive():
            child.terminate(force=True)


def test_repl_tool_call_refusal_blocks_tool(
    ap_cli: str,
    repl_env: dict[str, str],
) -> None:
    """
    TOOL_CALL ASK → refuse → tool NEVER runs → sentinel
    replaces output → LLM sees sentinel and typically relays
    that denial to the user.

    Load-bearing: the raw tool output MUST NOT reach the
    conversation — ``_enforce_tool_result_policy`` substitutes
    ``[Denied by policy: ...]``. This test is the end-to-end
    proof that the pre-persistence ordering holds under real
    streaming + DBOS parking.
    """
    child = pexpect.spawn(
        ap_cli,
        ["run", str(_TOOL_GATE_DIR)],
        env=repl_env,
        encoding="utf-8",
        codec_errors="replace",
        dimensions=(40, 120),
        timeout=60,
    )
    try:
        _wait_for_prompt_ready(child, timeout=60, welcome_pattern="e2e.tool.gate")
        child.send("testing456" + "\r")
        child.expect("approval required", timeout=45)
        child.send("n" + "\r")
        child.expect("refused", timeout=5)
        # Wait for the turn to complete. The LLM sees
        # the blocked sentinel as the tool output, then
        # either reports the denial or stops. Elapsed-time
        # marker signals the turn ended.
        full_turn = _deny_turn_text(child, timeout=60)
        # The sentinel must appear in the tool output path —
        # this is the regression guard for the pre-persist
        # ordering invariant.
        assert "Denied by policy" in full_turn, (
            "Tool result sentinel did not appear in the turn — "
            "pre-persistence enforcement may have regressed.\n"
            f"Captured:\n{full_turn[:1500]}"
        )
    finally:
        try:
            child.send("/quit" + "\r")
            child.expect(pexpect.EOF, timeout=5)
        except Exception:
            pass
        if child.isalive():
            child.terminate(force=True)


# ── Sub-agent approval tunneling ──────────────────────────
#
# When a sub-agent hits an ASK, the parked workflow is the
# SUB-AGENT's, but the ``response.elicitation_request`` must
# surface on the ROOT task's SSE stream so the REPL (which
# is attached to the root) sees it. This is the same
# tunneling path client-side tool calls use from within
# sub-agents — POLICIES.md §7 / workflow.py's
# ``_handle_policy_ask`` ``publish_target`` computation.


def test_repl_subagent_ask_tunnels_approval_to_root(
    ap_cli: str,
    repl_env: dict[str, str],
) -> None:
    """
    Sub-agent INPUT ASK → approval on ROOT SSE stream →
    REPL approves → sub-agent runs → parent integrates the
    sub-agent's reply and finishes the turn.

    Load-bearing:

    - The banner must appear on the root REPL — proves
      ``root_task_id``-based tunneling for the synthetic
      function_call works exactly like for client-side
      tool calls.
    - The banner's phase must be ``request`` — the sub-agent's
      gate, not the parent's. Both the policy_name and the
      phase field come from the SUB-AGENT's spec, so
      matching ``worker_input_gate`` + ``request`` on the
      banner proves the right engine fired.
    - After approving, the parent's reply must exist —
      proves the wake path unblocks the sub-agent, its LLM
      runs, the result flows to the parent, and the parent
      composes the final response.
    """
    child = pexpect.spawn(
        ap_cli,
        ["run", str(_SUBAGENT_GATE_DIR)],
        env=repl_env,
        encoding="utf-8",
        codec_errors="replace",
        dimensions=(40, 120),
        timeout=90,
    )
    try:
        _wait_for_prompt_ready(
            child,
            timeout=90,
            welcome_pattern="e2e.subagent.gate",
        )
        child.send("say hello" + "\r")
        # The approval banner may take a bit longer because
        # spawn + sub-agent boot fires first.
        child.expect("approval required", timeout=60)
        banner_tail = _read_pending(child, seconds=1.5)
        # Phase must be the request (INPUT) phase — the
        # sub-agent's INPUT site — and policy_name must be the
        # sub-agent's policy. These two together prove the
        # routing path: the ASK came from the WORKER's engine,
        # surfaced on the ROOT stream. The banner renders the
        # phase string verbatim from the policy's ``on_phases``
        # entry, which for an INPUT-phase gate is ``request``
        # (the worker fixture declares ``on_phases: [request]``);
        # the old assertion looked for ``input``, a phase label
        # the engine never emits on the banner.
        assert "request" in banner_tail, (
            "Sub-agent ASK banner did not show phase=request — routing may "
            "have attached the wrong phase or the ASK never tunneled "
            "to the root SSE stream.\n"
            f"Banner:\n{banner_tail[:800]}"
        )
        assert "worker_input_gate" in banner_tail, (
            "Sub-agent's policy name missing from root-surfaced banner — "
            "tunneling may have confused root/sub-agent identity.\n"
            f"Banner:\n{banner_tail[:800]}"
        )
        child.send("y" + "\r")
        child.expect("approved", timeout=5)
        # Let the full turn complete — sub-agent runs, returns,
        # parent summarizes, turn ends.
        full_turn = _assistant_turn_text(child, timeout=90)
        # The parent produced a real assistant reply after the
        # sub-agent approval. The ``◆`` diamond is the assistant
        # message header (``◆ <model>``), committed only when the
        # model returns text and never on an error panel — so it is
        # the "parent composed a final response" tooth. (A bare
        # ``[A-Za-z]{3,}`` word check would also pass on an error
        # box's prose, hiding a broken wake path.)
        _assert_assistant_reply_rendered(full_turn, "sub-agent approval")
    finally:
        try:
            child.send("/quit" + "\r")
            child.expect(pexpect.EOF, timeout=5)
        except Exception:
            pass
        if child.isalive():
            child.terminate(force=True)


# ── Label-driven ASK composition ──────────────────────────
#
# Tests the two-turn chain:
# - Turn 1 with a trigger token: FunctionPolicy ALLOWs and
#   writes a taint label.
# - Turn 2: Policy with ``condition: {tainted: "1"}``
#   fires ASK because the label persisted across the
#   workflow boundary.
#
# Complements ``test_label_gate_*`` in test_policies_e2e.py
# which cover the DENY variant via the polling API.


def test_repl_label_driven_ask_approves(
    ap_cli: str,
    repl_env: dict[str, str],
) -> None:
    """
    Two-turn label-ASK composition, approve path.

    Turn 1: user message contains ``BANANA_TRIGGER``. The
    FunctionPolicy writes ``tainted: "1"``; the gated policy's
    condition checks the pre-evaluation snapshot so does NOT
    fire yet. LLM responds normally.

    Turn 2: any message. The persisted label makes the
    Policy condition match → ASK. User approves → LLM
    runs normally for the second turn.

    Load-bearing: proves (a) FunctionPolicy label writes
    persist to the store and survive the sub-agent /
    workflow restart, (b) condition gates read
    the live cache on turn 2, (c) ASK composition with a
    write in the chain doesn't leak the write on refuse
    (that's a separate refuse test below).
    """
    child = pexpect.spawn(
        ap_cli,
        ["run", str(_LABEL_ASK_GATE_DIR)],
        env=repl_env,
        encoding="utf-8",
        codec_errors="replace",
        dimensions=(40, 120),
        timeout=60,
    )
    try:
        _wait_for_prompt_ready(
            child,
            timeout=60,
            welcome_pattern="e2e.label.ask.gate",
        )
        # Turn 1: trigger taint — no ASK fires this turn
        # (condition checks the pre-evaluation snapshot).
        child.send("hello BANANA_TRIGGER" + "\r")
        # The LLM still replies normally. Wait for turn end.
        _assistant_turn_text(child, timeout=45)
        turn_one = child.before or ""
        if isinstance(turn_one, bytes):
            turn_one = turn_one.decode("utf-8", errors="replace")
        turn_one = _strip_ansi(turn_one)
        # Turn 1 MUST NOT show an approval banner — the
        # taint label didn't exist when the condition was
        # checked.
        assert "approval required" not in turn_one, (
            "Turn 1 fired an ASK before the taint label was set — "
            "condition gate is reading the post-write snapshot.\n"
            f"Turn 1:\n{turn_one[:1500]}"
        )

        _read_pending(child, seconds=1.0)

        # Turn 2: label persists from the store → condition
        # matches → ASK fires.
        child.send("please continue" + "\r")
        child.expect("approval required", timeout=45)
        banner_tail = _read_pending(child, seconds=1.0)
        assert "ask_when_tainted" in banner_tail, (
            "Turn 2's banner didn't come from the label-gated policy.\n"
            f"Banner:\n{banner_tail[:800]}"
        )
        child.send("y" + "\r")
        child.expect("approved", timeout=5)
        # Turn 2 completes — LLM replies normally.
        _assistant_turn_text(child, timeout=45)
    finally:
        try:
            child.send("/quit" + "\r")
            child.expect(pexpect.EOF, timeout=5)
        except Exception:
            pass
        if child.isalive():
            child.terminate(force=True)


def test_repl_label_driven_ask_refuse_shows_sentinel(
    ap_cli: str,
    repl_env: dict[str, str],
) -> None:
    """
    Same composition, refuse path.

    Turn 2's ASK refused → server substitutes the DENY
    sentinel → REPL shows ``Denied by policy``. Proves the
    label-gated ASK's refuse branch goes through the same
    pre-persist sentinel path as INPUT DENY.
    """
    child = pexpect.spawn(
        ap_cli,
        ["run", str(_LABEL_ASK_GATE_DIR)],
        env=repl_env,
        encoding="utf-8",
        codec_errors="replace",
        dimensions=(40, 120),
        timeout=60,
    )
    try:
        _wait_for_prompt_ready(
            child,
            timeout=60,
            welcome_pattern="e2e.label.ask.gate",
        )
        # Turn 1: taint.
        child.send("hi BANANA_TRIGGER" + "\r")
        _assistant_turn_text(child, timeout=45)
        _read_pending(child, seconds=1.0)

        # Turn 2: ASK fires, user refuses.
        child.send("anything" + "\r")
        child.expect("approval required", timeout=45)
        child.send("n" + "\r")
        child.expect("refused", timeout=5)
        full_turn = _deny_turn_text(child, timeout=45)
        assert "Denied by policy" in full_turn, (
            "Refused label-gated ASK did not produce a DENY sentinel.\n"
            f"Captured:\n{full_turn[:1500]}"
        )
    finally:
        try:
            child.send("/quit" + "\r")
            child.expect(pexpect.EOF, timeout=5)
        except Exception:
            pass
        if child.isalive():
            child.terminate(force=True)


# ── OUTPUT-phase approval coverage ────────────────────────
#
# POLICIES.md §11.4: the raw assistant text must never reach
# ``conversation_items`` when OUTPUT policy DENYs —
# compaction could resurface it otherwise. These tests prove
# the pre-persistence ordering holds end-to-end when the user
# actually refuses the assistant reply.


def test_repl_output_ask_approve_surfaces_llm_reply(
    ap_cli: str,
    repl_env: dict[str, str],
) -> None:
    """
    OUTPUT ASK → approve → LLM reply appears verbatim.

    Proves the OUTPUT enforcement site in
    ``_handle_final_response`` doesn't mangle the text on
    approve — the original ``text`` passes through the
    helper unchanged and lands in the assistant message.
    """
    child = pexpect.spawn(
        ap_cli,
        ["run", str(_OUTPUT_GATE_DIR)],
        env=repl_env,
        encoding="utf-8",
        codec_errors="replace",
        dimensions=(40, 120),
        timeout=60,
    )
    try:
        _wait_for_prompt_ready(
            child,
            timeout=60,
            welcome_pattern="e2e.output.gate",
        )
        child.send("say hi" + "\r")
        # OUTPUT ASK fires AFTER the LLM generates. The
        # banner's phase must be ``response``.
        child.expect("approval required", timeout=45)
        banner_tail = _read_pending(child, seconds=1.0)
        assert "response" in banner_tail, (
            f"RESPONSE-phase banner missing 'response' phase marker.\nBanner:\n{banner_tail[:800]}"
        )
        assert "ask_on_output" in banner_tail, (
            f"Policy name missing.\nBanner:\n{banner_tail[:800]}"
        )
        child.send("y" + "\r")
        child.expect("approved", timeout=5)
        full_turn = _assistant_turn_text(child, timeout=45)
        # The LLM reply arrives AFTER approve. The assistant
        # diamond is stronger than an arbitrary word check, which
        # could pass on error-panel prose instead of a rendered reply.
        _assert_assistant_reply_rendered(full_turn, "OUTPUT approval")
        # Critical: OUTPUT approve must NOT surface a DENY
        # sentinel — regression guard for the helper
        # substituting text on the wrong branch.
        assert "Denied by policy" not in full_turn, (
            f"OUTPUT approve path leaked a DENY sentinel.\nCaptured:\n{full_turn[:1500]}"
        )
    finally:
        try:
            child.send("/quit" + "\r")
            child.expect(pexpect.EOF, timeout=5)
        except Exception:
            pass
        if child.isalive():
            child.terminate(force=True)


def test_repl_output_ask_refuse_replaces_reply_with_sentinel(
    ap_cli: str,
    repl_env: dict[str, str],
) -> None:
    """
    OUTPUT ASK → refuse → assistant message = sentinel.

    The user sees ``[Denied by policy: ...]`` instead of the
    LLM's real reply. The REAL text must never land in
    ``conversation_items`` — pre-persistence ordering
    invariant from POLICIES.md §11.4. A follow-up turn only
    sees the sentinel in history.
    """
    child = pexpect.spawn(
        ap_cli,
        ["run", str(_OUTPUT_GATE_DIR)],
        env=repl_env,
        encoding="utf-8",
        codec_errors="replace",
        dimensions=(40, 120),
        timeout=60,
    )
    try:
        _wait_for_prompt_ready(
            child,
            timeout=60,
            welcome_pattern="e2e.output.gate",
        )
        child.send("say hi" + "\r")
        child.expect("approval required", timeout=45)
        child.send("n" + "\r")
        child.expect("refused", timeout=5)
        full_turn = _deny_turn_text(child, timeout=45)
        assert "Denied by policy" in full_turn, (
            f"OUTPUT refuse did not substitute the DENY sentinel.\nCaptured:\n{full_turn[:1500]}"
        )
    finally:
        try:
            child.send("/quit" + "\r")
            child.expect(pexpect.EOF, timeout=5)
        except Exception:
            pass
        if child.isalive():
            child.terminate(force=True)


# ── TOOL_RESULT-phase approval coverage ───────────────────
#
# Distinct from TOOL_CALL: the policy fires AFTER the tool
# dispatches and returns, BEFORE the result reaches
# function_call_output. Tool output exfiltration is the
# canonical motivating case — "run the tool but I want to
# review what it returned before the LLM sees it".


def test_repl_tool_result_ask_approve_surfaces_tool_output(
    ap_cli: str,
    repl_env: dict[str, str],
) -> None:
    """
    TOOL_RESULT ASK → approve → tool output reaches the LLM.

    Unlike the TOOL_CALL fixture, dispatch happens freely
    here; the ASK fires on the RESULT. On approve the
    original tool output (``echo: <input>``) flows back to
    the LLM which includes it in the final reply.
    """
    child = pexpect.spawn(
        ap_cli,
        ["run", str(_TOOL_RESULT_GATE_DIR)],
        env=repl_env,
        encoding="utf-8",
        codec_errors="replace",
        dimensions=(40, 120),
        timeout=60,
    )
    try:
        _wait_for_prompt_ready(
            child,
            timeout=60,
            welcome_pattern="e2e.tool.result.gate",
        )
        child.send("pineapple" + "\r")
        child.expect("approval required", timeout=45)
        banner_tail = _read_pending(child, seconds=1.0)
        # Must be TOOL_RESULT (not TOOL_CALL, not INPUT).
        assert "tool_result" in banner_tail, (
            "Banner phase was not tool_result — either the ASK fired at "
            "the wrong phase or the banner format regressed.\n"
            f"Banner:\n{banner_tail[:800]}"
        )
        # Preview should contain the echo tool's output
        # (``echo: pineapple``) — the TOOL_RESULT evaluator
        # passes the result dict as ctx.content.
        assert "echo" in banner_tail or "pineapple" in banner_tail, (
            f"Preview missing tool output.\nBanner:\n{banner_tail[:800]}"
        )
        child.send("y" + "\r")
        child.expect("approved", timeout=5)
        full_turn = _assistant_turn_text(child, timeout=45)
        # Tool output must flow to the LLM and appear in reply.
        assert "pineapple" in full_turn.lower() or "echo" in full_turn, (
            "Tool output did not reach the LLM's reply after TOOL_RESULT "
            f"approve.\nCaptured:\n{full_turn[:1500]}"
        )
        _assert_assistant_reply_rendered(full_turn, "TOOL_RESULT approval")
    finally:
        try:
            child.send("/quit" + "\r")
            child.expect(pexpect.EOF, timeout=5)
        except Exception:
            pass
        if child.isalive():
            child.terminate(force=True)


def test_repl_tool_result_ask_refuse_replaces_output(
    ap_cli: str,
    repl_env: dict[str, str],
) -> None:
    """
    TOOL_RESULT ASK → refuse → tool output replaced by DENY
    sentinel before reaching function_call_output.

    The tool DID run (TOOL_RESULT fires after dispatch), but
    the LLM must see the sentinel in function_call_output,
    NOT the real output. Regression guard for the pre-
    persistence substitution in ``_execute_tools``.
    """
    child = pexpect.spawn(
        ap_cli,
        ["run", str(_TOOL_RESULT_GATE_DIR)],
        env=repl_env,
        encoding="utf-8",
        codec_errors="replace",
        dimensions=(40, 120),
        timeout=60,
    )
    try:
        _wait_for_prompt_ready(
            child,
            timeout=60,
            welcome_pattern="e2e.tool.result.gate",
        )
        child.send("mangosteen" + "\r")
        child.expect("approval required", timeout=45)
        child.send("n" + "\r")
        child.expect("refused", timeout=5)
        full_turn = _deny_turn_text(child, timeout=60)
        assert "Denied by policy" in full_turn, (
            "TOOL_RESULT refuse did not produce a DENY sentinel on the "
            f"tool output.\nCaptured:\n{full_turn[:1500]}"
        )
    finally:
        try:
            child.send("/quit" + "\r")
            child.expect(pexpect.EOF, timeout=5)
        except Exception:
            pass
        if child.isalive():
            child.terminate(force=True)


# ── Sub-agent TOOL_CALL approval tunneling ────────────────
#
# The sub-agent fires an ASK from the TOOL_CALL phase (not
# INPUT). Still must surface on the ROOT SSE stream — the
# tunneling path is identical for every phase in the
# sub-agent's engine.


def test_repl_subagent_tool_call_ask_tunnels_to_root(
    ap_cli: str,
    repl_env: dict[str, str],
) -> None:
    """
    Sub-agent TOOL_CALL ASK → banner on root REPL → approve
    → sub-agent's tool runs → sub-agent replies → parent
    composes final turn.

    Load-bearing:

    - Banner phase must be ``tool_call`` (not ``input``) —
      proves the sub-agent's tool-phase engine fired.
    - Banner policy must be the sub-agent's
      ``worker_tool_gate`` (not the parent's non-existent
      gate).
    - Root REPL sees the banner through the same SSE stream
      it was already consuming.
    """
    child = pexpect.spawn(
        ap_cli,
        ["run", str(_SUBAGENT_TOOL_GATE_DIR)],
        env=repl_env,
        encoding="utf-8",
        codec_errors="replace",
        dimensions=(40, 120),
        timeout=90,
    )
    try:
        _wait_for_prompt_ready(
            child,
            timeout=90,
            welcome_pattern="e2e.subagent.tool.gate",
        )
        child.send("return the word durian" + "\r")
        child.expect("approval required", timeout=90)
        banner_tail = _read_pending(child, seconds=1.5)
        assert "tool_call" in banner_tail, (
            "Sub-agent TOOL_CALL ASK did not show phase=tool_call — "
            "routing may have surfaced the wrong phase.\n"
            f"Banner:\n{banner_tail[:800]}"
        )
        assert "worker_tool_gate" in banner_tail, (
            f"Sub-agent's tool-gate policy name missing from banner.\nBanner:\n{banner_tail[:800]}"
        )
        child.send("y" + "\r")
        child.expect("approved", timeout=5)
        full_turn = _assistant_turn_text(child, timeout=120)
        # Parent's final reply should contain something from
        # the sub-agent's reply, which used the tool output.
        _assert_assistant_reply_rendered(full_turn, "sub-agent TOOL_CALL approval")
    finally:
        try:
            child.send("/quit" + "\r")
            child.expect(pexpect.EOF, timeout=5)
        except Exception:
            pass
        if child.isalive():
            child.terminate(force=True)
