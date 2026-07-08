#!/usr/bin/env python3
"""Update the per-user stock-Codex compatibility launcher.

The script is intended to run from the installed/staged Omnigent compatibility
runtime through ``uvx --from <runtime>``. It owns the operator-friendly update
entrypoint around ``provision_stock_codex.py`` and can also write the user-level
LaunchAgent plist used to schedule future checks.
"""

from __future__ import annotations

import argparse
import json
import os
import plistlib
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

UPDATE_KIND = "omnigent-stock-codex-compat-update"
LAUNCH_AGENT_KIND = "omnigent-stock-codex-compat-update-launch-agent"
DEFAULT_CHANNEL_POLICY = "official-openai-github-release"
DEFAULT_CACHE_ROOT = Path.home() / ".local" / "omnigent" / "codex-stock"
DEFAULT_LAUNCHER_MANIFEST = (
    Path.home() / ".local" / "omnigent" / "launchers" / "stock-codex-compat.json"
)
DEFAULT_LAUNCH_AGENT_LABEL = "ai.omnigent.stock-codex-compat.update"
DEFAULT_LAUNCH_AGENT_PATH = (
    Path.home() / "Library" / "LaunchAgents" / f"{DEFAULT_LAUNCH_AGENT_LABEL}.plist"
)
DEFAULT_LOG_DIR = Path.home() / "Library" / "Logs" / "Omnigent" / "stock-codex-compat"
DEFAULT_START_INTERVAL_SECONDS = 24 * 60 * 60


class UpdateError(RuntimeError):
    """The stock-Codex compatibility updater could not complete."""


