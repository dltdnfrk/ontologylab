# macOS internal deployment

These commands are for controlled, same-user installation of the unnotarized Apple Silicon build. They do not make the app notarized, Developer-ID signed, or suitable for public distribution. Run them from the frozen source checkout that produced or received the candidate; all Python execution is `--frozen --offline`.

## Artifact receipt

The transfer includes `OntologyLab.app`, a receipt, and the SHA-256 of the receipt file through a separate trusted channel. The receipt is strict JSON:

```json
{
  "schema": "ontologylab.internal-artifact-receipt.v1",
  "artifact_name": "OntologyLab.app",
  "app_tree_sha256": "<64 lowercase hex characters>"
}
```

The tree digest binds every relative path, file/directory type, permission mode, and file byte. Symlinks and special files are refused. The installer first rehashes the receipt, parses its closed schema, rehashes the supplied app, requires Apple Silicon and macOS 15+, checks the Task 7 canonical storage compatibility CLI and supervisor lock, and verifies that the destination is on APFS with the macOS atomic-exchange API before creating an install stage. It copies to a same-volume hidden directory and verifies the staged tree. Quarantine clearance walks the owned stage without following symlinks, inspects each path, and removes `com.apple.quarantine` only where that attribute is present. An attributed read-only path temporarily receives owner-write permission through its already-open file descriptor; its exact mode is restored and verified in all outcomes. Unattributed paths are never chmodded. The complete tree hash and strict nested code signatures are revalidated after clearance and before activation. A first install activates with one atomic rename. An update durably writes an activation journal and calls `renameatx_np(..., RENAME_SWAP)`, which exchanges the live and staged app in one filesystem transaction: there is no instant at which the live path is absent. The old app then occupies the stage path and is removed after the swap.

## Task12 terminal finalization

Only after the signed `OntologyLab.app`, immutable DMG, deterministic ZIP, and install receipt exist, run the source-owned packaging workflow as its terminal operation:

```sh
uv run --frozen --offline python -m release.task12_workflow \
  --final-dmg /controlled-final/OntologyLab-internal-arm64.dmg \
  --final-zip /controlled-final/OntologyLab-internal-arm64.zip \
  --final-app /controlled-final/OntologyLab.app \
  --install-receipt /controlled-final/OntologyLab.receipt.json \
  --external-receipts-dir /controlled-final/Task12-authority
```

The workflow refuses absent finals and delegates its terminal operation to `release.task12_finalize`; no build, signing, DMG, or ZIP mutation may follow it. Finalization stages the complete authority and digest in a unique retained non-authoritative sibling directory, rehashes every final, and exclusively renames that directory into the previously absent canonical path. It then writes the terminal marker exclusively and reopens, re-stats, and rehashes the canonical DMG, ZIP, app tree, install receipt, embedded installer, authority, digest, marker, and path identities. Success is returned only after those current values match the strict authority. Detected drift or read failure exclusively renames the entire canonical directory to a fresh same-volume `.retained-failure-*` sibling and fsyncs the parent, leaving the canonical path absent without deleting or overwriting bytes; name collisions retry with a fresh exclusive destination. Mutation after the workflow has returned cannot be prevented forever and is instead detected when consumers rehash all final inputs.

## Install or update

```sh
RECEIPT_SHA256=$(shasum -a 256 /controlled-transfer/OntologyLab.receipt.json | awk '{print $1}')
scripts/ontologylab-internal-install \
  --app /controlled-transfer/OntologyLab.app \
  --receipt /controlled-transfer/OntologyLab.receipt.json \
  --receipt-sha256 "$RECEIPT_SHA256" \
  --acknowledge-unnotarized
```

`--acknowledge-unnotarized` is mandatory and records the operator's explicit understanding that Gatekeeper trust is being changed for a non-notarized internal artifact. Never add the flag to an unattended generic installer. The default destination is `/Applications/OntologyLab.app`; `--destination` and `--home` exist for disposable rehearsal.

Stop OntologyLab before installing. A held `~/Library/Caches/ontologylab/runtime/supervisor.lock`, an active WAL, newer/unknown/corrupt storage, a hung preflight, a wrong receipt, stale artifact, partial copy, denied permission, x86_64 host, or macOS 14 and older produces a nonzero refusal before app activation. No install path creates, migrates, or deletes canonical data.

## Uninstall

The safe default removes only the app and runtime state. It preserves canonical data, packs, backups, logs, and Keychain items:

```sh
scripts/ontologylab-internal-uninstall
```

Data destruction is a separate domain and exact confirmation:

```sh
scripts/ontologylab-internal-uninstall \
  --remove-data \
  --confirm-remove-data REMOVE-ONTOLOGYLAB-DATA
```

Credential destruction is independently confirmed. Accounts can be discovered from the local source registry or named explicitly; deletion goes through the installed signed Keychain helper before the app is removed:

