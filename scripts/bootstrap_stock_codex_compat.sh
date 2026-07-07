#!/bin/bash
set -euo pipefail

fail() {
  printf 'omnigent_stock_codex_compat_bootstrap_error=%s\n' "$*" >&2
  exit 70
}

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
source_runtime_root="$(cd "$script_dir/.." && pwd -P)"
user_runtime_root="${OMNIGENT_STOCK_CODEX_COMPAT_USER_RUNTIME_ROOT:-$HOME/.local/omnigent/stock-codex-compat/runtime}"
uvx_path="${UVX_PATH:-}"
stage_refresh=1
args=("$@")

for ((index = 0; index < ${#args[@]}; index++)); do
  case "${args[$index]}" in
    --source-runtime-root)
      next=$((index + 1))
      [ "$next" -lt "${#args[@]}" ] || fail "--source-runtime-root requires a value"
      source_runtime_root="${args[$next]}"
      ;;
    --user-runtime-root)
      next=$((index + 1))
      [ "$next" -lt "${#args[@]}" ] || fail "--user-runtime-root requires a value"
      user_runtime_root="${args[$next]}"
      ;;
    --uvx-path)
      next=$((index + 1))
      [ "$next" -lt "${#args[@]}" ] || fail "--uvx-path requires a value"
      uvx_path="${args[$next]}"
      ;;
    --no-stage-refresh)
      stage_refresh=0
      ;;
  esac
done

[ -n "${HOME:-}" ] || fail "HOME is not set"
case "$user_runtime_root" in
  ""|"/"|"$HOME"|"$HOME/")
    fail "refusing unsafe user runtime root: $user_runtime_root"
    ;;
esac

if [ -z "$uvx_path" ]; then
  uvx_path="$(command -v uvx || true)"
fi
[ -x "$uvx_path" ] || fail "uvx missing or not executable: ${uvx_path:-<not found>}"

[ -d "$source_runtime_root" ] || fail "source runtime root missing: $source_runtime_root"
source_runtime_root="$(cd "$source_runtime_root" && pwd -P)"
[ -f "$source_runtime_root/pyproject.toml" ] || fail "source runtime pyproject missing"
[ -f "$source_runtime_root/scripts/bootstrap_stock_codex_compat.py" ] || \
  fail "source bootstrap Python missing"

user_runtime_parent="$(dirname "$user_runtime_root")"
mkdir -p "$user_runtime_parent"
if [ -d "$user_runtime_root" ]; then
  user_runtime_real="$(cd "$user_runtime_root" && pwd -P)"
else
  user_runtime_real=""
fi

if [ "$source_runtime_root" != "$user_runtime_real" ]; then
  if [ "$stage_refresh" = "1" ] || [ ! -d "$user_runtime_root" ]; then
    stage_tmp="$user_runtime_parent/.runtime-staging.$$"
    rm -rf "$stage_tmp"
    mkdir -p "$stage_tmp"
    cleanup_stage_tmp() {
      rm -rf "$stage_tmp"
    }
    trap cleanup_stage_tmp EXIT
    if command -v ditto >/dev/null 2>&1; then
      ditto "$source_runtime_root" "$stage_tmp"
    else
      (cd "$source_runtime_root" && tar cf - .) | (cd "$stage_tmp" && tar xpf -)
    fi
    rm -rf "$user_runtime_root"
    mv "$stage_tmp" "$user_runtime_root"
    trap - EXIT
  fi
fi

exec "$uvx_path" --from "$user_runtime_root" python \
  "$user_runtime_root/scripts/bootstrap_stock_codex_compat.py" \
  --staged-runtime-root "$user_runtime_root" \
  "${args[@]}"