def _json_file(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise UpdateError(f"JSON file is missing: {path}") from exc
    except json.JSONDecodeError as exc:
        raise UpdateError(f"JSON file is invalid: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise UpdateError(f"JSON file was not an object: {path}")
    return payload


def _run_json(command: list[str], *, timeout: float) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if completed.returncode != 0:
        raise UpdateError(
            "Command failed.\n"
            f"command={shlex.join(command)}\n"
            f"exit={completed.returncode}\n"
            f"stdout={completed.stdout}\n"
            f"stderr={completed.stderr}"
        )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise UpdateError(
            "Command did not emit JSON.\n"
            f"command={shlex.join(command)}\n"
            f"stdout={completed.stdout}\n"
            f"stderr={completed.stderr}"
        ) from exc
    if not isinstance(payload, dict):
        raise UpdateError(f"Command JSON was not an object: {payload!r}")
    return payload


def _runtime_root_from_script() -> Path:
    return Path(__file__).resolve().parents[1]


def _require_file(path: Path, label: str) -> Path:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise UpdateError(f"{label} missing: {resolved}")
    return resolved


def _require_runtime(runtime_root: Path) -> Path:
    runtime_root = runtime_root.expanduser().resolve()
    required = (
        (runtime_root / "pyproject.toml", "runtime pyproject"),
        (runtime_root / "scripts" / "provision_stock_codex.py", "stock Codex provisioner"),
        (runtime_root / "scripts" / "update_stock_codex_compat.py", "stock Codex updater"),
    )
    for path, label in required:
        _require_file(path, label)
    return runtime_root


def _resolve_uvx(path: Path | None) -> Path:
    raw = path or shutil.which("uvx")
    if raw is None:
        raise UpdateError("Could not find uvx on PATH; pass --uvx-path")
    uvx_path = Path(raw).expanduser()
    if not uvx_path.is_file() or not os.access(uvx_path, os.X_OK):
        raise UpdateError(f"uvx is not executable: {uvx_path}")
    return uvx_path.resolve()


def default_rollback_metadata_path(launcher_manifest: Path) -> Path:
    launcher_manifest = launcher_manifest.expanduser()
    return launcher_manifest.with_name(f"{launcher_manifest.name}.rollback.json")


def _base_provisioner_command(
    args: argparse.Namespace,
    *,
    runtime_root: Path,
    launcher_manifest: Path,
    rollback_metadata_path: Path,
    include_remote_download: bool,
    include_current_codex: bool,
    promote_update: bool,
) -> list[str]:
    provisioner = runtime_root / "scripts" / "provision_stock_codex.py"
    command = [
        sys.executable,
        str(provisioner),
        "--plan-update",
        "--channel-manifest",
        str(args.channel_manifest.expanduser().resolve()),
        "--channel-policy",
        args.channel_policy,
        "--launcher-manifest",
        str(launcher_manifest),
        "--stage-update",
        "--json",
        "--cache-root",
        str(args.cache_root.expanduser().resolve()),
    ]
    if args.expected_sha256:
        command.extend(["--expected-sha256", args.expected_sha256])
    if args.channel_version:
        command.extend(["--channel-version", args.channel_version])
    if args.channel_platform:
        command.extend(["--channel-platform", args.channel_platform])
    if include_current_codex and args.current_codex is not None:
        command.extend(["--current-codex", str(args.current_codex.expanduser().resolve())])
    if include_remote_download and args.allow_remote_channel_download:
        command.append("--allow-remote-channel-download")
    if include_remote_download and args.force:
        command.append("--force")
    if promote_update:
        command.extend(["--promote-update", "--rollback-metadata", str(rollback_metadata_path)])
    return command


def _promotion_required(plan: dict[str, Any]) -> bool:
    promotion = plan.get("promotion")
    if not isinstance(promotion, dict):
        return False
    return promotion.get("required") is True and promotion.get("ready") is True


def _write_json_object(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.tmp")
    temp_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp_path.replace(path)


def launch_agent_program_arguments(
    *,
    runtime_root: Path,
    uvx_path: Path,
    cache_root: Path,
    channel_manifest: Path,
    channel_policy: str,
    launcher_manifest: Path,
    rollback_metadata_path: Path,
    expected_sha256: str | None,
    channel_version: str | None,
    channel_platform: str | None,
    allow_remote_channel_download: bool,
) -> list[str]:
    updater = runtime_root / "scripts" / "update_stock_codex_compat.py"
    arguments = [
        str(uvx_path),
        "--from",
        str(runtime_root),
        "python",
        str(updater),
        "--runtime-root",
        str(runtime_root),
        "--cache-root",
        str(cache_root),
        "--channel-manifest",
        str(channel_manifest),
        "--channel-policy",
        channel_policy,
        "--launcher-manifest",
        str(launcher_manifest),
        "--rollback-metadata",
        str(rollback_metadata_path),
        "--json",
    ]
    if expected_sha256:
        arguments.extend(["--expected-sha256", expected_sha256])
    if channel_version:
        arguments.extend(["--channel-version", channel_version])
    if channel_platform:
        arguments.extend(["--channel-platform", channel_platform])
    if allow_remote_channel_download:
        arguments.append("--allow-remote-channel-download")
    return arguments


def build_launch_agent_plist(
    *,
    label: str,
    program_arguments: list[str],
    start_interval: int,
    run_at_load: bool,
    log_dir: Path,
) -> dict[str, Any]:
    log_dir = log_dir.expanduser()
    plist: dict[str, Any] = {
        "Label": label,
        "ProgramArguments": program_arguments,
        "RunAtLoad": run_at_load,
        "StartInterval": start_interval,
        "StandardOutPath": str(log_dir / "update.out.log"),
        "StandardErrorPath": str(log_dir / "update.err.log"),
    }
    return plist


def write_launch_agent(path: Path, plist: dict[str, Any]) -> None:
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    log_dir_raw = plist.get("StandardOutPath")
    if isinstance(log_dir_raw, str):
        Path(log_dir_raw).expanduser().parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.tmp")
    with temp_path.open("wb") as handle:
        plistlib.dump(plist, handle, sort_keys=True)
    temp_path.replace(path)


def update_stock_codex_compat(args: argparse.Namespace) -> dict[str, Any]:
    runtime_root = _require_runtime(args.runtime_root or _runtime_root_from_script())
    launcher_manifest = _require_file(args.launcher_manifest, "launcher manifest")
    channel_manifest = _require_file(args.channel_manifest, "channel manifest")
    _json_file(launcher_manifest)
    _json_file(channel_manifest)

    cache_root = args.cache_root.expanduser().resolve()
    rollback_metadata_path = (
        args.rollback_metadata.expanduser().resolve()
        if args.rollback_metadata is not None
        else default_rollback_metadata_path(launcher_manifest).resolve()
    )
    uvx_path = _resolve_uvx(args.uvx_path)
    launch_agent_path = args.launch_agent_path.expanduser()
    log_dir = args.launch_agent_log_dir.expanduser()
    program_arguments = launch_agent_program_arguments(
        runtime_root=runtime_root,
        uvx_path=uvx_path,
        cache_root=cache_root,
        channel_manifest=channel_manifest,
        channel_policy=args.channel_policy,
        launcher_manifest=launcher_manifest,
        rollback_metadata_path=rollback_metadata_path,
        expected_sha256=args.expected_sha256,
        channel_version=args.channel_version,
        channel_platform=args.channel_platform,
        allow_remote_channel_download=args.allow_remote_channel_download,
    )
    launch_agent_plist = build_launch_agent_plist(
        label=args.launch_agent_label,
        program_arguments=program_arguments,
        start_interval=args.start_interval,
        run_at_load=not args.no_run_at_load,
        log_dir=log_dir,
    )

    launch_agent_written = False
    if args.write_launch_agent:
        write_launch_agent(launch_agent_path, launch_agent_plist)
        launch_agent_written = True

    should_run = args.run_now or not args.write_launch_agent
    plan: dict[str, Any] | None = None
    promotion: dict[str, Any] | None = None
    update_action = "launch-agent-written" if launch_agent_written else "not-run"
    update_mutates = launch_agent_written
    if should_run:
        plan_command = _base_provisioner_command(
            args,
            runtime_root=runtime_root,
            launcher_manifest=launcher_manifest,
            rollback_metadata_path=rollback_metadata_path,
            include_remote_download=True,
            include_current_codex=True,
            promote_update=False,
        )
        plan = _run_json(plan_command, timeout=args.update_timeout)
        update_action = str(plan.get("action") or "planned")
        update_mutates = update_mutates or bool(plan.get("mutatesFilesystem") is True)
        if _promotion_required(plan):
            promotion_command = _base_provisioner_command(
                args,
                runtime_root=runtime_root,
                launcher_manifest=launcher_manifest,
                rollback_metadata_path=rollback_metadata_path,
                include_remote_download=False,
                include_current_codex=False,
                promote_update=True,
            )
            promotion = _run_json(promotion_command, timeout=args.update_timeout)
            update_action = str(promotion.get("action") or "promoted")
            update_mutates = update_mutates or bool(
                promotion.get("mutatesFilesystem") is True
            )

    result = {
        "kind": UPDATE_KIND,
        "schemaVersion": 1,
        "action": update_action,
        "mutatesFilesystem": update_mutates,
        "runtimeRoot": str(runtime_root),
        "provisioner": str(runtime_root / "scripts" / "provision_stock_codex.py"),
        "cacheRoot": str(cache_root),
        "channelManifestPath": str(channel_manifest),
        "channelPolicy": args.channel_policy,
        "launcherManifestPath": str(launcher_manifest),
        "rollbackMetadataPath": str(rollback_metadata_path),
        "launchAgent": {
            "kind": LAUNCH_AGENT_KIND,
            "label": args.launch_agent_label,
            "path": str(launch_agent_path),
            "written": launch_agent_written,
            "mutatesFilesystem": launch_agent_written,
            "runAtLoad": not args.no_run_at_load,
            "startInterval": args.start_interval,
            "programArguments": program_arguments,
            "standardOutPath": launch_agent_plist["StandardOutPath"],
            "standardErrorPath": launch_agent_plist["StandardErrorPath"],
        },
        "plan": plan,
        "promotion": promotion,
    }
    if args.write_result_manifest is not None:
        _write_json_object(args.write_result_manifest.expanduser(), result)
    return result


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run or schedule stock-Codex compatibility updates."
    )
    parser.add_argument("--runtime-root", type=Path, default=None)
    parser.add_argument("--uvx-path", type=Path, default=None)
    parser.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE_ROOT)
    parser.add_argument("--channel-manifest", type=Path, required=True)
    parser.add_argument("--expected-sha256", default=None)
    parser.add_argument("--channel-version", default=None)
    parser.add_argument("--channel-platform", default=None)
    parser.add_argument("--channel-policy", default=DEFAULT_CHANNEL_POLICY)
    parser.add_argument("--allow-remote-channel-download", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--current-codex", type=Path, default=None)
    parser.add_argument("--launcher-manifest", type=Path, default=DEFAULT_LAUNCHER_MANIFEST)
    parser.add_argument("--rollback-metadata", type=Path, default=None)
    parser.add_argument("--write-launch-agent", action="store_true")
    parser.add_argument("--run-now", action="store_true")
    parser.add_argument("--launch-agent-path", type=Path, default=DEFAULT_LAUNCH_AGENT_PATH)
    parser.add_argument("--launch-agent-label", default=DEFAULT_LAUNCH_AGENT_LABEL)
    parser.add_argument("--launch-agent-log-dir", type=Path, default=DEFAULT_LOG_DIR)
    parser.add_argument("--start-interval", type=int, default=DEFAULT_START_INTERVAL_SECONDS)
    parser.add_argument("--no-run-at-load", action="store_true")
    parser.add_argument("--write-result-manifest", type=Path, default=None)
    parser.add_argument("--update-timeout", type=float, default=900.0)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = update_stock_codex_compat(args)
    except UpdateError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"omnigent_stock_codex_compat_update_action={result['action']}")
        print(
            "omnigent_stock_codex_compat_update_mutates_filesystem="
            f"{result['mutatesFilesystem']}"
        )
        print(f"omnigent_stock_codex_compat_update_launch_agent={result['launchAgent']['path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
