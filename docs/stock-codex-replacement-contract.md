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

## Carry Scoreboard

The current Codex-fork carry inventory is tracked in
`docs/codex-fork-carry-scoreboard.md`. That scoreboard maps the 22 local
carry commits against this Omnigent replacement track and preserves the
separation rule: scoring a carry as replaceable is evidence for future cutover,
not permission to mutate the existing Codex fork.

## Initial Proven Slice

The current spike proves the first narrow adapter behavior:

| Behavior | Status | Evidence |
| --- | --- | --- |
| Deterministic `routerSelection` route evidence before Codex model output | `replacement-ready` for the narrow Apple top-level route case | Omnigent branch `spike/codex-router-selection-adapter`, commit `51dc45ea`; direct Codex executor proof and normal Omnigent `run_prompt()` session/runner proof both emitted `Routing: orchestrator-led` before model continuation. |
| Router-selection matrix semantics | `replacement-ready` for the installed Apple workflow bundle matrix | `tests/inner/test_router_selection.py` covers prompt-signal boundaries, host scope, workspace file and extension signals, skill-filter gating, explicit downstream domain-route preservation, top-level duplicate suppression, focused specialist suppression, and foreign-plugin suppression. `tests/inner/test_codex_executor.py` covers route-prefix emission before Codex output for the preserved downstream-route case. `scripts/prove_stock_codex_replacement.py --proof router-matrix --codex-path /opt/homebrew/bin/codex --live-proof-timeout 420` then proved the live stock-Codex `0.142.2` session/runner path across seven cases: natural SwiftUI prompt signal, Xcode host scope, workspace `Package.swift`, workspace `.xcodeproj`, explicit downstream review route, focused decision-specialist suppression, and non-matching `server` host suppression. Persisted sessions `conv_8d545fe80c7d44bd9c654bd4a94c6b65`, `conv_659a68189bc74b5da6373138aae3724f`, `conv_1bef86a5e2b04c429664912a9a17b28b`, `conv_a8d48a31660e4df8b7e499f8c7828b28`, `conv_167cd0cbfce84801af35fc396ada4e7d`, `conv_bb2595b964ae4948ac00622b5bab5d34`, and `conv_bfba9bcf4ed9465fa36e605a2c4ef1e1` showed route evidence before the positive sentinels and no route evidence for the suppression cases. This proves the installed Apple bundle's current `routerSelection.hostScopes` of `desktop`, `xcode-headless`, and `xcode`; it does not prove arbitrary future manifest policies without rerunning the gate. |
| Adapter-level runtime failure diagnostics | `replacement-ready` for Omnigent harness progress diagnostics | `_AdapterTurnProgress` records inner-executor event progress in the shared `ExecutorAdapter` used by stock-Codex wrapping and decorates terminal failures when early tool-call progress arrives before durable visible output. The focused subprocess proof `tests/runtime/harnesses/test_executor_adapter.py::test_executor_error_after_tool_request_includes_progress_diagnostic` showed a real `HarnessProcessManager` stream emits the in-progress function-call item and then fails with diagnostic text containing `early output item progress before durable visible output`, `tool_call_request_seen=True`, `tool_call_complete_seen=False`, and `text_delta_seen=False`. This replaces the operator-facing failure classification value of the Codex fork carry at the Omnigent adapter boundary; it does not expose raw stock-Codex provider SSE/WebSocket response ids or internal transport lifecycle. |
| Codex provider URL fallback guard | `replacement-ready` for Omnigent-managed Codex provider gateway URLs | `_assert_codex_http_gateway_base_url` rejects non-`http`/`https` Codex provider-family `base_url` values before Omnigent emits `HARNESS_CODEX_GATEWAY_BASE_URL` for stock Codex. `tests/runtime/test_provider_spawn_env.py::test_codex_allows_http_provider_base_url` proves local HTTP gateways still work, and `tests/runtime/test_provider_spawn_env.py::test_codex_rejects_non_http_provider_base_url` proves `ws://`, `wss://`, and malformed URLs fail closed. This replaces the fork carry for Omnigent-managed provider entries; user-managed `cli-config` provider tables in `~/.codex/config.toml` remain stock-Codex-owned unless product scope later requires Omnigent to parse and guard them too. |
| Disabled-goal tolerance for Codex goal reads | `replacement-ready` for Omnigent runner goal reads | `CodexGoalRunner` now adapts stock-Codex `thread/goal/get` failures containing `goals feature is disabled` into Omnigent's read-only `{"goal": null}` API response, while preserving write failures for set/status/clear. `tests/runner/test_codex_goal_runner.py::test_codex_goal_runner_get_returns_none_when_stock_codex_goals_are_disabled` proves the read fallback; `tests/runner/test_codex_goal_runner.py::test_codex_goal_runner_set_keeps_disabled_goals_as_error` proves the adapter does not silently accept writes when stock Codex disables goals. |
| ChatGPT mobile remote resume redaction and payload capping | `obsolete-if-cutover` for the current Omnigent replacement scope | Read-only fork inspection showed the carry activates only for Codex app-server client names `codex_chatgpt_android_remote` and `codex_chatgpt_ios_remote`, where it response-redacts or caps mobile `thread/resume` payloads. Omnigent uses stock-Codex `thread/resume` internally for runner/web continuity, but the current replacement path does not expose ChatGPT mobile remote clients or their resume payload contract. This remains a new product scope if Omnigent later needs ChatGPT mobile/app-server remote resume compatibility. |
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
| XcodeBuildMCP simulator runtime logs through a CLI adapter | `replacement-ready` for bounded iOS simulator launch log observation | `omnigent.adapters.xcodebuild_cli.XcodeBuildCliAdapterPolicy` now installs a generated `xcodebuildmcp_simulator_runtime_logs` Python dynamic tool for the runtime-observation boundary, with the same full-feature CLI env overrides. The tool runs `xcodebuildmcp simulator build-and-run --output json`, extracts `runtimeLogPath` and `osLogPath`, verifies the files exist, waits briefly for log content to flush, and returns compact JSON with build, launch, runtime-log, and OS-log statuses plus paths, line counts, and excerpts. `DEVELOPER_DIR=/Applications/Xcode-27.0.0-Beta.2.app/Contents/Developer uvx --from . python scripts/prove_stock_codex_replacement.py --proof apple-xcodebuild-cli-runtime-logs --codex-path /opt/homebrew/bin/codex --live-proof-timeout 480` proved stock Codex `0.142.2` invoked that generated tool through normal Omnigent `dynamicTools`; persisted session `conv_dd977e23d864414bbe2778912bff3274` included function call `call_vnSAHZBr9fRznS5S0NoK8uBs`, output containing `"buildStatus": "SUCCEEDED"`, `"launchStatus": "SUCCEEDED"`, `"runtimeLogStatus": "SUCCEEDED"`, `"osLogStatus": "SUCCEEDED"`, `"bundleId": "ai.omnigent.ios"`, a runtime log excerpt including `UIAccessibilityLoaderWebShared`, an OS log excerpt including `getpwuid_r did not find a match for uid 501`, and the model replied `XCODEBUILDMCP_CLI_RUNTIME_LOGS_OK`. This proves bounded launch log observation through the CLI adapter, not debugger attach, gestures, device logs, streaming log follow, XcodeBuildMCP MCP run parity, or Xcode IDE bridge tools. |
| XcodeBuildMCP semantic UI snapshot through a CLI adapter | `replacement-ready` for bounded Xcode 27 Beta 2 simulator hierarchy snapshots with a source-provisioned patched AXe path | `omnigent.adapters.xcodebuild_cli.XcodeBuildCliAdapterPolicy` now installs a generated `xcodebuildmcp_simulator_snapshot_ui` Python dynamic tool for the semantic UI hierarchy boundary. The tool strips ambient `XCODEBUILDMCP_AXE_PATH`, maps an explicit `OMNIGENT_XCODEBUILDMCP_AXE_PATH` into the generated CLI subprocess env, uses a per-call isolated XcodeBuildMCP socket, runs `xcodebuildmcp simulator build-and-run --output json`, extracts the simulator id, runs `xcodebuildmcp ui-automation snapshot-ui --output json`, validates `type: runtime-snapshot`, positive `count`, and non-empty `targets`, then stops the isolated daemon best-effort. The patched AXe compatibility source is pinned to `jkaunert/AXe@9051a6e13fdd8e0789f734a11fc1e71f48def916`; upstream PR [cameroncooke/AXe#60](https://github.com/cameroncooke/AXe/pull/60) tracks absorption or supersession. That fork commit includes the Xcode 27 `SharedFrameworks` lookup fix plus the Xcode 27 deployment-target patch needed for IDB/AXe source builds under Xcode 27 Beta 2. `scripts/provision_xcode27_axe.py` builds, installs, and verifies the AXe runtime payload under `~/.cache/omnigent/axe/payloads/9051a6e13fdd8e0789f734a11fc1e71f48def916`, including the executable, sibling `Frameworks`, and both legacy and Xcode 27 `SimulatorKit` lookup markers in `FBControlCore`; source builds default to ad hoc signing (`-`). `DEVELOPER_DIR=/Applications/Xcode-27.0.0-Beta.2.app/Contents/Developer uvx --from . python scripts/provision_xcode27_axe.py --force --json` proved the default remote source-provisioning path. A stricter clean-profile run then used an empty temporary `HOME`, `UV_CACHE_DIR`, and AXe cache root, with only `CODEX_HOME=/Users/joshuakaunert/.codex` preserved for stock-Codex auth, and proved source provisioning from an empty cache plus the stock-Codex snapshot path. The clean-profile stock-Codex proof persisted session `conv_552d6c8d420a4e2fb709aa5cb980c922` with function call `call_kMObyDaKD0vtbW2vhsDnfIJI`; output contained `"buildStatus": "SUCCEEDED"`, `"snapshotStatus": "SUCCEEDED"`, `"bundleId": "ai.omnigent.ios"`, `"type": "runtime-snapshot"`, `"count": 16`, `screenHash: "0d3ho2y"`, and actionable refs including `e14|typeText|text-field||http://localhost:6767|` and `e15|tap|button|Connect||`; the model replied `XCODEBUILDMCP_CLI_SNAPSHOT_UI_OK`. This proves bounded semantic UI hierarchy capture through the CLI adapter plus source-provisioned patched AXe on this host, including an empty-cache profile run; it does not prove gestures, logs, device execution, upstream AXe direct parity, a different machine, or Xcode IDE bridge tools. |
| XcodeBuildMCP type-text interaction through a CLI adapter | `replacement-ready` for bounded iOS simulator text entry into a discovered text-field ref | `omnigent.adapters.xcodebuild_cli.XcodeBuildCliAdapterPolicy` now installs a generated `xcodebuildmcp_simulator_type_text` Python dynamic tool for the first UI interaction boundary. The tool strips ambient `XCODEBUILDMCP_AXE_PATH`, maps an explicit `OMNIGENT_XCODEBUILDMCP_AXE_PATH`, uses a per-call isolated XcodeBuildMCP socket, runs `xcodebuildmcp simulator build-and-run --output json`, captures a semantic snapshot, selects the first target that explicitly advertises `typeText` on a `text-field`, runs `xcodebuildmcp ui-automation type-text --replace-existing`, then verifies the sentinel through `xcodebuildmcp ui-automation wait-for-ui --predicate textContains`. `DEVELOPER_DIR=/Applications/Xcode-27.0.0-Beta.2.app/Contents/Developer uvx --from . python scripts/prove_stock_codex_replacement.py --proof apple-xcodebuild-cli-type-text --codex-path /opt/homebrew/bin/codex --live-proof-timeout 480 --xcodebuildmcp-axe-path ~/.cache/omnigent/axe/payloads/9051a6e13fdd8e0789f734a11fc1e71f48def916/axe` proved stock Codex `0.142.2` invoked that generated tool through normal Omnigent `dynamicTools`; persisted session `conv_afea5726821741c6a2cfbe255d56d41e` included function call `call_D9IzTX3TfyN6OUgQOd8eopRx`, output containing `"buildStatus": "SUCCEEDED"`, `"typeTextStatus": "SUCCEEDED"`, `"waitStatus": "SUCCEEDED"`, `"bundleId": "ai.omnigent.ios"`, `"elementRef": "e14"`, `beforeTarget` with `http://localhost:6767`, and `afterTargets` with `http://localhost:6767/gesture-proof`; the model replied `XCODEBUILDMCP_CLI_TYPE_TEXT_OK`. This proves bounded text-entry interaction through the CLI adapter, not tap, drag, multi-step navigation, debugger attach, device execution, streaming log follow, XcodeBuildMCP MCP parity, or Xcode IDE bridge tools. |
| XcodeBuildMCP tap interaction through a CLI adapter | `replacement-ready` for bounded iOS simulator tap on a discovered button ref after deterministic app-state reset | `omnigent.adapters.xcodebuild_cli.XcodeBuildCliAdapterPolicy` now installs a generated `xcodebuildmcp_simulator_tap` Python dynamic tool for the first tap boundary. The tool strips ambient `XCODEBUILDMCP_AXE_PATH`, maps an explicit `OMNIGENT_XCODEBUILDMCP_AXE_PATH`, uses a per-call isolated XcodeBuildMCP socket, performs an initial `xcodebuildmcp simulator build-and-run --output json` to discover the simulator and bundle id, clears persisted app state with command-scoped `xcrun simctl uninstall`, launches a fresh install, captures a semantic snapshot, types `http://localhost:6767/gesture-proof` into the discovered text field, selects only the discovered `tap` action on the `Connect` button, taps it, then waits for a settled post-tap snapshot whose text field has normalized back to `http://localhost:6767`. `DEVELOPER_DIR=/Applications/Xcode-27.0.0-Beta.2.app/Contents/Developer uvx --from . python scripts/prove_stock_codex_replacement.py --proof apple-xcodebuild-cli-tap --codex-path /opt/homebrew/bin/codex --live-proof-timeout 480 --xcodebuildmcp-axe-path ~/.cache/omnigent/axe/payloads/9051a6e13fdd8e0789f734a11fc1e71f48def916/axe` proved stock Codex `0.142.2` invoked that generated tool through normal Omnigent `dynamicTools`; persisted session `conv_a7d66fc64df148edbe616855fe0de7fd` included function call `call_DCsJXv24ga2bZYGrUaKz3Nef`, output containing `"preResetBuildStatus": "SUCCEEDED"`, `"resetStatus": "SUCCEEDED"`, `"buildStatus": "SUCCEEDED"`, `"typeTextStatus": "SUCCEEDED"`, `"tapStatus": "SUCCEEDED"`, `"settledStatus": "SUCCEEDED"`, `"bundleId": "ai.omnigent.ios"`, `afterTapTarget` with `http://localhost:6767`, and `afterTapScreenHash: "13s4ko7"`; the model replied `XCODEBUILDMCP_CLI_TAP_OK`. This proves one bounded tap interaction through the CLI adapter, not drag, multi-step navigation, debugger attach, device execution, streaming log follow, XcodeBuildMCP MCP parity, or Xcode IDE bridge tools. |
| Representative Apple workflow smoke through Omnigent plus stock Codex | `replacement-ready` for a routed workflow that uses Apple docs plus read-only Xcode discovery in one stock-Codex session | `scripts/prove_stock_codex_replacement.py --proof apple-workflow-smoke --codex-path /opt/homebrew/bin/codex --live-proof-timeout 240` proved stock Codex `0.142.2` began with the deterministic Apple route block, invoked Omnigent's generated `fetch_apple_docs` tool for `https://developer.apple.com/documentation/swift/string`, then invoked read-only `XcodeBuildMCP__discover_projs` against the Omnigent checkout. Persisted session `conv_6a8bb2b3fa6c4dc182d79ed961581e13` included Apple-docs call `call_YhQNwu4vF4gs4nDZJcTRbNfp` with output containing `title: String`, source URL, and timestamp `2026-06-27T22:39:20.021Z`, plus XcodeBuildMCP call `call_0CgVXm1tP9O2Tcua92bYpovU` with output finding `ap-web/ios/Omnigent.xcodeproj`; the model replied `APPLE_WORKFLOW_SMOKE_OK`. The proof rejects build, run, test, launch, simulator boot/open, and device tools. This proves one representative routed workflow surface, not full release-readiness, branch-diff review, clean-auth onboarding, default-path cutover, or broader XcodeBuildMCP workflow parity. |
| Default-path cutover rehearsal | `replacement-ready` for current-host ambient bundle lookup plus `PATH` stock-Codex resolution | `scripts/prove_stock_codex_replacement.py --proof default-path-cutover --live-proof-timeout 600` proved the same bounded replacement-ready aggregate as `cutover-ready` while rejecting explicit `--apple-bundle`, explicit `--codex-path`, and `--allow-fork-codex`. The successful run resolved the Apple workflow bundle through `$HOME/.codex-fork plugin cache`, resolved Codex from `PATH` to `/opt/homebrew/Caskroom/codex/0.142.2/codex-aarch64-apple-darwin`, reported `codex-cli 0.142.2`, printed fallback steps, and completed graph, router matrix, tool-plane, Apple memory MCP, Apple-docs CLI, XcodeBuildMCP CLI build/install/launch, and read-only XcodeBuildMCP discovery. Persisted evidence included tool-plane session `conv_43ac1aa5b2b54c6c9481e19f487b56e8`/call `call_s1JJto0zLnIntw6SWuOVVBIP`, memory session `conv_339991bb4daf457f9641c74087ba50e4`/call `call_X1378jE22OgPHISMZqrQnoEc`, Apple-docs session `conv_84b4d6ad9dc24d54a5af699a423361d2`/call `call_wOIBY2DurAKNFAOizWVMZ2K0` with timestamp `2026-06-27T23:48:47.569Z`, XcodeBuildMCP CLI run session `conv_516d0163660449f9bb26a89565f8a992`/call `call_qAavmde4rpb8om5WSu2QEYe2`, and read-only Xcode discovery session `conv_82c10dfceea1443abcabf22d23a8e9d6`/call `call_T6mZb5QP9aJnmWMTkokcWKLG`. An earlier `--live-proof-timeout 420` attempt timed out once at the final read-only Xcode discovery surface after preceding surfaces passed; a standalone discovery rerun then passed in 165.2s, and the full 600-second default-path rerun passed. This proves the current-host default lookup and fallback contract, not clean `CODEX_HOME` auth onboarding, cross-machine portability, or any actual mutation of launcher defaults. |
| Pinned stock-Codex provisioning | `replacement-ready` for source-binary provisioning into a deterministic Omnigent-owned cache layout | `scripts/provision_stock_codex.py` provisions a stock Codex binary from `PATH` or `--source-binary` into `<cache-root>/<version>/codex`, records `manifest.json` provenance with source path, source realpath, version, SHA-256, platform, install time, and `OMNIGENT_STOCK_CODEX_PATH`, rejects `.codex-fork` sources by default, and fails closed when an existing payload is stale unless `--force` is explicit. `uvx --from . python scripts/prove_stock_codex_replacement.py --proof pinned-codex-provision` proved the isolated temp-cache path against stock Codex `0.142.2`, source `/opt/homebrew/Caskroom/codex/0.142.2/codex-aarch64-apple-darwin`, SHA-256 `31ad44ac440cd7a6dd907c773817800db9c9a7e9c13d3bab7309319e2cd08fa9`, and verified Omnigent resolves the provisioned binary through `OMNIGENT_STOCK_CODEX_PATH` instead of ambient `codex` lookup. This proves the pinned local/downloaded-binary install contract, not an official remote download/update channel, clean-auth onboarding, cross-machine portability, persistent launcher activation, or production-default mutation. |
| Stock-Codex channel manifest provisioning | `replacement-ready` for a local/file-backed update-channel contract | `scripts/provision_stock_codex.py` accepts a mutually exclusive `--channel-manifest` path whose `kind: omnigent-stock-codex-channel` manifest selects an artifact by `latest`, `--channel-version`, and platform, then stages a local path or `file://` artifact, verifies SHA-256 and `codex --version`, installs it into the deterministic `codex-stock/<version>/codex` cache, and records `sourceKind: channel`, channel manifest path, and channel artifact provenance in the installed payload manifest. `uvx --from . python scripts/prove_stock_codex_replacement.py --proof stock-codex-channel` proved this through a temporary local channel manifest and cache against stock Codex `0.142.2`, source `/Users/joshuakaunert/.local/omnigent/codex-stock/0.142.2/codex`, SHA-256 `31ad44ac440cd7a6dd907c773817800db9c9a7e9c13d3bab7309319e2cd08fa9`, `sourceKind=channel`, and `OMNIGENT_STOCK_CODEX_PATH` resolver selection of the channel-provisioned payload. This proves the manifest-driven staging/update primitive for local artifacts; remote transport is covered by the separate Homebrew remote-channel gate. |
| Stock-Codex Homebrew/GitHub remote channel provisioning | `replacement-ready` for temporary official cask metadata download and archive extraction | `scripts/provision_stock_codex.py` now supports opt-in remote channel artifacts via `--allow-remote-channel-download`, verifies the downloaded artifact SHA-256 before materialization, supports `archiveFormat: tar.gz` with a declared `archiveExecutable`, extracts only a safe matching file into a staged `codex` binary, verifies `codex --version`, installs the binary with channel provenance, and records the remote source URL in the installed payload manifest. `uvx --from . python scripts/prove_stock_codex_replacement.py --proof stock-codex-homebrew-remote-channel` read `HOMEBREW_NO_AUTO_UPDATE=1 brew info --cask --json=v2 codex`, required `homepage=https://github.com/openai/codex`, required an `https://github.com/openai/codex/releases/download/...tar.gz` URL, downloaded `https://github.com/openai/codex/releases/download/rust-v0.142.2/codex-aarch64-apple-darwin.tar.gz`, verified cask archive SHA-256 `264c15a63146176db0314c54728437c97b1121bb2617c426c06925d62b4454b3`, extracted `codex-aarch64-apple-darwin`, verified `codex-cli 0.142.2`, installed a temporary payload with binary SHA-256 `31ad44ac440cd7a6dd907c773817800db9c9a7e9c13d3bab7309319e2cd08fa9`, and proved Omnigent resolver selection through `OMNIGENT_STOCK_CODEX_PATH`. This proves Homebrew cask metadata plus OpenAI GitHub release archive download, SHA verification, safe extraction, version verification, temporary installation, and resolver selection; it does not prove independent signature/notarization policy, automatic update scheduling, persistent installation, clean-auth onboarding, cross-machine portability, or app-bundle launcher mutation. |
| Clean Codex-auth onboarding boundary | `replacement-ready` for local auth-source classification and stock-home separation | `scripts/prove_stock_codex_replacement.py --proof clean-auth-onboarding` now resolves stock Codex through the managed default, prefers stock `~/.codex/auth.json` when the parent Codex app process inherits `CODEX_HOME=/Users/joshuakaunert/.codex-fork`, verifies the current stock auth source is locally available without printing credential material, then runs an isolated clean `HOME` plus clean `CODEX_HOME` and proves it reports `needs-auth` rather than falling back to the Codex fork. The same proof writes a synthetic temporary API-key-shaped `auth.json`, verifies the classifier recognizes it as available, and removes the temporary profile. The current green run used stock Codex `0.142.2`, stock auth path `/Users/joshuakaunert/.codex/auth.json`, `clean_auth_real_auth_source=stock-default-home`, `clean_auth_clean_unavailable_reason=needs-auth`, and `clean_auth_synthetic_available_reason=None`. This proves the local onboarding boundary, credential-source separation, and failure classification; it does not automate `codex login`, prove browser/device auth UX, validate token freshness against OpenAI servers, package credentials for another machine, or run a live model call under a newly authenticated clean profile. |
| Temporary macOS app-bundle entrypoint rehearsal | `replacement-ready` for a non-installed `.app` launcher shape | `scripts/prove_stock_codex_replacement.py --proof app-bundle-entrypoint` creates a temporary `Omnigent Codex.app` bundle with a generated `Contents/Info.plist` and executable `Contents/MacOS/omnigent-codex`, validates the plist keys, directly runs the executable probe, and verifies the entrypoint exports `OMNIGENT_STOCK_CODEX_PATH=<stock codex>` before delegating to `uvx --from <repo> omnigent codex`. The current green run used stock Codex `0.142.2`, bundle identifier `ai.omnigent.codex`, executable `omnigent-codex`, and a temporary app bundle that was removed after proof. This proves the user-facing app-entrypoint shape without mutating the stock Codex app, `/Applications`, LaunchServices, Dock/Finder defaults, shell profiles, or persistent launcher state; it does not prove signing, notarization, packaging, Sparkle/update behavior, or production app installation. |
| Isolated Codex launcher activation rehearsal | `replacement-ready` for temporary PATH shadowing, pinned stock-Codex delegation, no-recursion lookup, and rollback | `scripts/prove_stock_codex_replacement.py --proof launcher-activation` creates a temporary versioned pinned target under `omnigent/codex-stock/<version>/codex` by copying the current stock Codex binary, creates a temporary `codex` shim, prepends only that temp shim directory to `PATH` inside the proof process, and proves `codex` resolves to the shim during activation. The shim exports `OMNIGENT_STOCK_CODEX_PATH=<pinned target>` before delegation, and Omnigent's central Codex resolver selects that pinned binary instead of the shadowed `codex` command. The proof still verifies the sanitized PATH no longer points at the shim and can resolve the original stock Codex at `/opt/homebrew/bin/codex`, whose realpath was `/opt/homebrew/Caskroom/codex/0.142.2/codex-aarch64-apple-darwin`; it also verifies the delegate shape `/Users/joshuakaunert/.local/bin/uvx --from /Users/joshuakaunert/Developer/HarnessEngineering/omnigent-upstream-audit omnigent codex`. After the scoped activation, `PATH` lookup restores to `/opt/homebrew/bin/codex`. This proves a rollback-first launcher shape can avoid recursive `codex` lookup and can target a managed pinned stock-Codex binary, not a persistent shell alias, app launcher, production-default mutation, persistent provisioner execution, remote downloader/update channel, or live Codex TUI launch. |
| Persistent Omnigent `codex` launcher/default | `replacement-ready` for the current-host Homebrew-bin default with rollback | `scripts/install_omnigent_codex_launcher.py` installs a managed launcher at the selected `codex` path, writes a manifest, preserves `codex --version` by delegating it to the pinned stock binary, probes with `--omnigent-launcher-probe`, exports `OMNIGENT_STOCK_CODEX_PATH` before normal delegation to `uvx --from <repo> omnigent codex`, backs up an existing unmanaged target, and uninstalls only when the target carries the Omnigent marker. `omnigent.inner.codex_executor._find_codex_cli()` detects the managed launcher marker and manifest so inner Omnigent sessions resolve to the pinned stock binary instead of recursing into the launcher. On 2026-06-28, `/opt/homebrew/bin/codex` was replaced by the managed launcher, the original Homebrew symlink was preserved at `/opt/homebrew/bin/codex.omnigent-backup-20260628T091032Z`, `codex --version` returned `codex-cli 0.142.2`, `codex --omnigent-launcher-probe` returned `OMNIGENT_CODEX_PERSISTENT_LAUNCHER_OK`, and `scripts/prove_stock_codex_replacement.py --proof graph --live-proof-timeout 180` with no explicit `--codex-path` resolved to `/Users/joshuakaunert/.local/omnigent/codex-stock/0.142.2/codex` and passed in 33.3s after an actual rollback/reinstall cycle. Rollback command: `uvx --from /Users/joshuakaunert/Developer/HarnessEngineering/omnigent-upstream-audit python /Users/joshuakaunert/Developer/HarnessEngineering/omnigent-upstream-audit/scripts/install_omnigent_codex_launcher.py --uninstall --launcher-path /opt/homebrew/bin/codex --manifest-path /Users/joshuakaunert/.local/omnigent/launchers/codex.json`. This proves current-host default mutation and rollback execution, not a remote download/update channel, clean-auth onboarding, cross-machine portability, or app-bundle launcher mutation. |

This proves the scoped carry-parity claims above plus current-host clean-profile
and default-path rehearsals, isolated pinned stock-Codex provisioning, isolated
pinned launcher activation, and current-host persistent `codex` default
activation plus temporary Homebrew/GitHub remote channel download and the local
clean-auth onboarding boundary plus temporary macOS app-bundle entrypoint
rehearsal. Cross-machine portability, persistent app-bundle installation,
LaunchServices/Dock/Finder default behavior, persistent update scheduling,
independent signature/notarization policy, and automated browser/device login
UX remain separate decisions.

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

Live stock-Codex router-selection matrix proof:

```bash
uvx --from . python scripts/prove_stock_codex_replacement.py \
  --proof router-matrix \
  --codex-path /opt/homebrew/bin/codex \
  --live-proof-timeout 420
```

Runtime diagnostic and provider guard proof:

```bash
uvx --from '.[dev]' pytest \
  tests/runtime/harnesses/test_executor_adapter.py::test_executor_error_after_tool_request_includes_progress_diagnostic \
  tests/runtime/harnesses/test_executor_adapter.py::test_executor_error_terminates_with_response_failed \
  tests/runtime/test_provider_spawn_env.py::test_codex_allows_http_provider_base_url \
  tests/runtime/test_provider_spawn_env.py::test_codex_rejects_non_http_provider_base_url \
  tests/runtime/test_provider_spawn_env.py::test_codex_uses_openai_global_default
```

Disabled-goal read tolerance proof:

```bash
uvx --from '.[dev]' pytest \
  tests/runner/test_codex_goal_runner.py::test_codex_goal_runner_get_returns_none_when_stock_codex_goals_are_disabled \
  tests/runner/test_codex_goal_runner.py::test_codex_goal_runner_set_keeps_disabled_goals_as_error
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

Apple XcodeBuildMCP simulator runtime logs CLI adapter proof:

```bash
DEVELOPER_DIR=/Applications/Xcode-27.0.0-Beta.2.app/Contents/Developer \
uvx --from . python scripts/prove_stock_codex_replacement.py \
  --proof apple-xcodebuild-cli-runtime-logs \
  --codex-path /opt/homebrew/bin/codex \
  --live-proof-timeout 480
```

Apple XcodeBuildMCP type-text CLI adapter proof with the provisioned patched AXe
binary:

```bash
AXE_PATH="$(
  DEVELOPER_DIR=/Applications/Xcode-27.0.0-Beta.2.app/Contents/Developer \
  uvx --from . python scripts/provision_xcode27_axe.py \
    --print-path
)"

