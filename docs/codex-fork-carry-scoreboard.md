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
| Responses stream lifecycle diagnostics | `8eea3c5b34`, `07f2c46719` | `replacement-ready` for Omnigent adapter-level progress diagnostics plus wrapper file-bridge adapter failure diagnostics | `_AdapterTurnProgress` in `omnigent.runtime.harnesses._executor_adapter` records per-turn inner-executor progress and decorates `response.failed` errors when early tool-call progress appears before durable visible output. `tests/runtime/harnesses/test_executor_adapter.py::test_executor_error_after_tool_request_includes_progress_diagnostic` proves this through a real `HarnessProcessManager` subprocess stream: the function-call progress item reaches SSE, then the terminal failure includes `early output item progress before durable visible output`, `tool_call_request_seen=True`, `tool_call_complete_seen=False`, and `text_delta_seen=False`. The stock-compat wrapper now also preserves failed file-bridge adapter diagnostics through stock Codex `command_execution` output: `--proof stock-codex-compat-wrapper-bridge-diagnostics` proved a failed `fetch_apple_docs` bridge call persisted exit code `64`, policy error text, `OMNIGENT_ADAPTER_BRIDGE_DIAGNOSTIC`, request id, tool name, timestamps, and duration while route evidence was still injected first. This replaces the operator diagnostic value at the Omnigent harness and wrapper adapter boundaries; it does not claim raw stock-Codex provider SSE/WebSocket lifecycle visibility or response-id mismatch logging. | Keep fork unchanged. If product later requires raw provider-stream response ids from inside stock Codex, that remains out of scope for a wrapper and should be handled as a separate keep/drop decision. |
| HTTP fallback guard by provider URL | `bb07d63968` | `replacement-ready` for Omnigent-managed Codex provider gateway URLs | `_assert_codex_http_gateway_base_url` rejects non-`http`/`https` Codex provider-family `base_url` values before `HARNESS_CODEX_GATEWAY_BASE_URL` reaches stock Codex. `tests/runtime/test_provider_spawn_env.py::test_codex_allows_http_provider_base_url` proves local HTTP gateways still work, and `tests/runtime/test_provider_spawn_env.py::test_codex_rejects_non_http_provider_base_url` proves `ws://`, `wss://`, and malformed URLs fail closed. This covers Omnigent-managed provider entries; user-managed `cli-config` provider tables in `~/.codex/config.toml` remain stock-Codex-owned unless product scope says Omnigent must parse and guard them too. | Keep fork unchanged. Treat cli-config websocket-only provider support as out of scope unless explicitly required. |
| Disabled-goal tolerance for Codex goal reads | `de81a71e9c` | `replacement-ready` for Omnigent runner goal reads | `CodexGoalRunner` normalizes stock-Codex `thread/goal/get` failures containing `goals feature is disabled` to `{"goal": null}` at the Omnigent runner boundary, while leaving write operations as errors. `tests/runner/test_codex_goal_runner.py::test_codex_goal_runner_get_returns_none_when_stock_codex_goals_are_disabled` and `tests/runner/test_codex_goal_runner.py::test_codex_goal_runner_set_keeps_disabled_goals_as_error` prove the replacement behavior without mutating stock Codex. | Keep fork unchanged. Continue treating set, status, and clear as real errors when stock Codex disables goals. |
| ChatGPT mobile remote resume redaction and payload capping | `b51c499276`, `c716294c3b` | `obsolete-if-cutover` for the current Omnigent stock-Codex replacement scope | The fork carry only activates for Codex app-server client names `codex_chatgpt_android_remote` and `codex_chatgpt_ios_remote`, capping resume turns and redacting MCP, dynamic-tool, image, file-change, and large text payloads in response-only mobile resume data. Omnigent uses `thread/resume` internally for local runner/web continuity, but the current replacement path does not expose those ChatGPT mobile remote clients or their resume payload contract. | Keep as fork fallback. Build an Omnigent-side remote-resume redaction proof only if product scope explicitly adds ChatGPT mobile/app-server remote resume compatibility. |
| Rebase and upstream-refresh adaptation commits | `fa2fa9ba98`, `393f22fa01`, `f86f506f3a`, `67f216880e`, `dd0e591851`, `9b28f2aaba`, `ed4c40fecb`, `9567a9c98e`, `aabfc59d3d`, `c716294c3b`, `4286b74d90` | `obsolete-if-cutover` | These commits keep the fork carry stack compiling and testing across upstream Codex drift. They are not independent product capabilities once the Omnigent path no longer depends on the fork. | Do not delete now. Treat as maintenance burden avoided only after explicit cutover. |

