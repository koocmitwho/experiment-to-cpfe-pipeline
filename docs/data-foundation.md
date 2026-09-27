# Data foundation: files, samples and datasets

This guide covers the v0.2.0 experimental-file, normalization, dataset,
evaluation-protocol and handoff commands. The example runs with the base
installation on Python 3.12 or newer.

## Run the complete example

From the repository root with the environment activated:

```text
python -m pip install -e .
python examples/data_foundation/workflow.py --run-dir runs/data-foundation-001
```

The script generates three synthetic specimens with four rows each. Force is
`2 * command + 0.1 * specimen_index`, in N. Two specimens supply eight training
rows and the third supplies four validation rows. A separate CSV demonstrates
declarative normalization. Checks cover unknown-header preservation, HDF5
readback, input-availability rules and group isolation.

Use a fresh output directory for each run. The twelve rows belong to three
declared statistical groups. Feature and target arrays both have shape `(12, 1)`.
The original `unknown_header` remains in context `raw_metadata`.

## Find the outputs

Paths are relative to `--run-dir`:

| Path | Contents |
|---|---|
| `inputs/`, `configs/` | Generated JSON/CSV sources and the configuration for each command |
| `imports/<specimen>/sample.h5` | Canonical sample for each specimen |
| `imports/<specimen>/experiment-context.json` | Context states, original metadata and script receipts |
| `imports/<specimen>/experiment-file.json` | Import status, source hash and artifacts |
| `normalized/sample.h5`, `normalized/normalization.json` | CSV normalization and readback evidence |
| `dataset/dataset.npz` | Features, targets, groups, splits, sample IDs and row identities |
| `dataset/dataset.json` | Units, selectors, lineage, task contract and checks |
| `dataset/training-config.json` | Dataset path, content binding and quantity declarations |
| `dataset/build-manifest.json` | Build configuration, input and artifact receipts |
| `protocol/evaluation-protocol.json`, `protocol/REPORT.md` | Protocol metadata and saved-evidence checks |
| `intake/intake-status.json`, `intake/REPORT.md` | Selected handoff checkpoints and reviewer evidence |
| `verification.json` | Synthetic workflow execution summary |

## Run individual commands

After the complete example has generated its configurations and sources:

```text
pipeline import-experiment-file --config runs/data-foundation-001/configs/specimen-a.json --run-dir runs/data-foundation-import-002
pipeline normalize-sample --config runs/data-foundation-001/configs/normalize.json --run-dir runs/data-foundation-normalize-002
pipeline build-training-dataset --config runs/data-foundation-001/configs/build.json --run-dir runs/data-foundation-dataset-002
pipeline check-evaluation-protocol --config runs/data-foundation-001/configs/protocol.json --run-dir runs/data-foundation-protocol-002
pipeline check-intake-status --config runs/data-foundation-001/configs/intake.json --run-dir runs/data-foundation-intake-002
```

Each command reads the original example's configuration. Dataset reconstruction
uses its three HDF5 inputs. Update the `inputs` paths when selecting another
import batch or relocating the example. Inspect a failed operation's status file,
correct the configuration and use a fresh directory for the next attempt.

## Experimental context and normalization

`import-experiment-file` supports `self_describing_json_v1` and
`bam_lis_context_v1`. The JSON profile reads declared sample metadata, units,
observation rows and context; BAM uses an explicitly supplied LIS task profile.
`source.path` and `source.sha256` bind the file, with purpose, license and
`evidence_scope` supplied by the configuration. The example uses
`synthetic_mechanism_only`.

Context entries use `confirmed`, `unconfirmed`, `unavailable` and `not_applicable`
for identity, material, geometry, loading, temperature, preload, zeroing,
measurement timing and preprocessing. Each state retains its declared basis.
Confirmed acquisition timestamps include a time zone. Unknown fields remain in
the original metadata record. Optional `scripts` capture file paths, hashes,
declared versions and purposes as acquisition/processing receipts.

`normalize-sample` consumes explicit table, asset and native-import declarations.
Each mapped quantity has a unit. The command writes HDF5, verifies its readback,
and records configuration and input hashes. `validate` adds the solver-readiness
checks used by the Abaqus workflow.

## Dataset declarations and task contracts

The builder selects table columns or array components from canonical HDF5 and
aligns them by row identity. Affine unit conversions include a scale, offset and
rationale. The resulting metadata retains source rows, assets and split groups.

- v1 declares one scalar `target`.
- v2 declares an ordered `targets` list; its order determines output columns.
- Grouping uses `sample_id`, `experiment_id` or explicit `group_id`.
- Train and validation partitions are required; test is optional for dataset
  construction. Each present partition contains at least two rows.
- Shared workbooks can declare `target_specimen` using an original specimen
  column and verified source-row provenance; see the [GH4169 example](../examples/gh4169_ultrasonic/README.md).

The task contract records prediction time, available inputs, target quantities,
units, spatial/temporal scope, required context and independent grouping identity.
Checks identify future inputs, target-derived predictors, source-role reuse,
group overlaps and preprocessing fitted on held-out records. Legacy
configurations receive `legacy_unassessed`; assessed configurations receive
`declared_ready` or `conditional` with their supporting declarations.

For scalar CPU MLP training, use the v1 target declaration and train/validation/test
configuration in the [training guide](training-datasets.md) and
[synthetic training example](../examples/synthetic_training/README.md).
The data-foundation example demonstrates v2 dataset construction with two splits.

## Evaluation and handoff records

`check-evaluation-protocol` counts unique conditions, statistical groups and
expanded records, checks role overlap and declared holdout axes, and verifies
optional saved metric values through file hashes, value pointers and units.
Configured thresholds receive explicit comparison results. The synthetic example
uses three generated conditions and their batch declarations.

`check-intake-status` records a reviewer, basis, conditions, blockers and evidence
for each selected checkpoint. States are `ready`, `conditional`,
`awaiting_information` and `not_applicable`. The example identifies the reviewer
as the automated synthetic workflow. The JSON report preserves each checkpoint's
status alongside the report's processing status.

[Project overview](../README.md) · [Schema](schema.md) · [Abaqus runbook](runbook.md)
