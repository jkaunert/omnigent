"""Tests for ``scripts/provision_xcode27_axe.py``."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "provision_xcode27_axe.py"


def _load_module() -> Any:
    spec = importlib.util.spec_from_file_location(
        "scripts_provision_xcode27_axe",
        _SCRIPT_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_MOD = _load_module()


def _write_payload(
    payload_dir: Path,
    *,
    include_shared_marker: bool = True,
    include_legacy_marker: bool = True,
) -> Path:
    payload_dir.mkdir(parents=True)
    axe = payload_dir / "axe"
    axe.write_text("#!/bin/sh\n")
    axe.chmod(0o755)

    framework_binary = (
        payload_dir / "Frameworks" / "FBControlCore.framework" / "Versions" / "A" / "FBControlCore"
    )
    framework_binary.parent.mkdir(parents=True)
    markers = [b"FBControlCore"]
    if include_shared_marker:
        markers.append(_MOD.SHARED_SIMULATORKIT_MARKER)
    if include_legacy_marker:
        markers.append(_MOD.LEGACY_SIMULATORKIT_MARKER)
    framework_binary.write_bytes(b"\0".join(markers))

    resource_bundle = payload_dir / "AXe_AXe.bundle"
    resource_bundle.mkdir()
    (resource_bundle / "Info.plist").write_text("<plist/>")
    return axe


def test_verify_payload_accepts_xcode27_compatible_runtime_payload(tmp_path: Path) -> None:
    payload_dir = tmp_path / "payload"
    _write_payload(payload_dir)

    provisioned = _MOD.verify_payload(payload_dir, ref="refs/heads/fix/xcode27")

    assert provisioned.axe_path == payload_dir / "axe"
    assert provisioned.payload_dir == payload_dir
    assert provisioned.fbcontrolcore_binary.name == "FBControlCore"
    assert provisioned.ref == "refs/heads/fix/xcode27"


def test_verify_payload_rejects_unpatched_fbcontrolcore(tmp_path: Path) -> None:
    payload_dir = tmp_path / "payload"
    _write_payload(payload_dir, include_shared_marker=False)

    with pytest.raises(_MOD.ProvisioningError, match="SharedFrameworks"):
        _MOD.verify_payload(payload_dir, ref="abc123")


def test_copy_payload_from_binary_installs_runtime_payload(tmp_path: Path) -> None:
    source_binary = _write_payload(tmp_path / "source-build")
    destination_payload_dir = tmp_path / "cache" / "payloads" / "abc123"

    _MOD.copy_payload_from_binary(source_binary, destination_payload_dir)

    provisioned = _MOD.verify_payload(destination_payload_dir, ref="abc123")
    assert provisioned.axe_path == destination_payload_dir / "axe"
    assert (destination_payload_dir / "Frameworks").is_dir()
    assert (destination_payload_dir / "AXe_AXe.bundle").is_dir()


def test_provision_axe_copies_source_binary_to_ref_cache(tmp_path: Path) -> None:
    source_binary = _write_payload(tmp_path / "source-build")
    cache_root = tmp_path / "cache"

    provisioned = _MOD.provision_axe(
        cache_root=cache_root,
        ref="refs/heads/fix/xcode27",
        repo_url="https://example.invalid/AXe.git",
        source_binary=source_binary,
        force=False,
        no_build=True,
        codesign_identity=None,
    )

    expected_payload_dir = cache_root / "payloads" / _MOD.ref_slug("refs/heads/fix/xcode27")
    assert provisioned.payload_dir == expected_payload_dir
    assert provisioned.axe_path == expected_payload_dir / "axe"


def test_parse_args_defaults_to_pinned_ref_and_ad_hoc_signing() -> None:
    args = _MOD.parse_args([])

    assert args.repo_url == "https://github.com/cameroncooke/AXe.git"
    assert args.ref == "51cfaf7552512224c5e9e6a01e059d3986d544bc"
    assert args.codesign_identity == "-"


def test_main_prints_shell_export_for_source_binary(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source_binary = _write_payload(tmp_path / "source-build")
    cache_root = tmp_path / "cache"
    ref = "refs/heads/fix/xcode27"

    rc = _MOD.main(
        [
            "--source-binary",
            str(source_binary),
            "--cache-root",
            str(cache_root),
            "--ref",
            ref,
            "--no-build",
            "--print-shell-env",
        ]
    )

    expected_axe_path = cache_root / "payloads" / _MOD.ref_slug(ref) / "axe"
    assert rc == 0
    assert capsys.readouterr().out.strip() == (
        f"export {_MOD.OMNIGENT_AXE_ENV_VAR}='{expected_axe_path}'"
    )


def test_main_no_build_fails_without_cache_or_source_binary(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = _MOD.main(
        [
            "--cache-root",
            str(tmp_path / "cache"),
            "--ref",
            "abc123",
            "--no-build",
            "--print-path",
        ]
    )

    assert rc == 1
    assert "rerun with --source-binary or allow build" in capsys.readouterr().err