Some commits appear in both a product-behavior group and an adaptation group
because later refresh commits adjust tests or fixtures for an existing behavior.
That overlap is intentional; the product carry and the upkeep burden are
separate decisions.

## Cutover Rule

The Omnigent path is a dual-mode replacement target:

- `omnigent-runtime`: Omnigent is the installed app/CLI entrypoint and stock
  Codex is the engine underneath it.
- `stock-codex-compat`: stock Codex Electron or CLI remains the underlying
  surface, but the install carries the Apple workflow plugin plus the Omnigent
  meta-harness bridge required for parity. Full parity may require an
  Omnigent-owned wrapper entrypoint around stock Codex rather than an unwrapped
  stock launch.

Neither mode authorizes Codex-fork deletion by itself. A mode is not a full fork
replacement until all product-required carry groups for that mode are classified
as one of:

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
rehearsal are now green for the current host with stock Codex `0.142.5`. The
clean-profile gate used isolated `HOME`/cache/XDG dirs, explicit Apple bundle
input, and preserved real `CODEX_HOME` for authentication. The default-path gate
used ambient Apple bundle lookup, `PATH` stock-Codex resolution through the
Omnigent-managed launcher, and documented fallback steps without mutating the
Codex fork. The `pinned-codex-provision`, `stock-codex-channel`, and
`stock-codex-homebrew-remote-channel` proofs are green for provisioning a stock
Codex payload into an Omnigent-owned `codex-stock/<version>/codex` cache with
manifest provenance, SHA-256 verification, channel provenance, and
`OMNIGENT_STOCK_CODEX_PATH` resolver proof. The current host now has stock Codex
`0.142.5` persistently installed at
`~/.local/omnigent/codex-stock/0.142.5/codex`, sourced from the official
Homebrew/OpenAI GitHub release archive and recorded with `sourceKind: channel`.
The `stock-codex-production-channel-policy` proof is now green for the
`official-openai-github-release` policy: it accepts only HTTPS OpenAI Codex
GitHub release tarballs with declared archive executables, verifies matching
channel-managed payloads before any remote download is allowed, rejects
non-official URLs before cache mutation, and proves resolver selection from a
clean temporary cache.
The `stock-codex-update-doctor` proof is also green: it requires that same
production channel policy for `--plan-update`, reports `stage-required` without
cache mutation when a selected target is absent, withholds promotion material
until `promotion.ready=true`, reports `stage-ready` with launcher promotion and
rollback intent for a preverified target, suppresses promotion for `up-to-date`,
and keeps host cache paths out of emitted update plans.
The `stock-codex-update-acquisition` proof is now green for stable official
remote acquisition execution: it reads Homebrew cask metadata with auto-update
disabled, validates the `official-openai-github-release` policy, proves remote
download is blocked without `--allow-remote-channel-download`, downloads the
selected OpenAI GitHub release archive only with explicit opt-in and expected
SHA-256, extracts the declared executable, records channel provenance, proves
reuse without another remote-download flag or mutation, and keeps host cache
paths out of emitted plans. On 2026-07-07, both the official cask and GitHub
latest stable release selected `0.142.5`; `0.143.0-alpha.37` existed as a
pre-release and remains outside this stable production-channel policy unless
we intentionally add a separate alpha/pre-release gate.
The existing `/opt/homebrew/bin/codex` Omnigent-managed launcher now delegates
to that `0.142.5` payload while preserving the original Homebrew backup path.
The `clean-auth-onboarding` proof remains green for the local auth boundary:
inherited `.codex-fork` `CODEX_HOME` is not treated as the replacement-track
stock auth source, stock `~/.codex/auth.json` is locally available, clean
temporary `HOME`/`CODEX_HOME` reports `needs-auth`, and a populated temporary
`auth.json` reports available without printing credential material or running
interactive login. The isolated
`app-bundle-entrypoint` proof is green for a temporary `Omnigent Codex.app`
bundle with a valid `Info.plist`, executable `Contents/MacOS/omnigent-codex`,
explicit `OMNIGENT_STOCK_CODEX_PATH` pin, and delegation through
`uvx --from <repo> omnigent codex`; it does not install into `/Applications`,
register LaunchServices, mutate Stock Codex.app, or prove signing/notarization.
The isolated
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
graph proof passed through that launcher after reinstall. On 2026-07-04, after
the `0.142.5` refresh, `codex --version` and the launcher probe delegated to
the refreshed pinned payload, the explicit `cutover-ready` aggregate passed
with `--codex-path` set to the `0.142.5` payload, and the full
`default-path-cutover` aggregate passed with no explicit `--codex-path`,
proving graph, router matrix, tool-plane, Apple memory MCP, Apple-docs CLI,
XcodeBuildMCP CLI build/install/launch, and read-only XcodeBuildMCP discovery
through the refreshed default path.

