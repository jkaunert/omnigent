#!/usr/bin/env python3
"""Publish and verify a promoted stock-Codex compatibility GitHub release."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

PUBLICATION_KIND = "omnigent-stock-codex-compat-github-publication"
PUBLICATION_SCHEMA_VERSION = 2
PUBLICATION_STATUS = "published"
PUBLICATION_RECORD_FILENAME = "publication-record.json"
CHECKSUMS_FILENAME = "SHA256SUMS"
RELEASE_NOTES_FILENAME = "release-notes.md"
TAG_PREFIX = "stock-codex-compat-v"
REPOSITORY_PATTERN = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")


class PublicationError(RuntimeError):
    """The release could not be published without weakening the contract."""


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_promotion_module() -> ModuleType:
    path = Path(__file__).with_name("promote_stock_codex_compat_release.py")
    spec = importlib.util.spec_from_file_location(
        "omnigent_stock_codex_compat_promotion_for_publication",
        path,
    )
    if spec is None or spec.loader is None:
        raise PublicationError(f"could not load promotion verifier: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_PROMOTION = _load_promotion_module()


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
        raise PublicationError(f"{label} is not readable JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise PublicationError(f"{label} must be a JSON object: {path}")
    return payload


def _run_command(
    command: Sequence[str],
    *,
    cwd: Path,
    timeout: float,
    label: str,
    check: bool = True,
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
        raise PublicationError(f"{label} could not execute: {command!r}") from exc
    if check and completed.returncode != 0:
        raise PublicationError(
            f"{label} failed with exit {completed.returncode}.\n"
            f"command={shlex.join(command)}\n"
            f"stdout={completed.stdout}\n"
            f"stderr={completed.stderr}"
        )
    return completed


def _git_capture(source_root: Path, *arguments: str) -> str:
    completed = _run_command(
        ("git", "-C", str(source_root), *arguments),
        cwd=source_root,
        timeout=60,
        label="Git publication provenance",
    )
    return completed.stdout.strip()


def _validate_repository(value: str) -> str:
    if not REPOSITORY_PATTERN.fullmatch(value):
        raise PublicationError(f"GitHub repository must be OWNER/REPO: {value!r}")
    return value


def _manifest_mapping(
    manifest: Mapping[str, object],
    key: str,
) -> Mapping[str, object]:
    value = manifest.get(key)
    if not isinstance(value, Mapping):
        raise PublicationError(f"promotion manifest omitted {key}")
    return value


def _manifest_string(mapping: Mapping[str, object], key: str, *, label: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value:
        raise PublicationError(f"{label} omitted {key}")
    return value


def _validate_tag(tag: str, *, version: str) -> str:
    expected = f"{TAG_PREFIX}{version}"
    if tag != expected:
        raise PublicationError(f"release tag must be {expected!r}, got {tag!r}")
    return tag


def _remote_tag_commit(
    source_root: Path,
    *,
    remote: str,
    tag: str,
) -> str:
    local_commit = _git_capture(source_root, "rev-list", "-n", "1", tag)
    output = _git_capture(
        source_root,
        "ls-remote",
        "--tags",
        remote,
        f"refs/tags/{tag}",
        f"refs/tags/{tag}^{{}}",
    )
    direct: str | None = None
    peeled: str | None = None
    for line in output.splitlines():
        fields = line.split()
        if len(fields) != 2:
            continue
        if fields[1] == f"refs/tags/{tag}":
            direct = fields[0]
        elif fields[1] == f"refs/tags/{tag}^{{}}":
            peeled = fields[0]
    remote_commit = peeled or direct
    if not remote_commit:
        raise PublicationError(f"release tag is not present on remote {remote}: {tag}")
    if local_commit != remote_commit:
        raise PublicationError(
            f"local and remote release tag commits differ: {local_commit} != {remote_commit}"
        )
    return remote_commit


def _artifact_record(path: Path, *, url: str) -> dict[str, object]:
    return {
        "name": path.name,
        "url": url,
        "sha256": sha256_file(path),
        "size": path.stat().st_size,
    }


def _release_asset_url(repository: str, tag: str, filename: str) -> str:
    return f"https://github.com/{repository}/releases/download/{tag}/{filename}"


def _release_url(repository: str, tag: str) -> str:
    return f"https://github.com/{repository}/releases/tag/{tag}"


def _write_checksums(paths: Sequence[Path], destination: Path) -> None:
    lines = [f"{sha256_file(path)}  {path.name}" for path in sorted(paths)]
    destination.write_text("\n".join(lines) + "\n", encoding="utf-8")
    destination.chmod(0o644)


def _write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    path.chmod(0o644)


def _release_exists(gh: str, repository: str, tag: str, *, cwd: Path) -> bool:
    completed = _run_command(
        (gh, "api", f"repos/{repository}/releases/tags/{tag}"),
        cwd=cwd,
        timeout=60,
        label="GitHub release existence check",
        check=False,
    )
    if completed.returncode == 0:
        return True
    combined = f"{completed.stdout}\n{completed.stderr}"
    if "HTTP 404" in combined or '"status":"404"' in combined:
        return False
    raise PublicationError(
        "GitHub release existence check failed without a 404.\n"
        f"stdout={completed.stdout}\nstderr={completed.stderr}"
    )


def _require_immutable_releases_enabled(
    gh: str,
    repository: str,
    *,
    cwd: Path,
) -> None:
    completed = _run_command(
        (gh, "api", f"repos/{repository}/immutable-releases"),
        cwd=cwd,
        timeout=60,
        label="GitHub immutable releases setting inspection",
    )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise PublicationError("GitHub immutable releases setting returned invalid JSON") from exc
    if not isinstance(payload, Mapping) or payload.get("enabled") is not True:
        raise PublicationError("GitHub immutable releases must be enabled before publication")


def _gh_release_payload(
    gh: str,
    repository: str,
    tag: str,
    *,
    cwd: Path,
) -> dict[str, object]:
    completed = _run_command(
        (
            gh,
            "release",
            "view",
            tag,
            "--repo",
            repository,
            "--json",
            "tagName,isDraft,isImmutable,isPrerelease,url,body,assets",
        ),
        cwd=cwd,
        timeout=60,
        label="GitHub release inspection",
    )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise PublicationError("GitHub release inspection returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise PublicationError("GitHub release inspection did not return an object")
    assets = payload.get("assets")
    normalized_assets: list[dict[str, object]] = []
    if isinstance(assets, list):
        for asset in assets:
            if isinstance(asset, Mapping):
                normalized_assets.append(
                    {
                        "name": asset.get("name"),
                        "browser_download_url": asset.get("url"),
                        "size": asset.get("size"),
                    }
                )
    return {
        "tag_name": payload.get("tagName"),
        "draft": payload.get("isDraft"),
        "immutable": payload.get("isImmutable"),
        "prerelease": payload.get("isPrerelease"),
        "html_url": payload.get("url"),
        "body": payload.get("body"),
        "assets": normalized_assets,
    }


def _expected_assets(
    publication: Mapping[str, object],
) -> dict[str, tuple[str, int]]:
    artifacts = publication.get("artifacts")
    if not isinstance(artifacts, Mapping):
        raise PublicationError("publication record omitted artifacts")
    expected: dict[str, tuple[str, int]] = {}
    for value in artifacts.values():
        if not isinstance(value, Mapping):
            raise PublicationError("publication artifact record is invalid")
        name = value.get("name")
        digest = value.get("sha256")
        size = value.get("size")
        if (
            not isinstance(name, str)
            or Path(name).name != name
            or not isinstance(digest, str)
            or len(digest) != 64
            or not isinstance(size, int)
            or size < 1
        ):
            raise PublicationError("publication artifact record is malformed")
        try:
            int(digest, 16)
        except ValueError as exc:
            raise PublicationError("publication artifact SHA-256 is malformed") from exc
        if name in expected:
            raise PublicationError(f"duplicate publication artifact filename: {name}")
        expected[name] = (digest, size)
    return expected


def _verify_checksums_file(
    path: Path,
    *,
    publication: Mapping[str, object],
) -> None:
    expected = _expected_assets(publication)
    checksums_record = expected.pop(CHECKSUMS_FILENAME, None)
    if checksums_record is None:
        raise PublicationError("publication record omitted SHA256SUMS")
    observed: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise PublicationError(f"could not read downloaded SHA256SUMS: {path}") from exc
    for line in lines:
        fields = line.split("  ", 1)
        if len(fields) != 2 or not fields[0] or Path(fields[1]).name != fields[1]:
            raise PublicationError("SHA256SUMS contains a malformed line")
        observed[fields[1]] = fields[0]
    expected_digests = {name: digest for name, (digest, _size) in expected.items()}
    if observed != expected_digests:
        raise PublicationError("SHA256SUMS does not match publication artifacts")


def _verify_release_payload(
    payload: Mapping[str, object],
    *,
    repository: str,
    tag: str,
    publication: Mapping[str, object],
    publication_record_sha256: str,
    expect_draft: bool,
) -> dict[str, str]:
    if payload.get("tag_name") != tag:
        raise PublicationError("GitHub release tag does not match publication record")
    if payload.get("draft") is not expect_draft:
        raise PublicationError(f"GitHub release draft state is not {expect_draft}")
    expected_immutable = not expect_draft
    if payload.get("immutable") is not expected_immutable:
        raise PublicationError(f"GitHub release immutable state is not {expected_immutable}")
    if payload.get("prerelease") is not False:
        raise PublicationError("stable compatibility release cannot be a prerelease")
    release_url = payload.get("html_url")
    expected_release_url = _release_url(repository, tag)
    draft_url_prefix = f"https://github.com/{repository}/releases/tag/untagged-"
    asset_release_ref = tag
    if expect_draft:
        if release_url != expected_release_url and (
            not isinstance(release_url, str) or not release_url.startswith(draft_url_prefix)
        ):
            raise PublicationError("GitHub draft release URL is invalid")
        if isinstance(release_url, str) and release_url.startswith(draft_url_prefix):
            asset_release_ref = release_url.rsplit("/", 1)[-1]
    elif release_url != expected_release_url:
        raise PublicationError("GitHub release URL does not match publication record")
    body = payload.get("body")
    if not isinstance(body, str) or publication_record_sha256 not in body:
        raise PublicationError("GitHub release notes omit the publication-record digest")
    expected = _expected_assets(publication)
    expected[PUBLICATION_RECORD_FILENAME] = (
        publication_record_sha256,
        -1,
    )
    assets = payload.get("assets")
    if not isinstance(assets, list):
        raise PublicationError("GitHub release assets are missing")
    observed: dict[str, str] = {}
    observed_sizes: dict[str, int] = {}
    for asset in assets:
        if not isinstance(asset, Mapping):
            raise PublicationError("GitHub release asset record is invalid")
        name = asset.get("name")
        url = asset.get("browser_download_url")
        size = asset.get("size")
        if isinstance(name, str) and isinstance(url, str) and isinstance(size, int):
            observed[name] = url
            observed_sizes[name] = size
    if set(observed) != set(expected):
        raise PublicationError(
            f"GitHub release assets differ: {sorted(observed)} != {sorted(expected)}"
        )
    for name, (_digest, expected_size) in expected.items():
        expected_url = _release_asset_url(repository, asset_release_ref, name)
        if observed[name] != expected_url:
            raise PublicationError(f"GitHub release asset URL is wrong: {name}")
        if expected_size >= 0 and observed_sizes[name] != expected_size:
            raise PublicationError(f"GitHub release asset size is wrong: {name}")
    return observed


def _verify_downloaded_assets(
    directory: Path,
    *,
    publication: Mapping[str, object],
    publication_record_sha256: str,
) -> None:
    expected = _expected_assets(publication)
    expected[PUBLICATION_RECORD_FILENAME] = (publication_record_sha256, -1)
    observed_names = {path.name for path in directory.iterdir() if path.is_file()}
    if observed_names != set(expected):
        raise PublicationError("downloaded release asset set is incomplete")
    for name, (expected_sha256, expected_size) in expected.items():
        path = directory / name
        if path.is_symlink() or not path.is_file():
            raise PublicationError(f"downloaded release asset is not a regular file: {name}")
        if sha256_file(path) != expected_sha256:
            raise PublicationError(f"downloaded release asset SHA-256 mismatch: {name}")
        if expected_size >= 0 and path.stat().st_size != expected_size:
            raise PublicationError(f"downloaded release asset size mismatch: {name}")
    _verify_checksums_file(
        directory / CHECKSUMS_FILENAME,
        publication=publication,
    )


def _download_public_asset(url: str, destination: Path) -> None:
    request = Request(url, headers={"User-Agent": "omnigent-release-verifier/1"})
    try:
        with urlopen(request, timeout=180) as response, destination.open("wb") as handle:
            if getattr(response, "status", 200) != 200:
                raise PublicationError(f"public asset returned HTTP {response.status}: {url}")
            shutil.copyfileobj(response, handle)
    except (HTTPError, URLError, OSError) as exc:
        raise PublicationError(f"could not download public release asset: {url}") from exc


def _public_release_payload(repository: str, tag: str) -> dict[str, object]:
    url = f"https://api.github.com/repos/{repository}/releases/tags/{tag}"
    request = Request(url, headers={"User-Agent": "omnigent-release-verifier/1"})
    try:
        with urlopen(request, timeout=60) as response:
            payload = json.load(response)
    except (HTTPError, URLError, OSError, json.JSONDecodeError) as exc:
        raise PublicationError(f"could not inspect public GitHub release: {url}") from exc
    if not isinstance(payload, dict):
        raise PublicationError("public GitHub release did not return an object")
    return payload


def _verify_public_assets(
    *,
    repository: str,
    tag: str,
    publication: Mapping[str, object],
    publication_record_path: Path,
) -> None:
    publication_record_sha256 = sha256_file(publication_record_path)
    payload = _public_release_payload(repository, tag)
    urls = _verify_release_payload(
        payload,
        repository=repository,
        tag=tag,
        publication=publication,
        publication_record_sha256=publication_record_sha256,
        expect_draft=False,
    )
    expected = _expected_assets(publication)
    expected[PUBLICATION_RECORD_FILENAME] = (publication_record_sha256, -1)
    with tempfile.TemporaryDirectory(prefix="omnigent-public-release-download-") as directory:
        download_dir = Path(directory)
        for name, (digest, size) in expected.items():
            destination = download_dir / name
            _download_public_asset(urls[name], destination)
            if sha256_file(destination) != digest:
                raise PublicationError(f"public release asset SHA-256 mismatch: {name}")
            if size >= 0 and destination.stat().st_size != size:
                raise PublicationError(f"public release asset size mismatch: {name}")
        _verify_checksums_file(
            download_dir / CHECKSUMS_FILENAME,
            publication=publication,
        )
        manifest = _PROMOTION.verify_promotion_directory(
            download_dir,
            checker_script=repo_root()
            / "scripts"
            / "check_stock_codex_compat_release_evidence.py",
            python_executable=sys.executable,
        )
        source = _manifest_mapping(manifest, "source")
        package = _manifest_mapping(manifest, "package")
        if source.get("commit") != publication.get("sourceCommit"):
            raise PublicationError(
                "public promotion manifest source commit differs from publication record"
            )
        if package.get("packageVersion") != publication.get("packageVersion"):
            raise PublicationError(
                "public promotion manifest package version differs from publication record"
            )
        if package.get("packageIdentifier") != publication.get("packageIdentifier"):
            raise PublicationError(
                "public promotion manifest identifier differs from publication record"
            )


def _verify_release_attestations(
    gh: str,
    repository: str,
    tag: str,
    package_path: Path,
    *,
    cwd: Path,
) -> None:
    release_completed: subprocess.CompletedProcess[str] | None = None
    asset_completed: subprocess.CompletedProcess[str] | None = None
    for attempt in range(12):
        release_completed = _run_command(
            (gh, "release", "verify", tag, "--repo", repository, "--format", "json"),
            cwd=cwd,
            timeout=120,
            label="GitHub release attestation verification",
            check=False,
        )
        if release_completed.returncode == 0:
            asset_completed = _run_command(
                (
                    gh,
                    "release",
                    "verify-asset",
                    tag,
                    str(package_path),
                    "--repo",
                    repository,
                    "--format",
                    "json",
                ),
                cwd=cwd,
                timeout=120,
                label="GitHub package attestation verification",
                check=False,
            )
            if asset_completed.returncode == 0:
                return
        if attempt < 11:
            time.sleep(5)
    raise PublicationError(
        "GitHub release attestations did not verify.\n"
        f"release_stdout={release_completed.stdout if release_completed else ''}\n"
        f"release_stderr={release_completed.stderr if release_completed else ''}\n"
        f"asset_stdout={asset_completed.stdout if asset_completed else ''}\n"
        f"asset_stderr={asset_completed.stderr if asset_completed else ''}"
    )


def _validate_publication_record(
    publication: Mapping[str, object],
) -> tuple[str, str, str]:
    if publication.get("kind") != PUBLICATION_KIND:
        raise PublicationError("unexpected publication record kind")
    if publication.get("schemaVersion") != PUBLICATION_SCHEMA_VERSION:
        raise PublicationError("unexpected publication record schemaVersion")
    if publication.get("status") != PUBLICATION_STATUS:
        raise PublicationError("publication record status is not published")
    if publication.get("releaseImmutable") is not True:
        raise PublicationError("publication record does not require an immutable release")
    repository = publication.get("repository")
    tag = publication.get("tag")
    version = publication.get("packageVersion")
    if not isinstance(repository, str):
        raise PublicationError("publication record omitted repository")
    if not isinstance(tag, str):
        raise PublicationError("publication record omitted tag")
    if not isinstance(version, str):
        raise PublicationError("publication record omitted packageVersion")
    _validate_repository(repository)
    _validate_tag(tag, version=version)
    if not _PROMOTION.STABLE_RELEASE_VERSION_PATTERN.fullmatch(version):
        raise PublicationError("publication packageVersion is not stable MAJOR.MINOR.PATCH")
    source_commit = publication.get("sourceCommit")
    if not isinstance(source_commit, str) or not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise PublicationError("publication sourceCommit is invalid")
    if publication.get("releaseUrl") != _release_url(repository, tag):
        raise PublicationError("publication releaseUrl is invalid")
    if publication.get("publicationRecordUrl") != _release_asset_url(
        repository,
        tag,
        PUBLICATION_RECORD_FILENAME,
    ):
        raise PublicationError("publication publicationRecordUrl is invalid")
    artifacts = publication.get("artifacts")
    if not isinstance(artifacts, Mapping) or set(artifacts) != {
        "package",
        "releaseEvidence",
        "promotionManifest",
        "checksums",
    }:
        raise PublicationError("publication artifact roles are invalid")
    expected_assets = _expected_assets(publication)
    for value in artifacts.values():
        assert isinstance(value, Mapping)
        name = value.get("name")
        if not isinstance(name, str) or value.get("url") != _release_asset_url(
            repository,
            tag,
            name,
        ):
            raise PublicationError("publication artifact URL is invalid")
    promotion_manifest = artifacts.get("promotionManifest")
    assert isinstance(promotion_manifest, Mapping)
    if publication.get("promotionManifestSha256") != promotion_manifest.get("sha256"):
        raise PublicationError("publication promotionManifestSha256 is inconsistent")
    if set(expected_assets) != {
        _PROMOTION.PACKAGE_FILENAME,
        _PROMOTION.EVIDENCE_FILENAME,
        _PROMOTION.MANIFEST_FILENAME,
        CHECKSUMS_FILENAME,
    }:
        raise PublicationError("publication artifact filenames are invalid")
    return repository, tag, version


def verify_publication(publication_record_path: Path) -> dict[str, object]:
    publication_record_path = publication_record_path.expanduser().resolve()
    if publication_record_path.is_symlink() or not publication_record_path.is_file():
        raise PublicationError(
            f"publication record must be a regular file: {publication_record_path}"
        )
    publication = _load_json(publication_record_path, label="publication record")
    repository, tag, _version = _validate_publication_record(publication)
    _verify_public_assets(
        repository=repository,
        tag=tag,
        publication=publication,
        publication_record_path=publication_record_path,
    )
    return publication


def publish_release(args: argparse.Namespace) -> dict[str, object]:
    source_root = repo_root().resolve()
    promotion_dir = args.promotion_dir.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    if output_dir.exists():
        raise PublicationError(f"immutable publication output already exists: {output_dir}")
    try:
        output_dir.relative_to(source_root)
    except ValueError:
        pass
    else:
        raise PublicationError("publication output directory must be outside the checkout")
    repository = _validate_repository(args.repository)
    gh = args.gh or shutil.which("gh")
    if not gh:
        raise PublicationError("GitHub CLI is required")
    _require_immutable_releases_enabled(gh, repository, cwd=source_root)
    checker_script = args.evidence_checker_script.expanduser().resolve()
    manifest = _PROMOTION.verify_promotion_directory(
        promotion_dir,
        checker_script=checker_script,
        python_executable=args.python_executable,
    )
    source = _manifest_mapping(manifest, "source")
    package = _manifest_mapping(manifest, "package")
    release_evidence = _manifest_mapping(manifest, "releaseEvidence")
    source_commit = _manifest_string(source, "commit", label="promotion source")
    package_version = _manifest_string(package, "packageVersion", label="package summary")
    package_sha256 = _manifest_string(package, "packageSha256", label="package summary")
    stock_codex_version = _manifest_string(
        release_evidence,
        "stockCodexVersion",
        label="release evidence",
    )
    _validate_tag(args.tag, version=package_version)
    provenance = _PROMOTION.git_provenance(source_root)
    if provenance.get("commit") != source_commit:
        raise PublicationError(
            "publication checkout HEAD does not match the promoted source commit"
        )
    remote_tag_commit = _remote_tag_commit(
        source_root,
        remote=args.remote,
        tag=args.tag,
    )
    if remote_tag_commit != source_commit:
        raise PublicationError("release tag does not point to the promoted source commit")
    if _release_exists(gh, repository, args.tag, cwd=source_root):
        raise PublicationError(f"GitHub release already exists: {repository} {args.tag}")

    artifacts = _manifest_mapping(manifest, "artifacts")
    package_artifact = _manifest_mapping(artifacts, "package")
    evidence_artifact = _manifest_mapping(artifacts, "releaseEvidence")
    package_path = promotion_dir / _manifest_string(
        package_artifact,
        "file",
        label="package artifact",
    )
    evidence_path = promotion_dir / _manifest_string(
        evidence_artifact,
        "file",
        label="release evidence artifact",
    )
    manifest_path = promotion_dir / _PROMOTION.MANIFEST_FILENAME
    for path in (package_path, evidence_path, manifest_path):
        if path.is_symlink() or not path.is_file():
            raise PublicationError(f"publication artifact is not a regular file: {path}")
    if sha256_file(package_path) != package_sha256:
        raise PublicationError("package summary SHA-256 changed before publication")

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir()
    release_create_attempted = False
    published = False
    try:
        checksums_path = output_dir / CHECKSUMS_FILENAME
        _write_checksums((package_path, evidence_path, manifest_path), checksums_path)
        base_url = f"https://github.com/{repository}/releases/download/{args.tag}"
        publication_artifacts = {
            "package": _artifact_record(
                package_path,
                url=f"{base_url}/{package_path.name}",
            ),
            "releaseEvidence": _artifact_record(
                evidence_path,
                url=f"{base_url}/{evidence_path.name}",
            ),
            "promotionManifest": _artifact_record(
                manifest_path,
                url=f"{base_url}/{manifest_path.name}",
            ),
            "checksums": _artifact_record(
                checksums_path,
                url=f"{base_url}/{checksums_path.name}",
            ),
        }
        publication = {
            "kind": PUBLICATION_KIND,
            "schemaVersion": PUBLICATION_SCHEMA_VERSION,
            "status": PUBLICATION_STATUS,
            "releaseImmutable": True,
            "createdAt": datetime.now(UTC).isoformat(),
            "repository": repository,
            "tag": args.tag,
            "releaseUrl": _release_url(repository, args.tag),
            "publicationRecordUrl": _release_asset_url(
                repository,
                args.tag,
                PUBLICATION_RECORD_FILENAME,
            ),
            "sourceCommit": source_commit,
            "packageVersion": package_version,
            "packageIdentifier": package.get("packageIdentifier"),
            "stockCodexVersion": stock_codex_version,
            "promotionManifestSha256": sha256_file(manifest_path),
            "artifacts": publication_artifacts,
        }
        publication_record_path = output_dir / PUBLICATION_RECORD_FILENAME
        _write_json(publication_record_path, publication)
        publication_record_sha256 = sha256_file(publication_record_path)
        notes_path = output_dir / RELEASE_NOTES_FILENAME
        notes_path.write_text(
            "\n".join(
                [
                    f"# Omnigent Stock Codex Compatibility {package_version}",
                    "",
                    "Commit-bound, Developer ID signed and notarized compatibility runtime.",
                    "",
                    f"- Source commit: `{source_commit}`",
                    "- GitHub immutable release: `required`",
                    f"- Package SHA-256: `{package_sha256}`",
                    (f"- Promotion manifest SHA-256: `{sha256_file(manifest_path)}`"),
                    (f"- Publication record SHA-256: `{publication_record_sha256}`"),
                    f"- Official stock Codex validated: `{stock_codex_version}`",
                    "",
                    "`SHA256SUMS` covers the package, release evidence, and promotion manifest.",
                    "The package itself is signed, notarized, stapled, and Gatekeeper accepted.",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        notes_path.chmod(0o644)

        release_create_attempted = True
        _run_command(
            (
                gh,
                "release",
                "create",
                args.tag,
                "--repo",
                repository,
                "--draft",
                "--verify-tag",
                "--title",
                args.title or f"Omnigent Stock Codex Compatibility {package_version}",
                "--notes-file",
                str(notes_path),
            ),
            cwd=source_root,
            timeout=120,
            label="GitHub draft release creation",
        )
        upload_paths = (
            package_path,
            evidence_path,
            manifest_path,
            checksums_path,
            publication_record_path,
        )
        _run_command(
            (
                gh,
                "release",
                "upload",
                args.tag,
                *(str(path) for path in upload_paths),
                "--repo",
                repository,
            ),
            cwd=source_root,
            timeout=600,
            label="GitHub release asset upload",
        )
        draft_payload = _gh_release_payload(gh, repository, args.tag, cwd=source_root)
        _verify_release_payload(
            draft_payload,
            repository=repository,
            tag=args.tag,
            publication=publication,
            publication_record_sha256=publication_record_sha256,
            expect_draft=True,
        )
        with tempfile.TemporaryDirectory(prefix="omnigent-draft-release-download-") as directory:
            _run_command(
                (
                    gh,
                    "release",
                    "download",
                    args.tag,
                    "--repo",
                    repository,
                    "--dir",
                    directory,
                ),
                cwd=source_root,
                timeout=600,
                label="GitHub draft release asset download",
            )
            _verify_downloaded_assets(
                Path(directory),
                publication=publication,
                publication_record_sha256=publication_record_sha256,
            )
        _run_command(
            (
                gh,
                "release",
                "edit",
                args.tag,
                "--repo",
                repository,
                "--draft=false",
                "--prerelease=false",
                "--latest",
            ),
            cwd=source_root,
            timeout=120,
            label="GitHub release publication",
        )
        published = True
        _verify_public_assets(
            repository=repository,
            tag=args.tag,
            publication=publication,
            publication_record_path=publication_record_path,
        )
        _verify_release_attestations(
            gh,
            repository,
            args.tag,
            package_path,
            cwd=source_root,
        )
        return publication
    except BaseException:
        if release_create_attempted and not published:
            _run_command(
                (gh, "release", "delete", args.tag, "--repo", repository, "--yes"),
                cwd=source_root,
                timeout=120,
                label="failed draft release cleanup",
                check=False,
            )
        if not published:
            shutil.rmtree(output_dir, ignore_errors=True)
        raise


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    root = repo_root()
    parser = argparse.ArgumentParser(
        description=(
            "Publish a promoted compatibility package as a verified public GitHub release."
        )
    )
    parser.add_argument("--promotion-dir", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--repository")
    parser.add_argument("--tag")
    parser.add_argument("--remote", default="origin")
    parser.add_argument("--title")
    parser.add_argument("--gh", default=shutil.which("gh"))
    parser.add_argument("--verify-only", type=Path)
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
            if any(
                value is not None
                for value in (
                    args.promotion_dir,
                    args.output_dir,
                    args.repository,
                    args.tag,
                )
            ):
                raise PublicationError(
                    "--verify-only cannot be combined with publication arguments"
                )
            publication = verify_publication(args.verify_only)
            record_path = args.verify_only.expanduser().resolve()
        else:
            missing = [
                option
                for option, value in (
                    ("--promotion-dir", args.promotion_dir),
                    ("--output-dir", args.output_dir),
                    ("--repository", args.repository),
                    ("--tag", args.tag),
                )
                if value is None
            ]
            if missing:
                raise PublicationError(f"missing publication arguments: {', '.join(missing)}")
            publication = publish_release(args)
            record_path = args.output_dir.expanduser().resolve() / PUBLICATION_RECORD_FILENAME
    except PublicationError as exc:
        print(f"release_publication_error={exc}", file=sys.stderr)
        return 1
    print("release_publication_status=published")
    print(f"release_publication_repository={publication['repository']}")
    print(f"release_publication_tag={publication['tag']}")
    print(f"release_publication_url={publication['releaseUrl']}")
    print(f"release_publication_record={record_path}")
    print(f"release_publication_record_sha256={sha256_file(record_path)}")
    artifacts = publication.get("artifacts")
    if isinstance(artifacts, Mapping):
        package = artifacts.get("package")
        if isinstance(package, Mapping):
            print(f"release_publication_package_url={package.get('url')}")
            print(f"release_publication_package_sha256={package.get('sha256')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
