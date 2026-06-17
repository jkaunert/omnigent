"""Behavioral I/O tests for :class:`TerminalRegistry` against a real tmux.

These complement :mod:`tests.terminals.test_registry` (registry
lifecycle, no keystrokes) and :mod:`tests.tools.builtins.test_sys_terminal`
(the same behaviors through the ``sys_terminal_*`` tool envelopes) by
driving ``TerminalRegistry.launch`` → ``TerminalInstance.send`` / ``.read``
directly: interactive state that survives across calls, cwd anchoring of
the live shell, control-key delivery, and per-session isolation.

The equivalent end-to-end coverage in ``tests/e2e/test_sys_terminal_e2e.py``
is suppressed in ``tests/known_failures.yaml`` because it needs a live
runner and a real LLM. These reach the same tmux behaviors with neither,
so the capability keeps coverage in the ``tests/terminals`` CI shard
(which installs tmux).

Skipped when tmux is absent. ``send`` is asynchronous from the shell's
view, so reads poll on a bounded budget rather than asserting a single
capture.
"""

from __future__ import annotations

import asyncio
import shutil
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from omnigent.inner.datamodel import OSEnvSandboxSpec, OSEnvSpec, TerminalEnvSpec
from omnigent.inner.terminal import TerminalInstance
from omnigent.terminals import TerminalRegistry

pytestmark = pytest.mark.skipif(
    shutil.which("tmux") is None,
    reason="tmux not installed; registry I/O tests need a real tmux on PATH",
)

_MARKER_BUDGET_S = 5.0
_POLL_INTERVAL_S = 0.1


def _dewrap(screen: str) -> str:
    """Join the pane's ``-x 80`` soft-wrapped rows so a needle straddling the wrap matches."""
    return screen.replace("\n", "")


def _bash_spec(cwd: Path, *, allow_cwd_override: bool = False) -> TerminalEnvSpec:
    return TerminalEnvSpec(
        command="bash",
        allow_cwd_override=allow_cwd_override,
        os_env=OSEnvSpec(
            type="caller_process",
            cwd=str(cwd),
            sandbox=OSEnvSandboxSpec(type="none"),
        ),
    )


async def _read_until(
    instance: TerminalInstance,
    needle: str,
    *,
    budget_s: float = _MARKER_BUDGET_S,
) -> str:
    """Poll ``instance.read`` until *needle* appears or the budget elapses.

    Returns the last pane text seen — containing *needle* on success, or
    the final capture (for a useful failure message) on timeout.
    """
    waited = 0.0
    screen = ""
    while waited < budget_s:
        screen = _dewrap((await instance.read()).get("screen", ""))
        if needle in screen:
            return screen
        await asyncio.sleep(_POLL_INTERVAL_S)
        waited += _POLL_INTERVAL_S
    return screen


def _path_tail(*parts: str) -> str:
    """Join path segments into a tmux-pwd needle.

    Matching a two-segment tail (parent/leaf) rather than a bare leaf
    keeps the assertion off a basename-only shell prompt and off the
    macOS ``/var`` → ``/private/var`` symlink rewrite, both of which
    would otherwise let a test pass without the real pwd in the pane.
    """
    return str(Path(*parts))


@pytest.fixture
def reg() -> TerminalRegistry:
    return TerminalRegistry()


@pytest.fixture
async def shutdown_terminals(reg: TerminalRegistry) -> AsyncIterator[None]:
    """Close every terminal at test exit, even when an assertion fails."""
    yield
    await reg.shutdown()


async def test_shell_state_persists_across_separate_sends(
    reg: TerminalRegistry, shutdown_terminals: None, tmp_path: Path
) -> None:
    """A variable set in one ``send`` is still set in a later ``send``.

    The capability ``sys_terminal_*`` adds over a one-shot ``sys_os_shell``:
    one long-lived shell across calls. A "fresh shell per send" regression
    passes every lifecycle test yet fails here.
    """
    instance = await reg.launch("conv_a", "bash", "s1", _bash_spec(tmp_path))

    await instance.send(text="MARKER_VAR=persisted_value", keys="Enter")
    await instance.send(text="echo VAR_IS_$MARKER_VAR", keys="Enter")

    screen = await _read_until(instance, "VAR_IS_persisted_value")
    assert "VAR_IS_persisted_value" in screen, (
        "variable from the first send was not visible in the second — each "
        f"send is spawning a fresh shell. Last pane:\n{screen!r}"
    )


async def test_working_directory_change_persists_across_sends(
    reg: TerminalRegistry, shutdown_terminals: None, tmp_path: Path
) -> None:
    """A ``cd`` in one send is reflected by ``pwd`` in a later send."""
    subdir = tmp_path / "nested_dir"
    subdir.mkdir()
    instance = await reg.launch("conv_a", "bash", "s1", _bash_spec(tmp_path))

    await instance.send(text="cd nested_dir", keys="Enter")
    await instance.send(text="pwd", keys="Enter")

    needle = _path_tail(tmp_path.name, "nested_dir")
    screen = await _read_until(instance, needle)
    assert needle in screen, (
        f"cd from the first send did not persist into the second send's pwd. "
        f"Last pane:\n{screen!r}"
    )


