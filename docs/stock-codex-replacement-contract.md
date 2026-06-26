# Stock Codex Replacement Contract

This document tracks the Omnigent development path for replacing local
Codex-fork carries with a stock-Codex wrapper. It is not an upstream
contribution plan and it is not an instruction to mutate the existing Codex
fork.

## Goal

Prove that Omnigent can wrap an unmodified Codex surface and provide the
workflow behaviors that previously required fork-local Codex carries.

The expected end state is an independent Omnigent-based runtime path. Once it
is proven, operational cutover can choose that path instead of continuing to
maintain the Codex fork. The Codex fork remains the proven production fallback
until that explicit cutover decision is made.

## Separation Rules

- Do not merge Omnigent harness code into the Codex fork.
- Do not delete, retire, or rewrite Codex-fork carries as part of this track.
- Do not mutate the current Codex-fork worktree to make Omnigent proofs pass.
- Use the Codex fork only as a read-only comparator for behavior and carry
  inventory unless a separate Codex-fork task explicitly asks otherwise.
- Keep Omnigent proof branches, commits, fixtures, scripts, and docs in the
  Omnigent track.
- Treat replacement readiness as evidence for a future cutover decision, not as
  permission to change the existing fork.

## Terms

- Replacement contract: the evidence table that says which carried behaviors
  Omnigent can provide around stock Codex.
- Carry: a fork-local Codex change or patch maintained to preserve local
  workflow behavior.
- Stock Codex: an unmodified Codex CLI/app-server surface used through normal
  installation and authentication paths.
- Adapter: Omnigent-owned code that translates bundle policy, routing,
  sessions, tools, or environment into stock-Codex-compatible inputs and
  outputs.
- Proof gate: a repeatable command, fixture, or manual check that demonstrates
  one replacement claim.
- Cutover decision: a separate operational decision to use the Omnigent path as
  the default. This document does not perform that cutover.

## Carry Classification

Each carry or behavior should land in exactly one current classification.

| Classification | Meaning | Allowed next action |
| --- | --- | --- |
| `replacement-ready` | Omnigent plus stock Codex has a repeatable proof for the behavior. | Record evidence; keep the Codex fork unchanged. |
| `needs-omnigent-adapter` | The behavior belongs in Omnigent, but no proof exists yet. | Build the smallest Omnigent adapter/proof slice. |
| `needs-stock-codex-config` | The behavior is available in stock Codex but needs install, config, env, or host setup. | Document and prove the setup path. |
| `unproven` | The behavior is required but has not been tested through stock Codex. | Create a bounded proof gate. |
| `obsolete-if-cutover` | The behavior only supports the old forked path and would not be needed after cutover. | Do not delete it now; mark it as cutover-only cleanup. |
| `blocked` | The proof cannot proceed because of host state, missing upstream capability, or unclear requirements. | Preserve state and record the blocker without mutating the fork. |

## Evidence Requirements

A replacement claim is not accepted until it records:

- Omnigent commit or branch.
- Stock Codex binary and version or path used for the proof.
- Whether the proof used direct executor, normal Omnigent session/runner path,
  or another surface.
- Fixture location or generation steps.
- Exact proof command.
- Output excerpt showing the behavior.
- Known caveats and what the proof does not cover.
- Confirmation that no Codex-fork files were changed by the proof.

## Initial Proven Slice

The current spike proves the first narrow adapter behavior:

