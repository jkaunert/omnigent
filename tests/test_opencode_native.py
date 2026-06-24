"""Unit tests for the ``omni opencode`` launcher helpers (``opencode_native.py``).

Covers the pure spec/payload/tmux helpers plus the httpx-backed session and
terminal helpers over a fake ``AsyncClient`` — the daemon/tmux attach plumbing
itself stays for the live host e2e.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import click
import httpx
import pytest
import yaml

from omnigent.opencode_native import (
    LaunchedOpenCodeTerminal,
    PreparedOpenCodeTerminal,
    _create_opencode_session,
    _direct_tmux_unavailable_reason,
    _ensure_opencode_terminal_on_runner,
    _fetch_opencode_session,
    _find_running_opencode_terminal,
    _launched_opencode_terminal_from_payload,
    _materialize_opencode_agent_spec,
    _resolve_session_id_for_resume,
    opencode_terminal_resource_id,
)


class _FakeClient:
    """Async httpx stand-in returning one preset response per call."""

    def __init__(self, response: httpx.Response) -> None:
        self._response = response
        self.requests: list[tuple[str, str, dict[str, Any]]] = []

    async def post(self, url: str, **kwargs: Any) -> httpx.Response:
        self.requests.append(("POST", url, kwargs))
        return self._response

    async def get(self, url: str, **kwargs: Any) -> httpx.Response:
        self.requests.append(("GET", url, kwargs))
        return self._response


# ── _materialize_opencode_agent_spec ────────────────────────────────────────


def test_materialize_spec_defaults_no_model(tmp_path: Path) -> None:
    spec = yaml.safe_load(_materialize_opencode_agent_spec(tmp_path).read_text())
    assert spec["executor"] == {"harness": "opencode-native"}
    assert spec["spawn"] is True
    assert "shell" in spec["terminals"]


def test_materialize_spec_pins_model(tmp_path: Path) -> None:
    spec = yaml.safe_load(
        _materialize_opencode_agent_spec(tmp_path, model="anthropic/claude-opus-4").read_text()
    )
    assert spec["executor"] == {"harness": "opencode-native", "model": "anthropic/claude-opus-4"}


def test_terminal_resource_id_is_deterministic() -> None:
    assert opencode_terminal_resource_id() == opencode_terminal_resource_id()


# ── _launched_opencode_terminal_from_payload ────────────────────────────────


def test_launched_terminal_parses_tmux_metadata() -> None:
    launched = _launched_opencode_terminal_from_payload(
        {"id": "term_1", "metadata": {"tmux_socket": "/tmp/s.sock", "tmux_target": "sess:0.0"}}
    )
    assert launched.terminal_id == "term_1"
    assert launched.tmux_socket == Path("/tmp/s.sock")
    assert launched.tmux_target == "sess:0.0"


def test_launched_terminal_without_metadata_has_no_tmux() -> None:
    launched = _launched_opencode_terminal_from_payload({"id": "term_1"})
    assert launched.tmux_socket is None and launched.tmux_target is None


def test_launched_terminal_missing_id_raises() -> None:
    with pytest.raises(click.ClickException):
        _launched_opencode_terminal_from_payload({"metadata": {}})
    with pytest.raises(click.ClickException):
        _launched_opencode_terminal_from_payload("not-a-dict")


# ── _direct_tmux_unavailable_reason ─────────────────────────────────────────


def _prepared(socket: Path | None, target: str | None) -> PreparedOpenCodeTerminal:
    return PreparedOpenCodeTerminal(
        session_id="conv_1",
        terminal_id="term_1",
        tmux_socket=socket,
        tmux_target=target,
        reattached=False,
    )


def test_tmux_reason_missing_socket() -> None:
    assert "tmux socket" in (_direct_tmux_unavailable_reason(_prepared(None, "t")) or "")


def test_tmux_reason_missing_target() -> None:
    assert "tmux target" in (_direct_tmux_unavailable_reason(_prepared(Path("/x"), None)) or "")


def test_tmux_reason_socket_not_reachable(tmp_path: Path) -> None:
    reason = _direct_tmux_unavailable_reason(_prepared(tmp_path / "missing.sock", "t"))
    assert reason is not None and "not reachable" in reason


# ── _resolve_session_id_for_resume ──────────────────────────────────────────


def test_resolve_session_id_passthrough() -> None:
    assert (
        _resolve_session_id_for_resume(
            base_url="http://x", headers={}, session_id="conv_9", resume_picker=False
        )
        == "conv_9"
    )


def test_resolve_session_id_none_without_picker() -> None:
    assert (
        _resolve_session_id_for_resume(
            base_url="http://x", headers={}, session_id=None, resume_picker=False
        )
        is None
    )


# ── httpx-backed session/terminal helpers ───────────────────────────────────


async def test_create_session_returns_id() -> None:
    client = _FakeClient(httpx.Response(200, json={"session_id": "conv_new"}))
    sid = await _create_opencode_session(client, b"bundle", terminal_launch_args=["--foo"])  # type: ignore[arg-type]
    assert sid == "conv_new"
    assert client.requests[0][1] == "/v1/sessions"


async def test_create_session_errors_on_http_failure() -> None:
    client = _FakeClient(httpx.Response(500, json={"error": "boom"}))
    with pytest.raises(click.ClickException):
        await _create_opencode_session(client, b"bundle")  # type: ignore[arg-type]


async def test_create_session_errors_without_session_id() -> None:
    client = _FakeClient(httpx.Response(200, json={}))
    with pytest.raises(click.ClickException):
        await _create_opencode_session(client, b"bundle")  # type: ignore[arg-type]


async def test_fetch_session_returns_payload() -> None:
    client = _FakeClient(httpx.Response(200, json={"id": "conv_1", "title": "t"}))
    assert (await _fetch_opencode_session(client, "conv_1"))["id"] == "conv_1"  # type: ignore[arg-type]


async def test_fetch_session_404_raises() -> None:
    client = _FakeClient(httpx.Response(404, json={"error": "nope"}))
    with pytest.raises(click.ClickException):
        await _fetch_opencode_session(client, "conv_1")  # type: ignore[arg-type]


async def test_ensure_terminal_ok_then_error() -> None:
    ok = _FakeClient(httpx.Response(200, json={}))
    await _ensure_opencode_terminal_on_runner(ok, "conv_1")  # type: ignore[arg-type]
    assert ok.requests[0][0] == "POST"
    bad = _FakeClient(httpx.Response(503, json={"error": "x"}))
    with pytest.raises(click.ClickException):
        await _ensure_opencode_terminal_on_runner(bad, "conv_1")  # type: ignore[arg-type]


async def test_find_terminal_404_returns_none() -> None:
    client = _FakeClient(httpx.Response(404, json={}))
    assert await _find_running_opencode_terminal(client, "conv_1") is None  # type: ignore[arg-type]


async def test_find_terminal_not_running_returns_none() -> None:
    client = _FakeClient(
        httpx.Response(200, json={"id": "term_1", "metadata": {"running": False}})
    )
    assert await _find_running_opencode_terminal(client, "conv_1") is None  # type: ignore[arg-type]


async def test_find_terminal_returns_launched() -> None:
    client = _FakeClient(
        httpx.Response(200, json={"id": "term_1", "metadata": {"tmux_target": "s:0.0"}})
    )
    launched = await _find_running_opencode_terminal(client, "conv_1")  # type: ignore[arg-type]
    assert isinstance(launched, LaunchedOpenCodeTerminal)
    assert launched.tmux_target == "s:0.0"


async def test_find_terminal_offline_runner_returns_none() -> None:
    client = _FakeClient(httpx.Response(409, text="session not bound to a runner"))
    assert await _find_running_opencode_terminal(client, "conv_1") is None  # type: ignore[arg-type]
