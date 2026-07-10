"""Tests for ``scripts/promote_stock_codex_compat_release.py``."""

from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "promote_stock_codex_compat_release.py"
_COMMIT = "a" * 40
_UPSTREAM = "origin/spike/release"
_NOTARY_ID = "d44ce89e-3316-443e-9da1-dcae9f0f2a37"
_SIGNING_IDENTITY = "Developer ID Installer: Release Test (ABCDE12345)"


def _load_module() -> Any:
    spec = importlib.util.spec_from_file_location(
        "scripts_promote_stock_codex_compat_release",
        _SCRIPT_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_MOD = _load_module()


def _write_file(path: Path, text: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _provenance(source_root: Path) -> dict[str, Any]:
    return {
        "repoRoot": str(source_root.resolve()),
        "commit": _COMMIT,
        "branch": "spike/release",
        "commitTimestamp": "2026-07-10T00:00:00-05:00",
        "originUrl": "git@github.com:jkaunert/omnigent.git",
        "upstream": _UPSTREAM,
        "upstreamCommit": _COMMIT,
        "remoteName": "origin",
        "remoteRef": "refs/heads/spike/release",
        "remoteUrl": "git@github.com:jkaunert/omnigent.git",
        "remoteCommit": _COMMIT,
        "treeClean": True,
        "pushed": True,
    }


def _release_evidence(package_path: Path) -> dict[str, Any]:
    package_sha256 = _MOD.sha256_file(package_path)
    remote_codex_home = "/Users/omnigent-clean/.codex-omnigent-wrapper-auth"
    return {
        "kind": _MOD.RELEASE_EVIDENCE_KIND,
        "schemaVersion": 1,
        "proof": "stock-codex-compat-pkg-clean-vm-release",
        "command": [
            "/opt/python",
            "/repo/scripts/prove_stock_codex_replacement.py",
            "--proof",
            "stock-codex-compat-pkg-clean-vm-release",
            "--pkg-path",
            str(package_path),
            "--clean-vm-ssh-target",
            "omnigent-clean@10.0.0.10",
            "--clean-vm-remote-codex-home",
            remote_codex_home,
        ],
        "exitCode": 0,
        "underlyingExitCode": 0,
        "releaseCriteriaFailures": [],
        "status": "replacement-ready",
        "missingPrerequisites": [],
        "packagePath": str(package_path),
        "packageSha256": package_sha256,
        "caskVersion": "0.144.1",
        "caskUrl": (
            "https://github.com/openai/codex/releases/download/"
            "rust-v0.144.1/codex-aarch64-apple-darwin.tar.gz"
        ),
        "caskSha256": "c" * 64,
        "channelPolicy": _MOD.OFFICIAL_CHANNEL_POLICY,
        "targetMode": "direct-ssh",
        "sshTarget": "omnigent-clean@10.0.0.10",
        "tartName": None,
        "authPath": f"{remote_codex_home}/auth.json",
        "authSource": f"remote-existing-codex-home:{remote_codex_home}",
        "authAvailable": True,
        "stepOrder": [
            "remote-acquisition",
            "auth-onboarding",
            "auth-persistence",
            "update-agent",
            "live",
        ],
        "stepStatuses": {
            "remote-acquisition": "replacement-ready",
            "auth-onboarding": "replacement-ready",
            "auth-persistence": "replacement-ready",
            "update-agent": "replacement-ready",
            "live": "replacement-ready",
        },
        "hostStockCodexUploadedAny": False,
        "stepDetails": {
            "auth-persistence": {
                "authUploaded": False,
                "threadId": "thread-auth",
            },
            "live": {
                "authUploaded": False,
                "threadId": "thread-live",
            },
        },
    }


def _promotion_args(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> tuple[Path, Path, argparse.Namespace]:
    source_root = tmp_path / "repo"
    _write_file(
        source_root / "pyproject.toml",
        '[project]\nname = "omnigent"\nversion = "0.3.0.dev0"\n',
    )
    scripts_root = source_root / "scripts"
    proof_script = _write_file(scripts_root / "prove.py")
    candidate_script = _write_file(scripts_root / "candidate.py")
    checker_script = _write_file(scripts_root / "checker.py")
    codex_path = _write_file(tmp_path / "stock" / "codex")
    ssh_identity = _write_file(tmp_path / "keys" / "id_release")
    output_dir = tmp_path / "artifacts" / "release"
    monkeypatch.setattr(_MOD, "repo_root", lambda: source_root)
    args = _MOD.parse_args(
        [
            "--output-dir",
            str(output_dir),
            "--python",
            "/opt/python",
            "--proof-script",
            str(proof_script),
            "--release-candidate-script",
            str(candidate_script),
            "--evidence-checker-script",
            str(checker_script),
            "--codex-path",
            str(codex_path),
            "--notarytool-profile",
            "OmnigentExperiment",
            "--pkg-sign-identity",
            _SIGNING_IDENTITY,
            "--clean-vm-ssh-target",
            "omnigent-clean@10.0.0.10",
            "--clean-vm-remote-codex-home",
            "/Users/omnigent-clean/.codex-omnigent-wrapper-auth",
            "--clean-vm-ssh-identity",
            str(ssh_identity),
        ]
    )
    return source_root, output_dir, args


def _install_success_fakes(
    monkeypatch: pytest.MonkeyPatch,
    *,
    source_root: Path,
    fail_label: str | None = None,
    bad_producer_hash: bool = False,
) -> list[tuple[str, tuple[str, ...]]]:
    calls: list[tuple[str, tuple[str, ...]]] = []
    provenance = _provenance(source_root)
    monkeypatch.setattr(_MOD, "git_provenance", lambda _root: dict(provenance))
    monkeypatch.setattr(
        _MOD,
        "_release_tool_provenance",
        lambda _root, path, *, label: {
            "path": f"scripts/{path.name}",
            "sha256": _MOD.sha256_file(path),
            "gitBlob": "d" * 40,
            "label": label,
        },
    )
    monkeypatch.setattr(_MOD.shutil, "which", lambda name: f"/usr/bin/{name}")

    def fake_run_command(
        command: Any,
        *,
        cwd: Path,
        timeout: float,
        label: str,
    ) -> subprocess.CompletedProcess[str]:
        del cwd, timeout
        command_tuple = tuple(command)
        calls.append((label, command_tuple))
        if fail_label == label:
            raise _MOD.PromotionError(f"forced failure: {label}")
        if label == "signed/notarized package producer":
            package_path = Path(command_tuple[command_tuple.index("--pkg-output-path") + 1])
            package_path.write_bytes(b"signed-notarized-package")
            package_sha256 = "0" * 64 if bad_producer_hash else _MOD.sha256_file(package_path)
            stdout = "\n".join(
                [
                    f"{_MOD.PRODUCER_PREFIX}status=replacement-ready",
                    f"{_MOD.PRODUCER_PREFIX}missing_prerequisites=[]",
                    f"{_MOD.PRODUCER_PREFIX}sign_identity={_SIGNING_IDENTITY}",
                    (
                        f"{_MOD.PRODUCER_PREFIX}sign_identity_source="
                        "autodiscovered-developer-id-installer"
                    ),
                    f"{_MOD.PRODUCER_PREFIX}signing_keychain=None",
                    (f"{_MOD.PRODUCER_PREFIX}notarytool_profile=OmnigentExperiment"),
                    f"{_MOD.PRODUCER_PREFIX}package_path={package_path}",
                    f"{_MOD.PRODUCER_PREFIX}package_sha256={package_sha256}",
                    f"{_MOD.PRODUCER_PREFIX}source_bundle_sha256={'b' * 64}",
                    f"{_MOD.PRODUCER_PREFIX}identifier=ai.omnigent.stock-codex-compat",
                    f"{_MOD.PRODUCER_PREFIX}version=0.3.0.dev0",
                    (
                        f"{_MOD.PRODUCER_PREFIX}signature_status="
                        "signed by a developer certificate issued by Apple for distribution"
                    ),
                    f"{_MOD.PRODUCER_PREFIX}signed=True",
                    f"{_MOD.PRODUCER_PREFIX}notary_submission_id={_NOTARY_ID}",
                    f"{_MOD.PRODUCER_PREFIX}notary_status=Accepted",
                ]
            )
            return subprocess.CompletedProcess(command_tuple, 0, stdout=stdout, stderr="")
        if label == "clean-machine release candidate":
            package_path = Path(command_tuple[command_tuple.index("--pkg-path") + 1])
            evidence_path = Path(command_tuple[command_tuple.index("--evidence-output") + 1])
            evidence_path.write_text(
                json.dumps(_release_evidence(package_path)),
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(command_tuple, 0, stdout="ready\n", stderr="")
        if label == "promoted package signature verification":
            return subprocess.CompletedProcess(
                command_tuple,
                0,
                stdout=f"1. {_SIGNING_IDENTITY}\n",
                stderr="",
            )
        if label == "promoted package Gatekeeper verification":
            return subprocess.CompletedProcess(
                command_tuple,
                0,
                stdout="",
                stderr=(
                    "package: accepted\n"
                    "source=Notarized Developer ID\n"
                    f"origin={_SIGNING_IDENTITY}\n"
                ),
            )
        if label == "promoted package metadata verification":
            expand_dir = Path(command_tuple[-1])
            _write_file(
                expand_dir / "PackageInfo",
                (
                    '<pkg-info identifier="ai.omnigent.stock-codex-compat" '
                    'version="0.3.0.dev0" install-location="/" />\n'
                ),
            )
            _write_file(
                expand_dir / _MOD.PACKAGE_MANIFEST_RELATIVE_PATH,
                json.dumps(
                    {
                        "packageIdentifier": "ai.omnigent.stock-codex-compat",
                        "packageVersion": "0.3.0.dev0",
                        "sourceBundleSha256": "b" * 64,
                    }
                ),
            )
            return subprocess.CompletedProcess(
                command_tuple,
                0,
                stdout="expanded\n",
                stderr="",
            )
        return subprocess.CompletedProcess(command_tuple, 0, stdout="ok\n", stderr="")

    monkeypatch.setattr(_MOD, "_run_command", fake_run_command)
    return calls


def test_promote_release_builds_validates_and_writes_manifest_last(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_root, output_dir, args = _promotion_args(monkeypatch, tmp_path)
    calls = _install_success_fakes(monkeypatch, source_root=source_root)

    manifest = _MOD.promote_release(args)

    package_path = output_dir / _MOD.PACKAGE_FILENAME
    evidence_path = output_dir / _MOD.EVIDENCE_FILENAME
    manifest_path = output_dir / _MOD.MANIFEST_FILENAME
    assert package_path.is_file()
    assert evidence_path.is_file()
    assert manifest_path.is_file()
    assert stat.S_IMODE(manifest_path.stat().st_mode) == 0o644
    assert manifest["source"]["commit"] == _COMMIT
    assert manifest["source"]["pushed"] is True
    assert manifest["package"]["packageIdentifier"] == ("ai.omnigent.stock-codex-compat")
    assert manifest["package"]["notarySubmissionId"] == _NOTARY_ID
    assert manifest["artifacts"]["package"]["sha256"] == _MOD.sha256_file(package_path)
    assert manifest["artifacts"]["releaseEvidence"]["sha256"] == (_MOD.sha256_file(evidence_path))
    assert manifest["releaseEvidence"]["stockCodexVersion"] == "0.144.1"
    assert manifest["releaseEvidence"]["liveThreadId"] == "thread-live"
    assert [label for label, _command in calls] == [
        "signed/notarized package producer",
        "clean-machine release candidate",
        "offline release evidence verification",
        "promoted package signature verification",
        "promoted package stapled-ticket verification",
        "promoted package Gatekeeper verification",
        "promoted package metadata verification",
        "offline release evidence verification",
    ]
    assert not list(output_dir.glob(f".{_MOD.MANIFEST_FILENAME}.*.tmp"))


def test_promote_release_cleans_partial_directory_on_candidate_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_root, output_dir, args = _promotion_args(monkeypatch, tmp_path)
    _install_success_fakes(
        monkeypatch,
        source_root=source_root,
        fail_label="clean-machine release candidate",
    )

    with pytest.raises(_MOD.PromotionError, match="forced failure"):
        _MOD.promote_release(args)

    assert not output_dir.exists()


def test_promote_release_cleans_partial_directory_on_producer_hash_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_root, output_dir, args = _promotion_args(monkeypatch, tmp_path)
    _install_success_fakes(
        monkeypatch,
        source_root=source_root,
        bad_producer_hash=True,
    )

    with pytest.raises(_MOD.PromotionError, match="does not match the package"):
        _MOD.promote_release(args)

    assert not output_dir.exists()


def test_promote_release_refuses_existing_or_checkout_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_root, output_dir, args = _promotion_args(monkeypatch, tmp_path)
    output_dir.mkdir(parents=True)

    with pytest.raises(_MOD.PromotionError, match="already exists"):
        _MOD.promote_release(args)

    args.output_dir = source_root / "release"
    with pytest.raises(_MOD.PromotionError, match="outside the source checkout"):
        _MOD.promote_release(args)


def test_promote_release_requires_remote_auth_for_direct_ssh(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _source_root, _output_dir, args = _promotion_args(monkeypatch, tmp_path)
    args.clean_vm_remote_codex_home = None

    with pytest.raises(_MOD.PromotionError, match=r"requires.*remote-codex-home"):
        _MOD.promote_release(args)


def test_verify_promotion_directory_rejects_tampered_package(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_root, output_dir, args = _promotion_args(monkeypatch, tmp_path)
    _install_success_fakes(monkeypatch, source_root=source_root)
    _MOD.promote_release(args)
    (output_dir / _MOD.PACKAGE_FILENAME).write_bytes(b"tampered")

    with pytest.raises(_MOD.PromotionError, match="package SHA-256"):
        _MOD.verify_promotion_directory(
            output_dir,
            checker_script=args.evidence_checker_script,
            python_executable=args.python_executable,
        )


def test_verify_promotion_directory_rejects_symlinked_package(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_root, output_dir, args = _promotion_args(monkeypatch, tmp_path)
    _install_success_fakes(monkeypatch, source_root=source_root)
    _MOD.promote_release(args)
    package_path = output_dir / _MOD.PACKAGE_FILENAME
    external_package = tmp_path / "external.pkg"
    shutil.copyfile(package_path, external_package)
    package_path.unlink()
    package_path.symlink_to(external_package)

    with pytest.raises(_MOD.PromotionError, match="regular file, not a symlink"):
        _MOD.verify_promotion_directory(
            output_dir,
            checker_script=args.evidence_checker_script,
            python_executable=args.python_executable,
        )


def test_verify_promotion_directory_requires_exact_signing_identity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_root, output_dir, args = _promotion_args(monkeypatch, tmp_path)
    _install_success_fakes(monkeypatch, source_root=source_root)
    _MOD.promote_release(args)
    manifest_path = output_dir / _MOD.MANIFEST_FILENAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["package"]["signingIdentity"] = "Developer ID Installer: Release Test"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(_MOD.PromotionError, match="signature does not match"):
        _MOD.verify_promotion_directory(
            output_dir,
            checker_script=args.evidence_checker_script,
            python_executable=args.python_executable,
        )


def test_verify_promotion_directory_rejects_command_path_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_root, output_dir, args = _promotion_args(monkeypatch, tmp_path)
    _install_success_fakes(monkeypatch, source_root=source_root)
    _MOD.promote_release(args)
    manifest_path = output_dir / _MOD.MANIFEST_FILENAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    command = manifest["commands"]["releaseCandidate"]
    command[command.index("--pkg-path") + 1] = "/tmp/other.pkg"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(_MOD.PromotionError, match="does not name the promoted package"):
        _MOD.verify_promotion_directory(
            output_dir,
            checker_script=args.evidence_checker_script,
            python_executable=args.python_executable,
        )


def test_verify_promotion_directory_accepts_relocated_artifacts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_root, output_dir, args = _promotion_args(monkeypatch, tmp_path)
    _install_success_fakes(monkeypatch, source_root=source_root)
    _MOD.promote_release(args)
    relocated_dir = tmp_path / "relocated" / "release"
    shutil.copytree(output_dir, relocated_dir)
    shutil.rmtree(output_dir)

    manifest = _MOD.verify_promotion_directory(
        relocated_dir,
        checker_script=args.evidence_checker_script,
        python_executable=args.python_executable,
    )

    assert manifest["artifacts"]["package"]["buildPath"] == str(output_dir / _MOD.PACKAGE_FILENAME)
    assert (relocated_dir / _MOD.PACKAGE_FILENAME).is_file()


def test_verify_promotion_directory_rejects_package_metadata_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_root, output_dir, args = _promotion_args(monkeypatch, tmp_path)
    _install_success_fakes(monkeypatch, source_root=source_root)
    _MOD.promote_release(args)
    manifest_path = output_dir / _MOD.MANIFEST_FILENAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["package"]["packageIdentifier"] = "ai.example.wrong"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(_MOD.PromotionError, match="PackageInfo does not match"):
        _MOD.verify_promotion_directory(
            output_dir,
            checker_script=args.evidence_checker_script,
            python_executable=args.python_executable,
        )


def test_promote_release_requires_explicit_signing_identity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _source_root, output_dir, args = _promotion_args(monkeypatch, tmp_path)
    args.pkg_sign_identity = None

    with pytest.raises(_MOD.PromotionError, match="pkg-sign-identity"):
        _MOD.promote_release(args)

    assert not output_dir.exists()


def test_release_tool_provenance_rejects_external_or_modified_tool(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "repo"
    source_tool = _write_file(source_root / "scripts" / "release.py", "pass\n")
    external_tool = _write_file(tmp_path / "external.py", "pass\n")

    with pytest.raises(_MOD.PromotionError, match="inside the release source"):
        _MOD._release_tool_provenance(
            source_root,
            external_tool,
            label="proof script",
        )

    def modified_capture(_root: Path, *arguments: str, check: bool = True) -> str:
        del check
        values = {
            (
                "ls-files",
                "--error-unmatch",
                "--",
                "scripts/release.py",
            ): "scripts/release.py",
            ("rev-parse", "HEAD:scripts/release.py"): "d" * 40,
            ("hash-object", "--", "scripts/release.py"): "e" * 40,
        }
        return values[arguments]

    monkeypatch.setattr(_MOD, "_git_capture", modified_capture)
    with pytest.raises(_MOD.PromotionError, match="does not match HEAD"):
        _MOD._release_tool_provenance(
            source_root,
            source_tool,
            label="proof script",
        )


def test_sanitize_remote_url_removes_http_credentials_only() -> None:
    assert (
        _MOD._sanitize_remote_url("https://release-user:secret@github.com/example/repo.git")
        == "https://github.com/example/repo.git"
    )
    assert (
        _MOD._sanitize_remote_url("git@github.com:example/repo.git")
        == "git@github.com:example/repo.git"
    )


def test_git_provenance_rejects_dirty_and_unpushed_sources(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "repo"
    source_root.mkdir()

    def dirty_capture(_root: Path, *arguments: str, check: bool = True) -> str:
        del check
        if arguments == ("rev-parse", "--show-toplevel"):
            return str(source_root)
        if arguments[0] == "status":
            return " M scripts/release.py"
        raise AssertionError(arguments)

    monkeypatch.setattr(_MOD, "_git_capture", dirty_capture)
    with pytest.raises(_MOD.PromotionError, match="clean Git worktree"):
        _MOD.git_provenance(source_root)

    def unpushed_capture(_root: Path, *arguments: str, check: bool = True) -> str:
        del check
        values = {
            ("rev-parse", "--show-toplevel"): str(source_root),
            ("status", "--porcelain=v1", "--untracked-files=all"): "",
            ("rev-parse", "HEAD"): _COMMIT,
            (
                "rev-parse",
                "--abbrev-ref",
                "--symbolic-full-name",
                "@{upstream}",
            ): _UPSTREAM,
            ("rev-parse", "@{upstream}"): "b" * 40,
        }
        return values[arguments]

    monkeypatch.setattr(_MOD, "_git_capture", unpushed_capture)
    with pytest.raises(_MOD.PromotionError, match="match its pushed upstream"):
        _MOD.git_provenance(source_root)


def test_git_provenance_rejects_remote_ref_that_does_not_contain_head(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "repo"
    source_root.mkdir()

    def remote_mismatch_capture(
        _root: Path,
        *arguments: str,
        check: bool = True,
    ) -> str:
        del check
        values = {
            ("rev-parse", "--show-toplevel"): str(source_root),
            ("status", "--porcelain=v1", "--untracked-files=all"): "",
            ("rev-parse", "HEAD"): _COMMIT,
            (
                "rev-parse",
                "--abbrev-ref",
                "--symbolic-full-name",
                "@{upstream}",
            ): _UPSTREAM,
            ("rev-parse", "@{upstream}"): _COMMIT,
            ("branch", "--show-current"): "spike/release",
            ("config", "--get", "branch.spike/release.remote"): "origin",
            (
                "config",
                "--get",
                "branch.spike/release.merge",
            ): "refs/heads/spike/release",
            (
                "ls-remote",
                "--exit-code",
                "origin",
                "refs/heads/spike/release",
            ): f"{'b' * 40}\trefs/heads/spike/release",
        }
        return values[arguments]

    monkeypatch.setattr(_MOD, "_git_capture", remote_mismatch_capture)
    with pytest.raises(_MOD.PromotionError, match="remote upstream"):
        _MOD.git_provenance(source_root)
