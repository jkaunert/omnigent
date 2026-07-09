#!/usr/bin/env python3
"""Run the stock-Codex compatibility package release-candidate gate."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROOF_NAME = "stock-codex-compat-pkg-clean-vm-release"
EVIDENCE_KIND = "omnigent-stock-codex-compat-release-candidate-evidence"
EVIDENCE_SCHEMA_VERSION = 1
PROOF_OUTPUT_PREFIX = "stock_codex_compat_pkg_clean_vm_release_"
ENV_PKG_PATH = "OMNIGENT_STOCK_CODEX_COMPAT_RELEASE_PKG_PATH"
ENV_CODEX_PATH = "OMNIGENT_STOCK_CODEX_COMPAT_RELEASE_CODEX_PATH"
ENV_TART_NAME = "OMNIGENT_STOCK_CODEX_COMPAT_RELEASE_TART_NAME"
ENV_SSH_TARGET = "OMNIGENT_STOCK_CODEX_COMPAT_RELEASE_SSH_TARGET"
ENV_SSH_USER = "OMNIGENT_STOCK_CODEX_COMPAT_RELEASE_SSH_USER"
ENV_SSH_IDENTITY = "OMNIGENT_STOCK_CODEX_COMPAT_RELEASE_SSH_IDENTITY"
ENV_SSH_PORT = "OMNIGENT_STOCK_CODEX_COMPAT_RELEASE_SSH_PORT"
ENV_EVIDENCE_OUTPUT = "OMNIGENT_STOCK_CODEX_COMPAT_RELEASE_EVIDENCE_OUTPUT"

EVIDENCE_FIELD_MAP = {
    "status": "status",
    "missing_prerequisites": "missingPrerequisites",
    "package_path": "packagePath",
    "package_sha256": "packageSha256",
    "stock_codex_path": "stockCodexPath",
    "stock_codex_version": "stockCodexVersion",
    "stock_codex_sha256": "stockCodexSha256",
    "cask_version": "caskVersion",
    "cask_url": "caskUrl",
    "cask_sha256": "caskSha256",
    "channel_policy": "channelPolicy",
    "tart_name": "tartName",
    "ssh_target": "sshTarget",
    "ssh_identity": "sshIdentity",
    "ssh_user": "sshUser",
    "ssh_port": "sshPort",
    "auth_path": "authPath",
    "auth_source": "authSource",
    "auth_available": "authAvailable",
    "step_order": "stepOrder",
    "step_statuses": "stepStatuses",
    "step_missing_prerequisites": "stepMissingPrerequisites",
    "blocked_step": "blockedStep",
    "tart_started_count": "tartStartedCount",
    "tart_stopped_count": "tartStoppedCount",
    "host_stock_codex_uploaded_any": "hostStockCodexUploadedAny",
    "step_details": "stepDetails",
}
EXPECTED_RELEASE_STEPS = (
    "remote-acquisition",
    "auth-onboarding",
    "auth-persistence",
    "update-agent",
    "live",
)
TART_TARGET_MODE = "tart"
DIRECT_SSH_TARGET_MODE = "direct-ssh"


def _truthy_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def infer_target_mode(evidence: Mapping[str, Any]) -> str | None:
    target_mode = evidence.get("targetMode")
    if target_mode in {TART_TARGET_MODE, DIRECT_SSH_TARGET_MODE}:
        return str(target_mode)
    if _truthy_string(evidence.get("tartName")):
        return TART_TARGET_MODE
    if _truthy_string(evidence.get("sshTarget")):
        return DIRECT_SSH_TARGET_MODE
    return None


def _env_path(name: str) -> Path | None:
    value = os.environ.get(name)
    return Path(value) if value else None


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise SystemExit(f"{name} must be an integer: {value!r}") from exc


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run the stock-Codex compatibility signed-package release-candidate "
            "gate. This is a thin wrapper around the clean-VM release aggregate."
        )
    )
    parser.add_argument(
        "--pkg-path",
        type=Path,
        default=_env_path(ENV_PKG_PATH),
        help=f"Signed/notarized package artifact. Defaults to {ENV_PKG_PATH}.",
    )
    parser.add_argument(
        "--codex-path",
        type=Path,
        default=_env_path(ENV_CODEX_PATH),
        help=(
            "Optional stock Codex reference binary. If omitted, the underlying "
            f"proof resolves codex from PATH. Defaults to {ENV_CODEX_PATH}."
        ),
    )
    parser.add_argument(
        "--clean-vm-tart-name",
        default=os.environ.get(ENV_TART_NAME),
        help=f"Disposable Tart VM name. Defaults to {ENV_TART_NAME}.",
    )
    parser.add_argument(
        "--clean-vm-ssh-target",
        default=os.environ.get(ENV_SSH_TARGET),
        help=f"Direct SSH target for an already-running VM. Defaults to {ENV_SSH_TARGET}.",
    )
    parser.add_argument(
        "--clean-vm-ssh-user",
        default=os.environ.get(ENV_SSH_USER),
        help=(
            "SSH user for --clean-vm-tart-name. Defaults to "
            f"{ENV_SSH_USER}, or admin when a Tart VM name is supplied."
        ),
    )
    parser.add_argument(
        "--clean-vm-ssh-identity",
        type=Path,
        default=_env_path(ENV_SSH_IDENTITY),
        help=f"Optional SSH identity. Defaults to {ENV_SSH_IDENTITY}.",
    )
    parser.add_argument(
        "--clean-vm-ssh-port",
        type=int,
        default=_env_int(ENV_SSH_PORT, 22),
        help=f"SSH port. Defaults to {ENV_SSH_PORT}, then 22.",
    )
    start_group = parser.add_mutually_exclusive_group()
    start_group.add_argument(
        "--start-tart",
        dest="start_tart",
        action="store_true",
        default=None,
        help="Force the wrapper to pass --clean-vm-start-tart.",
    )
    start_group.add_argument(
        "--no-start-tart",
        dest="start_tart",
        action="store_false",
        help="Do not pass --clean-vm-start-tart, even with --clean-vm-tart-name.",
    )
    parser.add_argument(
        "--proof-script",
        type=Path,
        default=None,
        help="Override the underlying proof script path. Mostly for tests.",
    )
    parser.add_argument(
        "--python",
        dest="python_executable",
        default=sys.executable,
        help="Python executable used for the underlying proof script.",
    )
    parser.add_argument(
        "--print-command",
        action="store_true",
        help="Print the expanded underlying proof command without running it.",
    )
    parser.add_argument(
        "--evidence-output",
        type=Path,
        default=_env_path(ENV_EVIDENCE_OUTPUT),
        help=(
            "Optional JSON release evidence path. Defaults to "
            f"{ENV_EVIDENCE_OUTPUT}. Refuses to overwrite unless "
            "--force-evidence-output is also passed."
        ),
    )
    parser.add_argument(
        "--force-evidence-output",
        action="store_true",
        help="Overwrite an existing --evidence-output artifact.",
    )
    return parser.parse_args(argv)


def build_command(args: argparse.Namespace) -> tuple[str, ...]:
    proof_script = args.proof_script or (
        repo_root() / "scripts" / "prove_stock_codex_replacement.py"
    )
    proof_script = proof_script.expanduser().resolve()
    if not proof_script.is_file():
        raise SystemExit(f"underlying proof script is missing: {proof_script}")

    if args.pkg_path is None:
        raise SystemExit(f"--pkg-path or {ENV_PKG_PATH} is required.")
    pkg_path = args.pkg_path.expanduser().resolve()
    if not pkg_path.is_file():
        raise SystemExit(f"signed/notarized package artifact is missing: {pkg_path}")

    tart_name = args.clean_vm_tart_name
    ssh_target = args.clean_vm_ssh_target
    if tart_name and ssh_target:
        raise SystemExit("pass either --clean-vm-tart-name or --clean-vm-ssh-target, not both.")
    if not tart_name and not ssh_target:
        raise SystemExit(
            "release-candidate gate requires --clean-vm-tart-name or --clean-vm-ssh-target."
        )

    start_tart = bool(tart_name) if args.start_tart is None else bool(args.start_tart)
    if start_tart and not tart_name:
        raise SystemExit("--start-tart requires --clean-vm-tart-name.")

    command: list[str] = [
        args.python_executable,
        str(proof_script),
        "--proof",
        PROOF_NAME,
        "--pkg-path",
        str(pkg_path),
    ]
    if args.codex_path is not None:
        command.extend(["--codex-path", str(args.codex_path.expanduser())])
    if tart_name:
        command.extend(["--clean-vm-tart-name", tart_name])
        command.extend(["--clean-vm-ssh-user", args.clean_vm_ssh_user or "admin"])
    if ssh_target:
        command.extend(["--clean-vm-ssh-target", ssh_target])
        if args.clean_vm_ssh_user:
            command.extend(["--clean-vm-ssh-user", args.clean_vm_ssh_user])
    if args.clean_vm_ssh_identity is not None:
        command.extend(["--clean-vm-ssh-identity", str(args.clean_vm_ssh_identity.expanduser())])
    if args.clean_vm_ssh_port != 22:
        command.extend(["--clean-vm-ssh-port", str(args.clean_vm_ssh_port)])
    if start_tart:
        command.append("--clean-vm-start-tart")
    return tuple(command)


def parse_proof_value(raw_value: str) -> Any:
    value = raw_value.strip()
    if value in {"True", "False"}:
        return value == "True"
    if value in {"None", "null"}:
        return None
    if value and (value[0] in "[{\"" or value in {"true", "false"}):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return raw_value
    if value.lstrip("-").isdigit():
        try:
            return int(value)
        except ValueError:
            return raw_value
    return raw_value


def parse_release_evidence(stdout: str) -> dict[str, Any]:
    evidence_fields: dict[str, Any] = {}
    for line in stdout.splitlines():
        if not line.startswith(PROOF_OUTPUT_PREFIX) or "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        evidence_fields[key.removeprefix(PROOF_OUTPUT_PREFIX)] = parse_proof_value(
            raw_value
        )
    return evidence_fields


def build_evidence_artifact(
    *,
    command: Sequence[str],
    completed: subprocess.CompletedProcess[str],
    stdout: str,
    stderr: str,
) -> dict[str, Any]:
    fields = parse_release_evidence(stdout)
    artifact: dict[str, Any] = {
        "kind": EVIDENCE_KIND,
        "schemaVersion": EVIDENCE_SCHEMA_VERSION,
        "createdAt": datetime.now(UTC).isoformat(),
        "proof": PROOF_NAME,
        "command": list(command),
        "exitCode": completed.returncode,
        "underlyingExitCode": completed.returncode,
        "releaseCriteriaFailures": [],
        "stdoutLineCount": len(stdout.splitlines()),
        "stderrLineCount": len(stderr.splitlines()),
        "fields": fields,
    }
    for proof_key, artifact_key in EVIDENCE_FIELD_MAP.items():
        if proof_key in fields:
            artifact[artifact_key] = fields[proof_key]
    target_mode = infer_target_mode(artifact)
    if target_mode is not None:
        artifact["targetMode"] = target_mode
    return artifact


def write_evidence_artifact(
    path: Path,
    evidence: dict[str, Any],
    *,
    force: bool,
) -> None:
    output_path = path.expanduser().resolve()
    if output_path.exists() and not force:
        raise SystemExit(
            f"evidence output already exists: {output_path}; pass "
            "--force-evidence-output to replace it."
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def release_criteria_failures(evidence: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    if evidence.get("status") != "replacement-ready":
        failures.append(f"status={evidence.get('status')!r}")

    step_order = evidence.get("stepOrder")
    if step_order != list(EXPECTED_RELEASE_STEPS):
        failures.append(f"stepOrder={step_order!r}")

    step_statuses = evidence.get("stepStatuses")
    if not isinstance(step_statuses, dict):
        failures.append("stepStatuses is missing or not an object")
    else:
        for step_name in EXPECTED_RELEASE_STEPS:
            if step_statuses.get(step_name) != "replacement-ready":
                failures.append(f"stepStatuses[{step_name}]={step_statuses.get(step_name)!r}")

    step_missing = evidence.get("stepMissingPrerequisites")
    if not isinstance(step_missing, dict):
        failures.append("stepMissingPrerequisites is missing or not an object")
    else:
        blocked_steps = {
            step_name: missing
            for step_name, missing in step_missing.items()
            if missing
        }
        if blocked_steps:
            failures.append(f"stepMissingPrerequisites={blocked_steps!r}")

    if evidence.get("blockedStep") is not None:
        failures.append(f"blockedStep={evidence.get('blockedStep')!r}")
    if evidence.get("hostStockCodexUploadedAny") is not False:
        failures.append(
            f"hostStockCodexUploadedAny={evidence.get('hostStockCodexUploadedAny')!r}"
        )

    target_mode = infer_target_mode(evidence)
    if target_mode is None:
        failures.append("targetMode could not be inferred")
    tart_started = evidence.get("tartStartedCount")
    tart_stopped = evidence.get("tartStoppedCount")
    if tart_started != tart_stopped:
        failures.append(f"tart counts differ: started={tart_started!r} stopped={tart_stopped!r}")
    if target_mode == TART_TARGET_MODE:
        if not evidence.get("tartName"):
            failures.append("tartName is missing for tart target mode")
        if tart_started != len(EXPECTED_RELEASE_STEPS):
            failures.append(f"tartStartedCount={tart_started!r}")
    elif target_mode == DIRECT_SSH_TARGET_MODE:
        if not evidence.get("sshTarget"):
            failures.append("sshTarget is missing for direct SSH target mode")
        if tart_started != 0:
            failures.append(f"tartStartedCount={tart_started!r}")
        if tart_stopped != 0:
            failures.append(f"tartStoppedCount={tart_stopped!r}")

    step_details = evidence.get("stepDetails")
    if not isinstance(step_details, dict):
        failures.append("stepDetails is missing or not an object")
    else:
        if set(step_details) != set(EXPECTED_RELEASE_STEPS):
            failures.append(f"stepDetails keys={sorted(step_details)!r}")
        expected_tart_value = target_mode == TART_TARGET_MODE
        for step_name in EXPECTED_RELEASE_STEPS:
            detail = step_details.get(step_name)
            if not isinstance(detail, dict):
                failures.append(f"stepDetails[{step_name}] is missing or not an object")
                continue
            for tart_key in ("tartStarted", "tartStopped"):
                if detail.get(tart_key) is not expected_tart_value:
                    failures.append(
                        f"stepDetails[{step_name}][{tart_key}]={detail.get(tart_key)!r}"
                    )

    for required_key in (
        "packageSha256",
        "stockCodexSha256",
        "caskVersion",
        "caskUrl",
        "caskSha256",
        "channelPolicy",
        "stepDetails",
    ):
        if required_key not in evidence:
            failures.append(f"{required_key} is missing")
    return failures


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    command = build_command(args)
    if args.print_command and args.evidence_output is not None:
        raise SystemExit("--print-command cannot be combined with --evidence-output.")
    if args.print_command:
        print(" ".join(shlex.quote(part) for part in command))
        return 0
    if args.evidence_output is None:
        completed = subprocess.run(command, check=False)
        return completed.returncode
    evidence_output = args.evidence_output.expanduser().resolve()
    if evidence_output.exists() and not args.force_evidence_output:
        raise SystemExit(
            f"evidence output already exists: {evidence_output}; pass "
            "--force-evidence-output to replace it."
        )
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    stdout = completed.stdout or ""
    stderr = completed.stderr or ""
    if stdout:
        sys.stdout.write(stdout)
    if stderr:
        sys.stderr.write(stderr)
    evidence = build_evidence_artifact(
        command=command,
        completed=completed,
        stdout=stdout,
        stderr=stderr,
    )
    failures = [] if completed.returncode != 0 else release_criteria_failures(evidence)
    wrapper_exit_code = completed.returncode if completed.returncode != 0 else int(bool(failures))
    evidence["exitCode"] = wrapper_exit_code
    evidence["releaseCriteriaFailures"] = failures
    write_evidence_artifact(evidence_output, evidence, force=args.force_evidence_output)
    if failures:
        print("release evidence did not satisfy release-candidate criteria:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
    return wrapper_exit_code


if __name__ == "__main__":
    raise SystemExit(main())
