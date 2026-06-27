from __future__ import annotations

import json
import logging
from types import SimpleNamespace
from typing import Any

import pytest

from omnigent.runner.codex.goal import CodexGoalRunner


class _DisabledGoalsAppServerClient:
    def __init__(self) -> None:
        self.requests: list[tuple[str, dict[str, Any]]] = []
        self.connected = False
        self.closed = False

    async def connect(self) -> None:
        self.connected = True

    async def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self.requests.append((method, params))
        raise RuntimeError("{'code': -32600, 'message': 'goals feature is disabled'}")

    async def close(self) -> None:
        self.closed = True


def _disabled_goals_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[CodexGoalRunner, _DisabledGoalsAppServerClient]:
    import omnigent.codex_native_app_server as app_server

    client = _DisabledGoalsAppServerClient()
    monkeypatch.setattr(
        app_server,
        "client_for_transport",
        lambda transport, *, client_name="omnigent": client,
    )

    async def bridge_state_for_session(
        conv_id: str,
        *,
        action: str,
        missing_state_log_level: int = logging.WARNING,
    ) -> SimpleNamespace:
        del conv_id, action, missing_state_log_level
        return SimpleNamespace(
            socket_path="ws://127.0.0.1:1",
            thread_id="thread_disabled_goals",
        )

    return (
        CodexGoalRunner(
            bridge_state_for_session=bridge_state_for_session,
            client_safe_error_detail=lambda exc, *, context: "safe runner error",
            logger=logging.getLogger("tests.runner.test_codex_goal_runner"),
        ),
        client,
    )


@pytest.mark.asyncio
async def test_codex_goal_runner_get_returns_none_when_stock_codex_goals_are_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner, client = _disabled_goals_runner(monkeypatch)

    response = await runner.get("conv_codex")

    assert response.status_code == 200
    assert json.loads(response.body) == {"goal": None}
    assert client.connected is True
    assert client.closed is True
    assert client.requests == [("thread/goal/get", {"threadId": "thread_disabled_goals"})]


@pytest.mark.asyncio
async def test_codex_goal_runner_set_keeps_disabled_goals_as_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner, client = _disabled_goals_runner(monkeypatch)

    response = await runner.set(
        "conv_codex",
        objective="Finish parity",
        token_budget=None,
        token_budget_provided=False,
        status=None,
    )

    assert response.status_code == 503
    assert json.loads(response.body)["error"] == "codex_native_goal_failed"
    assert client.connected is True
    assert client.closed is True
    assert client.requests == [
        (
            "thread/goal/set",
            {
                "threadId": "thread_disabled_goals",
                "objective": "Finish parity",
            },
        )
    ]
