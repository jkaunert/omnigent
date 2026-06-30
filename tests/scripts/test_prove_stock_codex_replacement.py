"""Tests for ``scripts/prove_stock_codex_replacement.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "prove_stock_codex_replacement.py"


def _load_module() -> Any:
    spec = importlib.util.spec_from_file_location(
        "scripts_prove_stock_codex_replacement",
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


def _write_auth(codex_home: Path, payload: object) -> Path:
    codex_home.mkdir(parents=True, exist_ok=True)
    auth_path = codex_home / "auth.json"
    auth_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    return auth_path


def test_clean_auth_onboarding_proof_classifies_clean_and_synthetic_auth(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_home = tmp_path / "real-home"
    real_codex_home = tmp_path / "real-codex-home"
    real_auth_path = _write_auth(
        real_codex_home,
        {"auth_mode": "api", "OPENAI_API_KEY": "sk-real-proof-fixture"},
    )
    stock_codex = _write_codex_binary(tmp_path / "bin" / "codex")
    monkeypatch.setenv("HOME", str(real_home))
    monkeypatch.setenv("CODEX_HOME", str(real_codex_home))

    proof = _MOD.run_clean_auth_onboarding_proof(stock_codex)

    assert proof.stock_codex_path == stock_codex.resolve()
    assert proof.stock_codex_version == "codex-cli 0.142.2"
    assert proof.real_auth_path == real_auth_path
    assert proof.real_auth_source == "explicit-CODEX_HOME"
    assert proof.real_auth_available is True
    assert proof.clean_unavailable_reason == "needs-auth"
    assert proof.synthetic_available_reason is None


def test_clean_auth_onboarding_proof_ignores_inherited_codex_fork_home(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_home = tmp_path / "real-home"
    stock_auth_path = _write_auth(
        real_home / ".codex",
        {"auth_mode": "api", "OPENAI_API_KEY": "sk-stock-proof-fixture"},
    )
    fork_auth_path = _write_auth(
        real_home / ".codex-fork",
        {"auth_mode": "api", "OPENAI_API_KEY": "sk-fork-proof-fixture"},
    )
    stock_codex = _write_codex_binary(tmp_path / "bin" / "codex")
    monkeypatch.setenv("HOME", str(real_home))
    monkeypatch.setenv("CODEX_HOME", str(fork_auth_path.parent))

    proof = _MOD.run_clean_auth_onboarding_proof(stock_codex)

    assert proof.real_auth_path == stock_auth_path
    assert proof.real_auth_path != fork_auth_path
    assert proof.real_auth_source == "stock-default-home"
    assert proof.real_auth_available is True


def test_clean_auth_onboarding_proof_requires_real_auth(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stock_codex = _write_codex_binary(tmp_path / "bin" / "codex")
    real_home = tmp_path / "real-home"
    real_codex_home = tmp_path / "real-codex-home"
    real_codex_home.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(real_home))
    monkeypatch.setenv("CODEX_HOME", str(real_codex_home))

    with pytest.raises(SystemExit) as excinfo:
        _MOD.run_clean_auth_onboarding_proof(stock_codex)

    assert "Current real Codex auth source is not available" in str(excinfo.value)