async def test_launched_shell_starts_in_spec_cwd(
    reg: TerminalRegistry, shutdown_terminals: None, tmp_path: Path
) -> None:
    """``pwd`` in a freshly launched shell reports the spec's cwd.

    The behavioral half of ``_resolve_cwd``'s precedence logic, which is
    unit-tested in isolation but never proven against a live shell.
    """
    instance = await reg.launch("conv_a", "bash", "s1", _bash_spec(tmp_path))

    await instance.send(text="pwd", keys="Enter")

    needle = _path_tail(tmp_path.parent.name, tmp_path.name)
    screen = await _read_until(instance, needle)
    assert needle in screen, (
        f"launched shell's pwd did not report the spec cwd {tmp_path}. Last pane:\n{screen!r}"
    )


async def test_cwd_override_anchors_live_shell_in_subdirectory(
    reg: TerminalRegistry, shutdown_terminals: None, tmp_path: Path
) -> None:
    """A per-launch ``cwd_override`` starts the live shell in that subdir."""
    override_dir = tmp_path / "workdir"
    override_dir.mkdir()

    instance = await reg.launch(
        "conv_a",
        "bash",
        "s1",
        _bash_spec(tmp_path, allow_cwd_override=True),
        cwd_override=str(override_dir),
    )

    assert instance.launch_cwd is not None
    assert Path(instance.launch_cwd).name == "workdir", (
        f"launch_cwd did not reflect the cwd_override; got {instance.launch_cwd!r}"
    )

    await instance.send(text="pwd", keys="Enter")
    needle = _path_tail(tmp_path.name, "workdir")
    screen = await _read_until(instance, needle)
    assert needle in screen, f"cwd_override did not anchor the live shell. Last pane:\n{screen!r}"


async def test_ctrl_c_interrupts_running_command(
    reg: TerminalRegistry, shutdown_terminals: None, tmp_path: Path
) -> None:
    """``keys="C-c"`` interrupts a running foreground command."""
    instance = await reg.launch("conv_a", "bash", "s1", _bash_spec(tmp_path))

    await instance.send(text="sleep 120", keys="Enter")
    # Let bash fork `sleep` before interrupting; a C-c that lands first
    # only edits the command line. Roomy for loaded CI.
    await asyncio.sleep(1.0)

    interrupt = await instance.send(text=None, keys="C-c")
    assert interrupt.get("status") == "sent", f"C-c send failed: {interrupt!r}"

    await instance.send(text="echo INTERRUPT_RECOVERED_OK", keys="Enter")
    screen = await _read_until(instance, "INTERRUPT_RECOVERED_OK")
    assert "INTERRUPT_RECOVERED_OK" in screen, (
        "marker echo did not appear after C-c, so the foreground `sleep` was "
        f"never interrupted. Last pane:\n{screen!r}"
    )


async def test_parallel_sessions_have_isolated_shell_state(
    reg: TerminalRegistry, shutdown_terminals: None, tmp_path: Path
) -> None:
    """Two sessions of the same terminal don't share shell state.

    Stronger than the socket-identity checks in ``test_registry.py``: a
    regression collapsing ``(name, key)`` to ``name`` surfaces here as
    cross-talk between the two panes.
    """
    spec = _bash_spec(tmp_path)
    s1 = await reg.launch("conv_a", "bash", "s1", spec)
    s2 = await reg.launch("conv_a", "bash", "s2", spec)

    assert s1 is not s2
    assert s1.socket_path != s2.socket_path

    await s1.send(text="SESSION_TAG=alpha_one", keys="Enter")
    await s2.send(text="SESSION_TAG=beta_two", keys="Enter")
    await s1.send(text="echo TAG=$SESSION_TAG", keys="Enter")
    await s2.send(text="echo TAG=$SESSION_TAG", keys="Enter")

    s1_screen = await _read_until(s1, "TAG=alpha_one")
    s2_screen = await _read_until(s2, "TAG=beta_two")

    assert "TAG=alpha_one" in s1_screen, f"s1 lost its own value. Pane:\n{s1_screen!r}"
    assert "TAG=beta_two" in s2_screen, f"s2 lost its own value. Pane:\n{s2_screen!r}"
    assert "beta_two" not in s1_screen, f"s1 sees s2's value. Pane:\n{s1_screen!r}"
    assert "alpha_one" not in s2_screen, f"s2 sees s1's value. Pane:\n{s2_screen!r}"


async def test_send_and_read_after_close_report_not_running(
    reg: TerminalRegistry, shutdown_terminals: None, tmp_path: Path
) -> None:
    """Once closed, the instance's ``send`` / ``read`` error cleanly.

    ``test_registry.py`` proves ``close`` removes the registry entry; this
    proves the instance refuses I/O afterward instead of talking to a dead
    socket.
    """
    instance = await reg.launch("conv_a", "bash", "s1", _bash_spec(tmp_path))
    assert await instance.is_alive()

    assert await reg.close("conv_a", "bash", "s1") is True
    assert instance.running is False
    assert await instance.is_alive() is False

    assert "error" in await instance.send(text="echo too_late", keys="Enter")
    assert "error" in await instance.read()
