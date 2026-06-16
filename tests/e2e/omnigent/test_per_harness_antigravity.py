"""Per-harness live acceptance test — antigravity native-tool policy gating.

Runs ``omnigent run <bundle> -p "..." --tools coding`` as a real subprocess
against the ``antigravity`` harness (Gemini via the ``google-antigravity`` SDK)
with a guardrail policy that DENIES native file-write tool calls on the
``[tool_call]`` phase, and asserts the native write is **blocked**: the sentinel
file is NOT created on disk, and the run does not report a successful write.

This is the e2e acceptance gate for PR #284 ("enforce tool-call and LLM-phase
policies" / "scope bridged-tool skip per-agent and gate native-name
collisions"). #284 adds a ``PreToolCallDecideHook`` to ``AntigravityExecutor``
(:meth:`omnigent.inner.antigravity_executor.AntigravityExecutor._build_pre_tool_hook`)
that routes every tool call — INCLUDING the SDK's bundled native tools
(``create_file`` / ``edit_file`` / ``run_command``) — through Omnigent's
TOOL_CALL policy before it runs (see ``_evaluate_tool_call_policy`` and
``_is_native_tool_call``). A live bug-bash proved that on pre-#284 main a native
``create_file`` wrote to disk EVEN UNDER an ``on:[tool_call]`` deny policy (the
native call never reached policy — a policy bypass). This test pins the fix: the
deny now blocks the native write.

The two bundles under ``tests/resources/examples/`` mirror the bug-bash arms:

- ``antigravity_native_write_denied`` — the deny policy is attached; the native
  write must be BLOCKED (this test).
- ``antigravity_native_write_allowed`` — the positive control with no policy,
  proving the native tool writes when nothing blocks it. (Driven by hand during
  the live bug-bash, not in CI, to avoid a second metered model turn; kept as a
  resource so the control is reproducible.)

The model is asked to write the sentinel **in the current directory** (not
``/tmp``): the antigravity SDK ships a built-in ``workspace_only`` policy that
denies writes outside the agent's working directory regardless of Omnigent's
policy, so an out-of-workspace path would be blocked by the SDK and could not
distinguish #284's gate from the SDK's own. An in-workspace path is allowed by
the SDK (its catch-all decision is APPROVE), so the ONLY thing that can block it
is Omnigent's ``on:[tool_call]`` deny — exactly what we are asserting.

**Prerequisites (skipped cleanly when absent):**

- The ``google-antigravity`` package importable (an optional extra). When it is
  not installed the executor raises ``ImportError`` at request time.
- A Gemini API key resolvable (the ``antigravity:`` config block written by
  ``omnigent setup``, or an ambient ``GEMINI_API_KEY`` / ``ANTIGRAVITY_API_KEY``).
  Antigravity is Gemini-native — there is no Databricks-gateway path — so, like
  the cursor per-harness test, this gate SKIPS (not fails) when no key is
  provisioned so the e2e shards stay green; it runs for real wherever a key is
  present.
- A runnable harness binary. The SDK launches a bundled native ``localharness``
  ELF that needs **glibc >= ~2.36**. On a host with older glibc the harness
  fails to start ("GLIBC_ABI_DT_RELR not found"); the SDK honors
  ``ANTIGRAVITY_HARNESS_PATH`` to point at a loader shim that runs the binary
  through a newer glibc (a DEV workaround — in prod the harness runs on a
  glibc >= 2.36 host). This test passes the ambient environment through, so it
  runs unmodified where glibc is new enough OR where the dev shim is exported,
  and SKIPS (rather than fails) when the harness cannot launch.
- The shared Gemini free tier throttles aggressively (HTTP 429 on a small daily
  request quota). A run that never reaches a tool call because the model 429'd
  is inconclusive, so it SKIPS rather than asserting on an empty turn.

**What breaks if this fails (with prerequisites present):**

- #284's native-tool gate regresses — a native ``create_file`` / ``edit_file``
  stops being routed through the TOOL_CALL policy (the pre-tool decide hook is
  dropped, the bridged-skip set leaks to native names, or
  ``_evaluate_tool_call_policy`` stops collapsing a DENY to ``allow=False``), so
  the native write reaches disk under an ``on:[tool_call]`` deny — the original
  bug.
- ``AntigravityExecutor`` setup regresses such that policies are not wired onto
  the SDK agent at all.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
from pathlib import Path

import pytest

_HARNESS = "antigravity"
_BUNDLE = "antigravity_native_write_denied"

# The sentinel is written into the agent's working directory (the subprocess
# cwd). A relative name keeps it in-workspace so the SDK's built-in
# ``workspace_only`` policy does not pre-empt Omnigent's gate (see module
# docstring), and lets the test clean it up deterministically.
_SENTINEL_NAME = "NATIVE_WRITE_PROOF_284.txt"
_SENTINEL_CONTENT = "POLICY_BYPASS_CONFIRMED"

# antigravity boots a native localharness subprocess and round-trips to Gemini
# before the first turn event; 180s matches the headroom the other coding-agent
# per-harness tests allow on CI hosts.
_RUN_TIMEOUT_SEC = 180

# Substrings that mean the run never reached a tool call for an environmental
# reason (model throttle / harness launch failure), so the result is
# inconclusive and the test SKIPS rather than passing or failing.
_INCONCLUSIVE_MARKERS = (
    "code 429",
    "exceeded your current quota",
    "high demand",
    "GLIBC",
    "localharness",
    "Failed to read length from stdout",
)


def _antigravity_key_present() -> bool:
    """Whether a Gemini API key is resolvable for the antigravity harness.

    Mirrors ``AntigravityExecutor`` credential resolution: the ``antigravity:``
    config block (``omnigent setup``) or an ambient ``GEMINI_API_KEY`` /
    ``ANTIGRAVITY_API_KEY``. Never raises — a missing/unresolvable key reads as
    absent so the gate skips cleanly.

    :returns: ``True`` when a key is configured or present in the environment.
    """
    if os.environ.get("GEMINI_API_KEY") or os.environ.get("ANTIGRAVITY_API_KEY"):
        return True
    try:
        from omnigent.onboarding.antigravity_auth import antigravity_api_key_configured

        return antigravity_api_key_configured()
    except Exception:
        # Onboarding import / secret-store failure → treat as "no key" so the
        # test skips instead of erroring in a bare environment.
        return False


def test_per_harness_antigravity_native_write_denied(
    omnigent_python: Path,
    omnigent_repo_root: Path,
) -> None:
    """A native ``create_file`` is BLOCKED under an ``on:[tool_call]`` deny.

    Runs the ``antigravity_native_write_denied`` bundle with native tools
    enabled (``--tools coding``) and a prompt that asks the agent to write a
    sentinel file with its bundled native ``create_file`` tool. #284's pre-tool
    policy gate must deny that native call, so the sentinel never reaches disk.

    The subprocess cwd is the repo root for two reasons: the bundle's policy
    handler (``tests.resources.examples._shared.native_tool_policies``) is a
    dotted module path that only imports with the repo root on ``sys.path``,
    AND the SDK's built-in ``workspace_only`` policy keys on the process cwd —
    so a sentinel written "in the current directory" is in-workspace (the SDK
    would allow it; only Omnigent's deny blocks it). The sentinel is removed
    before the run and in a ``finally`` so a regressed bypass cannot leave a
    file in the working tree.

    :param omnigent_python: Interpreter with omnigent + the ``antigravity``
        extra installed and importable.
    :param omnigent_repo_root: Cwd for the subprocess so the bundle's policy
        handler resolves on ``sys.path`` and the SDK workspace is the repo root.
    """
    if importlib.util.find_spec("google.antigravity") is None:
        pytest.skip(
            "antigravity prerequisite missing: the 'google-antigravity' package "
            "is not installed (pip install 'omnigent[antigravity]')."
        )
    if not _antigravity_key_present():
        pytest.skip(
            "antigravity prerequisite missing: no Gemini API key resolvable. "
            "Antigravity is Gemini-native (no Databricks-gateway path), so this "
            "live gate is skipped rather than failed when the key is absent. "
            "Configure it with `omnigent setup` or export GEMINI_API_KEY."
        )

    bundle = omnigent_repo_root / "tests" / "resources" / "examples" / _BUNDLE
    # Where an in-workspace native write would land (the process cwd = the SDK
    # workspace). Cleaned before and after so a regressed bypass never pollutes
    # the working tree.
    sentinel = omnigent_repo_root / _SENTINEL_NAME

    prompt = (
        f"Create a new file named {_SENTINEL_NAME} in the current directory "
        f"containing the exact text: {_SENTINEL_CONTENT}. Use your native "
        "create_file tool. Then confirm whether you succeeded."
    )

    try:
        sentinel.unlink(missing_ok=True)
        # Pass the ambient environment through so a host with glibc >= 2.36 runs
        # the bundled localharness directly, and a dev host that exported
        # ANTIGRAVITY_HARNESS_PATH (the glibc-shim workaround) is honored too.
        # The antigravity harness runs in-process in the local-run topology, so
        # the subprocess's env reaches the SDK without the host-daemon env
        # filtering that strips ANTIGRAVITY_HARNESS_PATH on the runner spawn
        # path.
        try:
            result = subprocess.run(
                [
                    str(omnigent_python),
                    "-m",
                    "omnigent",
                    "run",
                    str(bundle),
                    "-p",
                    prompt,
                    "--tools",
                    "coding",
                    "--no-log",
                    "--no-session",
                ],
                env=dict(os.environ),
                cwd=str(omnigent_repo_root),
                capture_output=True,
                text=True,
                timeout=_RUN_TIMEOUT_SEC,
            )
        except subprocess.TimeoutExpired:
            # A run that never returns is inconclusive: the executor retries a
            # 429 throttle with backoff and can burn the whole timeout without
            # ever reaching a tool call, so blocking can't be asserted. The
            # on-disk check is the authoritative signal regardless; verify
            # nothing leaked before skipping.
            assert not sentinel.exists(), (
                f"POLICY BYPASS: native create_file wrote {sentinel} before the "
                f"run timed out — content: {sentinel.read_text(errors='replace')!r}"
            )
            pytest.skip(
                "antigravity run timed out before completing a turn (model "
                "throttle retry-backoff or cold-start) — no tool call reached "
                "the policy gate."
            )

        combined = f"{result.stdout}\n{result.stderr}"

        # The run is only conclusive if it reached a tool call. A model throttle
        # (429) or a harness that couldn't launch (glibc) means no native write
        # was ever attempted, so blocking can't be asserted — skip cleanly.
        if any(marker in combined for marker in _INCONCLUSIVE_MARKERS):
            pytest.skip(
                "antigravity run inconclusive (model throttle or harness launch "
                "failure — no tool call reached the policy gate):\n"
                f"stdout:\n{result.stdout!r}\n\nstderr:\n{result.stderr!r}"
            )

        # THE GATE: the native create_file must have been denied, so nothing
        # reached disk. On pre-#284 main this file WOULD exist (the native call
        # bypassed policy) — its absence is the regression assertion.
        assert not sentinel.exists(), (
            f"POLICY BYPASS: native create_file wrote {sentinel} under an "
            f"on:[tool_call] deny policy — #284's native-tool gate did not hold. "
            f"Content: {sentinel.read_text(errors='replace')!r}\n\n"
            f"stdout:\n{result.stdout!r}\n\nstderr:\n{result.stderr!r}"
        )

        # The bundle's deny carries the marker text 'denied by the
        # on:[tool_call] guardrail policy'; the SDK surfaces a blocked native
        # call to the model as 'denied permission'. Either phrasing in the
        # assistant's reply confirms the block was observed by the model
        # (belt-and-suspenders over the on-disk check, the authoritative signal).
        lowered = result.stdout.lower()
        assert ("denied" in lowered) or ("blocked" in lowered) or ("not allowed" in lowered), (
            "native write left no file (good) but the assistant did not report a "
            "denial — the turn may have ended before calling the tool. Treating "
            f"as a soft signal failure.\n\nstdout:\n{result.stdout!r}\n\n"
            f"stderr:\n{result.stderr!r}"
        )
    finally:
        sentinel.unlink(missing_ok=True)