| Behavior | Status | Evidence |
| --- | --- | --- |
| Deterministic `routerSelection` route evidence before Codex model output | `replacement-ready` for the narrow Apple top-level route case | Omnigent branch `spike/codex-router-selection-adapter`, commit `51dc45ea`; direct Codex executor proof and normal Omnigent `run_prompt()` session/runner proof both emitted `Routing: orchestrator-led` before model continuation. |
| Full Apple top-level skill graph from an Omnigent bundle | `replacement-ready` for the selected `apple-app-orchestrator` graph | `scripts/prove_stock_codex_replacement.py` resolved 19 relative reference files and 13 referenced Apple skills inside the generated Omnigent bundle, then stock Codex read `references/brigade-output-contract.md` through normal `run_prompt()` and returned `GRAPH_OK`; initially proven on `0.137.0` and revalidated on `0.142.2`. |
| Omnigent dynamic tool exposure to stock Codex | `replacement-ready` for the `dynamicTools` channel | `scripts/prove_stock_codex_replacement.py --proof tool-plane` verified the Apple bundle's `.mcp.json` declares `XcodeBuildMCP`, `memory`, and `sosumi`, then stock Codex `0.142.2` invoked Omnigent-exposed `sys_os_read` through normal `run_prompt()`; persisted session items included a `function_call` and matching `function_call_output` containing the sentinel. |
| Apple `.mcp.json` `memory` server execution through Omnigent | `replacement-ready` for the local stdio `memory` server | `scripts/prove_stock_codex_replacement.py --proof apple-mcp` converted the Apple plugin `.mcp.json` `memory` server into an Omnigent `tools: memory: type: mcp` declaration with an isolated temp `MEMORY_FILE_PATH`, then stock Codex `0.142.2` invoked `memory__create_entities`; persisted session items included a `function_call` and matching `function_call_output` containing `APPLE_MCP_SENTINEL_73`. |
| Apple `.mcp.json` `sosumi` server execution through Omnigent | `blocked` at the stock-Codex sessions/proxy layer | `scripts/prove_stock_codex_replacement.py --proof apple-mcp-sosumi` converts the Apple plugin `.mcp.json` `sosumi` server into an Omnigent `tools: sosumi: type: mcp` declaration. Diagnosis on 2026-06-25 showed direct `McpServerConnection` and direct `RunnerMcpManager` can list and call sosumi quickly, direct `CodexExecutor` can call a hidden-result dynamic tool, and direct Sosumi CLI fetches succeed. The current headless sessions/proxy path still times out before any assistant or function-call item is persisted; the narrowed timeout diagnostic reported `session_status=running`, `last_task_error=None`, and persisted items limited to `resource_event` plus the user message after 75 seconds. |
| Apple documentation fetch through a Sosumi CLI adapter | `replacement-ready` for the `fetch-apple-docs` CLI adapter/policy transport | `omnigent.adapters.apple_docs_cli.AppleDocsCliAdapterPolicy` installs a generated `fetch_apple_docs` Python dynamic tool when the Apple bundle MCP manifest still declares `sosumi`; the policy validates `https://developer.apple.com` documentation, HIG, and video URLs and leaves the existing MCP config unchanged. `scripts/prove_stock_codex_replacement.py --proof apple-docs-cli --codex-path /opt/homebrew/bin/codex --live-proof-timeout 180` proved stock Codex `0.142.2` invoked that tool through normal Omnigent `dynamicTools`; persisted session items included a `function_call` and matching `function_call_output` containing `title: String`, `source: https://developer.apple.com/documentation/swift/string`, and `timestamp: 2026-06-25T23:44:15.942Z`; the model replied with the exact timestamp. This proves the Apple-docs capability through the CLI adapter, not the network-backed MCP sessions path. |
| Apple `.mcp.json` `XcodeBuildMCP` project discovery through Omnigent | `replacement-ready` for read-only project discovery | `scripts/prove_stock_codex_replacement.py --proof apple-mcp-xcodebuild` converted the Apple plugin `.mcp.json` `XcodeBuildMCP` server into an Omnigent `tools: XcodeBuildMCP: type: mcp` declaration, then stock Codex `0.142.2` invoked `XcodeBuildMCP__discover_projs` against the local Omnigent checkout; persisted session items included a `function_call` and matching `function_call_output` that found `ap-web/ios/Omnigent.xcodeproj`. This does not prove build, test, launch, simulator, or device execution. |
| Apple `.mcp.json` `XcodeBuildMCP` simulator build through Omnigent | `replacement-ready` for compile-only iOS simulator build | `scripts/prove_stock_codex_replacement.py --proof apple-mcp-xcodebuild-build --codex-path /opt/homebrew/bin/codex --live-proof-timeout 240` converted the Apple plugin `.mcp.json` `XcodeBuildMCP` server into an Omnigent MCP tool config, then stock Codex `0.142.2` invoked `XcodeBuildMCP__session_show_defaults`, `XcodeBuildMCP__session_set_defaults` with `persist: false`, and `XcodeBuildMCP__build_sim` with `extraArgs: ["-quiet"]` against `ap-web/ios/Omnigent.xcodeproj`, scheme `Omnigent`, configuration `Debug`, simulator `iPhone 17`, and temporary DerivedData. Persisted session items included all three function calls and matching outputs; the build output included `iOS Simulator Build build succeeded for scheme Omnigent`. This proves compile-only simulator build, not install, launch, UI automation, tests, device builds, or XcodeBuildMCP CLI parity. |
| Apple `.mcp.json` `XcodeBuildMCP` simulator run/launch through Omnigent MCP | `blocked` at the stock-Codex sessions/proxy layer | Direct XcodeBuildMCP `build_run_sim` succeeded on 2026-06-26 for `ap-web/ios/Omnigent.xcodeproj`, scheme `Omnigent`, simulator `iPhone 17`, and reported `The app (ai.omnigent.ios) is now running in the iOS Simulator.` The stock-Codex Omnigent MCP gate `scripts/prove_stock_codex_replacement.py --proof apple-mcp-xcodebuild-run --codex-path /opt/homebrew/bin/codex --live-proof-timeout 300` timed out after 301.3 seconds before producing a persisted proof result. This preserves the existing XcodeBuildMCP discovery/build proof while marking install/launch through the MCP sessions path as not replacement-ready. |
| XcodeBuildMCP simulator run/launch through a CLI adapter | `replacement-ready` for bounded iOS simulator build/install/launch | `omnigent.adapters.xcodebuild_cli.XcodeBuildCliAdapterPolicy` installs a generated `xcodebuildmcp_simulator_build_run` Python dynamic tool when the Apple bundle MCP manifest declares `XcodeBuildMCP`; the policy keeps the existing MCP config unchanged, constrains the tool to `.xcodeproj` paths, iOS simulator names, temp DerivedData roots, and `extra_args: ["-quiet"]`, and passes full-feature CLI env overrides: `XCODEBUILDMCP_ENABLED_WORKFLOWS=coverage,debugging,device,doctor,macos,project-discovery,project-scaffolding,session-management,simulator-management,simulator,swift-package,ui-automation,utilities,workflow-discovery,xcode-ide`, `XCODEBUILDMCP_EXPERIMENTAL_WORKFLOW_DISCOVERY=true`, and `XCODEBUILDMCP_DEBUG=true`. `scripts/prove_stock_codex_replacement.py --proof apple-xcodebuild-cli-run --codex-path /opt/homebrew/bin/codex --live-proof-timeout 300` re-proved stock Codex `0.142.2` invoked that generated tool through normal Omnigent `dynamicTools` with the full-feature env; persisted session `conv_aa44681fbc124422b92a3f02e1d84c96` included function call `call_v8VfWnpylRGiJMUR5FomGwXo`, CLI output containing `Build succeeded`, `Build & Run complete`, and `Bundle ID: ai.omnigent.ios`, and the model replied `XCODEBUILDMCP_CLI_RUN_OK`. This proves the bounded CLI-adapter run/launch path, not XcodeBuildMCP MCP run parity, UI automation, device execution, or a clean-host install. |
| XcodeBuildMCP simulator tests through a CLI adapter | `replacement-ready` for bounded iOS simulator tests | `omnigent.adapters.xcodebuild_cli.XcodeBuildCliAdapterPolicy` now also installs a generated `xcodebuildmcp_simulator_test` Python dynamic tool for the simulator test boundary, with the same full-feature CLI env overrides that enable non-default workflows and experimental workflow discovery. Direct `xcodebuildmcp simulator test` with those env overrides found and passed 9 Omnigent iOS tests. `scripts/prove_stock_codex_replacement.py --proof apple-xcodebuild-cli-test --codex-path /opt/homebrew/bin/codex --live-proof-timeout 360` then proved stock Codex `0.142.2` invoked the generated test tool through normal Omnigent `dynamicTools`; persisted session `conv_f80892556ef54e96849b1de8481a1518` included function call `call_7Dzms7WmGDach013GZmEcJgC`, CLI output containing `9 tests passed`, `0 failed`, and `0 skipped`, and the model replied `XCODEBUILDMCP_CLI_TEST_OK`. This proves bounded simulator tests through the CLI adapter, not UI automation, device tests, or XcodeBuildMCP MCP test parity. |
| XcodeBuildMCP simulator screenshot through a CLI adapter | `replacement-ready` for bounded non-mutating iOS simulator screenshot after launch | `omnigent.adapters.xcodebuild_cli.XcodeBuildCliAdapterPolicy` now also installs a generated `xcodebuildmcp_simulator_screenshot` Python dynamic tool for the UI screenshot boundary, with the same full-feature CLI env overrides. The tool runs `xcodebuildmcp simulator build-and-run --output json`, extracts the launched simulator id, runs `xcodebuildmcp ui-automation screenshot --output json`, verifies the screenshot file exists, and returns a compact JSON summary. `scripts/prove_stock_codex_replacement.py --proof apple-xcodebuild-cli-screenshot --codex-path /opt/homebrew/bin/codex --live-proof-timeout 360` proved stock Codex `0.142.2` invoked the generated screenshot tool through normal Omnigent `dynamicTools`; persisted session `conv_f65409a009804370a00b35e00d26d727` included function call `call_wW5AEWaSRCFkxUy7m2z6LuoU`, output containing `"buildStatus": "SUCCEEDED"`, `"screenshotStatus": "SUCCEEDED"`, `"bundleId": "ai.omnigent.ios"`, `"format": "image/jpeg"`, `"width": 368`, and `"height": 800`, and the model replied `XCODEBUILDMCP_CLI_SCREENSHOT_OK`. This proves bounded screenshot capture through the CLI adapter, not semantic UI hierarchy snapshots, gestures, logs, device execution, or Xcode IDE bridge tools. |
| XcodeBuildMCP semantic UI snapshot through a CLI adapter | `replacement-ready` for bounded Xcode 27 Beta 2 simulator hierarchy snapshots with a source-provisioned patched AXe path | `omnigent.adapters.xcodebuild_cli.XcodeBuildCliAdapterPolicy` now installs a generated `xcodebuildmcp_simulator_snapshot_ui` Python dynamic tool for the semantic UI hierarchy boundary. The tool strips ambient `XCODEBUILDMCP_AXE_PATH`, maps an explicit `OMNIGENT_XCODEBUILDMCP_AXE_PATH` into the generated CLI subprocess env, uses a per-call isolated XcodeBuildMCP socket, runs `xcodebuildmcp simulator build-and-run --output json`, extracts the simulator id, runs `xcodebuildmcp ui-automation snapshot-ui --output json`, validates `type: runtime-snapshot`, positive `count`, and non-empty `targets`, then stops the isolated daemon best-effort. The patched AXe compatibility source is pinned to `jkaunert/AXe@9051a6e13fdd8e0789f734a11fc1e71f48def916`; upstream PR [cameroncooke/AXe#60](https://github.com/cameroncooke/AXe/pull/60) tracks absorption or supersession. That fork commit includes the Xcode 27 `SharedFrameworks` lookup fix plus the Xcode 27 deployment-target patch needed for IDB/AXe source builds under Xcode 27 Beta 2. `scripts/provision_xcode27_axe.py` builds, installs, and verifies the AXe runtime payload under `~/.cache/omnigent/axe/payloads/9051a6e13fdd8e0789f734a11fc1e71f48def916`, including the executable, sibling `Frameworks`, and both legacy and Xcode 27 `SimulatorKit` lookup markers in `FBControlCore`; source builds default to ad hoc signing (`-`). `DEVELOPER_DIR=/Applications/Xcode-27.0.0-Beta.2.app/Contents/Developer uvx --from . python scripts/provision_xcode27_axe.py --force --json` proved the default remote source-provisioning path. A stricter clean-profile run then used an empty temporary `HOME`, `UV_CACHE_DIR`, and AXe cache root, with only `CODEX_HOME=/Users/joshuakaunert/.codex` preserved for stock-Codex auth, and proved source provisioning from an empty cache plus the stock-Codex snapshot path. The clean-profile stock-Codex proof persisted session `conv_552d6c8d420a4e2fb709aa5cb980c922` with function call `call_kMObyDaKD0vtbW2vhsDnfIJI`; output contained `"buildStatus": "SUCCEEDED"`, `"snapshotStatus": "SUCCEEDED"`, `"bundleId": "ai.omnigent.ios"`, `"type": "runtime-snapshot"`, `"count": 16`, `screenHash: "0d3ho2y"`, and actionable refs including `e14|typeText|text-field||http://localhost:6767|` and `e15|tap|button|Connect||`; the model replied `XCODEBUILDMCP_CLI_SNAPSHOT_UI_OK`. This proves bounded semantic UI hierarchy capture through the CLI adapter plus source-provisioned patched AXe on this host, including an empty-cache profile run; it does not prove gestures, logs, device execution, upstream AXe direct parity, a different machine, or Xcode IDE bridge tools. |

This does not yet prove full Codex-fork replacement.

## Proof Commands

Static graph proof only:

```bash
uvx --from . python scripts/prove_stock_codex_replacement.py \
  --skip-live
```

Live stock-Codex runner proof:

```bash
uvx --from . python scripts/prove_stock_codex_replacement.py \
  --codex-path /opt/homebrew/bin/codex
```

Tool-plane bounded proof:

```bash
uvx --from . python scripts/prove_stock_codex_replacement.py \
  --proof tool-plane \
  --codex-path /opt/homebrew/bin/codex
```

Apple memory MCP execution proof:

```bash
uvx --from . python scripts/prove_stock_codex_replacement.py \
  --proof apple-mcp \
  --codex-path /opt/homebrew/bin/codex
```

Apple sosumi MCP execution proof:

```bash
uvx --from . python scripts/prove_stock_codex_replacement.py \
  --proof apple-mcp-sosumi \
  --codex-path /opt/homebrew/bin/codex
```

Apple documentation Sosumi CLI adapter proof:

```bash
uvx --from . python scripts/prove_stock_codex_replacement.py \
  --proof apple-docs-cli \
  --codex-path /opt/homebrew/bin/codex \
  --live-proof-timeout 180
```

Apple XcodeBuildMCP read-only discovery proof:

```bash
uvx --from . python scripts/prove_stock_codex_replacement.py \
  --proof apple-mcp-xcodebuild \
  --codex-path /opt/homebrew/bin/codex
```

Apple XcodeBuildMCP compile-only simulator build proof:

```bash
uvx --from . python scripts/prove_stock_codex_replacement.py \
  --proof apple-mcp-xcodebuild-build \
  --codex-path /opt/homebrew/bin/codex \
  --live-proof-timeout 240
```

Apple XcodeBuildMCP simulator run/launch MCP proof:

```bash
uvx --from . python scripts/prove_stock_codex_replacement.py \
  --proof apple-mcp-xcodebuild-run \
  --codex-path /opt/homebrew/bin/codex \
  --live-proof-timeout 300
```

Apple XcodeBuildMCP simulator run/launch CLI adapter proof:

```bash
uvx --from . python scripts/prove_stock_codex_replacement.py \
  --proof apple-xcodebuild-cli-run \
  --codex-path /opt/homebrew/bin/codex \
  --live-proof-timeout 300
```

Apple XcodeBuildMCP simulator test CLI adapter proof:

```bash
uvx --from . python scripts/prove_stock_codex_replacement.py \
  --proof apple-xcodebuild-cli-test \
  --codex-path /opt/homebrew/bin/codex \
  --live-proof-timeout 360
```

Apple XcodeBuildMCP simulator screenshot CLI adapter proof:

```bash
uvx --from . python scripts/prove_stock_codex_replacement.py \
  --proof apple-xcodebuild-cli-screenshot \
  --codex-path /opt/homebrew/bin/codex \
  --live-proof-timeout 360
```

Provision the pinned Xcode 27-compatible AXe payload from source:

```bash
DEVELOPER_DIR=/Applications/Xcode-27.0.0-Beta.2.app/Contents/Developer \
uvx --from . python scripts/provision_xcode27_axe.py \
  --force \
  --json
```

Source builds default to ad hoc signing (`-`). Override with
`AXE_CODESIGN_IDENTITY` or `--codesign-identity` when a distribution signing
identity is required.

Provision the pinned Xcode 27-compatible AXe payload from an existing verified
local build only when source compilation is intentionally being skipped:

```bash
uvx --from . python scripts/provision_xcode27_axe.py \
  --source-binary /Users/joshuakaunert/Developer/HarnessEngineering/spikes/AXe-xcode27/build_products/axe \
  --no-build \
  --print-shell-env
```

Apple XcodeBuildMCP semantic snapshot CLI adapter proof with the provisioned
patched AXe binary:

```bash
AXE_PATH="$(
  DEVELOPER_DIR=/Applications/Xcode-27.0.0-Beta.2.app/Contents/Developer \
  uvx --from . python scripts/provision_xcode27_axe.py \
    --print-path
)"

DEVELOPER_DIR=/Applications/Xcode-27.0.0-Beta.2.app/Contents/Developer \
uvx --from . python scripts/prove_stock_codex_replacement.py \
  --proof apple-xcodebuild-cli-snapshot-ui \
  --codex-path /opt/homebrew/bin/codex \
  --live-proof-timeout 480 \
  --xcodebuildmcp-axe-path "$AXE_PATH"
```

Combined bounded proof:

```bash
uvx --from . python scripts/prove_stock_codex_replacement.py \
  --proof all \
  --codex-path /opt/homebrew/bin/codex \
  --live-proof-timeout 180
```

The proof script copies the installed Apple workflow bundle into a temporary
Omnigent agent, writes an Omnigent `harness: codex` config, refuses
`.codex-fork` binaries by default, and removes the temp fixture unless
`--keep-fixture` is passed. Live proof runs emit `live_proof_start`,
`live_proof_ok`, `live_proof_failed`, or `live_proof_timeout` for each bounded
surface. In the combined proof, each MCP surface is run with its own generated
Omnigent tools config so one hanging server does not obscure which replacement
surface failed.

Current aggregate status on 2026-06-25: `graph`, `tool-plane`, and
`apple-mcp-memory` passed under `--proof all`; `apple-mcp-sosumi` timed out at
180 seconds, and standalone `apple-mcp-sosumi` reruns also timed out. Follow-up
diagnosis isolated sosumi itself as healthy: direct MCP, direct
`RunnerMcpManager`, direct Sosumi CLI, and stock-Codex dynamic tool execution
all succeeded outside the network-backed MCP sessions path. The headless
sessions/proxy path remains blocked and now reports a clean 75-second timeout
diagnostic with the session still running and only `resource_event` plus the
user message persisted. The `apple-docs-cli` proof passed through the normal
Omnigent session/runner path, and its adapter policy now installs from the
Apple bundle's `sosumi` MCP presence without mutating that MCP declaration. So
Apple documentation fetching is replacement ready through the CLI adapter even
though the Sosumi MCP path remains blocked.
The aggregate proof therefore does not currently reach the XcodeBuildMCP
discovery step, which remains proven by its standalone gate. A standalone
XcodeBuildMCP compile-only simulator build gate also passed on 2026-06-25 after
an initial prompt-shape failure where stock Codex wrote a pseudo-call in prose
instead of emitting persisted function calls; the final gate now explicitly
rejects pseudo-calls and validates the three persisted build-boundary calls.
On 2026-06-26, direct XcodeBuildMCP `build_run_sim` and direct
`xcodebuildmcp simulator build-and-run` both launched `ai.omnigent.ios` on
`iPhone 17`, but the stock-Codex Omnigent MCP run gate timed out after 301.3
seconds. The generated XcodeBuildMCP CLI adapter gate then passed through normal
stock-Codex `dynamicTools`, so bounded simulator build/install/launch is
replacement-ready through the CLI adapter while the MCP run/launch path remains
blocked.
The CLI adapter policy now explicitly enables the full installed XcodeBuildMCP
workflow surface, including `workflow-discovery`, by passing
`XCODEBUILDMCP_ENABLED_WORKFLOWS`, `XCODEBUILDMCP_EXPERIMENTAL_WORKFLOW_DISCOVERY=true`,
and `XCODEBUILDMCP_DEBUG=true` to generated CLI subprocesses. With those env
overrides, default MCP registration expands from the simulator-only subset to
the full configured workflow surface. The bounded simulator test adapter proof
also passed on 2026-06-26: stock Codex invoked `xcodebuildmcp_simulator_test`
through Omnigent `dynamicTools`, and the CLI reported `9 tests passed, 0 failed,
0 skipped`.
The bounded simulator screenshot adapter proof also passed on 2026-06-26:
stock Codex invoked `xcodebuildmcp_simulator_screenshot` through Omnigent
`dynamicTools`, and the CLI returned a successful JPEG screenshot summary with
positive dimensions. The semantic `snapshot-ui` surface is now separately
proven through a generated CLI adapter when the proof supplies an explicit
patched AXe binary. That proof uses command-scoped `DEVELOPER_DIR` and
`OMNIGENT_XCODEBUILDMCP_AXE_PATH`; it does not require global `xcode-select`
mutation, Xcode bundle mutation, or Homebrew Cellar mutation.

## Semantic Snapshot Resolution

Current state on 2026-06-26:

- The failing selected-Xcode diagnosis used
  `/Applications/Xcode-27.0.0-Beta.app/Contents/Developer` (`Xcode 27.0`,
  build `27A5194q`). Source provisioning and the final stock-Codex live proof
  used command-scoped
  `/Applications/Xcode-27.0.0-Beta.2.app/Contents/Developer`.
- XcodeBuildMCP is `2.6.2`.
- `xcodebuildmcp ui-automation snapshot-ui --output json` and
  `xcodebuildmcp simulator snapshot-ui --output json` both fail against the
  booted `iPhone 17` simulator with `Failed to get accessibility hierarchy`
  because AXe attempts to load
  `/Applications/Xcode-27.0.0-Beta.app/Contents/Developer/Library/PrivateFrameworks/SimulatorKit.framework`.
- That path does not exist in either installed Xcode 27 beta bundle; the
  framework exists at
  `/Applications/Xcode-27.0.0-Beta.app/Contents/SharedFrameworks/SimulatorKit.framework`
  and `/Applications/Xcode-27.0.0-Beta.2.app/Contents/SharedFrameworks/SimulatorKit.framework`.
- Direct AXe invocation shows the same selected-Xcode failure, so the problem
  is below Omnigent and below the stock Codex session layer.
- A diagnostic isolated daemon using the original patched AXe binary at
  `/Users/joshuakaunert/Developer/HarnessEngineering/spikes/AXe-xcode27/build_products/axe`,
  command-scoped `DEVELOPER_DIR=/Applications/Xcode-27.0.0-Beta.2.app/Contents/Developer`,
  and the same full-feature XcodeBuildMCP env successfully captured a semantic
  runtime snapshot for the booted iOS 27 simulator. The snapshot returned
  `status: SUCCEEDED`, `type: runtime-snapshot`, `rs: 1`, `count: 16`, and
  actionable refs including `e15|tap|button|Connect||`.
- The patch source has been moved from a local-only spike into
  `jkaunert/AXe@9051a6e13fdd8e0789f734a11fc1e71f48def916` and proposed
  upstream as [cameroncooke/AXe#60](https://github.com/cameroncooke/AXe/pull/60).
  Omnigent should treat that fork commit as a temporary compatibility source
  until upstream absorbs or supersedes the change. The commit carries both the
  Xcode 27 `SharedFrameworks` lookup fix and an IDB deployment-target patch
  needed for source builds under Xcode 27 Beta 2.
- `scripts/provision_xcode27_axe.py` makes the compatibility payload
  reproducible for Omnigent proofs. It clones/builds the pinned fork commit
  by default with ad hoc signing (`-`), or copies an existing built `axe` plus
  sibling `Frameworks` into a deterministic cache under `~/.cache/omnigent/axe`,
  then rejects payloads whose `FBControlCore` binary does not include both the
  legacy `PrivateFrameworks` and Xcode 27 `SharedFrameworks` `SimulatorKit`
  lookup markers.
- The default source-provisioning path passed on this host with
  `DEVELOPER_DIR=/Applications/Xcode-27.0.0-Beta.2.app/Contents/Developer` and
  installed the verified payload at
  `/Users/joshuakaunert/.cache/omnigent/axe/payloads/9051a6e13fdd8e0789f734a11fc1e71f48def916/axe`.
- A stricter clean-profile proof also passed with empty temporary `HOME`,
  `UV_CACHE_DIR`, and AXe cache root. The only preserved profile state was
  `CODEX_HOME=/Users/joshuakaunert/.codex` for stock-Codex authentication.
  That run source-built AXe into the temp cache and then completed the stock
  Codex semantic snapshot proof with session
  `conv_552d6c8d420a4e2fb709aa5cb980c922` and function call
  `call_kMObyDaKD0vtbW2vhsDnfIJI`. The temporary 2.1 GB clean-profile cache was
  removed after the successful proof.
- Omnigent now owns a replacement-safe adapter contract for this boundary: the
  generated snapshot tool strips ambient `XCODEBUILDMCP_AXE_PATH`, maps only
  explicit `OMNIGENT_XCODEBUILDMCP_AXE_PATH` into the subprocess env, and uses
  a per-call isolated XcodeBuildMCP socket.
- The stock-Codex live proof passed through normal Omnigent `dynamicTools` with
  the source-provisioned cache-backed AXe path, session
  `conv_813fe1a74de04b3fbed9c47918ac89fd`, and function call
  `call_1THIkMjZaVhorRsgwSvje5I8`.

Do not treat this as upstream AXe direct parity. The clean-profile proof closes
the local Omnigent cache/setup assumption on this host, but the Xcode 27
semantic snapshot boundary still needs one of these distribution stories:

- XcodeBuildMCP/AXe supports the Xcode 27 `SharedFrameworks` layout directly.
- The operator explicitly provisions the pinned AXe fork commit, or an
  equivalent patched AXe payload, as part of setup for the selected Xcode.
- The operator intentionally selects an Xcode/AXe combination whose hierarchy
  path is known to work, and that requirement is documented as part of
  clean-host setup.
- A separate clean-machine gate proves the same source provisioning and
  stock-Codex snapshot path outside this host.

## Next Proof Gates

Run these in order unless a later gate becomes cheaper due to new evidence.

1. Upstream AXe adoption gate
   - When [cameroncooke/AXe#60](https://github.com/cameroncooke/AXe/pull/60)
     merges or is superseded, update `scripts/provision_xcode27_axe.py` away
     from the temporary `jkaunert/AXe` fork pin, then rerun source provisioning
     and the stock-Codex semantic snapshot proof. Keep the proof scoped to
     explicit `OMNIGENT_XCODEBUILDMCP_AXE_PATH` and command-scoped
     `DEVELOPER_DIR`; do not rely on global `xcode-select`, Xcode bundle
     mutation, or Homebrew Cellar mutation.

2. XcodeBuildMCP logs or runtime observation boundary
   - Add a narrow, non-mutating runtime-observation proof only after deciding
     whether screenshot-level UI evidence is sufficient for the replacement
     contract. Keep runtime logs, OSLog, debugger attach, gestures, and device
     checks separate.

3. Expand the Apple docs adapter contract only if needed
   - The current adapter/policy proof covers the documented `fetch-apple-docs`
     transport shape and a targeted Apple `String` documentation URL. Broaden it
     only when a real workflow needs additional Apple docs, HIG, or video URL
     shapes beyond the current policy allowlist.

4. Sosumi MCP timeout containment
   - Keep the isolated blocker recorded: sosumi MCP launch, remote network
     fetch, runner-local MCP dispatch, direct CLI fetch, and dynamic tool
     execution are green. The remaining failing surface is the headless
     sessions/proxy stream from the Codex harness. Diagnose it later only if
     network-backed MCP execution is still required after the CLI adapter path.

5. Session and terminal behavior
   - Prove the Omnigent path supports the required live terminal/session shape,
     including tmux/native-terminal expectations where the workflow depends on
     them.

6. Clean stock-Codex install
   - Prove the path from a clean Codex home or clean host profile using the
     stock Codex binary. Record every required install/config step.

7. End-to-end Apple workflow smoke
   - Run a representative Apple workflow request through Omnigent plus stock
     Codex and compare the visible route, tool availability, and output contract
     against the current forked path.

7. Cutover rehearsal
   - In a separate environment, run the Omnigent path as the default without
     changing the existing Codex fork. Record fallback steps.

## Non-Actions

The following are intentionally out of scope for this track:

- Deleting Codex-fork carries.
- Merging Omnigent adapters into the Codex fork.
- Treating one green proof as full replacement readiness.
- Publishing the Omnigent spike upstream before it serves the internal
  replacement goal.
- Rewriting current production workflow docs to point at Omnigent before a
  cutover decision exists.