The next gates should split by product mode:

- for `omnigent-runtime`, turn the temporary app-bundle proof into a signed,
  notarized persistent Omnigent app install with LaunchServices or Dock/Finder
  defaults only if those are desired for the primary entrypoint;
- for `stock-codex-compat`, treat the isolated install/config gate as green:
  stock Codex can install the Apple workflow plugin from a disposable local
  marketplace and can read the Omnigent MCP bridge plus Codex policy hooks from
  a temp `CODEX_HOME`;
- for `stock-codex-compat`, treat live deterministic route parity as blocked at
  route injection: a stock Codex `exec` turn can authenticate and return the
  live sentinel from the isolated profile, but the current policy hook does not
  prepend `Routing: orchestrator-led` before model output;
- for `stock-codex-compat`, treat the Omnigent-owned wrapper spike as green for
  CLI JSONL route injection: `omnigent.stock_codex_compat_wrapper` is now a
  source-owned module exposed as `omnigent-stock-codex-wrapper`, the wrapped
  stock Codex process returned the sentinel as its pre-wrapper first message,
  and the wrapper injected the deterministic Apple route before the visible
  first agent message;
- for `stock-codex-compat`, treat the first wrapped tool-event gate as green:
  `stock-codex-compat-wrapper-command-tool` proves the wrapper preserves one
  completed stock Codex `command_execution` event, including
  `cat tool-proof.txt`, `OMNIGENT_TOOL_SENTINEL_42`, exit code `0`, and route
  injection before the final visible answer;
- for `stock-codex-compat`, treat the stronger wrapper-owned adapter package
  gate as green: `stock-codex-compat-wrapper-adapter-tool` proves the wrapper
  can validate an Omnigent adapter manifest with a closed object schema,
  prepend the declared adapter bin to stock Codex's `PATH`, record the
  adapter-bin, manifest, and tool names in wrapper evidence, have stock Codex
  execute `omnigent-wrapper-adapter-probe --message stock-codex-wrapper-adapter-proof`
  exactly once, preserve the adapter `command_execution` output sentinel, and
  still inject route evidence before the final visible answer;
