"""Wrapper-owned file bridge worker for stock Codex adapter commands."""

from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AdapterBridgeResponse:
    """Structured response consumed by generated stock-Codex bridge commands."""

    status: str
    stdout: str
    stderr: str
    exitCode: int

    def as_payload(self) -> dict[str, object]:
        """Return the JSON-serializable response payload."""
        return {
            "status": self.status,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "exitCode": self.exitCode,
        }

    @classmethod
    def ok(cls, stdout: str, *, stderr: str = "", exit_code: int = 0) -> AdapterBridgeResponse:
        return cls(status="ok", stdout=stdout, stderr=stderr, exitCode=exit_code)

    @classmethod
    def error(cls, message: str, *, exit_code: int = 70) -> AdapterBridgeResponse:
        stderr = message if message.endswith("\n") else f"{message}\n"
        return cls(status="error", stdout="", stderr=stderr, exitCode=exit_code)

    @classmethod
    def from_completed_process(
        cls,
        *,
        stdout: str,
        stderr: str,
        returncode: int,
    ) -> AdapterBridgeResponse:
        return cls(
            status="ok" if returncode == 0 else "error",
            stdout=stdout,
            stderr=stderr,
            exitCode=returncode,
        )


AdapterBridgeHandler = Callable[[Mapping[str, object]], AdapterBridgeResponse]


@dataclass(frozen=True)
class FileBridgeAdapterWorker:
    """Poll a stock-Codex adapter bridge directory and dispatch requests."""

    bridge_dir: Path
    handlers: Mapping[str, AdapterBridgeHandler]
    poll_interval_seconds: float = 0.05
    thread_name: str = "omnigent-stock-codex-file-bridge-worker"

    def ensure_directories(self) -> tuple[Path, Path]:
        """Create and return request/response directories."""
        requests_dir = self.bridge_dir / "requests"
        responses_dir = self.bridge_dir / "responses"
        requests_dir.mkdir(parents=True, exist_ok=True)
        responses_dir.mkdir(parents=True, exist_ok=True)
        return requests_dir, responses_dir

    def start(self, *, stop_event: threading.Event) -> threading.Thread:
        """Start the bridge worker thread."""
        requests_dir, responses_dir = self.ensure_directories()

        def worker() -> None:
            self._run(requests_dir, responses_dir, stop_event=stop_event)

        thread = threading.Thread(target=worker, name=self.thread_name, daemon=True)
        thread.start()
        return thread

    def _run(
        self,
        requests_dir: Path,
        responses_dir: Path,
        *,
        stop_event: threading.Event,
    ) -> None:
        while not stop_event.is_set():
            for request_path in sorted(requests_dir.glob("*.json")):
                self._handle_request_path(request_path, responses_dir)
            time.sleep(self.poll_interval_seconds)

    def _handle_request_path(self, request_path: Path, responses_dir: Path) -> None:
        request_id = request_path.stem
        response_path = responses_dir / f"{request_id}.json"
        if response_path.exists():
            request_path.unlink(missing_ok=True)
            return
        try:
            request = json.loads(request_path.read_text(encoding="utf-8"))
            response = self._dispatch_request(request_id, request)
        except json.JSONDecodeError as exc:
            response = AdapterBridgeResponse.error(
                f"Error: invalid adapter bridge request: {exc}",
                exit_code=70,
            )
        except Exception as exc:  # noqa: BLE001 - the bridge must fail closed per request.
            response = AdapterBridgeResponse.error(f"Error: {exc}", exit_code=70)
        write_adapter_bridge_response(responses_dir, request_id, response)
        request_path.unlink(missing_ok=True)

    def _dispatch_request(
        self,
        request_id: str,
        request: object,
    ) -> AdapterBridgeResponse:
        if not isinstance(request, dict):
            return AdapterBridgeResponse.error(
                "Error: adapter bridge request must be an object",
                exit_code=70,
            )
        if request.get("id") != request_id:
            return AdapterBridgeResponse.error(
                "Error: adapter bridge request id did not match its file name",
                exit_code=70,
            )
        tool_name = request.get("tool")
        if not isinstance(tool_name, str) or not tool_name:
            return AdapterBridgeResponse.error(
                "Error: adapter bridge request omitted tool",
                exit_code=70,
            )
        arguments = request.get("arguments")
        if not isinstance(arguments, dict):
            return AdapterBridgeResponse.error(
                "Error: adapter bridge request omitted arguments",
                exit_code=70,
            )
        handler = self.handlers.get(tool_name)
        if handler is None:
            return AdapterBridgeResponse.error(
                f"Error: adapter bridge request used unexpected tool {tool_name!r}",
                exit_code=64,
            )
        try:
            return handler(arguments)
        except ValueError as exc:
            return AdapterBridgeResponse.error(f"Error: {exc}", exit_code=64)


class FileBridgeAdapterService:
    """Context-managed runtime service for a stock-Codex file bridge."""

    def __init__(
        self,
        bridge_dir: Path,
        handlers: Mapping[str, AdapterBridgeHandler],
        *,
        poll_interval_seconds: float = 0.05,
        thread_name: str = "omnigent-stock-codex-file-bridge-worker",
    ) -> None:
        self.bridge_dir = bridge_dir
        self.handlers = handlers
        self.poll_interval_seconds = poll_interval_seconds
        self.thread_name = thread_name
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None

    def start(self) -> FileBridgeAdapterService:
        """Start the bridge service if it is not already running."""
        if self.thread is not None and self.thread.is_alive():
            return self
        self.stop_event.clear()
        self.thread = FileBridgeAdapterWorker(
            self.bridge_dir,
            self.handlers,
            poll_interval_seconds=self.poll_interval_seconds,
            thread_name=self.thread_name,
        ).start(stop_event=self.stop_event)
        return self

    def stop(self, *, timeout_seconds: float = 5) -> None:
        """Stop the bridge service and wait briefly for the worker thread."""
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout=timeout_seconds)
            self.thread = None

    def __enter__(self) -> FileBridgeAdapterService:
        return self.start()

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.stop()


def write_adapter_bridge_response(
    responses_dir: Path,
    request_id: str,
    response: AdapterBridgeResponse,
) -> None:
    """Atomically write one bridge response."""
    response_path = responses_dir / f"{request_id}.json"
    response_tmp_path = responses_dir / f"{request_id}.tmp"
    response_tmp_path.write_text(
        json.dumps(response.as_payload(), sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(response_tmp_path, response_path)


def require_string_argument(arguments: Mapping[str, object], name: str) -> str:
    """Return a required string bridge argument or raise ``ValueError``."""
    value = arguments.get(name)
    if not isinstance(value, str) or not value:
        raise ValueError(f"adapter bridge request omitted {name}")
    return value