DEVELOPER_DIR=/Applications/Xcode-27.0.0-Beta.2.app/Contents/Developer \
uvx --from . python scripts/prove_stock_codex_replacement.py \
  --proof apple-xcodebuild-cli-type-text \
  --codex-path /opt/homebrew/bin/codex \
  --live-proof-timeout 480 \
  --xcodebuildmcp-axe-path "$AXE_PATH"
```

Apple XcodeBuildMCP tap CLI adapter proof with the provisioned patched AXe
binary:

```bash
AXE_PATH="$(
  DEVELOPER_DIR=/Applications/Xcode-27.0.0-Beta.2.app/Contents/Developer \
  uvx --from . python scripts/provision_xcode27_axe.py \
    --print-path
)"

DEVELOPER_DIR=/Applications/Xcode-27.0.0-Beta.2.app/Contents/Developer \
uvx --from . python scripts/prove_stock_codex_replacement.py \
  --proof apple-xcodebuild-cli-tap \
  --codex-path /opt/homebrew/bin/codex \
  --live-proof-timeout 480 \
  --xcodebuildmcp-axe-path "$AXE_PATH"
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

Representative Apple workflow smoke proof:

```bash
uvx --from . python scripts/prove_stock_codex_replacement.py \
  --proof apple-workflow-smoke \
  --codex-path /opt/homebrew/bin/codex \
  --live-proof-timeout 240
```