- for `stock-codex-compat`, treat bounded multi-tool adapter arbitration as
  green: `stock-codex-compat-wrapper-adapter-arbitration` proves the wrapper
  can validate a generated two-tool adapter package, record both tool names in
  wrapper evidence, have stock Codex select the route adapter, reject the
  release-notes adapter, preserve exactly one selected `command_execution`
  output sentinel, and still inject route evidence before the final visible
  answer;
- for `stock-codex-compat`, treat the first real workflow adapter gate as
  green with a sandbox caveat: `stock-codex-compat-wrapper-apple-docs-adapter`
  proves the generated `fetch_apple_docs` adapter package can fetch
  `https://developer.apple.com/documentation/swift/string` through stock
  Codex's command tool, preserve exactly one `command_execution` event, and
  still inject route evidence; `read-only` timed out on `npx`,
  `workspace-write` still failed direct Sosumi fetch, and the green run required
  `danger-full-access` in the temporary proof workspace;
- for `stock-codex-compat`, treat the wrapper-side file-bridge variant as
  green for low-privilege Apple-docs execution:
  `stock-codex-compat-wrapper-apple-docs-bridge-adapter` places the generated
  `fetch_apple_docs` command and bridge directory inside the temporary stock
  workspace, keeps stock Codex in `workspace-write`, records `adapterBridgeDir`
  in wrapper evidence, has stock Codex write the bridge request through its
  command tool, starts the wrapper-owned bridge runtime from the adapter
  manifest, runs `sosumi fetch` from the adapter-owned bridge handler, and
  preserves the real Apple-docs output plus route evidence;
- for `stock-codex-compat`, treat the first XcodeBuildMCP file-bridge adapter as
  green for low-privilege stock command execution plus wrapper-side simulator
  build/install/launch: `stock-codex-compat-wrapper-xcodebuild-bridge-adapter`
  places the generated `xcodebuildmcp_simulator_build_run` command and bridge
  directory inside the temporary stock workspace, keeps stock Codex in
  `workspace-write`, records `adapterBridgeDir` in wrapper evidence, has stock
  Codex write the bridge request through its command tool, and runs
  `xcodebuildmcp simulator build-and-run` from the wrapper-owned bridge runtime
  with the full XcodeBuildMCP workflow env enabled;
- for `stock-codex-compat`, treat the managed compatibility launcher activation
  gate as green for default-entrypoint wiring:
  `stock-codex-compat-launcher-activation` installs a temporary managed
  `codex` launcher with the standard Omnigent marker and manifest pointer,
  proves Omnigent resolves that launcher back to the manifest-pinned stock
  Codex binary instead of recursing, delegates through
  `uvx --from <repo> omnigent-stock-codex-wrapper`, starts the wrapper-owned
  file-bridge runtime, runs the generated `fetch_apple_docs` bridge adapter
  under `workspace-write`, injects deterministic route evidence, and uninstalls
  the temporary launcher plus manifest;
- for `stock-codex-compat`, treat the non-mutating host doctor gate as green:
  `stock-codex-compat-launcher-doctor` validates the intended default
  compatibility launcher target at
  `~/.local/bin/omnigent-stock-codex-compat`, manifest path
  `~/.local/omnigent/launchers/stock-codex-compat.json`, pinned stock Codex
  `~/.local/omnigent/codex-stock/0.142.5/codex`, `uvx`, route prefix,
  generated `fetch_apple_docs` adapter manifest, default bridge dir
  `~/.local/omnigent/stock-codex-compat/adapter-bridge`, PATH posture,
  rollback command, and install command shape without creating or replacing
  launcher files. Current host result: target absent, parent on PATH, parent
  writable, install allowed, and filesystem mutation false;
- for `stock-codex-compat`, treat persistent adapter package placement as
  green: `install_stock_codex_compat_launcher.py --install-adapter-package`
  installed the default adapter package at
  `~/.local/omnigent/stock-codex-compat/adapter-package`, a second run reused
  it with `mutatesFilesystem=false`, and launcher doctor validated the package
  against stock Codex `0.142.5` without explicit `--adapter-bin` or
  `--adapter-manifest`. The package contains `adapter-manifest.json` and
  `bin/fetch_apple_docs`;
