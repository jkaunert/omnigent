"""Tests for ``scripts/publish_stock_codex_compat_release.py``."""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "publish_stock_codex_compat_release.py"
_COMMIT = "a" * 40
_REPOSITORY = "jkaunert/omnigent"
_TAG = "stock-codex-compat-v0.1.0"


def _load_module() -> Any:
    spec = importlib.util.spec_from_file_location(
        "scripts_publish_stock_codex_compat_release",
        _SCRIPT_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_MOD = _load_module()


def _write(path: Path, contents: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(contents)
    return path


def _promotion_fixture(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    promotion_dir = tmp_path / "promotion"
    package = _write(promotion_dir / _MOD._PROMOTION.PACKAGE_FILENAME, b"signed package")
    evidence = _write(promotion_dir / _MOD._PROMOTION.EVIDENCE_FILENAME, b"{}\n")
    manifest_path = _write(
        promotion_dir / _MOD._PROMOTION.MANIFEST_FILENAME,
        b'{"kind":"promotion"}\n',
    )
    manifest: dict[str, object] = {
        "source": {"commit": _COMMIT},
        "package": {
            "packageVersion": "0.1.0",
            "packageIdentifier": "ai.omnigent.stock-codex-compat",
            "packageSha256": _MOD.sha256_file(package),
        },
        "releaseEvidence": {"stockCodexVersion": "0.144.1"},
        "artifacts": {
            "package": {"file": package.name},
            "releaseEvidence": {"file": evidence.name},
        },
    }
    assert manifest_path.is_file()
    return promotion_dir, manifest


def _publication_fixture(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    root = tmp_path / "publication"
    root.mkdir()
    package = _write(root / _MOD._PROMOTION.PACKAGE_FILENAME, b"artifact")
    evidence = _write(root / _MOD._PROMOTION.EVIDENCE_FILENAME, b"{}\n")
    manifest = _write(root / _MOD._PROMOTION.MANIFEST_FILENAME, b"{}\n")
    checksums = root / _MOD.CHECKSUMS_FILENAME
    _MOD._write_checksums((package, evidence, manifest), checksums)
    publication: dict[str, object] = {
        "kind": _MOD.PUBLICATION_KIND,
        "schemaVersion": _MOD.PUBLICATION_SCHEMA_VERSION,
        "status": _MOD.PUBLICATION_STATUS,
        "repository": _REPOSITORY,
        "tag": _TAG,
        "packageVersion": "0.1.0",
        "packageIdentifier": "ai.omnigent.stock-codex-compat",
        "sourceCommit": _COMMIT,
        "releaseUrl": _MOD._release_url(_REPOSITORY, _TAG),
        "publicationRecordUrl": _MOD._release_asset_url(
            _REPOSITORY,
            _TAG,
            _MOD.PUBLICATION_RECORD_FILENAME,
        ),
        "promotionManifestSha256": _MOD.sha256_file(manifest),
        "artifacts": {
            "package": _MOD._artifact_record(
                package,
                url=_MOD._release_asset_url(_REPOSITORY, _TAG, package.name),
            ),
            "releaseEvidence": _MOD._artifact_record(
                evidence,
                url=_MOD._release_asset_url(_REPOSITORY, _TAG, evidence.name),
            ),
            "promotionManifest": _MOD._artifact_record(
                manifest,
                url=_MOD._release_asset_url(_REPOSITORY, _TAG, manifest.name),
            ),
            "checksums": _MOD._artifact_record(
                checksums,
                url=_MOD._release_asset_url(_REPOSITORY, _TAG, checksums.name),
            ),
        },
    }
    record = root / _MOD.PUBLICATION_RECORD_FILENAME
    _MOD._write_json(record, publication)
    return record, publication


def test_validate_tag_uses_independent_compatibility_namespace() -> None:
    assert _MOD._validate_tag(_TAG, version="0.1.0") == _TAG
    with pytest.raises(_MOD.PublicationError, match="release tag must be"):
        _MOD._validate_tag("v0.1.0", version="0.1.0")


def test_verify_release_payload_requires_record_digest_and_exact_assets(
    tmp_path: Path,
) -> None:
    record, publication = _publication_fixture(tmp_path)
    record_sha256 = _MOD.sha256_file(record)
    artifact_paths = [
        path
        for path in (tmp_path / "publication").iterdir()
        if path.name != _MOD.PUBLICATION_RECORD_FILENAME
    ]
    payload = {
        "tag_name": _TAG,
        "draft": True,
        "prerelease": False,
        "html_url": _MOD._release_url(_REPOSITORY, _TAG),
        "body": f"publication record: {record_sha256}",
        "assets": [
            *[
                {
                    "name": artifact.name,
                    "browser_download_url": _MOD._release_asset_url(
                        _REPOSITORY,
                        _TAG,
                        artifact.name,
                    ),
                    "size": artifact.stat().st_size,
                }
                for artifact in artifact_paths
            ],
            {
                "name": _MOD.PUBLICATION_RECORD_FILENAME,
                "browser_download_url": _MOD._release_asset_url(
                    _REPOSITORY,
                    _TAG,
                    _MOD.PUBLICATION_RECORD_FILENAME,
                ),
                "size": record.stat().st_size,
            },
        ],
    }

    urls = _MOD._verify_release_payload(
        payload,
        repository=_REPOSITORY,
        tag=_TAG,
        publication=publication,
        publication_record_sha256=record_sha256,
        expect_draft=True,
    )
    assert set(urls) == {
        *(path.name for path in artifact_paths),
        _MOD.PUBLICATION_RECORD_FILENAME,
    }

    payload["body"] = "digest omitted"
    with pytest.raises(_MOD.PublicationError, match=r"omit.*digest"):
        _MOD._verify_release_payload(
            payload,
            repository=_REPOSITORY,
            tag=_TAG,
            publication=publication,
            publication_record_sha256=record_sha256,
            expect_draft=True,
        )


def test_verify_downloaded_assets_rejects_tampering(tmp_path: Path) -> None:
    record, publication = _publication_fixture(tmp_path)
    download = tmp_path / "download"
    download.mkdir()
    source_artifact = tmp_path / "publication" / _MOD._PROMOTION.PACKAGE_FILENAME
    for artifact in (tmp_path / "publication").iterdir():
        if artifact.name != _MOD.PUBLICATION_RECORD_FILENAME:
            shutil.copy2(artifact, download / artifact.name)
    shutil.copy2(record, download / record.name)
    _MOD._verify_downloaded_assets(
        download,
        publication=publication,
        publication_record_sha256=_MOD.sha256_file(record),
    )
    (download / source_artifact.name).write_bytes(b"tampered")
    with pytest.raises(_MOD.PublicationError, match="SHA-256 mismatch"):
        _MOD._verify_downloaded_assets(
            download,
            publication=publication,
            publication_record_sha256=_MOD.sha256_file(record),
        )


def test_publish_release_drafts_verifies_and_publishes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "repo"
    source_root.mkdir()
    promotion_dir, manifest = _promotion_fixture(tmp_path)
    output_dir = tmp_path / "publication-output"
    calls: list[str] = []
    uploaded_paths: list[Path] = []

    monkeypatch.setattr(_MOD, "repo_root", lambda: source_root)
    monkeypatch.setattr(
        _MOD._PROMOTION,
        "verify_promotion_directory",
        lambda *_args, **_kwargs: manifest,
    )
    monkeypatch.setattr(
        _MOD._PROMOTION,
        "git_provenance",
        lambda _root: {"commit": _COMMIT},
    )
    monkeypatch.setattr(_MOD, "_remote_tag_commit", lambda *_args, **_kwargs: _COMMIT)
    monkeypatch.setattr(_MOD, "_release_exists", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(_MOD, "_verify_public_assets", lambda **_kwargs: None)

    def fake_run_command(
        command: Any,
        *,
        cwd: Path,
        timeout: float,
        label: str,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        del cwd, timeout, check
        calls.append(label)
        command_tuple = tuple(command)
        if label == "GitHub release asset upload":
            repo_index = command_tuple.index("--repo")
            uploaded_paths.extend(Path(value) for value in command_tuple[4:repo_index])
        if label == "GitHub draft release asset download":
            destination = Path(command_tuple[command_tuple.index("--dir") + 1])
            for path in uploaded_paths:
                shutil.copy2(path, destination / path.name)
        return subprocess.CompletedProcess(command_tuple, 0, stdout="ok\n", stderr="")

    def fake_release_payload(
        _gh: str,
        repository: str,
        tag: str,
        *,
        cwd: Path,
    ) -> dict[str, object]:
        del cwd
        notes = (output_dir / _MOD.RELEASE_NOTES_FILENAME).read_text(encoding="utf-8")
        return {
            "tag_name": tag,
            "draft": True,
            "prerelease": False,
            "html_url": _MOD._release_url(repository, tag),
            "body": notes,
            "assets": [
                {
                    "name": path.name,
                    "browser_download_url": _MOD._release_asset_url(
                        repository,
                        tag,
                        path.name,
                    ),
                    "size": path.stat().st_size,
                }
                for path in uploaded_paths
            ],
        }

    monkeypatch.setattr(_MOD, "_run_command", fake_run_command)
    monkeypatch.setattr(_MOD, "_gh_release_payload", fake_release_payload)
    args = _MOD.parse_args(
        [
            "--promotion-dir",
            str(promotion_dir),
            "--output-dir",
            str(output_dir),
            "--repository",
            _REPOSITORY,
            "--tag",
            _TAG,
            "--gh",
            "/usr/bin/gh",
        ]
    )

    publication = _MOD.publish_release(args)

    assert publication["status"] == _MOD.PUBLICATION_STATUS
    assert (output_dir / _MOD.PUBLICATION_RECORD_FILENAME).is_file()
    assert calls == [
        "GitHub draft release creation",
        "GitHub release asset upload",
        "GitHub draft release asset download",
        "GitHub release publication",
    ]


def test_publish_release_cleans_failed_draft_and_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "repo"
    source_root.mkdir()
    promotion_dir, manifest = _promotion_fixture(tmp_path)
    output_dir = tmp_path / "publication-output"
    calls: list[str] = []
    monkeypatch.setattr(_MOD, "repo_root", lambda: source_root)
    monkeypatch.setattr(
        _MOD._PROMOTION,
        "verify_promotion_directory",
        lambda *_args, **_kwargs: manifest,
    )
    monkeypatch.setattr(
        _MOD._PROMOTION,
        "git_provenance",
        lambda _root: {"commit": _COMMIT},
    )
    monkeypatch.setattr(_MOD, "_remote_tag_commit", lambda *_args, **_kwargs: _COMMIT)
    monkeypatch.setattr(_MOD, "_release_exists", lambda *_args, **_kwargs: False)

    def fake_run_command(
        command: Any,
        *,
        cwd: Path,
        timeout: float,
        label: str,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        del cwd, timeout, check
        calls.append(label)
        if label == "GitHub release asset upload":
            raise _MOD.PublicationError("forced upload failure")
        return subprocess.CompletedProcess(tuple(command), 0, stdout="ok\n", stderr="")

    monkeypatch.setattr(_MOD, "_run_command", fake_run_command)
    args = _MOD.parse_args(
        [
            "--promotion-dir",
            str(promotion_dir),
            "--output-dir",
            str(output_dir),
            "--repository",
            _REPOSITORY,
            "--tag",
            _TAG,
            "--gh",
            "/usr/bin/gh",
        ]
    )

    with pytest.raises(_MOD.PublicationError, match="forced upload failure"):
        _MOD.publish_release(args)

    assert "failed draft release cleanup" in calls
    assert not output_dir.exists()
