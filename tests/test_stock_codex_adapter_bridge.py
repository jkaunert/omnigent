"""Tests for the stock Codex adapter file bridge worker."""

from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Mapping
from pathlib import Path

from omnigent.stock_codex_adapter_bridge import (
    AdapterBridgeResponse,
    FileBridgeAdapterService,
    FileBridgeAdapterWorker,
)


def _write_request(requests_dir: Path, request_id: str, payload: dict[str, object]) -> None:
    request_path = requests_dir / f"{request_id}.json"
    request_tmp_path = requests_dir / f"{request_id}.tmp"
    request_tmp_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    os.replace(request_tmp_path, request_path)


def _read_response(responses_dir: Path, request_id: str) -> dict[str, object]:
    deadline = time.monotonic() + 5
    response_path = responses_dir / f"{request_id}.json"
    while time.monotonic() < deadline:
        if response_path.exists():
            return json.loads(response_path.read_text(encoding="utf-8"))
        time.sleep(0.05)
    raise AssertionError(f"bridge response was not written: {response_path}")


def test_file_bridge_worker_dispatches_request_to_handler(tmp_path: Path) -> None:
    bridge_dir = tmp_path / "bridge"
    requests_dir = bridge_dir / "requests"
    responses_dir = bridge_dir / "responses"
    seen_arguments: list[dict[str, object]] = []

    def handler(arguments: dict[str, object]) -> AdapterBridgeResponse:
        seen_arguments.append(dict(arguments))
        return AdapterBridgeResponse.ok("handled\n")

    stop_event = threading.Event()
    thread = FileBridgeAdapterWorker(
        bridge_dir,
        {"fetch_apple_docs": handler},
    ).start(stop_event=stop_event)
    try:
        _write_request(
            requests_dir,
            "request-1",
            {
                "id": "request-1",
                "tool": "fetch_apple_docs",
                "arguments": {"url": "https://developer.apple.com/documentation/swift/string"},
            },
        )

        response = _read_response(responses_dir, "request-1")
    finally:
        stop_event.set()
        thread.join(timeout=5)

    assert seen_arguments == [
        {"url": "https://developer.apple.com/documentation/swift/string"}
    ]
    assert response == {
        "status": "ok",
        "stdout": "handled\n",
        "stderr": "",
        "exitCode": 0,
    }


def test_file_bridge_service_context_manages_worker_lifecycle(tmp_path: Path) -> None:
    bridge_dir = tmp_path / "bridge"
    requests_dir = bridge_dir / "requests"
    responses_dir = bridge_dir / "responses"

    def handler(arguments: Mapping[str, object]) -> AdapterBridgeResponse:
        return AdapterBridgeResponse.ok(f"service handled {arguments['url']}\n")

    with FileBridgeAdapterService(
        bridge_dir,
        {"fetch_apple_docs": handler},
        thread_name="test-stock-codex-file-bridge-service",
    ) as service:
        assert service.thread is not None
        assert service.thread.is_alive()
        _write_request(
            requests_dir,
            "request-service",
            {
                "id": "request-service",
                "tool": "fetch_apple_docs",
                "arguments": {"url": "https://developer.apple.com/documentation/swift/string"},
            },
        )

        response = _read_response(responses_dir, "request-service")

    assert service.thread is None
    assert response == {
        "status": "ok",
        "stdout": "service handled https://developer.apple.com/documentation/swift/string\n",
        "stderr": "",
        "exitCode": 0,
    }


def test_file_bridge_worker_rejects_unexpected_tool(tmp_path: Path) -> None:
    bridge_dir = tmp_path / "bridge"
    requests_dir = bridge_dir / "requests"
    responses_dir = bridge_dir / "responses"
    stop_event = threading.Event()
    thread = FileBridgeAdapterWorker(
        bridge_dir,
        {"fetch_apple_docs": lambda _arguments: AdapterBridgeResponse.ok("handled\n")},
    ).start(stop_event=stop_event)
    try:
        _write_request(
            requests_dir,
            "request-2",
            {
                "id": "request-2",
                "tool": "other_tool",
                "arguments": {},
            },
        )

        response = _read_response(responses_dir, "request-2")
    finally:
        stop_event.set()
        thread.join(timeout=5)

    assert response["status"] == "error"
    assert response["exitCode"] == 64
    assert "unexpected tool" in str(response["stderr"])