Cutover-ready aggregate proof:

```bash
uvx --from . python scripts/prove_stock_codex_replacement.py \
  --proof cutover-ready \
  --codex-path /opt/homebrew/bin/codex \
  --live-proof-timeout 420
```

The `cutover-ready` proof is the bounded aggregate for the current replacement
track. It runs only replacement-ready surfaces: graph, router-selection matrix,
dynamic tool plane, Apple memory MCP, Apple-docs CLI adapter, XcodeBuildMCP
read-only discovery, and XcodeBuildMCP CLI build/install/launch. It
intentionally excludes known-blocked MCP Sosumi and MCP build/run launch paths,
as well as the heavier optional UI-automation slices that remain covered by
their standalone proof commands.

Default-path cutover rehearsal:

```bash
uvx --from . python scripts/prove_stock_codex_replacement.py \
  --proof default-path-cutover \
  --live-proof-timeout 600
```

The `default-path-cutover` proof runs the same bounded replacement-ready
aggregate as `cutover-ready`, but it fails closed if `--apple-bundle`,
`--codex-path`, or `--allow-fork-codex` are supplied. It must resolve the Apple
workflow bundle through the ambient default lookup path and resolve stock Codex
from `PATH`. The proof prints fallback steps and does not mutate `PATH`,
`CODEX_HOME`, Xcode selection, the Codex fork, or launcher defaults.

