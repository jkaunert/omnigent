# Codex Fork Carry Scoreboard

This document maps the current Codex-fork carry inventory to the private
Omnigent stock-Codex replacement track. It is a cutover-readiness scoreboard,
not an instruction to delete or rewrite the Codex fork.

## Comparator Baseline

- Omnigent worktree:
  `/Users/joshuakaunert/Developer/HarnessEngineering/omnigent-upstream-audit`
  on `spike/codex-router-selection-adapter-upstream-audit`.
- Codex-fork comparator:
  `/Users/joshuakaunert/Developer/codex-formal-carry-refresh-20260609`
  on `work/formal-carry-refresh-main-20260609`.
- Baseline command:
  `git rev-list --left-right --count upstream/main...HEAD`.
- Baseline result on 2026-06-27: `657 22`.
- The Codex-fork comparator was read-only while preparing this scoreboard.

## Scoreboard

| Carry group | Fork commits | Current classification | Omnigent evidence | Required next action |
| --- | --- | --- | --- | --- |
| Deterministic Apple top-level route evidence and bundle graph | `66360e01c5`, `7b01fd2067`, `097d9afd00`, `ce0525962a` | `replacement-ready` for the narrow Apple route case | `docs/stock-codex-replacement-contract.md` records stock Codex `0.142.2` route-prefix, graph, tool-plane, memory MCP, Apple-docs CLI, and XcodeBuildMCP proofs. | Keep fork unchanged; continue proving broader parity in Omnigent. |
| Router-selection matrix semantics: host scope, prompt boundaries, workspace signals, downstream route preservation, focused specialist suppression | `fa2fa9ba98`, `ab65f05df4`, `5be5163502`, `393f22fa01`, `f86f506f3a`, `67f216880e`, `dd0e591851`, `9b28f2aaba`, `ed4c40fecb`, `9567a9c98e`, `4286b74d90` | `replacement-ready` for the installed Apple workflow bundle matrix | `omnigent.inner.router_selection` owns the adapter policy. `tests/inner/test_router_selection.py` covers prompt-signal boundaries, host scope, workspace files/extensions, skill filters, explicit downstream domain-route preservation, top-level duplicate suppression, focused specialist suppression, and foreign-plugin suppression. `tests/inner/test_codex_executor.py` covers route-prefix emission before Codex output for the preserved downstream-route case. `scripts/prove_stock_codex_replacement.py --proof router-matrix --codex-path /opt/homebrew/bin/codex --live-proof-timeout 420` proved stock Codex `0.142.2` across prompt signal, Xcode host scope, workspace file, workspace extension, explicit downstream review route, focused specialist suppression, and non-matching host suppression. | Keep fork unchanged; rerun the matrix gate when the Apple bundle manifest or Codex CLI changes. |
| Responses stream lifecycle diagnostics | `8eea3c5b34`, `07f2c46719` | `replacement-ready` for Omnigent adapter-level progress diagnostics | `_AdapterTurnProgress` in `omnigent.runtime.harnesses._executor_adapter` records per-turn inner-executor progress and decorates `response.failed` errors when early tool-call progress appears before durable visible output. `tests/runtime/harnesses/test_executor_adapter.py::test_executor_error_after_tool_request_includes_progress_diagnostic` proves this through a real `HarnessProcessManager` subprocess stream: the function-call progress item reaches SSE, then the terminal failure includes `early output item progress before durable visible output`, `tool_call_request_seen=True`, `tool_call_complete_seen=False`, and `text_delta_seen=False`. This replaces the operator diagnostic value at the Omnigent harness boundary; it does not claim raw stock-Codex provider SSE/WebSocket lifecycle visibility or response-id mismatch logging. | Keep fork unchanged. If product later requires raw provider-stream response ids from inside stock Codex, that remains out of scope for a wrapper and should be handled as a separate keep/drop decision. |
| HTTP fallback guard by provider URL | `bb07d63968` | `replacement-ready` for Omnigent-managed Codex provider gateway URLs | `_assert_codex_http_gateway_base_url` rejects non-`http`/`https` Codex provider-family `base_url` values before `HARNESS_CODEX_GATEWAY_BASE_URL` reaches stock Codex. `tests/runtime/test_provider_spawn_env.py::test_codex_allows_http_provider_base_url` proves local HTTP gateways still work, and `tests/runtime/test_provider_spawn_env.py::test_codex_rejects_non_http_provider_base_url` proves `ws://`, `wss://`, and malformed URLs fail closed. This covers Omnigent-managed provider entries; user-managed `cli-config` provider tables in `~/.codex/config.toml` remain stock-Codex-owned unless product scope says Omnigent must parse and guard them too. | Keep fork unchanged. Treat cli-config websocket-only provider support as out of scope unless explicitly required. |
| Disabled-goal tolerance for Codex goal reads | `de81a71e9c` | `replacement-ready` for Omnigent runner goal reads | `CodexGoalRunner` normalizes stock-Codex `thread/goal/get` failures containing `goals feature is disabled` to `{"goal": null}` at the Omnigent runner boundary, while leaving write operations as errors. `tests/runner/test_codex_goal_runner.py::test_codex_goal_runner_get_returns_none_when_stock_codex_goals_are_disabled` and `tests/runner/test_codex_goal_runner.py::test_codex_goal_runner_set_keeps_disabled_goals_as_error` prove the replacement behavior without mutating stock Codex. | Keep fork unchanged. Continue treating set, status, and clear as real errors when stock Codex disables goals. |
| ChatGPT mobile remote resume redaction and payload capping | `b51c499276`, `c716294c3b` | `obsolete-if-cutover` for the current Omnigent stock-Codex replacement scope | The fork carry only activates for Codex app-server client names `codex_chatgpt_android_remote` and `codex_chatgpt_ios_remote`, capping resume turns and redacting MCP, dynamic-tool, image, file-change, and large text payloads in response-only mobile resume data. Omnigent uses `thread/resume` internally for local runner/web continuity, but the current replacement path does not expose those ChatGPT mobile remote clients or their resume payload contract. | Keep as fork fallback. Build an Omnigent-side remote-resume redaction proof only if product scope explicitly adds ChatGPT mobile/app-server remote resume compatibility. |
| Rebase and upstream-refresh adaptation commits | `fa2fa9ba98`, `393f22fa01`, `f86f506f3a`, `67f216880e`, `dd0e591851`, `9b28f2aaba`, `ed4c40fecb`, `9567a9c98e`, `aabfc59d3d`, `c716294c3b`, `4286b74d90` | `obsolete-if-cutover` | These commits keep the fork carry stack compiling and testing across upstream Codex drift. They are not independent product capabilities once the Omnigent path no longer depends on the fork. | Do not delete now. Treat as maintenance burden avoided only after explicit cutover. |

