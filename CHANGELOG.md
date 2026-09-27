# Changelog

## 0.2.1 — 2026-09-27

- Validate merged extraction records before canonical HDF5 export and retain
  stage-specific validation reports, field-time semantics and row provenance.
- Report missing extraction metadata with named ValueError diagnostics while
  retaining the version 0.1 bundle interface.
- Add CLI completion summaries and `--version`, enforce configured export formats,
  share validation policy through readiness and record runtime/source fingerprints.
- Fail unexpected pytest skips, add strict marker checks and a CPU PyG CI job,
  and exercise subprocess-family cleanup on both operating systems.
- Update v0.2.0 guides, material-profile instructions, project attribution and
  capability descriptions; preserve dated history in repository archives.
- Add a stable run-artifact checksum command and a retry-attempt design proposal.

## 0.2.0 — 2026-09-26

Data foundation release, distributed through GitHub source and Release artifacts.
No PyPI publication accompanies this version.

- Added explicit experimental-file import for self-describing JSON and configured
  BAM LIS profiles, preserving context, unknown fields, raw metadata, source hashes
  and acquisition-script receipts without executing those scripts.
- Added solver-independent sample normalization with HDF5 readback and diagnostic
  status records.
- Extended dataset construction with ordered multi-target arrays, optional test
  partitions, explicit task declarations, input-availability checks and source/role
  isolation while retaining the public native-table specimen grouping behavior.
- Added evaluation-protocol checks for declared identities, groups, holdout axes
  and saved metric evidence, plus explicit handoff-status reporting.
- Added a self-contained synthetic workflow covering three specimens and twelve
  rows without Torch, solver execution or external data.
- Made the Chinese README the primary entry point and added a synchronized English
  introduction and a data-foundation guide. Existing KupferDigital and GH4169
  examples remain documented with their separate data licenses.

The existing `train-surrogate` remains a scalar CPU MLP with its original
train/validation/test interface. New v2 multi-target or train/validation-only
configurations describe data and cannot directly be used with that trainer.
The new demonstration establishes software behavior with synthetic data, not
experimental accuracy, material calibration or numerical convergence.

[Data-foundation guide](docs/data-foundation.md) · [Synthetic example](examples/data_foundation/README.md)

## 0.1.0 — 2026-09-06

Initial GitHub release. A wheel and sdist are available below.

- Multimodal ingestion, unit and source records, validation, solver readiness
  checks, and HDF5/NPZ datasets.
- Native instrument/XLSX blocks, MAT5/HDF5/NPY arrays, Gmsh 2.2 meshes,
  Rodrigues orientations, grain graphs and configured stiffness pairing.
- Abaqus input preparation, execution records and ODB
  field extraction for checked isotropic-elastic, isotropic-plastic and
  explicit UMAT profiles.
- Grouped CPU MLP training with train-only normalization and validation-based
  checkpoint selection; optional PyG export with an explicit graph contract.
- A public CuSn8Ni2 tensile case with twelve real FE cases, 84 completed
  stages and separate FE and experimental holdouts. At 0–0.8% engineering
  strain, MLP/held-out-FE RMSE is 0.682 MPa; FE/MLP against H_18 is
  4.428/4.477 MPa.
- Apache-2.0 project license and CC-BY-4.0 attribution for the public tensile materials.

Python 3.12 or newer is required. `native`, `training` and `ml` extras supply
the corresponding optional dependencies. Solver execution uses the user's
Abaqus installation. The tensile case uses a small-strain uniform gauge model,
with H_08 for calibration, H_16 for model checking and H_18 for final evaluation.

[Release and downloads](https://github.com/koocmitwho/experiment-to-cpfe-pipeline/releases/tag/v0.1.0)
· [Verification](https://github.com/koocmitwho/experiment-to-cpfe-pipeline/blob/v0.1.0/docs/verification/2026-09-06-v0.1.0-release.md)
