#!/usr/bin/env python3
"""Validate stock-Codex compatibility release evidence offline."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

EVIDENCE_KIND = "omnigent-stock-codex-compat-release-candidate-evidence"
EVIDENCE_SCHEMA_VERSION = 1
PROOF_NAME = "stock-codex-compat-pkg-clean-vm-release"
OFFICIAL_CHANNEL_POLICY = "official-openai-github-release"
OFFICIAL_CODEX_RELEASE_PREFIX = "https://github.com/openai/codex/releases/download/"
ENV_EVIDENCE_OUTPUT = "OMNIGENT_STOCK_CODEX_COMPAT_RELEASE_EVIDENCE_OUTPUT"
ENV_PKG_PATH = "OMNIGENT_STOCK_CODEX_COMPAT_RELEASE_PKG_PATH"

EXPECTED_RELEASE_STEPS = (
    "remote-acquisition",
    "auth-onboarding",
    "auth-persistence",
    "update-agent",
    "live",
)
TART_TARGET_MODE = "tart"
DIRECT_SSH_TARGET_MODE = "direct-ssh"

REQUIRED_FIELDS = (
    "kind",
    "schemaVersion",
    "proof",
    "command",
    "exitCode",
    "underlyingExitCode",
    "releaseCriteriaFailures",
    "status",
    "missingPrerequisites",
    "packagePath",
    "packageSha256",
    "stockCodexPath",
    "stockCodexVersion",
    "stockCodexSha256",
    "caskVersion",
    "caskUrl",
    "caskSha256",
    "channelPolicy",
    "authPath",
    "authSource",
    "authAvailable",
    "stepOrder",
    "stepStatuses",
    "stepMissingPrerequisites",
    "blockedStep",
    "tartStartedCount",
    "tartStoppedCount",
    "hostStockCodexUploadedAny",
    "stepDetails",
    "fields",
)


def _env_path(name: str) -> Path | None:
    value = os.environ.get(name)
    return Path(value) if value else None


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Validate a stock-Codex compatibility release evidence JSON artifact "
            "against the package it claims to certify. This does not start a VM "
            "or execute Codex."
        )
    )
    parser.add_argument(
        "--evidence-output",
        type=Path,
        default=_env_path(ENV_EVIDENCE_OUTPUT),
        help=f"Release evidence JSON artifact. Defaults to {ENV_EVIDENCE_OUTPUT}.",
    )
    parser.add_argument(
        "--pkg-path",
        type=Path,
        default=_env_path(ENV_PKG_PATH),
        help=f"Package artifact to hash and compare. Defaults to {ENV_PKG_PATH}.",
    )
    return parser.parse_args(argv)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_evidence(path: Path) -> dict[str, Any]:
    try:
        raw_evidence = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SystemExit(f"release evidence artifact is missing: {path}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"release evidence artifact is not valid JSON: {path}: {exc}") from exc
    if not isinstance(raw_evidence, dict):
        raise SystemExit(f"release evidence artifact must be a JSON object: {path}")
    return raw_evidence


def _missing_required_fields(evidence: Mapping[str, Any]) -> list[str]:
    return [field for field in REQUIRED_FIELDS if field not in evidence]


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


def _check_step_statuses(evidence: Mapping[str, Any]) -> list[str]:
    failures: list[str] = []
    step_order = evidence.get("stepOrder")
    if step_order != list(EXPECTED_RELEASE_STEPS):
        failures.append(f"stepOrder={step_order!r}")

    step_statuses = evidence.get("stepStatuses")
    if not isinstance(step_statuses, Mapping):
        failures.append("stepStatuses is missing or not an object")
    else:
        if set(step_statuses) != set(EXPECTED_RELEASE_STEPS):
            failures.append(f"stepStatuses keys={sorted(step_statuses)!r}")
        for step_name in EXPECTED_RELEASE_STEPS:
            if step_statuses.get(step_name) != "replacement-ready":
                failures.append(f"stepStatuses[{step_name}]={step_statuses.get(step_name)!r}")

    step_missing = evidence.get("stepMissingPrerequisites")
    if not isinstance(step_missing, Mapping):
        failures.append("stepMissingPrerequisites is missing or not an object")
    else:
        blocked_steps = {
            str(step_name): missing
            for step_name, missing in step_missing.items()
            if missing
        }
        if blocked_steps:
            failures.append(f"stepMissingPrerequisites={blocked_steps!r}")
    return failures


def _check_step_details(evidence: Mapping[str, Any], *, target_mode: str | None) -> list[str]:
    failures: list[str] = []
    step_details = evidence.get("stepDetails")
    if not isinstance(step_details, Mapping):
        return ["stepDetails is missing or not an object"]
    if set(step_details) != set(EXPECTED_RELEASE_STEPS):
        failures.append(f"stepDetails keys={sorted(step_details)!r}")
    for step_name in EXPECTED_RELEASE_STEPS:
        detail = step_details.get(step_name)
        if not isinstance(detail, Mapping):
            failures.append(f"stepDetails[{step_name}] is missing or not an object")
            continue
        for status_key in ("status", "remoteStatus"):
            if detail.get(status_key) != "replacement-ready":
                failures.append(
                    f"stepDetails[{step_name}][{status_key}]={detail.get(status_key)!r}"
                )
        if detail.get("hostStockCodexUploaded") is not False:
            failures.append(
                "stepDetails"
                f"[{step_name}][hostStockCodexUploaded]="
                f"{detail.get('hostStockCodexUploaded')!r}"
            )
        expected_tart_value = target_mode == TART_TARGET_MODE
        for tart_key in ("tartStarted", "tartStopped"):
            if detail.get(tart_key) is not expected_tart_value:
                failures.append(f"stepDetails[{step_name}][{tart_key}]={detail.get(tart_key)!r}")

    live_detail = step_details.get("live")
    if isinstance(live_detail, Mapping) and not live_detail.get("threadId"):
        failures.append("stepDetails[live][threadId] is missing")
    auth_persistence_detail = step_details.get("auth-persistence")
    if isinstance(auth_persistence_detail, Mapping) and not auth_persistence_detail.get(
        "threadId"
    ):
        failures.append("stepDetails[auth-persistence][threadId] is missing")
    update_agent_detail = step_details.get("update-agent")
    if isinstance(update_agent_detail, Mapping) and not update_agent_detail.get(
        "scheduledAction"
    ):
        failures.append("stepDetails[update-agent][scheduledAction] is missing")
    return failures


def validate_release_evidence(
    evidence: Mapping[str, Any],
    *,
    pkg_path: Path,
    package_sha256: str,
) -> list[str]:
    failures = [f"{field} is missing" for field in _missing_required_fields(evidence)]

    if evidence.get("kind") != EVIDENCE_KIND:
        failures.append(f"kind={evidence.get('kind')!r}")
    if evidence.get("schemaVersion") != EVIDENCE_SCHEMA_VERSION:
        failures.append(f"schemaVersion={evidence.get('schemaVersion')!r}")
    if evidence.get("proof") != PROOF_NAME:
        failures.append(f"proof={evidence.get('proof')!r}")
    if evidence.get("exitCode") != 0:
        failures.append(f"exitCode={evidence.get('exitCode')!r}")
    if evidence.get("underlyingExitCode") != 0:
        failures.append(f"underlyingExitCode={evidence.get('underlyingExitCode')!r}")
    if evidence.get("releaseCriteriaFailures") != []:
        failures.append(
            f"releaseCriteriaFailures={evidence.get('releaseCriteriaFailures')!r}"
        )
    if evidence.get("status") != "replacement-ready":
        failures.append(f"status={evidence.get('status')!r}")
    if evidence.get("missingPrerequisites") != []:
        failures.append(f"missingPrerequisites={evidence.get('missingPrerequisites')!r}")
    if evidence.get("packageSha256") != package_sha256:
        failures.append(
            f"packageSha256={evidence.get('packageSha256')!r} "
            f"does not match {pkg_path} sha256={package_sha256!r}"
        )
    if evidence.get("channelPolicy") != OFFICIAL_CHANNEL_POLICY:
        failures.append(f"channelPolicy={evidence.get('channelPolicy')!r}")
    cask_url = evidence.get("caskUrl")
    if not isinstance(cask_url, str) or not cask_url.startswith(
        OFFICIAL_CODEX_RELEASE_PREFIX
    ):
        failures.append(f"caskUrl={cask_url!r}")
    if "caskSha256" in evidence and not evidence.get("caskSha256"):
        failures.append("caskSha256 is missing")
    if "stockCodexSha256" in evidence and not evidence.get("stockCodexSha256"):
        failures.append("stockCodexSha256 is missing")
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
    if not isinstance(tart_started, int):
        failures.append(f"tartStartedCount={tart_started!r}")
    if not isinstance(tart_stopped, int):
        failures.append(f"tartStoppedCount={tart_stopped!r}")
    if isinstance(tart_started, int) and isinstance(tart_stopped, int):
        if tart_started != tart_stopped:
            failures.append(
                f"tart counts differ: started={tart_started!r} stopped={tart_stopped!r}"
            )
        if target_mode == TART_TARGET_MODE and tart_started != len(EXPECTED_RELEASE_STEPS):
            failures.append(f"tartStartedCount={tart_started!r}")
        if target_mode == DIRECT_SSH_TARGET_MODE:
            if tart_started != 0:
                failures.append(f"tartStartedCount={tart_started!r}")
            if tart_stopped != 0:
                failures.append(f"tartStoppedCount={tart_stopped!r}")
    if target_mode == TART_TARGET_MODE and not evidence.get("tartName"):
        failures.append("tartName is missing for tart target mode")
    if target_mode == DIRECT_SSH_TARGET_MODE and not evidence.get("sshTarget"):
        failures.append("sshTarget is missing for direct SSH target mode")

    failures.extend(_check_step_statuses(evidence))
    failures.extend(_check_step_details(evidence, target_mode=target_mode))
    return failures


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.evidence_output is None:
        raise SystemExit(f"--evidence-output or {ENV_EVIDENCE_OUTPUT} is required.")
    if args.pkg_path is None:
        raise SystemExit(f"--pkg-path or {ENV_PKG_PATH} is required.")

    evidence_path = args.evidence_output.expanduser().resolve()
    pkg_path = args.pkg_path.expanduser().resolve()
    if not pkg_path.is_file():
        raise SystemExit(f"package artifact is missing: {pkg_path}")

    evidence = load_evidence(evidence_path)
    package_sha256 = sha256_file(pkg_path)
    failures = validate_release_evidence(
        evidence,
        pkg_path=pkg_path,
        package_sha256=package_sha256,
    )
    if failures:
        print("release evidence is not release-ready:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1

    print("release_evidence_status=replacement-ready")
    print(f"release_evidence_package_sha256={package_sha256}")
    print(f"release_evidence_channel_policy={evidence['channelPolicy']}")
    print(f"release_evidence_cask_version={evidence['caskVersion']}")
    print(f"release_evidence_step_order={json.dumps(evidence['stepOrder'])}")
    target_mode = infer_target_mode(evidence)
    if target_mode is not None:
        print(f"release_evidence_target_mode={target_mode}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
