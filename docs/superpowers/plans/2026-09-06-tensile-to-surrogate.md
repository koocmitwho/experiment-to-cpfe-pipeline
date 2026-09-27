# Tensile to surrogate implementation plan

> Historical design/plan. Retained as a development archive; current operation is described in the v0.2.0 guides. Editorial update: 2026-09-27.

**Goal:** Execute a public experimental calibration, real FE response generation,
canonical packaging, neural training and held-out evaluation.

**Architecture:** Reuse the existing validated solver/extraction stages and add
small generic mechanics/training modules. Local case configurations bind data,
model assumptions, case splits and actual outputs.

**Spec:** `docs/superpowers/specs/2026-09-06-tensile-to-surrogate-design.md`.

**Execution:** Local implementation and bounded one-CPU solver/training work
under the user's full-workflow request. Preserve the preceding adapter edits.

## Steps

- [x] Test and implement explicit inapplicable orientation, material-region
  assignment and isotropic tabulated plasticity in the existing solver contract.
- [x] Test and implement bilinear calibration, homogeneous gauge configuration,
  reaction/displacement reduction and numeric comparison functions.
- [x] Test and implement case-grouped MLP training, training-only normalization,
  validation checkpoint selection and held-out prediction.
- [x] Prepare three local public curves, inspect the source figure and freeze
  preprocessing, geometry, parameters and splits in a local case manifest.
- [x] Run the calibrated FE case and check its axial response before executing
  the remaining small parameter/sensitivity cases.
- [x] Package real outputs, train the MLP and save all evaluation tables/figures.
- [x] Run focused/full offline tests and the applicable real-run checks, then
  document the actual outcome and the reproducible commands.
