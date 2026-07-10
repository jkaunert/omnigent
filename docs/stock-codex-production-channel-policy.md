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

The stock-Codex compatibility installer has an independent release version at
`packaging/stock-codex-compat/VERSION`. It does not reuse or mutate the root
Omnigent `project.version`, because that version belongs to the three lockstep
PyPI packages documented in `RELEASING.md`. Compatibility installer releases
use stable `MAJOR.MINOR.PATCH` values and tags shaped as
`stock-codex-compat-v<version>` so they cannot collide with or trigger the
upstream `vX.Y.Z` PyPI/GitHub release workflow.

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
`stock-codex-compat-pkg-clean-vm-live` can use either proof-scoped copied auth for
legacy Tart rehearsal or an already-authenticated remote `CODEX_HOME` in place
for direct-SSH release evidence. Neither mode uploads the host stock Codex
binary, and the direct mode does not upload credential contents. Both run a real
model turn through the installed compatibility launcher after in-VM
acquisition. When the harness
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
count mismatch, or host stock-Codex upload. Direct-SSH release evidence also
fails closed unless it names an absolute remote existing auth home, reports the
matching available `auth.json`, and records `authUploaded=false` for onboarding,
persistence, and live. The recorded command must name the same SSH target and
remote auth home.

A package intended for distribution must enter those gates through
`scripts/promote_stock_codex_compat_release.py`, not through separate hand-run
producer and release-candidate commands. Promotion is permitted only from a
clean commit that matches both its local tracking ref and the live remote branch;
the producer, release-candidate wrapper, and offline checker must be tracked
files whose content matches that commit. The command requires an explicit
Developer ID Installer identity and notarytool profile, writes a new immutable
release directory, and emits the manifest only after package signing,
notarization, clean-target validation, offline evidence validation, signature,
staple, Gatekeeper, and embedded package-metadata checks all pass. Release review
must archive the `.pkg`, release evidence JSON, and promotion manifest together,
and publish the manifest SHA-256 through the trusted release channel. The
promotion script does not upload or publish those artifacts and the manifest is
not a detached signature by itself.

Publish a promoted compatibility package only after its source commit is clean,
pushed, and tagged on the fork with the independent tag namespace:

```sh
VERSION=0.1.2
git tag -a "stock-codex-compat-v${VERSION}" -m \
  "Omnigent Stock Codex Compatibility ${VERSION}" <promoted-source-commit>
git push origin "stock-codex-compat-v${VERSION}"

uv run python scripts/publish_stock_codex_compat_release.py \
  --promotion-dir "/absolute/path/to/promoted-${VERSION}" \
  --output-dir "/absolute/path/to/publication-${VERSION}" \
  --repository jkaunert/omnigent \
  --tag "stock-codex-compat-v${VERSION}"
```

The publisher verifies the promotion directory first, requires the local and
remote tag to resolve to the promoted source commit, refuses a preexisting
release, creates a draft release, uploads the package, release evidence,
promotion manifest, `SHA256SUMS`, and `publication-record.json`, then downloads
the complete draft asset set and re-hashes it. Only after that draft check passes
does it publish a stable release. It then accesses the public GitHub API and
downloads every asset without credentials, verifies all hashes again, and
requires the release body to contain the publication-record SHA-256. A failure
before publication deletes the attempted draft and partial publication output.
The package remains authenticated independently by its pinned SHA-256 plus its
Developer ID signature, notarization ticket, and Gatekeeper acceptance.

Verify the public release again without mutating GitHub:

```sh
uv run python scripts/publish_stock_codex_compat_release.py \
  --verify-only "/absolute/path/to/publication-${VERSION}/publication-record.json"
```

Then prove the distribution channel from a disposable clean Mac rather than by
uploading the host package:

```sh
uv run python scripts/prove_stock_codex_compat_published_release.py \
  --publication-record "/absolute/path/to/publication-${VERSION}/publication-record.json" \
  --ssh-target omnigent-clean@10.0.0.10 \
  --ssh-identity ~/.ssh/mba_github_ssh_key
```

That proof verifies the public release first, sends only a shell program over
SSH, downloads the package on the target from the public GitHub asset URL,
checks SHA-256, Developer ID signature, staple, and Gatekeeper, installs into the
real `/Library`, checks receipt and payload version, then removes the payload and
receipt and confirms package, launcher, adapter, stock cache, and LaunchAgent
state are absent. It does not upload the package, stock Codex, or auth material.

The first completed public-channel proof is
[`stock-codex-compat-v0.1.2`](https://github.com/jkaunert/omnigent/releases/tag/stock-codex-compat-v0.1.2),
published on 2026-07-10 from source commit
`cb2520a9e748ccf5da987926ae6a70ad519994b0`. Its package SHA-256 is
`42d61a2e93b384297d968bd1092d08eb26e4f5f62688a3c7b8908d063a97525b`,
promotion-manifest SHA-256 is
`7d1675a5c9275b273782a63e4277d075eba5005c9df7922848fb74aa946f6713`,
and publication-record SHA-256 is
`3f0dd33395c0ab295ae628ecb0a8b6345ab220df9891888a0df38a99265a865e`.
Independent public verification and the disposable clean-Mac URL install and
cleanup proof both passed without host package or auth upload.

For non-Tart targets, run
`stock-codex-compat-pkg-nontart-clean-machine-preflight` before any package
install or auth/live proof. That gate consumes the archived `.pkg` plus release
evidence JSON, refuses Tart resolution, checks the operator-supplied SSH host
for `uvx`, noninteractive `sudo`, disposable marker, clean Omnigent state,
remote package SHA, signature, staple, and Gatekeeper acceptance, and reports
`unsafe-target` instead of cleaning or installing on a dirty unmarked machine.
