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

The current proof gate exercises the exact pin path. Automatic update
scheduling, staged rollout, and persistent launcher pointer promotion are
separate product decisions.

## Rollback

Provisioned payloads live in versioned cache directories:

`<cache-root>/<version>/codex`

That layout preserves older payloads as rollback candidates. This policy does
not yet define an automatic rollback daemon or persistent pointer update flow.
Those should be added only after the acquisition policy, signing/notarization
path, clean auth boundary, and installed runtime bootstrap remain green.

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
