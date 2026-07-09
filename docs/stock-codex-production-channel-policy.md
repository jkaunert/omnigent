# Stock Codex Production Channel Policy

This policy defines the production source boundary for provisioning stock Codex
payloads under the Omnigent replacement track.

## Policy

Policy name: `official-openai-github-release`

Accepted artifacts must satisfy all of these checks:

- They are selected from a `kind: omnigent-stock-codex-channel` manifest.
- The selected artifact uses a `url` source, not an arbitrary local `path`.
- The URL is
  `https://github.com/openai/codex/releases/download/<tag>/<archiveExecutable>.tar.gz`.
- The artifact is a `.tar.gz` archive with `archiveFormat: tar.gz`.
- The artifact declares the executable member to extract through
  `archiveExecutable`.
- The selected artifact records a 64-character SHA-256 digest.
- The provisioner verifies an existing channel-managed payload before any
  remote download is attempted.
- A stale or mismatched existing payload fails closed unless `--force` is
  explicit.

## Versioning

The policy supports exact version pins. Channel manifests may mark a `latest`
value, but production install/update code should record the selected exact
version and SHA-256 in the installed payload manifest before the payload is used.

The production channel proof exercises the exact pin path. The update doctor
proof exercises version comparison, dry-run planning, preverified target
detection, promotion intent, rollback intent, and up-to-date promotion
suppression. The update acquisition proof exercises explicit remote download,
SHA-256 verification, safe archive extraction, reusable staged payloads, and
promotion/rollback planning without promoting persistent pointers. Automatic
update scheduling, staged rollout policy, pre-release channel adoption, and
persistent launcher pointer promotion are separate product decisions.

## Rollback

Provisioned payloads live in versioned cache directories:

`<cache-root>/<version>/codex`

That layout preserves older payloads as rollback candidates. This policy does
not define an automatic rollback daemon or persistent pointer update flow. The
update doctor emits rollback intent by retaining the current Codex path and
relying on versioned-cache payload retention.

## Proof Gate

Run:

```sh
uvx --from . python scripts/prove_stock_codex_replacement.py \
  --proof stock-codex-production-channel-policy \
  --codex-path ~/.local/omnigent/codex-stock/0.142.5/codex
```

The proof is temp-rooted. It validates the policy, proves matching payload reuse
without remote download, proves non-official URL rejection before cache mutation,
and proves Omnigent resolver selection through `OMNIGENT_STOCK_CODEX_PATH`.

Run the update doctor gate:

```sh
uvx --from . python scripts/prove_stock_codex_replacement.py \
  --proof stock-codex-update-doctor \
  --codex-path ~/.local/omnigent/codex-stock/0.142.5/codex
```

The proof is temp-rooted. It proves `--plan-update` requires the production
channel policy, dry-run planning reports `stage-required` without cache
mutation when the selected target is absent, promotion material is withheld
until `promotion.ready=true`, preverified targets report `stage-ready` with
launcher promotion and rollback intent, and already-current targets report
`up-to-date` with promotion suppressed.

Run the update acquisition gate:

```sh
uvx --from . python scripts/prove_stock_codex_replacement.py \
  --proof stock-codex-update-acquisition \
  --codex-path ~/.local/omnigent/codex-stock/0.142.5/codex
```

The proof is temp-rooted. It reads the official Homebrew cask metadata with
auto-update disabled, writes an official OpenAI GitHub release channel
manifest, proves remote acquisition fails closed without
`--allow-remote-channel-download`, downloads the selected release archive only
with explicit opt-in, verifies the expected cask SHA-256, extracts the declared
executable, records channel provenance, proves reuse without another remote
download, and verifies the acquired payload resolves through
`OMNIGENT_STOCK_CODEX_PATH`. On 2026-07-07, the official stable cask and GitHub
latest release both selected `0.142.5`; `0.143.0-alpha.37` existed as a
pre-release and is not part of this stable production-channel policy.

Run the package-installed runtime acquisition gate:

```sh
uvx --from . python scripts/prove_stock_codex_replacement.py \
  --proof stock-codex-compat-pkg-update-acquisition \
  --codex-path ~/.local/omnigent/codex-stock/0.142.5/codex
```

This proof builds and stages the compatibility `.pkg` under a temporary
installed-root shape, then runs the installed runtime's bundled
`runtime/scripts/provision_stock_codex.py` under a clean temporary `HOME`. It
proves the same stable official remote acquisition contract from packaged
runtime code rather than from the development checkout.

The disposable clean-VM gates prove the same channel boundary through the
production-shaped install path. `stock-codex-compat-pkg-clean-vm-remote-acquisition`
copies only the signed/notarized package, a URL-backed channel manifest, and the
remote proof script into the VM, then installs into the VM's real `/Library` and
downloads/verifies the official OpenAI GitHub archive there. The live extension
`stock-codex-compat-pkg-clean-vm-live` adds only proof-scoped copied stock auth,
does not upload the host stock Codex binary, and runs a real model turn through
the installed compatibility launcher after in-VM acquisition. When the harness
starts Tart itself, the package-consuming clean-VM gates first run a
marker-gated cleanup of known proof-owned launcher, cache, auth, update-agent,
payload, and receipt state so repeat runs cannot pass or fail because of stale
proof residue. Direct SSH-target runs keep stale state as a hard blocker. The
release aggregate `stock-codex-compat-pkg-clean-vm-release` runs the
remote-acquisition, auth-onboarding, auth-persistence, update-agent, and live
extensions against one package and one channel selection, fail-fast, so release
validation does not rely on manually stitching those gates together. Release
operators should enter that aggregate through
`scripts/prove_stock_codex_compat_release_candidate.py`, which is the checklist
gate for stock-Codex compatibility package release candidates. Release review
should run that wrapper with `--evidence-output` and archive the generated JSON
next to the `.pkg`; the artifact records package and official-channel SHA-256
values, aggregate and per-step statuses, Tart start/stop counts, host-stock
upload status, and live/auth thread IDs without relying on terminal log
scraping. The offline verifier
`scripts/check_stock_codex_compat_release_evidence.py` should then be run
against the archived `.pkg` and evidence JSON to re-hash the package and fail
closed on schema drift, non-official channel evidence, non-ready steps, Tart
count mismatch, or host stock-Codex upload.
