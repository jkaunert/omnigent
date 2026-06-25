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
| Apple `.mcp.json` `sosumi` server execution through Omnigent | `replacement-ready` for the network-backed Apple documentation MCP server | `scripts/prove_stock_codex_replacement.py --proof apple-mcp-sosumi` converted the Apple plugin `.mcp.json` `sosumi` server into an Omnigent `tools: sosumi: type: mcp` declaration, then stock Codex `0.142.2` invoked `sosumi__fetchAppleDocumentation` with `/documentation/swift/string`; persisted session items included a `function_call` and matching `function_call_output` containing `title: String` and the Apple documentation source URL. |
| Apple `.mcp.json` `XcodeBuildMCP` project discovery through Omnigent | `replacement-ready` for read-only project discovery | `scripts/prove_stock_codex_replacement.py --proof apple-mcp-xcodebuild` converted the Apple plugin `.mcp.json` `XcodeBuildMCP` server into an Omnigent `tools: XcodeBuildMCP: type: mcp` declaration, then stock Codex `0.142.2` invoked `XcodeBuildMCP__discover_projs` against the local Omnigent checkout; persisted session items included a `function_call` and matching `function_call_output` that found `ap-web/ios/Omnigent.xcodeproj`. This does not prove build, test, launch, simulator, or device execution. |

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

Apple XcodeBuildMCP read-only discovery proof:

```bash
uvx --from . python scripts/prove_stock_codex_replacement.py \
  --proof apple-mcp-xcodebuild \
  --codex-path /opt/homebrew/bin/codex
```

The proof script copies the installed Apple workflow bundle into a temporary
Omnigent agent, writes an Omnigent `harness: codex` config, refuses
`.codex-fork` binaries by default, and removes the temp fixture unless
`--keep-fixture` is passed.

## Next Proof Gates

Run these in order unless a later gate becomes cheaper due to new evidence.

1. XcodeBuildMCP build/run boundaries
   - Extend the proven `XcodeBuildMCP` discovery path to bounded build/run
     checks only after selecting a safe local fixture. Keep build, test,
     simulator, and device checks separate so host setup failures do not blur
     the already-proven MCP adapter path.

2. Session and terminal behavior
   - Prove the Omnigent path supports the required live terminal/session shape,
     including tmux/native-terminal expectations where the workflow depends on
     them.

3. Clean stock-Codex install
   - Prove the path from a clean Codex home or clean host profile using the
     stock Codex binary. Record every required install/config step.

4. End-to-end Apple workflow smoke
   - Run a representative Apple workflow request through Omnigent plus stock
     Codex and compare the visible route, tool availability, and output contract
     against the current forked path.

5. Cutover rehearsal
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
