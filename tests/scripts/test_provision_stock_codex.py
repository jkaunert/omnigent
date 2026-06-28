"""Tests for ``scripts/provision_stock_codex.py``."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "provision_stock_codex.py"


def _load_module() -> Any:
    spec = importlib.util.spec_from_file_location(
        "scripts_provision_stock_codex",
        _SCRIPT_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_MOD = _load_module()


def _write_codex_binary(path: Path, *, version: str = "codex-cli 0.142.2") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""#!/bin/sh
if [ "${{1:-}}" = "--version" ]; then
  cat <<'EOF'
{version}
EOF
  exit 0
fi
printf 'fake codex\\n'
""",
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


def test_provision_stock_codex_copies_source_to_version_cache(tmp_path: Path) -> None:
    source_binary = _write_codex_binary(tmp_path / "source" / "codex")
    cache_root = tmp_path / "cache"

    provisioned = _MOD.provision_stock_codex(
        cache_root=cache_root,
        source_binary=source_binary,
        expected_sha256=None,
        force=False,
        allow_fork_codex=False,
    )

    expected_payload_dir = cache_root / "0.142.2"
    assert provisioned.payload_dir == expected_payload_dir
    assert provisioned.codex_path == expected_payload_dir / "codex"
    assert provisioned.manifest_path == expected_payload_dir / _MOD.MANIFEST_NAME
    assert provisioned.version == "codex-cli 0.142.2"
    assert provisioned.sha256 == _MOD.sha256_file(source_binary)
    assert provisioned.as_dict()["env"] == {
        _MOD.OMNIGENT_STOCK_CODEX_PATH_ENV: str(expected_payload_dir / "codex")
    }


def test_provision_stock_codex_expected_sha_mismatch_fails(tmp_path: Path) -> None:
    source_binary = _write_codex_binary(tmp_path / "source" / "codex")

    with pytest.raises(_MOD.ProvisioningError, match="Source Codex sha256 mismatch"):
        _MOD.provision_stock_codex(
            cache_root=tmp_path / "cache",
            source_binary=source_binary,
            expected_sha256="0" * 64,
            force=False,
            allow_fork_codex=False,
        )


def test_provision_stock_codex_reuses_verified_existing_payload(tmp_path: Path) -> None:
    source_binary = _write_codex_binary(tmp_path / "source" / "codex")
    cache_root = tmp_path / "cache"

    first = _MOD.provision_stock_codex(
        cache_root=cache_root,
        source_binary=source_binary,
        expected_sha256=None,
        force=False,
        allow_fork_codex=False,
    )
    second = _MOD.provision_stock_codex(
        cache_root=cache_root,
        source_binary=source_binary,
        expected_sha256=None,
        force=False,
        allow_fork_codex=False,
    )

    assert second.codex_path == first.codex_path
    assert second.sha256 == first.sha256


def test_provision_stock_codex_existing_mismatch_requires_force(tmp_path: Path) -> None:
    source_binary = _write_codex_binary(tmp_path / "source" / "codex")
    cache_root = tmp_path / "cache"
    provisioned = _MOD.provision_stock_codex(
        cache_root=cache_root,
        source_binary=source_binary,
        expected_sha256=None,
        force=False,
        allow_fork_codex=False,
    )
    _write_codex_binary(provisioned.codex_path, version="codex-cli 0.142.2")
    with provisioned.codex_path.open("a", encoding="utf-8") as handle:
        handle.write("# tampered\n")

    with pytest.raises(_MOD.ProvisioningError, match="Rerun with --force"):
        _MOD.provision_stock_codex(
            cache_root=cache_root,
            source_binary=source_binary,
            expected_sha256=None,
            force=False,
            allow_fork_codex=False,
        )


def test_main_prints_shell_env_for_source_binary(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source_binary = _write_codex_binary(tmp_path / "source" / "codex")
    cache_root = tmp_path / "cache"

    rc = _MOD.main(
        [
            "--source-binary",
            str(source_binary),
            "--cache-root",
            str(cache_root),
            "--print-shell-env",
        ]
    )

    expected_codex_path = cache_root / "0.142.2" / "codex"
    assert rc == 0
    assert capsys.readouterr().out.strip() == (
        f"export {_MOD.OMNIGENT_STOCK_CODEX_PATH_ENV}='{expected_codex_path}'"
    )


def test_resolve_source_codex_rejects_codex_fork_path(tmp_path: Path) -> None:
    source_binary = _write_codex_binary(tmp_path / ".codex-fork" / "bin" / "codex")

    with pytest.raises(_MOD.ProvisioningError, match="Codex-fork binary"):
        _MOD.resolve_source_codex(source_binary, allow_fork_codex=False)

    assert _MOD.resolve_source_codex(source_binary, allow_fork_codex=True) == source_binary
