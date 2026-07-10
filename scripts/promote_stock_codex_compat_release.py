#!/usr/bin/env python3
"""Build and promote one provenance-bound stock-Codex compatibility release."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import uuid
import xml.etree.ElementTree as ET
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

PROMOTION_KIND = "omnigent-stock-codex-compat-release-promotion"
PROMOTION_SCHEMA_VERSION = 2
SUPPORTED_PROMOTION_SCHEMA_VERSIONS = {1, PROMOTION_SCHEMA_VERSION}
PROMOTION_STATUS = "promoted"
PACKAGE_FILENAME = "omnigent-stock-codex-compat.pkg"
EVIDENCE_FILENAME = "release-evidence.json"
MANIFEST_FILENAME = "promotion-manifest.json"
PACKAGE_MANIFEST_RELATIVE_PATH = Path(
    "Payload/Library/Application Support/Omnigent/stock-codex-compat/pkg-manifest.json"
)
RELEASE_VERSION_RELATIVE_PATH = Path("packaging/stock-codex-compat/VERSION")
STABLE_RELEASE_VERSION_PATTERN = re.compile(
    r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
)
PRODUCER_PROOF = "stock-codex-compat-pkg-signed-notarized"
PRODUCER_PREFIX = "stock_codex_compat_pkg_signed_notarized_"
RELEASE_EVIDENCE_KIND = "omnigent-stock-codex-compat-release-candidate-evidence"
OFFICIAL_CHANNEL_POLICY = "official-openai-github-release"
NOTARYTOOL_PROFILE_ENV = "OMNIGENT_NOTARYTOOL_PROFILE"
PKG_SIGN_IDENTITY_ENV = "OMNIGENT_PKG_SIGN_IDENTITY"
PKG_SIGN_KEYCHAIN_ENV = "OMNIGENT_PKG_SIGN_KEYCHAIN"


class PromotionError(RuntimeError):
    """The release could not be promoted without weakening the contract."""


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path, *, label: str) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PromotionError(f"{label} is not readable JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise PromotionError(f"{label} must be a JSON object: {path}")
    return payload


def _parse_marker_value(raw_value: str) -> object:
    value = raw_value.strip()
    if value in {"True", "False"}:
        return value == "True"
    if value in {"None", "null"}:
        return None
    if value and (value[0] in '[{"' or value in {"true", "false"}):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return raw_value
    return raw_value


def _parse_prefixed_markers(stdout: str, *, prefix: str) -> dict[str, object]:
    fields: dict[str, object] = {}
    for line in stdout.splitlines():
        if not line.startswith(prefix) or "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        fields[key.removeprefix(prefix)] = _parse_marker_value(raw_value)
    return fields


def _run_command(
    command: Sequence[str],
    *,
    cwd: Path,
    timeout: float,
    label: str,
) -> subprocess.CompletedProcess[str]:
    try:
        completed = subprocess.run(
            list(command),
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise PromotionError(f"{label} could not execute: {command!r}") from exc
    if completed.returncode != 0:
        raise PromotionError(
            f"{label} failed with exit {completed.returncode}.\n"
            f"command={shlex.join(command)}\n"
            f"stdout={completed.stdout}\n"
            f"stderr={completed.stderr}"
        )
    return completed


def _git_capture(source_root: Path, *arguments: str, check: bool = True) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(source_root), *arguments],
            check=False,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise PromotionError("git provenance inspection could not execute") from exc
    if check and completed.returncode != 0:
        raise PromotionError(
            "git provenance inspection failed.\n"
            f"command={completed.args!r}\n"
            f"stdout={completed.stdout}\n"
            f"stderr={completed.stderr}"
        )
    if completed.returncode != 0:
        return ""
    return completed.stdout.strip()


def _sanitize_remote_url(value: str) -> str:
    for scheme in ("https://", "http://"):
        if value.startswith(scheme):
            authority_and_path = value.removeprefix(scheme)
            authority, separator, path = authority_and_path.partition("/")
            if "@" in authority:
                authority = authority.rsplit("@", 1)[1]
            return f"{scheme}{authority}{separator}{path}"
    return value


def git_provenance(source_root: Path) -> dict[str, object]:
    source_root = source_root.resolve()
    discovered_root = Path(_git_capture(source_root, "rev-parse", "--show-toplevel")).resolve()
    if discovered_root != source_root:
        raise PromotionError(f"release source root mismatch: {discovered_root} != {source_root}")
    dirty = _git_capture(
        source_root,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
    )
    if dirty:
        raise PromotionError(
            f"release promotion requires a clean Git worktree; dirty paths:\n{dirty}"
        )
    commit = _validate_git_oid(
        _git_capture(source_root, "rev-parse", "HEAD"),
        label="release source commit",
    )
    upstream = _git_capture(
        source_root,
        "rev-parse",
        "--abbrev-ref",
        "--symbolic-full-name",
        "@{upstream}",
    )
    upstream_commit = _validate_git_oid(
        _git_capture(source_root, "rev-parse", "@{upstream}"),
        label="local upstream commit",
    )
    if upstream_commit != commit:
        raise PromotionError(
            "release promotion requires HEAD to match its pushed upstream; "
            f"HEAD={commit} upstream={upstream_commit}"
        )
    branch = _git_capture(source_root, "branch", "--show-current", check=False)
    if not branch:
        raise PromotionError("release promotion requires an attached Git branch")
    remote_name = _git_capture(
        source_root,
        "config",
        "--get",
        f"branch.{branch}.remote",
    )
    remote_ref = _git_capture(
        source_root,
        "config",
        "--get",
        f"branch.{branch}.merge",
    )
    if not remote_name or remote_name == "." or not remote_ref.startswith("refs/heads/"):
        raise PromotionError(
            "release promotion requires a remote branch upstream, not local-only tracking"
        )
    remote_listing = _git_capture(
        source_root,
        "ls-remote",
        "--exit-code",
        remote_name,
        remote_ref,
    )
    matching_remote_commits = [
        fields[0]
        for line in remote_listing.splitlines()
        if len(fields := line.split()) == 2 and fields[1] == remote_ref
    ]
    if len(matching_remote_commits) != 1:
        raise PromotionError(
            f"remote upstream ref did not resolve exactly once: {remote_name} {remote_ref}"
        )
    remote_commit = _validate_git_oid(
        matching_remote_commits[0],
        label="remote upstream commit",
    )
    if remote_commit != commit:
        raise PromotionError(
            "release promotion requires HEAD to exist at the remote upstream; "
            f"HEAD={commit} remote={remote_commit}"
        )
    origin_url = _git_capture(
        source_root,
        "remote",
        "get-url",
        "origin",
        check=False,
    )
    remote_url = _git_capture(source_root, "remote", "get-url", remote_name)
    return {
        "repoRoot": str(source_root),
        "commit": commit,
        "branch": branch,
        "commitTimestamp": _git_capture(source_root, "show", "-s", "--format=%cI", "HEAD"),
        "originUrl": _sanitize_remote_url(origin_url) if origin_url else None,
        "upstream": upstream,
        "upstreamCommit": upstream_commit,
        "remoteName": remote_name,
        "remoteRef": remote_ref,
        "remoteUrl": _sanitize_remote_url(remote_url),
        "remoteCommit": remote_commit,
        "treeClean": True,
        "pushed": True,
    }


def _read_release_version(source_root: Path) -> str:
    version_path = source_root / RELEASE_VERSION_RELATIVE_PATH
    try:
        version = version_path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise PromotionError(
            f"could not read compatibility-package release version: {version_path}"
        ) from exc
    if not STABLE_RELEASE_VERSION_PATTERN.fullmatch(version):
        raise PromotionError(
            f"compatibility-package release version must be stable MAJOR.MINOR.PATCH: {version!r}"
        )
    return version


def _require_script(path: Path, *, label: str) -> Path:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise PromotionError(f"{label} is missing: {resolved}")
    return resolved


def _release_tool_provenance(
    source_root: Path,
    path: Path,
    *,
    label: str,
) -> dict[str, str]:
    try:
        relative_path = path.relative_to(source_root)
    except ValueError as exc:
        raise PromotionError(
            f"{label} must resolve inside the release source checkout: {path}"
        ) from exc
    relative = relative_path.as_posix()
    tracked = _git_capture(
        source_root,
        "ls-files",
        "--error-unmatch",
        "--",
        relative,
    )
    if tracked != relative:
        raise PromotionError(f"{label} is not a tracked source file: {relative}")
    head_blob = _validate_git_oid(
        _git_capture(source_root, "rev-parse", f"HEAD:{relative}"),
        label=f"{label} HEAD blob",
    )
    worktree_blob = _validate_git_oid(
        _git_capture(source_root, "hash-object", "--", relative),
        label=f"{label} worktree blob",
    )
    if worktree_blob != head_blob:
        raise PromotionError(f"{label} content does not match HEAD: {relative}")
    return {
        "path": relative,
        "sha256": sha256_file(path),
        "gitBlob": head_blob,
    }


def _validate_output_dir(output_dir: Path, *, source_root: Path) -> Path:
    resolved = output_dir.expanduser().resolve()
    try:
        resolved.relative_to(source_root)
    except ValueError:
        pass
    else:
        raise PromotionError("release output directory must be outside the source checkout")
    if resolved.exists():
        raise PromotionError(f"immutable release output already exists: {resolved}")
    return resolved


def _validate_sha256(value: object, *, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise PromotionError(f"{label} is not a SHA-256 digest: {value!r}")
    try:
        int(value, 16)
    except ValueError as exc:
        raise PromotionError(f"{label} is not a SHA-256 digest: {value!r}") from exc
    return value.lower()


def _validate_git_oid(value: object, *, label: str) -> str:
    if not isinstance(value, str) or len(value) != 40:
        raise PromotionError(f"{label} is not a 40-character Git object id: {value!r}")
    try:
        int(value, 16)
    except ValueError as exc:
        raise PromotionError(f"{label} is not a 40-character Git object id: {value!r}") from exc
    return value.lower()


def _validate_producer_fields(
    fields: Mapping[str, object],
    *,
    package_path: Path,
    expected_package_version: str,
    notarytool_profile: str,
    expected_signing_identity: str,
) -> dict[str, object]:
    if not package_path.is_file():
        raise PromotionError(f"signed package producer did not create the package: {package_path}")
    if fields.get("status") != "replacement-ready":
        raise PromotionError(f"signed package producer status={fields.get('status')!r}")
    if fields.get("missing_prerequisites") != []:
        raise PromotionError(
            "signed package producer reported missing prerequisites: "
            f"{fields.get('missing_prerequisites')!r}"
        )
    if fields.get("package_path") != str(package_path):
        raise PromotionError("signed package producer reported the wrong package path")
    package_sha256 = _validate_sha256(
        fields.get("package_sha256"),
        label="producer package SHA-256",
    )
    if package_sha256 != sha256_file(package_path):
        raise PromotionError("signed package producer SHA-256 does not match the package")
    source_bundle_sha256 = _validate_sha256(
        fields.get("source_bundle_sha256"),
        label="source bundle SHA-256",
    )
    package_identifier = fields.get("identifier")
    if not isinstance(package_identifier, str) or not package_identifier:
        raise PromotionError("signed package producer omitted the package identifier")
    if fields.get("version") != expected_package_version:
        raise PromotionError(
            "signed package version does not match the release version: "
            f"{fields.get('version')!r} != {expected_package_version!r}"
        )
    sign_identity = fields.get("sign_identity")
    if sign_identity != expected_signing_identity:
        raise PromotionError(
            "signed package producer used the wrong signing identity: "
            f"{sign_identity!r} != {expected_signing_identity!r}"
        )
    if not sign_identity.startswith("Developer ID Installer:"):
        raise PromotionError(f"unexpected package signing identity: {sign_identity!r}")
    if fields.get("signed") is not True:
        raise PromotionError("signed package producer did not report signed=True")
    if fields.get("notarytool_profile") != notarytool_profile:
        raise PromotionError("signed package producer used the wrong notarytool profile")
    notary_submission_id = fields.get("notary_submission_id")
    try:
        uuid.UUID(str(notary_submission_id))
    except (ValueError, AttributeError) as exc:
        raise PromotionError(
            f"invalid notarization submission id: {notary_submission_id!r}"
        ) from exc
    if str(fields.get("notary_status", "")).lower() != "accepted":
        raise PromotionError(f"notarization was not accepted: {fields.get('notary_status')!r}")
    signature_status = fields.get("signature_status")
    if not isinstance(signature_status, str) or not signature_status:
        raise PromotionError("signed package producer omitted signature status")
    return {
        "packageSha256": package_sha256,
        "sourceBundleSha256": source_bundle_sha256,
        "packageIdentifier": package_identifier,
        "packageVersion": expected_package_version,
        "signingIdentity": sign_identity,
        "signingIdentitySource": fields.get("sign_identity_source"),
        "signingKeychain": fields.get("signing_keychain"),
        "signatureStatus": signature_status,
        "notarytoolProfile": notarytool_profile,
        "notarySubmissionId": str(notary_submission_id),
        "notaryStatus": fields.get("notary_status"),
    }


def _command_option_value(command: object, option: str) -> str | None:
    if not isinstance(command, list) or command.count(option) != 1:
        return None
    index = command.index(option)
    if index + 1 >= len(command):
        return None
    value = command[index + 1]
    return value if isinstance(value, str) and value else None


def _validate_release_evidence(
    evidence: Mapping[str, object],
    *,
    recorded_package_path: str,
    package_sha256: str,
) -> dict[str, object]:
    if evidence.get("kind") != RELEASE_EVIDENCE_KIND:
        raise PromotionError(f"unexpected release evidence kind: {evidence.get('kind')!r}")
    if evidence.get("exitCode") != 0 or evidence.get("underlyingExitCode") != 0:
        raise PromotionError("release evidence records a nonzero proof result")
    if evidence.get("releaseCriteriaFailures") != []:
        raise PromotionError("release evidence records failed release criteria")
    if evidence.get("status") != "replacement-ready":
        raise PromotionError(f"release evidence status={evidence.get('status')!r}")
    if evidence.get("packagePath") != recorded_package_path:
        raise PromotionError("release evidence packagePath does not match its build path")
    if evidence.get("packageSha256") != package_sha256:
        raise PromotionError("release evidence packageSha256 does not match the release package")
    if _command_option_value(evidence.get("command"), "--pkg-path") != recorded_package_path:
        raise PromotionError("release evidence command does not name its package build path")
    if evidence.get("channelPolicy") != OFFICIAL_CHANNEL_POLICY:
        raise PromotionError(f"release evidence channelPolicy={evidence.get('channelPolicy')!r}")
    cask_version = evidence.get("caskVersion")
    cask_url = evidence.get("caskUrl")
    cask_sha256 = _validate_sha256(
        evidence.get("caskSha256"),
        label="stock Codex archive SHA-256",
    )
    if not isinstance(cask_version, str) or not cask_version:
        raise PromotionError("release evidence omitted caskVersion")
    if not isinstance(cask_url, str) or not cask_url.startswith(
        "https://github.com/openai/codex/releases/download/"
    ):
        raise PromotionError(f"release evidence caskUrl={cask_url!r}")
    step_details = evidence.get("stepDetails")
    if not isinstance(step_details, Mapping):
        raise PromotionError("release evidence omitted stepDetails")
    return {
        "kind": evidence.get("kind"),
        "schemaVersion": evidence.get("schemaVersion"),
        "sha256": None,
        "targetMode": evidence.get("targetMode"),
        "channelPolicy": evidence.get("channelPolicy"),
        "stockCodexVersion": cask_version,
        "stockCodexUrl": cask_url,
        "stockCodexArchiveSha256": cask_sha256,
        "sshTarget": evidence.get("sshTarget"),
        "tartName": evidence.get("tartName"),
        "authPath": evidence.get("authPath"),
        "authSource": evidence.get("authSource"),
        "stepOrder": evidence.get("stepOrder"),
        "stepStatuses": evidence.get("stepStatuses"),
        "authPersistenceThreadId": (
            step_details.get("auth-persistence", {}).get("threadId")
            if isinstance(step_details.get("auth-persistence"), Mapping)
            else None
        ),
        "liveThreadId": (
            step_details.get("live", {}).get("threadId")
            if isinstance(step_details.get("live"), Mapping)
            else None
        ),
        "hostStockCodexUploadedAny": evidence.get("hostStockCodexUploadedAny"),
    }


def _artifact_path(output_dir: Path, value: object, *, label: str) -> Path:
    if not isinstance(value, str) or not value or Path(value).name != value:
        raise PromotionError(f"{label} must be a release-directory filename")
    path = output_dir / value
    if path.is_symlink():
        raise PromotionError(f"{label} must be a regular file, not a symlink: {path}")
    if not path.is_file():
        raise PromotionError(f"{label} is missing: {path}")
    return path


def _validated_release_tools(
    manifest: Mapping[str, object],
) -> dict[str, Mapping[str, object]]:
    release_tools = manifest.get("releaseTools")
    expected_names = {"producer", "releaseCandidate", "evidenceChecker"}
    if not isinstance(release_tools, Mapping) or set(release_tools) != expected_names:
        raise PromotionError("promotion manifest releaseTools records are invalid")
    validated: dict[str, Mapping[str, object]] = {}
    for name in sorted(expected_names):
        record = release_tools.get(name)
        if not isinstance(record, Mapping):
            raise PromotionError(f"promotion release tool record is invalid: {name}")
        path_value = record.get("path")
        if (
            not isinstance(path_value, str)
            or not path_value
            or Path(path_value).is_absolute()
            or ".." in Path(path_value).parts
        ):
            raise PromotionError(f"promotion release tool path is invalid: {name}")
        _validate_sha256(record.get("sha256"), label=f"{name} release tool SHA-256")
        _validate_git_oid(record.get("gitBlob"), label=f"{name} release tool Git blob")
        validated[name] = record
    return validated


def _require_tool(name: str) -> str:
    tool_path = shutil.which(name)
    if not tool_path:
        raise PromotionError(f"required release verification tool is missing: {name}")
    return tool_path


def _verify_package_distribution(
    package_path: Path,
    *,
    expected_signing_identity: str,
    cwd: Path,
) -> None:
    pkgutil = _require_tool("pkgutil")
    xcrun = _require_tool("xcrun")
    spctl = _require_tool("spctl")
    signature = _run_command(
        (pkgutil, "--check-signature", str(package_path)),
        cwd=cwd,
        timeout=120,
        label="promoted package signature verification",
    )
    signature_output = (signature.stdout or "") + (signature.stderr or "")
    signature_lines = {line.strip() for line in signature_output.splitlines()}
    if f"1. {expected_signing_identity}" not in signature_lines:
        raise PromotionError(
            "promoted package signature does not match the manifest signing identity"
        )
    _run_command(
        (xcrun, "stapler", "validate", str(package_path)),
        cwd=cwd,
        timeout=300,
        label="promoted package stapled-ticket verification",
    )
    gatekeeper = _run_command(
        (spctl, "-a", "-vv", "-t", "install", str(package_path)),
        cwd=cwd,
        timeout=120,
        label="promoted package Gatekeeper verification",
    )
    gatekeeper_output = (gatekeeper.stdout or "") + (gatekeeper.stderr or "")
    if "accepted" not in gatekeeper_output.lower():
        raise PromotionError("Gatekeeper did not report the promoted package accepted")
    if "Notarized Developer ID" not in gatekeeper_output:
        raise PromotionError("Gatekeeper did not report a notarized Developer ID package")
    gatekeeper_lines = {line.strip() for line in gatekeeper_output.splitlines()}
    if f"origin={expected_signing_identity}" not in gatekeeper_lines:
        raise PromotionError("Gatekeeper origin does not match the manifest signing identity")


def _verify_package_metadata(
    package_path: Path,
    *,
    expected_identifier: str,
    expected_version: str,
    expected_source_bundle_sha256: str,
    cwd: Path,
) -> None:
    pkgutil = _require_tool("pkgutil")
    with tempfile.TemporaryDirectory(prefix="omnigent-release-pkg-expand-") as directory:
        expand_dir = Path(directory) / "expanded"
        _run_command(
            (pkgutil, "--expand-full", str(package_path), str(expand_dir)),
            cwd=cwd,
            timeout=300,
            label="promoted package metadata verification",
        )
        package_info_path = expand_dir / "PackageInfo"
        try:
            package_info = ET.fromstring(package_info_path.read_text(encoding="utf-8"))
        except (OSError, ET.ParseError) as exc:
            raise PromotionError(
                f"promoted package PackageInfo is invalid: {package_info_path}"
            ) from exc
        actual_metadata = {
            "identifier": package_info.attrib.get("identifier"),
            "version": package_info.attrib.get("version"),
            "install-location": package_info.attrib.get("install-location"),
        }
        expected_metadata = {
            "identifier": expected_identifier,
            "version": expected_version,
            "install-location": "/",
        }
        if actual_metadata != expected_metadata:
            raise PromotionError(
                "promoted package PackageInfo does not match the promotion manifest: "
                f"{actual_metadata!r}"
            )
        package_manifest = _load_json(
            expand_dir / PACKAGE_MANIFEST_RELATIVE_PATH,
            label="embedded package manifest",
        )
        for key, expected in (
            ("packageIdentifier", expected_identifier),
            ("packageVersion", expected_version),
            ("sourceBundleSha256", expected_source_bundle_sha256),
        ):
            if package_manifest.get(key) != expected:
                raise PromotionError(
                    f"embedded package manifest does not match promotion field: {key}"
                )


def verify_promotion_directory(
    output_dir: Path,
    *,
    checker_script: Path,
    python_executable: str,
) -> dict[str, object]:
    output_dir = output_dir.expanduser().resolve()
    manifest_path = output_dir / MANIFEST_FILENAME
    if manifest_path.is_symlink():
        raise PromotionError(
            f"promotion manifest must be a regular file, not a symlink: {manifest_path}"
        )
    manifest = _load_json(manifest_path, label="promotion manifest")
    if manifest.get("kind") != PROMOTION_KIND:
        raise PromotionError(f"unexpected promotion kind: {manifest.get('kind')!r}")
    schema_version = manifest.get("schemaVersion")
    if (
        not isinstance(schema_version, int)
        or schema_version not in SUPPORTED_PROMOTION_SCHEMA_VERSIONS
    ):
        raise PromotionError(f"unexpected promotion schemaVersion: {schema_version!r}")
    if manifest.get("status") != PROMOTION_STATUS:
        raise PromotionError(f"promotion status={manifest.get('status')!r}")
    source = manifest.get("source")
    if not isinstance(source, Mapping):
        raise PromotionError("promotion manifest omitted source provenance")
    commit = _validate_git_oid(
        source.get("commit"),
        label="promotion source commit",
    )
    if source.get("treeClean") is not True or source.get("pushed") is not True:
        raise PromotionError("promotion source was not recorded clean and pushed")
    if source.get("upstreamCommit") != commit:
        raise PromotionError("promotion source commit does not match upstreamCommit")
    if source.get("remoteCommit") != commit:
        raise PromotionError("promotion source commit does not match remoteCommit")
    source_repo_root = source.get("repoRoot")
    if not isinstance(source_repo_root, str) or not Path(source_repo_root).is_absolute():
        raise PromotionError("promotion source repoRoot is invalid")
    release_version_record = manifest.get("releaseVersion")
    if schema_version == PROMOTION_SCHEMA_VERSION:
        if not isinstance(release_version_record, Mapping):
            raise PromotionError("promotion manifest omitted releaseVersion")
        if release_version_record.get("path") != RELEASE_VERSION_RELATIVE_PATH.as_posix():
            raise PromotionError("promotion releaseVersion path is invalid")
        _validate_sha256(
            release_version_record.get("sha256"),
            label="release version SHA-256",
        )
        _validate_git_oid(
            release_version_record.get("gitBlob"),
            label="release version Git blob",
        )
        release_version = release_version_record.get("version")
        if not isinstance(release_version, str) or not STABLE_RELEASE_VERSION_PATTERN.fullmatch(
            release_version
        ):
            raise PromotionError("promotion releaseVersion is not stable MAJOR.MINOR.PATCH")
    else:
        release_version = None
    release_tools = _validated_release_tools(manifest)
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, Mapping):
        raise PromotionError("promotion manifest omitted artifacts")
    package_record = artifacts.get("package")
    evidence_record = artifacts.get("releaseEvidence")
    if not isinstance(package_record, Mapping) or not isinstance(evidence_record, Mapping):
        raise PromotionError("promotion manifest artifact records are invalid")
    package_path = _artifact_path(
        output_dir,
        package_record.get("file"),
        label="promoted package",
    )
    evidence_path = _artifact_path(
        output_dir,
        evidence_record.get("file"),
        label="release evidence",
    )
    package_sha256 = sha256_file(package_path)
    evidence_sha256 = sha256_file(evidence_path)
    package_build_path = package_record.get("buildPath")
    evidence_build_path = evidence_record.get("buildPath")
    if not isinstance(package_build_path, str) or not Path(package_build_path).is_absolute():
        raise PromotionError("promoted package buildPath is invalid")
    if not isinstance(evidence_build_path, str) or not Path(evidence_build_path).is_absolute():
        raise PromotionError("release evidence buildPath is invalid")
    if package_record.get("sha256") != package_sha256:
        raise PromotionError("promoted package SHA-256 does not match the manifest")
    if evidence_record.get("sha256") != evidence_sha256:
        raise PromotionError("release evidence SHA-256 does not match the manifest")
    package_summary = manifest.get("package")
    if not isinstance(package_summary, Mapping):
        raise PromotionError("promotion manifest omitted package summary")
    if package_summary.get("packageSha256") != package_sha256:
        raise PromotionError("promotion package summary SHA-256 does not match")
    signing_identity = package_summary.get("signingIdentity")
    if not isinstance(signing_identity, str) or not signing_identity:
        raise PromotionError("promotion package summary omitted signing identity")
    package_identifier = package_summary.get("packageIdentifier")
    package_version = package_summary.get("packageVersion")
    if not isinstance(package_identifier, str) or not package_identifier:
        raise PromotionError("promotion package summary omitted package identifier")
    if not isinstance(package_version, str) or not package_version:
        raise PromotionError("promotion package summary omitted package version")
    if release_version is not None and package_version != release_version:
        raise PromotionError("promotion package version does not match releaseVersion")
    source_bundle_sha256 = _validate_sha256(
        package_summary.get("sourceBundleSha256"),
        label="promotion source bundle SHA-256",
    )
    if package_summary.get("notaryStatus") != "Accepted":
        raise PromotionError("promotion package summary notarization was not accepted")
    try:
        uuid.UUID(str(package_summary.get("notarySubmissionId")))
    except (ValueError, AttributeError) as exc:
        raise PromotionError("promotion package summary has invalid notarization id") from exc
    _verify_package_distribution(
        package_path,
        expected_signing_identity=signing_identity,
        cwd=output_dir,
    )
    _verify_package_metadata(
        package_path,
        expected_identifier=package_identifier,
        expected_version=package_version,
        expected_source_bundle_sha256=source_bundle_sha256,
        cwd=output_dir,
    )
    commands = manifest.get("commands")
    if not isinstance(commands, Mapping):
        raise PromotionError("promotion manifest omitted command provenance")
    producer_command = commands.get("producer")
    candidate_command = commands.get("releaseCandidate")
    evidence_checker_command = commands.get("evidenceChecker")
    command_tools = {
        "producer": producer_command,
        "releaseCandidate": candidate_command,
        "evidenceChecker": evidence_checker_command,
    }
    for name, command in command_tools.items():
        record = release_tools[name]
        if not isinstance(command, list) or len(command) < 2:
            raise PromotionError(f"promotion command is invalid: {name}")
        expected_script = str(Path(source_repo_root) / str(record["path"]))
        if command[1] != expected_script:
            raise PromotionError(f"promotion command does not match releaseTools path: {name}")
    if _command_option_value(producer_command, "--pkg-output-path") != package_build_path:
        raise PromotionError("producer command does not name the promoted package")
    if release_version is not None and (
        _command_option_value(producer_command, "--pkg-version") != release_version
    ):
        raise PromotionError("producer command does not name the stable release version")
    if _command_option_value(candidate_command, "--pkg-path") != package_build_path:
        raise PromotionError("release candidate command does not name the promoted package")
    if _command_option_value(candidate_command, "--evidence-output") != evidence_build_path:
        raise PromotionError("release candidate command does not name release evidence")
    if _command_option_value(evidence_checker_command, "--pkg-path") != package_build_path:
        raise PromotionError("evidence checker command does not name the promoted package")
    if (
        _command_option_value(
            evidence_checker_command,
            "--evidence-output",
        )
        != evidence_build_path
    ):
        raise PromotionError("evidence checker command does not name release evidence")
    checker_script = _require_script(checker_script, label="release evidence checker")
    checker_command = (
        python_executable,
        str(checker_script),
        "--pkg-path",
        str(package_path),
        "--evidence-output",
        str(evidence_path),
    )
    _run_command(
        checker_command,
        cwd=checker_script.parents[1],
        timeout=120,
        label="offline release evidence verification",
    )
    evidence = _load_json(evidence_path, label="release evidence")
    summary = _validate_release_evidence(
        evidence,
        recorded_package_path=package_build_path,
        package_sha256=package_sha256,
    )
    release_record = manifest.get("releaseEvidence")
    if not isinstance(release_record, Mapping):
        raise PromotionError("promotion manifest omitted releaseEvidence summary")
    for key in (
        "targetMode",
        "channelPolicy",
        "stockCodexVersion",
        "stockCodexUrl",
        "stockCodexArchiveSha256",
        "authPersistenceThreadId",
        "liveThreadId",
        "hostStockCodexUploadedAny",
    ):
        if release_record.get(key) != summary.get(key):
            raise PromotionError(f"promotion manifest releaseEvidence mismatch: {key}")
    return manifest


def _producer_command(
    args: argparse.Namespace,
    *,
    package_path: Path,
    package_version: str,
) -> tuple[str, ...]:
    command = [
        args.python_executable,
        str(args.proof_script),
        "--proof",
        PRODUCER_PROOF,
        "--pkg-output-path",
        str(package_path),
        "--pkg-version",
        package_version,
        "--notarytool-profile",
        args.notarytool_profile,
    ]
    if args.pkg_sign_identity:
        command.extend(["--pkg-sign-identity", args.pkg_sign_identity])
    if args.pkg_sign_keychain is not None:
        command.extend(["--pkg-sign-keychain", str(args.pkg_sign_keychain)])
    return tuple(command)


def _release_candidate_command(
    args: argparse.Namespace,
    *,
    package_path: Path,
    evidence_path: Path,
) -> tuple[str, ...]:
    command = [
        args.python_executable,
        str(args.release_candidate_script),
        "--python",
        args.python_executable,
        "--proof-script",
        str(args.proof_script),
        "--pkg-path",
        str(package_path),
        "--evidence-output",
        str(evidence_path),
    ]
    if args.codex_path is not None:
        command.extend(["--codex-path", str(args.codex_path)])
    if args.clean_vm_tart_name:
        command.extend(["--clean-vm-tart-name", args.clean_vm_tart_name])
        if args.clean_vm_ssh_user:
            command.extend(["--clean-vm-ssh-user", args.clean_vm_ssh_user])
        if args.start_tart is True:
            command.append("--start-tart")
        elif args.start_tart is False:
            command.append("--no-start-tart")
    if args.clean_vm_ssh_target:
        if args.start_tart is not None:
            raise PromotionError("--start-tart/--no-start-tart cannot be used with direct SSH")
        if args.clean_vm_remote_codex_home is None:
            raise PromotionError("direct-SSH promotion requires --clean-vm-remote-codex-home")
        command.extend(["--clean-vm-ssh-target", args.clean_vm_ssh_target])
        command.extend(["--clean-vm-remote-codex-home", args.clean_vm_remote_codex_home])
        if args.clean_vm_ssh_user:
            command.extend(["--clean-vm-ssh-user", args.clean_vm_ssh_user])
    if args.clean_vm_ssh_identity is not None:
        command.extend(["--clean-vm-ssh-identity", str(args.clean_vm_ssh_identity)])
    if args.clean_vm_ssh_port != 22:
        command.extend(["--clean-vm-ssh-port", str(args.clean_vm_ssh_port)])
    return tuple(command)


def _checker_command(
    args: argparse.Namespace,
    *,
    package_path: Path,
    evidence_path: Path,
) -> tuple[str, ...]:
    return (
        args.python_executable,
        str(args.evidence_checker_script),
        "--pkg-path",
        str(package_path),
        "--evidence-output",
        str(evidence_path),
    )


def _validate_normal_args(args: argparse.Namespace, *, source_root: Path) -> None:
    if args.output_dir is None:
        raise PromotionError("--output-dir is required for release promotion")
    if not args.notarytool_profile:
        raise PromotionError(f"--notarytool-profile or {NOTARYTOOL_PROFILE_ENV} is required")
    if not args.pkg_sign_identity:
        raise PromotionError(f"--pkg-sign-identity or {PKG_SIGN_IDENTITY_ENV} is required")
    if not args.pkg_sign_identity.startswith("Developer ID Installer:"):
        raise PromotionError("--pkg-sign-identity must name a Developer ID Installer identity")
    if bool(args.clean_vm_tart_name) == bool(args.clean_vm_ssh_target):
        raise PromotionError("pass exactly one of --clean-vm-tart-name or --clean-vm-ssh-target")
    if args.clean_vm_ssh_target:
        if args.start_tart is not None:
            raise PromotionError("--start-tart/--no-start-tart cannot be used with direct SSH")
        if not args.clean_vm_remote_codex_home:
            raise PromotionError("direct-SSH promotion requires --clean-vm-remote-codex-home")
        if not Path(args.clean_vm_remote_codex_home).is_absolute():
            raise PromotionError("--clean-vm-remote-codex-home must be absolute")
    elif args.clean_vm_remote_codex_home:
        raise PromotionError("--clean-vm-remote-codex-home is supported only for direct SSH")
    if args.codex_path is not None:
        args.codex_path = args.codex_path.expanduser().resolve()
        if not args.codex_path.is_file():
            raise PromotionError(f"stock Codex reference is missing: {args.codex_path}")
    if args.clean_vm_ssh_identity is not None:
        args.clean_vm_ssh_identity = args.clean_vm_ssh_identity.expanduser().resolve()
        if not args.clean_vm_ssh_identity.is_file():
            raise PromotionError(f"clean VM SSH identity is missing: {args.clean_vm_ssh_identity}")
    if args.pkg_sign_keychain is not None:
        args.pkg_sign_keychain = args.pkg_sign_keychain.expanduser().resolve()
        if not args.pkg_sign_keychain.exists():
            raise PromotionError(f"package signing keychain is missing: {args.pkg_sign_keychain}")
    args.output_dir = _validate_output_dir(args.output_dir, source_root=source_root)


def promote_release(args: argparse.Namespace) -> dict[str, object]:
    source_root = repo_root().resolve()
    _validate_normal_args(args, source_root=source_root)
    args.proof_script = _require_script(args.proof_script, label="proof script")
    args.release_candidate_script = _require_script(
        args.release_candidate_script,
        label="release candidate wrapper",
    )
    args.evidence_checker_script = _require_script(
        args.evidence_checker_script,
        label="release evidence checker",
    )
    provenance = git_provenance(source_root)
    release_tools = {
        "producer": _release_tool_provenance(
            source_root,
            args.proof_script,
            label="proof script",
        ),
        "releaseCandidate": _release_tool_provenance(
            source_root,
            args.release_candidate_script,
            label="release candidate wrapper",
        ),
        "evidenceChecker": _release_tool_provenance(
            source_root,
            args.evidence_checker_script,
            label="release evidence checker",
        ),
    }
    package_version = _read_release_version(source_root)
    release_version_record = _release_tool_provenance(
        source_root,
        (source_root / RELEASE_VERSION_RELATIVE_PATH).resolve(),
        label="compatibility-package release version",
    )
    release_version_record["version"] = package_version
    output_dir: Path = args.output_dir
    try:
        output_dir.parent.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir()
    except FileExistsError as exc:
        raise PromotionError(f"immutable release output already exists: {output_dir}") from exc
    except OSError as exc:
        raise PromotionError(f"could not create immutable release output: {output_dir}") from exc
    package_path = output_dir / PACKAGE_FILENAME
    evidence_path = output_dir / EVIDENCE_FILENAME
    manifest_path = output_dir / MANIFEST_FILENAME
    try:
        producer_command = _producer_command(
            args,
            package_path=package_path,
            package_version=package_version,
        )
        print("promotion_phase=signed-notarized-package")
        producer = _run_command(
            producer_command,
            cwd=source_root,
            timeout=3600,
            label="signed/notarized package producer",
        )
        producer_fields = _parse_prefixed_markers(
            producer.stdout,
            prefix=PRODUCER_PREFIX,
        )
        package_record = _validate_producer_fields(
            producer_fields,
            package_path=package_path,
            expected_package_version=package_version,
            notarytool_profile=args.notarytool_profile,
            expected_signing_identity=args.pkg_sign_identity,
        )
        package_sha256 = package_record.get("packageSha256")
        if not isinstance(package_sha256, str):
            raise PromotionError("validated package record omitted package SHA-256")

        candidate_command = _release_candidate_command(
            args,
            package_path=package_path,
            evidence_path=evidence_path,
        )
        print("promotion_phase=clean-machine-release-candidate")
        _run_command(
            candidate_command,
            cwd=source_root,
            timeout=7200,
            label="clean-machine release candidate",
        )

        checker_command = _checker_command(
            args,
            package_path=package_path,
            evidence_path=evidence_path,
        )
        print("promotion_phase=offline-release-evidence")
        _run_command(
            checker_command,
            cwd=source_root,
            timeout=120,
            label="offline release evidence verification",
        )
        evidence = _load_json(evidence_path, label="release evidence")
        evidence_summary = _validate_release_evidence(
            evidence,
            recorded_package_path=str(package_path),
            package_sha256=package_sha256,
        )
        evidence_sha256 = sha256_file(evidence_path)
        evidence_summary["sha256"] = evidence_sha256

        final_provenance = git_provenance(source_root)
        if final_provenance != provenance:
            raise PromotionError("Git provenance changed during release promotion")
        manifest = {
            "kind": PROMOTION_KIND,
            "schemaVersion": PROMOTION_SCHEMA_VERSION,
            "status": PROMOTION_STATUS,
            "createdAt": datetime.now(UTC).isoformat(),
            "source": provenance,
            "releaseVersion": release_version_record,
            "releaseTools": release_tools,
            "artifacts": {
                "package": {
                    "file": PACKAGE_FILENAME,
                    "buildPath": str(package_path),
                    "sha256": package_sha256,
                },
                "releaseEvidence": {
                    "file": EVIDENCE_FILENAME,
                    "buildPath": str(evidence_path),
                    "sha256": evidence_sha256,
                },
            },
            "package": package_record,
            "releaseEvidence": evidence_summary,
            "commands": {
                "producer": list(producer_command),
                "releaseCandidate": list(candidate_command),
                "evidenceChecker": list(checker_command),
            },
        }
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=output_dir,
            prefix=f".{MANIFEST_FILENAME}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_manifest = Path(handle.name)
            json.dump(manifest, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temporary_manifest, manifest_path)
        manifest_path.chmod(0o644)
        return verify_promotion_directory(
            output_dir,
            checker_script=args.evidence_checker_script,
            python_executable=args.python_executable,
        )
    except BaseException:
        shutil.rmtree(output_dir, ignore_errors=True)
        raise


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    root = repo_root()
    parser = argparse.ArgumentParser(
        description=(
            "Build, validate, and promote an immutable stock-Codex compatibility "
            "release from one clean pushed Git commit."
        )
    )
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument(
        "--verify-only",
        type=Path,
        help="Verify an existing promotion directory without building or using Git.",
    )
    parser.add_argument("--codex-path", type=Path)
    parser.add_argument(
        "--notarytool-profile",
        default=os.environ.get(NOTARYTOOL_PROFILE_ENV),
    )
    parser.add_argument(
        "--pkg-sign-identity",
        default=os.environ.get(PKG_SIGN_IDENTITY_ENV),
    )
    parser.add_argument(
        "--pkg-sign-keychain",
        type=Path,
        default=(
            Path(os.environ[PKG_SIGN_KEYCHAIN_ENV])
            if os.environ.get(PKG_SIGN_KEYCHAIN_ENV)
            else None
        ),
    )
    parser.add_argument("--clean-vm-tart-name")
    parser.add_argument("--clean-vm-ssh-target")
    parser.add_argument("--clean-vm-ssh-user")
    parser.add_argument("--clean-vm-ssh-identity", type=Path)
    parser.add_argument("--clean-vm-ssh-port", type=int, default=22)
    parser.add_argument("--clean-vm-remote-codex-home")
    start_group = parser.add_mutually_exclusive_group()
    start_group.add_argument("--start-tart", dest="start_tart", action="store_true")
    start_group.add_argument("--no-start-tart", dest="start_tart", action="store_false")
    parser.set_defaults(start_tart=None)
    parser.add_argument(
        "--proof-script",
        type=Path,
        default=root / "scripts" / "prove_stock_codex_replacement.py",
    )
    parser.add_argument(
        "--release-candidate-script",
        type=Path,
        default=root / "scripts" / "prove_stock_codex_compat_release_candidate.py",
    )
    parser.add_argument(
        "--evidence-checker-script",
        type=Path,
        default=root / "scripts" / "check_stock_codex_compat_release_evidence.py",
    )
    parser.add_argument("--python", dest="python_executable", default=sys.executable)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.verify_only is not None:
            if args.output_dir is not None:
                raise PromotionError("--verify-only cannot be combined with --output-dir")
            manifest = verify_promotion_directory(
                args.verify_only,
                checker_script=args.evidence_checker_script,
                python_executable=args.python_executable,
            )
            output_dir = args.verify_only.expanduser().resolve()
        else:
            manifest = promote_release(args)
            output_dir = args.output_dir
    except PromotionError as exc:
        print(f"release_promotion_error={exc}", file=sys.stderr)
        return 1
    manifest_path = output_dir / MANIFEST_FILENAME
    print("release_promotion_status=promoted")
    print(f"release_promotion_directory={output_dir}")
    print(f"release_promotion_manifest={manifest_path}")
    print(f"release_promotion_manifest_sha256={sha256_file(manifest_path)}")
    source = manifest.get("source")
    package = manifest.get("package")
    release_evidence = manifest.get("releaseEvidence")
    if not all(isinstance(value, Mapping) for value in (source, package, release_evidence)):
        print(
            "release_promotion_error=promotion result omitted required summaries",
            file=sys.stderr,
        )
        return 1
    assert isinstance(source, Mapping)
    assert isinstance(package, Mapping)
    assert isinstance(release_evidence, Mapping)
    print(f"release_promotion_source_commit={source['commit']}")
    print(f"release_promotion_package_sha256={package['packageSha256']}")
    print(f"release_promotion_stock_codex_version={release_evidence['stockCodexVersion']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