Pinned stock-Codex provision rehearsal:

```bash
uvx --from . python scripts/prove_stock_codex_replacement.py \
  --proof pinned-codex-provision
```

The `pinned-codex-provision` proof fails closed if `--apple-bundle` or
`--allow-fork-codex` are supplied. It resolves stock Codex from `PATH`, or from
`--codex-path` when testing a specific downloaded binary, provisions that binary
into a temporary deterministic `codex-stock/<version>/codex` cache, verifies
the source SHA-256, provisioned binary, manifest provenance, and
`OMNIGENT_STOCK_CODEX_PATH` resolver behavior, then removes the temporary cache.
It does not mutate persistent launcher defaults.

Stock-Codex channel manifest rehearsal:

```bash
uvx --from . python scripts/prove_stock_codex_replacement.py \
  --proof stock-codex-channel
```

The `stock-codex-channel` proof fails closed if `--apple-bundle` or
`--allow-fork-codex` are supplied. It writes a temporary
`kind: omnigent-stock-codex-channel` manifest for a local stock Codex artifact,
selects the artifact through the channel path, verifies SHA-256 and
`codex --version`, stages it in a temporary directory, provisions it into a
temporary `codex-stock/<version>/codex` cache with `sourceKind: channel`
provenance, verifies the installed payload manifest, then proves
`OMNIGENT_STOCK_CODEX_PATH` resolves through Omnigent to the channel-provisioned
binary. It stays local-file-only; the remote download path is covered by the
separate Homebrew remote-channel proof.

