# Stock Codex Replacement Contract

This document tracks the Omnigent development path for replacing local
Codex-fork carries with a stock-Codex wrapper. It is not an upstream
contribution plan and it is not an instruction to mutate the existing Codex
fork.

## Goal

Prove that Omnigent can wrap an unmodified Codex surface and provide the
workflow behaviors that previously required fork-local Codex carries.

The expected end state is a dual-mode distribution:

- Primary mode: an independent Omnigent runtime/entrypoint that uses stock
  Codex as its engine and provides the replacement harness behavior itself.
- Compatibility mode: a stock Codex Electron or CLI entrypoint that can still
  use the same workflow bundle through an installed Omnigent meta-harness
  bridge.

Once the required replacement surfaces are proven in either mode, operational
cutover can choose that path instead of continuing to maintain the Codex fork.
The Codex fork remains the proven production fallback until that explicit
cutover decision is made.

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

## Distribution Modes

The plugin bundle and the Omnigent harness are separate deliverables. Installing
the Apple workflow plugin into stock Codex does not, by itself, install
Omnigent's deterministic routing, generated adapter tools, launcher resolver,
auth-source policy, provider guards, or harness diagnostics.

### Primary: Omnigent Runtime

In primary mode, users launch Omnigent through the installed app or managed CLI.
Omnigent installs or resolves the Apple workflow bundle, provisions or pins a
stock Codex engine, owns the policy/adapter layer, and launches stock Codex
under that harness boundary. This is the preferred replacement path for
retiring Codex-fork upkeep because the carry-replacement behavior lives above
stock Codex and does not require patching Codex itself.

Proven pieces for this mode already include the persistent managed `codex`
launcher, pinned stock-Codex payload resolution, temporary macOS app-bundle
entrypoint shape, clean-auth source classification, router-selection evidence,
dynamic tool adapters, and the bounded Apple workflow proofs below.

### Secondary: Stock Codex Compatibility

In compatibility mode, users can still open stock Codex Electron or run the
stock Codex CLI, but parity requires more than plugin installation. The
installer must bundle the Apple workflow plugin with an Omnigent meta-harness
sidecar or equivalent bridge, then configure stock Codex to use that bridge for
the behaviors Omnigent owns: deterministic route evidence, generated
dynamic-tool adapters, MCP conversion or containment, stock-Codex pinning,
auth-source policy, and diagnostics.

This compatibility path is a first-class product target, but it has two
different evidence levels. A raw stock Codex plugin-only install remains lower
parity unless the stock Codex surface exposes enough hooks for the Omnigent
bridge to run before model output and to own the required tool/session policy.
An Omnigent-owned wrapper around stock Codex can satisfy the pre-visible-output
route boundary, but that means the wrapper is the compatibility entrypoint, not
an unwrapped stock Codex launch.

### Packaging Rule

Any user-facing package should make the selected mode explicit:

- `omnigent-runtime`: installs Omnigent as the app/CLI entrypoint and uses stock
  Codex underneath.
- `stock-codex-compat`: installs stock Codex compatibility assets: the plugin
  bundle plus the Omnigent meta-harness bridge needed for parity.

