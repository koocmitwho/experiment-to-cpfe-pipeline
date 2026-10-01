# Build training collections from canonical samples

`build-training-dataset` combines configured project HDF5 inputs into numerical
features and targets, aligning records by identity and preserving units, groups
and source selections. v1 declares a scalar target; v2 declares an ordered list
of targets. Dataset construction uses the base installation. The scalar CPU MLP
uses the `training` extra and v1 train/validation/test bundles:

```text
python -m pip install -e ".[training]"
pipeline build-training-dataset --config build.yaml --run-dir runs/dataset-001
pipeline train-surrogate --config runs/dataset-001/training-config.json --run-dir runs/model-001
```

Use a fresh directory for each command. Input paths resolve relative to the build
configuration. Training settings include `epochs`, `patience`, `seed`, `hidden`
and `learning_rate`. The trainer fits normalization on training rows, selects a
checkpoint by validation MSE and reports split errors and a mean baseline.

## Table selectors

This example reads three canonical samples. Their source assets declare
extension in mm, stiffness in N/mm and force in kN:

```yaml
version: 1
features:
  - {name: extension, unit: mm}
  - {name: stiffness, unit: N/mm}
target: {name: force, unit: N}
group_by: sample_id
grouping_evidence: Each sample identifies an independent parameter case
layouts:
  curve:
    alignment_evidence: Inputs and responses use the same increment identity
    columns:
      extension:
        kind: table
        table: measured_observations
        column: extension
        id_columns: [increment]
        source_unit: mm
      stiffness:
        kind: table
        table: measured_observations
        column: stiffness
        id_columns: [increment]
        source_unit: N/mm
      force:
        kind: table
        table: measured_observations
        column: force
        id_columns: [increment]
        source_unit: kN
        conversion: {factor: 1000, offset: 0, reason: Convert kN to N}
inputs:
  - {path: a.h5, sample_id: case-a, layout: curve, split: train}
  - {path: b.h5, sample_id: case-b, layout: curve, split: validation}
  - {path: c.h5, sample_id: case-c, layout: curve, split: test}
```

Feature order determines input order. A layout supplies every feature and target
column. Separate files may select different layouts. `where` filters row values,
for example `where: {source_asset_id: sensor-A}`. `id_columns` can be composite,
such as `[step, frame, node_label]`. Each column has the same unique identity set;
alignment preserves the first feature's order and reorders other columns to it.

Extracted ODB rows bind to their `odb-extraction-bundle` asset through
`source_asset_id`. A selector may also supply an explicit matching `asset_id`.
Use `where` to select field/component, with `value` units checked against both
the field unit on the asset and the row's `unit`. `unit_key` selects an existing
unit declaration for renamed columns; all available declarations must agree.

Layout `rows: {start: 0, stop: 20, step: 2}` selects every second aligned row in
the first twenty. Indices are zero-based, stop is exclusive and step is positive.
The same selection applies to every feature and target and retains original row
indices. Empty or out-of-bounds selections produce a diagnostic.

## Array selectors

For a `[channel, row]` array, select the second channel with:

```yaml
kind: array
array: channels
asset_id: channels-normalized
ids: increment_ids
row_axis: 1
component: [1]
unit_key: gain
source_unit: V
```

The asset binds the array through `descriptive_metadata.array_key`. `ids` is a
unique integer/string vector matching the record axis. `component` selects one
index for each remaining axis in natural axis order. A one-dimensional array
uses `row_axis: 0` and an empty component selection. Native component names,
entity identities and entity axes participate in checks. Store upstream
aggregation or registration results with their definitions in the canonical
sample before selecting them.

## Units, grouping and source partitions

`source_unit` agrees with the registered asset or converted `normalized_units`.
Output units come from `features`, `target` or `targets`. A conversion computes
`value * factor + offset` and records its rationale.

| `group_by` | Group identity |
|---|---|
| `sample_id` | SampleMetadata sample identity |
| `experiment_id` | Shared experiment identity across samples |
| `explicit` | Each input supplies `group_id` with grouping evidence |

All rows of one group remain in one split. Train and validation are required for
construction, and test is optional; each present split has at least two rows.
The scalar trainer defaults to all three. Explicit `evaluation_mode: external_test`
requires exactly train/validation and leaves test responses external. It accepts
v1 scalar bundles only; v2 target lists are rejected before model output creation.
The builder checks sample identity, file
content, existing split declarations and native target group/split declarations.

Target origins are checked across splits by file digest and URI. Shared feature
or calibration sources retain their respective roles. A shared original table
can declare its physical specimen column:

```yaml
inputs:
  - path: coupon-a.h5
    sample_id: coupon-a
    layout: specimen
    split: train
    target_specimen:
      column: specimen_id
      evidence: Original worksheet column A identifies each physical specimen
```

Every selected target row carries the declared specimen identity, original
`source_row`, worksheet where applicable and a verified table-conversion receipt.
The builder checks specimen and worksheet/row intersections. Whole-file and
specimen-level source partitions remain consistent. `dataset.json` records
`target_partitions`, including specimen, source rows, identity column and basis.
The original source URI, digest and asset chain remain attached.

`column_partitions` bind every compatible selected feature/target to
the original text identity column, sheet/row and complete conversion receipt.
Changing the identity column does not establish independent scope. Strict task
contracts use those verified scopes; uncovered roots remain whole-file.

Version 0.3.0 adds `infer-surrogate`, `evaluate-surrogate` and two scalar
`template-config` drafts. Contracts propagate unchanged; predictions use frozen
training normalization, evaluation aligns sample/row/group identity and does not
reopen model/training sources. [Real-case guide](real-case-workflow.en.md).

## v2 and task declarations

Set `version: 2` and replace `target` with an ordered `targets` list to build named
multi-target arrays. Target-list order is retained in data and metadata. Optional
task contracts describe prediction time, input availability, source roles,
required context and grouping identity. See the [data-foundation guide](data-foundation.md)
for a complete v2 example and assessment states.

## Inspect artifacts

| File | Contents |
|---|---|
| `dataset.npz` | Features, targets, groups, splits, sample IDs, row identities and JSON metadata |
| `dataset.json` | Quantity order/units, configuration, sample metadata, asset chains, source rows, transformations and groups |
| `training-config.json` | Dataset-relative path, quantity declarations and content receipts |
| `build-manifest.json` | Build status and configuration/input/output receipts |

Read arrays with `np.load(path, allow_pickle=False)`. Row identities are JSON
lists that preserve integer and string components. Training writes
`dataset-receipt.json`, `training.json`, checkpoint and predictions.

The training NPZ format is `experiment-to-cpfe-training-1`; the full sample NPZ
from `pipeline export --format npz` preserves the whole SamplePackage. Legacy
four-array training bundles retain their training entry. Canonical HDF5 provides
the source contract; vendor HDF5 enters through its configured adapter.

The [synthetic example](../examples/synthetic_training/README.md) generates table
and array layouts. The [GH4169 example](../examples/gh4169_ultrasonic/README.md)
demonstrates specimen grouping from a shared workbook. The public tensile case
retains its documented physical reduction, interpolation and evaluation splits.