Homebrew/OpenAI GitHub remote channel rehearsal:

```bash
uvx --from . python scripts/prove_stock_codex_replacement.py \
  --proof stock-codex-homebrew-remote-channel
```

The `stock-codex-homebrew-remote-channel` proof fails closed if
`--apple-bundle`, `--codex-path`, or `--allow-fork-codex` are supplied. It reads
`brew info --cask --json=v2 codex` with `HOMEBREW_NO_AUTO_UPDATE=1`, requires
the cask homepage and archive URL to point at `github.com/openai/codex`, writes
a temporary channel manifest for the cask archive, downloads it only through the
provisioner's explicit `--allow-remote-channel-download` flag, verifies the
cask SHA-256 before extraction, extracts the declared archive executable,
verifies `codex --version`, installs it into a temporary
`codex-stock/<version>/codex` cache with `sourceKind: channel` provenance, and
proves `OMNIGENT_STOCK_CODEX_PATH` resolver selection. It proves the
Homebrew-cask-plus-OpenAI-GitHub-release trust path, not independent
signature/notarization policy, automatic update scheduling, persistent
installation, clean-auth onboarding, cross-machine portability, or app-bundle
launcher mutation.

Clean Codex-auth onboarding boundary:

```bash
uvx --from . python scripts/prove_stock_codex_replacement.py \
  --proof clean-auth-onboarding
```

The `clean-auth-onboarding` proof fails closed if `--apple-bundle` or
`--allow-fork-codex` are supplied. It resolves the stock Codex binary, uses the
stock `~/.codex/auth.json` source when the current parent process has inherited
`.codex-fork` as `CODEX_HOME`, verifies that source is locally available without
printing credentials, then runs two isolated temporary profiles: one clean
`HOME`/`CODEX_HOME` that must report `needs-auth`, and one synthetic populated
`auth.json` that must report available. It does not run `codex login`, open a
browser, validate token freshness with OpenAI, copy credentials to another
machine, or run a live model call under a newly authenticated profile.

Persistent source-binary provisioning is available only when an operator
explicitly decides to install a pinned binary:

```bash
uvx --from . python scripts/provision_stock_codex.py \
  --source-binary /path/to/codex \
  --expected-sha256 <sha256> \
  --json
```

The default persistent cache root is `~/.local/omnigent/codex-stock`. This
installs the managed binary and manifest only; pointing a real launcher, shell
alias, app, or production default at it is a separate cutover mutation.

Persistent Omnigent `codex` launcher install:

```bash
uvx --from . python scripts/install_omnigent_codex_launcher.py \
  --install \
  --launcher-path /opt/homebrew/bin/codex \
  --pinned-codex-path /Users/joshuakaunert/.local/omnigent/codex-stock/0.142.2/codex \
  --backup-existing \
  --require-path-selected \
  --json
```

Rollback:

```bash
uvx --from /Users/joshuakaunert/Developer/HarnessEngineering/omnigent-upstream-audit \
  python /Users/joshuakaunert/Developer/HarnessEngineering/omnigent-upstream-audit/scripts/install_omnigent_codex_launcher.py \
  --uninstall \
  --launcher-path /opt/homebrew/bin/codex \
  --manifest-path /Users/joshuakaunert/.local/omnigent/launchers/codex.json
```

The installer refuses to overwrite unmanaged targets unless `--backup-existing`
is supplied. The uninstall path refuses to remove unmanaged launchers and
restores the recorded backup if one exists.

Managed launcher read-only doctor:

```bash
uvx --from . python scripts/doctor_omnigent_codex_launcher.py --json
```

The doctor does not repair or rewrite host state. It checks that the selected
`codex` path is the managed launcher, the launcher marker and embedded manifest
pointer are coherent, the manifest records the expected launcher, repo, `uvx`,
pinned Codex, environment, and backup paths, the pinned stock binary reports the
manifested version, `codex --version` delegates to that pinned binary, the
launcher probe reports the pinned environment and delegate shape, and
Omnigent's inner resolver maps the managed launcher back to the pinned stock
Codex payload.

Isolated Codex launcher activation rehearsal:

```bash
uvx --from . python scripts/prove_stock_codex_replacement.py \
  --proof launcher-activation
```

The `launcher-activation` proof fails closed if `--apple-bundle`,
`--codex-path`, or `--allow-fork-codex` are supplied. It creates a temporary
versioned pinned stock-Codex target by copying the current stock binary under a
temp `omnigent/codex-stock/<version>/codex` layout, creates a temporary `codex`
shim, prepends only that temp bin directory to `PATH` in the proof process,
exports `OMNIGENT_STOCK_CODEX_PATH=<pinned target>` from the shim, verifies
Omnigent resolves the pinned binary instead of the shadowed `codex`, and then
verifies `PATH` lookup returns to the original stock Codex path. It does not
install a real shim, run the persistent provisioner, download Codex, edit shell
startup files, mutate app launchers, or launch the live Codex TUI.

Temporary macOS app-bundle entrypoint rehearsal:

```bash
uvx --from . python scripts/prove_stock_codex_replacement.py \
  --proof app-bundle-entrypoint
```

The `app-bundle-entrypoint` proof fails closed if `--apple-bundle` or
`--allow-fork-codex` are supplied. It resolves stock Codex from the managed
default or an explicit `--codex-path`, creates a temporary `Omnigent Codex.app`
bundle, writes and validates `Contents/Info.plist`, writes an executable
`Contents/MacOS/omnigent-codex`, runs that executable directly with a probe
argument, and verifies the executable exports
`OMNIGENT_STOCK_CODEX_PATH=<stock codex>` before delegating to
`uvx --from <repo> omnigent codex`. It does not install into `/Applications`,
register LaunchServices, mutate Stock Codex.app, change Dock/Finder defaults,
edit shell startup files, prove signing/notarization, or launch the live Codex
TUI.