Both packages may share the same workflow bundle and stock-Codex provisioner,
but their evidence gates stay separate. A green primary-mode proof does not
automatically prove stock Codex Electron/CLI compatibility, and a green
plugin-only install does not prove carry replacement.

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
| XcodeBuildMCP semantic UI snapshot through a CLI adapter | `replacement-ready` for bounded Xcode 27 Beta 2 simulator hierarchy snapshots with a source-provisioned upstream AXe path | `omnigent.adapters.xcodebuild_cli.XcodeBuildCliAdapterPolicy` installs a generated `xcodebuildmcp_simulator_snapshot_ui` dynamic tool that strips ambient `XCODEBUILDMCP_AXE_PATH`, maps only explicit `OMNIGENT_XCODEBUILDMCP_AXE_PATH`, uses an isolated XcodeBuildMCP socket, and validates a non-empty `runtime-snapshot`. The AXe source pin now defaults to upstream `cameroncooke/AXe@51cfaf7552512224c5e9e6a01e059d3986d544bc`, after [cameroncooke/AXe#60](https://github.com/cameroncooke/AXe/pull/60) landed as `ee92b93` for Xcode 27 `SharedFrameworks` lookup and `51cfaf7` for the IDB deployment-target patch. `scripts/provision_xcode27_axe.py --force --json` built and verified the upstream payload under `~/.cache/omnigent/axe/payloads/51cfaf7552512224c5e9e6a01e059d3986d544bc`. `scripts/prove_stock_codex_replacement.py --proof apple-xcodebuild-cli-snapshot-ui --codex-path /Users/joshuakaunert/.local/omnigent/codex-stock/0.142.5/codex --xcodebuildmcp-axe-path ~/.cache/omnigent/axe/payloads/51cfaf7552512224c5e9e6a01e059d3986d544bc/axe` then proved stock Codex `0.142.5` invoked the generated tool through Omnigent `dynamicTools`; persisted session `conv_f1d8eacf14d44482beea756d64473916` included function call `call_rp3b5TNKpozMNdAPrk1j86Io`, output containing `"snapshotStatus": "SUCCEEDED"`, `"count": 16`, `screenHash: "0d3ho2y"`, and actionable refs `e14|typeText|text-field||http://localhost:6767|` and `e15|tap|button|Connect||`; the model replied `XCODEBUILDMCP_CLI_SNAPSHOT_UI_OK`. This proves bounded semantic UI hierarchy capture through the CLI adapter plus source-provisioned upstream AXe on this host; it does not prove gestures, logs, device execution, a different machine, bundled-XcodeBuildMCP AXe parity, or Xcode IDE bridge tools. |
| XcodeBuildMCP type-text interaction through a CLI adapter | `replacement-ready` for bounded iOS simulator text entry into a discovered text-field ref | `omnigent.adapters.xcodebuild_cli.XcodeBuildCliAdapterPolicy` now installs a generated `xcodebuildmcp_simulator_type_text` Python dynamic tool for the first UI interaction boundary. The tool strips ambient `XCODEBUILDMCP_AXE_PATH`, maps an explicit `OMNIGENT_XCODEBUILDMCP_AXE_PATH`, uses a per-call isolated XcodeBuildMCP socket, runs `xcodebuildmcp simulator build-and-run --output json`, captures a semantic snapshot, selects the first target that explicitly advertises `typeText` on a `text-field`, runs `xcodebuildmcp ui-automation type-text --replace-existing`, then verifies the sentinel through `xcodebuildmcp ui-automation wait-for-ui --predicate textContains`. The current rerun command should provision AXe through `scripts/provision_xcode27_axe.py` and pass `--xcodebuildmcp-axe-path ~/.cache/omnigent/axe/payloads/51cfaf7552512224c5e9e6a01e059d3986d544bc/axe`; the original stock Codex `0.142.2` proof persisted session `conv_afea5726821741c6a2cfbe255d56d41e` with function call `call_D9IzTX3TfyN6OUgQOd8eopRx`, output containing `"buildStatus": "SUCCEEDED"`, `"typeTextStatus": "SUCCEEDED"`, `"waitStatus": "SUCCEEDED"`, `"bundleId": "ai.omnigent.ios"`, `"elementRef": "e14"`, `beforeTarget` with `http://localhost:6767`, and `afterTargets` with `http://localhost:6767/gesture-proof`; the model replied `XCODEBUILDMCP_CLI_TYPE_TEXT_OK`. This proves bounded text-entry interaction through the CLI adapter, not tap, drag, multi-step navigation, debugger attach, device execution, streaming log follow, XcodeBuildMCP MCP parity, or Xcode IDE bridge tools. |
| XcodeBuildMCP tap interaction through a CLI adapter | `replacement-ready` for bounded iOS simulator tap on a discovered button ref after deterministic app-state reset | `omnigent.adapters.xcodebuild_cli.XcodeBuildCliAdapterPolicy` now installs a generated `xcodebuildmcp_simulator_tap` Python dynamic tool for the first tap boundary. The tool strips ambient `XCODEBUILDMCP_AXE_PATH`, maps an explicit `OMNIGENT_XCODEBUILDMCP_AXE_PATH`, uses a per-call isolated XcodeBuildMCP socket, performs an initial `xcodebuildmcp simulator build-and-run --output json` to discover the simulator and bundle id, clears persisted app state with command-scoped `xcrun simctl uninstall`, launches a fresh install, captures a semantic snapshot, types `http://localhost:6767/gesture-proof` into the discovered text field, selects only the discovered `tap` action on the `Connect` button, taps it, then waits for a settled post-tap snapshot whose text field has normalized back to `http://localhost:6767`. The current rerun command should provision AXe through `scripts/provision_xcode27_axe.py` and pass `--xcodebuildmcp-axe-path ~/.cache/omnigent/axe/payloads/51cfaf7552512224c5e9e6a01e059d3986d544bc/axe`; the original stock Codex `0.142.2` proof persisted session `conv_a7d66fc64df148edbe616855fe0de7fd` with function call `call_DCsJXv24ga2bZYGrUaKz3Nef`, output containing `"preResetBuildStatus": "SUCCEEDED"`, `"resetStatus": "SUCCEEDED"`, `"buildStatus": "SUCCEEDED"`, `"typeTextStatus": "SUCCEEDED"`, `"tapStatus": "SUCCEEDED"`, `"settledStatus": "SUCCEEDED"`, `"bundleId": "ai.omnigent.ios"`, `afterTapTarget` with `http://localhost:6767`, and `afterTapScreenHash: "13s4ko7"`; the model replied `XCODEBUILDMCP_CLI_TAP_OK`. This proves one bounded tap interaction through the CLI adapter, not drag, multi-step navigation, debugger attach, device execution, streaming log follow, XcodeBuildMCP MCP parity, or Xcode IDE bridge tools. |
| Representative Apple workflow smoke through Omnigent plus stock Codex | `replacement-ready` for a routed workflow that uses Apple docs plus read-only Xcode discovery in one stock-Codex session | `scripts/prove_stock_codex_replacement.py --proof apple-workflow-smoke --codex-path /opt/homebrew/bin/codex --live-proof-timeout 240` proved stock Codex `0.142.2` began with the deterministic Apple route block, invoked Omnigent's generated `fetch_apple_docs` tool for `https://developer.apple.com/documentation/swift/string`, then invoked read-only `XcodeBuildMCP__discover_projs` against the Omnigent checkout. Persisted session `conv_6a8bb2b3fa6c4dc182d79ed961581e13` included Apple-docs call `call_YhQNwu4vF4gs4nDZJcTRbNfp` with output containing `title: String`, source URL, and timestamp `2026-06-27T22:39:20.021Z`, plus XcodeBuildMCP call `call_0CgVXm1tP9O2Tcua92bYpovU` with output finding `ap-web/ios/Omnigent.xcodeproj`; the model replied `APPLE_WORKFLOW_SMOKE_OK`. The proof rejects build, run, test, launch, simulator boot/open, and device tools. This proves one representative routed workflow surface, not full release-readiness, branch-diff review, clean-auth onboarding, default-path cutover, or broader XcodeBuildMCP workflow parity. |
| Default-path cutover rehearsal | `replacement-ready` for current-host ambient bundle lookup plus `PATH` stock-Codex resolution | `scripts/prove_stock_codex_replacement.py --proof default-path-cutover --live-proof-timeout 600` proved the same bounded replacement-ready aggregate as `cutover-ready` while rejecting explicit `--apple-bundle`, explicit `--codex-path`, and `--allow-fork-codex`. The successful run resolved the Apple workflow bundle through `$HOME/.codex-fork plugin cache`, resolved Codex from `PATH` to `/opt/homebrew/Caskroom/codex/0.142.2/codex-aarch64-apple-darwin`, reported `codex-cli 0.142.2`, printed fallback steps, and completed graph, router matrix, tool-plane, Apple memory MCP, Apple-docs CLI, XcodeBuildMCP CLI build/install/launch, and read-only XcodeBuildMCP discovery. Persisted evidence included tool-plane session `conv_43ac1aa5b2b54c6c9481e19f487b56e8`/call `call_s1JJto0zLnIntw6SWuOVVBIP`, memory session `conv_339991bb4daf457f9641c74087ba50e4`/call `call_X1378jE22OgPHISMZqrQnoEc`, Apple-docs session `conv_84b4d6ad9dc24d54a5af699a423361d2`/call `call_wOIBY2DurAKNFAOizWVMZ2K0` with timestamp `2026-06-27T23:48:47.569Z`, XcodeBuildMCP CLI run session `conv_516d0163660449f9bb26a89565f8a992`/call `call_qAavmde4rpb8om5WSu2QEYe2`, and read-only Xcode discovery session `conv_82c10dfceea1443abcabf22d23a8e9d6`/call `call_T6mZb5QP9aJnmWMTkokcWKLG`. An earlier `--live-proof-timeout 420` attempt timed out once at the final read-only Xcode discovery surface after preceding surfaces passed; a standalone discovery rerun then passed in 165.2s, and the full 600-second default-path rerun passed. This proves the current-host default lookup and fallback contract, not clean `CODEX_HOME` auth onboarding, cross-machine portability, or any actual mutation of launcher defaults. |
| Pinned stock-Codex provisioning | `replacement-ready` for source-binary provisioning into a deterministic Omnigent-owned cache layout | `scripts/provision_stock_codex.py` provisions a stock Codex binary from `PATH` or `--source-binary` into `<cache-root>/<version>/codex`, records `manifest.json` provenance with source path, source realpath, version, SHA-256, platform, install time, and `OMNIGENT_STOCK_CODEX_PATH`, rejects `.codex-fork` sources by default, and fails closed when an existing payload is stale unless `--force` is explicit. `uvx --from . python scripts/prove_stock_codex_replacement.py --proof pinned-codex-provision` proved the isolated temp-cache path against stock Codex `0.142.2`, source `/opt/homebrew/Caskroom/codex/0.142.2/codex-aarch64-apple-darwin`, SHA-256 `31ad44ac440cd7a6dd907c773817800db9c9a7e9c13d3bab7309319e2cd08fa9`, and verified Omnigent resolves the provisioned binary through `OMNIGENT_STOCK_CODEX_PATH` instead of ambient `codex` lookup. This proves the pinned local/downloaded-binary install contract, not an official remote download/update channel, clean-auth onboarding, cross-machine portability, persistent launcher activation, or production-default mutation. |
| Stock-Codex channel manifest provisioning | `replacement-ready` for a local/file-backed update-channel contract | `scripts/provision_stock_codex.py` accepts a mutually exclusive `--channel-manifest` path whose `kind: omnigent-stock-codex-channel` manifest selects an artifact by `latest`, `--channel-version`, and platform, then stages a local path or `file://` artifact, verifies SHA-256 and `codex --version`, installs it into the deterministic `codex-stock/<version>/codex` cache, and records `sourceKind: channel`, channel manifest path, and channel artifact provenance in the installed payload manifest. `uvx --from . python scripts/prove_stock_codex_replacement.py --proof stock-codex-channel` proved this through a temporary local channel manifest and cache against stock Codex `0.142.2`, source `/Users/joshuakaunert/.local/omnigent/codex-stock/0.142.2/codex`, SHA-256 `31ad44ac440cd7a6dd907c773817800db9c9a7e9c13d3bab7309319e2cd08fa9`, `sourceKind=channel`, and `OMNIGENT_STOCK_CODEX_PATH` resolver selection of the channel-provisioned payload. This proves the manifest-driven staging/update primitive for local artifacts; remote transport is covered by the separate Homebrew remote-channel gate. |
| Stock-Codex Homebrew/GitHub remote channel provisioning | `replacement-ready` for temporary official cask metadata download and archive extraction | `scripts/provision_stock_codex.py` now supports opt-in remote channel artifacts via `--allow-remote-channel-download`, verifies the downloaded artifact SHA-256 before materialization, supports `archiveFormat: tar.gz` with a declared `archiveExecutable`, extracts only a safe matching file into a staged `codex` binary, verifies `codex --version`, installs the binary with channel provenance, and records the remote source URL in the installed payload manifest. `uvx --from . python scripts/prove_stock_codex_replacement.py --proof stock-codex-homebrew-remote-channel` read `HOMEBREW_NO_AUTO_UPDATE=1 brew info --cask --json=v2 codex`, required `homepage=https://github.com/openai/codex`, required an `https://github.com/openai/codex/releases/download/...tar.gz` URL, downloaded `https://github.com/openai/codex/releases/download/rust-v0.142.2/codex-aarch64-apple-darwin.tar.gz`, verified cask archive SHA-256 `264c15a63146176db0314c54728437c97b1121bb2617c426c06925d62b4454b3`, extracted `codex-aarch64-apple-darwin`, verified `codex-cli 0.142.2`, installed a temporary payload with binary SHA-256 `31ad44ac440cd7a6dd907c773817800db9c9a7e9c13d3bab7309319e2cd08fa9`, and proved Omnigent resolver selection through `OMNIGENT_STOCK_CODEX_PATH`. This proves Homebrew cask metadata plus OpenAI GitHub release archive download, SHA verification, safe extraction, version verification, temporary installation, and resolver selection; it does not prove independent signature/notarization policy, automatic update scheduling, persistent installation, clean-auth onboarding, cross-machine portability, or app-bundle launcher mutation. |
| Stock-Codex production channel policy | `replacement-ready` for official-source policy, no-network reuse, and fail-closed rejection | `docs/stock-codex-production-channel-policy.md` defines the accepted production source as an `omnigent-stock-codex-channel` artifact whose URL is exactly shaped as an HTTPS `github.com/openai/codex/releases/download/<tag>/<archiveExecutable>.tar.gz` tarball with a declared archive executable and SHA-256. `scripts/provision_stock_codex.py --channel-policy official-openai-github-release` validates that policy and now verifies an existing matching channel-managed payload before attempting remote materialization. `uvx --from . python scripts/prove_stock_codex_replacement.py --proof stock-codex-production-channel-policy --codex-path <stock-codex>` proves a temp-rooted clean cache can reuse a preverified official-channel payload without remote download, reject a non-official URL before cache mutation, and resolve the reused payload through `OMNIGENT_STOCK_CODEX_PATH`. This closes the production trust-source, exact-pin reuse, and fail-closed policy gate; automatic update scheduling, persistent launcher pointer promotion, and independent archive signature policy remain separate product decisions. |
| Stock-Codex update doctor | `replacement-ready` for official-policy dry-run planning and promotion/rollback intent | `scripts/provision_stock_codex.py --plan-update` emits a stable JSON plan for an official channel artifact without promoting persistent pointers. The mode requires `--channel-policy official-openai-github-release`, inspects the current Codex path from `--current-codex`, launcher manifest, or `OMNIGENT_STOCK_CODEX_PATH`, verifies any existing target payload before recommending it, reports `stage-required`, `force-required`, `stage-ready`, `staged`, or `up-to-date`, and records promotion plus rollback intent. Promotion material such as env updates is emitted only when `promotion.ready=true`. `uvx --from . python scripts/prove_stock_codex_replacement.py --proof stock-codex-update-doctor --codex-path ~/.local/omnigent/codex-stock/0.142.5/codex` proved missing-policy rejection, dry-run no-mutation behavior for an absent target, target-ready promotion gating, preverified target detection with launcher promotion and rollback intent, up-to-date promotion suppression, and no host-cache references in emitted plans. This closes update planning and doctor semantics; automatic scheduling, persistent pointer promotion, pre-release channel adoption, and independent archive-signature verification remain separate decisions. |
| Stock-Codex update acquisition | `replacement-ready` for stable official-channel remote acquisition execution without persistent promotion | `scripts/prove_stock_codex_replacement.py --proof stock-codex-update-acquisition --codex-path /Users/joshuakaunert/.local/omnigent/codex-stock/0.142.5/codex` reads Homebrew cask metadata with auto-update disabled, validates policy `official-openai-github-release`, writes a temporary OpenAI GitHub release channel manifest, copies the current stock Codex into a temp current-path so host cache paths cannot leak into emitted plans, proves acquisition fails closed without `--allow-remote-channel-download` and without blocked-cache mutation, then reruns with explicit remote opt-in and expected SHA-256. On 2026-07-07 the live run selected stable cask/GitHub latest `0.142.5`, downloaded `https://github.com/openai/codex/releases/download/rust-v0.142.5/codex-aarch64-apple-darwin.tar.gz`, verified cask SHA-256 `7156b19962735c9cfb555cdd7babe8c40e7976881f8712b781199219d2e3a707`, extracted `codex-aarch64-apple-darwin`, staged a channel payload with binary SHA-256 `0d9a9da26e49e62b2c36f11229920287fc05576e77140ec63621ef6fdb2ddcd1`, reported `promotion.required=true`, `promotion.ready=true`, launcher update intent, and rollback to the temp current Codex, then proved the same target reuses as `stage-ready` without another remote-download flag or mutation. `gh release list --repo openai/codex --limit 10` showed `rust-v0.142.5` as latest stable and `0.143.0-alpha.37` as a pre-release; adopting pre-release payloads remains a separate policy decision. This closes stable remote acquisition execution, not scheduled updates, persistent launcher pointer promotion, alpha-channel adoption, or independent signature verification. |
| Clean Codex-auth onboarding boundary | `replacement-ready` for local auth-source classification and stock-home separation | `scripts/prove_stock_codex_replacement.py --proof clean-auth-onboarding` now resolves stock Codex through the managed default, prefers stock `~/.codex/auth.json` when the parent Codex app process inherits `CODEX_HOME=/Users/joshuakaunert/.codex-fork`, verifies the current stock auth source is locally available without printing credential material, then runs an isolated clean `HOME` plus clean `CODEX_HOME` and proves it reports `needs-auth` rather than falling back to the Codex fork. The same proof writes a synthetic temporary API-key-shaped `auth.json`, verifies the classifier recognizes it as available, and removes the temporary profile. The current green run used stock Codex `0.142.2`, stock auth path `/Users/joshuakaunert/.codex/auth.json`, `clean_auth_real_auth_source=stock-default-home`, `clean_auth_clean_unavailable_reason=needs-auth`, and `clean_auth_synthetic_available_reason=None`. This proves the local onboarding boundary, credential-source separation, and failure classification; it does not automate `codex login`, prove browser/device auth UX, validate token freshness against OpenAI servers, package credentials for another machine, or run a live model call under a newly authenticated clean profile. |
| Stock Codex compatibility install/config bridge | `replacement-ready` for isolated plugin install plus Omnigent bridge configuration; not yet live route parity | `uvx --from . python scripts/prove_stock_codex_replacement.py --proof stock-codex-compat --codex-path /Users/joshuakaunert/.local/omnigent/codex-stock/0.142.2/codex` created a temporary local Codex marketplace, installed and enabled `apple-appdev-workflow@LocalAppleWorkflow` through stock Codex's own `plugin marketplace add`, `plugin add`, and `plugin list --json` commands, then injected the real Omnigent `mcp_servers.omnigent` bridge and Codex policy hooks into an isolated temporary `CODEX_HOME`. Stock Codex's own `mcp list --json` and `mcp get omnigent --json` saw `XcodeBuildMCP`, `memory`, `omnigent`, and `sosumi`; the `omnigent` server command used `python -I -m omnigent.claude_native_bridge serve-mcp --bridge-dir <temp>`. The generated `hooks.json` carried `PreToolUse`, `PostToolUse`, and `UserPromptSubmit` commands for `omnigent.codex_native_hook evaluate-policy --bridge-dir <temp>`. This proves a stock Codex CLI profile can carry the plugin plus Omnigent sidecar bridge without mutating persistent `~/.codex`, the stock Codex app, or the Codex fork. It does not prove a live stock Codex Electron/CLI session emits deterministic route evidence before model output, executes adapter tools through that sidecar, pins the stock binary from the stock entrypoint, or preserves diagnostics under a real user turn. |
| Stock Codex compatibility live route parity | `blocked` at stock-entrypoint route injection | `uvx --from . python scripts/prove_stock_codex_replacement.py --proof stock-codex-compat-live --codex-path /Users/joshuakaunert/.local/omnigent/codex-stock/0.142.2/codex --live-proof-timeout 180` reused the isolated compatibility profile, symlinked stock `~/.codex/auth.json` into the temporary `CODEX_HOME`, launched stock Codex `exec --json --dangerously-bypass-hook-trust`, and completed a live model turn from the stock entrypoint. The proof first caught a prompt-too-loose attempt where the model tried to inspect the workspace, then tightened the no-tool sentinel prompt. The final run returned the exact model sentinel `STOCK_CODEX_COMPAT_LIVE_OK`, proving the live stock-entrypoint profile can authenticate and run, but failed because the first agent message was only that sentinel and did not start with `Routing: orchestrator-led`. Diagnosis: the current Omnigent Codex policy hook can block `UserPromptSubmit`, but it does not rewrite or prepend prompt context for a stock Codex entrypoint. This preserves the primary Omnigent runtime as the proven route-before-model path and shows that stock-Codex compatibility needs a new route-injection surface, a supported stock hook/context mechanism, or an explicit compatibility wrapper before it can claim deterministic route parity. |
| Omnigent-owned stock Codex wrapper live route parity | `replacement-ready` for source-owned CLI JSONL route prefix; raw stock entrypoint remains blocked | `omnigent.stock_codex_compat_wrapper` is now a package module exposed as console script `omnigent-stock-codex-wrapper`. `uvx --from . python scripts/prove_stock_codex_replacement.py --proof stock-codex-compat-wrapper-live --codex-path /Users/joshuakaunert/.local/omnigent/codex-stock/0.142.2/codex --live-proof-timeout 180` reused the isolated compatibility profile, symlinked stock `~/.codex/auth.json`, installed the Apple workflow plugin from the disposable marketplace, injected the Omnigent MCP bridge and policy hooks, then launched stock Codex through that source-owned wrapper module. The wrapped stock process returned the pre-wrapper first model message `STOCK_CODEX_COMPAT_LIVE_OK`; the wrapper recorded `routeInjected=True` and transformed the first visible `agent_message` to start with `Routing: orchestrator-led` and `apple-appdev-workflow:apple-app-orchestrator` before the sentinel. The current live run used stock Codex `0.142.2`, wrapper path `omnigent/stock_codex_compat_wrapper.py`, thread `019f28f7-57c9-7491-b10b-e6422b0936ba`, and saw `XcodeBuildMCP`, `memory`, `omnigent`, and `sosumi` in the isolated profile. This removes the route-injection blocker if the compatibility product is allowed to ship an Omnigent-owned wrapper as the entrypoint around stock Codex. It does not prove unwrapped stock Codex Electron parity, streaming TUI transformation, generated adapter-tool execution through the wrapper, stock-binary pinning from the wrapper, auth onboarding UX, or diagnostics preservation under multi-turn work. |
| Omnigent-owned stock Codex wrapper command-tool execution | `replacement-ready` for wrapped stock `command_execution` event preservation; generated adapter tools still separate | `uvx --from . python scripts/prove_stock_codex_replacement.py --proof stock-codex-compat-wrapper-command-tool --codex-path /Users/joshuakaunert/.local/omnigent/codex-stock/0.142.2/codex --live-proof-timeout 180` reused the isolated compatibility profile and source-owned wrapper, created a temporary read-only workspace containing `tool-proof.txt`, then asked stock Codex to run `cat tool-proof.txt` through its shell command tool. The wrapped stock run persisted exactly one completed `command_execution` item, command `/bin/zsh -lc 'cat tool-proof.txt'`, output `OMNIGENT_TOOL_SENTINEL_42`, exit code `0`, and final pre-wrapper model reply `STOCK_CODEX_COMPAT_WRAPPER_TOOL_OK`. The wrapper recorded `routeInjected=True` and transformed the first visible `agent_message` to start with the deterministic Apple route before that sentinel. The live run used stock Codex `0.142.2`, wrapper path `omnigent/stock_codex_compat_wrapper.py`, thread `019f28f7-1087-7c22-9922-fc28c8d9b8ac`, and saw `XcodeBuildMCP`, `memory`, `omnigent`, and `sosumi` in the isolated profile. This proves the wrapper can preserve stock Codex JSONL tool events while injecting route evidence. It does not prove Omnigent generated adapter tools, MCP tool calls through the sidecar, streaming TUI transformation, stock-binary pinning from the wrapper, or diagnostics preservation under multi-turn work. |
| Omnigent-owned stock Codex wrapper adapter-package execution | `replacement-ready` for validated wrapper-owned adapter package exposure through the proven stock command tool | `omnigent.adapters.stock_codex_compat` now writes executable adapter packages and `omnigent.stock_codex_compat_wrapper` accepts `--adapter-bin` / `OMNIGENT_STOCK_CODEX_COMPAT_ADAPTER_BIN` plus `--adapter-manifest` / `OMNIGENT_STOCK_CODEX_COMPAT_ADAPTER_MANIFEST`, validates the adapter package before launching stock Codex, requires each declared command to be executable in the adapter bin, and requires a closed object parameter schema (`additionalProperties=false`) for each adapter tool. `uvx --from . python scripts/prove_stock_codex_replacement.py --proof stock-codex-compat-wrapper-adapter-tool --codex-path /Users/joshuakaunert/.local/omnigent/codex-stock/0.142.2/codex --live-proof-timeout 180` created a temporary adapter package with `adapter-manifest.json`, declared `omnigent-wrapper-adapter-probe` with argument object `{"message": "stock-codex-wrapper-adapter-proof"}`, launched stock Codex through the wrapper, and asked stock Codex to run `omnigent-wrapper-adapter-probe --message stock-codex-wrapper-adapter-proof` exactly once through its shell command tool. The wrapped run persisted one completed `command_execution` item, command `/bin/zsh -lc 'omnigent-wrapper-adapter-probe --message stock-codex-wrapper-adapter-proof'`, output `{"source":"omnigent-wrapper-adapter","tool":"omnigent-wrapper-adapter-probe","capability":"adapter-proof","sentinel":"OMNIGENT_ADAPTER_TOOL_SENTINEL_64","message":"stock-codex-wrapper-adapter-proof"}`, exit code `0`, and final pre-wrapper model reply `STOCK_CODEX_COMPAT_WRAPPER_ADAPTER_TOOL_OK`. The wrapper recorded `routeInjected=True` plus the expected temporary `adapterBin`, `adapterManifest`, and `adapterToolNames=["omnigent-wrapper-adapter-probe"]`, then transformed the first visible `agent_message` to start with the deterministic Apple route. The live run used stock Codex `0.142.2`, thread `019f2c07-db4b-75d1-bc14-bad4ef391ca4`, and saw `XcodeBuildMCP`, `memory`, `omnigent`, and `sosumi` in the isolated profile. This proves a stronger Omnigent-owned adapter package and argument-schema discipline path around stock Codex without relying on stock `exec` MCP relay discovery. It does not itself prove real workflow adapters are wired through the generator, model-visible schema rendering outside the proof prompt, or streaming TUI transformation. |
| Omnigent-owned stock Codex wrapper adapter arbitration | `replacement-ready` for generated multi-tool adapter package selection through the proven stock command tool | `scripts/prove_stock_codex_replacement.py --proof stock-codex-compat-wrapper-adapter-arbitration --codex-path /Users/joshuakaunert/.local/omnigent/codex-stock/0.142.2/codex --live-proof-timeout 180` created a generated adapter package through `omnigent.adapters.stock_codex_compat` with two manifest-declared tools, `omnigent-wrapper-route-adapter-probe` for `route-selection` and `omnigent-wrapper-release-adapter-probe` for `release-notes`, each with a closed argument object schema. The wrapper validated the manifest and exposed both commands through the adapter bin before launching stock Codex. The live stock run selected the requested route adapter, rejected the release adapter, persisted exactly one completed `command_execution` item, command `/bin/zsh -lc 'omnigent-wrapper-route-adapter-probe --message route-selection-proof'`, output `{"source":"omnigent-wrapper-adapter","tool":"omnigent-wrapper-route-adapter-probe","capability":"route-selection","sentinel":"OMNIGENT_ADAPTER_ARBITRATION_ROUTE_SENTINEL_88","message":"route-selection-proof"}`, exit code `0`, and final pre-wrapper model reply `STOCK_CODEX_COMPAT_WRAPPER_ADAPTER_ARBITRATION_OK`. The wrapper recorded `routeInjected=True`, the expected `adapterBin`, `adapterManifest`, and `adapterToolNames=["omnigent-wrapper-route-adapter-probe","omnigent-wrapper-release-adapter-probe"]`, then transformed the first visible `agent_message` to start with the deterministic Apple route. The live run used stock Codex `0.142.2`, thread `019f2c09-01c0-7293-8368-15a7999f73ac`, and saw `XcodeBuildMCP`, `memory`, `omnigent`, and `sosumi` in the isolated profile. This closes the bounded multi-tool arbitration proof for wrapper-owned adapter packages around stock Codex. It does not prove real workflow adapters are wired through the generator, MCP relay discovery, or streaming TUI transformation. |
| Omnigent-owned stock Codex wrapper Apple docs adapter | `replacement-ready` for the first real workflow adapter through the generated wrapper package, with elevated network sandbox caveat | `omnigent.adapters.apple_docs_cli.build_fetch_apple_docs_stock_codex_adapter_spec` now produces a `fetch_apple_docs` `StockCodexCompatAdapterCommandSpec` with a closed `{"url": "string"}` object schema and executable command source. `scripts/prove_stock_codex_replacement.py --proof stock-codex-compat-wrapper-apple-docs-adapter --codex-path /Users/joshuakaunert/.local/omnigent/codex-stock/0.142.2/codex --live-proof-timeout 300` created a temporary generated adapter package, selected a direct `sosumi fetch` command prefix when available to avoid `npx` package installation in the isolated stock profile, launched stock Codex through the wrapper, and asked stock Codex to run `fetch_apple_docs --url https://developer.apple.com/documentation/swift/string` exactly once. The wrapped run persisted one completed `command_execution` item, command `/bin/zsh -lc 'fetch_apple_docs --url https://developer.apple.com/documentation/swift/string'`, output containing `title: String`, `source: https://developer.apple.com/documentation/swift/string`, and timestamp `2026-07-04T07:47:01.726Z`, exit code `0`, and final pre-wrapper model reply `STOCK_CODEX_COMPAT_WRAPPER_APPLE_DOCS_ADAPTER_OK`. The wrapper recorded `routeInjected=True`, `adapterToolNames=["fetch_apple_docs"]`, and transformed the visible first `agent_message` to start with the deterministic Apple route. The live run used stock Codex `0.142.2`, thread `019f2c18-380a-7003-90a0-e11b7edd8a93`, and saw `XcodeBuildMCP`, `memory`, `omnigent`, and `sosumi` in the isolated profile. This proves the first real generated workflow adapter through the stock-wrapper command surface. It also proves an important caveat: `read-only` timed out on `npx`, `workspace-write` still failed the direct Sosumi fetch, and this networked adapter required stock Codex `--sandbox danger-full-access` in a temporary workspace. It does not prove low-privilege network adapter execution, packaged cross-machine Sosumi provisioning, or streaming TUI transformation. |
| Omnigent-owned stock Codex wrapper Apple docs file-bridge adapter | `replacement-ready` for low-privilege stock command execution plus wrapper-side network execution | `omnigent.adapters.stock_codex_compat.build_stock_codex_compat_file_bridge_command_source` now generates adapter commands that write a JSON request under a wrapper-owned file bridge, poll for a structured response, and print the returned stdout/stderr/exit code. `omnigent.stock_codex_adapter_runtime.build_stock_codex_adapter_bridge_service` maps supported manifest capabilities to wrapper-side handlers, and `omnigent.stock_codex_compat_wrapper` starts `FileBridgeAdapterService` automatically when `--adapter-bridge-dir` is present. `omnigent.adapters.apple_docs_cli.build_fetch_apple_docs_stock_codex_bridge_handler` owns the adapter subprocess handler. `omnigent.adapters.apple_docs_cli.build_fetch_apple_docs_stock_codex_bridge_adapter_spec` uses that bridge command for `fetch_apple_docs` with the same closed `{"url": "string"}` object schema as the direct adapter. `omnigent.stock_codex_compat_wrapper` accepts `--adapter-bridge-dir` / `OMNIGENT_STOCK_CODEX_COMPAT_ADAPTER_BRIDGE_DIR`, passes it to stock Codex, and records `adapterBridgeDir` in wrapper evidence. `uvx --from . python scripts/prove_stock_codex_replacement.py --proof stock-codex-compat-wrapper-apple-docs-bridge-adapter --codex-path /Users/joshuakaunert/.local/omnigent/codex-stock/0.142.2/codex --live-proof-timeout 300` placed both the generated adapter package and bridge directory inside a temporary stock workspace, launched stock Codex through the wrapper with `--sandbox workspace-write`, and asked stock Codex to run `fetch_apple_docs --url https://developer.apple.com/documentation/swift/string` exactly once. The stock command wrote the bridge request, the wrapper-owned bridge runtime validated the URL and ran `sosumi fetch` outside the stock sandbox, and the wrapped run persisted one completed `command_execution` item, command `/bin/zsh -lc 'fetch_apple_docs --url https://developer.apple.com/documentation/swift/string'`, output containing `title: String`, `source: https://developer.apple.com/documentation/swift/string`, and timestamp `2026-07-04T12:28:36.014Z`, exit code `0`, and final pre-wrapper model reply `STOCK_CODEX_COMPAT_WRAPPER_APPLE_DOCS_BRIDGE_ADAPTER_OK`. The wrapper recorded `routeInjected=True`, `adapterToolNames=["fetch_apple_docs"]`, and `adapterBridgeDir=<workspace>/.omnigent-adapter-bridge`; the regression run used stock Codex `0.142.2`, thread `019f2d19-ea7b-7330-87eb-a9eadc74add7`, and saw `XcodeBuildMCP`, `memory`, `omnigent`, and `sosumi` in the isolated profile. This closes the low-privilege networked Apple-docs adapter gate for the wrapper-owned command surface and proves the reusable packaged bridge service still preserves the original Apple-docs behavior under wrapper-runtime activation. It does not prove a packaged cross-machine Sosumi worker or streaming TUI transformation. |
| Omnigent-owned stock Codex wrapper file-bridge diagnostics | `replacement-ready` for failed adapter command diagnostics through stock Codex `command_execution` output | `omnigent.stock_codex_adapter_bridge.AdapterBridgeResponse` now attaches diagnostics metadata only to error responses, and `omnigent.adapters.stock_codex_compat.build_stock_codex_compat_file_bridge_command_source` emits one `OMNIGENT_ADAPTER_BRIDGE_DIAGNOSTIC` JSON line to stderr for failed bridge responses while leaving successful adapter stdout/stderr unchanged. `scripts/prove_stock_codex_replacement.py --proof stock-codex-compat-wrapper-bridge-diagnostics --codex-path /Users/joshuakaunert/.local/omnigent/codex-stock/0.142.5/codex --live-proof-timeout 300` placed a generated `fetch_apple_docs` bridge adapter package and bridge directory inside a temporary stock workspace, launched stock Codex through the wrapper with `--sandbox workspace-write`, and intentionally asked stock Codex to run `fetch_apple_docs --url https://example.com/documentation/swift/string` exactly once. The wrapper-side bridge rejected the URL before network execution, returned exit code `64`, and stock Codex persisted one failed `command_execution` item for `/bin/zsh -lc 'fetch_apple_docs --url https://example.com/documentation/swift/string'` with aggregated output containing `Error: url must be an https://developer.apple.com documentation URL` plus `OMNIGENT_ADAPTER_BRIDGE_DIAGNOSTIC {"diagnostics": {"bridge": "stock-codex-file-bridge", "completedAt": "2026-07-07T01:10:47.610480Z", "durationMs": 0.224, "requestId": "8714-f7d87f76e35d42bd9e2dfe1945705590", "startedAt": "2026-07-07T01:10:47.610075Z", "tool": "fetch_apple_docs"}, "exitCode": 64, "source": "omnigent-stock-codex-file-bridge", "status": "error"}`. The model replied `STOCK_CODEX_COMPAT_WRAPPER_BRIDGE_DIAGNOSTICS_OK`, and the wrapper still injected deterministic route evidence first. The live run used stock Codex `0.142.5`, thread `019f3a20-840a-7251-91b1-238254a176dc`, and saw `XcodeBuildMCP`, `memory`, `omnigent`, and `sosumi` in the isolated profile. Unit coverage in `tests/test_stock_codex_adapter_bridge.py::test_file_bridge_worker_adds_error_diagnostics`, `tests/adapters/test_stock_codex_compat.py::test_file_bridge_command_emits_error_diagnostic`, and `tests/scripts/test_prove_stock_codex_replacement.py::test_stock_codex_bridge_diagnostics_validator_preserves_failure_payload` pins the bridge response metadata, generated command stderr shape, and proof validator. This closes wrapper file-bridge diagnostics preservation for failed adapter commands; it does not expose raw stock-Codex provider SSE/WebSocket response ids, streaming TUI transformation, or diagnostics for unrelated stock-Codex internals. |
| Omnigent-owned stock Codex wrapper XcodeBuildMCP file-bridge adapter | `replacement-ready` for low-privilege stock command execution plus wrapper-side simulator build/install/launch | `omnigent.adapters.xcodebuild_cli.build_xcodebuildmcp_simulator_build_run_stock_codex_bridge_adapter_spec` now produces a `xcodebuildmcp_simulator_build_run` `StockCodexCompatAdapterCommandSpec` with a closed object schema for `project_path`, `scheme`, `configuration`, `simulator_name`, and `derived_data_path`. `omnigent.stock_codex_adapter_runtime.build_stock_codex_adapter_bridge_service` maps the manifest capability to `omnigent.adapters.xcodebuild_cli.build_xcodebuildmcp_simulator_build_run_stock_codex_bridge_handler`, and `omnigent.stock_codex_compat_wrapper` starts that service automatically when `--adapter-bridge-dir` is present. The handler reuses `XcodeBuildCliAdapterPolicy.command_for_build_run`, supplies bounded `extra_args=["-quiet"]`, preserves the full XcodeBuildMCP workflow env overrides, and keeps AXe env normalization aligned with the existing dynamic-tool adapter. `DEVELOPER_DIR=/Applications/Xcode-27.0.0-Beta.2.app/Contents/Developer uvx --from . python scripts/prove_stock_codex_replacement.py --proof stock-codex-compat-wrapper-xcodebuild-bridge-adapter --codex-path /Users/joshuakaunert/.local/omnigent/codex-stock/0.142.2/codex --live-proof-timeout 480` placed the generated adapter package and bridge directory inside a temporary stock workspace, launched stock Codex through the wrapper with `--sandbox workspace-write`, and asked stock Codex to run `xcodebuildmcp_simulator_build_run --project_path /Users/joshuakaunert/Developer/HarnessEngineering/omnigent-upstream-audit/ap-web/ios/Omnigent.xcodeproj --scheme Omnigent --configuration Debug --simulator_name 'iPhone 17' --derived_data_path <temp>/xcodebuild-bridge-deriveddata` exactly once. The stock command wrote the bridge request, the wrapper-owned bridge runtime ran `xcodebuildmcp simulator build-and-run` outside the stock sandbox, and the wrapped run persisted one completed `command_execution` item with output containing `Build succeeded`, `Build & Run complete`, and `Bundle ID: ai.omnigent.ios`, exit code `0`, and final pre-wrapper model reply `STOCK_CODEX_COMPAT_WRAPPER_XCODEBUILD_BRIDGE_ADAPTER_OK`. The wrapper recorded `routeInjected=True`, `adapterToolNames=["xcodebuildmcp_simulator_build_run"]`, and `adapterBridgeDir=<workspace>/.omnigent-adapter-bridge`; the live run used stock Codex `0.142.2`, thread `019f2d1a-5253-7d30-92d0-a29c23c44869`, simulator `iPhone 17`, temporary DerivedData under `/var/folders`, and saw `XcodeBuildMCP`, `memory`, `omnigent`, and `sosumi` in the isolated profile. This proves the same reusable packaged wrapper bridge can carry the first XcodeBuildMCP simulator build/install/launch adapter without granting stock Codex `danger-full-access`, with bridge runtime activation owned by the wrapper entrypoint. It does not prove XcodeBuildMCP tests, screenshots, semantic snapshots, gestures, device execution, or streaming TUI transformation. |
| Omnigent-owned stock Codex wrapper XcodeBuildMCP simulator-test file-bridge adapter | `replacement-ready` for low-privilege stock command execution plus wrapper-side simulator tests | `omnigent.adapters.xcodebuild_cli.build_xcodebuildmcp_simulator_test_stock_codex_bridge_adapter_spec` now produces a `xcodebuildmcp_simulator_test` `StockCodexCompatAdapterCommandSpec` with the same closed object schema shape as build/run for `project_path`, `scheme`, `configuration`, `simulator_name`, and `derived_data_path`. `omnigent.stock_codex_adapter_runtime.build_stock_codex_adapter_bridge_service` maps the manifest capability to `omnigent.adapters.xcodebuild_cli.build_xcodebuildmcp_simulator_test_stock_codex_bridge_handler`. The handler reuses `XcodeBuildCliAdapterPolicy.command_for_simulator_test`, supplies bounded `extra_args=["-quiet"]`, preserves the full XcodeBuildMCP workflow env overrides, and keeps wrapper-side execution outside the stock Codex sandbox. `DEVELOPER_DIR=/Applications/Xcode-27.0.0-Beta.2.app/Contents/Developer uvx --from . python scripts/prove_stock_codex_replacement.py --proof stock-codex-compat-wrapper-xcodebuild-bridge-test-adapter --codex-path /Users/joshuakaunert/.local/omnigent/codex-stock/0.142.5/codex --live-proof-timeout 600` placed the generated adapter package and bridge directory inside a temporary stock workspace, launched stock Codex through the wrapper with `--sandbox workspace-write`, and asked stock Codex to run `xcodebuildmcp_simulator_test --project_path /Users/joshuakaunert/Developer/HarnessEngineering/omnigent-upstream-audit/ap-web/ios/Omnigent.xcodeproj --scheme Omnigent --configuration Debug --simulator_name 'iPhone 17' --derived_data_path <temp>/xcodebuild-bridge-deriveddata` exactly once. The stock command wrote the bridge request, the wrapper-owned bridge runtime ran `xcodebuildmcp simulator test` outside the stock sandbox, and the wrapped run persisted one completed `command_execution` item with output containing `Discovered 10 test(s)`, `10 tests passed`, `0 failed`, and `0 skipped`, exit code `0`, and final pre-wrapper model reply `STOCK_CODEX_COMPAT_WRAPPER_XCODEBUILD_BRIDGE_TEST_ADAPTER_OK`. The wrapper recorded `routeInjected=True`, `adapterToolNames=["xcodebuildmcp_simulator_test"]`, and `adapterBridgeDir=<workspace>/.omnigent-adapter-bridge`; the live run used stock Codex `0.142.5`, thread `019f3a01-d0c5-74c1-a036-b2158c453402`, simulator `iPhone 17`, temporary DerivedData under `/var/folders`, and saw `XcodeBuildMCP`, `memory`, `omnigent`, and `sosumi` in the isolated profile. This proves the reusable packaged wrapper bridge can carry XcodeBuildMCP simulator tests without granting stock Codex `danger-full-access`. It does not prove screenshots, semantic snapshots, gestures, device execution, or streaming TUI transformation. |
| Managed stock Codex compatibility launcher activation | `replacement-ready` for temporary default-entrypoint wiring of the wrapper-owned bridge runtime | `scripts/install_stock_codex_compat_launcher.py` now writes a managed compatibility launcher that carries the standard Omnigent launcher marker and manifest pointer, records the pinned stock Codex binary, route prefix, adapter bin, adapter manifest, adapter bridge dir, and adapter tool names, preserves `--version` delegation to the pinned stock binary, and delegates normal execution through `uvx --from <repo> omnigent-stock-codex-wrapper`. The installer refuses unmanaged existing targets unless `--backup-existing` is explicit, validates probe and version behavior, and when installed as `codex` proves `omnigent.inner.codex_executor._find_codex_cli()` maps the managed launcher back to the manifest-pinned stock Codex path instead of recursing into the launcher. `uvx --from . python scripts/prove_stock_codex_replacement.py --proof stock-codex-compat-launcher-activation` installed that launcher as a temporary PATH-selected `codex`, used real `uvx` at `/Users/joshuakaunert/.local/bin/uvx`, launched a deterministic fake stock Codex through `omnigent-stock-codex-wrapper`, started the wrapper-owned file-bridge runtime from a generated `fetch_apple_docs` bridge adapter package, kept the stock command under `workspace-write`, persisted one `command_execution` item for `/bin/zsh -lc 'fetch_apple_docs --url https://developer.apple.com/documentation/swift/string'`, returned output containing `title: String` and `source: https://developer.apple.com/documentation/swift/string`, injected the deterministic Apple route before `STOCK_CODEX_COMPAT_LAUNCHER_ACTIVATION_OK`, and uninstalled the temporary launcher plus manifest. Unit coverage in `tests/scripts/test_install_stock_codex_compat_launcher.py` covers manifest writing, managed launcher detection, PATH-selected resolver mapping, normal delegation argv shape, refusal of unmanaged targets, backup/restore uninstall, and unmanaged uninstall refusal; `tests/scripts/test_prove_stock_codex_replacement.py::test_stock_codex_compat_launcher_activation_proof_runs_wrapper_bridge` covers the proof path with a fake `uvx` wrapper forwarder. This proves the durable launcher/default wiring shape for the compatibility wrapper without touching host launcher defaults. It does not prove a production host install target, shell-profile mutation, app-bundle registration, cross-machine packaging, streaming TUI behavior, raw unwrapped stock Codex Electron route parity, or additional bridge tools beyond the Apple-docs adapter used in this gate. |
| Managed stock Codex compatibility launcher doctor | `replacement-ready` for non-mutating host install-plan validation | `scripts/install_stock_codex_compat_launcher.py --doctor` now validates a compatibility launcher install plan without creating, replacing, backing up, or removing launcher files. It validates repo root, `uvx`, pinned stock Codex executable and version, adapter manifest and bin, adapter bridge dir path, existing target state, whether the target is Omnigent-managed, PATH selection posture, parent-directory writability, backup/force requirements, rollback command, and install command shape. `uvx --from . python scripts/prove_stock_codex_replacement.py --proof stock-codex-compat-launcher-doctor` resolved stock Codex to `/Users/joshuakaunert/.local/omnigent/codex-stock/0.142.2/codex`, validated `uvx` at `/Users/joshuakaunert/.local/bin/uvx`, planned the default compatibility launcher target `/Users/joshuakaunert/.local/bin/omnigent-stock-codex-compat`, planned manifest `/Users/joshuakaunert/.local/omnigent/launchers/stock-codex-compat.json`, validated a generated `fetch_apple_docs` bridge adapter package, planned bridge dir `/Users/joshuakaunert/.local/omnigent/stock-codex-compat/adapter-bridge`, reported target absent, parent on PATH, parent exists and is writable, install allowed, no backup required, and `mutatesFilesystem=False`. Unit coverage in `tests/scripts/test_install_stock_codex_compat_launcher.py` covers absent-target doctor behavior, unmanaged-target backup requirements, and CLI JSON output; `tests/scripts/test_prove_stock_codex_replacement.py::test_stock_codex_compat_launcher_doctor_proof_is_non_mutating` covers the proof runner. This closes the pre-install host-plan validation gap for the compatibility launcher. It does not create the launcher, prove cross-machine packaging, or authorize replacing a host `codex` default. |
| Persistent stock Codex compatibility adapter package | `replacement-ready` for durable user-space adapter placement | `scripts/install_stock_codex_compat_launcher.py --install-adapter-package` now materializes the default compatibility adapter package at `~/.local/omnigent/stock-codex-compat/adapter-package`, writes `bin/fetch_apple_docs` plus `adapter-manifest.json`, validates the manifest through the same wrapper contract used at runtime, and reuses an existing valid package without filesystem mutation. `uvx --from . python scripts/install_stock_codex_compat_launcher.py --install-adapter-package --json` installed the package on the current host, a second run returned `action=adapter-package-reused` and `mutatesFilesystem=false`, and `uvx --from . python scripts/install_stock_codex_compat_launcher.py --doctor --pinned-codex-path /Users/joshuakaunert/.local/omnigent/codex-stock/0.142.5/codex --json` validated the default adapter package without passing `--adapter-bin` or `--adapter-manifest`. The doctor result reported `adapterToolNames=["fetch_apple_docs"]`, target absent, parent on PATH and writable, install allowed, `mutatesFilesystem=false`, and pinned Codex `codex-cli 0.142.5`. Unit coverage in `tests/scripts/test_install_stock_codex_compat_launcher.py` covers package install/reuse, JSON output, and omitted-adapter-path doctor resolution; the proof runner now uses the installer-owned package materializer and default resolver for its temporary non-mutating doctor fixture. This closes persistent packaged adapter placement for the compatibility launcher. It does not create the launcher, pick a production default, package for another machine, or broaden bridge coverage beyond the generated Apple-docs adapter. |
| Persistent stock Codex compatibility launcher command | `replacement-ready` for a separate managed compatibility command on the current host | The default compatibility launcher was installed at `/Users/joshuakaunert/.local/bin/omnigent-stock-codex-compat` with manifest `/Users/joshuakaunert/.local/omnigent/launchers/stock-codex-compat.json`, pinned Codex `/Users/joshuakaunert/.local/omnigent/codex-stock/0.142.5/codex`, adapter package `/Users/joshuakaunert/.local/omnigent/stock-codex-compat/adapter-package`, and bridge dir `/Users/joshuakaunert/.local/omnigent/stock-codex-compat/adapter-bridge`. `which omnigent-stock-codex-compat` selected that path, `omnigent-stock-codex-compat --version` returned `codex-cli 0.142.5`, and `omnigent-stock-codex-compat --omnigent-stock-codex-compat-launcher-probe` reported the expected pinned env, route prefix, adapter paths, and delegate `uvx --from /Users/joshuakaunert/Developer/HarnessEngineering/omnigent-upstream-audit omnigent-stock-codex-wrapper`. The rollback command from the manifest was exercised, removed both launcher and manifest, and a follow-up `which` plus `ls` confirmed they were absent; the same install command was then rerun so the current host ends with the separate command installed. A post-install doctor without `--force` reports the managed target as present and refuses accidental overwrite with `requires-force-for-managed-target`; a force-aware doctor with `--require-path-selected --force` reports `installAllowed=true`, `targetSelectedOnPath=true`, `existingTargetManaged=true`, and `mutatesFilesystem=false`. This closes the production-shaped separate-command install policy for the current host without changing the existing `codex` default. It does not prove cross-machine packaging, app-bundle registration, raw unwrapped stock Codex route parity, or a live model turn through the persistent command. |
| Clean-home stock Codex compatibility install rehearsal | `replacement-ready` for repeatable default-path install and rollback under a fresh profile | `scripts/prove_stock_codex_replacement.py --proof stock-codex-compat-clean-install --codex-path /Users/joshuakaunert/.local/omnigent/codex-stock/0.142.5/codex` runs the real compatibility installer CLI under a temporary clean `HOME`, with `CODEX_HOME` and `OMNIGENT_STOCK_CODEX_PATH` stripped from the child env and `~/.local/bin` first on PATH. The proof installs the adapter package from defaults, installs the separate `omnigent-stock-codex-compat` command from defaults, verifies PATH selection, delegates `--version` to `codex-cli 0.142.5`, probes the wrapper delegate and adapter paths, runs a force-aware doctor that reports `installAllowed=True`, `existingTargetState=managed`, `targetSelectedOnPath=True`, and `mutatesFilesystem=False`, then uninstalls and confirms launcher plus manifest removal. The temporary clean profile is removed after proof. Unit coverage in `tests/scripts/test_prove_stock_codex_replacement.py::test_stock_codex_compat_clean_install_proof_uses_clean_home_defaults` covers the same clean-home default layout with fake stock Codex and fake `uvx`. This closes the clean-profile repeatability contract for a package or installer to execute; it does not create a signed installer artifact, automate stock-Codex download on another machine, or prove credential onboarding there. |
| Portable stock Codex compatibility runtime bundle | `replacement-ready` for an unsigned portable installer artifact rehearsal | `scripts/build_stock_codex_compat_bundle.py` now builds `omnigent-stock-codex-compat-bundle.tar.gz` with `bundle-manifest.json`, a `runtime/` source root containing `pyproject.toml`, `uv.lock`, `omnigent/`, `sdks/`, and `runtime/scripts/install_stock_codex_compat_launcher.py`, while excluding caches and build noise. `scripts/prove_stock_codex_replacement.py --proof stock-codex-compat-bundle-install --codex-path /Users/joshuakaunert/.local/omnigent/codex-stock/0.142.5/codex` builds that bundle into a temporary artifact path, verifies its SHA-256, safely extracts it, runs the bundled installer from the extracted runtime under a temporary clean `HOME`, installs the default adapter package and separate `omnigent-stock-codex-compat` command, verifies PATH selection, delegates `--version` to `codex-cli 0.142.5`, probes the launcher, verifies the installed launcher manifest's `repoRoot` points at the extracted `runtime/` and not the development checkout, runs a force-aware non-mutating doctor, then uninstalls and confirms launcher plus manifest removal. Unit coverage in `tests/scripts/test_build_stock_codex_compat_bundle.py` covers the bundle manifest/archive contract and `tests/scripts/test_prove_stock_codex_replacement.py::test_stock_codex_compat_bundle_install_proof_uses_extracted_runtime` covers the install proof with fake stock Codex and fake `uvx`. This closes the unsigned portable artifact rehearsal for the separate compatibility command. It does not prove a signed `.pkg`/`.app`, notarization, persistent update scheduling, remote stock-Codex download on another machine, auth onboarding there, or a live model turn through the extracted runtime. |
| Unsigned stock Codex compatibility macOS pkg structure | `replacement-ready` for unsigned flat `.pkg` layout and inspection | `scripts/build_stock_codex_compat_pkg.py` builds an unsigned flat macOS package from the portable runtime bundle, stages only the machine-level runtime under `/Library/Application Support/Omnigent/stock-codex-compat`, writes `pkg-manifest.json`, sanitizes the copied bundle manifest so it does not embed the development checkout path, and includes a minimal `postinstall` that validates the runtime root, launcher installer, and stock Codex provisioner without touching user homes. `scripts/prove_stock_codex_replacement.py --proof stock-codex-compat-pkg-structure` built and inspected the package without installing it; the proof reported identifier `ai.omnigent.stock-codex-compat`, version `0.3.0.dev0`, install location `/`, install prefix `/Library/Application Support/Omnigent/stock-codex-compat`, payload file count `1368`, required payload files present for `pkg-manifest.json`, `bundle-manifest.json`, `runtime/pyproject.toml`, `runtime/scripts/install_stock_codex_compat_launcher.py`, `runtime/scripts/provision_stock_codex.py`, and `runtime/omnigent/stock_codex_compat_wrapper.py`, archive entries `Bom`, `PackageInfo`, `Payload`, and `Scripts`, `signatureStatus=no signature`, package SHA-256 `b37ea72c27140836ebf3d2f9ecfc6d7b6084252a0e2ff400b61bec06b6ea1349`, and source bundle SHA-256 `9bab191b411c76d316686b62c9a1f74bb0a8ce714c91f2ae2425f78d7bf89d5e`. Unit coverage in `tests/scripts/test_build_stock_codex_compat_pkg.py` covers the builder contract and `tests/scripts/test_prove_stock_codex_replacement.py::test_stock_codex_compat_pkg_structure_proof_builds_unsigned_pkg` covers the proof path. This closes the unsigned `.pkg` structure gate only; it does not install the package, run a live model turn from the packaged runtime, perform per-user bootstrap, provision stock Codex on a clean machine, handle auth onboarding, sign, notarize, staple, or prove Gatekeeper behavior. |
| Expanded stock Codex compatibility pkg runtime live model turn | `replacement-ready` for live wrapper execution from an expanded unsigned `.pkg` runtime | `scripts/prove_stock_codex_replacement.py --proof stock-codex-compat-pkg-runtime-live --codex-path /Users/joshuakaunert/.local/omnigent/codex-stock/0.142.5/codex --live-proof-timeout 300` built the unsigned `.pkg`, revalidated the package identifier `ai.omnigent.stock-codex-compat`, version `0.3.0.dev0`, install prefix `/Library/Application Support/Omnigent/stock-codex-compat`, sanitized manifest contract, unsigned signature status, and required runtime payload files including `runtime/scripts/provision_stock_codex.py`, then expanded the package without installing it and launched `omnigent-stock-codex-wrapper` via `uvx --from <expanded Payload/Library/Application Support/Omnigent/stock-codex-compat/runtime>` with subprocess `cwd` set to that expanded runtime. The live run reused known-good stock auth from `/Users/joshuakaunert/.codex/auth.json`, enabled every generically enableable stock Codex feature, installed the Apple workflow plugin into an isolated temporary `CODEX_HOME`, saw `XcodeBuildMCP`, `memory`, `omnigent`, and `sosumi`, returned thread `019f3877-0831-75d1-a0a7-08ea9b5bf29c`, recorded pre-wrapper message `STOCK_CODEX_COMPAT_LIVE_OK`, and injected the deterministic Apple route before the visible sentinel. The proof used package SHA-256 `7f1e3c1830cd5c5a6bdb1708c32fb1a2a400b74c6a7e57ab28e12f23c9fd2c46` and source bundle SHA-256 `2e8310efdb40cadde856979807e81f4cbf7e6adf1d011cb6045a0289a8c971a9`. Unit coverage in `tests/scripts/test_prove_stock_codex_replacement.py::test_stock_codex_compat_pkg_runtime_live_proof_uses_expanded_runtime` covers the expanded-runtime command shape with fake stock Codex and fake `uvx`. This closes the live model turn through the expanded package runtime gate. It does not install the package into `/Library`, perform per-user bootstrap from the installed runtime, provision stock Codex on a clean machine, run clean auth onboarding, sign, notarize, staple, or prove Gatekeeper behavior. |
| Pkg-installed runtime per-user bootstrap | `replacement-ready` for clean-user launcher bootstrap, update, doctor, and rollback from an installed runtime shape | `scripts/prove_stock_codex_replacement.py --proof stock-codex-compat-pkg-user-bootstrap --codex-path /Users/joshuakaunert/.local/omnigent/codex-stock/0.142.5/codex` built the unsigned `.pkg`, expanded it, staged the payload under a temporary install root shaped like `/Library/Application Support/Omnigent/stock-codex-compat`, and then ran `runtime/scripts/install_stock_codex_compat_launcher.py` from that installed runtime against a clean temporary `HOME`. The proof installed the default `fetch_apple_docs` adapter package, installed `~/.local/bin/omnigent-stock-codex-compat`, verified PATH selection, delegated `--version` to stock Codex `0.142.5`, verified the launcher probe recorded the installed runtime, verified the launcher manifest `repoRoot` was the installed runtime and `wrapperEntrypoint` was `omnigent-stock-codex-wrapper`, ran a force-aware doctor that reported `installAllowed=True`, `existingTargetState=managed`, `targetSelectedOnPath=True`, and `mutatesFilesystem=False`, force-updated the managed launcher, then executed the generated rollback command. The rollback command itself targeted `uvx --from <installed-runtime> python <installed-runtime>/scripts/install_stock_codex_compat_launcher.py --uninstall ...` and removed both launcher and manifest. The proof used package SHA-256 `2cfa0d27641a5b1c98da15f1fceb7f2ee20591508e98f8ea8f780f97c6768178`. Unit coverage in `tests/scripts/test_prove_stock_codex_replacement.py::test_stock_codex_compat_pkg_user_bootstrap_proof_uses_installed_runtime` covers the installed-runtime command shape with fake stock Codex and fake rollback-capable `uvx`. This closes per-user bootstrap from the installed runtime. It does not perform a real `/Library` install, provision stock Codex on a clean machine, run clean auth onboarding, sign, notarize, staple, or prove Gatekeeper behavior. |
| Pkg-installed runtime clean stock Codex provisioning | `replacement-ready` for clean-user stock Codex cache provisioning from the installed runtime | `scripts/build_stock_codex_compat_bundle.py` and `scripts/build_stock_codex_compat_pkg.py` now include `runtime/scripts/provision_stock_codex.py` in the machine-level runtime payload, require it in package inspection, and have `postinstall` validate both the launcher installer and stock Codex provisioner. `scripts/prove_stock_codex_replacement.py --proof stock-codex-compat-pkg-clean-provision --codex-path /Users/joshuakaunert/.local/omnigent/codex-stock/0.142.5/codex` built the unsigned `.pkg`, expanded and staged it under a temporary installed-root shape, executed `runtime/scripts/provision_stock_codex.py` from that installed runtime against a clean temporary `HOME`, and provisioned stock Codex `0.142.5` into `<clean-home>/.local/omnigent/codex-stock/0.142.5/codex` from an explicit file-backed channel artifact. The proof verified SHA-256 `0d9a9da26e49e62b2c36f11229920287fc05576e77140ec63621ef6fdb2ddcd1`, `sourceKind=channel`, `OMNIGENT_STOCK_CODEX_PATH=<clean-cache>/0.142.5/codex`, Omnigent resolver selection of the clean-provisioned binary, a second no-force provision reusing the same verified payload, and no references to the host cache root `/Users/joshuakaunert/.local/omnigent/codex-stock` in the provisioned manifest/output. The proof used package SHA-256 `8712700c5ce0d9282078fdf149f61ca3ee168bce2c8818fe15b88fc882a606bb`; the refreshed structure proof reports payload file count `1368`, required provisioner payload present, package SHA-256 `b37ea72c27140836ebf3d2f9ecfc6d7b6084252a0e2ff400b61bec06b6ea1349`, and source bundle SHA-256 `9bab191b411c76d316686b62c9a1f74bb0a8ce714c91f2ae2425f78d7bf89d5e`. Unit coverage in `tests/scripts/test_build_stock_codex_compat_bundle.py`, `tests/scripts/test_build_stock_codex_compat_pkg.py`, and `tests/scripts/test_prove_stock_codex_replacement.py::test_stock_codex_compat_pkg_clean_provision_proof_uses_installed_runtime` covers the packaged provisioner contract. This closes clean user-cache file-backed stock Codex provisioning from the installed runtime; stable remote acquisition from the installed runtime is covered by the adjacent update-acquisition gate. It does not prove clean auth onboarding, signing, notarization, stapling, or Gatekeeper behavior. |
| Pkg-installed runtime stable stock Codex update acquisition | `replacement-ready` for clean-user stable remote acquisition from the installed runtime without persistent promotion | `scripts/prove_stock_codex_replacement.py --proof stock-codex-compat-pkg-update-acquisition --codex-path /Users/joshuakaunert/.local/omnigent/codex-stock/0.142.5/codex` builds the unsigned `.pkg`, expands it, stages the payload under a temporary installed-root shape, validates the package manifests, then executes `runtime/scripts/provision_stock_codex.py` from that installed runtime against a clean temporary `HOME`. The proof reads Homebrew cask metadata with auto-update disabled, validates policy `official-openai-github-release`, writes a temporary OpenAI GitHub release channel manifest, copies the current stock Codex into a temp current path, proves the installed provisioner fails closed without `--allow-remote-channel-download` and without blocked-cache mutation, then reruns with explicit opt-in and expected SHA-256. On 2026-07-07 the live run selected stable cask `0.142.5`, downloaded `https://github.com/openai/codex/releases/download/rust-v0.142.5/codex-aarch64-apple-darwin.tar.gz`, verified cask SHA-256 `7156b19962735c9cfb555cdd7babe8c40e7976881f8712b781199219d2e3a707`, extracted `codex-aarch64-apple-darwin`, staged a channel payload with binary SHA-256 `0d9a9da26e49e62b2c36f11229920287fc05576e77140ec63621ef6fdb2ddcd1`, reported launcher update and rollback intent, proved `stage-ready` reuse without another remote-download flag or mutation, and kept host cache paths out of emitted plans. The proof emits package and source-bundle SHA-256 values as run evidence; those values are not pinned in this row because the package includes this documentation. Unit coverage in `tests/scripts/test_prove_stock_codex_replacement.py::test_stock_codex_compat_pkg_update_acquisition_proof_uses_installed_runtime` covers the installed-runtime command shape, explicit-download block, staged acquisition, non-mutating reuse, rollback intent, resolver selection, and host-cache isolation with fake package staging and fake stock Codex. This closes stable remote stock-Codex acquisition from the pkg-installed runtime. It does not prove scheduled updates, persistent launcher pointer promotion, alpha/pre-release adoption, independent signature verification, real `/Library` installation, or Gatekeeper behavior. |
| Pkg-installed runtime stable stock Codex update promotion | `replacement-ready` for clean-user persistent launcher pointer promotion and rollback from the installed runtime | `scripts/prove_stock_codex_replacement.py --proof stock-codex-compat-pkg-update-promotion --codex-path /Users/joshuakaunert/.local/omnigent/codex-stock/0.142.5/codex` builds the unsigned `.pkg`, expands it, stages the payload under a temporary installed-root shape, validates the package manifests, then executes `runtime/scripts/provision_stock_codex.py` from that installed runtime against a clean temporary `HOME`. The proof stages the stable official Homebrew/OpenAI GitHub release target with explicit remote-download opt-in, verifies the installed provisioner reports target-ready launcher promotion intent, then reruns the installed provisioner with `--promote-update --rollback-metadata <path>` so the installed runtime owns the persistent launcher update. That command updates only the clean user's launcher manifest `pinnedCodexPath` and `OMNIGENT_STOCK_CODEX_PATH` env contract to the staged target and writes adjacent rollback metadata. The proof reruns the installed-runtime plan without `--current-codex` or another remote-download flag and verifies `action=up-to-date`, `mutatesFilesystem=false`, and `promotion.required=false`. It then invokes `--rollback-update <metadata>`, restores the previous temp current Codex pointer, proves resolver selection for the restored pointer, and verifies the plan returns to `stage-ready` without mutation. The proof emits package and source-bundle SHA-256 values as run evidence; those values are not pinned in this row because the package includes this documentation. Unit coverage in `tests/scripts/test_prove_stock_codex_replacement.py::test_stock_codex_compat_pkg_update_promotion_proof_promotes_and_rolls_back` covers installed-runtime acquisition, command-backed manifest promotion, rollback metadata, command-backed rollback restoration, post-promotion suppression, resolver selection, and host-cache isolation with fake package staging and fake stock Codex. This closes persistent update pointer promotion and rollback from the pkg-installed runtime. It does not prove automatic update scheduling, alpha/pre-release adoption, independent archive signature verification, real `/Library` installation, LaunchDaemon/LaunchAgent behavior, or Gatekeeper behavior. |
| Pkg-installed runtime clean auth onboarding | `replacement-ready` for packaged-runtime auth classification and guided setup boundary | `scripts/prove_stock_codex_replacement.py --proof stock-codex-compat-pkg-clean-auth-onboarding --codex-path /Users/joshuakaunert/.local/omnigent/codex-stock/0.142.5/codex` built the unsigned `.pkg`, expanded and staged it under a temporary installed-root shape, provisioned stock Codex `0.142.5` into the clean user cache from the installed runtime's `provision_stock_codex.py`, then ran the packaged runtime's own `omnigent.codex_native` auth classifier in subprocesses with `PYTHONPATH=<installed-runtime>`. The proof verified the current real stock auth source `/Users/joshuakaunert/.codex/auth.json` is available without printing credential material, verified a clean `CODEX_HOME` resolves `<clean-codex-home>/auth.json` and reports `needs-auth`, verified a synthetic populated `auth.json` reports available, verified the classifier used the clean-provisioned stock Codex path, and emitted a guided setup command shaped as `CODEX_HOME=<clean-codex-home> <clean-cache>/0.142.5/codex login`. The proof used stock Codex SHA-256 `0d9a9da26e49e62b2c36f11229920287fc05576e77140ec63621ef6fdb2ddcd1` and package SHA-256 `6438abbcbdb09df91ab02e5ae918e0fe3fec83f977170dc133a76c32a2435677`. Unit coverage in `tests/scripts/test_prove_stock_codex_replacement.py::test_stock_codex_compat_pkg_clean_auth_proof_uses_installed_runtime` covers the packaged classifier path with fake stock Codex and auth fixtures. This closes clean auth classification and guided onboarding from the installed runtime. It does not automate browser/device login, validate token freshness with OpenAI, copy credentials to another machine, sign, notarize, staple, or prove Gatekeeper behavior. |
| Signed/notarized stock Codex compatibility macOS pkg | `replacement-ready` for Developer ID signed, notarized, stapled, Gatekeeper-accepted, and persistable `.pkg` distribution | `scripts/build_stock_codex_compat_pkg.py` accepts an optional Developer ID Installer signing identity and keychain and builds signed packages with `pkgbuild --sign ... --timestamp` while preserving the unsigned package gate. `scripts/prove_stock_codex_replacement.py --proof stock-codex-compat-pkg-signed-notarized --notarytool-profile OmnigentExperiment --pkg-output-path <artifact.pkg>` classifies signing/notary prerequisites, builds the signed package at the requested artifact path, validates `pkgutil --check-signature`, submits it with `xcrun notarytool submit --output-format json`, waits on the returned submission id with `xcrun notarytool wait`, staples it with `xcrun stapler staple`, validates with `xcrun stapler validate`, and runs `spctl -a -vv -t install`. On the credential-backed rerun, the proof reported `status=replacement-ready`, autodiscovered `Developer ID Installer: Joshua Kaunert (HSRQC9N69B)`, used notarytool profile `OmnigentExperiment`, found one Developer ID Installer identity and one Developer ID Application identity, built package identifier `ai.omnigent.stock-codex-compat` version `0.3.0.dev0`, reported final stapled package SHA-256 `68f71a7a20d4f8059cd8f7a812096d045dbdab1fa7baf07df50f11dd86687fe3` and source bundle SHA-256 `f712e8eedc9bbf9e0615a2a96a81f7cff8cb9175e1cbbb03eff487cc36fba73b`, verified `signature_status=signed by a developer certificate issued by Apple for distribution`, received notary submission `f45b29fc-a635-4ff1-8836-81c0e629d9b0` with status `Accepted`, stapled successfully, validated successfully, and `spctl` accepted the package with source `Notarized Developer ID` and origin `Developer ID Installer: Joshua Kaunert (HSRQC9N69B)`. Unit coverage in `tests/scripts/test_build_stock_codex_compat_pkg.py::test_pkgbuild_command_includes_developer_id_signing_args`, `tests/scripts/test_prove_stock_codex_replacement.py::test_stock_codex_compat_pkg_signed_notarized_blocks_when_prereqs_missing`, `tests/scripts/test_prove_stock_codex_replacement.py::test_stock_codex_compat_pkg_signing_prereqs_explain_application_identity_mismatch`, and `tests/scripts/test_prove_stock_codex_replacement.py::test_stock_codex_compat_pkg_signed_notarized_runs_distribution_checks` covers signing argv, blocked-prereq classification, Application-vs-Installer mismatch reporting, explicit artifact output, and the notarize/staple/Gatekeeper command sequence without requiring real credentials. This closes the user-context signed/notarized `.pkg` artifact producer; it does not perform a persistent `/Library` install, LaunchServices registration, app-bundle distribution, update scheduling, or clean-machine live model turn from the installed package. |
| Signed/notarized stock Codex compatibility pkg installer lifecycle | `replacement-ready` for admin-authenticated package-manager install, receipt validation, installed-runtime clean adapter bootstrap/doctor, and cleanup | `scripts/prove_stock_codex_replacement.py --proof stock-codex-compat-pkg-installer-lifecycle --codex-path /Users/joshuakaunert/.local/omnigent/codex-stock/0.142.5/codex --pkg-path <artifact.pkg>` supports the production split: it consumes an already signed/notarized package, validates package structure, signature, stapled ticket, and Gatekeeper acceptance without signing credentials, then requires root/admin privileges only for the macOS installer lifecycle. On 2026-07-07 the admin-authenticated consumer run used prebuilt package SHA-256 `68f71a7a20d4f8059cd8f7a812096d045dbdab1fa7baf07df50f11dd86687fe3`, Gatekeeper source `Notarized Developer ID`, and origin `Developer ID Installer: Joshua Kaunert (HSRQC9N69B)`. The proof created a temporary HFS+ target image, installed with `/usr/sbin/installer -target <mountpoint>`, validated `pkgutil --volume <mountpoint>` receipt package id `ai.omnigent.stock-codex-compat`, version `0.3.0.dev0`, receipt file count `2884`, and required runtime payload files, then ran the installed runtime against a separate clean temporary `HOME`. That clean profile installed the default adapter package with `action=adapter-package-installed`, `mutatesFilesystem=True`, ran doctor with `installAllowed=True` and `mutatesFilesystem=False`, removed the installed payload, forgot the target-volume receipt, proved the receipt absent, and detached the temporary image. `tests/scripts/test_build_stock_codex_compat_pkg.py::test_postinstall_validates_target_volume_payload` covers the target-volume-aware `postinstall`; `tests/scripts/test_prove_stock_codex_replacement.py::test_stock_codex_compat_pkg_installer_lifecycle_blocks_without_root` covers the legacy one-step admin-prereq block before build/notary; `tests/scripts/test_prove_stock_codex_replacement.py::test_stock_codex_compat_pkg_installer_lifecycle_prebuilt_blocks_after_validation` covers prebuilt package validation before the root block; and `tests/scripts/test_prove_stock_codex_replacement.py::test_stock_codex_compat_pkg_installer_lifecycle_uses_mounted_target` covers mounted-target install, receipt, adapter-package bootstrap, doctor, cleanup, and detach lifecycle with fake tools. This closes the split signed/notarized package-manager lifecycle proof without performing a persistent install into this host's real `/Library`, LaunchServices registration, app-bundle distribution, update scheduling, or clean-machine live model turn from a newly installed package. |
| Signed/notarized stock Codex compatibility pkg clean-user canary | `replacement-ready` for admin-authenticated signed-pkg install plus clean-user stock Codex provisioning, launcher bootstrap, auth classification, rollback, and receipt cleanup | `scripts/prove_stock_codex_replacement.py --proof stock-codex-compat-pkg-clean-user-canary --codex-path /Users/joshuakaunert/.local/omnigent/codex-stock/0.142.5/codex --pkg-path <artifact.pkg>` consumes the signed/notarized package from the producer gate, validates the prebuilt package, installs it with macOS installer onto a temporary mounted target volume, then runs the installed runtime from that target volume against a clean temporary `HOME`. On 2026-07-07 the admin-authenticated canary used package SHA-256 `68f71a7a20d4f8059cd8f7a812096d045dbdab1fa7baf07df50f11dd86687fe3`, stock Codex `codex-cli 0.142.5`, and stock Codex SHA-256 `0d9a9da26e49e62b2c36f11229920287fc05576e77140ec63621ef6fdb2ddcd1`. The canary validated receipt package id `ai.omnigent.stock-codex-compat`, version `0.3.0.dev0`, and required runtime payload files, provisioned stock Codex into `<clean-home>/.local/omnigent/codex-stock/0.142.5/codex` from the installed runtime's provisioner with `sourceKind=channel`, installed the default adapter package, installed `~/.local/bin/omnigent-stock-codex-compat`, verified PATH selection, delegated `--version` to `codex-cli 0.142.5`, verified the launcher probe pinned the clean-provisioned stock Codex and installed runtime, ran doctor with `existingTargetState=managed`, `targetSelectedOnPath=True`, and `mutatesFilesystem=False`, classified a clean `CODEX_HOME` as `needs-auth`, executed the generated rollback command, removed launcher plus manifest, removed the installed package payload from the temporary target volume, forgot the target-volume receipt, proved receipt absence, and detached the image. Unit coverage in `tests/scripts/test_prove_stock_codex_replacement.py::test_stock_codex_compat_pkg_clean_user_canary_uses_installed_pkg_runtime` covers the joined package-manager install, clean provisioning, clean launcher bootstrap, clean auth, rollback, receipt cleanup, and detach sequence with fake tools. This is the strongest current production-shaped canary while still avoiding persistent installation into this host's real `/Library`; it does not prove a separate clean physical/virtual machine, automated browser/device login, LaunchServices registration, app-bundle distribution, scheduled update agents, or a live model turn from the newly installed clean user profile. |
| Signed/notarized stock Codex compatibility pkg external clean-user gate | `replacement-ready` for an admin-authenticated marked throwaway home; separate macOS account/VM evidence still pending | `scripts/prove_stock_codex_replacement.py --proof stock-codex-compat-pkg-external-clean-user --codex-path /Users/joshuakaunert/.local/omnigent/codex-stock/0.142.5/codex --pkg-path <artifact.pkg> --clean-user-home <home>` consumes the same signed/notarized package artifact and requires `<home>/.omnigent-stock-codex-compat-clean-user-ok` before it will mutate the supplied profile. It refuses homes with preexisting compatibility launcher, manifest, adapter package, Codex stock cache, clean auth canary, or in-flight proof state. On the admin-authenticated rerun, the gate used package SHA-256 `68f71a7a20d4f8059cd8f7a812096d045dbdab1fa7baf07df50f11dd86687fe3`, validated Gatekeeper source `Notarized Developer ID`, installed the signed package onto a temporary mounted target volume, validated receipt package id `ai.omnigent.stock-codex-compat`, version `0.3.0.dev0`, and required runtime payload files, provisioned stock Codex `0.142.5` into a marked `/private/tmp` throwaway home with `sourceKind=channel`, installed the default adapter package, installed and selected `~/.local/bin/omnigent-stock-codex-compat`, verified `--version` plus launcher probe delegation, ran non-mutating doctor, classified proof-scoped `CODEX_HOME` as `needs-auth`, executed the generated rollback command, removed canary-created user state while preserving only the operator marker, removed package payload and receipt state from the temporary target volume, and detached the image. Unit coverage in `tests/scripts/test_prove_stock_codex_replacement.py::test_stock_codex_compat_pkg_external_clean_user_requires_marked_home` and `tests/scripts/test_prove_stock_codex_replacement.py::test_stock_codex_compat_pkg_external_clean_user_uses_marked_home` covers marker enforcement, prebuilt package validation, mounted-target install, external-home provisioning, launcher bootstrap, proof-scoped `CODEX_HOME` and uv scratch env, auth classification, rollback, user-state cleanup, receipt cleanup, and detach with fake tools. This creates and validates the clean-user/VM proof surface without silently creating macOS users or modifying a real `/Library`; it does not yet prove a separate macOS account, Fast User Switching/loginwindow state, user keychain behavior, or a clean VM. |
| Signed/notarized stock Codex compatibility pkg clean-VM automation | `replacement-ready` for disposable Tart macOS VM real-`/Library` install, VM-user runtime staging, bootstrap, auth classification, rollback, and receipt cleanup | `scripts/prove_stock_codex_replacement.py --proof stock-codex-compat-pkg-clean-vm --codex-path /Users/joshuakaunert/.local/omnigent/codex-stock/0.142.5/codex --pkg-path /private/tmp/omnigent-stock-codex-compat-pkg-proof.EHfs5j/omnigent-stock-codex-compat.pkg --clean-vm-tart-name omnigent-clean --clean-vm-ssh-user admin` now passes against a disposable Tart Tahoe VM after VM bootstrap supplied key SSH, `uvx`, noninteractive `sudo -n`, and the clean-user marker. The gate transfers the signed/notarized package plus a file-backed stock Codex channel artifact into the VM, refuses preexisting user/package state, validates Gatekeeper source `Notarized Developer ID`, installs package `ai.omnigent.stock-codex-compat` version `0.3.0.dev0` into the VM's real `/Library`, validates the receipt, stages the immutable machine runtime from `/Library/Application Support/Omnigent/stock-codex-compat/runtime` into the VM user's writable `~/.local/omnigent/stock-codex-compat/runtime`, runs `uvx` from that staged runtime, provisions stock Codex `codex-cli 0.142.5` with SHA-256 `0d9a9da26e49e62b2c36f11229920287fc05576e77140ec63621ef6fdb2ddcd1`, installs the default adapter package, installs and selects `~/.local/bin/omnigent-stock-codex-compat`, delegates `--version`, runs doctor with `existingTargetState=managed`, `targetSelectedOnPath=True`, and `mutatesFilesystem=False`, classifies clean proof-scoped auth as `needs-auth`, uninstalls the user launcher, removes created user state, removes `/Library/Application Support/Omnigent/stock-codex-compat`, forgets the package receipt, and removes the remote work directory. The successful VM run used signed package SHA-256 `68f71a7a20d4f8059cd8f7a812096d045dbdab1fa7baf07df50f11dd86687fe3`. The live gate exposed and fixed four release-relevant script issues: user-local `uvx` was not on the SSH PATH, direct `uvx --from /Library/.../runtime` failed because the installed source tree is root-owned, the shell version parser reduced `codex-cli 0.142.5` to `2.5`, and `grep -q` under `pipefail` turned a successful launcher probe into exit `141`; it also now exports proof-scoped `OMNIGENT_STOCK_CODEX_PATH` before auth classification. Unit coverage in `tests/scripts/test_prove_stock_codex_replacement.py::test_stock_codex_compat_pkg_clean_vm_requires_target`, `tests/scripts/test_prove_stock_codex_replacement.py::test_stock_codex_compat_pkg_clean_vm_blocks_missing_tart_vm`, `tests/scripts/test_prove_stock_codex_replacement.py::test_clean_vm_remote_script_requires_marker_and_noninteractive_sudo`, and `tests/scripts/test_prove_stock_codex_replacement.py::test_clean_vm_ssh_command_avoids_persistent_known_hosts` covers fail-closed target selection, missing Tart VM classification, marker enforcement, user-local PATH setup, noninteractive sudo shape, staged user runtime execution, first-version-token parsing, probe capture, proof-scoped stock Codex export, remote script contract, and non-persistent SSH known-hosts behavior. This closes the live clean-VM signed-pkg automation gate; it does not yet prove remote stock-Codex GitHub acquisition from inside the VM, automated first-boot VM setup from a raw public image, a packaged product-owned bootstrap command that performs the staged-runtime copy outside this proof harness, browser/device auth login, scheduled update agents, or a clean-machine live model turn from the installed launcher. |
| Omnigent-owned stock Codex wrapper relay-tool execution | `blocked` at stock `exec` MCP relay-tool invocation | `--proof stock-codex-compat-wrapper-relay-tool` now starts the real Omnigent `tool_relay.json` sidecar via `start_tool_relay`, advertises a deterministic `omnigent_wrapper_relay_probe` MCP tool from a temp-scoped Codex-native bridge root, launches stock Codex through the source-owned wrapper, and enables every current stock-Codex feature that can be generically enabled from this binary. The proof explicitly skips `rollout_budget` because the CLI rejects `--enable rollout_budget` without structured config, and skips `shell_zsh_fork`/`unified_exec_zsh_fork` because this downloaded stock binary lacks the packaged zsh-fork runtime. The first live attempt returned `RELAY_TOOL_MISSING`; after adding the full-feature-compatible flag set and an explicit `tool_search` fallback, the sharper validator still reported `Expected exactly one Omnigent relay executor call ... found 0`. `codex debug prompt-input` did not mention the relay tool, but that is only diagnostic because prompt-input renders messages, not necessarily the separate tool schema list. Current read: the wrapper can preserve stock command events, but stock `codex exec` is not invoking Omnigent relay tools advertised only through the sidecar. This blocks the generated adapter-tool-through-stock-MCP claim until we add a stronger stock-Codex tool exposure path, an Omnigent-owned wrapper-side tool bridge, or prove the correct deferred-tool/search contract for external MCP tools. |
| Temporary macOS app-bundle entrypoint rehearsal | `replacement-ready` for a non-installed `.app` launcher shape | `scripts/prove_stock_codex_replacement.py --proof app-bundle-entrypoint` creates a temporary `Omnigent Codex.app` bundle with a generated `Contents/Info.plist` and executable `Contents/MacOS/omnigent-codex`, validates the plist keys, directly runs the executable probe, and verifies the entrypoint exports `OMNIGENT_STOCK_CODEX_PATH=<stock codex>` before delegating to `uvx --from <repo> omnigent codex`. The current green run used stock Codex `0.142.2`, bundle identifier `ai.omnigent.codex`, executable `omnigent-codex`, and a temporary app bundle that was removed after proof. This proves the user-facing app-entrypoint shape without mutating the stock Codex app, `/Applications`, LaunchServices, Dock/Finder defaults, shell profiles, or persistent launcher state; it does not prove signing, notarization, packaging, Sparkle/update behavior, or production app installation. |
| Isolated Codex launcher activation rehearsal | `replacement-ready` for temporary PATH shadowing, pinned stock-Codex delegation, no-recursion lookup, and rollback | `scripts/prove_stock_codex_replacement.py --proof launcher-activation` creates a temporary versioned pinned target under `omnigent/codex-stock/<version>/codex` by copying the current stock Codex binary, creates a temporary `codex` shim, prepends only that temp shim directory to `PATH` inside the proof process, and proves `codex` resolves to the shim during activation. The shim exports `OMNIGENT_STOCK_CODEX_PATH=<pinned target>` before delegation, and Omnigent's central Codex resolver selects that pinned binary instead of the shadowed `codex` command. The proof still verifies the sanitized PATH no longer points at the shim and can resolve the original stock Codex at `/opt/homebrew/bin/codex`, whose realpath was `/opt/homebrew/Caskroom/codex/0.142.2/codex-aarch64-apple-darwin`; it also verifies the delegate shape `/Users/joshuakaunert/.local/bin/uvx --from /Users/joshuakaunert/Developer/HarnessEngineering/omnigent-upstream-audit omnigent codex`. After the scoped activation, `PATH` lookup restores to `/opt/homebrew/bin/codex`. This proves a rollback-first launcher shape can avoid recursive `codex` lookup and can target a managed pinned stock-Codex binary, not a persistent shell alias, app launcher, production-default mutation, persistent provisioner execution, remote downloader/update channel, or live Codex TUI launch. |
| Persistent Omnigent `codex` launcher/default | `replacement-ready` for the current-host Homebrew-bin default with rollback | `scripts/install_omnigent_codex_launcher.py` installs a managed launcher at the selected `codex` path, writes a manifest, preserves `codex --version` by delegating it to the pinned stock binary, probes with `--omnigent-launcher-probe`, exports `OMNIGENT_STOCK_CODEX_PATH` before normal delegation to `uvx --from <repo> omnigent codex`, backs up an existing unmanaged target, and uninstalls only when the target carries the Omnigent marker. `omnigent.inner.codex_executor._find_codex_cli()` detects the managed launcher marker and manifest so inner Omnigent sessions resolve to the pinned stock binary instead of recursing into the launcher. On 2026-06-28, `/opt/homebrew/bin/codex` was replaced by the managed launcher, the original Homebrew symlink was preserved at `/opt/homebrew/bin/codex.omnigent-backup-20260628T091032Z`, `codex --version` returned `codex-cli 0.142.2`, `codex --omnigent-launcher-probe` returned `OMNIGENT_CODEX_PERSISTENT_LAUNCHER_OK`, and `scripts/prove_stock_codex_replacement.py --proof graph --live-proof-timeout 180` with no explicit `--codex-path` resolved to `/Users/joshuakaunert/.local/omnigent/codex-stock/0.142.2/codex` and passed in 33.3s after an actual rollback/reinstall cycle. Rollback command: `uvx --from /Users/joshuakaunert/Developer/HarnessEngineering/omnigent-upstream-audit python /Users/joshuakaunert/Developer/HarnessEngineering/omnigent-upstream-audit/scripts/install_omnigent_codex_launcher.py --uninstall --launcher-path /opt/homebrew/bin/codex --manifest-path /Users/joshuakaunert/.local/omnigent/launchers/codex.json`. This proves current-host default mutation and rollback execution, not a remote download/update channel, clean-auth onboarding, cross-machine portability, or app-bundle launcher mutation. |

2026-07-04 `0.142.5` rerun note: the current-host pinned stock payload and
managed `/opt/homebrew/bin/codex` launcher were refreshed from the official
Homebrew/OpenAI GitHub release archive to `codex-cli 0.142.5`. The
`stock-codex-compat-launcher-doctor`,
`stock-codex-compat-wrapper-apple-docs-bridge-adapter`,
`stock-codex-compat-wrapper-xcodebuild-bridge-adapter`, explicit
`cutover-ready`, and no-explicit-path `default-path-cutover` gates were rerun
against the refreshed payload and passed. Older `0.142.2` rows above remain
historical evidence for the original proof sequence, not the current safe
production pin. The persistent `stock-codex-compat` adapter package was also
installed at `~/.local/omnigent/stock-codex-compat/adapter-package`, rerun as a
non-mutating reuse, and validated by launcher doctor defaults without explicit
`--adapter-bin` or `--adapter-manifest` arguments. The separate compatibility
launcher command was installed at `~/.local/bin/omnigent-stock-codex-compat`,
validated as PATH-selected, uninstalled to prove rollback, then reinstalled as
the final host state. The `stock-codex-compat-clean-install` proof then proved
the same default-path install, doctor, probe, version delegation, and rollback
sequence under a temporary clean `HOME`.

2026-07-05 packaging note: `scripts/build_stock_codex_compat_bundle.py` now
builds an unsigned portable `omnigent-stock-codex-compat-bundle.tar.gz`
containing the runtime source needed by `uvx --from <extracted-runtime>`, and
`stock-codex-compat-bundle-install` proved build, SHA-256 verification, safe
extraction, clean-home install, doctor, probe, version delegation, extracted
runtime manifest wiring, and rollback from that artifact. The follow-on
`scripts/build_stock_codex_compat_pkg.py` proof now builds an unsigned flat
macOS `.pkg` from that portable bundle and inspects identifier, version,
install root, script presence, unsigned signature status, sanitized manifests,
and required runtime payload files without installing it.

2026-07-06 package-runtime live note:
`stock-codex-compat-pkg-runtime-live` is green against pinned stock Codex
`0.142.5`. The proof builds the unsigned `.pkg`, expands it without installing
to `Payload/Library/Application Support/Omnigent/stock-codex-compat/runtime`,
then runs `uvx --from <expanded-runtime> omnigent-stock-codex-wrapper` with the
subprocess working directory set to that expanded runtime. It reused known-good
stock auth, enabled every generically enableable stock Codex feature, returned
thread `019f3877-0831-75d1-a0a7-08ea9b5bf29c`, and injected the deterministic
Apple route before `STOCK_CODEX_COMPAT_LIVE_OK`. This closes the live model
turn through expanded package runtime gate, not `/Library` installation,
per-user bootstrap, clean-machine stock-Codex provisioning, clean auth
onboarding, signing, notarization, stapling, or Gatekeeper validation.

2026-07-06 installed-runtime bootstrap note:
`stock-codex-compat-pkg-user-bootstrap` is green against pinned stock Codex
`0.142.5`. The proof stages the `.pkg` payload under a temporary installed-root
shape, runs the installed runtime's `install_stock_codex_compat_launcher.py`
against a clean temporary `HOME`, installs the default adapter package and
`omnigent-stock-codex-compat` command, verifies version/probe/PATH selection,
verifies the launcher manifest points back to the installed runtime, force
updates the managed launcher, then executes the generated rollback command. The
rollback command itself runs through `uvx --from <installed-runtime>` and
removes both launcher and manifest. This closes per-user bootstrap from the
installed runtime, not real `/Library` installation, clean-machine stock-Codex
provisioning, clean auth onboarding, signing, notarization, stapling, or
Gatekeeper validation.

2026-07-06 clean stock-Codex provisioning note:
`stock-codex-compat-pkg-clean-provision` is green against pinned stock Codex
`0.142.5`. The package runtime now carries `scripts/provision_stock_codex.py`;
the proof stages the `.pkg` payload under a temporary installed-root shape,
runs that installed provisioner under a clean temporary `HOME`, provisions a
channel-provenance stock Codex payload into the clean user cache, verifies
`OMNIGENT_STOCK_CODEX_PATH`, verifies Omnigent resolver selection of the clean
payload, proves a second no-force provision reuses the same payload, and checks
the generated manifest/output do not reference the host stock-Codex cache. This
closes clean user-cache stock-Codex provisioning from the installed runtime.
The next canonical gate was clean auth onboarding from the packaged runtime.

2026-07-07 installed-runtime stable acquisition note:
`stock-codex-compat-pkg-update-acquisition` is green against pinned stock Codex
`0.142.5`. The proof builds and stages the `.pkg` runtime under a temporary
installed-root shape, runs its bundled `scripts/provision_stock_codex.py` under
a clean temporary `HOME`, proves stable remote acquisition is blocked without
explicit `--allow-remote-channel-download`, then downloads, verifies, extracts,
and stages the official Homebrew/OpenAI GitHub release archive with channel
provenance. It also proves reuse without another remote-download flag and
keeps host-cache paths out of emitted plans. This closes stable remote
acquisition from the installed runtime, not scheduled updates, persistent
pointer promotion, alpha/pre-release adoption, independent signature
verification, real `/Library` installation, or Gatekeeper behavior.

2026-07-06 packaged clean-auth onboarding note:
`stock-codex-compat-pkg-clean-auth-onboarding` is green against pinned stock
Codex `0.142.5`. The proof stages the `.pkg` payload under a temporary
installed-root shape, provisions stock Codex into the clean user's cache from
the installed runtime, then runs the packaged runtime's auth classifier with
`PYTHONPATH=<installed-runtime>`. It verifies the real stock auth source is
available, a clean `CODEX_HOME` reports `needs-auth`, a synthetic populated
`auth.json` reports available, the clean-provisioned stock Codex path is in
scope, and classifier output does not leak synthetic credential material. This
closes clean auth classification and guided onboarding from the installed
runtime.

2026-07-07 signed/notarized package gate note:
`stock-codex-compat-pkg-signed-notarized` is replacement-ready on this host. The
proof verifies prerequisite state before doing notarization work, then builds,
signs, submits, waits on the returned notary id, staples, validates, and runs
Gatekeeper assessment. The
credential-backed rerun found `pkgbuild`, `pkgutil`, `xcrun`, `spctl`,
`notarytool`, and `stapler`; autodiscovered `Developer ID Installer: Joshua
Kaunert (HSRQC9N69B)`; used notarytool keychain profile
`OmnigentExperiment`; submitted and stapled final package SHA-256
`68f71a7a20d4f8059cd8f7a812096d045dbdab1fa7baf07df50f11dd86687fe3`; received
notary submission `f45b29fc-a635-4ff1-8836-81c0e629d9b0` with status
`Accepted`; stapled and validated successfully; and `spctl` accepted the
package with source `Notarized Developer ID`.

2026-07-07 package-manager installer lifecycle note:
`stock-codex-compat-pkg-installer-lifecycle` now has a validated two-phase
production path: run `stock-codex-compat-pkg-signed-notarized --pkg-output-path
<artifact.pkg>` from the normal user context that owns signing/notary
credentials, then run `stock-codex-compat-pkg-installer-lifecycle --pkg-path
<artifact.pkg>` from an admin-authenticated root context. In non-root prebuilt
mode, the lifecycle proof still validates package structure, signature,
stapled-ticket validation, and Gatekeeper acceptance before reporting the admin
installer prerequisite. The split producer run created
`/private/tmp/omnigent-stock-codex-compat-pkg-proof.EHfs5j/omnigent-stock-codex-compat.pkg`,
received notary submission `f45b29fc-a635-4ff1-8836-81c0e629d9b0` with status
`Accepted`, and reported final stapled package SHA-256
`68f71a7a20d4f8059cd8f7a812096d045dbdab1fa7baf07df50f11dd86687fe3`. The
admin-authenticated consumer then consumed the same artifact, validated
Gatekeeper source `Notarized Developer ID`, installed onto a temporary mounted
target volume, validated receipt metadata and required runtime payload files,
materialized the default adapter package in a separate clean temporary `HOME`,
ran the installed-runtime doctor without filesystem mutation, removed the
installed payload, forgot the target-volume receipt, proved the receipt absent,
and detached the image. The proof path is covered at the harness layer:
target-volume-aware `postinstall` validation, root-prerequisite classification
before one-step build/notary, prebuilt package validation before the root block,
mounted-target install command shape, receipt validation, installed-runtime
adapter-package bootstrap and doctor, payload cleanup, receipt forget, and image
detach all have focused tests.

2026-07-07 clean-user signed-package canary note:
`stock-codex-compat-pkg-clean-user-canary` now consumes the same signed/stapled
package artifact from the producer gate and runs the joined production-shaped
path without installing into the real host `/Library`. The admin-authenticated
run installed the package onto a temporary target volume, validated receipt
metadata and required payload files, provisioned stock Codex `0.142.5` into a
clean user's cache from the installed runtime, installed the default adapter
package and separate compatibility launcher under the clean `HOME`, verified
PATH selection plus version/probe delegation to the clean-provisioned Codex,
ran non-mutating doctor against the managed launcher, classified a clean
`CODEX_HOME` as `needs-auth`, executed the generated rollback command, removed
the launcher and manifest, removed package payload and receipt state from the
target volume, and detached the image. This closes the strongest local canary
short of a separate clean physical or virtual machine.

2026-07-07 external clean-user gate note:
`stock-codex-compat-pkg-external-clean-user` adds the next validation surface
for a marked throwaway macOS user profile or clean VM home. The gate is
deliberately fail-closed: it requires either `--clean-user-home` or
`--clean-user-name`, requires the marker
`.omnigent-stock-codex-compat-clean-user-ok`, refuses preexisting Omnigent
compatibility state in that profile, consumes an existing signed/stapled
package through `--pkg-path`, and still uses a temporary mounted target volume
instead of this host's real `/Library`. When `--clean-user-name` is supplied,
the proof derives or validates the passwd home, rejects root and mismatched
homes, and runs user-level provisioning, launcher bootstrap, auth
classification, and rollback through `sudo -u <clean-user>` with a proof-scoped
environment. The admin-authenticated rerun against a marked `/private/tmp`
throwaway home now reports `replacement-ready` and proves the package install,
receipt validation, external-home provisioning, launcher bootstrap,
proof-scoped `CODEX_HOME`, proof-scoped uv/XDG scratch directories, clean auth
classification, rollback, user-state cleanup, package cleanup, and detach
sequence. A live run against a separate macOS account or clean VM remains
unproven.

2026-07-07 clean-VM automation note:
`stock-codex-compat-pkg-clean-vm` adds the remote disposable-machine proof
surface. The gate can target direct SSH or a Tart VM name, copies the signed
package plus a file-backed stock-Codex channel artifact into the VM, and runs a
real `/Library` package install plus VM-user staged-runtime bootstrap, auth
classification, rollback, payload cleanup, and receipt cleanup. It requires the
same disposable home marker, key SSH, `uvx`, and noninteractive `sudo -n` inside
the VM, so it blocks cleanly for ordinary desktop VMs or unprepared CI images.
On 2026-07-07, Tart `2.32.1` ran the live gate against `omnigent-clean`; the
signed package installed into the VM's real `/Library`, the user-owned staged
runtime avoided root-owned source-tree writes, clean auth classified as
`needs-auth`, and package/user state cleaned up.

This proves the scoped carry-parity claims above plus current-host clean-profile
and default-path rehearsals, unsigned portable artifact rehearsal, expanded
package runtime live model-turn proof, installed-runtime per-user bootstrap,
isolated pinned stock-Codex provisioning, isolated pinned launcher activation,
and current-host persistent `codex` default activation plus temporary
Homebrew/GitHub remote channel download and the local clean-auth onboarding
boundary, temporary macOS app-bundle entrypoint rehearsal, and the first real
generated workflow adapter through the stock-wrapper command surface, including
low-privilege Apple-docs plus XcodeBuildMCP build/run and simulator-test
execution through the packaged file bridge, failed adapter diagnostics
preservation through stock Codex `command_execution` output, plus clean
user-cache stock-Codex provisioning from the pkg-installed runtime, stable
remote stock-Codex acquisition from the pkg-installed runtime, stable update
pointer promotion and rollback from the pkg-installed runtime, clean auth
onboarding from the pkg-installed runtime, and signed/notarized `.pkg`
distribution.
Persistent app-bundle installation, LaunchServices/Dock/Finder default
behavior, persistent update scheduling, LaunchAgent/LaunchDaemon packaging
policy, pre-release stock-Codex channel adoption, automated browser/device
login UX, and broader UI/device bridge coverage remain separate decisions.

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

Apple XcodeBuildMCP type-text CLI adapter proof with the provisioned upstream-fixed AXe
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

Apple XcodeBuildMCP tap CLI adapter proof with the provisioned upstream-fixed AXe
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
local build only when upstream source compilation is intentionally being skipped:

```bash
uvx --from . python scripts/provision_xcode27_axe.py \
  --source-binary /Users/joshuakaunert/Developer/HarnessEngineering/spikes/AXe-xcode27/build_products/axe \
  --no-build \
  --print-shell-env
```

Apple XcodeBuildMCP semantic snapshot CLI adapter proof with the provisioned
upstream-fixed AXe binary:

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

Stock-Codex update doctor:

```bash
uvx --from . python scripts/prove_stock_codex_replacement.py \
  --proof stock-codex-update-doctor \
  --codex-path ~/.local/omnigent/codex-stock/0.142.5/codex
```

The `stock-codex-update-doctor` proof fails closed if `--apple-bundle` or
`--allow-fork-codex` are supplied. It uses the real current stock Codex metadata,
creates an official-policy-shaped synthetic newer artifact in a clean temporary
home, and proves the update planner requires `--channel-policy`, keeps dry-run
planning non-mutating, recognizes preverified targets, emits launcher promotion
and rollback intent only after target readiness, and suppresses promotion when
current already equals the selected target. It does not schedule updates,
promote persistent launcher pointers, adopt pre-release channels, or verify an
independent archive signature.

Stock-Codex update acquisition:

```bash
uvx --from . python scripts/prove_stock_codex_replacement.py \
  --proof stock-codex-update-acquisition \
  --codex-path ~/.local/omnigent/codex-stock/0.142.5/codex
```

The `stock-codex-update-acquisition` proof fails closed if `--apple-bundle` or
`--allow-fork-codex` are supplied. It reads official Homebrew cask metadata,
builds a temporary official OpenAI GitHub release channel manifest, proves
remote acquisition is blocked without `--allow-remote-channel-download`, then
downloads, verifies, safely extracts, and stages the selected archive only with
explicit opt-in and expected SHA-256. It also proves the staged payload can be
reused without another remote-download flag or filesystem mutation, and that
the acquired payload resolves through `OMNIGENT_STOCK_CODEX_PATH`. It does not
schedule updates, promote persistent launcher pointers, adopt pre-release
channels, or verify an independent archive signature.

Pkg-installed runtime stable update acquisition:

```bash
uvx --from . python scripts/prove_stock_codex_replacement.py \
  --proof stock-codex-compat-pkg-update-acquisition \
  --codex-path ~/.local/omnigent/codex-stock/0.142.5/codex
```

The `stock-codex-compat-pkg-update-acquisition` proof fails closed if
`--apple-bundle` or `--allow-fork-codex` are supplied. It builds and expands the
unsigned `.pkg`, stages the runtime under a temporary installed-root shape,
then runs the packaged `runtime/scripts/provision_stock_codex.py` from that
installed runtime against a clean temporary `HOME`. It proves the same stable
official channel acquisition contract as `stock-codex-update-acquisition`, but
from the installed package runtime rather than the development checkout. It
does not schedule updates, promote persistent launcher pointers, adopt
pre-release channels, verify an independent archive signature, perform a real
`/Library` install, or prove Gatekeeper behavior.

Pkg-installed runtime stable update promotion:

```bash
uvx --from . python scripts/prove_stock_codex_replacement.py \
  --proof stock-codex-compat-pkg-update-promotion \
  --codex-path ~/.local/omnigent/codex-stock/0.142.5/codex
```

The `stock-codex-compat-pkg-update-promotion` proof fails closed if
`--apple-bundle` or `--allow-fork-codex` are supplied. It builds and expands
the unsigned `.pkg`, stages the runtime under a temporary installed-root shape,
then runs the packaged `runtime/scripts/provision_stock_codex.py` from that
installed runtime against a clean temporary `HOME`. It stages the stable
official release target, invokes the installed provisioner with
`--promote-update --rollback-metadata <path>` to promote only the clean user's
launcher manifest pointer and env contract to that target, verifies the
post-promotion plan is `up-to-date` without mutation or another remote-download
flag, then invokes `--rollback-update <metadata>` and verifies the plan returns
to `stage-ready`.
It does not schedule updates, adopt pre-release channels, verify an independent
archive signature, perform a real `/Library` install, or prove Gatekeeper
behavior.

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

Pkg-installed runtime clean auth onboarding boundary:

```bash
uvx --from . python scripts/prove_stock_codex_replacement.py \
  --proof stock-codex-compat-pkg-clean-auth-onboarding \
  --codex-path /Users/joshuakaunert/.local/omnigent/codex-stock/0.142.5/codex
```

The `stock-codex-compat-pkg-clean-auth-onboarding` proof builds and stages the
unsigned `.pkg`, provisions stock Codex into a clean user cache from the
installed runtime, then runs the packaged runtime's auth classifier for real,
clean, and synthetic auth profiles. It proves the packaged runtime can guide a
new user to `CODEX_HOME=<clean-codex-home> <clean-cache>/codex login` without
printing credential material. It does not automate browser/device login,
validate token freshness with OpenAI, or copy credentials to another machine.

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

Managed stock-Codex compatibility launcher activation:

```bash
uvx --from . python scripts/prove_stock_codex_replacement.py \
  --proof stock-codex-compat-launcher-activation
```

The `stock-codex-compat-launcher-activation` proof fails closed if
`--apple-bundle`, `--codex-path`, or `--allow-fork-codex` are supplied. It
installs a temporary managed `codex` launcher with the stock-Codex
compatibility manifest, proves Omnigent resolves that launcher back to the
manifest-pinned stock binary without recursion, delegates through real
`uvx --from <repo> omnigent-stock-codex-wrapper`, runs the generated
`fetch_apple_docs` file-bridge adapter under `workspace-write`, and uninstalls
the temporary launcher plus manifest. It does not mutate host defaults or prove
the persistent host install; the separate-command install gate below covers
that current-host policy.

Managed stock-Codex compatibility launcher doctor:

```bash
uvx --from . python scripts/prove_stock_codex_replacement.py \
  --proof stock-codex-compat-launcher-doctor
```

The `stock-codex-compat-launcher-doctor` proof fails closed if `--apple-bundle`
or `--allow-fork-codex` are supplied. It validates the current host install
plan for the compatibility launcher without creating or replacing files:
launcher target, manifest path, pinned stock Codex, `uvx`, generated adapter
manifest, default bridge dir, PATH posture, parent writability,
backup/rollback requirements, and install command shape. The proof script uses
a temporary default-layout adapter package to stay non-mutating; the persistent
package placement is covered by the direct installer gate below.

Persistent stock-Codex compatibility adapter package:

```bash
uvx --from . python scripts/install_stock_codex_compat_launcher.py \
  --install-adapter-package \
  --json

uvx --from . python scripts/install_stock_codex_compat_launcher.py \
  --doctor \
  --pinned-codex-path /Users/joshuakaunert/.local/omnigent/codex-stock/0.142.5/codex \
  --json
```

The default package path is
`~/.local/omnigent/stock-codex-compat/adapter-package`. The installer writes or
reuses the generated `fetch_apple_docs` bridge adapter at `bin/fetch_apple_docs`
plus `adapter-manifest.json`. The doctor command above intentionally omits
`--adapter-bin` and `--adapter-manifest`; it resolves and validates those paths
from `--adapter-package-dir` defaults, then confirms the `0.142.5` pinned stock
Codex plan remains non-mutating. This proves persistent adapter-package
placement, not launcher creation, shell-profile mutation, cross-machine
packaging, or broader bridge-tool coverage.

Persistent separate compatibility launcher command:

```bash
uvx --from . python scripts/install_stock_codex_compat_launcher.py \
  --install \
  --pinned-codex-path /Users/joshuakaunert/.local/omnigent/codex-stock/0.142.5/codex \
  --require-path-selected \
  --json

uvx --from . python scripts/install_stock_codex_compat_launcher.py \
  --doctor \
  --pinned-codex-path /Users/joshuakaunert/.local/omnigent/codex-stock/0.142.5/codex \
  --require-path-selected \
  --force \
  --json
```

Rollback:

```bash
uvx --from /Users/joshuakaunert/Developer/HarnessEngineering/omnigent-upstream-audit \
  python /Users/joshuakaunert/Developer/HarnessEngineering/omnigent-upstream-audit/scripts/install_stock_codex_compat_launcher.py \
  --uninstall \
  --launcher-path /Users/joshuakaunert/.local/bin/omnigent-stock-codex-compat \
  --manifest-path /Users/joshuakaunert/.local/omnigent/launchers/stock-codex-compat.json
```

The persistent command is intentionally separate from `codex`. It validates as
PATH-selected at `~/.local/bin/omnigent-stock-codex-compat`, delegates
`--version` to the pinned stock Codex `0.142.5`, and probes the wrapper
delegate plus adapter package paths without replacing the current `codex`
default. A normal post-install doctor refuses accidental overwrite of the
managed target unless `--force` is supplied.

Clean-home compatibility install rehearsal:

```bash
uvx --from . python scripts/prove_stock_codex_replacement.py \
  --proof stock-codex-compat-clean-install \
  --codex-path /Users/joshuakaunert/.local/omnigent/codex-stock/0.142.5/codex
```

The `stock-codex-compat-clean-install` proof runs the installer CLI under a
temporary clean `HOME`, strips inherited `CODEX_HOME` and
`OMNIGENT_STOCK_CODEX_PATH`, installs the default adapter package, installs the
default separate launcher command, validates PATH selection, version delegation,
launcher probe, and force-aware doctor behavior, then uninstalls and confirms
the launcher plus manifest are removed. It proves the repeatable default-path
install sequence a package or setup command can execute; it does not create a
signed installer artifact, automate stock-Codex download on another machine, or
prove credential onboarding there.

Portable compatibility runtime bundle install rehearsal:

```bash
uvx --from . python scripts/prove_stock_codex_replacement.py \
  --proof stock-codex-compat-bundle-install \
  --codex-path /Users/joshuakaunert/.local/omnigent/codex-stock/0.142.5/codex
```

The `stock-codex-compat-bundle-install` proof builds
`omnigent-stock-codex-compat-bundle.tar.gz`, verifies its SHA-256, safely
extracts the bundle into a temporary directory, runs the bundled installer
from the extracted `runtime/` source root under a temporary clean `HOME`, then
installs, validates, doctors, and rolls back the separate compatibility
command. It verifies the installed launcher manifest and launcher probe point
at the extracted runtime rather than the development checkout. This proves an
unsigned portable artifact rehearsal; it does not prove `.pkg`/`.app` signing,
notarization, remote stock-Codex download on another machine, or credential
onboarding there.

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

Current stock-Codex `0.142.5` refresh status on 2026-07-04: the Homebrew/OpenAI
GitHub remote-channel rehearsal selected cask version `0.142.5`, downloaded
`https://github.com/openai/codex/releases/download/rust-v0.142.5/codex-aarch64-apple-darwin.tar.gz`,
verified cask archive SHA-256
`7156b19962735c9cfb555cdd7babe8c40e7976881f8712b781199219d2e3a707`,
extracted `codex-aarch64-apple-darwin`, verified `codex-cli 0.142.5`, installed
a temporary channel payload with binary SHA-256
`0d9a9da26e49e62b2c36f11229920287fc05576e77140ec63621ef6fdb2ddcd1`, and proved
Omnigent resolver selection. The same channel artifact was then provisioned
persistently at
`/Users/joshuakaunert/.local/omnigent/codex-stock/0.142.5/codex` with
`sourceKind: channel` provenance. The existing Omnigent-managed
`/opt/homebrew/bin/codex` launcher was reinstalled with `--force` to point at
that payload while preserving the original Homebrew backup path
`/opt/homebrew/bin/codex.omnigent-backup-20260628T091032Z`. Validation showed
`which codex` selects `/opt/homebrew/bin/codex`, `codex --version` returns
`codex-cli 0.142.5`, the launcher probe reports
`OMNIGENT_CODEX_PERSISTENT_LAUNCHER_OK`, and the launcher manifest now records
`pinnedCodexPath=/Users/joshuakaunert/.local/omnigent/codex-stock/0.142.5/codex`.
An explicit `cutover-ready` rerun with
`--codex-path /Users/joshuakaunert/.local/omnigent/codex-stock/0.142.5/codex`
passed graph, router matrix, tool-plane, Apple memory MCP, Apple-docs CLI,
XcodeBuildMCP CLI build/install/launch, and read-only XcodeBuildMCP discovery.
The no-explicit-path `default-path-cutover` rerun also resolved through `PATH`
to the managed `0.142.5` payload and passed the same aggregate. This refresh
closes the stale pinned-stock-Codex gap for the current host default; it does
not change the remaining production gaps around cross-machine install
packaging, app-bundle signing or notarization, automated auth UX, broader
bridge-tool coverage, or raw unwrapped stock-Codex route parity.

Current persistent compatibility launcher command status on 2026-07-04: the
default separate launcher command was installed at
`/Users/joshuakaunert/.local/bin/omnigent-stock-codex-compat` with manifest
`/Users/joshuakaunert/.local/omnigent/launchers/stock-codex-compat.json`,
pinned stock Codex
`/Users/joshuakaunert/.local/omnigent/codex-stock/0.142.5/codex`, adapter
package
`/Users/joshuakaunert/.local/omnigent/stock-codex-compat/adapter-package`, and
bridge dir
`/Users/joshuakaunert/.local/omnigent/stock-codex-compat/adapter-bridge`.
Validation showed `which omnigent-stock-codex-compat` selects the installed
command, `omnigent-stock-codex-compat --version` returns `codex-cli 0.142.5`,
and the launcher probe reports the expected pinned env, route prefix, adapter
paths, and wrapper delegate. The recorded rollback command was exercised and
removed both launcher and manifest; absence was confirmed, then the launcher was
reinstalled. A force-aware post-install doctor reports the managed target is
PATH-selected, reinstall is allowed with `--force`, and the check is
non-mutating. This proves the current-host production-shaped separate command
without changing the existing `codex` default.

Current clean-home compatibility install status on 2026-07-04:
`--proof stock-codex-compat-clean-install --codex-path
/Users/joshuakaunert/.local/omnigent/codex-stock/0.142.5/codex` passed. The
proof created a temporary clean `HOME`, installed the default adapter package
under `home/.local/omnigent/stock-codex-compat/adapter-package`, installed the
default launcher under `home/.local/bin/omnigent-stock-codex-compat`, verified
PATH selection, verified `--version` returned `codex-cli 0.142.5`, probed the
expected wrapper delegate and adapter paths, ran a force-aware doctor with
`installAllowed=True`, `existingTargetState=managed`,
`targetSelectedOnPath=True`, and `mutatesFilesystem=False`, then uninstalled and
confirmed launcher and manifest removal. The temporary profile was removed
after proof. This closes the clean-profile repeatability contract for a package
or setup command, not a signed installer artifact, remote stock-Codex download
on another machine, or auth onboarding there.

Current portable compatibility bundle status on 2026-07-05:
`--proof stock-codex-compat-bundle-install --codex-path
/Users/joshuakaunert/.local/omnigent/codex-stock/0.142.5/codex` passed. The
proof built an unsigned `omnigent-stock-codex-compat-bundle.tar.gz`, verified
the generated archive SHA-256, safely extracted it, ran the bundled installer
from the extracted `runtime/` source root, installed the default adapter
package and separate compatibility launcher under a temporary clean `HOME`,
verified PATH selection and
`codex-cli 0.142.5` version delegation, probed the wrapper delegate and adapter
paths, verified the installed launcher manifest `repoRoot` pointed at the
extracted runtime instead of the development checkout, ran a force-aware
non-mutating doctor, then uninstalled and confirmed launcher plus manifest
removal. This closes the unsigned portable artifact rehearsal, not signing,
notarization, remote stock-Codex provisioning on another machine, or auth
onboarding there.

Current unsigned compatibility `.pkg` structure status on 2026-07-06:
`--proof stock-codex-compat-pkg-structure` passed. The proof built an unsigned
flat package from the portable runtime bundle, expanded/inspected it without
installing it, verified identifier `ai.omnigent.stock-codex-compat`, version
`0.3.0.dev0`, install location `/`, install prefix
`/Library/Application Support/Omnigent/stock-codex-compat`, archive entries
`Bom`, `PackageInfo`, `Payload`, and `Scripts`, script `postinstall`,
`signatureStatus=no signature`, sanitized `bundle-manifest.json` source root
`<omitted-from-pkg>`, and required payload files for `pkg-manifest.json`,
`bundle-manifest.json`, `runtime/pyproject.toml`,
`runtime/scripts/install_stock_codex_compat_launcher.py`,
`runtime/scripts/provision_stock_codex.py`, and
`runtime/omnigent/stock_codex_compat_wrapper.py`. This closes only the unsigned
structure gate; live runtime relocation, per-user bootstrap, clean stock-Codex
provisioning, clean auth onboarding, signing, notarization, stapling, and
Gatekeeper validation remain separate gates.

Current expanded compatibility `.pkg` runtime live status on 2026-07-06:
`--proof stock-codex-compat-pkg-runtime-live --codex-path
/Users/joshuakaunert/.local/omnigent/codex-stock/0.142.5/codex
--live-proof-timeout 300` passed. The proof expanded the generated package
without installing it, verified the runtime files under
`Payload/Library/Application Support/Omnigent/stock-codex-compat/runtime`, ran
`uvx --from <expanded-runtime> omnigent-stock-codex-wrapper`, reused known-good
stock auth, enabled the current generically enableable stock Codex feature set,
and returned routed thread `019f3877-0831-75d1-a0a7-08ea9b5bf29c` with
`Routing: orchestrator-led` before `STOCK_CODEX_COMPAT_LIVE_OK`. This closes
runtime relocation plus live model turn from the expanded package runtime.

Current installed-runtime per-user bootstrap status on 2026-07-06:
`--proof stock-codex-compat-pkg-user-bootstrap --codex-path
/Users/joshuakaunert/.local/omnigent/codex-stock/0.142.5/codex` passed. The
proof staged the package payload under a temporary installed root, ran the
installed runtime's launcher installer against a clean temporary `HOME`,
installed the adapter package and separate compatibility command, verified the
launcher manifest `repoRoot` points at the installed runtime, force-updated the
managed launcher, and executed the generated `uvx --from <installed-runtime>`
rollback command. The rollback removed both launcher and manifest. This closes
per-user bootstrap from the installed runtime.

Current installed-runtime clean stock-Codex provisioning status on 2026-07-06:
`--proof stock-codex-compat-pkg-clean-provision --codex-path
/Users/joshuakaunert/.local/omnigent/codex-stock/0.142.5/codex` passed. The
proof staged the package payload under a temporary installed root, ran the
installed runtime's `provision_stock_codex.py` under a clean temporary `HOME`,
provisioned stock Codex `0.142.5` into the clean user's
`~/.local/omnigent/codex-stock/0.142.5/codex` from a file-backed channel
artifact, verified `sourceKind=channel`, SHA-256, `OMNIGENT_STOCK_CODEX_PATH`,
Omnigent resolver selection, no-force reuse, and no host-cache reference in
the generated manifest/output. This closes clean user-cache stock-Codex
file-backed provisioning from the installed runtime.

Current installed-runtime stable stock-Codex acquisition status on 2026-07-07:
`--proof stock-codex-compat-pkg-update-acquisition --codex-path
/Users/joshuakaunert/.local/omnigent/codex-stock/0.142.5/codex` passed. The
proof built the unsigned `.pkg`, expanded it, staged the payload under a
temporary installed-root shape, then ran the installed runtime's
`provision_stock_codex.py` under a clean temporary `HOME`. It selected stable
Homebrew cask version `0.142.5`, proved the installed provisioner blocks remote
acquisition without `--allow-remote-channel-download` and without blocked-cache
mutation, then downloaded the official OpenAI GitHub release archive with
explicit opt-in, verified cask SHA-256
`7156b19962735c9cfb555cdd7babe8c40e7976881f8712b781199219d2e3a707`,
extracted `codex-aarch64-apple-darwin`, staged a channel payload with binary
SHA-256 `0d9a9da26e49e62b2c36f11229920287fc05576e77140ec63621ef6fdb2ddcd1`,
reported launcher update plus rollback intent, proved `stage-ready` reuse
without another remote-download flag, and kept host-cache paths out of emitted
plans. This closes stable remote acquisition from the installed runtime.

Current installed-runtime stable stock-Codex promotion status on 2026-07-07:
`--proof stock-codex-compat-pkg-update-promotion --codex-path
/Users/joshuakaunert/.local/omnigent/codex-stock/0.142.5/codex` passed. The
proof staged the package payload under a temporary installed root, ran the
installed runtime's `provision_stock_codex.py` under a clean temporary `HOME`,
staged the stable official release target with explicit remote-download opt-in,
then invoked `--promote-update --rollback-metadata <path>` to update only the
clean user's launcher manifest `pinnedCodexPath` and
`OMNIGENT_STOCK_CODEX_PATH` env contract to the staged target. The command wrote
rollback metadata next to the manifest, the proof reran the installed-runtime
plan without `--current-codex` or another remote-download flag and verified
`up-to-date` with no mutation, then invoked `--rollback-update <metadata>` and
verified the plan returned to `stage-ready` with the previous temp current
Codex pointer.
This closes persistent update pointer promotion and rollback from the installed
runtime while keeping update scheduling out of scope.

Current installed-runtime clean auth onboarding status on 2026-07-06:
`--proof stock-codex-compat-pkg-clean-auth-onboarding --codex-path
/Users/joshuakaunert/.local/omnigent/codex-stock/0.142.5/codex` passed. The
proof staged the package payload under a temporary installed root, provisioned
stock Codex `0.142.5` into the clean user cache from the installed runtime,
then ran the installed runtime's `omnigent.codex_native` auth classifier in
subprocesses with `PYTHONPATH=<installed-runtime>`. It verified the current
real stock auth source `/Users/joshuakaunert/.codex/auth.json` reports
available, a clean `CODEX_HOME` resolves `<clean-codex-home>/auth.json` and
reports `needs-auth`, a synthetic populated `auth.json` reports available, the
classifier used the clean-provisioned stock Codex path, and synthetic
credential material was not printed. This closes clean auth classification and
guided onboarding from the installed runtime.

Current signed/notarized package status on 2026-07-07:
`--proof stock-codex-compat-pkg-signed-notarized --notarytool-profile
OmnigentExperiment` is green. It verified the local packaging/notary toolchain
is present (`pkgbuild`, `pkgutil`, `xcrun`, `spctl`, `notarytool`, and
`stapler`), autodiscovered `Developer ID Installer: Joshua Kaunert
(HSRQC9N69B)`, signed package identifier `ai.omnigent.stock-codex-compat`
version `0.3.0.dev0`, submitted it to Apple, received `Accepted` for submission
`f45b29fc-a635-4ff1-8836-81c0e629d9b0`, reported final stapled package SHA-256
`68f71a7a20d4f8059cd8f7a812096d045dbdab1fa7baf07df50f11dd86687fe3`, stapled
successfully, validated the staple successfully, and `spctl -a -vv -t install`
accepted the package as `Notarized Developer ID`.

Current production stock-Codex channel policy status on 2026-07-07:
`--proof stock-codex-production-channel-policy --codex-path <stock-codex>` is
green. The proof records policy `official-openai-github-release`, validates the
accepted source shape as HTTPS `github.com/openai/codex/releases/download/...`
tarballs with a declared archive executable, creates a clean temporary
`HOME`/cache, verifies a matching channel-managed payload before remote download
is allowed, proves Omnigent resolver selection through
`OMNIGENT_STOCK_CODEX_PATH`, rejects a non-official URL before cache mutation,
and confirms the proof output does not reference the host stock-Codex cache.
This closes production source-policy and no-network reuse. It does not add
automatic update scheduling, persistent launcher pointer promotion, or an
independent archive signature policy.

Current stock-Codex update doctor status on 2026-07-07:
`--proof stock-codex-update-doctor --codex-path
~/.local/omnigent/codex-stock/0.142.5/codex` is green. The proof uses the real
pinned stock Codex `0.142.5` metadata as the current payload, creates an
official-policy-shaped synthetic newer release artifact in a clean temporary
home, and runs `provision_stock_codex.py --plan-update`. It proves the planner
fails closed without `--channel-policy`, reports `stage-required` without cache
mutation when the selected target is absent, withholds promotion material until
`promotion.ready=true`, reports `stage-ready` for a preverified target with
launcher promotion and rollback intent, reports `up-to-date` with promotion
suppressed when current equals target, and keeps the host stock-Codex cache out
of emitted plans. This closes update planning and doctor semantics, not
automatic scheduling, persistent pointer promotion, pre-release channel
adoption, or independent archive-signature verification.

Current stock-Codex update acquisition status on 2026-07-07:
`--proof stock-codex-update-acquisition --codex-path
/Users/joshuakaunert/.local/omnigent/codex-stock/0.142.5/codex` is green for
the stable official channel. The proof read Homebrew cask metadata with
auto-update disabled, selected cask version `0.142.5`, validated policy
`official-openai-github-release`, proved remote acquisition is blocked without
`--allow-remote-channel-download` and without blocked-cache mutation, then
downloaded the OpenAI GitHub archive
`https://github.com/openai/codex/releases/download/rust-v0.142.5/codex-aarch64-apple-darwin.tar.gz`
with explicit opt-in, verified cask SHA-256
`7156b19962735c9cfb555cdd7babe8c40e7976881f8712b781199219d2e3a707`,
extracted `codex-aarch64-apple-darwin`, staged a channel payload with binary
SHA-256 `0d9a9da26e49e62b2c36f11229920287fc05576e77140ec63621ef6fdb2ddcd1`,
reported launcher update and rollback intent, proved reuse as `stage-ready`
without another remote-download flag, and kept host cache paths out of emitted
plans. `gh release list --repo openai/codex --limit 10` showed
`rust-v0.142.5` as latest stable and `0.143.0-alpha.37` as a pre-release. This
closes stable remote acquisition execution, not scheduled updates, persistent
pointer promotion, alpha/pre-release adoption, or independent signature
verification.

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
when the proof supplies an explicit upstream-fixed AXe binary. That proof uses
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
- A diagnostic isolated daemon using the original locally patched AXe binary at
  `/Users/joshuakaunert/Developer/HarnessEngineering/spikes/AXe-xcode27/build_products/axe`,
  command-scoped `DEVELOPER_DIR=/Applications/Xcode-27.0.0-Beta.2.app/Contents/Developer`,
  and the same full-feature XcodeBuildMCP env successfully captured a semantic
  runtime snapshot for the booted iOS 27 simulator. The snapshot returned
  `status: SUCCEEDED`, `type: runtime-snapshot`, `rs: 1`, `count: 16`, and
  actionable refs including `e15|tap|button|Connect||`.
- The AXe upstream adoption gate is now closed: [cameroncooke/AXe#60](https://github.com/cameroncooke/AXe/pull/60)
  landed on upstream `main` as `ee92b93` for the Xcode 27 `SharedFrameworks`
  lookup fix and `51cfaf7` for the IDB deployment-target patch needed for
  source builds under Xcode 27 Beta 2. Omnigent no longer needs the retired
  temporary fork pin for default provisioning.
- `scripts/provision_xcode27_axe.py` makes the compatibility payload
  reproducible for Omnigent proofs. It clones/builds upstream
  `cameroncooke/AXe@51cfaf7552512224c5e9e6a01e059d3986d544bc` by default
  with ad hoc signing (`-`), or copies an existing built `axe` plus sibling
  `Frameworks` into a deterministic cache under `~/.cache/omnigent/axe`, then
  rejects payloads whose `FBControlCore` binary does not include both the
  legacy `PrivateFrameworks` and Xcode 27 `SharedFrameworks` `SimulatorKit`
  lookup markers.
- The default source-provisioning path passed on this host with
  `DEVELOPER_DIR=/Applications/Xcode-27.0.0-Beta.2.app/Contents/Developer` and
  installed the verified payload at
  `/Users/joshuakaunert/.cache/omnigent/axe/payloads/51cfaf7552512224c5e9e6a01e059d3986d544bc/axe`.
- The earlier clean-profile proof remains historical evidence that the
  source-build plus stock-Codex snapshot flow can run from an empty temporary
  `HOME`, `UV_CACHE_DIR`, and AXe cache root, but that proof used the retired
  fork-era pin. Rerun that clean-profile gate against the upstream pin only if
  clean-machine AXe source provisioning becomes part of the production
  acceptance sequence.
- Omnigent now owns a replacement-safe adapter contract for this boundary: the
  generated snapshot tool strips ambient `XCODEBUILDMCP_AXE_PATH`, maps only
  explicit `OMNIGENT_XCODEBUILDMCP_AXE_PATH` into the subprocess env, and uses
  a per-call isolated XcodeBuildMCP socket.
- The stock-Codex live proof passed through normal Omnigent `dynamicTools` with
  the upstream source-provisioned cache-backed AXe path, stock Codex `0.142.5`,
  session `conv_f1d8eacf14d44482beea756d64473916`, and function call
  `call_rp3b5TNKpozMNdAPrk1j86Io`.

Do not treat this as bundled-XcodeBuildMCP AXe direct parity. The upstream AXe
source default closes the fork-maintenance branch of the problem, but the Xcode
27 semantic snapshot boundary still needs one of these distribution stories:

- XcodeBuildMCP's bundled AXe payload absorbs the upstream Xcode 27 fixes.
- The operator explicitly provisions the pinned upstream AXe commit, or an
  equivalent upstream-fixed AXe payload, as part of setup for the selected
  Xcode.
- The operator intentionally selects an Xcode/AXe combination whose hierarchy
  path is known to work, and that requirement is documented as part of
  clean-host setup.
- A separate clean-machine gate proves the same source provisioning and
  stock-Codex snapshot path outside this host.

## Next Proof Gates

Run these in order unless a later gate becomes cheaper due to new evidence.

1. Upstream AXe source-provisioning rerun
   - Rerun default source provisioning from `cameroncooke/AXe` and then rerun
     the stock-Codex semantic snapshot proof. Keep the proof scoped to explicit
     `OMNIGENT_XCODEBUILDMCP_AXE_PATH` and command-scoped `DEVELOPER_DIR`; do
     not rely on global `xcode-select`, Xcode bundle mutation, or Homebrew
     Cellar mutation.

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

8. `omnigent-runtime` install hardening
   - The default-path rehearsal is green for current-host ambient bundle lookup
     and `PATH` stock-Codex resolution. The pinned provisioner is green for
     local or downloaded source-binary pinning into an Omnigent-owned cache,
     and the current host now has a persistent managed Codex `0.142.5` payload
     installed at `~/.local/omnigent/codex-stock/0.142.5/codex`; the older
     `0.142.2` payload remains as historical evidence only. The isolated launcher
     activation proof is also green for temporary PATH shadowing, pinned
     stock-Codex selection through
     `OMNIGENT_STOCK_CODEX_PATH`, delegation through
     `uvx --from <repo> omnigent codex`, and rollback. The current host now also
     has `/opt/homebrew/bin/codex` pointed at the managed Omnigent launcher with
     rollback metadata and that launcher now delegates to `codex-cli 0.142.5`.
     The full managed-default aggregate is green through that launcher, and the
     read-only launcher doctor remains the cheap post-update drift check. The
     file-backed stock-Codex channel manifest
     proof is also green for manifest selection, staging, SHA/version
     verification, channel-provenance install, and resolver selection. The
     Homebrew/GitHub remote-channel proof is also green for temporary official
     cask metadata download and archive extraction, including the `0.142.5`
     refresh from the official OpenAI GitHub release archive. The temporary
     `app-bundle-entrypoint` proof is green for a non-installed
     `Omnigent Codex.app` bundle shape that delegates through
     `uvx --from <repo> omnigent codex` with an explicit stock-Codex pin.
     Remaining primary-mode product decisions are whether that temporary
     app-bundle shape should become a signed/notarized persistent app install,
     whether it should register with LaunchServices or Dock/Finder defaults,
     whether the temporary remote-channel proof should become a persistent
     updater/install command, and what independent signature or notarization
     policy is required.

9. `stock-codex-compat` bridge proof
   - First install/config gate is green: `--proof stock-codex-compat` proves a
     stock Codex CLI profile can install `apple-appdev-workflow` from a
     disposable local marketplace and can read the Omnigent MCP bridge plus
     `PreToolUse`, `PostToolUse`, and `UserPromptSubmit` hooks from an isolated
     `CODEX_HOME`.
   - Current live gate is blocked: `--proof stock-codex-compat-live` proves the
     isolated profile can authenticate and run a stock Codex `exec` turn, but
     the first model message is the sentinel without the deterministic
     `Routing: orchestrator-led` block. The current Codex policy hook can block
     `UserPromptSubmit`; it does not rewrite or prepend prompt context.
   - Wrapper route-injection gate is green: `--proof
     stock-codex-compat-wrapper-live` proves the source-owned
     `omnigent.stock_codex_compat_wrapper` entrypoint can invoke stock Codex
     from the same isolated profile, record the pre-wrapper first model message,
     and prefix deterministic route evidence before the first visible
     `agent_message`.
   - Remaining product decision: decide whether compatibility mode may require
     launching stock Codex through an Omnigent-owned wrapper. If yes, the next
     tool-event gate is already green for stock `command_execution`: `--proof
     stock-codex-compat-wrapper-command-tool` proves the wrapper preserves a
     completed read-only command tool event and still injects route evidence
     before the final visible answer. The current stock-MCP relay sidecar gate
     is blocked: `--proof stock-codex-compat-wrapper-relay-tool` advertises a
     deterministic Omnigent relay tool through `tool_relay.json`, but stock
     `codex exec` records `0` relay executor calls even with the
     generic-enable-compatible feature set and an explicit `tool_search`
     fallback prompt. The stronger wrapper-owned adapter-package bridge is green:
     `--proof stock-codex-compat-wrapper-adapter-tool` proves stock Codex can
     execute a wrapper-exposed Omnigent adapter command from a validated
     manifest with a closed argument schema via the proven command tool while
     the wrapper preserves route evidence. The bounded multi-tool arbitration
     gate is also green: `--proof stock-codex-compat-wrapper-adapter-arbitration`
     proves a generated two-tool adapter package can expose both route-selection
     and release-notes adapters, have stock Codex select the route adapter,
     reject the release adapter, and preserve route evidence. The first real
     workflow adapter gate is green in two forms: the direct
     `--proof stock-codex-compat-wrapper-apple-docs-adapter` gate proves the
     generated `fetch_apple_docs` adapter through the wrapper but required stock
     Codex `--sandbox danger-full-access`, while
     `--proof stock-codex-compat-wrapper-apple-docs-bridge-adapter` proves the
     same Apple-docs workflow with stock Codex in `--sandbox workspace-write` by
     keeping the visible adapter command workspace-local and moving network
     execution to the reusable wrapper-owned file bridge. The same bridge shape
     now reaches XcodeBuildMCP build/install/launch:
     `--proof stock-codex-compat-wrapper-xcodebuild-bridge-adapter` proves stock
     Codex can run a workspace-local `xcodebuildmcp_simulator_build_run` adapter
     command under `--sandbox workspace-write` while wrapper-side execution runs
     the full-feature XcodeBuildMCP CLI build/run outside the stock sandbox. The
     bridge now also reaches XcodeBuildMCP simulator tests:
     `--proof stock-codex-compat-wrapper-xcodebuild-bridge-test-adapter` proves
     stock Codex can run a workspace-local `xcodebuildmcp_simulator_test`
     adapter command under `--sandbox workspace-write` while wrapper-side
     execution runs the full-feature XcodeBuildMCP CLI simulator-test flow
     outside the stock sandbox.
     reusable bridge service, domain handlers, and wrapper-owned runtime
     activation are now source-packaged and live-proven. The managed
     compatibility launcher activation gate also proves temporary default
     wiring for that runtime. The managed compatibility launcher doctor gate
     now proves the non-mutating host install plan. The persistent adapter
     package placement gate is green at
     `~/.local/omnigent/stock-codex-compat/adapter-package` and the doctor path
     validates it by default without explicit adapter paths. The persistent
     separate-command install gate is green at
     `~/.local/bin/omnigent-stock-codex-compat` with rollback exercised and the
     current `codex` default untouched. The clean-home install gate is green
     for default-path install, doctor, probe, version delegation, and rollback
     under a temporary fresh profile. The unsigned flat `.pkg` structure gate is
     green for identifier, version, install root, scripts, unsigned signature
     status, sanitized manifests, and required runtime payload layout. The
     expanded package runtime live gate is also green:
     `stock-codex-compat-pkg-runtime-live` runs a real stock Codex `0.142.5`
     model turn through the expanded package runtime using `uvx --from` and
     `omnigent-stock-codex-wrapper`, with route injection before
     `STOCK_CODEX_COMPAT_LIVE_OK`. The pkg-installed runtime bootstrap gate is
     green too: `stock-codex-compat-pkg-user-bootstrap` stages the package
     payload under a temporary installed-root shape, runs the installed runtime
     installer against a clean temporary `HOME`, installs and force-updates the
     compatibility launcher and adapter package, verifies the launcher manifest
     points at the installed runtime, and executes the generated rollback
     command. The pkg-installed runtime clean stock-Codex provisioning gate is
     green too: `stock-codex-compat-pkg-clean-provision` runs the installed
     runtime's provisioner under a clean temporary `HOME`, provisions stock
     Codex `0.142.5` into the clean user cache from a file-backed channel
     artifact, verifies resolver selection through `OMNIGENT_STOCK_CODEX_PATH`,
     and proves no-force reuse without referencing the host stock-Codex cache.
     The pkg-installed runtime stable acquisition gate is green too:
     `stock-codex-compat-pkg-update-acquisition` runs the installed runtime's
     provisioner under a clean temporary `HOME`, blocks remote download without
     explicit opt-in, downloads and verifies the stable Homebrew/OpenAI GitHub
     release archive with opt-in, stages a channel payload, proves reuse without
     another remote-download flag, and keeps host-cache paths out of emitted
     plans.
     The pkg-installed runtime stable promotion gate is green too:
     `stock-codex-compat-pkg-update-promotion` stages the stable official
     release target from the installed runtime, invokes
     `--promote-update --rollback-metadata <path>` to promote only the clean
     user's launcher manifest pointer plus env contract, verifies the
     post-promotion plan is `up-to-date` without mutation, invokes
     `--rollback-update <metadata>`, and verifies the plan returns to
     `stage-ready`.
     The pkg-installed runtime clean auth gate is green too:
     `stock-codex-compat-pkg-clean-auth-onboarding` runs the installed
     runtime's auth classifier against real, clean, and synthetic auth profiles,
     proves clean `CODEX_HOME` reports `needs-auth`, proves a populated
     `auth.json` reports available, and keeps credential material out of
     classifier output.
     The signed/notarized package gate is now green with Developer ID Installer
     signing, notarization, stapling, stapler validation, and Gatekeeper
     acceptance. The package-manager installer lifecycle gate now has an
     explicit two-phase producer/consumer shape: user-context
     `--pkg-output-path` creates the signed/notarized artifact, and admin-context
     `--pkg-path` consumes it for the installer/receipt/doctor/cleanup lifecycle.
     The admin-authenticated consumer is now green against the prebuilt artifact:
     it installed to a temporary target volume, validated package receipt
     metadata and required payload files, materialized the clean-home adapter
     package, ran non-mutating doctor, removed the payload, forgot the receipt,
     proved receipt absence, and detached the image. The clean-user signed-pkg
     canary is also green: it consumes the same signed artifact, installs to a
     temporary target volume, provisions stock Codex into a clean cache from the
     installed runtime, bootstraps and rolls back the clean compatibility
     launcher, classifies clean auth as `needs-auth`, cleans package payload and
     receipt state, and detaches the image. The external clean-user gate is now
     green for an admin-authenticated marked throwaway home and leaves only the
     operator marker after cleanup. It also has a fail-closed `--clean-user-name`
     account mode that derives the passwd home and executes user-level work
     through `sudo -u`, but it still does not create users itself or prove a
     separate macOS account/VM until that live account or VM run is captured.
     The production stock-Codex channel policy gate is green for
     official OpenAI GitHub release source validation, exact-pin reuse before
     network access, non-official URL rejection, and resolver selection. The
     stock-Codex update doctor gate is green for fail-closed policy
     requirement, dry-run no-mutation behavior, preverified target detection,
     target-ready promotion material, launcher promotion intent, rollback
     intent, and up-to-date promotion suppression. The remaining carry-parity
     gates now focus on broader bridge coverage such as screenshot, snapshot,
     gesture, or device execution through the wrapper file bridge if product
     scope requires it, plus updater scheduling, LaunchAgent/LaunchDaemon
     packaging policy, or independent archive signature policy if product scope
     requires them.
     If no, raw stock Codex Electron/CLI route parity remains blocked until
     stock Codex exposes a pre-model prompt/context injection surface.
   - Minimum live acceptance should include deterministic route evidence before
     the first model continuation, generated adapter-tool availability,
     stock-Codex binary pinning or resolver evidence, clean auth-source
     separation, and a clear statement of any stock Codex surfaces that cannot
     be bridged from a plugin/sidecar install.
   - A plugin-only install is not sufficient evidence for the live gate unless
     it proves the Omnigent bridge is installed and active.

## Non-Actions

The following are intentionally out of scope for this track:

- Deleting Codex-fork carries.
- Merging Omnigent adapters into the Codex fork.
- Treating one green proof as full replacement readiness.
- Publishing the Omnigent spike upstream before it serves the internal
  replacement goal.
- Rewriting current production workflow docs to point at Omnigent before a
  cutover decision exists.
