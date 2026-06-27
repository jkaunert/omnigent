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
| Remote resume redaction and disabled-goal tolerance | `de81a71e9c`, `b51c499276`, `aabfc59d3d`, `c716294c3b` | `obsolete-if-cutover` unless Omnigent must support the same mobile remote clients | These commits serve forked app-server remote/mobile resume behavior. The current Omnigent proof path is a local stock-Codex wrapper path and does not exercise ChatGPT mobile remote resume payloads. | Keep as fork fallback. Reclassify only if Omnigent becomes responsible for mobile remote resume. |
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
parity, adapter-level runtime diagnostics, or Omnigent-managed provider URL
guarding. Remote/mobile resume behavior and any demand for raw stock-Codex
provider-stream internals still need a product-scope decision before they can
be scored honestly.

## Next Proof Gate

The next narrow gate should address the remaining remote/mobile resume carry
group. Decide whether stock-Codex cutover needs replacement behavior for:

- remote thread resume payload redaction
- disabled-goal tolerance for remote reads
- mobile/app-server resume compatibility around stock Codex

If those are not product requirements for the Omnigent replacement path, score
the group as `obsolete-if-cutover`. If they are required, build an
Omnigent-side remote-resume proof instead of carrying the behavior in a Codex
fork.
