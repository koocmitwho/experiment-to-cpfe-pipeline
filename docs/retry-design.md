# Proposal: retry failed stages with immutable attempts

**Status: design for maintainer review, 2026-09-27.** The current CLI continues
to use one recorded attempt per stage. The proposed interface is
`pipeline <stage> --retry --config <original-config> --run-dir <existing-run>`.

## Directory and identity

Keep the existing run and its original `run_manifest.json`, input lock,
configuration digest and stage artifacts. A retry creates
`attempts/<stage>/0002/` with its own `input/`, `solver/`, `dataset/` and `reports/`.
The attempt receipt records its stage, monotonically increasing attempt number,
parent-attempt receipt hash, original run-manifest hash and exact prerequisite
attempt IDs. A run-level append-only attempt index selects the accepted result
for downstream stages. A filesystem lock serializes index updates.

## Admission and execution

1. Verify the original configuration, input lock and every required artifact
   against their existing receipts. Changed input or code/dependency identity
   selects a new run with an explicit parent reference.
2. Permit retries of failed or blocked stages. An accepted completed attempt
   remains fixed; downstream work refers to its exact receipt.
3. Stage verified prerequisites into the fresh attempt directory. For example,
   retry extraction against a recorded ODB after an extraction-command failure,
   retaining the expensive completed analysis.
4. Record running, completed, failed or interrupted state in the new attempt.
   Validate resulting data and publish the receipt atomically before adding
   its index entry. Only then may downstream stages select it.
5. If a successful analysis lacks its recorded ODB, report the missing artifact
   against the original receipt. Recovery accepts a supplied ODB only when its
   bytes match the already recorded digest; otherwise a new analysis is required.

## Integrity and interruption

Original receipts and digests are read-only inputs to retry admission. Each
attempt hashes only its new artifacts and records references to old receipts.
A changed or missing previous artifact remains an integrity error. Index entries
chain to the previous index-entry digest. After interruption, a new attempt
records recovery state and the last verified index entry; partial output remains
associated with the interrupted attempt for inspection.

## Acceptance tests for a future implementation

- Failed extraction followed by a valid retry reuses the verified ODB and keeps
  every original artifact and receipt byte unchanged.
- Changed config, source, ODB or prerequisite receipt fails admission before
  launching a process or allocating a completed-result reference.
- Concurrent retries allocate distinct attempts and serialize index publication.
- Interruption before/after receipt publication produces an auditable state;
  downstream export selects only a completed, validated attempt.
- Existing single-attempt runs remain readable through `pipeline inspect`.

The proposal adds a new attempt schema alongside the existing run schema.
Implementation and migration follow maintainer approval of these semantics.