- for `stock-codex-compat`, treat the persistent separate-command launcher as
  green for the current host: `omnigent-stock-codex-compat` is installed at
  `~/.local/bin/omnigent-stock-codex-compat`, selected on PATH, delegates
  `--version` to stock Codex `0.142.5`, probes the expected wrapper delegate and
  adapter paths, was uninstalled once to prove rollback, then reinstalled as
  the final host state without touching the existing `codex` default;
- for `stock-codex-compat`, treat the clean-home install sequence as green:
  `stock-codex-compat-clean-install` installs the adapter package and separate
  command from defaults under a temporary fresh `HOME`, validates PATH
  selection, probe, version delegation, force-aware doctor behavior, and
  rollback, then removes the temporary profile;
- for `stock-codex-compat`, treat the unsigned portable runtime bundle
  rehearsal as green: `build_stock_codex_compat_bundle.py` creates
  `omnigent-stock-codex-compat-bundle.tar.gz` with the `runtime/` source root
  needed by `uvx --from <extracted-runtime>`, and
  `stock-codex-compat-bundle-install` verifies SHA-256, safe extraction,
  clean-home install, extracted-runtime launcher manifest wiring, probe,
  version delegation, force-aware doctor behavior, and rollback;
- for `stock-codex-compat`, treat the unsigned flat `.pkg` structure proof as
  green: `build_stock_codex_compat_pkg.py` builds a package from the portable
  runtime bundle and `stock-codex-compat-pkg-structure` verifies identifier
  `ai.omnigent.stock-codex-compat`, version `0.3.0.dev0`, install prefix
  `/Library/Application Support/Omnigent/stock-codex-compat`, script
  `postinstall`, unsigned signature status, sanitized manifests, and required
  runtime payload files, including `runtime/scripts/provision_stock_codex.py`,
  without installing the package;
- for `stock-codex-compat`, treat the expanded `.pkg` runtime live model turn
  as green: `stock-codex-compat-pkg-runtime-live` builds the package, expands
  it without installing, validates the runtime under
  `Payload/Library/Application Support/Omnigent/stock-codex-compat/runtime`,
  then runs pinned stock Codex `0.142.5` through the expanded runtime using
  `uvx --from` and `omnigent-stock-codex-wrapper`, and injects the deterministic
  Apple route before `STOCK_CODEX_COMPAT_LIVE_OK`;
- for `stock-codex-compat`, treat per-user bootstrap from the pkg-installed
  runtime as green: `stock-codex-compat-pkg-user-bootstrap` stages the package
  payload under a temporary installed root, runs the installed runtime's
  launcher installer against a clean temporary `HOME`, installs the adapter
  package and `omnigent-stock-codex-compat` command, verifies PATH selection,
  version delegation, probe output, manifest `repoRoot`, and force-aware doctor
  behavior, force-updates the managed launcher, then executes the generated
  rollback command through `uvx --from <installed-runtime>` and removes both
  launcher and manifest;
- for `stock-codex-compat`, treat clean stock-Codex provisioning from the
  pkg-installed runtime as green: `stock-codex-compat-pkg-clean-provision`
  stages the package payload under a temporary installed root, runs the
  installed runtime's `provision_stock_codex.py` against a clean temporary
  `HOME`, provisions pinned stock Codex `0.142.5` into the clean user's
  `~/.local/omnigent/codex-stock/0.142.5/codex` from an explicit file-backed
  channel artifact, verifies SHA-256 and `sourceKind=channel`, verifies
  `OMNIGENT_STOCK_CODEX_PATH` and Omnigent resolver selection of the
  clean-provisioned payload, proves a second no-force provision reuses the
  same payload, and checks the provisioned manifest/output do not reference the
  host stock-Codex cache;