Clean-profile cutover-ready rehearsal:

```bash
ROOT="$(mktemp -d /tmp/omnigent-cutover-ready.XXXXXX)"
mkdir -p "$ROOT/home" "$ROOT/tmp" "$ROOT/uv-cache" \
  "$ROOT/work" "$ROOT/xdg-cache" "$ROOT/xdg-config" "$ROOT/xdg-data"

cd "$ROOT/work"
env -i \
  HOME="$ROOT/home" \
  TMPDIR="$ROOT/tmp" \
  UV_CACHE_DIR="$ROOT/uv-cache" \
  XDG_CACHE_HOME="$ROOT/xdg-cache" \
  XDG_CONFIG_HOME="$ROOT/xdg-config" \
  XDG_DATA_HOME="$ROOT/xdg-data" \
  CODEX_HOME="/Users/joshuakaunert/.codex" \
  DEVELOPER_DIR="/Applications/Xcode-27.0.0-Beta.2.app/Contents/Developer" \
  PATH="/Users/joshuakaunert/.local/bin:/nix/var/nix/profiles/default/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin" \
  LANG="en_US.UTF-8" \
  LC_ALL="en_US.UTF-8" \
  PYTHONUNBUFFERED=1 \
  uvx --from /Users/joshuakaunert/Developer/HarnessEngineering/omnigent-upstream-audit \
    python /Users/joshuakaunert/Developer/HarnessEngineering/omnigent-upstream-audit/scripts/prove_stock_codex_replacement.py \
      --proof cutover-ready \
      --apple-bundle /Users/joshuakaunert/.codex-fork/plugins/cache/LocalAppleWorkflow/apple-appdev-workflow/0.1.1 \
      --codex-path /opt/homebrew/bin/codex \
      --live-proof-timeout 420
```

In an isolated `HOME`, the Apple workflow bundle must be supplied explicitly
with `--apple-bundle`; relying on the default `$HOME/.codex-fork` or
`$HOME/.codex` plugin-cache lookup fails correctly because those directories
are intentionally absent. The only preserved profile state in this rehearsal is
`CODEX_HOME=/Users/joshuakaunert/.codex` for stock-Codex authentication.

Legacy diagnostic aggregate proof:

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
surface. In aggregate proof modes, each MCP surface is run with its own
generated Omnigent tools config so one hanging server does not obscure which
replacement surface failed.

Current cutover-ready status on 2026-06-27: the clean-profile
`cutover-ready` proof passed through an installed `uvx --from` Omnigent package
path, outside the repo working directory, with isolated `HOME`, `TMPDIR`,
`UV_CACHE_DIR`, and XDG dirs. Stock Codex resolved from `/opt/homebrew/bin/codex`
to `/opt/homebrew/Caskroom/codex/0.142.2/codex-aarch64-apple-darwin` and
reported `codex-cli 0.142.2`. Static preflight resolved 19 relative files, 13
skill refs, and Apple MCP servers `XcodeBuildMCP`, `memory`, and `sosumi`.
Live proof results:

- `graph` passed in 30.2s with `GRAPH_OK`.
- `router-matrix` passed in 115.4s with sessions
  `conv_54315e89816547a6a68c7229593b16d6`,
  `conv_9189b4b5a7514c88b0bc5177a4d1196d`,
  `conv_dd65baa4da074c42bb9783b87bd7f026`,
  `conv_153f979a70a54331940e8a301af66590`,
  `conv_4b3ef4a458624f2fb87e27019d266937`,
  `conv_0a3858d7f7804f63999f8e8cd661134f`, and
  `conv_d3fba08001bb4570b9b03f44dc0b32fe`.
- `tool-plane` passed in 15.4s with session
  `conv_afaafe9ff68a45109702f47ca594dbf9` and call
  `call_LbcIcR30QNEmyGaJSDaGhSKF`.
- `apple-mcp-memory` passed in 15.1s with session
  `conv_214da46a61f043cd8b5ee99f877c13b3` and call
  `call_fndovF4DaB6Z8bWe2VBnAIXC`.
- `apple-docs-cli` passed in 26.9s with session
  `conv_87e4829c34374418a95456bbd87c929c`, call
  `call_sWsWw5mCK9phKxAsYIVzbTqh`, and timestamp
  `2026-06-27T18:19:45.581Z`.
- `apple-xcodebuild-cli-run` passed in 66.8s with session
  `conv_bfb317d6d75442f7936e761237af3064` and call
  `call_kHpoSE2vf1BbKLQLcYyXoK67`.
- `apple-mcp-xcodebuild` passed in 55.0s with session
  `conv_972d47c6b74d466c91ab0314e71072f0` and call
  `call_VkqaRJESsOML6N6bKFPh2lav`.

The temporary clean-profile tree was 1.3 GB after the run and was removed after
evidence capture. This closes local clean-profile aggregate replacement proof
for the current host, not cross-machine install portability and not a clean
Codex-auth onboarding flow.

Representative Apple workflow smoke status on 2026-06-27: `--proof
apple-workflow-smoke` passed in 47.3s with stock Codex `0.142.2`. The session
`conv_6a8bb2b3fa6c4dc182d79ed961581e13` started with the expected Apple route
block, called `fetch_apple_docs` as `call_YhQNwu4vF4gs4nDZJcTRbNfp`, then called
read-only `XcodeBuildMCP__discover_projs` as
`call_0CgVXm1tP9O2Tcua92bYpovU`. The Apple docs result returned `title: String`,
the Swift `String` source URL, and timestamp `2026-06-27T22:39:20.021Z`; the
XcodeBuildMCP result found `ap-web/ios/Omnigent.xcodeproj`; the model replied
`APPLE_WORKFLOW_SMOKE_OK`. This closes the first representative routed workflow
smoke, not full release/readiness/review parity and not default-path cutover.

Current default-path cutover status on 2026-06-27: `--proof
default-path-cutover --live-proof-timeout 600` passed using ambient default
selection. The run used no `--apple-bundle` and no `--codex-path`; it selected
the Apple workflow bundle from `$HOME/.codex-fork plugin cache`, selected stock
Codex from `PATH`, resolved `/opt/homebrew/Caskroom/codex/0.142.2/codex-aarch64-apple-darwin`,
reported `codex-cli 0.142.2`, and printed fallback steps that preserve the
Codex fork and all carries. Live proof results:

- `graph` passed in 27.4s with `GRAPH_OK`.
- `router-matrix` passed in 139.5s with sessions
  `conv_d30b2de8030445048dadc51dafada15e`,
  `conv_9ae13372fa4541978691fc4e20a62ca1`,
  `conv_9207b789e86f4b058e16d44fdeae25eb`,
  `conv_ea854e8eb1e34bcba1a235bb66c8bb26`,
  `conv_3b74cea696ca470498be73291eff5580`,
  `conv_f25950902dca4d8fb16b3e64acc2a4ec`, and
  `conv_b2b6f45061ba446cbed390071c80357a`.
- `tool-plane` passed in 26.2s with session
  `conv_43ac1aa5b2b54c6c9481e19f487b56e8` and call
  `call_s1JJto0zLnIntw6SWuOVVBIP`.
- `apple-mcp-memory` passed in 19.4s with session
  `conv_339991bb4daf457f9641c74087ba50e4` and call
  `call_X1378jE22OgPHISMZqrQnoEc`.
- `apple-docs-cli` passed in 34.6s with session
  `conv_84b4d6ad9dc24d54a5af699a423361d2`, call
  `call_wOIBY2DurAKNFAOizWVMZ2K0`, and timestamp
  `2026-06-27T23:48:47.569Z`.
- `apple-xcodebuild-cli-run` passed in 70.0s with session
  `conv_516d0163660449f9bb26a89565f8a992` and call
  `call_qAavmde4rpb8om5WSu2QEYe2`.
- `apple-mcp-xcodebuild` passed in 33.8s with session
  `conv_82c10dfceea1443abcabf22d23a8e9d6` and call
  `call_T6mZb5QP9aJnmWMTkokcWKLG`.

