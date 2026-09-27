# Validation, CI and documentation repair plan

**Goal:** Validate merged extraction data before export, make CI skips explicit, and update the v0.2.0 operating documentation.

**Architecture:** Retain the existing stage ledger and immutable artifact receipts. Validate the merged `SamplePackage` at the HDF5 boundary; derive NPZ/PyG from that validated canonical artifact. Keep parsing, scientific-data validation and solver-readiness checks as separate responsibilities.

**Tech stack:** Python 3.12, pytest, NumPy, pandas, h5py, Pydantic, CPU Torch/PyG, GitHub Actions.

**Specification:** User task supplied on 2026-09-27, including the request for capability-focused project prose. Work remains in this checkout for review at version 0.2.0. Existing dated verification records receive dated additions. The retry design is a proposal for later review.

## Baseline and evidence

- [x] Locate the v0.2.0 checkout and inspect Git status and the local `.venv`.
- [x] Reproduce `686 passed, 8 skipped` with `python -m pytest -q -rs`.
- [x] Record the CPU Torch baseline and explain any dependency-related difference from the supplied count.
- [x] Save commands and actual outputs in `runs/maintenance-20260927/`, then summarize them in a dated verification record and the Chinese repair report.

## 1. Extraction validation and bundle metadata

Files: `schema/validation.py`, `solvers/abaqus/extraction.py`, `pipeline.py`, new `tests/unit/test_extraction_validation.py`.

- [x] Write and run failing tests for decreasing `frame_time`, post-load NaN, increment reuse across frames, source binding, missing metadata and merged export validation.
- [x] Interpret `frame_time` as step-relative TIME-domain data, including the explicit legacy 0.1 bundle. Check `time` on its own clock; retain `frame_value` in its declared frame domain.
- [x] Keep full field/location/component row identity; require each source/step/load-case/increment ID to identify one frame. Multiple fields and locations in that frame are valid.
- [x] Bind extracted rows to the simulated extraction asset. Validate dynamic value units using the field name, while retaining ordinary tabular mapping checks.
- [x] Validate required metadata explicitly; allow an omitted field-contract version only for extraction version 0.1.
- [x] Save `export-hdf5_validation.json` and its QA report in the export stage, preserving the initial validation report and original receipts.
- [x] Run new tests and all existing extraction, export and validation regressions.

## 2. CLI, configuration and provenance

Files: `cli.py`, `pipeline.py`, `schema/validation.py`, `solvers/abaqus/inp.py`, `provenance/manifest.py`, new `tests/unit/test_stage_hardening.py`.

- [x] Write and run failing tests for command summaries, `--version`, configured export permissions, policy propagation and runtime fingerprints.
- [x] Print a status summary for stage commands and preserve structured data-command output.
- [x] Enforce `export.formats` at export entry, including derived exports.
- [x] Pass the loaded policy through readiness, INP generation and solver preflight.
- [x] Add tool/dependency versions and a deterministic package-source fingerprint. Retain effective solver command receipts; optional solver version/binary probes remain outside this local verification run.
- [x] Run targeted regressions and preserve prior manifest artifact hashes.

## 3. Skip gate and optional dependencies

Files: `tests/conftest.py`, new `tests/unit/test_skip_gate.py`, `tests/unit/test_abaqus_runner.py`, `.github/workflows/tests.yml`.

- [x] Exercise the gate through child pytest processes, including intentional call-time and collection-time skips.
- [x] Permit the two named opt-in integration skips and missing Torch imports in offline jobs. Treat every other skip as a test-run failure.
- [x] Extend the owned-child timeout test to both operating-system paths, keep all existing assertions and verify the Windows path locally; record Linux execution as pending CI.
- [x] Add `-rs --strict-markers`, retain the Ubuntu/Windows matrix and installed-wheel test, and add a CPU ML job that runs the real PyG serialization test.
- [x] Install the ML extra in this repository's `.venv` and execute the PyG test; run Ruff check for an inventory only.

## 4. Documentation and distribution

Files: `NOTICE`, both READMEs, current `docs/*.md`, example READMEs, tracked historical plans/specifications, `CHANGELOG.md`.

- [x] Update the owner and repository in `NOTICE`; inspect both built archives for the retired numeric identifier and required license files.
- [x] Describe v0.2.0 commands, material profiles and data contracts with capabilities, required inputs and outputs. Translate current documentation to English and synchronize the Chinese/English README content.
- [x] Add dated corrections to verification records and the public candidate audit. Mark old plans as historical, remove obsolete publication scaffolding and the unavailable research reference, and distinguish source review from distribution review in the release checklist.
- [x] Keep the source-distribution pruning of historical planning material; review its exclusion through archive inspection.
- [x] Append an Unreleased changelog entry.

## 5. Artifact checksums, retry proposal and final checks

Files: new `scripts/hash_run_artifacts.py`, new `tests/unit/test_hash_run_artifacts.py`, new `docs/retry-design.md`, new dated verification record, Chinese repair report.

- [x] Write and run failing script tests for sorted relative paths, stable SHA-256 output, repeated runs and unchanged input bytes/metadata.
- [x] Implement the checksum command for supplied run directories, excluding its own checksum file and rejecting unsafe symbolic traversal.
- [x] Write the attempt-directory retry proposal with prerequisite verification and preservation of original receipts.
- [x] Run the full strict suite, build wheel/sdist, check metadata, run the installed-wheel verification and inspect package members.
- [x] Review the final diff, original test preservation, version, Git status, documentation wording and evidence files.

Rollback is grouped by these file sets in the final report. The pre-existing untracked publication plan is retained separately from this change.