- for `stock-codex-compat`, treat clean auth onboarding from the pkg-installed
  runtime as green: `stock-codex-compat-pkg-clean-auth-onboarding` stages the
  package payload under a temporary installed root, provisions pinned stock
  Codex `0.142.5` into the clean user's cache from the installed runtime, then
  installs and selects the compatibility launcher before running the installed
  runtime's auth classifier with `PYTHONPATH=<installed-runtime>`; it verifies
  the current real stock auth source is available, a clean `CODEX_HOME` reports
  `needs-auth`, a synthetic populated `auth.json` reports available, the
  classifier uses the clean-provisioned stock Codex path, classifier output does
  not leak synthetic credential material, and guided login targets
  `~/.local/bin/omnigent-stock-codex-compat` instead of the raw stock Codex
  binary;
- for `stock-codex-compat`, treat pkg-installed runtime stable stock-Codex
  acquisition as green: `stock-codex-compat-pkg-update-acquisition` builds and
  stages the compatibility `.pkg` under a temporary installed-root shape, runs
  its bundled `scripts/provision_stock_codex.py` under a clean temporary `HOME`,
  proves remote acquisition is blocked without explicit
  `--allow-remote-channel-download`, then downloads, verifies, extracts, and
  stages the official stable Homebrew/OpenAI GitHub release archive, proves
  reuse without another remote-download flag, and keeps host-cache paths out of
  emitted plans;
- for `stock-codex-compat`, treat pkg-installed runtime stable update promotion
  and scheduled updater shape as green: `stock-codex-compat-pkg-update-promotion`
  promotes only the clean user's launcher manifest pointer and
  `OMNIGENT_STOCK_CODEX_PATH`, writes rollback metadata, suppresses a second
  promotion as `up-to-date`, and proves rollback restoration; the adjacent
  `stock-codex-compat-pkg-update-agent` gate packages
  `runtime/scripts/update_stock_codex_compat.py`, writes a user LaunchAgent plist
  whose `ProgramArguments` delegate to `uvx --from <installed-runtime> python
  <installed-runtime>/scripts/update_stock_codex_compat.py`, preserve
  `--uvx-path <absolute-uvx>` for launchd's sparse environment, omit proof-only
  stale-current flags, run the updater once directly, and prove the next run is a
  no-op without another remote-download flag. The clean-VM
  `stock-codex-compat-pkg-clean-vm-update-agent` gate now loads that generated
  LaunchAgent in `gui/501`, forces a scheduled updater run with
  `launchctl kickstart -k`, parses `scheduled_action=up-to-date`, unloads with
  `launchctl bootout`, and proves no host stock Codex cache reference;
- for `stock-codex-compat`, treat the wrapped MCP relay-tool gate as blocked:
  `stock-codex-compat-wrapper-relay-tool` starts the real Omnigent
  `tool_relay.json` sidecar and advertises `omnigent_wrapper_relay_probe`, but
  stock `codex exec` never invokes it (`0` relay executor calls) even after
  enabling every generically enableable current feature and prompting an
  explicit `tool_search` fallback;
