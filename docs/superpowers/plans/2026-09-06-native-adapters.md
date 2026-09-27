# Native adapters implementation plan

> Historical design/plan. Retained as a development archive; current operation is described in the v0.2.0 guides. Editorial update: 2026-09-27.

**Goal:** Import the approved representative native layouts with explicit semantics,
source receipts, offline regression and existing container compatibility.

**Architecture:** Extend table selection; add partial native drafts and gated
promotion of typed arrays to the unchanged complete sample contract.

**Tech Stack:** Python 3.12+, NumPy, h5py, Pydantic 2, optional scipy/openpyxl,
existing HDF5 and NPZ exports, pytest.

**Spec:** `docs/superpowers/specs/2026-09-06-native-adapters-design.md`.

The historical implementation used inline execution of the approved scope.

## Global constraints

- Inputs explicitly declare units, coordinates, tensor order, orientation and label correspondence.
- Execution covers local adaptation and offline checks using small synthetic fixtures.
- Existing source configurations retain compatibility. Partial native data stays a draft.
- Local evidence and reports stay under ignored runs. Public examples use relative paths.

## 1. Native table blocks

Files: `config.py`, `adapters/table_blocks.py`, `adapters/tabular.py`,
`tests/unit/test_native_table_blocks.py`, `pyproject.toml`.

- [x] Write failing LIS/XLSX/multirow CSV selection, identity, header and unit tests.
- [x] Run `.venv/Scripts/python.exe -m pytest tests/unit/test_native_table_blocks.py -q`.
- [x] Implement typed block configuration, physical row selection, conversions and receipts.
- [x] Check HDF5/NPZ table provenance and existing table tests.

## 2. Numerical containers and guarded promotion

Files: `adapters/native_models.py`, `native_numeric.py`, `native.py`,
`config.py`, `adapters/tabular.py`, `provenance/binding.py`,
`tests/unit/test_native_numeric.py`, `test_native_imports.py`.

- [x] Test MAT5 struct/cell selection, ragged states, HDF5 slices, class rejection,
  NPY Fortran/component axes and unknown semantic blockers before implementation.
- [x] Implement `read_numeric(path, selector)` and `decode_native(config)` drafts.
- [x] Add explicit semantics and quality/entity/alignment gates, label correspondence
  checks and `promote_native(draft)` conversion receipts.
- [x] Integrate `PipelineConfig.imports`, source binding and canonical round trips.

## 3. Mesh and graph readers

Files: `adapters/native_mesh.py`, `native_graph.py`,
`tests/unit/test_native_mesh_graph.py`.

- [x] Test sparse IDs, mixed-dimensional Gmsh elements, tag/orientation references,
  Rodrigues direction, graph endpoints, self loops, zero nodes and padding.
- [x] Implement `read_mesh(files, options)` and `read_graph(files, options)` returning
  separate typed arrays and detailed source selections.
- [x] Verify raw connectivity and graph-index semantics remain distinct and targets
  retain their evidence, physical quantity and structure-group identity.

## 4. Regression, documentation and acceptance

Files: `docs/native-adapters.md`, README/schema/modalities/limitations,
`docs/verification/2026-09-06-native-adapters.md`; local regression under ignored runs.

- [x] Run configured representative files with current hashes and preserve precise
  read/conversion/complete-sample/readiness/physical status and unresolved evidence.
- [x] Run focused tests, `.venv/Scripts/python.exe -m pytest -q`, dependency check,
  build and installed-wheel check for the offline delivery.
- [x] Inspect canonical/NPZ payloads, diff and public candidates; record actual counts.
- [x] Update checked steps and deliver findings, file links and remaining boundaries.