An earlier default-path aggregate attempt with `--live-proof-timeout 420` timed
out once at the final `apple-mcp-xcodebuild` surface after the preceding
surfaces passed. A standalone `apple-mcp-xcodebuild` rerun then passed in
165.2s with session `conv_9c2b49240b814805a16dc0b406f23a26` and call
`call_5zS4Ehoowx603hJRfsZx5sXK`; the full default-path rerun with a 600-second
per-step budget passed. This closes current-host default-path rehearsal without
mutating launcher defaults, not clean-auth onboarding or cross-machine cutover.

Current pinned stock-Codex provision status on 2026-06-28: `--proof
pinned-codex-provision` passed without persistent install or launcher mutation.
The run used source
`/opt/homebrew/Caskroom/codex/0.142.2/codex-aarch64-apple-darwin`, reported
`codex-cli 0.142.2`, verified SHA-256
`31ad44ac440cd7a6dd907c773817800db9c9a7e9c13d3bab7309319e2cd08fa9`,
provisioned a temporary cache at
`omnigent-pinned-codex-provision-proof-*/codex-stock/0.142.2/codex`, wrote a
manifest, exported
`OMNIGENT_STOCK_CODEX_PATH=<temporary cache>/codex-stock/0.142.2/codex`, and
proved Omnigent resolved that provisioned binary rather than relying on
ambient `codex` lookup. This closes the local or downloaded source-binary
pinning contract, not an official remote download/update channel or persistent
launcher/default mutation.

Current stock-Codex channel status on 2026-06-30: `--proof
stock-codex-channel` passed without persistent install or launcher mutation.
The run used source
`/Users/joshuakaunert/.local/omnigent/codex-stock/0.142.2/codex`, reported
`codex-cli 0.142.2`, verified SHA-256
`31ad44ac440cd7a6dd907c773817800db9c9a7e9c13d3bab7309319e2cd08fa9`, wrote a
temporary `kind: omnigent-stock-codex-channel` manifest, staged the local
artifact, provisioned a temporary cache at
`omnigent-stock-codex-channel-proof-*/codex-stock/0.142.2/codex`, wrote an
installed payload manifest with `sourceKind: channel` plus channel artifact
provenance, exported
`OMNIGENT_STOCK_CODEX_PATH=<temporary cache>/codex-stock/0.142.2/codex`, and
proved Omnigent resolved that channel-provisioned binary rather than relying on
ambient `codex` lookup. This closes the manifest-driven local/file update
primitive. The production trust-source decision, remote `http(s)` download
transport, signature/notarization checks, and official update metadata source
remain separate gates.

Current persistent pinned stock-Codex payload status on 2026-06-28: the
operator-approved persistent provision gate installed stock Codex `0.142.2`
into
`/Users/joshuakaunert/.local/omnigent/codex-stock/0.142.2/codex` using source
`/opt/homebrew/bin/codex`, source realpath
`/opt/homebrew/Caskroom/codex/0.142.2/codex-aarch64-apple-darwin`, and expected
SHA-256 `31ad44ac440cd7a6dd907c773817800db9c9a7e9c13d3bab7309319e2cd08fa9`.
The persistent manifest at
`/Users/joshuakaunert/.local/omnigent/codex-stock/0.142.2/manifest.json`
records `kind: omnigent-stock-codex`, `version: codex-cli 0.142.2`, source
path, source realpath, SHA-256, platform, install time, and
`OMNIGENT_STOCK_CODEX_PATH`. Validation proved the installed binary reports
`codex-cli 0.142.2`, the installed SHA-256 matches the source, and Omnigent's
resolver selects the persistent payload when
`OMNIGENT_STOCK_CODEX_PATH=/Users/joshuakaunert/.local/omnigent/codex-stock/0.142.2/codex`
is set. A live graph proof using that payload as `--codex-path` then passed in
40.4s through the normal Omnigent `run_prompt()` session/runner path: the
transcript began with the deterministic Apple route block and returned
`GRAPH_OK` after reading the bundled Apple reference. This installed the
managed payload only; it did not mutate shell startup files, launcher defaults,
app bundles, or the ambient `codex` command.

Current persistent Omnigent `codex` launcher status on 2026-06-28: the
operator-approved launcher/default gate replaced `/opt/homebrew/bin/codex`,
which was the first `codex` on `PATH`, with an Omnigent-managed launcher. The
original Homebrew symlink was preserved at
`/opt/homebrew/bin/codex.omnigent-backup-20260628T091032Z`, pointing to
`/opt/homebrew/Caskroom/codex/0.142.2/codex-aarch64-apple-darwin`. The launcher
manifest at `/Users/joshuakaunert/.local/omnigent/launchers/codex.json`
records `kind: omnigent-codex-launcher`, launcher path, backup path, repo root,
`uvx` path, pinned Codex path, pinned Codex version, and
`OMNIGENT_STOCK_CODEX_PATH`. Validation proved `which codex` selects
`/opt/homebrew/bin/codex`, `codex --version` returns `codex-cli 0.142.2`,
`codex --omnigent-launcher-probe` returns
`OMNIGENT_CODEX_PERSISTENT_LAUNCHER_OK`, and Omnigent's inner resolver maps the
managed launcher back to
`/Users/joshuakaunert/.local/omnigent/codex-stock/0.142.2/codex`. The default
graph proof then passed with no explicit `--codex-path`: it reported
`codex_path=/Users/joshuakaunert/.local/omnigent/codex-stock/0.142.2/codex`,
started the normal Omnigent `run_prompt()` session/runner path, emitted the
deterministic Apple route block, and returned `GRAPH_OK` in 33.3s. This closes
the current-host CLI default activation, not app bundle mutation, clean-auth
onboarding, cross-machine portability, or an official remote download/update
channel.

Current rollback/reinstall status on 2026-06-28: the recorded uninstall command
was run against `/opt/homebrew/bin/codex` and
`/Users/joshuakaunert/.local/omnigent/launchers/codex.json`. It removed the
managed launcher, restored `/opt/homebrew/bin/codex` to the original Homebrew
symlink, removed the launcher manifest, and removed the consumed backup path.
Validation after rollback showed `codex --version` still returned
`codex-cli 0.142.2` and Omnigent's inner resolver returned the stock
`/opt/homebrew/bin/codex` path. The managed launcher was then reinstalled with
backup path `/opt/homebrew/bin/codex.omnigent-backup-20260628T091032Z`; probe,
resolver, manifest, and default graph proof all passed after reinstall. This
proves rollback is executable on the current host and that reactivation returns
the host to the managed default.

Current managed-default aggregate status on 2026-06-29:
`scripts/prove_stock_codex_replacement.py --proof default-path-cutover
--live-proof-timeout 600` passed with no explicit `--apple-bundle`, no explicit
`--codex-path`, and the active `/opt/homebrew/bin/codex` Omnigent-managed
launcher selected on `PATH`. The proof resolved Codex to the pinned stock
payload at `/Users/joshuakaunert/.local/omnigent/codex-stock/0.142.2/codex`,
reported `codex-cli 0.142.2`, selected the Apple workflow bundle from
`$HOME/.codex-fork plugin cache`, and printed the default-path fallback steps.
Live proof results:

- `graph` passed in 29.4s with `GRAPH_OK`.
- `router-matrix` passed in 142.4s with sessions
  `conv_7313405b44ae44f88e02edd0abae97e0`,
  `conv_213c8c3de0b5423bbcfed527665a6eda`,
  `conv_14d2e9e042314d3db894de5bb0bcb9da`,
  `conv_1e2224c1e1824d48ba66e99b57c17bf2`,
  `conv_32870ac52562438f861d879e7822cf29`,
  `conv_18eae751720e489bb650af5fad9e300d`, and
  `conv_6884711762f84878b01671650a368fc8`.
- `tool-plane` passed in 29.5s with session
  `conv_bdbb7e7ecaf5475187778d0bf49cb256` and call
  `call_nvBrXWjPJdpDobcOWpUN2daG`.
- `apple-mcp-memory` passed in 23.0s with session
  `conv_19a436d1c5d1455ab03681d0cf73a718` and call
  `call_uldfV7n4T8m7upwGacoCeORL`.
- `apple-docs-cli` passed in 36.8s with session
  `conv_35e838abc77944e7b7334d3ab7bf1df9`, call
  `call_nG8NOtXLHfRRid0Nx0GE8BIs`, and timestamp
  `2026-06-29T21:12:27.412Z`.
