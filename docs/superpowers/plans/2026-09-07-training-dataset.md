# Training data foundation implementation plan

> Historical plan dated 2026-09-07. Editorial update: 2026-09-27. Checked items retain the recorded implementation status. Current operation is described in the [training guide](../../training-datasets.md).

**Goal:** Build traceable scalar-regression bundles from configured canonical samples.
**Architecture:** Separate data selection/alignment/grouping from CPU optimization.
**Stack:** Python 3.12+, NumPy, h5py, Pydantic, PyYAML, pytest and optional CPU Torch.
**Design:** [Original training design](../specs/2026-09-07-training-dataset-design.md).

## Configuration and in-memory construction

Files: `datasets/training_config.py`, `training_columns.py`, `training.py`,
`learning/data_contract.py`, `tests/unit/test_training_dataset.py`.

- [x] Write failing table/array fixtures for column order, unit conversion, row identity and provenance.
- [x] Implement `TrainingDatasetConfig` and `build_training_dataset(config, *, base_dir)` with features, targets, groups, splits, sample IDs, row IDs and metadata.
- [x] Test duplicate identities/content, target-source reuse, group conflicts, invalid types/units and empty selections.
- [x] Share `validate_group_splits` and verify canonical/derived-export compatibility.

## Persistence, CLI and training

Files: `datasets/training.py`, `learning/data_contract.py`, `learning/surrogate.py`,
`cli.py`, `tests/integration/test_training_dataset_pipeline.py`.

- [x] Exercise `build-training-dataset` and `train-surrogate` through the CLI using fresh destinations.
- [x] Write NPZ/JSON, dataset-relative training configuration and build receipts.
- [x] Validate content/quantity contracts and preserve legacy four-array training input.
- [x] Optimize both synthetic layouts on CPU with an 800-epoch ceiling; check loss, mean baseline, test NRMSE < 0.05 and checkpoint readback.

## Examples, documentation and delivery

- [x] Generate two independent layouts through `examples/synthetic_training/prepare.py` and exercise that entry in integration tests.
- [x] Add CPU training CI with explicit dependency import and actual optimization.
- [x] Document configuration, identity/unit/grouping rules and the two NPZ contracts.
- [x] Run the full suite and record actual counts and skips.
- [x] Build wheel/sdist, check metadata and install the candidate outside the source checkout.
- [x] Review the diff and receipts and deliver the local results.

## Recorded review follow-up

- [x] Cover missing-digest source matching in both input orders.
- [x] Preserve full-SamplePackage NPZ training compatibility and enforce new-bundle format metadata.
- [x] Resolve renamed columns through registered `unit_key` while retaining field-unit checks.
- [x] Add seven regression cases: recorded focused result 73 passed; recorded full result 535 passed, 2 skipped.
- [x] Rebuild and recheck the installed wheel: recorded result 1 passed; local evidence directory `runs/training-data-20260907/review-1/`.