```sh
scripts/ontologylab-internal-uninstall \
  --remove-credentials \
  --credential-account elsevier \
  --confirm-remove-credentials REMOVE-ONTOLOGYLAB-CREDENTIALS
```

To remove both, supply both flags and both different confirmation tokens. Repeating an unconfirmed request remains a refusal. Uninstall also refuses while the backend lock is held.

For no-delete QA, the exact standalone executable uses a two-step retained-removal protocol. Task12 creates an external `ontologylab.task12-release-authority.v1` sidecar only after the final DMG exists. Its separately supplied SHA-256 authenticates strict fields for the final DMG, `zip_sha256`, install receipt, signed app tree, embedded deployment executable path and hash, version, architecture, and tree-hash schema. Prepare rehashes the supplied final ZIP against `zip_sha256` before creating its journal. The controller runs the verified standalone installer outside both the active app and retained root.

Prepare accepts authority only from the canonical directory when its authority JSON, matching digest sidecar, and terminal marker are the only three members; hidden `.retained-failure-*` directories are never authoritative. It rehashes the authority bytes, final DMG, final ZIP, install receipt, installed app tree, embedded installer, and actual running executable against the strict authority and requires canonical non-symlink final-input paths. It then validates quiescence, same-device placement, and collision-free app/runtime identities. It durably creates only the canonical prepared journal and prints a controller-held `prepared_anchor`; it performs no rename:

```sh
/path/from/verified-dmg/ontologylab-internal-deploy prepare-retained-uninstall \
  --app /absolute/qa/Applications/OntologyLab.app \
  --home /absolute/qa/home \
  --retain-removals-under /absolute/qa/retained-removals \
  --release-authority /controlled-final/Task12-authority/OntologyLab.task12-release-authority.json \
  --release-authority-sha256 "$TASK12_AUTHORITY_SHA256" \
  --release-dmg /controlled-final/OntologyLab-internal-arm64.dmg \
  --release-zip /controlled-final/OntologyLab-internal-arm64.zip \
  --install-receipt /controlled-final/OntologyLab.receipt.json
```

The controller must preserve the printed anchor outside the retained root and supply that original value on every apply or recovery invocation:

```sh
/path/from/verified-dmg/ontologylab-internal-deploy apply-retained-uninstall \
  --app /absolute/qa/Applications/OntologyLab.app \
  --home /absolute/qa/home \
  --retain-removals-under /absolute/qa/retained-removals \
  --prepared-anchor "$PREPARED_ANCHOR"
```

Apply recomputes the domain-separated SHA-256 commitment from the exact first journal record before trusting any local progress, receipt, or tree field. Missing, malformed, substituted, or mismatched anchors refuse before mutation. Only after that check does forward-only recovery use exclusive same-volume renames for `OntologyLab.app` and the canonical runtime directory. Receipt and terminal records bind both the prepared anchor and Task12 authority digest. Data, packs, backups, logs, support state, and Keychain remain active. Crashes before or after either rename, either progress append, receipt creation, or terminal append resume with the same controller anchor; completed replay returns the same receipt. The old one-step retained option refuses, while ordinary uninstall without retained mode keeps its existing destructive selection.

This protects against coherent post-prepare rewriting of every owner-writable active/retained tree, journal, receipt, identity, event, timestamp, path, inode, device, mode, hash, and version field. It trusts the externally supplied genuine Task12 authority and digest, the verified running installer for each invocation, controller-held prepared anchor, SHA-256, and filesystem rename semantics. Compromise of the controller, verified DMG, or already-running verifier is outside the boundary and cannot be detected by local state.

## Support bundle

```sh
scripts/ontologylab-internal-support --output "$HOME/Desktop/ontologylab-support.zip"
```

The ZIP is local and contains only `support.json`: platform, presence flags, and aggregate counts. It never reads or includes raw documents, database bytes, settings, environment variables, Keychain values, log content, filenames, host/user names, or network data. Review the JSON before transfer. Delete the bundle after the support case closes.

## Recovery

- **Interrupted or partial copy:** interruption before exchange leaves the old live app; interruption after exchange leaves the new live app, the old app at the stage path, and `.OntologyLab.app.activation.json`. Re-running the same validated command compares the journal's expected digest to both paths, deterministically removes the non-live old stage, removes the journal, and retries. Ambiguous hashes are refused rather than guessed. APFS/atomic-exchange unavailability or a cross-device exchange is refused before app mutation.
- **Update refusal:** do not mutate the database or receipt. Resolve the named gate, rehash through the trusted channel, and retry.
- **Application will not start after update:** reinstall the previous app with its original receipt. Canonical state was not changed by installation.
- **Uninstall followed by reinstall:** use the normal installer. Preserved data and Keychain items are reused after Task 7 compatibility passes.
- **Support escalation:** attach only the metadata-only support ZIP and the non-secret command refusal. Never attach `data/documents`, SQLite files, settings, logs, or Keychain exports.