Some commits appear in both a product-behavior group and an adaptation group
because later refresh commits adjust tests or fixtures for an existing behavior.
That overlap is intentional; the product carry and the upkeep burden are
separate decisions.

## Cutover Rule

The Omnigent path is not a full fork replacement until all product-required
carry groups are classified as one of:

- `replacement-ready`
- `obsolete-if-cutover`
- explicitly out of scope by product decision

The current blocker is not more simulator gesture coverage, router-selection
parity, adapter-level runtime diagnostics, Omnigent-managed provider URL
guarding, or disabled-goal read tolerance. ChatGPT mobile remote resume
compatibility and any demand for raw stock-Codex provider-stream internals
remain product-scope decisions rather than unresolved adapter work in this
track.

## Next Proof Gate

The clean-profile `cutover-ready` aggregate proof and the default-path cutover
rehearsal are now green for the current host with stock Codex `0.142.2`. The
clean-profile gate used isolated `HOME`/cache/XDG dirs, explicit Apple bundle
input, and preserved real `CODEX_HOME` for authentication. The default-path gate
used ambient Apple bundle lookup, `PATH` stock-Codex resolution, and documented
fallback steps without mutating launcher defaults. The
`pinned-codex-provision` proof is green for provisioning a local or downloaded
source binary into an Omnigent-owned `codex-stock/<version>/codex` cache with
manifest provenance, SHA-256 verification, `.codex-fork` source rejection, and
`OMNIGENT_STOCK_CODEX_PATH` resolver proof. The current host now has that
managed stock Codex `0.142.2` payload persistently installed at
`~/.local/omnigent/codex-stock/0.142.2/codex`. The `stock-codex-channel` proof
is also green for a local/file-backed channel manifest that selects a stock
Codex artifact, verifies SHA-256 and version, stages it, installs it with
`sourceKind: channel` provenance, and proves Omnigent resolver selection; it
intentionally leaves remote `http(s)` download and production trust-source
selection for a later gate. The isolated
`launcher-activation` proof is also green for temporary PATH shadowing, pinned
stock-Codex selection through `OMNIGENT_STOCK_CODEX_PATH`, delegation through
`uvx --from <repo> omnigent codex` without recursive Codex lookup, and rollback
to the original `/opt/homebrew/bin/codex` PATH result. The current host now also
has `/opt/homebrew/bin/codex` installed as the managed Omnigent launcher, with
the original Homebrew symlink backed up at
`/opt/homebrew/bin/codex.omnigent-backup-20260628T091032Z`. The recorded
rollback command was exercised once, restored the Homebrew symlink and removed
the manifest, then the managed launcher was reinstalled. `codex --version`,
`codex --omnigent-launcher-probe`, Omnigent resolver detection, and the default
graph proof passed through that launcher after reinstall. On 2026-06-29, the
full `default-path-cutover` aggregate also passed with no explicit
`--codex-path`, resolving through the managed launcher to the pinned stock
payload and proving graph, router matrix, tool-plane, Apple memory MCP,
Apple-docs CLI, XcodeBuildMCP CLI build/install/launch, and read-only
XcodeBuildMCP discovery. On 2026-06-30, the read-only managed launcher doctor
also passed against the live host default: `codex` still resolves to the
managed `/opt/homebrew/bin/codex` launcher, the launcher and manifest are
coherent, the pinned stock payload is still
`~/.local/omnigent/codex-stock/0.142.2/codex`, the preserved backup exists,
`codex --version` and the launcher probe delegate correctly, and Omnigent's
resolver maps the launcher back to the pinned stock binary. The next gate
should stay in product operations:

- prove clean Codex-auth onboarding if first-run auth is in scope;
- broaden the Apple workflow smoke to release/readiness/review only if product
  cutover requires that higher-fidelity path; or
- decide whether to mutate app bundle launchers or other user-facing
  entrypoints beyond the CLI;
- decide whether first-run clean-auth onboarding is product scope; or
- choose the official remote metadata/download/signature source that will feed
  the now-proven channel manifest contract.

If ChatGPT mobile/app-server remote resume compatibility becomes product scope
later, reopen that as a new Omnigent-side remote-resume proof instead of
carrying it in a Codex fork.
