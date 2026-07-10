"""Tests for the public-release clean-Mac acquisition proof."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "prove_stock_codex_compat_published_release.py"
_PACKAGE_URL = (
    "https://github.com/jkaunert/omnigent/releases/download/"
    "stock-codex-compat-v0.1.0/omnigent-stock-codex-compat.pkg"
)
_PACKAGE_SHA256 = "a" * 64


def _load_module() -> Any:
    spec = importlib.util.spec_from_file_location(
        "scripts_prove_stock_codex_compat_published_release",
        _SCRIPT_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_MOD = _load_module()


def _publication() -> dict[str, object]:
    return {
        "repository": "jkaunert/omnigent",
        "tag": "stock-codex-compat-v0.1.0",
        "releaseUrl": (
            "https://github.com/jkaunert/omnigent/releases/tag/stock-codex-compat-v0.1.0"
        ),
        "packageIdentifier": "ai.omnigent.stock-codex-compat",
        "packageVersion": "0.1.0",
        "artifacts": {
            "package": {
                "url": _PACKAGE_URL,
                "sha256": _PACKAGE_SHA256,
            }
        },
    }


def _remote_output(*, cleanup: str = "complete") -> str:
    return "\n".join(
        [
            "published_release_remote_status=replacement-ready",
            f"published_release_remote_package_url={_PACKAGE_URL}",
            f"published_release_remote_package_sha256={_PACKAGE_SHA256}",
            ("published_release_remote_package_identifier=ai.omnigent.stock-codex-compat"),
            "published_release_remote_package_version=0.1.0",
            "published_release_remote_package_uploaded=false",
            "published_release_remote_auth_uploaded=false",
            f"published_release_remote_cleanup={cleanup}",
            "",
        ]
    )


def test_remote_script_downloads_public_package_and_cleans_state() -> None:
    syntax = subprocess.run(
        ["/bin/bash", "-n"],
        input=_MOD.REMOTE_SCRIPT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert syntax.returncode == 0, syntax.stderr
    assert "curl --fail --location" in _MOD.REMOTE_SCRIPT
    assert "sudo -n /usr/sbin/installer" in _MOD.REMOTE_SCRIPT
    assert "sudo -n /usr/sbin/pkgutil --forget" in _MOD.REMOTE_SCRIPT
    assert "published_release_remote_package_uploaded=false" in _MOD.REMOTE_SCRIPT
    assert "scp" not in _MOD.REMOTE_SCRIPT
    assert "auth.json" not in _MOD.REMOTE_SCRIPT


def test_published_release_proof_uses_public_record_and_no_upload(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    record = tmp_path / "publication-record.json"
    record.write_text("{}\n", encoding="utf-8")
    identity = tmp_path / "id_release"
    identity.write_text("key\n", encoding="utf-8")
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        _MOD._PUBLICATION,
        "verify_publication",
        lambda _path: _publication(),
    )

    def fake_run_remote(**kwargs: object) -> subprocess.CompletedProcess[str]:
        captured.update(kwargs)
        return subprocess.CompletedProcess(
            ["ssh"],
            0,
            stdout=_remote_output(),
            stderr="",
        )

    monkeypatch.setattr(_MOD, "_run_remote", fake_run_remote)
    args = _MOD.parse_args(
        [
            "--publication-record",
            str(record),
            "--ssh-target",
            "omnigent-clean@10.0.0.10",
            "--ssh-identity",
            str(identity),
            "--ssh",
            "/usr/bin/ssh",
        ]
    )

    proof = _MOD.prove_published_release(args)

    assert proof["status"] == "replacement-ready"
    assert proof["packageUploaded"] is False
    assert proof["authUploaded"] is False
    assert proof["cleanup"] == "complete"
    assert captured["package_url"] == _PACKAGE_URL
    assert captured["package_sha256"] == _PACKAGE_SHA256


def test_published_release_proof_rejects_incomplete_cleanup_marker(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    record = tmp_path / "publication-record.json"
    record.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(
        _MOD._PUBLICATION,
        "verify_publication",
        lambda _path: _publication(),
    )
    monkeypatch.setattr(
        _MOD,
        "_run_remote",
        lambda **_kwargs: subprocess.CompletedProcess(
            ["ssh"],
            0,
            stdout=_remote_output(cleanup="incomplete"),
            stderr="",
        ),
    )
    args = _MOD.parse_args(
        [
            "--publication-record",
            str(record),
            "--ssh-target",
            "omnigent-clean@10.0.0.10",
            "--ssh",
            "/usr/bin/ssh",
        ]
    )

    with pytest.raises(_MOD.PublishedReleaseProofError, match="marker mismatch"):
        _MOD.prove_published_release(args)


def test_published_release_proof_requires_user_qualified_target(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    record = tmp_path / "publication-record.json"
    record.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(
        _MOD._PUBLICATION,
        "verify_publication",
        lambda _path: _publication(),
    )
    args = _MOD.parse_args(
        [
            "--publication-record",
            str(record),
            "--ssh-target",
            "10.0.0.10",
            "--ssh",
            "/usr/bin/ssh",
        ]
    )

    with pytest.raises(_MOD.PublishedReleaseProofError, match="user@host"):
        _MOD.prove_published_release(args)