- `apple-xcodebuild-cli-run` passed in 76.3s with session
  `conv_a4b8fc1553ff4687857a4ab4c389d895` and call
  `call_HfxWtv0B2FHS4rQ45CknJtQf`.
- `apple-mcp-xcodebuild` passed in 70.0s with session
  `conv_b46a5fc618d84925b91fb60cada9540d` and call
  `call_NFWibtAzzE5FYnJ4jem89SqV`.

This closes the broad current-host managed-default aggregate: ambient bundle
lookup, managed launcher resolution, graph, router-selection matrix, dynamic
tool plane, Apple memory MCP, Apple-docs CLI adapter, XcodeBuildMCP CLI
build/install/launch, and read-only XcodeBuildMCP discovery all passed through
the installed Omnigent `codex` default. It does not prove app-bundle launcher
mutation, clean first-run Codex auth onboarding, cross-machine portability, or
an official remote download/update channel; the temporary app-bundle entrypoint
rehearsal is tracked as its own non-mutating proof.

Current managed launcher doctor status on 2026-06-30:
`uvx --from . python scripts/doctor_omnigent_codex_launcher.py --json` passed
against the live host default. It confirmed `codex` resolves to
`/opt/homebrew/bin/codex`, that path is still the selected Omnigent-managed
launcher, the launcher points at
`/Users/joshuakaunert/.local/omnigent/launchers/codex.json`, the manifest
records `kind: omnigent-codex-launcher`, the pinned stock Codex payload is
`/Users/joshuakaunert/.local/omnigent/codex-stock/0.142.2/codex`, the pinned
version is `codex-cli 0.142.2`, the preserved backup exists at
`/opt/homebrew/bin/codex.omnigent-backup-20260628T091032Z`, the launcher probe
returned `OMNIGENT_CODEX_PERSISTENT_LAUNCHER_OK`, `codex --version` returned
`codex-cli 0.142.2`, and Omnigent's resolver mapped the launcher to the pinned
stock payload. This is the cheap post-update drift check for the managed CLI
default; it does not mutate launcher state or prove app bundle launchers,
clean-auth onboarding, cross-machine portability, or an official remote
download/update channel.

Current isolated pinned launcher activation status on 2026-06-28: `--proof
launcher-activation` passed without persistent filesystem or launcher mutation.
The run used baseline `PATH` lookup `/opt/homebrew/bin/codex`, realpath
`/opt/homebrew/Caskroom/codex/0.142.2/codex-aarch64-apple-darwin`, a temporary
pinned target under `omnigent-codex-launcher-proof-*/omnigent/codex-stock/0.142.2/codex`,
a temporary shim path under `omnigent-codex-launcher-proof-*/bin/codex`, and
`uvx` at `/Users/joshuakaunert/.local/bin/uvx`. The shim probe emitted
`OMNIGENT_CODEX_LAUNCHER_ACTIVATION_OK`, exported
`OMNIGENT_STOCK_CODEX_PATH=<pinned target>`, proved Omnigent resolved the
pinned target, confirmed sanitized PATH still resolves the original stock
Codex at `/opt/homebrew/bin/codex` rather than the shim, and reported delegate
preview `/Users/joshuakaunert/.local/bin/uvx --from /Users/joshuakaunert/Developer/HarnessEngineering/omnigent-upstream-audit omnigent codex`.
After the scoped proof, `codex` lookup restored to `/opt/homebrew/bin/codex`.
This closes the no-recursion, pinned-target, and rollback rehearsal for a
launcher shim, not actual persistent launcher activation or a remote
download/update channel.

Legacy aggregate status on 2026-06-25: `graph`, `tool-plane`, and
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
positive dimensions. The bounded simulator runtime-log adapter proof passed on
2026-06-27: stock Codex invoked `xcodebuildmcp_simulator_runtime_logs` through
Omnigent `dynamicTools`, and the CLI returned successful build, launch,
runtime-log, and OS-log statuses with compact log excerpts. The semantic
`snapshot-ui` surface is now separately proven through a generated CLI adapter
when the proof supplies an explicit patched AXe binary. That proof uses
command-scoped `DEVELOPER_DIR` and `OMNIGENT_XCODEBUILDMCP_AXE_PATH`; it does
not require global `xcode-select` mutation, Xcode bundle mutation, or Homebrew
Cellar mutation. The bounded type-text interaction proof also passed on
2026-06-27 on the upstream audit branch: stock Codex invoked
`xcodebuildmcp_simulator_type_text` through Omnigent `dynamicTools`, the tool
selected the semantic text-field ref, typed
`http://localhost:6767/gesture-proof`, and verified that value through
`wait-for-ui`. The bounded tap interaction proof then passed on 2026-06-27:
stock Codex invoked `xcodebuildmcp_simulator_tap` through Omnigent
`dynamicTools`, the tool reset persisted simulator app state with
`xcrun simctl uninstall`, typed the proof URL, tapped the discovered `Connect`
button, and verified the settled post-tap state normalized back to
`http://localhost:6767`.

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

2. XcodeBuildMCP gesture expansion boundary
   - Add the next narrow UI interaction proof only after preserving the current
     screenshot, runtime-log, semantic snapshot, type-text, and tap evidence.
     Keep drag, multi-step navigation, debugger attach, device logs, and
     streaming log follow as separate replacement surfaces.

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

6. Clean Codex-auth onboarding
   - The clean host-profile proof is green while preserving
     `CODEX_HOME=/Users/joshuakaunert/.codex` for stock-Codex authentication.
     The `clean-auth-onboarding` proof is also green for the local onboarding
     boundary: a clean temporary `HOME`/`CODEX_HOME` reports `needs-auth`, a
     populated temporary `auth.json` reports available, and inherited
     `.codex-fork` `CODEX_HOME` is ignored in favor of stock `~/.codex` for the
     replacement track. A different gate is still needed if the product requires
     automated browser/device login UX, token freshness validation, or
     credential packaging for another machine.

7. Broader end-to-end Apple workflow smoke
   - The first representative routed workflow is green for Apple docs plus
     read-only Xcode project discovery in one stock-Codex session. Broaden this
     only if product cutover requires a higher-fidelity release-readiness,
     branch-diff review, or multi-tool Apple workflow path.

8. Persistent pinned launcher/default mutation decision
   - The default-path rehearsal is green for current-host ambient bundle lookup
     and `PATH` stock-Codex resolution. The pinned provisioner is green for
     local or downloaded source-binary pinning into an Omnigent-owned cache,
     and the current host now has a persistent managed Codex payload installed
     at `~/.local/omnigent/codex-stock/0.142.2/codex`. The isolated launcher
     activation proof is also green for temporary PATH shadowing, pinned
     stock-Codex selection through
     `OMNIGENT_STOCK_CODEX_PATH`, delegation through
     `uvx --from <repo> omnigent codex`, and rollback. The current host now also
     has `/opt/homebrew/bin/codex` pointed at the managed Omnigent launcher with
     rollback metadata, the full managed-default aggregate is green through
     that launcher, and the read-only launcher doctor is green as the current
     post-update drift check. The file-backed stock-Codex channel manifest
     proof is also green for manifest selection, staging, SHA/version
     verification, channel-provenance install, and resolver selection. The
     Homebrew/GitHub remote-channel proof is also green for temporary official
     cask metadata download and archive extraction. The temporary
     `app-bundle-entrypoint` proof is green for a non-installed
     `Omnigent Codex.app` bundle shape that delegates through
     `uvx --from <repo> omnigent codex` with an explicit stock-Codex pin.
     Remaining product decisions are whether that temporary app-bundle shape
     should become a signed/notarized persistent app install, whether it should
     register with LaunchServices or Dock/Finder defaults, whether the temporary
     remote-channel proof should become a persistent updater/install command,
     and what independent signature or notarization policy is required.

## Non-Actions

The following are intentionally out of scope for this track:

- Deleting Codex-fork carries.
- Merging Omnigent adapters into the Codex fork.
- Treating one green proof as full replacement readiness.
- Publishing the Omnigent spike upstream before it serves the internal
  replacement goal.
- Rewriting current production workflow docs to point at Omnigent before a
  cutover decision exists.
