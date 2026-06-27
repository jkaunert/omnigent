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
| Router-selection matrix semantics: host scope, prompt boundaries, workspace signals, downstream route preservation, focused specialist suppression | `fa2fa9ba98`, `ab65f05df4`, `5be5163502`, `393f22fa01`, `f86f506f3a`, `67f216880e`, `dd0e591851`, `9b28f2aaba`, `ed4c40fecb`, `9567a9c98e`, `4286b74d90` | `unproven` for full stock-Codex live matrix | `omnigent.inner.router_selection` owns the adapter policy. `tests/inner/test_router_selection.py` covers prompt-signal boundaries, host scope, workspace files/extensions, skill filters, explicit downstream domain-route preservation, top-level duplicate suppression, focused specialist suppression, and foreign-plugin suppression. `tests/inner/test_codex_executor.py` covers route-prefix emission before Codex output for the preserved downstream-route case. This proves the local adapter matrix, not the live stock-Codex matrix. | Add a live stock-Codex router matrix proof before declaring the whole carry group replaceable. |
| Responses stream lifecycle diagnostics | `8eea3c5b34`, `07f2c46719` | `blocked` pending product-scope decision | No Omnigent replacement exists yet. These changes instrument provider stream lifecycle and classify early output-item stalls inside the Codex runtime. | Decide whether production needs these diagnostics after stock-Codex cutover. If yes, build an Omnigent-side session/stream diagnostic layer instead of modifying stock Codex. |
| HTTP fallback guard by provider URL | `bb07d63968` | `blocked` pending product-scope decision | No Omnigent replacement exists yet. This is a runtime provider safety guard, not an Apple workflow adapter behavior. | Decide whether stock Codex without this guard is acceptable. If not, prove an external harness guard or keep the carry. |
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

The current blocker is not more simulator gesture coverage. The largest direct
overlap still needing live proof is the router-selection matrix. The runtime
diagnostic and remote-resume groups need a product-scope decision before they
can be scored honestly.

## Next Proof Gate

The next narrow gate should be a live stock-Codex router matrix proof that
exercises:

- natural Apple prompt signal selects the top-level owner
- workspace marker or extension selects the same owner
- explicit downstream broad/domain route preserves top-level owner evidence
- explicit focused specialist suppresses top-level owner evidence
- non-desktop host scope does not auto-route

Passing that gate would move the router-selection matrix row from `unproven`
to `replacement-ready`.
