# Training data foundation: original design

> Historical design dated 2026-09-07. Editorial update: 2026-09-27. Current v1/v2 interfaces are described in the [training guide](../../training-datasets.md).

## Architecture and interfaces

Use a dedicated stage: canonical HDF5 -> configured selection and identity
alignment -> training NPZ -> scalar CPU MLP. Data construction reuses
SamplePackage, source assets and the training contract independently of
optimization.

- `datasets/training_config.py`: explicit configuration models.
- `datasets/training_columns.py`: table/array extraction, units, provenance and identities.
- `datasets/training.py`: `build_training_dataset(config, *, base_dir)` and `run_dataset_build(config_path, output_dir)`.
- `learning/data_contract.py`: shared grouping and training-bundle checks.
- CLI: `pipeline build-training-dataset --config ... --run-dir ...`.

The original version 1 configuration declares ordered feature names/units, one
target, named layouts with `alignment_evidence`, explicit inputs with expected
sample identity/layout/split, and grouping by sample, experiment or explicit ID.

## Selection and grouping

Table selectors provide table, column, composite row IDs, optional equality
filters and row or explicit asset binding. Units come from `normalized_units`
or `units`; ODB values use field-name units. Array selectors provide array,
asset, identity vector, record axis and component indices. The asset binds its
array through `array_key`. Both selectors yield finite real scalar columns.

Each column declares source units. `unit_key` selects a registered declaration;
all available field/component units agree. Explicit affine conversion computes
`value * factor + offset`, recording the rationale. Row identities align columns
one-to-one in first-feature order. A shared positive, bounded row slice records
original positions.

Sample and file identity checks accompany group/split checks. The original
training interface uses train/validation/test with at least two rows each.
Targets retain registered source roots; digest or common URI identifies source
reuse across splits. Shared calibration and feature sources retain their roles.
Grouping evidence and upstream source identities come from the data declarations.

## Artifacts and acceptance

Fresh output directories contain `dataset.npz`, `dataset.json`,
`training-config.json` and `build-manifest.json`. They preserve quantity order,
units, arrays, group/split/sample/row IDs, configuration, asset chains, selections
and conversions. The scalar trainer checks the bundle's format, content and
quantity contract while preserving the legacy four-array entry.

Acceptance uses table and array fixtures, unit conversion, reordered identities,
source and split conflicts, actual CPU optimization, checkpoint readback, wheel
installation and CI. The CuSn8Ni2 case retains H_08/H_16/H_18 roles and its
0–0.8% gauge-response definition. Project code and designated tensile materials
retain their Apache-2.0 and CC-BY-4.0 terms.
