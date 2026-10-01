# v0.2.2 capabilities and operating conditions

Version 0.2.2 supports experimental-file import, sample normalization, dataset
construction, evaluation and handoff checks, Abaqus preparation and execution,
ODB field extraction, and HDF5/NPZ/PyG exports.

## Data foundation

| Command | Inputs and operations | Outputs and operating conditions |
|---|---|---|
| `import-experiment-file` | Self-describing JSON or the configured BAM LIS context profile; declared file hash, units, evidence class and context | Canonical HDF5, original metadata, unknown fields, context states and acquisition/processing-script receipts |
| `normalize-sample` | Explicit table mappings, asset declarations and native imports; per-quantity units and coordinate conventions | HDF5 with readback, diagnostics, configuration and source receipts |
| `build-training-dataset` | Canonical HDF5, table columns or scalar array components, row identities and grouping | v1 scalar or v2 ordered multi-target arrays; train/validation and optional test partitions; source, unit and task-contract records |
| `check-evaluation-protocol` | Declared condition/group identities, splits, holdout axes and optional saved metric evidence | Unique counts, role-overlap checks, holdout metadata, metric values/units and explicit threshold comparisons |
| `check-intake-status` | Selected checkpoints, reviewer, basis, status, conditions and evidence files | Reviewed checkpoint states, evidence receipts and a handoff report |

The [data-foundation guide](data-foundation.md) provides commands and output
locations. Import profiles and selectors provide the interpretation of each
source format. Context states are `confirmed`, `unconfirmed`, `unavailable` and
`not_applicable`, carrying the submitted basis for each declaration.

`check-evaluation-protocol` returns exit code 0 when configuration/evidence
checks and report generation complete. A metric's `not_met` threshold or an
unverified holdout remains an explicit finding in that report. The scientific
claim status is a report field, not a command exit code. Invalid configuration,
unreadable evidence and content-hash mismatches return exit code 1.

Dataset columns align through unique row identities. Explicit affine conversion
records source units, target units, scale, offset and rationale. Groups and
physical target-source rows remain within one split. Shared workbooks can use a
verified original specimen column to declare specimen-level partitions.

`train-surrogate` consumes v1 scalar-target bundles. Default `bundled_test` mode
requires train/validation/test; explicit `external_test` requires
exactly train/validation. V2 target lists remain unsupported by this trainer.
CPU MLP normalization fits training rows and checkpoints use validation MSE;
OLS coefficients fit training rows only. Independent prediction and
evaluation support scalar MLP/OLS with explicit names/units and source/identity
checks. [Real-case guide](real-case-workflow.en.md).

## Native data interfaces

Readers cover explicit CSV/TXT/JSON/XLSX blocks, configured ANG/CTF text,
selected HDF5 datasets, MAT5 numeric/struct/cell arrays, multichannel NPY,
scalar ASCII VTI, Gmsh 2.2 ASCII and grain-graph text bundles. The
[format guide](data-modalities.md) describes selectors and source declarations.

Image assets and vendor-native files retain format, location and source records.
Prepared numerical exports connect image processing, MATLAB object properties,
spatial registration and instrument-specific decoding to the numerical readers.
Upstream transformations retain their definitions and parent-asset records.

HDF5 slicing and NPY selection bound the requested arrays. MAT5 loads the selected
variable before selecting a nested field; working memory includes that variable
or the decompressed HDF5 chunk. Dataset construction and derived exports assemble
their selected payload in memory. Native numerical import defaults are 64 MiB
for selected data and 128 MiB for MAT5/text source files.

## Abaqus material and loading profiles

The checked profile uses a flat three-dimensional solid mesh, one named material
and one static displacement step. Supported elements are C3D4, C3D8, C3D8R,
C3D10, C3D20 and C3D20R. The gate compares geometry, assignments, boundary
conditions, material constants and output requests with the expanded deck.

- `isotropic_elastic` supplies explicit `E` and `nu` matching `*ELASTIC`.
- `isotropic_plastic` adds at least two stress/plastic-strain pairs matching
  one plain `*PLASTIC` block. Plastic strain starts at zero and increases
  strictly; stress is positive and nondecreasing.
- `umat` supplies constants, one unit per constant, a positive DEPVAR count
  and the configured user-subroutine source. Grain orientation can map to
  STATEV through complete `*INITIAL CONDITIONS, TYPE=SOLUTION` initialization.

Isotropic models can use material-region mapping and a reasoned orientation
applicability declaration. Crystalline declarations retain grain assignments,
orientation conventions and the supplied constitutive model. Units, coordinate
frames and tensor order are explicit. See the [runbook](runbook.md).

## Extraction, validation and export

ODB extraction preserves requested field/component names and stored location
labels. `E` and `LE` retain their respective strain measures. Each field has a
declared unit; extracted rows bind to their simulated extraction asset.

`frame_value` follows the ODB frame domain. `frame_time` is step-relative for
TIME frames, with a separate clock for each source, step and load case. Ordinary
table `time` is checked on its own clock. Each increment ID identifies one frame
within its source/step/load path; multiple fields, components and locations share
that frame. Full location/component identity determines row uniqueness.

HDF5 export validates the merged sample and records the report in its own stage.
The initial validation report remains the receipt for the initial sample.
NPZ/PyG exports verify and read the canonical HDF5. `export.formats` declares
the enabled export formats. PyG uses supplied graph arrays, node identities,
feature names/units and directedness.

## Cases, evidence and distribution

The public CuSn8Ni2 case covers the stated 0–0.8% small-strain gauge response
with separate calibration, model-check and experimental-holdout specimens.
The GH4169 case compares scalar regression methods on ten specimen summaries
with the recorded development and author-test splits. Results and their case
definitions are linked from the [README](../README.md).

Stage receipts preserve inputs and artifacts; manifests record tool, Python,
dependency versions and executing package-source fingerprints. Dated
[verification records](verification/) retain the commands and evidence for each
historical check. Project code uses Apache-2.0; third-party materials retain the
terms listed in [licensing.md](licensing.md).
