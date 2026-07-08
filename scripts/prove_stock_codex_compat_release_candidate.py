#!/usr/bin/env python3
"""Run the stock-Codex compatibility package release-candidate gate."""

from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

PROOF_NAME = "stock-codex-compat-pkg-clean-vm-release"
ENV_PKG_PATH = "OMNIGENT_STOCK_CODEX_COMPAT_RELEASE_PKG_PATH"
ENV_CODEX_PATH = "OMNIGENT_STOCK_CODEX_COMPAT_RELEASE_CODEX_PATH"
ENV_TART_NAME = "OMNIGENT_STOCK_CODEX_COMPAT_RELEASE_TART_NAME"
ENV_SSH_TARGET = "OMNIGENT_STOCK_CODEX_COMPAT_RELEASE_SSH_TARGET"
ENV_SSH_USER = "OMNIGENT_STOCK_CODEX_COMPAT_RELEASE_SSH_USER"
ENV_SSH_IDENTITY = "OMNIGENT_STOCK_CODEX_COMPAT_RELEASE_SSH_IDENTITY"
ENV_SSH_PORT = "OMNIGENT_STOCK_CODEX_COMPAT_RELEASE_SSH_PORT"


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


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    command = build_command(args)
    if args.print_command:
        print(" ".join(shlex.quote(part) for part in command))
        return 0
    completed = subprocess.run(command, check=False)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