- for `stock-codex-compat`, the signed/notarized package gate is green with
  Developer ID Installer signing, Apple notarization, stapling, stapler
  validation, and Gatekeeper acceptance, and it can now persist the artifact via
  `--pkg-output-path`. The package-manager lifecycle is now green through the
  disposable Tart VM path: the signed/notarized package installs into the VM's
  real `/Library`, bootstraps the user runtime, provisions stock Codex from the
  official OpenAI GitHub release channel inside the VM without uploading the
  host stock binary, classifies clean auth, rolls back user and package state,
  and forgets the package receipt. The live clean-VM launcher gate is also green:
  `stock-codex-compat-pkg-clean-vm-live` uploads only proof-scoped stock auth,
  runs the installed `~/.local/bin/omnigent-stock-codex-compat` launcher with
  the in-VM provisioned stock Codex, records parsed selected-launcher,
  `CODEX_HOME`, working-directory, and thread
  `019f3fd9-093f-7550-8474-3c67eb5fe6c9` evidence, and preserves the deterministic
  `Routing: orchestrator-led` route evidence before
  `STOCK_CODEX_COMPAT_LIVE_OK`. The clean-VM update-agent gate is green on the
  fixed signed/notarized package SHA-256
  `d0185a22380036b97703144f91bbcb701806c3638ebcbe98b2aa38df43baf581`: it
  writes the user LaunchAgent, loads/kickstarts/unloads it through launchd,
  parses the scheduled updater JSON, and verifies `host_cache_referenced=False`.
  The raw Tart clean-VM bootstrap gate is also green:
  `stock-codex-compat-pkg-clean-vm-bootstrap` cloned the cached
  `ghcr.io/cirruslabs/macos-tahoe-base:latest` source image into
  `omnigent-clean-bootstrap-proof`, randomized the clone MAC, waited for Tart
  guest-agent readiness, injected key SSH, marked the guest home disposable,
  installed user-local `uvx` without shell profile mutation, verified
  noninteractive sudo plus SSH, stopped the clone, and then the same clone passed
  the clean-VM update-agent gate with the signed/notarized package above.
  The release-candidate wrapper
  `scripts/prove_stock_codex_compat_release_candidate.py` now makes the
  `stock-codex-compat-pkg-clean-vm-release` aggregate the checklist gate for a
  package candidate, requiring remote acquisition, auth onboarding, auth
  persistence, update-agent, and live installed-launcher proof statuses to pass
  against one signed/notarized package and one official channel selection. It
  can also emit a JSON release evidence artifact with package/channel hashes,
  per-step statuses, Tart start/stop counts, host-stock-upload status, and
  live/auth thread IDs so release review does not depend on terminal log
  scraping. The current local evidence artifact
  `omnigent-stock-codex-compat-github-latest.release-evidence.json` is green on
  package SHA-256
  `cfff83af6fd1dfc59ea1ed4928befe53929462eabd096e5c54d6171379be7ccc`,
  official channel `0.143.0`, Tart `5/5`, and
  `hostStockCodexUploadedAny=False`. The offline verifier
  `scripts/check_stock_codex_compat_release_evidence.py` now re-hashes the
  archived package and fails closed on evidence schema drift, package hash
  mismatch, non-official channel evidence, non-ready steps, Tart count
  mismatch, or host stock-Codex upload.
  The production stock-Codex channel policy gate
  is green for official-source validation, clean-cache reuse before network
  access, fail-closed non-official URL rejection, resolver selection,
  explicit-download remote acquisition, SHA verification, safe archive
  extraction, staged-payload reuse, and no-host-cache leakage from both source
  checkout and packaged-runtime paths. The next non-Tart production slice is the
  direct-SSH clean-machine preflight gate: it should consume the archived `.pkg`
  and release evidence JSON, refuse Tart resolution, verify target readiness and
  package acceptance without installing, and report `unsafe-target` on dirty
  unmarked machines. Remaining production choices after that preflight are
  non-Tart package install/provisioning execution, browser or device auth
  onboarding UX, launchd enablement policy, alpha/pre-release channel policy,
  independent archive signature policy, and broader UI/device bridge coverage
  such as screenshot, snapshot, gesture, or device execution if product scope
  requires them. Raw unwrapped stock Codex Electron/CLI route parity remains
  blocked;
- decide whether automated browser/device login UX, token freshness validation,
  or cross-machine credential packaging is product scope; or
- broaden the Apple workflow smoke to release/readiness/review only if product
  cutover requires that higher-fidelity path.

If ChatGPT mobile/app-server remote resume compatibility becomes product scope
later, reopen that as a new Omnigent-side remote-resume proof instead of
carrying it in a Codex fork.
